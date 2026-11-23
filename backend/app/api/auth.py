import math

from fastapi import APIRouter, BackgroundTasks, Request, Response, status
from sqlalchemy import func, select

from app.api.deps import CurrentAuth, DbSession, SignedInUser
from app.core import device_token
from app.core.config import settings
from app.core.errors import AppError, Conflict, Forbidden, TooManyRequests, Unauthorized
from app.core.rate_limit import account_subject, client_ip, device_subject, login_limiter
from app.core.security import hash_password, verify_password, verify_password_and_update
from app.models import Membership, Organization, User
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    MembershipSummary,
    MeResponse,
    RegisterRequest,
    SessionResponse,
    TokenResponse,
    UpdateMeRequest,
    UserResponse,
)
from app.schemas.common import Message
from app.services import account_emails, otp, sessions
from app.services.email import email_delivery_available
from app.services.phone import PhoneNumberError, normalize_phone
from app.services.sms import sms_configuration_problem, sms_is_sandbox

router = APIRouter()


def normalize_email(email: str) -> str:
    return str(email).strip().lower()


def find_user_by_email(db, email: str) -> User | None:
    return db.scalar(select(User).where(func.lower(func.btrim(User.email)) == normalize_email(email)))


def _personal_phone(raw: str | None) -> str | None:
    """An account's own mobile number, stored in E.164 (+250...). Reservations use
    it as the contact number and it is verified by SMS code (/auth/phone), so
    only mobile numbers are accepted. Empty: no number."""
    if raw is None or not raw.strip():
        return None
    try:
        return normalize_phone(raw, mobile_only=True)
    except PhoneNumberError as exc:
        raise AppError(str(exc), status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, extra={"code": "invalid_phone"}) from None


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: DbSession):
    """Create a personal account of the given type: a patient (patient
    registration), or a pharmacy / supplier owner who then registers the
    business. The type is fixed: it decides which sign-in page accepts the
    account. Staff join through an invitation instead (app/api/invitations.py)."""
    email = normalize_email(payload.email)
    phone = _personal_phone(payload.phone)
    if phone is None and settings.phone_verification_required:
        raise AppError("Enter your mobile number. We send a code to verify it.",
                       status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, extra={"code": "phone_required"})
    if find_user_by_email(db, email):
        raise Conflict("An account with this email already exists.")

    user = User(
        name=payload.name,
        email=email,
        phone=phone,
        password_hash=hash_password(payload.password),
        account_type=payload.account_type.value,
    )
    # Locked until the number is verified, when verification is required.
    otp.mark_new_account(user)
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
        # Stored with non-current hashing parameters: re-hash with the current ones.
        user.password_hash = new_hash
        db.commit()

    # Right password, but is this the right sign-in page for the account? Checked
    # before any session exists: a refused account is never signed in.
    if not account_type_matches(user, payload.account_type):
        raise Forbidden(WRONG_PAGE[str(payload.account_type)], extra={"code": "wrong_account_type"})

    login_limiter.record_success(subject)
    issued = sessions.start(db, user)
    return token_response(issued, device_token=device_token.issue(user.user_id))


# Says only which kind of account this page is for, never what the account is.
WRONG_PAGE = {
    "patient": "This sign-in is for patients. This account can't sign in here: use the sign-in page for your account.",
    "pharmacy": "This sign-in is for pharmacies. This account can't sign in here: use the sign-in page for your account.",
    "supplier": "This sign-in is for medicine suppliers. This account can't sign in here: use the sign-in page for your account.",
    "admin": "This account is not an ApexRX administrator.",
}


def account_type_matches(user: User, requested: str) -> bool:
    if requested == "admin":
        return user.is_platform_admin
    return user.account_type == requested


def token_response(issued: sessions.IssuedToken, device_token: str | None = None) -> TokenResponse:
    return TokenResponse(
        access_token=issued.token,
        expires_in=issued.expires_in,
        device_token=device_token,
        idle_timeout_seconds=int(sessions.idle_timeout().total_seconds()),
        session_expires_at=issued.session.expires_at,
    )


@router.get("/capabilities")
def capabilities():
    """What works on this server right now (public). Email delivery is
    temporarily disabled, so the features that need it say so."""
    email = email_delivery_available()
    return {
        "email_delivery": email,
        "email_verification_required": settings.email_verification_required,
        "phone_verification_required": settings.phone_verification_required,
        "password_reset": email,
        "invitation_emails": email,
    }


@router.post("/session/activity", response_model=TokenResponse)
def session_activity(auth: CurrentAuth, db: DbSession):
    """Called by the page when the user is actually active (clicks, typing,
    navigation), at most about once a minute; never by background refreshes.
    Moves the session's inactivity clock and returns a fresh access token for
    the same session."""
    return token_response(sessions.renew(db, auth.session))


@router.get("/session", response_model=SessionResponse)
def session_status(auth: CurrentAuth):
    """The current session's limits. Reading it is not activity."""
    s = auth.session
    return SessionResponse(
        idle_timeout_seconds=int(sessions.idle_timeout().total_seconds()),
        last_activity_at=s.last_activity_at,
        idle_expires_at=s.last_activity_at + sessions.idle_timeout(),
        expires_at=s.expires_at,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(auth: CurrentAuth, db: DbSession):
    """End this session only. The access token stops working immediately.
    Other sessions, memberships, roles and organizations are unchanged."""
    sessions.revoke(db, auth.session, "signed_out")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _me(db, user: User) -> MeResponse:
    rows = db.execute(
        select(Membership, Organization)
        .join(Organization, Organization.organization_id == Membership.organization_id)
        .where(Membership.user_id == user.user_id, Membership.is_active.is_(True))
        .order_by(Organization.name)
    ).all()
    return MeResponse(
        **UserResponse.model_validate(user).model_dump(),
        phone_verification_pending=otp.verification_pending(user),
        phone_verification_available=sms_configuration_problem() is None and not sms_is_sandbox(),
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
def get_me(user: SignedInUser, db: DbSession):
    """The current user and the organizations they belong to (with role).
    Available while the phone still has to be verified (see
    ``phone_verification_pending``)."""
    return _me(db, user)


@router.patch("/me", response_model=MeResponse)
def update_me(payload: UpdateMeRequest, user: SignedInUser, db: DbSession):
    """Also available while the phone still has to be verified, to correct the
    number. A new number is never verified by this call: earlier codes stop
    working, and when verification is required the new number must be verified."""
    for field, value in payload.model_dump(exclude_unset=True).items():
        if field == "name" and value is None:
            continue
        if field == "phone":
            value = _personal_phone(value)
            if value is None and settings.phone_verification_required and user.phone_verification_required:
                raise AppError("Enter your mobile number. We send a code to verify it.",
                               status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, extra={"code": "phone_required"})
            if value != user.phone:
                user.phone = value
                otp.phone_changed(db, user)
            continue
        setattr(user, field, value)
    db.commit()
    return _me(db, user)


@router.post("/me/password", response_model=Message)
def change_password(payload: ChangePasswordRequest, auth: CurrentAuth, db: DbSession, background: BackgroundTasks):
    """Change the password. Every other session of this account is signed out
    (this one stays), and a confirmation email is sent."""
    user = auth.user
    if not verify_password(payload.current_password, user.password_hash):
        # 400, not 401: the session is valid, only the confirmation failed.
        raise AppError("Current password is incorrect.")
    user.password_hash = hash_password(payload.new_password)
    sessions.revoke_all(db, user.user_id, "password_changed", keep=auth.session.session_id)
    db.commit()
    background.add_task(account_emails.send_password_changed, user.user_id)
    return Message(detail="Password updated.")
