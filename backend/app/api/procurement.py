"""Procurement requests and quotations between a pharmacy and a supplier.
See app.services.procurement for the workflow rules.

Every status change goes through one of the action routes below, each of
which checks the side, the role and the current status; there is no route
that sets a status directly.
"""

from typing import Annotated

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import CurrentUser, DbSession, Pagination, get_org_access
from app.core.config import settings
from app.core.errors import NotFound, TooManyRequests
from app.core.rate_limit import procurement_limiter
from app.models import Location, Organization, ProcurementRequest, Product, PurchaseOrder, Quotation, User
from app.models.enums import OrganizationType
from app.schemas.common import Page
from app.schemas.procurement import (
    ConvertInput,
    ConvertResponse,
    NoteInput,
    Party,
    ProcurementRequestCreate,
    ProcurementRequestResponse,
    ProcurementRequestSummary,
    QuotationInput,
    QuotationItemResponse,
    QuotationResponse,
    ReasonInput,
    RequestItemResponse,
)
from app.services import messaging
from app.services import orders as order_svc
from app.services import procurement as svc
from app.services.procurement import Q, R

router = APIRouter()


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------
def _party(db: Session, organization_id: int, location_id: int | None = None) -> Party:
    org = db.get(Organization, organization_id)
    location = db.get(Location, location_id) if location_id else None
    return Party(
        organization_id=org.organization_id,
        name=org.name,
        location_id=location.location_id if location else None,
        location_name=location.name if location else None,
    )


def _visible_quotations(req: ProcurementRequest, side: str) -> list[Quotation]:
    """The pharmacy never sees the supplier's unsent draft."""
    return [q for q in req.quotations if side == "supplier" or q.status != Q.DRAFT]


def _needs_me(req: ProcurementRequest, side: str) -> bool:
    if side == "supplier":
        return req.status in (R.SUBMITTED, R.VIEWED, R.NEGOTIATION)
    return req.status in (R.QUOTED, R.ACCEPTED)


def _summary(db: Session, req: ProcurementRequest, side: str, orders: dict[int, int] | None = None) -> dict:
    shown = _visible_quotations(req, side)
    latest = shown[-1] if shown else None
    order_id = orders.get(req.procurement_request_id) if orders is not None else db.scalar(
        select(PurchaseOrder.purchase_order_id).where(
            PurchaseOrder.procurement_request_id == req.procurement_request_id
        )
    )
    return dict(
        procurement_request_id=req.procurement_request_id,
        status=req.status,
        pharmacy=_party(db, req.pharmacy_organization_id, req.pharmacy_location_id),
        supplier=_party(db, req.supplier_organization_id),
        conversation_id=req.conversation_id,
        item_count=len(req.items),
        currency=req.currency,
        latest_quotation_status=latest.status if latest else None,
        latest_quotation_total=svc.totals(latest) if latest else None,
        purchase_order_id=order_id,
        created_at=req.created_at,
        updated_at=req.updated_at,
        needs_my_action=_needs_me(req, side),
    )


def request_response(db: Session, user: User, req: ProcurementRequest, side: str) -> ProcurementRequestResponse:
    db.expire(req)  # reload items and quotations after changes
    quotations = _visible_quotations(req, side)
    user_ids = {req.created_by} | {u for q in quotations for u in (q.submitted_by, q.responded_by)}
    names = dict(db.execute(select(User.user_id, User.name).where(User.user_id.in_(user_ids - {None}))).all())
    return ProcurementRequestResponse(
        **_summary(db, req, side),
        notes=req.notes,
        needed_by=req.needed_by,
        status_reason=req.status_reason,
        created_by_name=names.get(req.created_by),
        viewed_at=req.viewed_at,
        items=[
            RequestItemResponse(
                procurement_request_item_id=i.procurement_request_item_id,
                line_no=i.line_no,
                product_id=i.product_id,
                in_catalogue=i.product_id is not None,
                medicine_name=i.medicine_name,
                strength=i.strength,
                dosage_form=i.dosage_form,
                pack_size=i.pack_size,
                quantity=i.quantity,
                notes=i.notes,
            )
            for i in req.items
        ],
        quotations=[
            QuotationResponse(
                quotation_id=q.quotation_id,
                revision=q.revision,
                status=q.status,
                currency=q.currency,
                note=q.note,
                estimated_days=q.estimated_days,
                total=svc.totals(q),
                submitted_by_name=names.get(q.submitted_by),
                submitted_at=q.submitted_at,
                responded_by_name=names.get(q.responded_by),
                responded_at=q.responded_at,
                response_note=q.response_note,
                updated_at=q.updated_at,
                items=[
                    QuotationItemResponse(
                        quotation_item_id=i.quotation_item_id,
                        procurement_request_item_id=i.procurement_request_item_id,
                        available=i.available,
                        quantity=i.quantity,
                        unit_price=i.unit_price,
                        line_total=i.quantity * i.unit_price if i.available else None,
                        note=i.note,
                    )
                    for i in q.items
                ],
            )
            for q in quotations
        ],
        allowed_actions=svc.allowed_actions(db, user, req, side),
    )


# ---------------------------------------------------------------------------
# Create / list / read
# ---------------------------------------------------------------------------
@router.post("", response_model=ProcurementRequestResponse, status_code=status.HTTP_201_CREATED)
def create_request(payload: ProcurementRequestCreate, user: CurrentUser, db: DbSession):
    """A pharmacy asks one supplier for prices on one or more medicines. Items
    may be catalogue products or medicines described in words; the supplier
    does not need to list them. Any active member of an approved pharmacy may
    send requests (at most 30 an hour per user)."""
    get_org_access(db, user, payload.pharmacy_organization_id, org_type=OrganizationType.PHARMACY,
                   require_approved=True)
    supplier = order_svc.get_supplier(db, payload.supplier_organization_id)
    order_svc.check_location(db, payload.pharmacy_location_id, payload.pharmacy_organization_id, "Pharmacy")
    product_ids = [i.product_id for i in payload.items if i.product_id is not None]
    products = {p.product_id: p for p in db.scalars(select(Product).where(Product.product_id.in_(product_ids)))}
    missing = [pid for pid in product_ids if pid not in products or not products[pid].is_active]
    if missing:
        raise NotFound(f"Catalogue product {missing[0]} not found.")
    wait = procurement_limiter.hit(str(user.user_id))
    if wait is not None:
        raise TooManyRequests("Too many requests sent. Please try again later.", headers={"Retry-After": str(wait)})

    conv, _ = messaging.get_or_create_conversation(
        db, payload.pharmacy_organization_id, supplier.organization_id, user.user_id
    )
    req = ProcurementRequest(
        pharmacy_organization_id=payload.pharmacy_organization_id,
        supplier_organization_id=supplier.organization_id,
        pharmacy_location_id=payload.pharmacy_location_id,
        conversation_id=conv.conversation_id,
        status=R.SUBMITTED,
        currency=settings.default_currency,
        notes=payload.notes,
        needed_by=payload.needed_by,
        created_by=user.user_id,
    )
    db.add(req)
    db.flush()
    svc.add_items(db, req, payload.items, products)
    messaging.notify(db, supplier.organization_id, "request_submitted", payload.pharmacy_organization_id,
                     procurement_request_id=req.procurement_request_id, conversation_id=conv.conversation_id)
    db.commit()
    return request_response(db, user, req, "pharmacy")


@router.get("", response_model=Page[ProcurementRequestSummary])
def list_requests(
    user: CurrentUser,
    db: DbSession,
    page: Pagination,
    organization_id: Annotated[int, Query(description="Your pharmacy or supplier organization")],
    status_filter: Annotated[list[svc.RequestStatus] | None, Query(alias="status")] = None,
    counterpart_organization_id: int | None = None,
):
    """Requests sent (pharmacy) or received (supplier), newest first."""
    access = get_org_access(db, user, organization_id, require_approved=True)
    side = "pharmacy" if access.organization.type == OrganizationType.PHARMACY else "supplier"
    own = ProcurementRequest.pharmacy_organization_id if side == "pharmacy" else ProcurementRequest.supplier_organization_id
    other = ProcurementRequest.supplier_organization_id if side == "pharmacy" else ProcurementRequest.pharmacy_organization_id
    stmt = select(ProcurementRequest).where(own == organization_id)
    if status_filter:
        stmt = stmt.where(ProcurementRequest.status.in_([s.value for s in status_filter]))
    if counterpart_organization_id is not None:
        stmt = stmt.where(other == counterpart_organization_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    limit, offset = page
    rows = db.scalars(
        stmt.order_by(ProcurementRequest.created_at.desc(), ProcurementRequest.procurement_request_id.desc())
        .limit(limit)
        .offset(offset)
        # The dashboards poll this list: load items and quotations up front.
        .options(selectinload(ProcurementRequest.items),
                 selectinload(ProcurementRequest.quotations).selectinload(Quotation.items))
    ).all()
    orders = dict(db.execute(
        select(PurchaseOrder.procurement_request_id, PurchaseOrder.purchase_order_id)
        .where(PurchaseOrder.procurement_request_id.in_([r.procurement_request_id for r in rows]))
    ).all()) if rows else {}
    return Page(items=[ProcurementRequestSummary(**_summary(db, r, side, orders)) for r in rows],
                total=total, limit=limit, offset=offset)


@router.get("/{request_id}", response_model=ProcurementRequestResponse)
def get_request(request_id: int, user: CurrentUser, db: DbSession):
    req, side = svc.load_request(db, user, request_id)
    return request_response(db, user, req, side)


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------
def _act(db: Session, user: User, request_id: int, side: str, action: str, *, manager: bool = False):
    req, my_side = svc.load_request(db, user, request_id, for_update=True)
    svc.require(my_side, side, action)
    if manager:
        svc.require_manager(db, user, req, action)
    messaging.require_approved(db, svc.own_org(req, my_side))
    return req, my_side


@router.post("/{request_id}/viewed", response_model=ProcurementRequestResponse)
def mark_viewed(request_id: int, user: CurrentUser, db: DbSession):
    """Supplier opened the request (submitted becomes viewed). Idempotent."""
    req, side = svc.load_request(db, user, request_id, for_update=True)
    if side == "supplier":
        svc.mark_viewed(db, req)
        db.commit()
    return request_response(db, user, req, side)


@router.post("/{request_id}/quotation", response_model=ProcurementRequestResponse)
def save_quotation(request_id: int, payload: QuotationInput, user: CurrentUser, db: DbSession):
    """Supplier answers every requested item (price and quantity, or
    unavailable). ``submit`` false saves a draft the pharmacy cannot see;
    ``submit`` true sends it, and the previous revision becomes superseded."""
    req, side = _act(db, user, request_id, "supplier", "quote")
    messaging.require_approved(db, req.pharmacy_organization_id)
    svc.save_quotation(db, user, req, payload)
    db.commit()
    return request_response(db, user, req, side)


@router.post("/{request_id}/decline", response_model=ProcurementRequestResponse)
def decline_request(request_id: int, payload: ReasonInput, user: CurrentUser, db: DbSession):
    """Supplier cannot supply any of it."""
    req, side = _act(db, user, request_id, "supplier", "decline")
    svc.decline(db, req, payload.reason)
    db.commit()
    return request_response(db, user, req, side)


@router.post("/{request_id}/cancel", response_model=ProcurementRequestResponse)
def cancel_request(request_id: int, payload: ReasonInput, user: CurrentUser, db: DbSession):
    """Pharmacy withdraws the request (owners and managers)."""
    req, side = _act(db, user, request_id, "pharmacy", "cancel requests", manager=True)
    svc.cancel(db, req, payload.reason)
    db.commit()
    return request_response(db, user, req, side)


@router.post("/{request_id}/quotations/{quotation_id}/request-revision", response_model=ProcurementRequestResponse)
def request_revision(request_id: int, quotation_id: int, user: CurrentUser, db: DbSession,
                     payload: NoteInput | None = None):
    """Pharmacy asks the supplier to revise the latest quotation."""
    req, side = _act(db, user, request_id, "pharmacy", "ask for a revision")
    svc.request_revision(db, user, req, quotation_id, payload.note if payload else None)
    db.commit()
    return request_response(db, user, req, side)


@router.post("/{request_id}/quotations/{quotation_id}/accept", response_model=ProcurementRequestResponse)
def accept_quotation(request_id: int, quotation_id: int, user: CurrentUser, db: DbSession,
                     payload: NoteInput | None = None):
    """Pharmacy accepts the latest quotation (owners and managers). No order
    is created yet: that is the separate convert step."""
    req, side = _act(db, user, request_id, "pharmacy", "accept quotations", manager=True)
    messaging.require_approved(db, req.supplier_organization_id)
    svc.accept(db, user, req, quotation_id, payload.note if payload else None)
    db.commit()
    return request_response(db, user, req, side)


@router.post("/{request_id}/quotations/{quotation_id}/reject", response_model=ProcurementRequestResponse)
def reject_quotation(request_id: int, quotation_id: int, payload: ReasonInput, user: CurrentUser, db: DbSession):
    """Pharmacy rejects the quotation, which closes the request (owners and managers)."""
    req, side = _act(db, user, request_id, "pharmacy", "reject quotations", manager=True)
    svc.reject(db, user, req, quotation_id, payload.reason)
    db.commit()
    return request_response(db, user, req, side)


@router.post("/{request_id}/convert", response_model=ConvertResponse)
def convert_to_order(request_id: int, user: CurrentUser, db: DbSession, response: Response,
                     payload: ConvertInput | None = None):
    """Create the supplier order from the accepted quotation (owners and
    managers). The order has the quoted quantities and prices, refers back to
    the request and quotation, and is already accepted, so the supplier goes
    on to prepare and dispatch it in Orders. Repeating the call returns the
    same order (200) instead of creating another (201)."""
    req, side = _act(db, user, request_id, "pharmacy", "create orders from quotations", manager=True)
    messaging.require_approved(db, req.supplier_organization_id)
    order, created = svc.convert(db, user, req, payload.pharmacy_location_id if payload else None)
    db.commit()
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return ConvertResponse(purchase_order_id=order.purchase_order_id, created=created,
                           request=request_response(db, user, req, side))
