"""Authentication and organization-access dependencies.

Role model (per organization membership):
    owner   - full control, including managing members of any role
    manager - manages locations, prices, documents and orders; may manage staff
    staff   - day-to-day stock updates and order handling

Platform admins (app_user.is_platform_admin) are ApexRx staff. They review
organizations/documents and maintain the catalogue; they are not members of
customer organizations and do not act on their behalf.
"""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db, set_session_actor
from app.core.errors import Forbidden, NotFound, Unauthorized
from app.core.security import decode_access_token
from app.models import AuthSession, Location, Membership, Organization, User
from app.models.enums import MembershipRole, OrganizationStatus, OrganizationType
from app.services import sessions

bearer_scheme = HTTPBearer(auto_error=False, description="JWT from POST /auth/login")

DbSession = Annotated[Session, Depends(get_db)]

ALL_ROLES = frozenset(MembershipRole)
MANAGERS = frozenset({MembershipRole.OWNER, MembershipRole.MANAGER})
OWNERS = frozenset({MembershipRole.OWNER})


@dataclass(frozen=True)
class Auth:
    user: User
    session: AuthSession


def get_auth(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> Auth:
    """The signed-in user and their server-side session. The token must be
    valid AND its session still usable: not signed out, not idle for longer
    than SESSION_IDLE_TIMEOUT_MINUTES, not older than SESSION_MAX_AGE_HOURS
    (app/services/sessions.py). Refusals carry a ``reason``."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise Unauthorized("Not authenticated.")
    decoded = decode_access_token(credentials.credentials)
    if decoded is None or not decoded[0].isdigit() or not decoded[1].isdigit():
        raise Unauthorized("Invalid or expired token.")
    user = db.get(User, int(decoded[0]))
    if user is None or not user.is_active:
        raise Unauthorized("Invalid or expired token.")
    session = db.get(AuthSession, int(decoded[1]))
    issue = sessions.problem(session, user.user_id)
    if issue is not None:
        reason, message = issue
        if session is not None and session.user_id == user.user_id and session.revoked_at is None:
            sessions.revoke(db, session, "idle" if reason == "session_idle" else "expired")
        raise Unauthorized(message, extra={"reason": reason})
    # Every write made with this session is attributed to this user by the
    # database triggers (app.user_id).
    set_session_actor(db, user.user_id)
    return Auth(user, session)


CurrentAuth = Annotated[Auth, Depends(get_auth)]


def get_current_user(auth: CurrentAuth) -> User:
    return auth.user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_platform_admin(user: CurrentUser) -> User:
    if not user.is_platform_admin:
        raise Forbidden("Platform administrator access is required.")
    return user


AdminUser = Annotated[User, Depends(require_platform_admin)]


@dataclass(frozen=True)
class OrgAccess:
    organization: Organization
    membership: Membership | None  # None when a platform admin is reading

    @property
    def role(self) -> MembershipRole | None:
        return MembershipRole(self.membership.role) if self.membership else None

    @property
    def is_approved(self) -> bool:
        return self.organization.status == OrganizationStatus.APPROVED


def get_org_access(
    db: Session,
    user: User,
    organization_id: int,
    *,
    roles: frozenset[MembershipRole] = ALL_ROLES,
    org_type: OrganizationType | None = None,
    require_approved: bool = False,
    allow_admin_read: bool = False,
) -> OrgAccess:
    """Resolve and authorize the caller's access to an organization.

    Raises 404 when the user has no relationship to the organization (so the
    API does not reveal which organization ids exist), 403 when they are a
    member without sufficient rights.
    """
    organization = db.get(Organization, organization_id)
    if organization is None:
        raise NotFound("Organization not found.")

    membership = db.scalar(
        select(Membership).where(
            Membership.organization_id == organization_id,
            Membership.user_id == user.user_id,
            Membership.is_active.is_(True),
        )
    )

    if membership is None:
        if allow_admin_read and user.is_platform_admin:
            return OrgAccess(organization, None)
        raise NotFound("Organization not found.")

    if org_type is not None and organization.type != org_type:
        raise Forbidden(f"This action is only available to {org_type.value} organizations.")
    if MembershipRole(membership.role) not in roles:
        allowed = ", ".join(sorted(r.value for r in roles))
        raise Forbidden(f"Your role does not allow this action (requires: {allowed}).")
    if require_approved and organization.status != OrganizationStatus.APPROVED:
        raise Forbidden(
            f"The organization must be approved by ApexRx first (current status: {organization.status})."
        )
    return OrgAccess(organization, membership)


def get_org_location(
    db: Session, organization_id: int, location_id: int, *, require_active: bool = False
) -> Location:
    location = db.get(Location, location_id)
    if location is None or location.organization_id != organization_id:
        raise NotFound("Location not found.")
    if require_active and not location.is_active:
        raise Forbidden("This location is deactivated.")
    return location


def pagination(
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> tuple[int, int]:
    return limit, offset


Pagination = Annotated[tuple[int, int], Depends(pagination)]
