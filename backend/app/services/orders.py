"""Purchase-order workflow (application-side rules the schema leaves to us).

Lifecycle::

    draft --submit--> submitted --accept--> accepted --start_processing--> processing
      |                  |  \\--counter--> countered --accept_counter--> accepted
      |                  \\--reject--> rejected       \\--cancel--> cancelled
      \\--cancel / delete                              processing|accepted --dispatch--> dispatched
                                                      dispatched --mark_delivered--> delivered

Who acts:
    pharmacy side: submit, accept_counter, cancel (draft/submitted/countered/accepted), mark_delivered
    supplier side: accept, counter, reject, start_processing, dispatch, mark_delivered,
                   cancel (accepted/processing, e.g. cannot fulfil)

Prices are never taken from the client: each line snapshots the supplier's
current listed price (requested_unit_price). Partial fulfilment is out of MVP
scope: a counteroffer may lower quantities/change prices, and the pharmacy
must approve it before the order is accepted.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.errors import AppError, Conflict, Forbidden, NotFound
from app.models import (
    Location,
    Membership,
    Organization,
    PurchaseOrder,
    PurchaseOrderStatusHistory,
    User,
    supplier_listing,
)
from app.models.enums import OrderStatus, OrganizationStatus, OrganizationType

S = OrderStatus


class Side(StrEnum):
    PHARMACY = "pharmacy"
    SUPPLIER = "supplier"


class Action(StrEnum):
    SUBMIT = "submit"
    ACCEPT = "accept"
    COUNTER = "counter"
    REJECT = "reject"
    ACCEPT_COUNTER = "accept_counter"
    START_PROCESSING = "start_processing"
    DISPATCH = "dispatch"
    MARK_DELIVERED = "mark_delivered"
    CANCEL = "cancel"
    # Draft editing (not status transitions)
    EDIT = "edit"
    DELETE = "delete"


@dataclass(frozen=True)
class Transition:
    from_statuses: frozenset[OrderStatus]
    to_status: OrderStatus | None
    sides: frozenset[Side]


_P = frozenset({Side.PHARMACY})
_S = frozenset({Side.SUPPLIER})
_BOTH = frozenset({Side.PHARMACY, Side.SUPPLIER})

TRANSITIONS: dict[Action, Transition] = {
    Action.SUBMIT: Transition(frozenset({S.DRAFT}), S.SUBMITTED, _P),
    Action.ACCEPT: Transition(frozenset({S.SUBMITTED}), S.ACCEPTED, _S),
    Action.COUNTER: Transition(frozenset({S.SUBMITTED}), S.COUNTERED, _S),
    Action.REJECT: Transition(frozenset({S.SUBMITTED}), S.REJECTED, _S),
    Action.ACCEPT_COUNTER: Transition(frozenset({S.COUNTERED}), S.ACCEPTED, _P),
    Action.START_PROCESSING: Transition(frozenset({S.ACCEPTED}), S.PROCESSING, _S),
    Action.DISPATCH: Transition(frozenset({S.ACCEPTED, S.PROCESSING}), S.DISPATCHED, _S),
    Action.MARK_DELIVERED: Transition(frozenset({S.DISPATCHED}), S.DELIVERED, _BOTH),
    Action.EDIT: Transition(frozenset({S.DRAFT}), None, _P),
    Action.DELETE: Transition(frozenset({S.DRAFT}), None, _P),
}

# Cancellation depends on who cancels.
CANCELLABLE_BY = {
    Side.PHARMACY: frozenset({S.DRAFT, S.SUBMITTED, S.COUNTERED, S.ACCEPTED}),
    Side.SUPPLIER: frozenset({S.ACCEPTED, S.PROCESSING}),
}


# ---------------------------------------------------------------------------
# Access
# ---------------------------------------------------------------------------
def user_sides(db: Session, user: User, order: PurchaseOrder) -> set[Side]:
    """The sides of the order the user acts for (normally exactly one)."""
    org_ids = set(
        db.scalars(
            select(Membership.organization_id).where(
                Membership.user_id == user.user_id,
                Membership.is_active.is_(True),
                Membership.organization_id.in_(
                    [order.pharmacy_organization_id, order.supplier_organization_id]
                ),
            )
        )
    )
    sides = set()
    if order.pharmacy_organization_id in org_ids:
        sides.add(Side.PHARMACY)
    # Suppliers never see a pharmacy's unsent drafts.
    if order.supplier_organization_id in org_ids and order.status != S.DRAFT:
        sides.add(Side.SUPPLIER)
    return sides


def load_order(db: Session, user: User, order_id: int, *, for_update: bool = False):
    stmt = select(PurchaseOrder).where(PurchaseOrder.purchase_order_id == order_id)
    if for_update:
        stmt = stmt.with_for_update()
    order = db.scalar(stmt.execution_options(populate_existing=True))
    if order is None:
        raise NotFound("Purchase order not found.")
    sides = user_sides(db, user, order)
    if not sides and not user.is_platform_admin:
        raise NotFound("Purchase order not found.")
    return order, sides


def allowed_actions(db: Session, order: PurchaseOrder, sides: set[Side]) -> list[str]:
    status = OrderStatus(order.status)
    actions = [
        action.value
        for action, t in TRANSITIONS.items()
        if status in t.from_statuses and sides & t.sides
    ]
    if any(status in CANCELLABLE_BY[side] for side in sides):
        actions.append(Action.CANCEL.value)
    return actions


def _org_status(db: Session, organization_id: int) -> str:
    return db.scalar(
        select(Organization.status).where(Organization.organization_id == organization_id)
    )


def authorize(db: Session, order: PurchaseOrder, sides: set[Side], action: Action) -> Side:
    """Check the action is valid now and the user may perform it. Returns the
    side the user acts as."""
    status = OrderStatus(order.status)
    if action == Action.CANCEL:
        acting = [side for side in sides if status in CANCELLABLE_BY[side]]
        if not acting:
            raise Conflict(f"This order cannot be cancelled by you while it is '{status}'.")
        side = acting[0]
    else:
        t = TRANSITIONS[action]
        permitted = sides & t.sides
        if not permitted:
            who = " or ".join(sorted(s.value for s in t.sides))
            raise Forbidden(f"Only the {who} can {action.value.replace('_', ' ')} this order.")
        if status not in t.from_statuses:
            raise Conflict(f"Cannot {action.value.replace('_', ' ')} an order that is '{status}'.")
        side = Side.PHARMACY if Side.PHARMACY in permitted else Side.SUPPLIER

    # Approved organizations only; cancelling stays possible so a suspended
    # counterpart never leaves an order stuck.
    if action != Action.CANCEL:
        org_id = order.pharmacy_organization_id if side == Side.PHARMACY else order.supplier_organization_id
        if _org_status(db, org_id) != OrganizationStatus.APPROVED:
            raise Forbidden("Your organization must be approved to work on purchase orders.")
    return side


# ---------------------------------------------------------------------------
# Prices and locations
# ---------------------------------------------------------------------------
def current_supplier_price(
    db: Session,
    supplier_organization_id: int,
    supplier_location_id: int | None,
    product_id: int,
    currency: str,
) -> Decimal | None:
    """The supplier's listed price for the product: at the chosen warehouse,
    or the lowest across its warehouses. Only approved suppliers, active
    locations and listed, active products count (the supplier_listing view)."""
    sl = supplier_listing.c
    stmt = select(func.min(sl.unit_price)).where(
        sl.supplier_organization_id == supplier_organization_id,
        sl.product_id == product_id,
        sl.currency == currency,
    )
    if supplier_location_id is not None:
        stmt = stmt.where(sl.supplier_location_id == supplier_location_id)
    return db.scalar(stmt)


def price_for_new_line(db: Session, order: PurchaseOrder, product_id: int) -> Decimal:
    price = current_supplier_price(
        db, order.supplier_organization_id, order.supplier_location_id, product_id, order.currency
    )
    if price is None:
        where = "at the selected warehouse" if order.supplier_location_id else ""
        raise Conflict(
            f"The supplier does not currently list product {product_id} {where} in {order.currency}.".replace(
                "  ", " "
            )
        )
    return price


def check_location(
    db: Session, location_id: int, organization_id: int, label: str
) -> Location:
    location = db.get(Location, location_id)
    if location is None or location.organization_id != organization_id:
        raise NotFound(f"{label} location not found for that organization.")
    if not location.is_active:
        raise Conflict(f"{label} location is deactivated.")
    return location


def get_supplier(db: Session, supplier_organization_id: int) -> Organization:
    supplier = db.get(Organization, supplier_organization_id)
    if (
        supplier is None
        or supplier.type != OrganizationType.SUPPLIER
        or supplier.status != OrganizationStatus.APPROVED
    ):
        raise NotFound("Supplier not found.")
    return supplier


def price_changes(db: Session, order: PurchaseOrder) -> list[dict]:
    changes = []
    for item in order.items:
        current = current_supplier_price(
            db, order.supplier_organization_id, order.supplier_location_id, item.product_id, order.currency
        )
        if current != item.requested_unit_price:
            changes.append(
                {
                    "purchase_order_item_id": item.purchase_order_item_id,
                    "product_id": item.product_id,
                    "previous_unit_price": str(item.requested_unit_price),
                    "current_unit_price": str(current) if current is not None else None,
                }
            )
    return changes


# ---------------------------------------------------------------------------
# Transitions
# ---------------------------------------------------------------------------
def transition(db: Session, order: PurchaseOrder, to_status: OrderStatus, note: str | None) -> None:
    """Change status; the trigger writes history and stamps actor/timestamps."""
    order.status = to_status
    db.flush()
    if note:
        latest = (
            select(func.max(PurchaseOrderStatusHistory.history_id))
            .where(PurchaseOrderStatusHistory.purchase_order_id == order.purchase_order_id)
            .scalar_subquery()
        )
        db.execute(
            update(PurchaseOrderStatusHistory)
            .where(PurchaseOrderStatusHistory.history_id == latest)
            .values(note=note)
        )


def submit(db: Session, order: PurchaseOrder, note: str | None) -> None:
    if not order.items:
        raise Conflict("Add at least one item before submitting the order.")
    if _org_status(db, order.supplier_organization_id) != OrganizationStatus.APPROVED:
        raise Conflict("The supplier is not currently approved on ApexRx.")
    check_location(db, order.pharmacy_location_id, order.pharmacy_organization_id, "Pharmacy")
    if order.supplier_location_id is not None:
        check_location(db, order.supplier_location_id, order.supplier_organization_id, "Supplier")
    changes = price_changes(db, order)
    if changes:
        raise Conflict(
            "Supplier prices changed since the items were added. Review them with "
            "POST /purchase-orders/{id}/reprice, then submit again.",
            extra={"price_changes": changes},
        )
    transition(db, order, S.SUBMITTED, note)


def reprice(db: Session, order: PurchaseOrder) -> list[dict]:
    changes = price_changes(db, order)
    unavailable = [c for c in changes if c["current_unit_price"] is None]
    if unavailable:
        raise Conflict(
            "Some products are no longer listed by the supplier; remove them first.",
            extra={"price_changes": unavailable},
        )
    by_id = {item.purchase_order_item_id: item for item in order.items}
    for change in changes:
        by_id[change["purchase_order_item_id"]].requested_unit_price = Decimal(change["current_unit_price"])
    db.flush()
    return changes


def accept(db: Session, order: PurchaseOrder, supplier_location_id: int | None, note: str | None) -> None:
    if supplier_location_id is not None:
        check_location(db, supplier_location_id, order.supplier_organization_id, "Supplier")
        order.supplier_location_id = supplier_location_id
    for item in order.items:
        item.confirmed_quantity = item.requested_quantity
        item.confirmed_unit_price = item.requested_unit_price
    transition(db, order, S.ACCEPTED, note)


def counter(db: Session, order: PurchaseOrder, lines: list, note: str | None) -> None:
    by_id = {item.purchase_order_item_id: item for item in order.items}
    given = {line.purchase_order_item_id for line in lines}
    if len(given) != len(lines):
        raise AppError("Each order item may appear only once in a counteroffer.")
    if given != set(by_id):
        raise AppError("A counteroffer must give confirmed values for every item on the order.")
    changed = False
    for line in lines:
        item = by_id[line.purchase_order_item_id]
        if line.confirmed_quantity > item.requested_quantity:
            raise AppError(
                f"Item {item.purchase_order_item_id}: confirmed quantity cannot exceed the requested "
                f"{item.requested_quantity} (partial fulfilment only lowers quantities)."
            )
        changed |= (
            line.confirmed_quantity != item.requested_quantity
            or line.confirmed_unit_price != item.requested_unit_price
        )
        item.confirmed_quantity = line.confirmed_quantity
        item.confirmed_unit_price = line.confirmed_unit_price
    if not changed:
        raise AppError("The counteroffer matches the request exactly; accept the order instead.")
    transition(db, order, S.COUNTERED, note)


def reject(db: Session, order: PurchaseOrder, reason: str) -> None:
    order.rejection_reason = reason
    transition(db, order, S.REJECTED, reason)


def cancel(db: Session, order: PurchaseOrder, reason: str) -> None:
    transition(db, order, S.CANCELLED, reason)
