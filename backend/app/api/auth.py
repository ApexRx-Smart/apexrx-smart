import math

from fastapi import APIRouter, Request, status
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession
from app.core import device_token
from app.core.errors import AppError, Conflict, TooManyRequests, Unauthorized
from app.core.rate_limit import account_subject, client_ip, device_subject, login_limiter
from app.core.security import create_access_token, hash_password, verify_password, verify_password_and_update
from app.models import Membership, Organization, User
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    MembershipSummary,
    MeResponse,
    RegisterRequest,
    TokenResponse,
    UpdateMeRequest,
    UserResponse,
)
from app.schemas.common import Message

router = APIRouter()


def normalize_email(email: str) -> str:
    return str(email).strip().lower()


def find_user_by_email(db, email: str) -> User | None:
    return db.scalar(select(User).where(func.lower(func.btrim(User.email)) == normalize_email(email)))


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: DbSession):
    """Create a personal user account. Patients do not need an account; this is
    for pharmacy/supplier staff, who then create or join an organization."""
    email = normalize_email(payload.email)
    if find_user_by_email(db, email):
        raise Conflict("An account with this email already exists.")

    user = User(
        name=payload.name,
        email=email,
        phone=payload.phone,
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    db.commit()
    return user


@router.post(
    "/login",
    response_model=TokenResponse,
    responses={429: {"description": "Too many failed sign-in attempts; see Retry-After"}},
)
def login(payload: LoginRequest, request: Request, db: DbSession):
    """Failed attempts are limited (see app/core/rate_limit.py):

    * from browsers the account does not recognise: per account (5 per 15 min),
      identical whether or not the email has an account;
    * from a browser holding a valid device token for this account: per
      device, so someone else's failures cannot lock the owner out there;
    * per client IP, when the IP can be trusted.

    The limits are checked before the password is verified.
    """
    email = normalize_email(payload.email)
    ip = client_ip(request)
    user = find_user_by_email(db, email)
    device_id = device_token.device_id_for(payload.device_token, user.user_id if user else None)
    subject = device_subject(device_id) if device_id else account_subject(email)

    wait = login_limiter.retry_after(ip, subject)
    if wait is not None:
        minutes = max(1, math.ceil(wait / 60))
        raise TooManyRequests(
            f"Too many failed sign-in attempts. Please wait about {minutes} minute"
            f"{'s' if minutes != 1 else ''} and try again.",
            headers={"Retry-After": str(wait)},
        )

    password_ok, new_hash = verify_password_and_update(payload.password, user.password_hash if user else None)
    if user is None or not password_ok or not user.is_active:
        login_limiter.record_failure(ip, subject)
        raise Unauthorized("Invalid email or password.")
    if new_hash:
        # Stored with older, slower hashing parameters: upgrade it now.
        user.password_hash = new_hash
        db.commit()

    login_limiter.record_success(subject)
    token, expires_in = create_access_token(subject=str(user.user_id))
    return TokenResponse(
        access_token=token, expires_in=expires_in, device_token=device_token.issue(user.user_id)
    )


def _me(db, user: User) -> MeResponse:
    rows = db.execute(
        select(Membership, Organization)
        .join(Organization, Organization.organization_id == Membership.organization_id)
        .where(Membership.user_id == user.user_id, Membership.is_active.is_(True))
        .order_by(Organization.name)
    ).all()
    return MeResponse(
        **UserResponse.model_validate(user).model_dump(),
        memberships=[
            MembershipSummary(
                membership_id=m.membership_id,
                organization_id=o.organization_id,
                organization_name=o.name,
                organization_type=o.type,
                organization_status=o.status,
                role=m.role,
            )
            for m, o in rows
        ],
    )


@router.get("/me", response_model=MeResponse)
def get_me(user: CurrentUser, db: DbSession):
    """The current user and the organizations they belong to (with role)."""
    return _me(db, user)


@router.patch("/me", response_model=MeResponse)
def update_me(payload: UpdateMeRequest, user: CurrentUser, db: DbSession):
    for field, value in payload.model_dump(exclude_unset=True).items():
        if field == "name" and value is None:
            continue
        setattr(user, field, value)
    db.commit()
    return _me(db, user)


@router.post("/me/password", response_model=Message)
def change_password(payload: ChangePasswordRequest, user: CurrentUser, db: DbSession):
    if not verify_password(payload.current_password, user.password_hash):
        # 400, not 401: the session is valid, only the confirmation failed.
        raise AppError("Current password is incorrect.")
    user.password_hash = hash_password(payload.new_password)
    db.commit()
    return Message(detail="Password updated.")
