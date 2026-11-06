"""Platform administration: verify organizations and documents, manage access."""

from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import func, or_, select

from app.api.auth import normalize_email
from app.api.catalogue import contains
from app.api.deps import AdminUser, DbSession, Pagination
from app.api.organizations import DOCUMENT_RESPONSES, document_file_response, list_member_responses
from app.core.errors import AppError, Conflict, NotFound
from app.models import Location, Organization, OrganizationDocument, SearchEvent, User
from app.models.enums import DocumentStatus, OrganizationStatus, OrganizationType
from app.schemas.admin import (
    AdminDocumentResponse,
    AdminOrganizationDetail,
    AdminUserUpdate,
    DocumentReview,
    OrganizationDecision,
    OrganizationReview,
    SearchInsight,
)
from app.schemas.auth import UserResponse
from app.schemas.common import Page
from app.schemas.organizations import (
    DocumentResponse,
    LocationResponse,
    OrganizationResponse,
)

router = APIRouter()

# Which review decisions are valid from each status.
ORG_TRANSITIONS = {
    OrganizationStatus.PENDING: {OrganizationDecision.APPROVED, OrganizationDecision.REJECTED},
    OrganizationStatus.APPROVED: {OrganizationDecision.SUSPENDED},
    OrganizationStatus.SUSPENDED: {OrganizationDecision.APPROVED, OrganizationDecision.REJECTED},
    OrganizationStatus.REJECTED: {OrganizationDecision.APPROVED},
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Organizations
# ---------------------------------------------------------------------------
@router.get("/organizations", response_model=Page[OrganizationResponse])
def list_organizations(
    _: AdminUser,
    db: DbSession,
    page: Pagination,
    status: OrganizationStatus | None = None,
    type: OrganizationType | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
):
    """Registration review queue (oldest first, so pending requests are FIFO)."""
    limit, offset = page
    stmt = select(Organization)
    if status:
        stmt = stmt.where(Organization.status == status)
    if type:
        stmt = stmt.where(Organization.type == type)
    if q and q.strip():
        stmt = stmt.where(or_(Organization.name.ilike(contains(q)), Organization.email.ilike(contains(q))))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    items = db.scalars(
        stmt.order_by(Organization.created_at, Organization.organization_id).limit(limit).offset(offset)
    ).all()
    return Page(items=items, total=total, limit=limit, offset=offset)


def _organization_detail(db, organization: Organization) -> AdminOrganizationDetail:
    locations = db.scalars(
        select(Location).where(Location.organization_id == organization.organization_id).order_by(Location.name)
    ).all()
    documents = db.scalars(
        select(OrganizationDocument)
        .where(OrganizationDocument.organization_id == organization.organization_id)
        .order_by(OrganizationDocument.uploaded_at.desc())
    ).all()
    return AdminOrganizationDetail(
        **OrganizationResponse.model_validate(organization).model_dump(),
        reviewed_by=organization.reviewed_by,
        members=list_member_responses(db, organization.organization_id),
        locations=[LocationResponse.model_validate(l) for l in locations],
        documents=[DocumentResponse.model_validate(d) for d in documents],
    )


@router.get("/organizations/{organization_id}", response_model=AdminOrganizationDetail)
def get_organization(organization_id: int, _: AdminUser, db: DbSession):
    organization = db.get(Organization, organization_id)
    if organization is None:
        raise NotFound("Organization not found.")
    return _organization_detail(db, organization)


@router.post("/organizations/{organization_id}/review", response_model=AdminOrganizationDetail)
def review_organization(
    organization_id: int, payload: OrganizationReview, admin: AdminUser, db: DbSession
):
    """Approve, reject or suspend an organization. Only approved organizations
    can publish stock/offers, search suppliers and send or receive orders."""
    organization = db.scalar(
        select(Organization).where(Organization.organization_id == organization_id).with_for_update()
    )
    if organization is None:
        raise NotFound("Organization not found.")
    current = OrganizationStatus(organization.status)
    if payload.decision not in ORG_TRANSITIONS[current]:
        raise Conflict(f"Cannot mark a '{current}' organization as '{payload.decision}'.")

    if payload.decision == OrganizationDecision.APPROVED:
        pending_docs = db.scalar(
            select(func.count())
            .select_from(OrganizationDocument)
            .where(
                OrganizationDocument.organization_id == organization_id,
                OrganizationDocument.verification_status == DocumentStatus.PENDING,
            )
        )
        if pending_docs:
            raise Conflict(f"Review the {pending_docs} pending document(s) before approving.")

    organization.status = payload.decision.value
    organization.reviewed_at = _now()
    organization.reviewed_by = admin.user_id
    organization.review_notes = payload.notes
    db.commit()
    return _organization_detail(db, organization)


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------
@router.get("/documents", response_model=Page[AdminDocumentResponse])
def list_documents(
    _: AdminUser,
    db: DbSession,
    page: Pagination,
    status: DocumentStatus | None = DocumentStatus.PENDING,
    organization_id: int | None = None,
):
    limit, offset = page
    stmt = select(OrganizationDocument, Organization).join(
        Organization, Organization.organization_id == OrganizationDocument.organization_id
    )
    if status:
        stmt = stmt.where(OrganizationDocument.verification_status == status)
    if organization_id is not None:
        stmt = stmt.where(OrganizationDocument.organization_id == organization_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.execute(
        stmt.order_by(OrganizationDocument.uploaded_at, OrganizationDocument.document_id)
        .limit(limit)
        .offset(offset)
    ).all()
    items = [
        AdminDocumentResponse(
            **DocumentResponse.model_validate(d).model_dump(),
            organization_name=o.name,
            organization_type=o.type,
            reviewed_by=d.reviewed_by,
        )
        for d, o in rows
    ]
    return Page(items=items, total=total, limit=limit, offset=offset)


def _get_document(db, document_id: int) -> OrganizationDocument:
    document = db.get(OrganizationDocument, document_id)
    if document is None:
        raise NotFound("Document not found.")
    return document


@router.get("/documents/{document_id}/download", responses=DOCUMENT_RESPONSES)
def download_document(document_id: int, _: AdminUser, db: DbSession):
    return document_file_response(_get_document(db, document_id))


@router.post("/documents/{document_id}/review", response_model=DocumentResponse)
def review_document(document_id: int, payload: DocumentReview, admin: AdminUser, db: DbSession):
    document = _get_document(db, document_id)
    if document.verification_status != DocumentStatus.PENDING:
        raise Conflict("This document has already been reviewed.")
    document.verification_status = payload.decision.value
    document.reviewed_at = _now()
    document.reviewed_by = admin.user_id
    document.rejection_reason = payload.rejection_reason if payload.decision == "rejected" else None
    db.commit()
    return document


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
@router.get("/users", response_model=Page[UserResponse])
def list_users(
    _: AdminUser,
    db: DbSession,
    page: Pagination,
    q: Annotated[str | None, Query(max_length=100)] = None,
    is_platform_admin: bool | None = None,
):
    limit, offset = page
    stmt = select(User)
    if q and q.strip():
        stmt = stmt.where(or_(User.name.ilike(contains(q)), User.email.ilike(contains(normalize_email(q)))))
    if is_platform_admin is not None:
        stmt = stmt.where(User.is_platform_admin.is_(is_platform_admin))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    items = db.scalars(stmt.order_by(User.created_at, User.user_id).limit(limit).offset(offset)).all()
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.patch("/users/{user_id}", response_model=UserResponse)
def update_user(user_id: int, payload: AdminUserUpdate, admin: AdminUser, db: DbSession):
    """Deactivate/reactivate accounts or grant/revoke platform admin."""
    target = db.get(User, user_id)
    if target is None:
        raise NotFound("User not found.")
    data = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    if target.user_id == admin.user_id and (
        data.get("is_active") is False or data.get("is_platform_admin") is False
    ):
        raise AppError("You cannot deactivate yourself or remove your own admin access.")
    for field, value in data.items():
        setattr(target, field, value)
    db.commit()
    return target


# ---------------------------------------------------------------------------
# Demand signal
# ---------------------------------------------------------------------------
@router.get("/insights/searches", response_model=list[SearchInsight])
def search_insights(
    _: AdminUser,
    db: DbSession,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    only_unmet: Annotated[bool, Query(description="Only searches that found nothing")] = False,
):
    """Most searched medicines by patients (anonymous), incl. unmet demand."""
    since = _now() - timedelta(days=days)
    query = func.lower(func.btrim(SearchEvent.query_text))
    zero = func.count().filter(SearchEvent.results_count == 0)
    stmt = (
        select(
            query.label("query"),
            func.count().label("searches"),
            zero.label("zero_result_searches"),
            func.max(SearchEvent.created_at).label("last_searched_at"),
        )
        .where(SearchEvent.created_at >= since)
        .group_by(query)
    )
    if only_unmet:
        stmt = stmt.having(zero > 0)
    rows = db.execute(stmt.order_by(func.count().desc(), query).limit(limit)).all()
    return [SearchInsight(**r._mapping) for r in rows]
