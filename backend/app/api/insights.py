"""Dashboard insights: the charts and management figures on the pharmacy and
supplier overviews (stock health, order pipeline, open order value, most
requested medicines).

Owners and managers only. Staff keep the operational routes they work with
(inventory, orders), but these aggregates are refused to them with 403, so
hiding the charts in the browser is not the only protection.
"""

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import case, func, select

from app.api.deps import MANAGERS, CurrentUser, DbSession, get_org_access, get_org_location
from app.api.orders import _totals
from app.models import Drug, Location, Product, ProductOffer, PurchaseOrder, PurchaseOrderItem, Stock
from app.models.enums import OrderStatus, OrganizationType
from app.schemas.insights import DashboardInsights, StockHealth, TopProduct

router = APIRouter()

# Orders still moving between the two sides; their value is "open".
OPEN_STATUSES = (
    OrderStatus.SUBMITTED,
    OrderStatus.COUNTERED,
    OrderStatus.ACCEPTED,
    OrderStatus.PROCESSING,
    OrderStatus.DISPATCHED,
)
# Same default as product_offer.low_stock_threshold, for stock with no offer yet.
DEFAULT_LOW_STOCK_THRESHOLD = 5
# "Most requested" looks at the latest orders, as the overview always has.
TOP_REQUESTED_ORDERS = 15
TOP_REQUESTED_LIMIT = 5


@router.get("/{organization_id}/insights", response_model=DashboardInsights)
def dashboard_insights(
    organization_id: int,
    user: CurrentUser,
    db: DbSession,
    location_id: Annotated[
        int | None, Query(description="Stock health for one location; all locations when omitted")
    ] = None,
):
    """Overview charts and management figures. Owners and managers only:
    staff get 403, non-members 404."""
    access = get_org_access(db, user, organization_id, roles=MANAGERS)
    if location_id is not None:
        get_org_location(db, organization_id, location_id)

    # Stock health
    threshold = func.coalesce(ProductOffer.low_stock_threshold, DEFAULT_LOW_STOCK_THRESHOLD)
    level = case(
        (Stock.quantity <= 0, "out"),
        (Stock.quantity <= threshold, "low"),
        else_="in",
    )
    stmt = (
        select(level, func.count())
        .select_from(Stock)
        .join(Location, Location.location_id == Stock.location_id)
        .outerjoin(
            ProductOffer,
            (ProductOffer.location_id == Stock.location_id) & (ProductOffer.product_id == Stock.product_id),
        )
        .where(Location.organization_id == organization_id)
        .group_by(level)
    )
    if location_id is not None:
        stmt = stmt.where(Stock.location_id == location_id)
    levels = dict(db.execute(stmt).all())
    health = StockHealth(
        in_stock=levels.get("in", 0),
        low_stock=levels.get("low", 0),
        out_of_stock=levels.get("out", 0),
        total=sum(levels.values()),
    )

    # Orders: the same set the orders list shows (suppliers never see drafts).
    is_pharmacy = access.organization.type == OrganizationType.PHARMACY
    own_col = PurchaseOrder.pharmacy_organization_id if is_pharmacy else PurchaseOrder.supplier_organization_id
    visible = [own_col == organization_id]
    if not is_pharmacy:
        visible.append(PurchaseOrder.status != OrderStatus.DRAFT)

    counts = dict(
        db.execute(
            select(PurchaseOrder.status, func.count()).where(*visible).group_by(PurchaseOrder.status)
        ).all()
    )
    pipeline = {s.value: int(counts.get(s.value, 0)) for s in OrderStatus if is_pharmacy or s != OrderStatus.DRAFT}

    open_orders = db.scalars(
        select(PurchaseOrder).where(*visible, PurchaseOrder.status.in_([s.value for s in OPEN_STATUSES]))
    ).all()
    open_value = Decimal("0")
    currencies = set()
    for order in open_orders:
        requested, confirmed = _totals(order.items)
        open_value += confirmed if confirmed is not None else requested
        currencies.add(order.currency)

    # Most requested medicines in the latest non-draft orders.
    recent = (
        select(PurchaseOrder.purchase_order_id)
        .where(*visible, PurchaseOrder.status != OrderStatus.DRAFT)
        .order_by(PurchaseOrder.created_at.desc(), PurchaseOrder.purchase_order_id.desc())
        .limit(TOP_REQUESTED_ORDERS)
        .subquery()
    )
    boxes = func.sum(func.coalesce(PurchaseOrderItem.confirmed_quantity, PurchaseOrderItem.requested_quantity))
    top = db.execute(
        select(Product.product_id, Product.product_name, Drug.name, Product.strength, Product.pack_size, boxes)
        .join(PurchaseOrderItem, PurchaseOrderItem.product_id == Product.product_id)
        .join(Drug, Drug.drug_id == Product.drug_id)
        .where(PurchaseOrderItem.purchase_order_id.in_(select(recent.c.purchase_order_id)))
        .group_by(Product.product_id, Product.product_name, Drug.name, Product.strength, Product.pack_size)
        .order_by(boxes.desc(), Product.product_name)
        .limit(TOP_REQUESTED_LIMIT)
    ).all()

    return DashboardInsights(
        organization_id=organization_id,
        location_id=location_id,
        stock_health=health,
        order_pipeline=pipeline,
        open_order_value=open_value,
        currency=currencies.pop() if len(currencies) == 1 else "RWF",
        top_requested=[
            TopProduct(product_id=r[0], product_name=r[1], drug_name=r[2], strength=r[3], pack_size=r[4], quantity=int(r[5]))
            for r in top
        ],
    )
