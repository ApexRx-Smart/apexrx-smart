"""Procurement requests and quotations (application-side rules).

A pharmacy asks one supplier for prices on several medicines. Each item is a
catalogue product or a free-text description, so the supplier does not need
to list it and the central catalogue is never changed. The supplier answers
with a quotation; the pharmacy accepts it, rejects it or asks for a revision.
An accepted quotation becomes a supplier order only when the pharmacy
converts it, through the existing purchase-order workflow.

Request lifecycle::

    submitted --(supplier opens)--> viewed
    submitted|viewed|negotiation|quoted --(supplier sends a quotation)--> quoted
    quoted --(pharmacy asks for a revision)--> negotiation
    quoted --(pharmacy accepts)--> accepted --(pharmacy converts)--> converted
    quoted --(pharmacy rejects)--> rejected
    submitted|viewed|negotiation --(supplier declines)--> rejected
    any open status --(pharmacy cancels)--> cancelled

Quotation lifecycle::

    draft --> submitted --> accepted | rejected | revision_requested
    submitted|revision_requested --(a newer revision is sent)--> superseded

A sent quotation is never edited (trigger quotation_item_guard); each
revision is a new row, so the negotiation history stays readable.

Who acts (same split as purchase orders): on the pharmacy side, committing or
withdrawing (accept, reject, cancel, convert) is for owners and managers;
staff can create requests and ask for revisions. On the supplier side every
role can quote and decline, as with counteroffers on orders.
"""

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.errors import AppError, Conflict, Forbidden, NotFound
from app.models import (
    Membership,
    ProcurementRequest,
    ProcurementRequestItem,
    PurchaseOrder,
    PurchaseOrderItem,
    Quotation,
    QuotationItem,
    User,
)
from app.models.enums import MembershipRole, OrderStatus
from app.services import messaging
from app.services import orders as order_svc


class RequestStatus(StrEnum):
    SUBMITTED = "submitted"
    VIEWED = "viewed"
    QUOTED = "quoted"
    NEGOTIATION = "negotiation"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    CONVERTED = "converted"


class QuotationStatus(StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    REVISION_REQUESTED = "revision_requested"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


R, Q = RequestStatus, QuotationStatus
OPEN = frozenset({R.SUBMITTED, R.VIEWED, R.QUOTED, R.NEGOTIATION})
QUOTABLE = frozenset({R.SUBMITTED, R.VIEWED, R.QUOTED, R.NEGOTIATION})
DECLINABLE = frozenset({R.SUBMITTED, R.VIEWED, R.NEGOTIATION})
CANCELLABLE = frozenset({R.SUBMITTED, R.VIEWED, R.QUOTED, R.NEGOTIATION, R.ACCEPTED})
MANAGERS = frozenset({MembershipRole.OWNER, MembershipRole.MANAGER})
PHARMACY_MANAGER_ACTIONS = frozenset({"accept", "reject", "cancel", "convert"})


def now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# Access
# ---------------------------------------------------------------------------
def load_request(db: Session, user: User, request_id: int, *, for_update: bool = False):
    """The request and the side the user acts for ('pharmacy' or 'supplier').
    404 for anyone outside the two organizations."""
    stmt = select(ProcurementRequest).where(ProcurementRequest.procurement_request_id == request_id)
    if for_update:
        stmt = stmt.with_for_update()
    req = db.scalar(stmt.execution_options(populate_existing=True))
    if req is None:
        raise NotFound("Procurement request not found.")
    mine = messaging.member_org_ids(db, user, [req.pharmacy_organization_id, req.supplier_organization_id])
    if not mine:
        raise NotFound("Procurement request not found.")
    side = "pharmacy" if req.pharmacy_organization_id in mine else "supplier"
    return req, side


def role_in(db: Session, user: User, organization_id: int) -> MembershipRole | None:
    role = db.scalar(
        select(Membership.role).where(
            Membership.user_id == user.user_id,
            Membership.organization_id == organization_id,
            Membership.is_active.is_(True),
        )
    )
    return MembershipRole(role) if role else None


def own_org(req: ProcurementRequest, side: str) -> int:
    return req.pharmacy_organization_id if side == "pharmacy" else req.supplier_organization_id


def other_org(req: ProcurementRequest, side: str) -> int:
    return req.supplier_organization_id if side == "pharmacy" else req.pharmacy_organization_id


def require(side: str, wanted: str, action: str) -> None:
    if side != wanted:
        raise Forbidden(f"Only the {wanted} can {action} on this request.")


def require_manager(db: Session, user: User, req: ProcurementRequest, action: str) -> None:
    if role_in(db, user, req.pharmacy_organization_id) not in MANAGERS:
        raise Forbidden(f"Only pharmacy owners and managers can {action}.")


def latest(req: ProcurementRequest, *statuses: QuotationStatus) -> Quotation | None:
    found = [q for q in req.quotations if q.status in statuses]
    return found[-1] if found else None


def allowed_actions(db: Session, user: User, req: ProcurementRequest, side: str) -> list[str]:
    status = RequestStatus(req.status)
    actions: list[str] = []
    if side == "supplier":
        if status in QUOTABLE:
            actions.append("quote")
        if status in DECLINABLE:
            actions.append("decline")
    else:
        manager = role_in(db, user, req.pharmacy_organization_id) in MANAGERS
        if status == R.QUOTED and latest(req, Q.SUBMITTED):
            actions.append("request_revision")
            if manager:
                actions += ["accept", "reject"]
        if status == R.ACCEPTED and manager:
            actions.append("convert")
        if status in CANCELLABLE and manager:
            actions.append("cancel")
    return actions


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------
def add_items(db: Session, req: ProcurementRequest, lines: list, products: dict) -> None:
    for n, line in enumerate(lines, start=1):
        product = products.get(line.product_id) if line.product_id else None
        if product is not None:
            # Catalogue items take their description from the catalogue, not the client.
            name, strength, form, pack = product.product_name, product.strength, product.dosage_form, product.pack_size
        else:
            name, strength, form, pack = line.medicine_name, line.strength, line.dosage_form, line.pack_size
        db.add(
            ProcurementRequestItem(
                procurement_request_id=req.procurement_request_id,
                line_no=n,
                product_id=product.product_id if product is not None else None,
                medicine_name=name,
                strength=strength,
                dosage_form=form,
                pack_size=pack,
                quantity=line.quantity,
                notes=line.notes,
            )
        )


def mark_viewed(db: Session, req: ProcurementRequest) -> None:
    if req.viewed_at is None:
        req.viewed_at = now()
    if req.status == R.SUBMITTED:
        req.status = R.VIEWED
        req.updated_at = now()


def decline(db: Session, req: ProcurementRequest, reason: str) -> None:
    if req.status not in DECLINABLE:
        raise Conflict(f"A request that is '{req.status}' cannot be declined.")
    draft = latest(req, Q.DRAFT)
    if draft is not None:
        db.delete(draft)
    _set_status(req, R.REJECTED, reason)
    messaging.notify(db, req.pharmacy_organization_id, "request_declined", req.supplier_organization_id,
                     procurement_request_id=req.procurement_request_id)


def cancel(db: Session, req: ProcurementRequest, reason: str) -> None:
    if req.status not in CANCELLABLE:
        raise Conflict(f"A request that is '{req.status}' cannot be cancelled.")
    _set_status(req, R.CANCELLED, reason)
    messaging.notify(db, req.supplier_organization_id, "request_cancelled", req.pharmacy_organization_id,
                     procurement_request_id=req.procurement_request_id)


def _set_status(req: ProcurementRequest, status: RequestStatus, reason: str | None = None) -> None:
    req.status = status
    req.updated_at = now()
    if reason is not None:
        req.status_reason = reason


# ---------------------------------------------------------------------------
# Quotations
# ---------------------------------------------------------------------------
def save_quotation(db: Session, user: User, req: ProcurementRequest, payload) -> Quotation:
    """Write the supplier's draft (creating it if needed) and, when
    ``payload.submit`` is set, send it. Every requested item must be answered:
    available with a quantity and unit price, or unavailable."""
    if req.status not in QUOTABLE:
        raise Conflict(f"A request that is '{req.status}' cannot be quoted.")
    by_id = {i.procurement_request_item_id: i for i in req.items}
    given = [line.procurement_request_item_id for line in payload.items]
    if len(given) != len(set(given)):
        raise AppError("Each requested item may appear only once in a quotation.")
    if set(given) != set(by_id):
        raise AppError("Answer every requested item: give a price, or mark it unavailable.")
    for line in payload.items:
        item = by_id[line.procurement_request_item_id]
        if line.available:
            if line.quantity is None or line.unit_price is None:
                raise AppError(f"Item {item.line_no} ({item.medicine_name}): give the quantity and unit price.")
            if line.quantity > item.quantity:
                raise AppError(
                    f"Item {item.line_no} ({item.medicine_name}): the quantity cannot exceed the "
                    f"{item.quantity} requested."
                )

    draft = latest(req, Q.DRAFT)
    if draft is None:
        revision = (db.scalar(
            select(func.max(Quotation.revision)).where(
                Quotation.procurement_request_id == req.procurement_request_id
            )
        ) or 0) + 1
        draft = Quotation(
            procurement_request_id=req.procurement_request_id,
            revision=revision,
            status=Q.DRAFT,
            currency=req.currency,
            created_by=user.user_id,
        )
        db.add(draft)
        db.flush()
    else:
        for old in list(draft.items):
            db.delete(old)
        db.flush()
    draft.note = payload.note
    draft.estimated_days = payload.estimated_days
    draft.updated_at = now()
    for line in payload.items:
        db.add(
            QuotationItem(
                quotation_id=draft.quotation_id,
                procurement_request_item_id=line.procurement_request_item_id,
                available=line.available,
                quantity=line.quantity if line.available else None,
                unit_price=line.unit_price if line.available else None,
                note=line.note,
            )
        )
    db.flush()
    if payload.submit:
        _send(db, user, req, draft)
    return draft


def _send(db: Session, user: User, req: ProcurementRequest, quotation: Quotation) -> None:
    # The previous revision (waiting for an answer, or sent back for revision)
    # stays in the history as superseded.
    for previous in req.quotations:
        if previous is not quotation and previous.status in (Q.SUBMITTED, Q.REVISION_REQUESTED):
            previous.status = Q.SUPERSEDED
            previous.updated_at = now()
    db.flush()  # free the one-open-quotation slot before this one is sent
    quotation.status = Q.SUBMITTED
    quotation.submitted_by = user.user_id
    quotation.submitted_at = now()
    quotation.updated_at = now()
    if req.viewed_at is None:
        req.viewed_at = now()
    _set_status(req, R.QUOTED)
    messaging.notify(db, req.pharmacy_organization_id, "quotation_submitted", req.supplier_organization_id,
                     procurement_request_id=req.procurement_request_id, quotation_id=quotation.quotation_id)


def _answer(user: User, quotation: Quotation, status: QuotationStatus, note: str | None) -> None:
    quotation.status = status
    quotation.responded_by = user.user_id
    quotation.responded_at = now()
    quotation.response_note = note
    quotation.updated_at = now()


def current_quotation(req: ProcurementRequest, quotation_id: int) -> Quotation:
    quotation = next((q for q in req.quotations if q.quotation_id == quotation_id), None)
    if quotation is None:
        raise NotFound("Quotation not found.")
    if req.status != R.QUOTED or quotation.status != Q.SUBMITTED:
        raise Conflict("Only the latest quotation, while it waits for your answer, can be answered.")
    return quotation


def request_revision(db: Session, user: User, req: ProcurementRequest, quotation_id: int, note: str | None) -> None:
    quotation = current_quotation(req, quotation_id)
    _answer(user, quotation, Q.REVISION_REQUESTED, note)
    _set_status(req, R.NEGOTIATION)
    messaging.notify(db, req.supplier_organization_id, "revision_requested", req.pharmacy_organization_id,
                     procurement_request_id=req.procurement_request_id, quotation_id=quotation.quotation_id)


def accept(db: Session, user: User, req: ProcurementRequest, quotation_id: int, note: str | None) -> None:
    quotation = current_quotation(req, quotation_id)
    if not any(i.available for i in quotation.items):
        raise Conflict("This quotation has no available items to accept. Ask for a revision or reject it.")
    _answer(user, quotation, Q.ACCEPTED, note)
    _set_status(req, R.ACCEPTED)
    messaging.notify(db, req.supplier_organization_id, "quotation_accepted", req.pharmacy_organization_id,
                     procurement_request_id=req.procurement_request_id, quotation_id=quotation.quotation_id)


def reject(db: Session, user: User, req: ProcurementRequest, quotation_id: int, reason: str) -> None:
    quotation = current_quotation(req, quotation_id)
    _answer(user, quotation, Q.REJECTED, reason)
    _set_status(req, R.REJECTED, reason)
    messaging.notify(db, req.supplier_organization_id, "quotation_rejected", req.pharmacy_organization_id,
                     procurement_request_id=req.procurement_request_id, quotation_id=quotation.quotation_id)


def totals(quotation: Quotation) -> Decimal:
    return sum(
        (i.quantity * i.unit_price for i in quotation.items if i.available),
        Decimal("0"),
    )


# ---------------------------------------------------------------------------
# Conversion into a supplier order
# ---------------------------------------------------------------------------
def existing_order(db: Session, req: ProcurementRequest) -> PurchaseOrder | None:
    return db.scalar(
        select(PurchaseOrder).where(PurchaseOrder.procurement_request_id == req.procurement_request_id)
    )


def convert(db: Session, user: User, req: ProcurementRequest, pharmacy_location_id: int | None):
    """Create the supplier order from the accepted quotation. The caller holds
    a row lock on the request, so two clicks cannot both get here; a request
    that is already converted returns its order instead (``created`` False).

    The order goes through the existing workflow and its database rules: it is
    inserted as a draft with the quoted lines (quantities and unit prices as
    agreed), then submitted, then accepted at those terms. The acceptance is
    recorded as the supplier user who sent the accepted quotation, because
    that quotation is the supplier's acceptance."""
    if req.status == R.CONVERTED:
        order = existing_order(db, req)
        if order is not None:
            return order, False
    if req.status != R.ACCEPTED:
        raise Conflict(f"Only an accepted request can become an order (this one is '{req.status}').")
    quotation = latest(req, Q.ACCEPTED)
    lines = [i for i in quotation.items if i.available] if quotation else []
    if not lines:
        raise Conflict("The accepted quotation has no available items.")
    location_id = pharmacy_location_id or req.pharmacy_location_id
    order_svc.check_location(db, location_id, req.pharmacy_organization_id, "Pharmacy")

    items = {i.procurement_request_item_id: i for i in req.items}
    order = PurchaseOrder(
        pharmacy_organization_id=req.pharmacy_organization_id,
        supplier_organization_id=req.supplier_organization_id,
        pharmacy_location_id=location_id,
        currency=quotation.currency,
        notes=req.notes,
        status=OrderStatus.DRAFT,
        created_by=user.user_id,
        procurement_request_id=req.procurement_request_id,
        quotation_id=quotation.quotation_id,
    )
    db.add(order)
    db.flush()
    for line in lines:
        item = items[line.procurement_request_item_id]
        db.add(
            PurchaseOrderItem(
                purchase_order_id=order.purchase_order_id,
                product_id=item.product_id,
                item_description=None if item.product_id else describe(item),
                requested_quantity=line.quantity,
                requested_unit_price=line.unit_price,
                confirmed_quantity=line.quantity,
                confirmed_unit_price=line.unit_price,
            )
        )
    db.flush()
    ref = f"Procurement request #{req.procurement_request_id}, quotation revision {quotation.revision}"
    order_svc.transition(db, order, OrderStatus.SUBMITTED, f"Created from {ref}.")
    supplier_actor = quotation.submitted_by
    if supplier_actor:
        _set_actor(db, supplier_actor)
    try:
        order_svc.transition(db, order, OrderStatus.ACCEPTED, f"Terms agreed in {ref}.")
    finally:
        if supplier_actor:
            _set_actor(db, user.user_id)
    _set_status(req, R.CONVERTED)
    messaging.notify(db, req.supplier_organization_id, "order_created", req.pharmacy_organization_id,
                     procurement_request_id=req.procurement_request_id, quotation_id=quotation.quotation_id,
                     purchase_order_id=order.purchase_order_id)
    return order, True


def _set_actor(db: Session, user_id: int) -> None:
    """Attribute the next writes in this transaction to ``user_id`` (the
    order triggers stamp app.user_id)."""
    db.execute(text("SELECT set_config('app.user_id', :actor, true)"), {"actor": str(int(user_id))})


def describe(item: ProcurementRequestItem) -> str:
    """One line for a requested medicine: name, strength, form, pack size."""
    parts = [item.medicine_name]
    for extra in (item.strength, item.dosage_form, item.pack_size):
        if extra and extra.lower() not in item.medicine_name.lower():
            parts.append(extra)
    return " ".join(parts)[:255]
