"""Phone verification by SMS one-time code (the signed-in user's own number).

  GET  /auth/phone          status: verified, pending, the usable code (id only)
  POST /auth/phone/send     sends a code to the account's mobile number
  POST /auth/phone/verify   {challenge_id, code} -> marks that number verified

The number is always the account's own (change it with PATCH /auth/me): a user
can only ever verify their own account, and nothing here reveals whether a
number belongs to another account. These endpoints work while the account is
still locked for verification; every other endpoint refuses it (app/api/deps.py).

  POST /webhooks/esms/delivery   eSMS Africa delivery reports (signed); they
                                 only record a delivery status, never verify.
"""

import hashlib
import hmac
import json
import logging
import re
from datetime import timedelta

from fastapi import APIRouter, Request, Response, status

from app.api.deps import DbSession, SignedInUser
from app.core.config import settings
from app.core.errors import AppError, NotFound, Unauthorized
from app.core.rate_limit import client_ip
from app.schemas.auth import (
    PhoneCodeSentResponse,
    PhoneStatusResponse,
    PhoneVerifiedResponse,
    PhoneVerifyRequest,
)
from app.services import otp
from app.services.phone import mask_phone
from app.services.sms import sms_configuration_problem, sms_is_sandbox

router = APIRouter()
webhook_router = APIRouter()
logger = logging.getLogger("apexrx.otp")

_CODE = re.compile(r"^\d{6}$")
MAX_WEBHOOK_BYTES = 64 * 1024


@router.get("", response_model=PhoneStatusResponse)
def phone_status(user: SignedInUser, db: DbSession):
    verified = otp.phone_verified(user)
    challenge = None if verified else otp.active_challenge(db, user)
    if challenge is not None and challenge.phone_e164 != user.phone:
        challenge = None
    resend_at = None
    if challenge is not None:
        resend_at = challenge.created_at + timedelta(seconds=settings.otp_resend_cooldown_seconds)
    return PhoneStatusResponse(
        phone=user.phone,
        phone_masked=mask_phone(user.phone) if user.phone else None,
        verified=verified,
        verified_at=user.phone_verified_at if verified else None,
        pending=otp.verification_pending(user),
        required=settings.phone_verification_required,
        sms_available=sms_configuration_problem() is None,
        sandbox=sms_is_sandbox(),
        challenge_id=challenge.challenge_ref if challenge else None,
        expires_at=challenge.expires_at if challenge else None,
        resend_available_at=resend_at,
    )


@router.post(
    "/send",
    response_model=PhoneCodeSentResponse,
    responses={
        409: {"description": "The number is already verified"},
        422: {"description": "No mobile number on the account, or the provider refused the number"},
        429: {"description": "Cooldown or a sending limit; see Retry-After"},
        503: {"description": "SMS is unavailable or delivery failed (nothing is verified)"},
    },
)
def send_code(request: Request, user: SignedInUser, db: DbSession):
    """Send a new code to the account's mobile number. Earlier codes stop working."""
    if otp.phone_verified(user):
        raise AppError("This number is already verified.", status_code=status.HTTP_409_CONFLICT,
                       extra={"code": "already_verified"})
    issued = otp.issue_code(db, user, client_ip(request))
    return PhoneCodeSentResponse(
        challenge_id=issued.challenge_id,
        phone_masked=mask_phone(issued.phone),
        expires_at=issued.expires_at,
        resend_available_at=issued.resend_available_at,
        sandbox=sms_is_sandbox(),
    )


@router.post(
    "/verify",
    response_model=PhoneVerifiedResponse,
    responses={400: {"description": "Wrong, expired, used or superseded code (see `code`)"},
               429: {"description": "Too many wrong codes in the last hour"}},
)
def verify_code(payload: PhoneVerifyRequest, user: SignedInUser, db: DbSession):
    """Check the code from the SMS. Refusals carry a ``code``: incorrect_code
    (with attempts_left), too_many_attempts, code_expired, code_superseded,
    code_used, phone_changed, invalid_challenge."""
    code = re.sub(r"\s", "", payload.code)
    if not _CODE.match(code):
        raise otp.OtpRejected("Enter the 6-digit code from the SMS.", extra={"code": "code_format"})
    otp.verify_code(db, user, payload.challenge_id, code)
    return PhoneVerifiedResponse(phone=user.phone, phone_masked=mask_phone(user.phone))


@webhook_router.post("/esms/delivery", status_code=status.HTTP_204_NO_CONTENT, include_in_schema=False)
async def esms_delivery_report(request: Request, db: DbSession):
    """eSMS Africa delivery report: ``X-Webhook-Signature: sha256=<hex>``, an
    HMAC-SHA256 of the raw body with the webhook signing secret. Only records
    the delivery status of a code that was sent; never verifies a number."""
    secret = settings.esms_webhook_secret
    if secret is None or not secret.get_secret_value():
        raise NotFound("Not found.")
    raw = await request.body()
    if len(raw) > MAX_WEBHOOK_BYTES:
        raise AppError("Payload too large.", status_code=status.HTTP_413_CONTENT_TOO_LARGE)
    expected = "sha256=" + hmac.new(secret.get_secret_value().encode(), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, request.headers.get("x-webhook-signature", "")):
        raise Unauthorized("Invalid signature.")
    try:
        event = json.loads(raw)
    except ValueError:
        raise AppError("Invalid JSON.") from None
    if not isinstance(event, dict):
        raise AppError("Invalid payload.")
    message_id, delivery = event.get("message_id"), event.get("status")
    if isinstance(message_id, str) and isinstance(delivery, str) and message_id:
        if not otp.record_delivery_report(db, "esms", message_id, delivery):
            logger.info("eSMS delivery report for an unknown message (ignored)")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
