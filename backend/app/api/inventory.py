"""Stock and offers for an organization's locations (manual MVP inventory).

* Stock = quantity on hand, per location and catalogue product.
* Offer = the location lists that product at a price. Pharmacies' offers are
  visible to patients (availability status only); suppliers' offers are
  visible to pharmacies (with exact quantity).

The database stamps updated_by / last_updated and writes the stock_adjustment
audit trail; this module only decides who may write what.
"""

from typing import Annotated

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.api.catalogue import contains, get_active_product
from app.api.deps import (
    ALL_ROLES,
    MANAGERS,
    CurrentUser,
    DbSession,
    Pagination,
    get_org_access,
    get_org_location,
)
from app.core.config import settings
from app.core.errors import Conflict, NotFound
from app.models import (
    Drug,
    Location,
    Product,
    ProductOffer,
    Stock,
    StockAdjustment,
    User,
)
from app.models.enums import AvailabilityStatus
from app.schemas.common import Message, Page
from app.schemas.inventory import (
    InventoryItem,
    OfferResponse,
    OfferUpsert,
    StockAdjustmentResponse,
    StockUpsert,
)

router = APIRouter()


def availability_for(quantity: int, offer: ProductOffer | None) -> AvailabilityStatus | None:
    """Same rule as the patient_availability view."""
    if offer is None or not offer.is_listed:
        return None
    if quantity <= 0:
        return AvailabilityStatus.UNAVAILABLE
    if quantity <= offer.low_stock_threshold:
        return AvailabilityStatus.LOW_STOCK
    return AvailabilityStatus.IN_STOCK


def _inventory_item(
    stock: Stock, offer: ProductOffer | None, product: Product, drug: Drug, location: Location
) -> InventoryItem:
    return InventoryItem(
        stock_id=stock.stock_id,
        location_id=location.location_id,
        location_name=location.name,
        product_id=product.product_id,
        product_name=product.product_name,
        drug_id=drug.drug_id,
        drug_name=drug.name,
        brand=product.brand,
        strength=product.strength,
        dosage_form=product.dosage_form,
        pack_size=product.pack_size,
        quantity=stock.quantity,
        last_updated=stock.last_updated,
        updated_by=stock.updated_by,
        offer=(
            OfferResponse(
                offer_id=offer.offer_id,
                unit_price=offer.unit_price,
                currency=offer.currency,
                low_stock_threshold=offer.low_stock_threshold,
                is_listed=offer.is_listed,
                last_updated=offer.last_updated,
                updated_by=offer.updated_by,
            )
            if offer
            else None
        ),
        availability_status=availability_for(stock.quantity, offer),
    )


def _inventory_query():
    return (
        select(Stock, ProductOffer, Product, Drug, Location)
        .join(Location, Location.location_id == Stock.location_id)
        .join(Product, Product.product_id == Stock.product_id)
        .join(Drug, Drug.drug_id == Product.drug_id)
        .outerjoin(
            ProductOffer,
            (ProductOffer.location_id == Stock.location_id)
            & (ProductOffer.product_id == Stock.product_id),
        )
    )


def _load_item(db: Session, location_id: int, product_id: int) -> InventoryItem:
    row = db.execute(
        _inventory_query()
        .where(Stock.location_id == location_id, Stock.product_id == product_id)
        .execution_options(populate_existing=True)
    ).one_or_none()
    if row is None:
        raise NotFound("This product has no stock record at this location.")
    return _inventory_item(*row)


def _writable_location(
    db: Session, user: User, organization_id: int, location_id: int, roles=ALL_ROLES
) -> Location:
    get_org_access(db, user, organization_id, roles=roles, require_approved=True)
    return get_org_location(db, organization_id, location_id, require_active=True)


def _get_stock(db: Session, location_id: int, product_id: int) -> Stock:
    stock = db.scalar(
        select(Stock).where(Stock.location_id == location_id, Stock.product_id == product_id)
    )
    if stock is None:
        raise NotFound("This product has no stock record at this location.")
    return stock


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------
@router.get("/{organization_id}/inventory", response_model=Page[InventoryItem])
def list_inventory(
    organization_id: int,
    user: CurrentUser,
    db: DbSession,
    page: Pagination,
    location_id: int | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    availability: Annotated[
        AvailabilityStatus | None, Query(description="Only listed items with this status")
    ] = None,
    listed: bool | None = None,
):
    """Stock and offers across the organization's locations."""
    get_org_access(db, user, organization_id, allow_admin_read=True)
    limit, offset = page
    stmt = _inventory_query().where(Location.organization_id == organization_id)
    if location_id is not None:
        stmt = stmt.where(Stock.location_id == location_id)
    if q and q.strip():
        pattern = contains(q)
        stmt = stmt.where(
            or_(Product.product_name.ilike(pattern), Product.brand.ilike(pattern), Drug.name.ilike(pattern))
        )
    if listed is True:
        stmt = stmt.where(ProductOffer.is_listed.is_(True))
    elif listed is False:
        stmt = stmt.where(or_(ProductOffer.offer_id.is_(None), ProductOffer.is_listed.is_(False)))
    if availability is not None:
        stmt = stmt.where(ProductOffer.is_listed.is_(True))
        if availability == AvailabilityStatus.UNAVAILABLE:
            stmt = stmt.where(Stock.quantity <= 0)
        elif availability == AvailabilityStatus.LOW_STOCK:
            stmt = stmt.where(Stock.quantity > 0, Stock.quantity <= ProductOffer.low_stock_threshold)
        else:
            stmt = stmt.where(Stock.quantity > ProductOffer.low_stock_threshold)

    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.execute(
        stmt.order_by(Location.name, Drug.name, Product.product_name, Stock.stock_id)
        .limit(limit)
        .offset(offset)
    ).all()
    return Page(items=[_inventory_item(*row) for row in rows], total=total, limit=limit, offset=offset)


@router.get(
    "/{organization_id}/locations/{location_id}/stock/{product_id}", response_model=InventoryItem
)
def get_stock_item(
    organization_id: int, location_id: int, product_id: int, user: CurrentUser, db: DbSession
):
    get_org_access(db, user, organization_id, allow_admin_read=True)
    get_org_location(db, organization_id, location_id)
    return _load_item(db, location_id, product_id)


@router.get(
    "/{organization_id}/locations/{location_id}/stock/{product_id}/adjustments",
    response_model=Page[StockAdjustmentResponse],
)
def list_stock_adjustments(
    organization_id: int,
    location_id: int,
    product_id: int,
    user: CurrentUser,
    db: DbSession,
    page: Pagination,
):
    """Audit trail of quantity changes (including deletions) for one product."""
    get_org_access(db, user, organization_id, allow_admin_read=True)
    get_org_location(db, organization_id, location_id)
    limit, offset = page
    stmt = (
        select(StockAdjustment, User.name)
        .outerjoin(User, User.user_id == StockAdjustment.changed_by)
        .where(StockAdjustment.location_id == location_id, StockAdjustment.product_id == product_id)
    )
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.execute(
        stmt.order_by(StockAdjustment.changed_at.desc(), StockAdjustment.adjustment_id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    items = [
        StockAdjustmentResponse(
            adjustment_id=a.adjustment_id,
            location_id=a.location_id,
            product_id=a.product_id,
            old_quantity=a.old_quantity,
            new_quantity=a.new_quantity,
            change_type=a.change_type,
            changed_by=a.changed_by,
            changed_by_name=name,
            changed_at=a.changed_at,
        )
        for a, name in rows
    ]
    return Page(items=items, total=total, limit=limit, offset=offset)


# ---------------------------------------------------------------------------
# Stock writes (any member role)
# ---------------------------------------------------------------------------
@router.put(
    "/{organization_id}/locations/{location_id}/stock/{product_id}", response_model=InventoryItem
)
def upsert_stock(
    organization_id: int,
    location_id: int,
    product_id: int,
    payload: StockUpsert,
    user: CurrentUser,
    db: DbSession,
):
    """Record the quantity on hand. Saving an unchanged quantity confirms it is
    still accurate (refreshes ``last_updated``)."""
    _writable_location(db, user, organization_id, location_id)
    get_active_product(db, product_id)
    # Always issue an UPDATE for an existing row, even if the quantity is
    # unchanged, so the trigger refreshes last_updated ("still accurate").
    result = db.execute(
        update(Stock)
        .where(Stock.location_id == location_id, Stock.product_id == product_id)
        .values(quantity=payload.quantity)
    )
    if result.rowcount == 0:
        db.add(Stock(location_id=location_id, product_id=product_id, quantity=payload.quantity))
    db.commit()
    return _load_item(db, location_id, product_id)


@router.post(
    "/{organization_id}/locations/{location_id}/stock/confirm",
    response_model=Message,
)
def confirm_location_stock(
    organization_id: int, location_id: int, user: CurrentUser, db: DbSession
):
    """Confirm every stock record at the location is still accurate."""
    _writable_location(db, user, organization_id, location_id)
    result = db.execute(
        update(Stock).where(Stock.location_id == location_id).values(quantity=Stock.quantity)
    )
    db.commit()
    return Message(detail=f"Confirmed {result.rowcount} stock records.")


@router.delete(
    "/{organization_id}/locations/{location_id}/stock/{product_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_stock(
    organization_id: int, location_id: int, product_id: int, user: CurrentUser, db: DbSession
):
    """Stop tracking a product at this location. Also removes its offer. The
    deletion is recorded in the audit trail."""
    _writable_location(db, user, organization_id, location_id, roles=MANAGERS)
    db.delete(_get_stock(db, location_id, product_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Offer writes (owners and managers set prices)
# ---------------------------------------------------------------------------
@router.put(
    "/{organization_id}/locations/{location_id}/stock/{product_id}/offer",
    response_model=InventoryItem,
)
def upsert_offer(
    organization_id: int,
    location_id: int,
    product_id: int,
    payload: OfferUpsert,
    user: CurrentUser,
    db: DbSession,
):
    """Set the selling price and publish (``is_listed``) the product. Requires
    a stock record first; availability is always derived from stock."""
    _writable_location(db, user, organization_id, location_id, roles=MANAGERS)
    get_active_product(db, product_id)
    _get_stock(db, location_id, product_id)

    values = {
        "unit_price": payload.unit_price,
        "currency": payload.currency or settings.default_currency,
        "low_stock_threshold": payload.low_stock_threshold,
        "is_listed": payload.is_listed,
    }
    result = db.execute(
        update(ProductOffer)
        .where(ProductOffer.location_id == location_id, ProductOffer.product_id == product_id)
        .values(**values)
    )
    if result.rowcount == 0:
        db.add(ProductOffer(location_id=location_id, product_id=product_id, **values))
    db.commit()
    return _load_item(db, location_id, product_id)


@router.delete(
    "/{organization_id}/locations/{location_id}/stock/{product_id}/offer",
    response_model=InventoryItem,
)
def delete_offer(
    organization_id: int, location_id: int, product_id: int, user: CurrentUser, db: DbSession
):
    """Remove the price/listing; the stock record stays. To hide a product
    temporarily, set ``is_listed: false`` instead."""
    _writable_location(db, user, organization_id, location_id, roles=MANAGERS)
    offer = db.scalar(
        select(ProductOffer).where(
            ProductOffer.location_id == location_id, ProductOffer.product_id == product_id
        )
    )
    if offer is None:
        raise Conflict("This product has no offer at this location.")
    db.delete(offer)
    db.commit()
    return _load_item(db, location_id, product_id)
