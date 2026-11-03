"""Organization registration and setup: profile, members, locations, documents."""

from typing import Annotated

from fastapi import APIRouter, File, Form, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select

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
from app.core.errors import AppError, Conflict, Forbidden, NotFound
from app.models import Location, Membership, Organization, OrganizationDocument, User
from app.models.enums import DocumentStatus, MembershipRole, OrganizationStatus
from app.schemas.common import Message
from app.schemas.organizations import (
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
from app.services import storage

router = APIRouter()


# ---------------------------------------------------------------------------
# Organizations
# ---------------------------------------------------------------------------
@router.post("", response_model=MyOrganizationResponse, status_code=status.HTTP_201_CREATED)
def create_organization(payload: OrganizationCreate, user: CurrentUser, db: DbSession):
    """Register a pharmacy or supplier organization. The caller becomes its
    owner. The organization stays ``pending`` until an ApexRx admin approves it."""
    organization = Organization(
        name=payload.name,
        type=payload.type,
        phone=payload.phone,
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
def update_organization(
    organization_id: int, payload: OrganizationUpdate, user: CurrentUser, db: DbSession
):
    organization = get_org_access(db, user, organization_id, roles=MANAGERS).organization
    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"] is None:
        raise AppError("name cannot be null.")
    if data.get("email"):
        data["email"] = str(data["email"]).lower()
    for field, value in data.items():
        setattr(organization, field, value)
    db.commit()
    return organization


@router.post("/{organization_id}/resubmit", response_model=OrganizationResponse)
def resubmit_organization(organization_id: int, user: CurrentUser, db: DbSession):
    """Send a rejected registration back to the review queue (e.g. after
    uploading corrected documents). Previous review notes are kept."""
    organization = get_org_access(db, user, organization_id, roles=OWNERS).organization
    if organization.status != OrganizationStatus.REJECTED:
        raise Conflict("Only rejected organizations can be resubmitted for review.")
    organization.status = OrganizationStatus.PENDING
    db.commit()
    return organization


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------
def _member_response(membership: Membership, member: User) -> MemberResponse:
    return MemberResponse(
        membership_id=membership.membership_id,
        user_id=member.user_id,
        name=member.name,
        email=member.email,
        phone=member.phone,
        role=membership.role,
        is_active=membership.is_active,
        created_at=membership.created_at,
    )


def list_member_responses(db, organization_id: int) -> list[MemberResponse]:
    rows = db.execute(
        select(Membership, User)
        .join(User, User.user_id == Membership.user_id)
        .where(Membership.organization_id == organization_id)
        .order_by(Membership.created_at)
    ).all()
    return [_member_response(m, u) for m, u in rows]


def _assert_can_manage(actor_role: MembershipRole, target_role: MembershipRole) -> None:
    """Owners manage everyone; managers manage staff only."""
    if actor_role == MembershipRole.OWNER:
        return
    if actor_role == MembershipRole.MANAGER and target_role == MembershipRole.STAFF:
        return
    raise Forbidden("Managers can only manage staff members; owners can manage everyone.")


def _active_owner_count(db, organization_id: int, excluding_membership_id: int | None = None) -> int:
    stmt = select(func.count()).select_from(Membership).where(
        Membership.organization_id == organization_id,
        Membership.role == MembershipRole.OWNER,
        Membership.is_active.is_(True),
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


@router.post(
    "/{organization_id}/members", response_model=MemberResponse, status_code=status.HTTP_201_CREATED
)
def add_member(organization_id: int, payload: MemberCreate, user: CurrentUser, db: DbSession):
    """Give an existing ApexRx user access to the organization. Each staff
    member uses their own account; accounts are never shared."""
    access = get_org_access(db, user, organization_id, roles=MANAGERS)
    _assert_can_manage(access.role, payload.role)

    member = find_user_by_email(db, payload.email)
    if member is None or not member.is_active:
        raise NotFound("No active ApexRx account uses that email. Ask them to register first.")

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
        membership = Membership(
            user_id=member.user_id, organization_id=organization_id, role=payload.role
        )
        db.add(membership)
    db.commit()
    return _member_response(membership, member)


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
    db.commit()
    return _member_response(membership, db.get(User, membership.user_id))


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
def list_locations(
    organization_id: int, user: CurrentUser, db: DbSession, include_inactive: bool = False
):
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
    appearing in search, while its stock history and orders are preserved."""
    get_org_access(db, user, organization_id, roles=MANAGERS)
    location = get_org_location(db, organization_id, location_id)
    data = payload.model_dump(exclude_unset=True)
    for required in ("name", "is_active"):
        if required in data and data[required] is None:
            raise AppError(f"{required} cannot be null.")
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
    get_org_access(db, user, organization_id, roles=MANAGERS)
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


def document_file_response(document: OrganizationDocument) -> FileResponse:
    path = storage.resolve(document.storage_key)
    if not path.is_file():
        raise NotFound("The document file is missing from storage.")
    return FileResponse(path, media_type=document.mime_type, filename=document.file_name)


@router.get("/{organization_id}/documents/{document_id}/download", response_class=FileResponse)
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
