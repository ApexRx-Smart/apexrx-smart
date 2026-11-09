"""Staff invitations (see app/services/invitations.py).

Organization side (owners and managers; managers may only invite staff,
exactly like adding members):
  POST /organizations/{id}/invitations              {email, role}
  GET  /organizations/{id}/invitations              list with status and delivery
  POST /organizations/{id}/invitations/{inv}/resend new link, previous one stops working
  POST /organizations/{id}/invitations/{inv}/revoke

Invitee side (the link from the email, opened on accept-invitation.html):
  POST /invitations/inspect     {token}                 what the invitation is for
  POST /invitations/accept-new  {token, name, password} new account + membership, signed in
  POST /invitations/accept      {token}  (signed in)    existing account; email must match
"""

from fastapi import APIRouter, status
from sqlalchemy import select

from app.api.auth import token_response
from app.api.deps import MANAGERS, CurrentUser, DbSession, get_org_access
from app.api.organizations import _assert_can_manage
from app.core.errors import NotFound
from app.core.security import hash_password
from app.models import Organization, OrganizationInvitation, User
from app.models.enums import MembershipRole
from app.schemas.auth import TokenResponse
from app.schemas.organizations import (
    InvitationAccepted,
    InvitationAcceptNew,
    InvitationCreate,
    InvitationPreview,
    InvitationResponse,
    InvitationSendResponse,
    InvitationTokenRequest,
)
from app.services import invitations, sessions

router = APIRouter()
public_router = APIRouter()


def _response(db, inv: OrganizationInvitation) -> dict:
    inviter = db.get(User, inv.invited_by) if inv.invited_by else None
    return dict(
        invitation_id=inv.invitation_id, email=inv.email, role=inv.role,
        status=invitations.state(inv), delivery=invitations.delivery(inv),
        created_at=inv.created_at, expires_at=inv.expires_at, sent_at=inv.sent_at, send_count=inv.send_count,
        accepted_at=inv.accepted_at, account_created=inv.account_created, revoked_at=inv.revoked_at,
        invited_by_name=inviter.name if inviter else None,
    )


def _invitation(db, organization_id: int, invitation_id: int) -> OrganizationInvitation:
    inv = db.get(OrganizationInvitation, invitation_id)
    if inv is None or inv.organization_id != organization_id:
        raise NotFound("Invitation not found.")
    return inv


@router.post("/{organization_id}/invitations", response_model=InvitationSendResponse,
             status_code=status.HTTP_201_CREATED)
def create_invitation(organization_id: int, payload: InvitationCreate, user: CurrentUser, db: DbSession):
    """Invite someone by email. They need no ApexRX account yet. No membership
    exists until they accept. ``email_sent`` says whether the email provider
    accepted the message; if not, the invitation is kept for a resend."""
    access = get_org_access(db, user, organization_id, roles=MANAGERS)
    _assert_can_manage(access.role, payload.role)
    inv, token = invitations.create(db, access.organization, user, str(payload.email), payload.role)
    outcome = invitations.send(db, inv, token)
    return InvitationSendResponse(**_response(db, inv), email_sent=outcome.sent, detail=outcome.message)


@router.get("/{organization_id}/invitations", response_model=list[InvitationResponse])
def list_invitations(organization_id: int, user: CurrentUser, db: DbSession):
    get_org_access(db, user, organization_id, roles=MANAGERS)
    rows = db.scalars(
        select(OrganizationInvitation)
        .where(OrganizationInvitation.organization_id == organization_id)
        .order_by(OrganizationInvitation.created_at.desc())
        .limit(200)
    ).all()
    return [InvitationResponse(**_response(db, inv)) for inv in rows]


@router.post("/{organization_id}/invitations/{invitation_id}/resend", response_model=InvitationSendResponse)
def resend_invitation(organization_id: int, invitation_id: int, user: CurrentUser, db: DbSession):
    access = get_org_access(db, user, organization_id, roles=MANAGERS)
    inv = _invitation(db, organization_id, invitation_id)
    _assert_can_manage(access.role, MembershipRole(inv.role))
    outcome = invitations.resend(db, inv)
    return InvitationSendResponse(**_response(db, inv), email_sent=outcome.sent, detail=outcome.message)


@router.post("/{organization_id}/invitations/{invitation_id}/revoke", response_model=InvitationResponse)
def revoke_invitation(organization_id: int, invitation_id: int, user: CurrentUser, db: DbSession):
    access = get_org_access(db, user, organization_id, roles=MANAGERS)
    inv = _invitation(db, organization_id, invitation_id)
    _assert_can_manage(access.role, MembershipRole(inv.role))
    invitations.revoke(db, inv, user)
    return InvitationResponse(**_response(db, inv))


# ---------------------------------------------------------------- invitee side
def _accepted(db, inv: OrganizationInvitation, role: str) -> InvitationAccepted:
    org = db.get(Organization, inv.organization_id)
    return InvitationAccepted(organization_id=org.organization_id, organization_name=org.name,
                              organization_type=org.type, role=role)


@public_router.post("/inspect", response_model=InvitationPreview)
def inspect_invitation(payload: InvitationTokenRequest, db: DbSession):
    """What the link is for, so the page can offer "set up your password" or
    "sign in". Errors carry a ``reason``: invalid, used, revoked, expired."""
    inv = invitations.by_token(db, payload.token)
    org = db.get(Organization, inv.organization_id)
    inviter = db.get(User, inv.invited_by) if inv.invited_by else None
    return InvitationPreview(
        organization_name=org.name, organization_type=org.type, role=inv.role, email=inv.email,
        invited_by_name=inviter.name if inviter else None, expires_at=inv.expires_at,
        account_exists=invitations.find_account(db, inv.email) is not None,
    )


class AcceptNewResponse(TokenResponse, InvitationAccepted):
    pass


@public_router.post("/accept-new", response_model=AcceptNewResponse, status_code=status.HTTP_201_CREATED)
def accept_with_new_account(payload: InvitationAcceptNew, db: DbSession):
    """The invitee sets up their own account (name and password; the email is
    the invited one and counts as verified) and joins. Signs them in. 409
    ``account_exists`` if the address already has an account: sign in instead."""
    user, inv, membership = invitations.accept_with_new_account(
        db, payload.token, payload.name, hash_password(payload.password)
    )
    issued = sessions.start(db, user)
    return AcceptNewResponse(**token_response(issued).model_dump(), **_accepted(db, inv, membership.role).model_dump())


@public_router.post("/accept", response_model=InvitationAccepted)
def accept_with_existing_account(payload: InvitationTokenRequest, user: CurrentUser, db: DbSession):
    """Join with the signed-in account. Its email must be the invited one (403
    ``email_mismatch`` otherwise). Other memberships are untouched; an existing
    active membership keeps its role."""
    inv, membership = invitations.accept_with_account(db, payload.token, user)
    return _accepted(db, inv, membership.role)
