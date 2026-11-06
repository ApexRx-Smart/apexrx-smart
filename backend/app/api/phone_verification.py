"""Phone verification by SMS one-time code (signed-in users).

The pharmacy registration flow is: create account and sign in, then
  POST /auth/phone/send-code {phone}        -> SMS with a 6-digit code
  POST /auth/phone/verify    {phone, code}  -> marks the user's phone verified
then POST /organizations (type pharmacy), which the backend only allows once
the caller's phone is verified, and which uses that verified number.
"""

import re

from fastapi import APIRouter, Request, status

from app.api.deps import CurrentUser, DbSession
from app.core.config import settings
from app.core.errors import AppError
from app.core.rate_limit import client_ip
from app.schemas.auth import (
    PhoneCodeRequest,
    PhoneCodeSentResponse,
    PhoneStatusResponse,
    PhoneVerifiedResponse,
    PhoneVerifyRequest,
)
from app.services import otp
from app.services.phone import PhoneNumberError, mask_phone, normalize_phone
from app.services.sms import sms_configuration_problem

router = APIRouter()

_CODE = re.compile(r"^\d{6}$")


def _phone(raw: str) -> str:
    try:
        return normalize_phone(raw, mobile_only=True)
    except PhoneNumberError as exc:
        raise AppError(str(exc), status_code=status.HTTP_422_UNPROCESSABLE_CONTENT) from None


@router.get("/status", response_model=PhoneStatusResponse)
def phone_status(user: CurrentUser):
    return PhoneStatusResponse(
        required=settings.phone_verification_required,
        verified=user.verified_phone is not None,
        verified_phone=user.verified_phone,
        sms_available=sms_configuration_problem() is None,
    )


@router.post(
    "/send-code",
    response_model=PhoneCodeSentResponse,
    responses={
        429: {"description": "Cooldown or sending limit; see Retry-After"},
        502: {"description": "The SMS provider did not accept the message"},
        503: {"description": "SMS is not configured"},
    },
)
def send_code(payload: PhoneCodeRequest, request: Request, user: CurrentUser, db: DbSession):
    phone = _phone(payload.phone)
    issued = otp.issue_code(db, user, phone, client_ip(request))
    return PhoneCodeSentResponse(
        phone=issued.phone,
        phone_masked=mask_phone(issued.phone),
        expires_in=issued.expires_in,
        resend_after=issued.resend_after,
    )


@router.post("/verify", response_model=PhoneVerifiedResponse)
def verify(payload: PhoneVerifyRequest, user: CurrentUser, db: DbSession):
    phone = _phone(payload.phone)
    code = re.sub(r"\s", "", payload.code)
    if not _CODE.match(code):
        raise otp.OtpRejected("Enter the 6-digit code from the SMS.", extra={"reason": "format"})
    otp.verify_code(db, user, phone, code)
    return PhoneVerifiedResponse(verified_phone=phone)
