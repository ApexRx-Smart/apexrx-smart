"""Patient medicine reservations: the HTTP layer over app.services.reservations.

Every state change goes through the reservation engine (one transaction per
call, the approved lock order, the database triggers as the backstop). This
module only resolves who is asking and what they may see:

* Patients (any signed-in account) see and act on their OWN reservations only.
  Anyone else's reservation is "not found" (404), never "forbidden".
* Pharmacy members see their organization's reservations (all branches:
  memberships are organization-wide). Another organization's reservation is 404.
  Confirm, decline and collect: any active role. Cancel a confirmed
  reservation and override the recorded stock at collection: owners and
  managers. Actions need an approved pharmacy; reading does not (a suspended
  pharmacy can still see its history).
* The patient's phone number is shown only to members of the handling
  pharmacy, and only while the reservation is open.
* Platform admins classify medicines (catalogue settings); they have no
  access to reservations or patient details.

Reservations are addressed by reference, never by database id. Expiry and
suspension are system operations with no endpoint here.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import case, exists, func, select
from sqlalchemy.orm import Session, aliased

from app.api.deps import (
    ALL_ROLES,
    MANAGERS,
    AdminUser,
    CurrentUser,
    DbSession,
    Pagination,
    bearer_scheme,
    get_auth,
    get_org_access,
    get_org_location,
)
from app.core.errors import AppError, NotFound, TooManyRequests
from app.core.rate_limit import reservation_limiter
from app.models import (
    Drug,
    Location,
    Membership,
    OfferUnitAcknowledgement,
    Organization,
    Product,
    ProductReservationHistory,
    Reservation,
    ReservationCollection,
    ReservationStatus,
    ReservationStatusHistory,
    Stock,
    User,
)
from app.models.enums import MembershipRole, OrganizationStatus, OrganizationType
from app.models.views import patient_availability
from app.schemas.common import Page
from app.schemas.reservations import (
    REFERENCE_PATTERN,
    BranchSummary,
    CollectionDetail,
    CollectRequest,
    HistoryEntry,
    MedicineSummary,
    PatientContact,
    PatientReservation,
    PatientReservationDetail,
    PharmacyReservation,
    PharmacyReservationDetail,
    ReservationCancel,
    ReservationCreate,
    ReservationDecision,
    ReservationOptions,
    ReservationSettings,
    ReservationSettingsHistory,
    ReservationSettingsUpdate,
    ReservationStatusFilter,
    SettingsProblem,
    StockAllocation,
    UnitAcknowledgementRequest,
    UnitAcknowledgementStatus,
    UnitInfo,
)
from app.services import reservations as engine
from app.services.reservations import (
    INELIGIBLE,
    SETTINGS_PROBLEMS,
    CollectionOverride,
    effective_status,
    open_clause,
)

R = Reservation
S = ReservationStatus

patient_router = APIRouter()
pharmacy_router = APIRouter()
settings_router = APIRouter()

ReferencePath = Annotated[str, Path(pattern=REFERENCE_PATTERN, description="The reservation reference, e.g. RX-AB3D…")]
Statuses = Annotated[list[ReservationStatusFilter] | None, Query(description="Repeat to match several.")]


ELIGIBILITY_MESSAGES = {**INELIGIBLE, "own_pharmacy": "You cannot reserve medicines at a pharmacy you work for."}


def _member_organization_ids(db: Session, user: User) -> set[int]:
    return set(
        db.scalars(
            select(Membership.organization_id).where(Membership.user_id == user.user_id, Membership.is_active.is_(True))
        )
    )


def _normalize(reference: str) -> str:
    return reference.strip().upper()


# ---------------------------------------------------------------------------
# Loading and serialization
# ---------------------------------------------------------------------------
Patient = aliased(User, name="patient")


def _query():
    return (
        select(
            R,
            Product,
            Drug,
            Location,
            Organization,
            Patient.name.label("patient_name"),
            effective_status().label("effective"),
            open_clause().label("is_open"),
        )
        .join(Product, Product.product_id == R.product_id)
        .join(Drug, Drug.drug_id == Product.drug_id)
        .join(Location, Location.location_id == R.location_id)
        .join(Organization, Organization.organization_id == R.pharmacy_organization_id)
        .join(Patient, Patient.user_id == R.patient_user_id)
    )


def _filtered(stmt, statuses, submitted_from: datetime | None, submitted_to: datetime | None):
    if statuses:
        stmt = stmt.where(effective_status().in_([s.value for s in statuses]))
    if submitted_from is not None:
        stmt = stmt.where(R.created_at >= submitted_from)
    if submitted_to is not None:
        stmt = stmt.where(R.created_at < submitted_to)
    return stmt


def _page(db: Session, stmt, order, limit: int, offset: int):
    total = db.scalar(select(func.count()).select_from(stmt.with_only_columns(R.reservation_id).subquery()))
    rows = db.execute(stmt.order_by(*order).limit(limit).offset(offset)).all()
    return rows, total


def _unit(r: Reservation) -> UnitInfo:
    return UnitInfo(unit_version=r.unit_version, stock_unit=r.stock_unit, unit_label=r.unit_label, pack_size=r.pack_size)


def _medicine(product: Product, drug: Drug) -> MedicineSummary:
    return MedicineSummary(
        product_id=product.product_id,
        product_name=product.product_name,
        drug_name=drug.name,
        brand=product.brand,
        strength=product.strength,
        dosage_form=product.dosage_form,
    )


def _closed_at(r: Reservation, effective: str) -> datetime | None:
    if effective in S.OPEN:
        return None
    if r.status in S.OPEN:  # past its deadline, expiry not recorded yet
        return r.expires_at if r.status == S.CONFIRMED else r.respond_by
    return r.status_changed_at


def _common(row) -> dict:
    r = row.Reservation
    return dict(
        reference=r.reference,
        status=row.effective,
        medicine=_medicine(row.Product, row.Drug),
        quantity=r.quantity,
        unit=_unit(r),
        unit_price=r.unit_price,
        currency=r.currency,
        note=r.patient_note,
        submitted_at=r.created_at,
        respond_by=r.respond_by,
        confirmed_at=r.confirmed_at,
        collect_by=r.expires_at,
        closed_at=_closed_at(r, row.effective),
        decline_reason=r.decline_reason,
        cancel_reason=r.cancel_reason,
        system_reason=r.status_reason if r.status_source == "system" else None,
    )


def _history(db: Session, reservation_id: int, *, staff_names: bool) -> list[HistoryEntry]:
    H = ReservationStatusHistory
    rows = db.execute(
        select(H, User.name)
        .outerjoin(User, User.user_id == H.changed_by)
        .where(H.reservation_id == reservation_id)
        .order_by(H.changed_at, H.history_id)
    ).all()
    return [
        HistoryEntry(
            from_status=h.from_status,
            to_status=h.to_status,
            by=h.source,
            by_name=name if staff_names and h.source == "pharmacy" else None,
            system_reason=h.system_reason,
            reason=h.reason,
            changed_at=h.changed_at,
        )
        for h, name in rows
    ]


# Patient views ----------------------------------------------------------------
def _patient_item(row) -> PatientReservation:
    location, org = row.Location, row.Organization
    return PatientReservation(
        **_common(row),
        branch=BranchSummary(
            location_id=location.location_id,
            name=location.name,
            pharmacy_name=org.name,
            address=location.address,
            city=location.city,
            phone=location.phone,
            whatsapp_phone=location.whatsapp_phone,
        ),
        contact_phone=row.Reservation.contact_phone,
        can_cancel=bool(row.is_open),
    )


def _own_reservation_row(db: Session, user: User, reference: str):
    row = db.execute(
        _query()
        .where(R.reference == _normalize(reference), R.patient_user_id == user.user_id)
        .execution_options(populate_existing=True)
    ).one_or_none()
    if row is None:
        raise NotFound("Reservation not found.")
    return row


def _patient_detail(db: Session, user: User, reference: str) -> PatientReservationDetail:
    row = _own_reservation_row(db, user, reference)
    return PatientReservationDetail(
        **_patient_item(row).model_dump(), history=_history(db, row.Reservation.reservation_id, staff_names=False)
    )


# Pharmacy views ---------------------------------------------------------------
def _actions(row, role: MembershipRole | None, user: User) -> list[str]:
    r = row.Reservation
    if (
        role is None
        or row.Organization.status != OrganizationStatus.APPROVED
        or not row.is_open
        or r.patient_user_id == user.user_id
    ):
        return []
    if r.status == S.REQUESTED:
        return ["confirm", "decline"]
    actions = ["collect"]
    if role in MANAGERS:
        actions += ["cancel", "override"]
    return actions


def _pharmacy_item(row, role: MembershipRole | None, user: User) -> PharmacyReservation:
    r = row.Reservation
    return PharmacyReservation(
        **_common(row),
        location_id=r.location_id,
        location_name=row.Location.name,
        patient=PatientContact(name=row.patient_name, phone=r.contact_phone if row.is_open else None),
        actions=_actions(row, role, user),
    )


def _pharmacy_access(db: Session, user: User, organization_id: int):
    return get_org_access(db, user, organization_id, org_type=OrganizationType.PHARMACY)


def _org_reservation_id(db: Session, organization_id: int, reference: str) -> int:
    reservation_id = db.scalar(
        select(R.reservation_id).where(
            R.reference == _normalize(reference), R.pharmacy_organization_id == organization_id
        )
    )
    if reservation_id is None:
        raise NotFound("Reservation not found.")
    return reservation_id


def _pharmacy_detail(db: Session, user: User, organization_id: int, reference: str) -> PharmacyReservationDetail:
    access = _pharmacy_access(db, user, organization_id)
    row = db.execute(
        _query()
        .where(R.reference == _normalize(reference), R.pharmacy_organization_id == organization_id)
        .execution_options(populate_existing=True)
    ).one_or_none()
    if row is None:
        raise NotFound("Reservation not found.")
    r = row.Reservation
    position = engine.stock_position(db, r.location_id, r.product_id)
    last_updated = db.scalar(
        select(Stock.last_updated).where(Stock.location_id == r.location_id, Stock.product_id == r.product_id)
    )
    collection = None
    record = db.get(ReservationCollection, r.reservation_id, populate_existing=True)
    if record is not None:
        names = dict(
            db.execute(
                select(User.user_id, User.name).where(User.user_id.in_({record.collected_by, record.override_by} - {None}))
            ).all()
        )
        collection = CollectionDetail(
            collected_at=record.collected_at,
            collected_by_name=names.get(record.collected_by),
            quantity=record.quantity,
            recorded_quantity_before=record.recorded_quantity_before,
            quantity_after=record.quantity_after,
            override=record.override,
            override_by_name=names.get(record.override_by),
            verified_on_hand=record.verified_on_hand,
            recorded_quantity_seen=record.recorded_quantity_seen,
            override_reason=record.override_reason,
        )
    return PharmacyReservationDetail(
        **_pharmacy_item(row, access.role, user).model_dump(),
        history=_history(db, r.reservation_id, staff_names=True),
        stock=StockAllocation(
            recorded_quantity=position.quantity,
            allocated_quantity=position.allocated,
            available_to_reserve=position.available_to_reserve,
            shortfall=position.shortfall,
            last_updated=last_updated,
            this_reservation_at_risk=r.reservation_id in position.at_risk_reservation_ids,
        ),
        collection=collection,
    )


# ---------------------------------------------------------------------------
# Patient endpoints
# ---------------------------------------------------------------------------
def optional_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User | None:
    """The signed-in user, or None without credentials. A token that is sent
    but invalid or expired is still refused (401), like everywhere else."""
    if credentials is None:
        return None
    return get_auth(db, credentials).user


@patient_router.get("/options", response_model=ReservationOptions)
def reservation_options(
    user: Annotated[User | None, Depends(optional_user)],
    db: DbSession,
    location_id: Annotated[int, Query(gt=0)],
    product_id: Annotated[int, Query(gt=0)],
):
    """Whether this medicine can be reserved at this branch, its unit (quote
    ``unit.unit_version`` when submitting) and the maximum quantity. Never
    returns stock quantities. Works signed out too (public search shows the
    Reserve button only when it applies); signed in, it also says when the
    caller works for this pharmacy (``own_pharmacy``)."""
    product = db.get(Product, product_id)
    if product is None:
        raise NotFound("Medicine not found.")
    problem = engine.eligibility_problem(db, location_id, product_id)
    if problem == "branch_not_found":
        raise NotFound("Pharmacy branch not found.")
    if user is not None and problem is None and db.scalar(
        select(Location.organization_id).where(Location.location_id == location_id)
    ) in _member_organization_ids(db, user):
        problem = "own_pharmacy"
    public = db.execute(
        select(patient_availability.c.availability_status, patient_availability.c.unit_price, patient_availability.c.currency).where(
            patient_availability.c.location_id == location_id, patient_availability.c.product_id == product_id
        )
    ).one_or_none()
    return ReservationOptions(
        reservable=problem is None,
        reason=problem,
        message=ELIGIBILITY_MESSAGES.get(problem) if problem else None,
        availability_status=public.availability_status if public else None,
        max_quantity=product.max_reservation_quantity if problem is None else None,
        unit=UnitInfo(
            unit_version=product.unit_version,
            stock_unit=product.stock_unit,
            unit_label=product.unit_label,
            pack_size=product.pack_size,
        ),
        unit_price=public.unit_price if public else None,
        currency=public.currency if public else None,
    )


@patient_router.post(
    "",
    response_model=PatientReservationDetail,
    status_code=status.HTTP_201_CREATED,
    responses={200: {"description": "A retry of an earlier request (same client_request_id)."}},
)
def submit_reservation(payload: ReservationCreate, user: CurrentUser, db: DbSession, response: Response):
    """Request one medicine at one branch. The price, unit, deadlines and
    status are set by the server. Retrying with the same ``client_request_id``
    returns the original reservation (200) instead of creating another; reusing
    it for a different request is 409 ``idempotency_key_reused``."""
    is_retry = db.scalar(
        select(exists().where(R.patient_user_id == user.user_id, R.client_request_id == payload.client_request_id))
    )
    if not is_retry:
        wait = reservation_limiter.hit(str(user.user_id))
        if wait is not None:
            raise TooManyRequests(
                "Too many reservation requests. Please wait and try again.",
                headers={"Retry-After": str(wait)},
                extra={"code": "rate_limited"},
            )
    phone = payload.contact_phone or user.phone
    if not phone or not phone.strip():
        raise AppError(
            "Add a phone number the pharmacy can call about this reservation.",
            status_code=422,
            extra={"code": "phone_required"},
        )
    outcome = engine.submit(
        db,
        user,
        location_id=payload.location_id,
        product_id=payload.product_id,
        quantity=payload.quantity,
        contact_phone=phone,
        client_request_id=payload.client_request_id,
        note=payload.note,
        expected_unit_version=payload.unit_version,
    )
    if not outcome.changed:
        response.status_code = status.HTTP_200_OK
    return _patient_detail(db, user, outcome.reservation.reference)


@patient_router.get("", response_model=Page[PatientReservation])
def list_my_reservations(user: CurrentUser, db: DbSession, page: Pagination, status_: Annotated[Statuses, Query(alias="status")] = None):
    """Your reservations, newest first."""
    limit, offset = page
    stmt = _filtered(_query().where(R.patient_user_id == user.user_id), status_, None, None)
    rows, total = _page(db, stmt, (R.created_at.desc(), R.reservation_id.desc()), limit, offset)
    return Page(items=[_patient_item(row) for row in rows], total=total, limit=limit, offset=offset)


@patient_router.get("/{reference}", response_model=PatientReservationDetail)
def get_my_reservation(reference: ReferencePath, user: CurrentUser, db: DbSession):
    return _patient_detail(db, user, reference)


@patient_router.post("/{reference}/cancel", response_model=PatientReservationDetail)
def cancel_my_reservation(
    reference: ReferencePath, user: CurrentUser, db: DbSession, payload: ReservationCancel | None = None
):
    """Cancel a pending or confirmed reservation (repeating it is harmless)."""
    reservation_id = _own_reservation_row(db, user, reference).Reservation.reservation_id
    engine.cancel_by_patient(db, user, reservation_id, payload.reason if payload else None)
    return _patient_detail(db, user, reference)


# ---------------------------------------------------------------------------
# Pharmacy endpoints
# ---------------------------------------------------------------------------
@pharmacy_router.get("/{organization_id}/reservations", response_model=Page[PharmacyReservation])
def list_pharmacy_reservations(
    organization_id: int,
    user: CurrentUser,
    db: DbSession,
    page: Pagination,
    location_id: int | None = None,
    status_: Annotated[Statuses, Query(alias="status")] = None,
    submitted_from: datetime | None = None,
    submitted_to: datetime | None = None,
    reference: Annotated[str | None, Query(pattern=REFERENCE_PATTERN)] = None,
    sort: Annotated[str, Query(pattern="^(newest|deadline)$")] = "newest",
):
    """The organization's reservations. ``sort=deadline`` puts the most urgent
    first (open ones by their next deadline, then closed ones, newest first)."""
    access = _pharmacy_access(db, user, organization_id)
    if location_id is not None:
        get_org_location(db, organization_id, location_id)
    limit, offset = page
    stmt = _query().where(R.pharmacy_organization_id == organization_id)
    if location_id is not None:
        stmt = stmt.where(R.location_id == location_id)
    if reference:
        stmt = stmt.where(R.reference == _normalize(reference))
    stmt = _filtered(stmt, status_, submitted_from, submitted_to)
    if sort == "deadline":
        deadline = case((R.status == S.REQUESTED, R.respond_by), else_=R.expires_at)
        order = (case((open_clause(), 0), else_=1), case((open_clause(), deadline)), R.created_at.desc(), R.reservation_id.desc())
    else:
        order = (R.created_at.desc(), R.reservation_id.desc())
    rows, total = _page(db, stmt, order, limit, offset)
    return Page(items=[_pharmacy_item(row, access.role, user) for row in rows], total=total, limit=limit, offset=offset)


@pharmacy_router.get("/{organization_id}/reservations/{reference}", response_model=PharmacyReservationDetail)
def get_pharmacy_reservation(organization_id: int, reference: ReferencePath, user: CurrentUser, db: DbSession):
    """One reservation with its history, the branch's stock against confirmed
    reservations and, once collected, the collection record."""
    return _pharmacy_detail(db, user, organization_id, reference)


def _act(db: Session, user: User, organization_id: int, reference: str, roles=ALL_ROLES) -> int:
    get_org_access(db, user, organization_id, roles=roles, org_type=OrganizationType.PHARMACY)
    return _org_reservation_id(db, organization_id, reference)


@pharmacy_router.post(
    "/{organization_id}/reservations/{reference}/confirm", response_model=PharmacyReservationDetail
)
def confirm_reservation(organization_id: int, reference: ReferencePath, user: CurrentUser, db: DbSession):
    """Allocate the requested quantity for 24 hours (any role). 409 when the
    unreserved stock no longer covers it, the medicine or branch is no longer
    eligible, the unit changed, or the response deadline passed."""
    reservation_id = _act(db, user, organization_id, reference)
    engine.confirm(db, user, organization_id, reservation_id)
    return _pharmacy_detail(db, user, organization_id, reference)


@pharmacy_router.post(
    "/{organization_id}/reservations/{reference}/decline", response_model=PharmacyReservationDetail
)
def decline_reservation(
    organization_id: int, reference: ReferencePath, payload: ReservationDecision, user: CurrentUser, db: DbSession
):
    """Decline a pending request with a reason the patient will see (any role)."""
    reservation_id = _act(db, user, organization_id, reference)
    engine.decline(db, user, organization_id, reservation_id, payload.reason)
    return _pharmacy_detail(db, user, organization_id, reference)


@pharmacy_router.post(
    "/{organization_id}/reservations/{reference}/cancel", response_model=PharmacyReservationDetail
)
def cancel_reservation(
    organization_id: int, reference: ReferencePath, payload: ReservationDecision, user: CurrentUser, db: DbSession
):
    """Cancel a CONFIRMED reservation with a reason (owners and managers)."""
    reservation_id = _act(db, user, organization_id, reference, roles=MANAGERS)
    engine.cancel_by_pharmacy(db, user, organization_id, reservation_id, payload.reason)
    return _pharmacy_detail(db, user, organization_id, reference)


@pharmacy_router.post(
    "/{organization_id}/reservations/{reference}/collect", response_model=PharmacyReservationDetail
)
def collect_reservation(
    organization_id: int,
    reference: ReferencePath,
    payload: CollectRequest,
    user: CurrentUser,
    db: DbSession,
):
    """Hand over the FULL quantity; the recorded stock is reduced by it in the
    same transaction. ``reference`` is the code the patient shows, typed by the
    staff member: the engine compares it with the reservation and refuses a
    mismatch (422 ``reference_mismatch``), so a reservation opened by mistake
    cannot be collected. If the recorded stock is too low: 409
    ``stock_record_insufficient``. Correct the stock after counting, or (owners
    and managers) send ``override`` with the physical count."""
    reservation_id = _act(db, user, organization_id, reference)
    override = None
    if payload.override is not None:
        o = payload.override
        override = CollectionOverride(
            verified_on_hand=o.verified_on_hand,
            recorded_quantity_seen=o.recorded_quantity_seen,
            reason=o.reason,
            physically_verified=o.physically_verified,
        )
    # The typed reference, never the one from the address, is what the engine checks.
    engine.collect(db, user, organization_id, reservation_id, reference=_normalize(payload.reference), override=override)
    return _pharmacy_detail(db, user, organization_id, reference)


# Branch unit acknowledgement --------------------------------------------------
def _ack_status(db: Session, location_id: int, product: Product) -> UnitAcknowledgementStatus:
    A = OfferUnitAcknowledgement
    current = db.execute(
        select(A, User.name)
        .outerjoin(User, User.user_id == A.acknowledged_by)
        .where(A.location_id == location_id, A.product_id == product.product_id, A.unit_version == product.unit_version)
    ).one_or_none()
    last = db.scalar(select(func.max(A.unit_version)).where(A.location_id == location_id, A.product_id == product.product_id))
    problem = engine.eligibility_problem(db, location_id, product.product_id)
    return UnitAcknowledgementStatus(
        location_id=location_id,
        product_id=product.product_id,
        product_name=product.product_name,
        current_unit=UnitInfo(
            unit_version=product.unit_version,
            stock_unit=product.stock_unit,
            unit_label=product.unit_label,
            pack_size=product.pack_size,
        ),
        acknowledged=current is not None,
        acknowledged_at=current[0].acknowledged_at if current else None,
        acknowledged_by_name=current[1] if current else None,
        last_acknowledged_version=last,
        reservable=problem is None,
        reason=problem,
        message=ELIGIBILITY_MESSAGES.get(problem) if problem else None,
    )


@pharmacy_router.get(
    "/{organization_id}/locations/{location_id}/reservation-units",
    response_model=Page[UnitAcknowledgementStatus],
)
def list_branch_units(organization_id: int, location_id: int, user: CurrentUser, db: DbSession, page: Pagination):
    """Each medicine this branch has a stock record for: its current unit,
    whether the branch acknowledged it and whether it can be reserved here."""
    _pharmacy_access(db, user, organization_id)
    get_org_location(db, organization_id, location_id)
    limit, offset = page
    stmt = select(Product).join(Stock, Stock.product_id == Product.product_id).where(Stock.location_id == location_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    products = db.scalars(stmt.order_by(Product.product_name, Product.product_id).limit(limit).offset(offset)).all()
    return Page(items=[_ack_status(db, location_id, p) for p in products], total=total, limit=limit, offset=offset)


def _branch_product(db: Session, organization_id: int, location_id: int, product_id: int) -> Product:
    get_org_location(db, organization_id, location_id)
    product = db.get(Product, product_id, populate_existing=True)
    if product is None:
        raise NotFound("Product not found.")
    return product


@pharmacy_router.get(
    "/{organization_id}/locations/{location_id}/products/{product_id}/unit-acknowledgement",
    response_model=UnitAcknowledgementStatus,
)
def get_unit_acknowledgement(organization_id: int, location_id: int, product_id: int, user: CurrentUser, db: DbSession):
    _pharmacy_access(db, user, organization_id)
    return _ack_status(db, location_id, _branch_product(db, organization_id, location_id, product_id))


@pharmacy_router.post(
    "/{organization_id}/locations/{location_id}/products/{product_id}/unit-acknowledgement",
    response_model=UnitAcknowledgementStatus,
)
def acknowledge_unit(
    organization_id: int,
    location_id: int,
    product_id: int,
    payload: UnitAcknowledgementRequest,
    user: CurrentUser,
    db: DbSession,
):
    """Confirm that this branch counts the medicine in the unit shown (owners
    and managers). Send back exactly the current ``unit_version``,
    ``stock_unit``, ``unit_label`` and ``pack_size``; anything stale or
    different is 409 ``unit_changed`` with the current values. Each unit
    version is acknowledged once; repeating it is harmless."""
    engine.acknowledge_unit(
        db,
        user,
        organization_id,
        location_id,
        product_id,
        unit_version=payload.unit_version,
        stock_unit=payload.stock_unit,
        unit_label=payload.unit_label,
        pack_size=payload.pack_size,
    )
    return _ack_status(db, location_id, _branch_product(db, organization_id, location_id, product_id))


# ---------------------------------------------------------------------------
# Catalogue reservation settings (platform admins edit; signed-in users read)
# ---------------------------------------------------------------------------
def _settings(product: Product) -> ReservationSettings:
    problems = engine.settings_problems(product)
    return ReservationSettings(
        product_id=product.product_id,
        is_active=product.is_active,
        dispensing_class=product.dispensing_class,
        unit_version=product.unit_version,
        stock_unit=product.stock_unit,
        unit_label=product.unit_label,
        pack_size=product.pack_size,
        max_reservation_quantity=product.max_reservation_quantity,
        reservation_enabled=product.reservation_enabled,
        can_enable=not problems,
        problems=[SettingsProblem(code=p, message=SETTINGS_PROBLEMS[p]) for p in problems],
    )


@settings_router.get("/products/{product_id}/reservation-settings", response_model=ReservationSettings)
def get_reservation_settings(product_id: int, _: CurrentUser, db: DbSession):
    """The medicine's classification and unit, and why reservations cannot
    be enabled yet (``problems``)."""
    product = db.get(Product, product_id)
    if product is None:
        raise NotFound("Product not found.")
    return _settings(product)


@settings_router.patch("/products/{product_id}/reservation-settings", response_model=ReservationSettings)
def update_reservation_settings(product_id: int, payload: ReservationSettingsUpdate, admin: AdminUser, db: DbSession):
    """Platform admins only (the catalogue is shared by every pharmacy). A
    change of unit, unit name or (for packs) pack size is refused while
    reservations are open and starts a new ``unit_version``, which every branch
    must acknowledge again. Every change is audited."""
    changes = payload.model_dump(exclude_unset=True)
    for key in ("dispensing_class", "stock_unit", "reservation_enabled"):
        if key in changes and changes[key] is None:
            raise AppError(f"{key} cannot be null.", status_code=422, extra={"code": "invalid_reservation_settings"})
    product = engine.configure_product(db, admin, product_id, **changes)
    return _settings(product)


@settings_router.get(
    "/products/{product_id}/reservation-settings/history", response_model=list[ReservationSettingsHistory]
)
def reservation_settings_history(product_id: int, _: AdminUser, db: DbSession):
    """The audit trail of the medicine's reservation settings, newest first."""
    if db.get(Product, product_id) is None:
        raise NotFound("Product not found.")
    H = ProductReservationHistory
    rows = db.execute(
        select(H, User.name)
        .outerjoin(User, User.user_id == H.changed_by)
        .where(H.product_id == product_id)
        .order_by(H.changed_at.desc(), H.history_id.desc())
    ).all()
    return [
        ReservationSettingsHistory(
            dispensing_class=h.dispensing_class,
            stock_unit=h.stock_unit,
            unit_label=h.unit_label,
            pack_size=h.pack_size,
            unit_version=h.unit_version,
            max_reservation_quantity=h.max_reservation_quantity,
            reservation_enabled=h.reservation_enabled,
            changed_by_name=name,
            changed_at=h.changed_at,
        )
        for h, name in rows
    ]

