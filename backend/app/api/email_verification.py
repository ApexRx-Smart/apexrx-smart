"""Email verification by emailed link.

The registration flow (pharmacies and suppliers) is: create an account and
sign in, then
  POST /auth/email/send   {next}   -> emails a single-use link to the account email
  POST /auth/email/verify {token}  -> opened from the link (verify-email.html);
                                      marks the account's email verified
  GET  /auth/email/status          -> whether it is verified / a link is pending
then POST /organizations, which the backend only allows once the caller's email
is verified (when EMAIL_VERIFICATION_REQUIRED is on).
"""

from fastapi import APIRouter, Request

from app.api.deps import CurrentUser, DbSession
from app.core.config import settings
from app.core.rate_limit import client_ip
from app.schemas.auth import (
    EmailSendRequest,
    EmailSentResponse,
    EmailStatusResponse,
    EmailVerifiedResponse,
    EmailVerifyRequest,
)
from app.services import email_verification as ev
from app.services.email import email_configuration_problem

router = APIRouter()


@router.get("/status", response_model=EmailStatusResponse)
def email_status(user: CurrentUser, db: DbSession):
    state = ev.link_state(db, user)
    return EmailStatusResponse(
        email=user.email,
        verified=user.email_verified_at is not None,
        verified_at=user.email_verified_at,
        required=settings.email_verification_required,
        delivery_available=email_configuration_problem() is None,
        pending=state.pending and user.email_verified_at is None,
        expires_at=state.expires_at if user.email_verified_at is None else None,
        resend_after=state.resend_after,
    )


@router.post(
    "/send",
    response_model=EmailSentResponse,
    responses={
        409: {"description": "The email address is already verified"},
        429: {"description": "Cooldown or sending limit; see Retry-After"},
        502: {"description": "The email provider did not accept the message"},
        503: {"description": "Email is not configured"},
    },
)
def send_verification_email(payload: EmailSendRequest, request: Request, user: CurrentUser, db: DbSession):
    """Email a new verification link to the signed-in user's account address.
    Earlier links stop working."""
    sent = ev.send_link(db, user, client_ip(request), payload.next)
    return EmailSentResponse(
        email_masked=ev.mask_email(sent.email), expires_in=sent.expires_in, resend_after=sent.resend_after
    )


@router.post(
    "/verify",
    response_model=EmailVerifiedResponse,
    responses={400: {"description": "Invalid, expired, used or superseded link (see `reason`)"}},
)
def verify_email(payload: EmailVerifyRequest, db: DbSession):
    """Verify with the token from an emailed link. No session needed: the link
    itself proves access to the mailbox. Errors carry a ``reason``:
    ``invalid``, ``expired``, ``used`` or ``superseded``."""
    result = ev.verify_token(db, payload.token)
    return EmailVerifiedResponse(already_verified=result.already_verified, email_masked=ev.mask_email(result.email))
