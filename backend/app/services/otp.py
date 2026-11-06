"""SMS one-time codes for phone verification.

* Codes are 6 random digits from ``secrets`` and are valid for
  OTP_TTL_SECONDS (default 5 minutes).
* Only an HMAC-SHA256 of the code is stored, keyed with a secret derived from
  JWT_SECRET_KEY and bound to the user, the phone number and the purpose, so
  a code for one number (or user, or purpose) can never verify another, and a
  leaked database row does not reveal the code.
* A new code invalidates every earlier unused code of that user and purpose.
* Each code is single-use and allows OTP_MAX_ATTEMPTS wrong guesses; the row
  is locked (SELECT ... FOR UPDATE) while it is checked, so two concurrent
  requests cannot both use it.
* Sending is limited by a per-number cooldown (persistent, from the database)
  and by hourly limits per phone number, per user and per client IP (the IP
  limit only when the IP can be trusted, see app/core/rate_limit.py).
* Code values never appear in API responses or logs. In development/test,
  the mock provider keeps the messages in memory for GET /dev/sms/latest.
"""

import hashlib
import hmac
import logging
import math
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import status
from limits import RateLimitItemPerHour
from limits.storage import storage_from_string
from limits.strategies import MovingWindowRateLimiter
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import AppError, TooManyRequests
from app.models import PhoneVerification, User
from app.services.phone import mask_phone
from app.services.sms import SmsDeliveryError, SmsNotConfigured, get_sms_provider

logger = logging.getLogger("apexrx.otp")

PURPOSE_PHARMACY_REGISTRATION = "pharmacy_registration"
_HASH_CONTEXT = b"apexrx-sms-otp-v1"


# ---------------------------------------------------------------------------
# Errors (all user-facing, none reveals anything about other accounts)
# ---------------------------------------------------------------------------
class SmsUnavailable(AppError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE


class SmsSendFailed(AppError):
    status_code = status.HTTP_502_BAD_GATEWAY


class OtpRejected(AppError):
    status_code = status.HTTP_400_BAD_REQUEST


def _too_many(message: str, wait: int) -> TooManyRequests:
    return TooManyRequests(message, headers={"Retry-After": str(wait)}, extra={"retry_after": wait})


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------
def _key() -> bytes:
    return hmac.new(settings.jwt_secret_key.encode(), _HASH_CONTEXT, hashlib.sha256).digest()


def hash_code(code: str, *, user_id: int, phone: str, purpose: str) -> str:
    message = f"{purpose}|{user_id}|{phone}|{code}".encode()
    return hmac.new(_key(), message, hashlib.sha256).hexdigest()


def generate_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def sms_text(code: str) -> str:
    minutes = max(1, settings.otp_ttl_seconds // 60)
    return f"Your ApexRX verification code is {code}. It expires in {minutes} minutes. Never share this code."


# ---------------------------------------------------------------------------
# Sending limits
# ---------------------------------------------------------------------------
class OtpSendLimiter:
    def __init__(self) -> None:
        self.configure()

    def configure(self) -> None:
        self._storage = storage_from_string(settings.rate_limit_storage_uri)
        self._limiter = MovingWindowRateLimiter(self._storage)
        self.per_phone = RateLimitItemPerHour(settings.otp_max_sends_per_phone_per_hour)
        self.per_user = RateLimitItemPerHour(settings.otp_max_sends_per_user_per_hour)
        self.per_ip = RateLimitItemPerHour(settings.otp_max_sends_per_ip_per_hour)

    def _checks(self, user_id: int, phone: str, ip: str | None):
        yield self.per_phone, ("otp-phone", hashlib.sha256(phone.encode()).hexdigest())
        yield self.per_user, ("otp-user", str(user_id))
        if ip:
            yield self.per_ip, ("otp-ip", ip)

    def retry_after(self, user_id: int, phone: str, ip: str | None) -> int | None:
        try:
            waits = []
            for item, keys in self._checks(user_id, phone, ip):
                if not self._limiter.test(item, *keys):
                    reset = self._limiter.get_window_stats(item, *keys).reset_time
                    waits.append(max(1, math.ceil(reset - time.time())))
            return max(waits) if waits else None
        except Exception as exc:  # pragma: no cover - storage outage
            logger.error("OTP send-limit check failed (allowing): %s", type(exc).__name__)
            return None

    def record(self, user_id: int, phone: str, ip: str | None) -> None:
        try:
            for item, keys in self._checks(user_id, phone, ip):
                self._limiter.hit(item, *keys)
        except Exception as exc:  # pragma: no cover - storage outage
            logger.error("Could not record an OTP send: %s", type(exc).__name__)

    def reset(self) -> None:
        self._storage.reset()


send_limiter = OtpSendLimiter()


# ---------------------------------------------------------------------------
# Issue and verify
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class IssuedCode:
    phone: str
    expires_in: int
    resend_after: int


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _active_query(user_id: int, purpose: str):
    return (
        select(PhoneVerification)
        .where(
            PhoneVerification.user_id == user_id,
            PhoneVerification.purpose == purpose,
            PhoneVerification.consumed_at.is_(None),
            PhoneVerification.invalidated_at.is_(None),
        )
        .order_by(PhoneVerification.created_at.desc(), PhoneVerification.verification_id.desc())
    )


def issue_code(
    db: Session, user: User, phone: str, ip: str | None, purpose: str = PURPOSE_PHARMACY_REGISTRATION
) -> IssuedCode:
    """Create a code for ``phone`` (E.164) and send it by SMS."""
    try:
        provider = get_sms_provider()
    except SmsNotConfigured as exc:
        logger.error("SMS verification requested but SMS is not configured: %s", exc)
        raise SmsUnavailable(
            "SMS verification is not available right now. Please try again later or contact ApexRX."
        ) from None

    now = _now()
    last = db.scalar(
        select(PhoneVerification)
        .where(
            PhoneVerification.user_id == user.user_id,
            PhoneVerification.purpose == purpose,
            PhoneVerification.phone_e164 == phone,
        )
        .order_by(PhoneVerification.created_at.desc())
        .limit(1)
    )
    if last is not None and settings.otp_resend_cooldown_seconds:
        elapsed = (now - last.created_at).total_seconds()
        if elapsed < settings.otp_resend_cooldown_seconds:
            wait = max(1, math.ceil(settings.otp_resend_cooldown_seconds - elapsed))
            raise _too_many(f"Please wait {wait} seconds before requesting another code.", wait)

    wait = send_limiter.retry_after(user.user_id, phone, ip)
    if wait is not None:
        minutes = max(1, math.ceil(wait / 60))
        raise _too_many(
            f"Too many codes requested. Please wait about {minutes} minute{'s' if minutes != 1 else ''}.",
            wait,
        )
    send_limiter.record(user.user_id, phone, ip)

    code = generate_code()
    db.execute(
        update(PhoneVerification)
        .where(
            PhoneVerification.user_id == user.user_id,
            PhoneVerification.purpose == purpose,
            PhoneVerification.consumed_at.is_(None),
            PhoneVerification.invalidated_at.is_(None),
        )
        .values(invalidated_at=now)
    )
    db.add(
        PhoneVerification(
            user_id=user.user_id,
            phone_e164=phone,
            purpose=purpose,
            code_hash=hash_code(code, user_id=user.user_id, phone=phone, purpose=purpose),
            created_at=now,
            expires_at=now + timedelta(seconds=settings.otp_ttl_seconds),
            max_attempts=settings.otp_max_attempts,
        )
    )
    db.flush()
    try:
        provider.send(phone, sms_text(code))
    except Exception as exc:
        # Nothing is stored for an undelivered code, and earlier codes stay valid.
        db.rollback()
        reason = type(exc).__name__ if not isinstance(exc, SmsDeliveryError) else "delivery refused"
        logger.error("SMS delivery via %s to %s failed: %s", provider.name, mask_phone(phone), reason)
        raise SmsSendFailed(
            "We could not send the SMS. Check the number and try again in a moment."
        ) from None
    db.commit()
    logger.info("Verification code sent via %s to %s", provider.name, mask_phone(phone))
    return IssuedCode(
        phone=phone, expires_in=settings.otp_ttl_seconds, resend_after=settings.otp_resend_cooldown_seconds
    )


def verify_code(
    db: Session, user: User, phone: str, code: str, purpose: str = PURPOSE_PHARMACY_REGISTRATION
) -> None:
    """Check ``code`` for ``phone``; on success mark the user's phone verified."""
    now = _now()
    row = db.scalar(_active_query(user.user_id, purpose).limit(1).with_for_update())
    if row is None or row.phone_e164 != phone:
        db.rollback()
        raise OtpRejected(
            "There is no active code for this number. Request a new code.", extra={"reason": "no_active_code"}
        )
    if row.expires_at <= now:
        row.invalidated_at = now
        db.commit()
        raise OtpRejected("This code has expired. Request a new code.", extra={"reason": "expired"})
    if row.attempts >= row.max_attempts:
        row.invalidated_at = now
        db.commit()
        raise OtpRejected(
            "Too many incorrect attempts. Request a new code.", extra={"reason": "too_many_attempts"}
        )

    expected = hash_code(code, user_id=user.user_id, phone=phone, purpose=purpose)
    if not hmac.compare_digest(expected.encode(), row.code_hash.encode()):
        row.attempts += 1
        remaining = row.max_attempts - row.attempts
        if remaining <= 0:
            row.invalidated_at = now
        db.commit()
        if remaining <= 0:
            raise OtpRejected(
                "Too many incorrect attempts. Request a new code.", extra={"reason": "too_many_attempts"}
            )
        raise OtpRejected(
            f"Incorrect code. {remaining} attempt{'s' if remaining != 1 else ''} left.",
            extra={"reason": "incorrect", "attempts_left": remaining},
        )

    row.consumed_at = now
    user.verified_phone = phone
    user.phone_verified_at = now
    user.phone = phone
    db.commit()
