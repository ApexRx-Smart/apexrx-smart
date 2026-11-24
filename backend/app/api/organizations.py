"""Organization registration and setup: profile, members, locations, documents."""

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, File, Form, Response, UploadFile, status
from sqlalchemy import delete, func, select

from app.api.auth import find_user_by_email
from app.api.deps import (
    ALL_ROLES,
    MANAGERS,
    OWNERS,
    CurrentUser,
    DbSession,
    get_org_access,
    get_org_location,
)
from app.core.config import settings
from app.core.errors import AppError, Conflict, Forbidden, NotFound
from app.models import Location, Membership, MembershipBranch, Organization, OrganizationDocument, User
from app.models.enums import DocumentStatus, MembershipRole, OrganizationStatus, OrganizationType
from app.schemas.common import Message
from app.schemas.organizations import (
    ApplicationDocument,
    ApplicationResponse,
    BranchAssignment,
    DocumentResponse,
    LocationCreate,
    LocationResponse,
    LocationUpdate,
    MemberCreate,
    MemberResponse,
    MemberUpdate,
    MyOrganizationResponse,
    OrganizationCreate,
    OrganizationResponse,
    OrganizationUpdate,
)
from app.services import applications, messaging, reservations, storage
from app.services.phone import PhoneNumberError, normalize_phone

router = APIRouter()


# ---------------------------------------------------------------------------
# Organizations
# ---------------------------------------------------------------------------
def _contact_phone(raw: str | None) -> str | None:
    """Business contact number (also for future Mobile Money), stored in E.164.
    Not a verification: nobody proves they own it."""
    if raw is None or not raw.strip():
        return None
    try:
        return normalize_phone(raw, mobile_only=False)
    except PhoneNumberError as exc:
        raise AppError(str(exc), status_code=status.HTTP_422_UNPROCESSABLE_CONTENT) from None


@router.post("", response_model=MyOrganizationResponse, status_code=status.HTTP_201_CREATED)
def create_organization(payload: OrganizationCreate, user: CurrentUser, db: DbSession):
    """Register a pharmacy or supplier organization. The caller becomes its
    owner. The organization stays ``pending`` until an ApexRx admin approves it.

    The caller's account email must be verified first (when
    EMAIL_VERIFICATION_REQUIRED is on; see app/api/email_verification.py)."""
    if user.account_type != payload.type:
        raise Forbidden(
            f"This account can't register a {payload.type}. Sign up on the {payload.type} registration page.",
            extra={"code": "wrong_account_type"},
        )
    if settings.email_verification_required and user.email_verified_at is None:
        raise Forbidden(
            "Verify your email address before registering an organization.",
            extra={"reason": "email_unverified"},
        )
    phone = _contact_phone(payload.phone)
    organization = Organization(
        name=payload.name,
        type=payload.type,
        phone=phone,
        email=str(payload.email).lower() if payload.email else None,
    )
    db.add(organization)
    db.flush()
    db.add(
        Membership(
            user_id=user.user_id,
            organization_id=organization.organization_id,
            role=MembershipRole.OWNER,
        )
    )
    db.commit()
    return MyOrganizationResponse(
        **OrganizationResponse.model_validate(organization).model_dump(), my_role=MembershipRole.OWNER
    )


@router.get("", response_model=list[MyOrganizationResponse])
def list_my_organizations(user: CurrentUser, db: DbSession):
    rows = db.execute(
        select(Organization, Membership.role)
        .join(Membership, Membership.organization_id == Organization.organization_id)
        .where(Membership.user_id == user.user_id, Membership.is_active.is_(True))
        .order_by(Organization.name)
    ).all()
    return [
        MyOrganizationResponse(**OrganizationResponse.model_validate(org).model_dump(), my_role=role)
        for org, role in rows
    ]


@router.get("/{organization_id}", response_model=OrganizationResponse)
def get_organization(organization_id: int, user: CurrentUser, db: DbSession):
    return get_org_access(db, user, organization_id, allow_admin_read=True).organization


@router.patch("/{organization_id}", response_model=OrganizationResponse)
def update_organization(organization_id: int, payload: OrganizationUpdate, user: CurrentUser, db: DbSession):
    organization = get_org_access(db, user, organization_id, roles=MANAGERS).organization
    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"] is None:
        raise AppError("name cannot be null.")
    if data.get("email"):
        data["email"] = str(data["email"]).lower()
    if "phone" in data:
        data["phone"] = _contact_phone(data["phone"])
    for field, value in data.items():
        setattr(organization, field, value)
    db.commit()
    return organization


def _application(db, organization: Organization) -> ApplicationResponse:
    items = applications.checklist(db, organization)
    complete = not applications.missing(items)
    stage = applications.stage(organization)
    return ApplicationResponse(
        organization_id=organization.organization_id,
        name=organization.name,
        type=organization.type,
        status=organization.status,
        stage=stage,
        submitted_at=organization.submitted_at,
        reviewed_at=organization.reviewed_at,
        review_notes=organization.review_notes,
        required_documents=[ApplicationDocument(**vars(i)) for i in items],
        documents_complete=complete,
        can_submit=complete and stage in ("in_progress", "rejected"),
        workspace_open=organization.status == OrganizationStatus.APPROVED,
    )


@router.get("/{organization_id}/application", response_model=ApplicationResponse)
def get_application(organization_id: int, user: CurrentUser, db: DbSession):
    """Where the registration stands: its stage, the review outcome and notes,
    and each required document's status. Open to members in every status (it
    is what a pending, rejected or suspended business sees)."""
    organization = get_org_access(db, user, organization_id, allow_admin_read=True).organization
    return _application(db, organization)


@router.post("/{organization_id}/submit", response_model=ApplicationResponse)
def submit_application(organization_id: int, user: CurrentUser, db: DbSession):
    """Submit the registration for review by ApexRX (owners and managers).

    Refused (409 documents_missing) until every required document is uploaded
    (one not rejected of each type). A rejected registration is resubmitted the
    same way: it goes back to 'pending', awaiting review; earlier review notes
    are kept until the next decision."""
    organization = db.scalar(
        select(Organization).where(Organization.organization_id == organization_id).with_for_update()
    )
    if organization is None:
        raise NotFound("Organization not found.")
    get_org_access(db, user, organization_id, roles=MANAGERS)
    stage = applications.stage(organization)
    if stage == "awaiting_review":
        raise Conflict("Your application is already waiting for review.", extra={"code": "already_submitted"})
    if stage not in ("in_progress", "rejected"):
        raise Conflict(f"This organization is {organization.status}; there is nothing to submit.",
                       extra={"code": "not_submittable"})
    missing = applications.missing(applications.checklist(db, organization))
    if missing:
        names = ", ".join(i.label for i in missing)
        raise Conflict(f"Upload every required document before submitting. Missing: {names}.",
                       extra={"code": "documents_missing", "missing": [i.document_type for i in missing]})
    organization.status = OrganizationStatus.PENDING
    organization.submitted_at = func.now()
    db.commit()
    db.refresh(organization)
    return _application(db, organization)


@router.post("/{organization_id}/resubmit", response_model=OrganizationResponse)
def resubmit_organization(organization_id: int, user: CurrentUser, db: DbSession):
    """Send a rejected registration back to the review queue. The same rules as
    POST /{organization_id}/submit (every required document uploaded)."""
    organization = get_org_access(db, user, organization_id, roles=MANAGERS).organization
    if organization.status != OrganizationStatus.REJECTED:
        raise Conflict("Only rejected organizations can be resubmitted for review.")
    submit_application(organization_id, user, db)
    db.refresh(organization)
    return organization


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------
def _branch_ids(db, membership_ids: list[int]) -> dict[int, list[int]]:
    out: dict[int, list[int]] = {}
    for mid, lid in db.execute(select(MembershipBranch.membership_id, MembershipBranch.location_id)
                               .where(MembershipBranch.membership_id.in_(membership_ids))
                               .order_by(MembershipBranch.location_id)):
        out.setdefault(mid, []).append(lid)
    return out


def _member_response(membership: Membership, member: User, branch_ids: list[int] | None = None) -> MemberResponse:
    return MemberResponse(
        membership_id=membership.membership_id,
        user_id=member.user_id,
        name=member.name,
        email=member.email,
        phone=member.phone,
        role=membership.role,
        is_active=membership.is_active,
        created_at=membership.created_at,
        branch_ids=branch_ids or [],
    )


def _member_out(db, membership: Membership, member: User) -> MemberResponse:
    return _member_response(membership, member, _branch_ids(db, [membership.membership_id]).get(membership.membership_id))


def list_member_responses(db, organization_id: int) -> list[MemberResponse]:
    rows = db.execute(
        select(Membership, User)
        .join(User, User.user_id == Membership.user_id)
        .where(Membership.organization_id == organization_id)
        .order_by(Membership.created_at)
    ).all()
    branches = _branch_ids(db, [m.membership_id for m, _ in rows])
    return [_member_response(m, u, branches.get(m.membership_id)) for m, u in rows]


def _assert_can_manage(actor_role: MembershipRole, target_role: MembershipRole) -> None:
    """Owners manage everyone; managers manage staff only."""
    if actor_role == MembershipRole.OWNER:
        return
    if actor_role == MembershipRole.MANAGER and target_role == MembershipRole.STAFF:
        return
    raise Forbidden("Managers can only manage staff members; owners can manage everyone.")


def _active_owner_count(db, organization_id: int, excluding_membership_id: int | None = None) -> int:
    stmt = (
        select(func.count())
        .select_from(Membership)
        .where(
            Membership.organization_id == organization_id,
            Membership.role == MembershipRole.OWNER,
            Membership.is_active.is_(True),
        )
    )
    if excluding_membership_id is not None:
        stmt = stmt.where(Membership.membership_id != excluding_membership_id)
    return db.scalar(stmt)


def _get_membership(db, organization_id: int, membership_id: int) -> Membership:
    membership = db.get(Membership, membership_id)
    if membership is None or membership.organization_id != organization_id:
        raise NotFound("Member not found.")
    return membership


@router.get("/{organization_id}/members", response_model=list[MemberResponse])
def list_members(organization_id: int, user: CurrentUser, db: DbSession):
    get_org_access(db, user, organization_id, allow_admin_read=True)
    return list_member_responses(db, organization_id)


@router.post("/{organization_id}/members", response_model=MemberResponse, status_code=status.HTTP_201_CREATED)
def add_member(organization_id: int, payload: MemberCreate, user: CurrentUser, db: DbSession):
    """Give an existing ApexRx user access to the organization. Each staff
    member uses their own account; accounts are never shared."""
    access = get_org_access(db, user, organization_id, roles=MANAGERS)
    _assert_can_manage(access.role, payload.role)

    member = find_user_by_email(db, payload.email)
    if member is None or not member.is_active:
        raise NotFound("No active ApexRx account uses that email. Ask them to register first.")
    if member.account_type != access.organization.type:
        raise Conflict(f"The account using that email can't join a {access.organization.type}. "
                       "Invite them with an email address that has no ApexRX account yet.",
                       extra={"code": "wrong_account_type"})

    membership = db.scalar(
        select(Membership).where(
            Membership.organization_id == organization_id, Membership.user_id == member.user_id
        )
    )
    if membership is not None:
        if membership.is_active:
            raise Conflict("This user is already a member of the organization.")
        _assert_can_manage(access.role, MembershipRole(membership.role))
        membership.is_active = True
        membership.role = payload.role
    else:
        membership = Membership(user_id=member.user_id, organization_id=organization_id, role=payload.role)
        db.add(membership)
    db.flush()
    messaging.assign_only_branch(db, membership)
    db.commit()
    return _member_out(db, membership, member)


@router.patch("/{organization_id}/members/{membership_id}", response_model=MemberResponse)
def update_member(
    organization_id: int,
    membership_id: int,
    payload: MemberUpdate,
    user: CurrentUser,
    db: DbSession,
):
    access = get_org_access(db, user, organization_id, roles=MANAGERS)
    membership = _get_membership(db, organization_id, membership_id)
    current_role = MembershipRole(membership.role)
    _assert_can_manage(access.role, current_role)
    if payload.role is not None:
        _assert_can_manage(access.role, payload.role)

    new_role = payload.role or current_role
    new_active = membership.is_active if payload.is_active is None else payload.is_active
    loses_owner = current_role == MembershipRole.OWNER and (
        new_role != MembershipRole.OWNER or not new_active
    )
    if loses_owner and _active_owner_count(db, organization_id, membership_id) == 0:
        raise Conflict("An organization must keep at least one active owner.")

    membership.role = new_role
    membership.is_active = new_active
    db.flush()
    messaging.assign_only_branch(db, membership)
    db.commit()
    return _member_out(db, membership, db.get(User, membership.user_id))


@router.put("/{organization_id}/members/{membership_id}/branches", response_model=MemberResponse)
def assign_branches(organization_id: int, membership_id: int, payload: BranchAssignment, user: CurrentUser,
                    db: DbSession):
    """The pharmacy branches a manager or staff member works at (owners only).
    They see those branches' supplier conversations and no others; an empty
    list leaves them with none. Owners always see every branch."""
    access = get_org_access(db, user, organization_id, roles=OWNERS)
    if access.organization.type != OrganizationType.PHARMACY:
        raise Conflict("Only pharmacy staff work at branches.")
    membership = db.scalar(select(Membership).where(
        Membership.membership_id == membership_id, Membership.organization_id == organization_id))
    if membership is None:
        raise NotFound("Member not found.")
    if membership.role == MembershipRole.OWNER:
        raise Conflict("Owners see every branch; they are not assigned to branches.")
    wanted = set(payload.location_ids)
    valid = set(db.scalars(select(Location.location_id).where(
        Location.organization_id == organization_id, Location.is_active.is_(True), Location.location_id.in_(wanted))))
    if wanted - valid:
        raise NotFound("Branch not found.")
    db.execute(delete(MembershipBranch).where(MembershipBranch.membership_id == membership_id))
    for location_id in sorted(wanted):
        db.add(MembershipBranch(membership_id=membership_id, organization_id=organization_id,
                                location_id=location_id, assigned_by=user.user_id))
    db.commit()
    return _member_out(db, membership, db.get(User, membership.user_id))


@router.delete("/{organization_id}/members/{membership_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(organization_id: int, membership_id: int, user: CurrentUser, db: DbSession):
    """Remove a member. Any member may remove themselves (leave)."""
    access = get_org_access(db, user, organization_id, roles=ALL_ROLES)
    membership = _get_membership(db, organization_id, membership_id)
    if membership.user_id != user.user_id:
        if access.role not in MANAGERS:
            raise Forbidden("Only owners and managers can remove other members.")
        _assert_can_manage(access.role, MembershipRole(membership.role))
    if (
        membership.role == MembershipRole.OWNER
        and _active_owner_count(db, organization_id, membership_id) == 0
    ):
        raise Conflict("An organization must keep at least one active owner.")
    db.delete(membership)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Locations (pharmacy branches / supplier warehouses)
# ---------------------------------------------------------------------------
@router.get("/{organization_id}/locations", response_model=list[LocationResponse])
def list_locations(organization_id: int, user: CurrentUser, db: DbSession, include_inactive: bool = False):
    get_org_access(db, user, organization_id, allow_admin_read=True)
    stmt = select(Location).where(Location.organization_id == organization_id)
    if not include_inactive:
        stmt = stmt.where(Location.is_active.is_(True))
    return db.scalars(stmt.order_by(Location.name)).all()


@router.post(
    "/{organization_id}/locations", response_model=LocationResponse, status_code=status.HTTP_201_CREATED
)
def create_location(organization_id: int, payload: LocationCreate, user: CurrentUser, db: DbSession):
    get_org_access(db, user, organization_id, roles=MANAGERS)
    location = Location(organization_id=organization_id, **payload.model_dump())
    db.add(location)
    db.commit()
    return location


@router.get("/{organization_id}/locations/{location_id}", response_model=LocationResponse)
def get_location(organization_id: int, location_id: int, user: CurrentUser, db: DbSession):
    get_org_access(db, user, organization_id, allow_admin_read=True)
    return get_org_location(db, organization_id, location_id)


@router.patch("/{organization_id}/locations/{location_id}", response_model=LocationResponse)
def update_location(
    organization_id: int,
    location_id: int,
    payload: LocationUpdate,
    user: CurrentUser,
    db: DbSession,
):
    """Update a location. Set ``is_active: false`` to close it: its offers stop
    appearing in search, while its stock history and orders are preserved.
    A branch with open patient reservations cannot be closed until they are
    resolved (the row is locked so that no reservation is submitted meanwhile)."""
    access = get_org_access(db, user, organization_id, roles=MANAGERS)
    get_org_location(db, organization_id, location_id)
    location = reservations.lock_location(db, location_id)
    data = payload.model_dump(exclude_unset=True)
    for required in ("name", "is_active", "reservation_min_stock"):
        if required in data and data[required] is None:
            raise AppError(f"{required} cannot be null.")
    if "reservation_min_stock" in data and access.organization.type != OrganizationType.PHARMACY:
        raise AppError("Only pharmacy branches keep stock back from patient reservations.", status_code=422)
    if data.get("is_active") is False and location.is_active:
        open_ids = reservations.open_reservation_ids(db, location_id=location_id)
        if open_ids:
            raise Conflict(
                "This branch has open patient reservations. Resolve them before closing the branch.",
                extra={"code": "open_reservations", "reservation_ids": open_ids},
            )
    for field, value in data.items():
        setattr(location, field, value)
    db.commit()
    return location


# ---------------------------------------------------------------------------
# Verification documents
# ---------------------------------------------------------------------------
def _get_document(db, organization_id: int, document_id: int) -> OrganizationDocument:
    document = db.get(OrganizationDocument, document_id)
    if document is None or document.organization_id != organization_id:
        raise NotFound("Document not found.")
    return document


@router.get("/{organization_id}/documents", response_model=list[DocumentResponse])
def list_documents(organization_id: int, user: CurrentUser, db: DbSession):
    get_org_access(db, user, organization_id, allow_admin_read=True)
    return db.scalars(
        select(OrganizationDocument)
        .where(OrganizationDocument.organization_id == organization_id)
        .order_by(OrganizationDocument.uploaded_at.desc())
    ).all()


@router.post(
    "/{organization_id}/documents",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
def upload_document(
    organization_id: int,
    document_type: Annotated[str, Form(min_length=1, max_length=100, examples=["pharmacy_license"])],
    file: Annotated[UploadFile, File(description="PDF, JPEG or PNG")],
    user: CurrentUser,
    db: DbSession,
):
    """Upload a verification document (e.g. operating license, business
    registration). Reviewed by ApexRx admins."""
    organization = get_org_access(db, user, organization_id, roles=MANAGERS).organization
    allowed = applications.allowed_document_types(organization.type)
    if document_type.strip() not in allowed:
        raise AppError(
            f"Choose one of the documents ApexRX asks for: {', '.join(applications.DOCUMENT_LABELS[t] for t in allowed)}.",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            extra={"code": "invalid_document_type", "allowed": list(allowed)},
        )
    storage_key, mime_type, size = storage.save_document(organization_id, file)
    file_name = (file.filename or "document").replace("\\", "/").rsplit("/", 1)[-1][:255]
    document = OrganizationDocument(
        organization_id=organization_id,
        document_type=document_type.strip(),
        file_name=file_name,
        storage_key=storage_key,
        mime_type=mime_type,
        file_size_bytes=size,
    )
    db.add(document)
    try:
        db.commit()
    except Exception:
        db.rollback()
        storage.delete_document(storage_key)
        raise
    return document


DOCUMENT_RESPONSES = {200: {"description": "The file", "content": {"application/octet-stream": {}}}}


def document_file_response(document: OrganizationDocument) -> Response:
    """Stream a stored document through the API. Callers must have authorized
    the request first; no storage URL is ever handed to the client."""
    content = storage.read_document(document.storage_key)
    ascii_name = document.file_name.encode("ascii", "ignore").decode().replace('"', "") or "document"
    disposition = f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(document.file_name)}"
    return Response(
        content=content,
        media_type=document.mime_type,
        headers={
            "Content-Disposition": disposition,
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/{organization_id}/documents/{document_id}/download", responses=DOCUMENT_RESPONSES)
def download_document(organization_id: int, document_id: int, user: CurrentUser, db: DbSession):
    get_org_access(db, user, organization_id, allow_admin_read=True)
    return document_file_response(_get_document(db, organization_id, document_id))


@router.delete("/{organization_id}/documents/{document_id}", response_model=Message)
def delete_document(organization_id: int, document_id: int, user: CurrentUser, db: DbSession):
    """Withdraw a document that has not been reviewed yet."""
    get_org_access(db, user, organization_id, roles=MANAGERS)
    document = _get_document(db, organization_id, document_id)
    if document.verification_status != DocumentStatus.PENDING:
        raise Conflict("Reviewed documents are kept as verification records and cannot be deleted.")
    storage_key = document.storage_key
    db.delete(document)
    db.commit()
    storage.delete_document(storage_key)
    return Message(detail="Document deleted.")
