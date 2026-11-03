"""Purchase orders: pharmacies order from suppliers. See app.services.orders
for the workflow rules."""

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.catalogue import get_active_product
from app.api.deps import CurrentUser, DbSession, Pagination, get_org_access
from app.core.config import settings
from app.core.errors import Conflict, NotFound
from app.models import (
    Drug,
    Location,
    Organization,
    Product,
    PurchaseOrder,
    PurchaseOrderItem,
    User,
)
from app.models.enums import OrderStatus, OrganizationType
from app.schemas.common import Page
from app.schemas.orders import (
    AcceptRequest,
    CounterRequest,
    NoteRequest,
    OrderItemCreate,
    OrderItemResponse,
    OrderItemUpdate,
    OrderPartyResponse,
    PriceChange,
    PurchaseOrderCreate,
    PurchaseOrderResponse,
    PurchaseOrderSummary,
    PurchaseOrderUpdate,
    ReasonRequest,
    StatusHistoryResponse,
)
from app.services import orders as svc
from app.services.orders import Action, Side

router = APIRouter()


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------
def _party(db: Session, organization_id: int, location_id: int | None) -> OrderPartyResponse:
    org = db.get(Organization, organization_id)
    location = db.get(Location, location_id) if location_id else None
    return OrderPartyResponse(
        organization_id=org.organization_id,
        name=org.name,
        location_id=location.location_id if location else None,
        location_name=location.name if location else None,
        phone=(location.phone if location and location.phone else org.phone),
        whatsapp_phone=location.whatsapp_phone if location else None,
    )


def _totals(items: list[PurchaseOrderItem]) -> tuple[Decimal, Decimal | None]:
    requested = sum((i.requested_quantity * i.requested_unit_price for i in items), Decimal("0"))
    if items and all(i.confirmed_quantity is not None for i in items):
        confirmed = sum((i.confirmed_quantity * i.confirmed_unit_price for i in items), Decimal("0"))
    else:
        confirmed = None
    return requested, confirmed


def _summary_fields(db: Session, order: PurchaseOrder) -> dict:
    requested, confirmed = _totals(order.items)
    return dict(
        purchase_order_id=order.purchase_order_id,
        status=order.status,
        currency=order.currency,
        pharmacy=_party(db, order.pharmacy_organization_id, order.pharmacy_location_id),
        supplier=_party(db, order.supplier_organization_id, order.supplier_location_id),
        item_count=len(order.items),
        requested_total=requested,
        confirmed_total=confirmed,
        created_at=order.created_at,
        updated_at=order.updated_at,
        submitted_at=order.submitted_at,
        responded_at=order.responded_at,
    )


def order_response(db: Session, order: PurchaseOrder, sides: set[Side]) -> PurchaseOrderResponse:
    db.expire(order)  # reload trigger-maintained columns, items and history
    products = {
        p.product_id: (p, d)
        for p, d in db.execute(
            select(Product, Drug)
            .join(Drug, Drug.drug_id == Product.drug_id)
            .where(Product.product_id.in_([i.product_id for i in order.items]))
        ).all()
    }
    items = []
    for i in order.items:
        product, drug = products[i.product_id]
        items.append(
            OrderItemResponse(
                purchase_order_item_id=i.purchase_order_item_id,
                product_id=i.product_id,
                product_name=product.product_name,
                drug_name=drug.name,
                strength=product.strength,
                dosage_form=product.dosage_form,
                pack_size=product.pack_size,
                requested_quantity=i.requested_quantity,
                requested_unit_price=i.requested_unit_price,
                confirmed_quantity=i.confirmed_quantity,
                confirmed_unit_price=i.confirmed_unit_price,
                requested_line_total=i.requested_quantity * i.requested_unit_price,
                confirmed_line_total=(
                    i.confirmed_quantity * i.confirmed_unit_price
                    if i.confirmed_quantity is not None
                    else None
                ),
            )
        )
    names = dict(
        db.execute(
            select(User.user_id, User.name).where(
                User.user_id.in_([h.changed_by for h in order.history if h.changed_by])
            )
        ).all()
    )
    history = [
        StatusHistoryResponse(
            history_id=h.history_id,
            from_status=h.from_status,
            to_status=h.to_status,
            changed_by=h.changed_by,
            changed_by_name=names.get(h.changed_by),
            changed_at=h.changed_at,
            note=h.note,
        )
        for h in order.history
    ]
    return PurchaseOrderResponse(
        **_summary_fields(db, order),
        notes=order.notes,
        rejection_reason=order.rejection_reason,
        created_by=order.created_by,
        responded_by=order.responded_by,
        status_changed_by=order.status_changed_by,
        items=items,
        history=history,
        allowed_actions=svc.allowed_actions(db, order, sides),
    )


def _act(db: Session, user, order_id: int, action: Action):
    order, sides = svc.load_order(db, user, order_id, for_update=True)
    svc.authorize(db, order, sides, action)
    return order, sides


def _get_item(order: PurchaseOrder, item_id: int) -> PurchaseOrderItem:
    for item in order.items:
        if item.purchase_order_item_id == item_id:
            return item
    raise NotFound("Order item not found.")


# ---------------------------------------------------------------------------
# Create / list / read
# ---------------------------------------------------------------------------
@router.post("", response_model=PurchaseOrderResponse, status_code=status.HTTP_201_CREATED)
def create_order(payload: PurchaseOrderCreate, user: CurrentUser, db: DbSession):
    """Create a draft order. Line prices are the supplier's current listed
    prices (from ``supplier_location_id`` if given, else its lowest)."""
    get_org_access(
        db,
        user,
        payload.pharmacy_organization_id,
        org_type=OrganizationType.PHARMACY,
        require_approved=True,
    )
    svc.get_supplier(db, payload.supplier_organization_id)
    svc.check_location(db, payload.pharmacy_location_id, payload.pharmacy_organization_id, "Pharmacy")
    if payload.supplier_location_id is not None:
        svc.check_location(
            db, payload.supplier_location_id, payload.supplier_organization_id, "Supplier"
        )

    order = PurchaseOrder(
        pharmacy_organization_id=payload.pharmacy_organization_id,
        supplier_organization_id=payload.supplier_organization_id,
        pharmacy_location_id=payload.pharmacy_location_id,
        supplier_location_id=payload.supplier_location_id,
        currency=payload.currency or settings.default_currency,
        notes=payload.notes,
        status=OrderStatus.DRAFT,
        created_by=user.user_id,  # overwritten by the trigger from app.user_id
    )
    db.add(order)
    db.flush()
    for line in payload.items:
        get_active_product(db, line.product_id)
        db.add(
            PurchaseOrderItem(
                purchase_order_id=order.purchase_order_id,
                product_id=line.product_id,
                requested_quantity=line.quantity,
                requested_unit_price=svc.price_for_new_line(db, order, line.product_id),
            )
        )
    db.commit()
    return order_response(db, order, {Side.PHARMACY})


@router.get("", response_model=Page[PurchaseOrderSummary])
def list_orders(
    user: CurrentUser,
    db: DbSession,
    page: Pagination,
    organization_id: Annotated[int, Query(description="Your pharmacy or supplier organization")],
    status_filter: Annotated[list[OrderStatus] | None, Query(alias="status")] = None,
    counterpart_organization_id: int | None = None,
):
    """Orders sent (pharmacy) or received (supplier) by an organization,
    newest first. Suppliers never see drafts."""
    access = get_org_access(db, user, organization_id, allow_admin_read=True)
    limit, offset = page
    is_pharmacy = access.organization.type == OrganizationType.PHARMACY
    own_col = PurchaseOrder.pharmacy_organization_id if is_pharmacy else PurchaseOrder.supplier_organization_id
    other_col = PurchaseOrder.supplier_organization_id if is_pharmacy else PurchaseOrder.pharmacy_organization_id

    stmt = select(PurchaseOrder).where(own_col == organization_id)
    if not is_pharmacy:
        stmt = stmt.where(PurchaseOrder.status != OrderStatus.DRAFT)
    if status_filter:
        stmt = stmt.where(PurchaseOrder.status.in_([s.value for s in status_filter]))
    if counterpart_organization_id is not None:
        stmt = stmt.where(other_col == counterpart_organization_id)

    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    orders = db.scalars(
        stmt.order_by(PurchaseOrder.created_at.desc(), PurchaseOrder.purchase_order_id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return Page(
        items=[PurchaseOrderSummary(**_summary_fields(db, o)) for o in orders],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{purchase_order_id}", response_model=PurchaseOrderResponse)
def get_order(purchase_order_id: int, user: CurrentUser, db: DbSession):
    order, sides = svc.load_order(db, user, purchase_order_id)
    return order_response(db, order, sides)


# ---------------------------------------------------------------------------
# Draft editing (pharmacy)
# ---------------------------------------------------------------------------
@router.patch("/{purchase_order_id}", response_model=PurchaseOrderResponse)
def update_draft(
    purchase_order_id: int, payload: PurchaseOrderUpdate, user: CurrentUser, db: DbSession
):
    """Edit a draft. Changing the supplier warehouse does not reprice existing
    lines; use ``/reprice`` to refresh them."""
    order, sides = _act(db, user, purchase_order_id, Action.EDIT)
    data = payload.model_dump(exclude_unset=True)
    if data.get("pharmacy_location_id") is not None:
        svc.check_location(db, data["pharmacy_location_id"], order.pharmacy_organization_id, "Pharmacy")
        order.pharmacy_location_id = data["pharmacy_location_id"]
    elif "pharmacy_location_id" in data:
        raise Conflict("pharmacy_location_id cannot be null.")
    if "supplier_location_id" in data:
        if data["supplier_location_id"] is not None:
            svc.check_location(
                db, data["supplier_location_id"], order.supplier_organization_id, "Supplier"
            )
        order.supplier_location_id = data["supplier_location_id"]
    if "notes" in data:
        order.notes = data["notes"]
    db.commit()
    return order_response(db, order, sides)


@router.delete("/{purchase_order_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_draft(purchase_order_id: int, user: CurrentUser, db: DbSession):
    """Delete a draft. Submitted orders are cancelled instead, never deleted."""
    order, _ = _act(db, user, purchase_order_id, Action.DELETE)
    db.delete(order)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{purchase_order_id}/items", response_model=PurchaseOrderResponse, status_code=status.HTTP_201_CREATED
)
def add_item(purchase_order_id: int, payload: OrderItemCreate, user: CurrentUser, db: DbSession):
    order, sides = _act(db, user, purchase_order_id, Action.EDIT)
    get_active_product(db, payload.product_id)
    if any(i.product_id == payload.product_id for i in order.items):
        raise Conflict("This product is already on the order; change its quantity instead.")
    db.add(
        PurchaseOrderItem(
            purchase_order_id=order.purchase_order_id,
            product_id=payload.product_id,
            requested_quantity=payload.quantity,
            requested_unit_price=svc.price_for_new_line(db, order, payload.product_id),
        )
    )
    db.commit()
    return order_response(db, order, sides)


@router.patch("/{purchase_order_id}/items/{item_id}", response_model=PurchaseOrderResponse)
def update_item(
    purchase_order_id: int, item_id: int, payload: OrderItemUpdate, user: CurrentUser, db: DbSession
):
    order, sides = _act(db, user, purchase_order_id, Action.EDIT)
    _get_item(order, item_id).requested_quantity = payload.quantity
    db.commit()
    return order_response(db, order, sides)


@router.delete("/{purchase_order_id}/items/{item_id}", response_model=PurchaseOrderResponse)
def remove_item(purchase_order_id: int, item_id: int, user: CurrentUser, db: DbSession):
    order, sides = _act(db, user, purchase_order_id, Action.EDIT)
    db.delete(_get_item(order, item_id))
    db.commit()
    return order_response(db, order, sides)


@router.post("/{purchase_order_id}/reprice", response_model=list[PriceChange])
def reprice_draft(purchase_order_id: int, user: CurrentUser, db: DbSession):
    """Refresh draft line prices to the supplier's current prices. Returns
    what changed."""
    order, _ = _act(db, user, purchase_order_id, Action.EDIT)
    changes = svc.reprice(db, order)
    db.commit()
    return changes


# ---------------------------------------------------------------------------
# Workflow transitions
# ---------------------------------------------------------------------------
@router.post("/{purchase_order_id}/submit", response_model=PurchaseOrderResponse)
def submit_order(
    purchase_order_id: int, user: CurrentUser, db: DbSession, payload: NoteRequest | None = None
):
    """Pharmacy sends the draft to the supplier. Fails with ``price_changes``
    if supplier prices moved since the lines were added."""
    order, sides = _act(db, user, purchase_order_id, Action.SUBMIT)
    svc.submit(db, order, payload.note if payload else None)
    db.commit()
    return order_response(db, order, sides)


@router.post("/{purchase_order_id}/accept", response_model=PurchaseOrderResponse)
def accept_order(
    purchase_order_id: int, user: CurrentUser, db: DbSession, payload: AcceptRequest | None = None
):
    """Supplier accepts the order as requested (optionally choosing the
    fulfilling warehouse)."""
    order, sides = _act(db, user, purchase_order_id, Action.ACCEPT)
    payload = payload or AcceptRequest()
    svc.accept(db, order, payload.supplier_location_id, payload.note)
    db.commit()
    return order_response(db, order, sides)


@router.post("/{purchase_order_id}/counter", response_model=PurchaseOrderResponse)
def counter_order(purchase_order_id: int, payload: CounterRequest, user: CurrentUser, db: DbSession):
    """Supplier proposes different quantities (lower only) and/or prices for
    every line. The pharmacy then accepts the counteroffer or cancels."""
    order, sides = _act(db, user, purchase_order_id, Action.COUNTER)
    svc.counter(db, order, payload.items, payload.note)
    db.commit()
    return order_response(db, order, sides)


@router.post("/{purchase_order_id}/reject", response_model=PurchaseOrderResponse)
def reject_order(purchase_order_id: int, payload: ReasonRequest, user: CurrentUser, db: DbSession):
    order, sides = _act(db, user, purchase_order_id, Action.REJECT)
    svc.reject(db, order, payload.reason)
    db.commit()
    return order_response(db, order, sides)


@router.post("/{purchase_order_id}/accept-counter", response_model=PurchaseOrderResponse)
def accept_counteroffer(
    purchase_order_id: int, user: CurrentUser, db: DbSession, payload: NoteRequest | None = None
):
    """Pharmacy approves the supplier's counteroffer."""
    order, sides = _act(db, user, purchase_order_id, Action.ACCEPT_COUNTER)
    svc.transition(db, order, OrderStatus.ACCEPTED, payload.note if payload else None)
    db.commit()
    return order_response(db, order, sides)


@router.post("/{purchase_order_id}/start-processing", response_model=PurchaseOrderResponse)
def start_processing(
    purchase_order_id: int, user: CurrentUser, db: DbSession, payload: NoteRequest | None = None
):
    order, sides = _act(db, user, purchase_order_id, Action.START_PROCESSING)
    svc.transition(db, order, OrderStatus.PROCESSING, payload.note if payload else None)
    db.commit()
    return order_response(db, order, sides)


@router.post("/{purchase_order_id}/dispatch", response_model=PurchaseOrderResponse)
def dispatch_order(
    purchase_order_id: int, user: CurrentUser, db: DbSession, payload: NoteRequest | None = None
):
    order, sides = _act(db, user, purchase_order_id, Action.DISPATCH)
    svc.transition(db, order, OrderStatus.DISPATCHED, payload.note if payload else None)
    db.commit()
    return order_response(db, order, sides)


@router.post("/{purchase_order_id}/mark-delivered", response_model=PurchaseOrderResponse)
def mark_delivered(
    purchase_order_id: int, user: CurrentUser, db: DbSession, payload: NoteRequest | None = None
):
    """Either side records that the dispatched order arrived."""
    order, sides = _act(db, user, purchase_order_id, Action.MARK_DELIVERED)
    svc.transition(db, order, OrderStatus.DELIVERED, payload.note if payload else None)
    db.commit()
    return order_response(db, order, sides)


@router.post("/{purchase_order_id}/cancel", response_model=PurchaseOrderResponse)
def cancel_order(purchase_order_id: int, payload: ReasonRequest, user: CurrentUser, db: DbSession):
    """Pharmacy: cancel before dispatch (also how a counteroffer is declined).
    Supplier: cancel an accepted/processing order it cannot fulfil."""
    order, sides = _act(db, user, purchase_order_id, Action.CANCEL)
    svc.cancel(db, order, payload.reason)
    db.commit()
    return order_response(db, order, sides)
