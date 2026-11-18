"""Patient medicine reservations: the reservation engine.

A patient requests one medicine at one pharmacy branch. Requests hold no
stock. When the pharmacy confirms, the quantity is allocated against the
branch's physical stock (Stock.quantity, which is never changed by a
reservation until it is collected) for 24 hours. Collection deducts the full
quantity from physical stock; cancellation, decline and expiry release the
allocation. Expiry is decided by time: a reservation past its deadline counts
as expired everywhere at once, and ``expire_due`` records it.

Every public operation here is ONE transaction: it commits on success and
rolls back completely on any error. The database triggers of migration
c8e5a1f7d2b9 enforce the same rules (actors, transitions, deadlines, stock,
eligibility, system actions); these functions check first so that callers get
clear errors.

Lock order (never acquire in reverse; levels may be skipped):

    L1 organization  FOR SHARE (its state must not change) / FOR NO KEY UPDATE (changes it)
    L2 location      FOR SHARE / FOR NO KEY UPDATE
    L3 product       FOR SHARE / FOR NO KEY UPDATE
    L4 app_user      FOR NO KEY UPDATE (the patient, submission only)
    L5 reservation   FOR UPDATE, ascending reservation_id
    L6 stock         FOR SHARE / FOR UPDATE, ascending (location_id, product_id)

Exclusive locks on parent rows use FOR NO KEY UPDATE, never FOR UPDATE:
inserts that reference those rows (notifications, history, stock
adjustments) take FOR KEY SHARE for their foreign-key check, which conflicts
with FOR UPDATE but not with FOR NO KEY UPDATE. With FOR UPDATE, a suspension
holding the organization and waiting for a reservation could deadlock with a
cancellation holding that reservation and inserting a notification.

Deadlines are compared with clock_timestamp() (the current time), never
now() (the start of the transaction, which may be long before a lock wait
ended). Rows are re-read after every lock (populate_existing).
"""

import functools
import secrets
import uuid
from dataclasses import dataclass, field

from sqlalchemy import and_, case, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import ALL_ROLES, MANAGERS, get_org_access, get_org_location
from app.core.config import settings
from app.core.errors import AppError, Conflict, Forbidden, NotFound
from app.models import (
    Location,
    Membership,
    OfferUnitAcknowledgement,
    Organization,
    Product,
    ProductOffer,
    Reservation,
    ReservationCollection,
    ReservationStatus,
    Stock,
    User,
)
from app.models.enums import OrganizationStatus, OrganizationType
from app.services.messaging import notify_reservation
from app.services.phone import PhoneNumberError, normalize_phone

R = Reservation
S = ReservationStatus

REFERENCE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I/L
DISPENSING_CLASSES = ("unclassified", "non_prescription", "prescription_only")
STOCK_UNITS = ("pack", "unit", "unknown")

INELIGIBLE = {
    "branch_not_found": "This pharmacy branch does not exist.",
    "not_a_pharmacy": "Reservations are only possible at pharmacies.",
    "pharmacy_unavailable": "This pharmacy is not accepting reservations right now.",
    "branch_inactive": "This pharmacy branch is closed.",
    "product_inactive": "This medicine is no longer in the catalogue.",
    "prescription_only": "Prescription-only medicines cannot be reserved.",
    "unclassified": "This medicine has not been classified for reservations yet.",
    "unit_unknown": "The stock unit of this medicine has not been defined yet.",
    "no_quantity_limit": "A reservation limit has not been set for this medicine yet.",
    "disabled": "Reservations are turned off for this medicine.",
    "offer_unlisted": "This branch does not list this medicine.",
    "unit_not_acknowledged": "This branch has not confirmed the stock unit it uses for this medicine.",
}


# ---------------------------------------------------------------------------
# Results and transaction handling
# ---------------------------------------------------------------------------
@dataclass
class Outcome:
    reservation: Reservation
    changed: bool = True  # False: the reservation was already in the requested state
    collection: ReservationCollection | None = None


@dataclass
class CollectionOverride:
    """An owner's or manager's physical count, when the recorded stock is too low."""

    verified_on_hand: int
    recorded_quantity_seen: int
    reason: str
    physically_verified: bool


@dataclass
class StockPosition:
    quantity: int | None  # physical stock on record (None: no stock row)
    allocated: int  # confirmed, unexpired reservations
    available_to_reserve: int
    shortfall: int  # allocated beyond physical stock (after a manual correction)
    at_risk_reservation_ids: list[int] = field(default_factory=list)


class _CommitThenRaise(Exception):
    """Raised inside an operation to keep its writes (e.g. a recorded expiry)
    and then report ``error`` to the caller."""

    def __init__(self, error: AppError):
        self.error = error


def _transaction(fn):
    @functools.wraps(fn)
    def run(db: Session, *args, **kwargs):
        try:
            result = fn(db, *args, **kwargs)
            db.commit()
            return result
        except _CommitThenRaise as exc:
            db.commit()
            raise exc.error from None
        except BaseException:
            db.rollback()
            raise

    return run


def _conflict(message: str, code: str, **extra) -> Conflict:
    return Conflict(message, extra={"code": code, **extra})


def _invalid(message: str, code: str) -> AppError:
    return AppError(message, status_code=422, extra={"code": code})


# ---------------------------------------------------------------------------
# SQL building blocks
# ---------------------------------------------------------------------------
def _now():
    return func.clock_timestamp()


def open_clause():
    """Pending or collectable at this instant."""
    return or_(
        and_(R.status == S.REQUESTED, R.respond_by > _now()),
        and_(R.status == S.CONFIRMED, R.expires_at > _now()),
    )


def lapsed_clause():
    """Still marked open, but past its deadline: expired in every response."""
    return or_(
        and_(R.status == S.REQUESTED, R.respond_by <= _now()),
        and_(R.status == S.CONFIRMED, R.expires_at <= _now()),
    )


def effective_status():
    """The status to show: 'expired' as soon as the deadline passes."""
    return case((lapsed_clause(), S.EXPIRED), else_=R.status)


def allocated_quantity(db: Session, location_id: int, product_id: int) -> int:
    return db.scalar(
        select(func.coalesce(func.sum(R.quantity), 0)).where(
            R.location_id == location_id,
            R.product_id == product_id,
            R.status == S.CONFIRMED,
            R.expires_at > _now(),
        )
    )


def stock_position(db: Session, location_id: int, product_id: int) -> StockPosition:
    """Physical stock against confirmed reservations. A shortfall appears when
    physical stock was corrected below what is already reserved; the affected
    reservations are listed oldest first."""
    quantity = db.scalar(
        select(Stock.quantity).where(Stock.location_id == location_id, Stock.product_id == product_id)
    )
    allocated = allocated_quantity(db, location_id, product_id)
    on_hand = quantity or 0
    shortfall = max(0, allocated - on_hand)
    at_risk = []
    if shortfall:
        at_risk = list(
            db.scalars(
                select(R.reservation_id)
                .where(
                    R.location_id == location_id,
                    R.product_id == product_id,
                    R.status == S.CONFIRMED,
                    R.expires_at > _now(),
                )
                .order_by(R.confirmed_at, R.reservation_id)
            )
        )
    return StockPosition(quantity, allocated, max(0, on_hand - allocated), shortfall, at_risk)


def eligibility_problem(db: Session, location_id: int, product_id: int) -> str | None:
    """Why the product cannot be reserved at the branch now (a code from
    INELIGIBLE), or None. The same database function the triggers use."""
    return db.scalar(select(func.reservation_ineligibility(location_id, product_id)))


def open_reservation_ids(db: Session, *, location_id: int, product_id: int | None = None) -> list[int]:
    stmt = select(R.reservation_id).where(R.location_id == location_id, open_clause())
    if product_id is not None:
        stmt = stmt.where(R.product_id == product_id)
    return list(db.scalars(stmt.order_by(R.reservation_id)))


def product_has_open_reservations(db: Session, product_id: int) -> bool:
    return db.scalar(select(select(R.reservation_id).where(R.product_id == product_id, open_clause()).exists()))


def _lock(db: Session, model, *where, mode: str):
    options = {"share": {"read": True}, "no_key_update": {"key_share": True}, "update": {}}[mode]
    return db.scalar(
        select(model)
        .where(*where)
        .with_for_update(of=model, **options)
        .execution_options(populate_existing=True)
    )


def lock_location(db: Session, location_id: int, *, mode: str = "no_key_update") -> Location | None:
    return _lock(db, Location, Location.location_id == location_id, mode=mode)


def lock_product(db: Session, product_id: int, *, mode: str = "no_key_update") -> Product | None:
    return _lock(db, Product, Product.product_id == product_id, mode=mode)


def lock_stock(db: Session, location_id: int, product_id: int) -> Stock | None:
    return _lock(db, Stock, Stock.location_id == location_id, Stock.product_id == product_id, mode="update")


def _reload(db: Session, reservation_id: int) -> Reservation:
    return db.scalar(select(R).where(R.reservation_id == reservation_id).execution_options(populate_existing=True))


def _is_lapsed(db: Session, reservation_id: int) -> bool:
    return bool(db.scalar(select(lapsed_clause()).select_from(R).where(R.reservation_id == reservation_id)))


def _transition(db: Session, reservation: Reservation, status: str, source: str, **values) -> Reservation:
    """One status change; the trigger validates it and stamps actor and times."""
    db.execute(
        update(R)
        .where(R.reservation_id == reservation.reservation_id)
        .values(status=status, status_source=source, **values)
        .execution_options(synchronize_session=False)
    )
    return _reload(db, reservation.reservation_id)


@dataclass
class ExpiryResult:
    """What one expiry transaction recorded."""

    expired: list[int] = field(default_factory=list)
    unanswered: int = 0  # requests past their response deadline (response_window_elapsed)
    uncollected: int = 0  # confirmed reservations past their collection deadline
    notifications: int = 0  # notifications created (a retry creates none twice)


def _record_expiry(db: Session, reservation_ids: list[int]) -> ExpiryResult:
    """Record expiry (a system transition) for reservations this transaction
    has locked and that are past their deadline, and notify, in the SAME
    transaction: a status change is never committed without its notifications,
    nor the other way round. The trigger sets the reason from the deadline that
    passed. Notifications are unique per reservation, kind and recipient.

    * unanswered request: the patient gets ``reservation_expired``, the
      pharmacy ``reservation_request_lapsed``;
    * confirmed but not collected: the patient gets ``reservation_expired``,
      the pharmacy ``reservation_expired`` (its held stock is free again)."""
    result = ExpiryResult()
    if not reservation_ids:
        return result
    rows = db.execute(
        update(R)
        .where(R.reservation_id.in_(reservation_ids), R.status.in_(S.OPEN), lapsed_clause())
        .values(status=S.EXPIRED, status_source="system")
        .returning(R.reservation_id, R.status_reason, R.patient_user_id, R.pharmacy_organization_id)
        .execution_options(synchronize_session=False)
    ).all()
    for reservation_id, reason, patient_id, org_id in rows:
        result.expired.append(reservation_id)
        sent = [notify_reservation(
            db, "reservation_expired", reservation_id, recipient_user_id=patient_id, from_organization_id=org_id
        )]
        if reason == "response_window_elapsed":
            result.unanswered += 1
            sent.append(notify_reservation(db, "reservation_request_lapsed", reservation_id, organization_id=org_id))
        else:  # collection_window_elapsed
            result.uncollected += 1
            sent.append(notify_reservation(db, "reservation_expired", reservation_id, organization_id=org_id))
        result.notifications += sum(sent)
    return result


def _expire_locked(db: Session, reservation_ids: list[int]) -> list[int]:
    return _record_expiry(db, reservation_ids).expired


def _expire_if_lapsed(db: Session, reservation: Reservation) -> None:
    if _is_lapsed(db, reservation.reservation_id):
        _expire_locked(db, [reservation.reservation_id])
        raise _CommitThenRaise(_conflict("This reservation has expired.", "expired", status=S.EXPIRED))


def _state_conflict(reservation: Reservation, action: str) -> Conflict:
    return _conflict(
        f"A {reservation.status} reservation cannot be {action}.",
        "reservation_state_conflict",
        status=reservation.status,
    )


def _ineligible(problem: str) -> Conflict:
    return _conflict(INELIGIBLE.get(problem, "This medicine cannot be reserved here."), "not_reservable", reason=problem)


def _unit_changed(product: Product) -> Conflict:
    return _conflict(
        "The stock unit of this medicine has changed. Review it and try again.",
        "unit_changed",
        unit_version=product.unit_version,
        stock_unit=product.stock_unit,
        unit_label=product.unit_label,
        pack_size=product.pack_size,
    )


def new_reference() -> str:
    return "RX-" + "".join(secrets.choice(REFERENCE_ALPHABET) for _ in range(10))


# ---------------------------------------------------------------------------
# Patient: submit and cancel
# ---------------------------------------------------------------------------
@_transaction
def submit(
    db: Session,
    patient: User,
    *,
    location_id: int,
    product_id: int,
    quantity: int,
    contact_phone: str,
    client_request_id: uuid.UUID,
    note: str | None = None,
    expected_unit_version: int | None = None,
) -> Outcome:
    """A reservation request. Idempotent per ``client_request_id``: a retry
    with the same id and the same branch, product and quantity returns the
    existing reservation (``changed=False``) whatever its status now.

    ``expected_unit_version`` is the unit version the patient was shown; it is
    compared under the product lock, so a unit change cannot slip in between
    (409 ``unit_changed`` with the current unit)."""
    if not isinstance(quantity, int) or quantity < 1:
        raise _invalid("Choose a quantity of at least 1.", "invalid_quantity")
    note = (note or "").strip() or None
    if note and len(note) > 500:
        raise _invalid("The note can be at most 500 characters.", "invalid_note")
    try:
        phone = normalize_phone(contact_phone, mobile_only=False)
    except PhoneNumberError as exc:
        raise _invalid(str(exc), "invalid_phone") from None

    branch = db.get(Location, location_id)
    if branch is None:
        raise NotFound("Pharmacy branch not found.")
    organization_id = branch.organization_id

    org = _lock(db, Organization, Organization.organization_id == organization_id, mode="share")  # L1
    branch = lock_location(db, location_id, mode="share")  # L2
    product = lock_product(db, product_id, mode="share")  # L3
    if product is None:
        raise NotFound("Medicine not found.")
    _lock(db, User, User.user_id == patient.user_id, mode="no_key_update")  # L4

    existing = db.scalar(
        select(R)
        .where(R.patient_user_id == patient.user_id, R.client_request_id == client_request_id)
        .execution_options(populate_existing=True)
    )
    if existing is not None:
        if (existing.location_id, existing.product_id, existing.quantity) != (location_id, product_id, quantity):
            raise _conflict("This request id was already used for a different reservation.", "idempotency_key_reused")
        return Outcome(existing, changed=False)

    # A reservation past its deadline still carries an open status until it is
    # recorded as expired; record it now so it does not block this request. (L5)
    lapsed = list(
        db.scalars(
            select(R.reservation_id)
            .where(
                R.patient_user_id == patient.user_id,
                R.location_id == location_id,
                R.product_id == product_id,
                R.status.in_(S.OPEN),
                lapsed_clause(),
            )
            .order_by(R.reservation_id)
            .with_for_update(of=R)
        )
    )
    _expire_locked(db, lapsed)

    if org.type != OrganizationType.PHARMACY:
        raise _ineligible("not_a_pharmacy")
    if db.scalar(
        select(Membership.membership_id).where(
            Membership.user_id == patient.user_id,
            Membership.organization_id == organization_id,
            Membership.is_active.is_(True),
        )
    ):
        raise _conflict("You cannot reserve medicines at a pharmacy you work for.", "own_pharmacy")
    problem = eligibility_problem(db, location_id, product_id)
    if problem:
        raise _ineligible(problem)
    if expected_unit_version is not None and expected_unit_version != product.unit_version:
        raise _unit_changed(product)
    if quantity > product.max_reservation_quantity:
        raise _conflict(
            f"At most {product.max_reservation_quantity} can be reserved at once.",
            "quantity_above_limit",
            max_quantity=product.max_reservation_quantity,
        )
    same = db.scalar(
        select(R.reference).where(
            R.patient_user_id == patient.user_id,
            R.location_id == location_id,
            R.product_id == product_id,
            R.status.in_(S.OPEN),
        )
    )
    if same is not None:
        # The patient's own reference (never the database id).
        raise _conflict(
            "You already have an open reservation for this medicine at this branch.",
            "open_reservation_exists",
            reference=same,
        )
    open_count = db.scalar(
        select(func.count()).select_from(R).where(R.patient_user_id == patient.user_id, open_clause())
    )
    if open_count >= settings.reservation_max_open_per_patient:
        raise _conflict(
            f"You can have at most {settings.reservation_max_open_per_patient} open reservations.",
            "too_many_open_reservations",
        )
    if _lock(db, Stock, Stock.location_id == location_id, Stock.product_id == product_id, mode="share") is None:  # L6
        raise _ineligible("offer_unlisted")

    for attempt in range(3):
        reservation = R(
            reference=new_reference(),
            patient_user_id=patient.user_id,
            pharmacy_organization_id=organization_id,
            location_id=location_id,
            product_id=product_id,
            quantity=quantity,
            contact_phone=phone,
            patient_note=note,
            client_request_id=client_request_id,
        )
        try:
            with db.begin_nested():
                db.add(reservation)
                db.flush()
            break
        except IntegrityError as exc:  # a reference collision: draw another
            if "reservation_reference_key" not in str(exc.orig) or attempt == 2:
                raise
    notify_reservation(db, "reservation_requested", reservation.reservation_id, organization_id=organization_id)
    return Outcome(_reload(db, reservation.reservation_id))


@_transaction
def cancel_by_patient(db: Session, patient: User, reservation_id: int, reason: str | None = None) -> Outcome:
    reservation = _lock(
        db, R, R.reservation_id == reservation_id, R.patient_user_id == patient.user_id, mode="update"
    )  # L5
    if reservation is None:
        raise NotFound("Reservation not found.")
    _expire_if_lapsed(db, reservation)
    if reservation.status == S.CANCELLED:
        return Outcome(reservation, changed=False)
    if reservation.status not in S.OPEN:
        raise _state_conflict(reservation, "cancelled")
    reason = (reason or "").strip()[:500] or None
    reservation = _transition(db, reservation, S.CANCELLED, "patient", cancel_reason=reason)
    notify_reservation(
        db,
        "reservation_cancelled_patient",
        reservation.reservation_id,
        organization_id=reservation.pharmacy_organization_id,
    )
    return Outcome(reservation)


# ---------------------------------------------------------------------------
# Pharmacy: confirm, decline, cancel, collect
# ---------------------------------------------------------------------------
def _pharmacy_access(db: Session, actor: User, organization_id: int, reservation_id: int, roles=ALL_ROLES):
    access = get_org_access(
        db, actor, organization_id, roles=roles, org_type=OrganizationType.PHARMACY, require_approved=True
    )
    # The branch and product never change after insert, so they can be read
    # before taking the locks in order.
    row = db.execute(
        select(R.location_id, R.product_id).where(
            R.reservation_id == reservation_id, R.pharmacy_organization_id == organization_id
        )
    ).one_or_none()
    if row is None:
        raise NotFound("Reservation not found.")
    return access, row.location_id, row.product_id


def _require_approved(org: Organization) -> None:
    if org.status != OrganizationStatus.APPROVED:
        raise _ineligible("pharmacy_unavailable")


@_transaction
def confirm(db: Session, actor: User, organization_id: int, reservation_id: int) -> Outcome:
    """Allocate the requested quantity: the branch's physical stock minus
    confirmed, unexpired reservations must cover it."""
    _, location_id, product_id = _pharmacy_access(db, actor, organization_id, reservation_id)
    org = _lock(db, Organization, Organization.organization_id == organization_id, mode="share")  # L1
    lock_location(db, location_id, mode="share")  # L2
    product = lock_product(db, product_id, mode="share")  # L3
    reservation = _lock(db, R, R.reservation_id == reservation_id, mode="update")  # L5
    _expire_if_lapsed(db, reservation)
    if reservation.status == S.CONFIRMED:
        return Outcome(reservation, changed=False)
    if reservation.status != S.REQUESTED:
        raise _state_conflict(reservation, "confirmed")
    _require_approved(org)
    if reservation.patient_user_id == actor.user_id:
        raise Forbidden("You cannot handle your own reservation.")
    problem = eligibility_problem(db, location_id, product_id)
    if problem:
        raise _ineligible(problem)
    if product.unit_version != reservation.unit_version:
        raise _conflict("The stock unit of this medicine changed after the request.", "unit_changed")
    stock = lock_stock(db, location_id, product_id)  # L6
    if stock is None:
        raise _ineligible("offer_unlisted")
    # A new statement after the stock lock: sees every confirmation committed meanwhile.
    allocated = allocated_quantity(db, location_id, product_id)
    available = stock.quantity - allocated
    if available < reservation.quantity:
        raise _conflict(
            "Not enough unreserved stock to confirm this reservation.",
            "insufficient_stock",
            available_to_reserve=max(0, available),
        )
    reservation = _transition(db, reservation, S.CONFIRMED, "pharmacy")
    notify_reservation(
        db, "reservation_confirmed", reservation.reservation_id,
        recipient_user_id=reservation.patient_user_id, from_organization_id=organization_id,
    )
    return Outcome(reservation)


def _reason(text: str | None, what: str) -> str:
    text = (text or "").strip()
    if not text:
        raise _invalid(f"Give a reason to {what}.", "reason_required")
    if len(text) > 500:
        raise _invalid("The reason can be at most 500 characters.", "reason_too_long")
    return text


@_transaction
def decline(db: Session, actor: User, organization_id: int, reservation_id: int, reason: str) -> Outcome:
    reason = _reason(reason, "decline")
    _pharmacy_access(db, actor, organization_id, reservation_id)
    reservation = _lock(db, R, R.reservation_id == reservation_id, mode="update")  # L5
    _expire_if_lapsed(db, reservation)
    if reservation.status == S.DECLINED:
        return Outcome(reservation, changed=False)
    if reservation.status != S.REQUESTED:
        raise _state_conflict(reservation, "declined")
    if reservation.patient_user_id == actor.user_id:
        raise Forbidden("You cannot handle your own reservation.")
    reservation = _transition(db, reservation, S.DECLINED, "pharmacy", decline_reason=reason)
    notify_reservation(
        db, "reservation_declined", reservation.reservation_id,
        recipient_user_id=reservation.patient_user_id, from_organization_id=organization_id,
    )
    return Outcome(reservation)


@_transaction
def cancel_by_pharmacy(db: Session, actor: User, organization_id: int, reservation_id: int, reason: str) -> Outcome:
    """Owners and managers cancel a CONFIRMED reservation (a pending request is declined)."""
    reason = _reason(reason, "cancel")
    _pharmacy_access(db, actor, organization_id, reservation_id, roles=MANAGERS)
    reservation = _lock(db, R, R.reservation_id == reservation_id, mode="update")  # L5
    _expire_if_lapsed(db, reservation)
    if reservation.status == S.CANCELLED:
        return Outcome(reservation, changed=False)
    if reservation.status != S.CONFIRMED:
        raise _state_conflict(reservation, "cancelled by the pharmacy (decline a pending request instead)")
    if reservation.patient_user_id == actor.user_id:
        raise Forbidden("You cannot handle your own reservation.")
    reservation = _transition(db, reservation, S.CANCELLED, "pharmacy", cancel_reason=reason)
    notify_reservation(
        db, "reservation_cancelled", reservation.reservation_id,
        recipient_user_id=reservation.patient_user_id, from_organization_id=organization_id,
    )
    return Outcome(reservation)


@_transaction
def collect(
    db: Session,
    actor: User,
    organization_id: int,
    reservation_id: int,
    *,
    reference: str,
    override: CollectionOverride | None = None,
) -> Outcome:
    """Hand over the FULL reserved quantity and deduct it from physical stock.

    If the recorded stock is lower than the reserved quantity, nothing changes
    and 409 ``stock_record_insufficient`` is returned. The stock can then be
    corrected (any role, through the stock screen) or an owner/manager can
    override with a physical count, recorded with their name and reason."""
    access, location_id, product_id = _pharmacy_access(db, actor, organization_id, reservation_id)
    org = _lock(db, Organization, Organization.organization_id == organization_id, mode="share")  # L1
    lock_location(db, location_id, mode="share")  # L2
    reservation = _lock(db, R, R.reservation_id == reservation_id, mode="update")  # L5
    if reservation.reference != (reference or "").strip().upper():
        raise _invalid("The reservation reference does not match.", "reference_mismatch")
    if reservation.status == S.COLLECTED:
        return Outcome(reservation, changed=False, collection=db.get(ReservationCollection, reservation_id))
    _expire_if_lapsed(db, reservation)
    if reservation.status != S.CONFIRMED:
        raise _state_conflict(reservation, "collected")
    _require_approved(org)
    if reservation.patient_user_id == actor.user_id:
        raise Forbidden("You cannot handle your own reservation.")
    can_override = access.role in MANAGERS
    if override is not None and not can_override:
        raise Forbidden("Only owners and managers can override the recorded stock.")
    stock = lock_stock(db, location_id, product_id)  # L6
    if stock is None:
        raise _conflict("This branch no longer has a stock record for this medicine.", "stock_missing")

    if override is None:
        if stock.quantity < reservation.quantity:
            raise _conflict(
                "The recorded stock is lower than the reserved quantity. Count the shelf, then correct "
                "the stock or ask an owner or manager to override.",
                "stock_record_insufficient",
                recorded_quantity=stock.quantity,
                reserved_quantity=reservation.quantity,
                can_override=can_override,
            )
        record = ReservationCollection(reservation_id=reservation_id)
    else:
        if override.physically_verified is not True:
            raise _invalid("Confirm that you physically counted the stock.", "not_verified")
        if override.verified_on_hand < reservation.quantity:
            raise _invalid(
                "The counted stock must cover the full reserved quantity; partial collection is not possible.",
                "count_too_low",
            )
        reason = (override.reason or "").strip()
        if not 10 <= len(reason) <= 500:
            raise _invalid("Explain the override in 10 to 500 characters.", "reason_required")
        if override.recorded_quantity_seen != stock.quantity:
            raise _conflict(
                "The recorded stock changed since you looked. Count again.",
                "stock_changed",
                recorded_quantity=stock.quantity,
            )
        record = ReservationCollection(
            reservation_id=reservation_id,
            override=True,
            verified_on_hand=override.verified_on_hand,
            recorded_quantity_seen=override.recorded_quantity_seen,
            override_reason=reason,
        )
    db.add(record)
    db.flush()  # the trigger deducts the stock and records the adjustments
    reservation = _transition(db, reservation, S.COLLECTED, "pharmacy")
    return Outcome(reservation, collection=record)


# ---------------------------------------------------------------------------
# System: expiry and pharmacy suspension
# ---------------------------------------------------------------------------
@_transaction
def expire_due(
    db: Session, *, patient_user_id: int | None = None, organization_id: int | None = None, limit: int = 500
) -> list[int]:
    """Record expiry for reservations past their deadline. Safe to run
    concurrently and repeatedly: rows locked by another transaction are
    skipped (still treated as expired by time), each row expires once and is
    notified once."""
    return _record_expiry(db, _lock_due(db, patient_user_id, organization_id, limit)).expired


def _lock_due(db: Session, patient_user_id: int | None, organization_id: int | None, limit: int) -> list[int]:
    """Lock (FOR UPDATE SKIP LOCKED, oldest first) up to ``limit`` reservations
    still marked open but past their deadline. Rows another transaction holds
    are skipped, never waited for: they stay due and a later run takes them."""
    stmt = select(R.reservation_id).where(R.status.in_(S.OPEN), lapsed_clause())
    if patient_user_id is not None:
        stmt = stmt.where(R.patient_user_id == patient_user_id)
    if organization_id is not None:
        stmt = stmt.where(R.pharmacy_organization_id == organization_id)
    return list(db.scalars(stmt.order_by(R.reservation_id).limit(limit).with_for_update(of=R, skip_locked=True)))


@_transaction
def expire_due_batch(db: Session, *, limit: int = 200) -> ExpiryResult:
    """One batch for the scheduled job (app/scripts/expire_reservations.py):
    the same locking and recording as ``expire_due``, with counts. One
    transaction: everything in the batch is committed together or not at all."""
    return _record_expiry(db, _lock_due(db, None, None, limit))


def count_due(db: Session) -> dict[str, int]:
    """Read only: reservations past a deadline whose expiry is not recorded yet."""
    rows = db.execute(
        select(R.status, func.count()).where(R.status.in_(S.OPEN), lapsed_clause()).group_by(R.status)
    ).all()
    counts = dict(rows)
    return {"unanswered": counts.get(S.REQUESTED, 0), "uncollected": counts.get(S.CONFIRMED, 0)}


def cancel_for_suspension(db: Session, organization_id: int) -> list[int]:
    """Called by the admin review in ITS transaction, after the organization
    row was locked (FOR NO KEY UPDATE) and its status set to 'suspended' and
    flushed. Every open reservation is closed: expired if past its deadline,
    otherwise cancelled as a system action, and the patient is notified.
    Waits for (never skips) reservations other transactions hold, so none
    escapes. Does not commit."""
    ids = list(
        db.scalars(
            select(R.reservation_id)
            .where(R.pharmacy_organization_id == organization_id, R.status.in_(S.OPEN))
            .order_by(R.reservation_id)
            .with_for_update(of=R)
        )
    )
    _expire_locked(db, ids)
    if not ids:
        return []
    rows = db.execute(
        update(R)
        .where(R.reservation_id.in_(ids), R.status.in_(S.OPEN))
        .values(status=S.CANCELLED, status_source="system")
        .returning(R.reservation_id, R.patient_user_id)
        .execution_options(synchronize_session=False)
    ).all()
    for reservation_id, patient_id in rows:
        notify_reservation(
            db, "reservation_withdrawn", reservation_id,
            recipient_user_id=patient_id, from_organization_id=organization_id,
        )
    return [row[0] for row in rows]


# ---------------------------------------------------------------------------
# Catalogue settings (platform admins) and branch unit acknowledgement
# ---------------------------------------------------------------------------
PRODUCT_SETTINGS = (
    "dispensing_class",
    "stock_unit",
    "unit_label",
    "pack_size",
    "max_reservation_quantity",
    "reservation_enabled",
)
UNIT_LABEL_PLACEHOLDERS = frozenset({"n/a", "na", "none", "unknown", "tbd", "other", "x"})
SETTINGS_PROBLEMS = {
    "product_inactive": "The medicine is retired from the catalogue.",
    "not_non_prescription": "Only medicines classified as non-prescription can be reserved.",
    "unit_unknown": "Choose the stock unit (pack or unit).",
    "unit_label_missing": "Name the unit (for example \"box\" or \"tablet\").",
    "unit_label_invalid": "The unit name must be 2 to 60 characters, contain a letter and not be a placeholder.",
    "pack_size_missing": "A medicine counted in packs needs a pack size.",
    "no_quantity_limit": "Set the maximum quantity per reservation.",
}


def _label_problem(stock_unit: str, label: str | None) -> str | None:
    """Mirrors product_unit_label_check (the database stays the authority)."""
    if label is None:
        return None if stock_unit == "unknown" else "unit_label_missing"
    if stock_unit == "unknown":
        return "unit_label_invalid"
    if (
        label != label.strip()
        or not 2 <= len(label) <= 60
        or label.lower() in UNIT_LABEL_PLACEHOLDERS
        or not any(ch.isalpha() for ch in label)
    ):
        return "unit_label_invalid"
    return None


def settings_problems(product: Product) -> list[str]:
    """Why reservations cannot be enabled for this product (codes from
    SETTINGS_PROBLEMS), in the order a reviewer would fix them. Empty when they can."""
    problems = []
    if not product.is_active:
        problems.append("product_inactive")
    if product.dispensing_class != "non_prescription":
        problems.append("not_non_prescription")
    if product.stock_unit == "unknown":
        problems.append("unit_unknown")
    elif label := _label_problem(product.stock_unit, product.unit_label):
        problems.append(label)
    if product.stock_unit == "pack" and not product.pack_size:
        problems.append("pack_size_missing")
    if product.max_reservation_quantity is None:
        problems.append("no_quantity_limit")
    return problems


@_transaction
def configure_product(db: Session, admin: User, product_id: int, **changes) -> Product:
    """Set a product's reservation settings. Enabling requires a
    non-prescription classification, a known unit with a label (and a pack
    size for packs) and a maximum quantity (database CHECK). A unit change is
    refused while reservations are open and invalidates every branch
    acknowledgement (unit_version)."""
    if not admin.is_platform_admin:
        raise Forbidden("Platform administrator access is required.")
    unknown = set(changes) - set(PRODUCT_SETTINGS)
    if unknown:
        raise ValueError(f"Unknown product settings: {sorted(unknown)}")
    if changes.get("dispensing_class", DISPENSING_CLASSES[0]) not in DISPENSING_CLASSES:
        raise _invalid("Unknown dispensing class.", "invalid_dispensing_class")
    if changes.get("stock_unit", STOCK_UNITS[0]) not in STOCK_UNITS:
        raise _invalid("Unknown stock unit.", "invalid_stock_unit")
    for key in ("unit_label", "pack_size"):
        if isinstance(changes.get(key), str):
            changes[key] = changes[key].strip() or None
    if "max_reservation_quantity" in changes and changes["max_reservation_quantity"] is not None:
        if not 1 <= changes["max_reservation_quantity"] <= 1000:
            raise _invalid("The maximum quantity must be between 1 and 1000.", "invalid_max_quantity")

    product = lock_product(db, product_id)  # L3, FOR NO KEY UPDATE
    if product is None:
        raise NotFound("Product not found.")
    new_unit = changes.get("stock_unit", product.stock_unit)
    unit_change = any(
        key in changes and changes[key] != getattr(product, key) for key in ("stock_unit", "unit_label")
    ) or (
        "pack_size" in changes
        and changes["pack_size"] != product.pack_size
        and "pack" in (product.stock_unit, new_unit)
    )
    if unit_change and product_has_open_reservations(db, product_id):
        raise _conflict(
            "This medicine has open reservations; its stock unit cannot change until they are resolved.",
            "open_reservations",
        )
    for key, value in changes.items():
        setattr(product, key, value)
    problems = [p for p in settings_problems(product) if p != "product_inactive"]
    label_problem = _label_problem(product.stock_unit, product.unit_label)
    if label_problem == "unit_label_invalid" or (product.reservation_enabled and problems):
        if label_problem == "unit_label_invalid" and label_problem not in problems:
            problems.append(label_problem)
        raise AppError(
            "These reservation settings are not valid together. Reservations need a non-prescription "
            "classification, a stock unit with a clear name (and a pack size for packs) and a maximum quantity.",
            status_code=422,
            extra={
                "code": "invalid_reservation_settings",
                "problems": [{"code": p, "message": SETTINGS_PROBLEMS[p]} for p in problems],
            },
        )
    try:
        db.flush()
    except IntegrityError as exc:  # the database CHECKs remain the authority
        raise _invalid(
            "These reservation settings are not valid together. Reservations need a non-prescription "
            "classification, a stock unit with a clear name (and a pack size for packs) and a maximum quantity.",
            "invalid_reservation_settings",
        ) from exc
    db.refresh(product)
    return product


@_transaction
def acknowledge_unit(
    db: Session,
    actor: User,
    organization_id: int,
    location_id: int,
    product_id: int,
    *,
    unit_version: int,
    stock_unit: str,
    unit_label: str,
    pack_size: str | None,
) -> OfferUnitAcknowledgement:
    """An owner or manager confirms that this branch counts the product in the
    unit shown to them. The values shown must still be the current ones."""
    get_org_access(
        db, actor, organization_id, roles=MANAGERS, org_type=OrganizationType.PHARMACY, require_approved=True
    )
    get_org_location(db, organization_id, location_id, require_active=True)
    product = lock_product(db, product_id, mode="share")  # L3
    if product is None:
        raise NotFound("Product not found.")
    if product.stock_unit == "unknown":
        raise _conflict("This medicine has no stock unit to acknowledge yet.", "unit_unknown")
    shown = (unit_version, stock_unit, unit_label)
    current = (product.unit_version, product.stock_unit, product.unit_label)
    if shown != current or (product.stock_unit == "pack" and pack_size != product.pack_size):
        raise _unit_changed(product)
    if not db.scalar(
        select(ProductOffer.offer_id).where(
            ProductOffer.location_id == location_id, ProductOffer.product_id == product_id
        )
    ):
        raise _conflict("Add this medicine to the branch stock and price it first.", "offer_missing")
    existing = db.get(OfferUnitAcknowledgement, (location_id, product_id, product.unit_version))
    if existing is not None:
        return existing
    ack = OfferUnitAcknowledgement(
        location_id=location_id,
        product_id=product_id,
        unit_version=product.unit_version,
        stock_unit=product.stock_unit,
        unit_label=product.unit_label,
        pack_size=product.pack_size,
    )
    db.add(ack)
    db.flush()
    return ack
