"""SMS one-time codes for phone verification.

Codes
* 6 random digits from ``secrets``, valid for OTP_TTL_SECONDS (default 5 min).
* Only an HMAC-SHA256 of the code is stored, keyed with a secret derived from
  JWT_SECRET_KEY and bound to the user, the phone number and the purpose: a
  code for one number (or user, or purpose) never verifies another, and a
  leaked row does not reveal the code.
* At most one valid code per user and purpose: issuing a new one invalidates
  the earlier ones. Each code is single-use and allows OTP_MAX_ATTEMPTS wrong
  guesses; its row is locked (SELECT ... FOR UPDATE) while it is checked, so
  two concurrent requests cannot both use it.

Issuing (all in PostgreSQL, so it holds across processes and instances)
1. In one transaction, take locks in a fixed order: the user's app_user row
   (FOR UPDATE), then transaction-scoped advisory locks for the phone number
   and (when trustworthy) the client IP. Concurrent requests for the same
   user, number or IP therefore run one after another.
2. Still inside that transaction: check the resend cooldown and the hourly
   limits per phone, per user and per IP by counting phone_verification rows,
   invalidate earlier codes, insert the new row, COMMIT. Counting and
   recording happen under the same locks, so the check-then-record is atomic.
3. Only then send the SMS. The code is therefore always stored before it can
   be delivered (no "delivered but not saved" code). If the provider fails,
   the row is marked delivery_failed and invalidated; it still counts towards
   the hourly limits (so a failing provider cannot be hammered) but not
   towards the cooldown (so the user can retry at once).
* Any database error while checking or recording the limits FAILS CLOSED: no
  SMS is sent and the client gets a generic 503.

Code values never appear in API responses or logs. In development/test, the
mock provider keeps messages in memory for GET /dev/sms/latest.
"""

import hashlib
import hmac
import logging
import math
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import status
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import AppError, TooManyRequests
from app.models import PhoneVerification, User
from app.services.phone import mask_phone
from app.services.sms import SmsDeliveryError, SmsNotConfigured, get_sms_provider

logger = logging.getLogger("apexrx.otp")

PURPOSE_PHARMACY_REGISTRATION = "pharmacy_registration"
_HASH_CONTEXT = b"apexrx-sms-otp-v1"
_IP_CONTEXT = b"apexrx-otp-client-ip-v1"
LIMIT_WINDOW = timedelta(hours=1)
UNAVAILABLE = "Verification codes cannot be sent right now. Please try again in a few minutes."


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
def _key(context: bytes) -> bytes:
    return hmac.new(settings.jwt_secret_key.encode(), context, hashlib.sha256).digest()


def hash_code(code: str, *, user_id: int, phone: str, purpose: str) -> str:
    message = f"{purpose}|{user_id}|{phone}|{code}".encode()
    return hmac.new(_key(_HASH_CONTEXT), message, hashlib.sha256).hexdigest()


def hash_ip(ip: str) -> str:
    """Client IPs are only stored as an HMAC (enough to count, not to read)."""
    return hmac.new(_key(_IP_CONTEXT), ip.encode(), hashlib.sha256).hexdigest()


def generate_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def sms_text(code: str) -> str:
    minutes = max(1, settings.otp_ttl_seconds // 60)
    return f"Your ApexRX verification code is {code}. It expires in {minutes} minutes. Never share this code."


# ---------------------------------------------------------------------------
# Locks and limits (inside the issuing transaction)
# ---------------------------------------------------------------------------
def _advisory_lock(db: Session, key: str) -> None:
    # Released automatically at COMMIT/ROLLBACK; shared by all app instances.
    db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": key})


def _lock_issuance(db: Session, user_id: int, phone: str, ip_hash: str | None) -> None:
    """Always the same order (user row, phone, IP) so requests cannot deadlock."""
    db.execute(select(User.user_id).where(User.user_id == user_id).with_for_update())
    _advisory_lock(db, f"apexrx-otp-phone:{phone}")
    if ip_hash:
        _advisory_lock(db, f"apexrx-otp-ip:{ip_hash}")


def _check_cooldown(db: Session, user_id: int, phone: str, purpose: str, now: datetime) -> None:
    cooldown = settings.otp_resend_cooldown_seconds
    if not cooldown:
        return
    last = db.scalar(
        select(func.max(PhoneVerification.created_at)).where(
            PhoneVerification.user_id == user_id,
            PhoneVerification.purpose == purpose,
            PhoneVerification.phone_e164 == phone,
            PhoneVerification.delivery_failed_at.is_(None),
        )
    )
    if last is not None and (elapsed := (now - last).total_seconds()) < cooldown:
        wait = max(1, math.ceil(cooldown - elapsed))
        raise _too_many(f"Please wait {wait} seconds before requesting another code.", wait)


def _check_limit(db: Session, condition, limit: int, now: datetime) -> None:
    count, oldest = db.execute(
        select(func.count(), func.min(PhoneVerification.created_at)).where(
            condition, PhoneVerification.created_at > now - LIMIT_WINDOW
        )
    ).one()
    if count >= limit:
        wait = max(1, math.ceil((oldest + LIMIT_WINDOW - now).total_seconds()))
        minutes = max(1, math.ceil(wait / 60))
        raise _too_many(
            f"Too many codes requested. Please wait about {minutes} minute{'s' if minutes != 1 else ''}.",
            wait,
        )


def _check_limits(db: Session, user_id: int, phone: str, ip_hash: str | None, now: datetime) -> None:
    _check_limit(db, PhoneVerification.phone_e164 == phone, settings.otp_max_sends_per_phone_per_hour, now)
    _check_limit(db, PhoneVerification.user_id == user_id, settings.otp_max_sends_per_user_per_hour, now)
    if ip_hash:
        _check_limit(
            db, PhoneVerification.client_ip_hash == ip_hash, settings.otp_max_sends_per_ip_per_hour, now
        )


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


def _record_code(db: Session, user_id: int, phone: str, ip: str | None, purpose: str, code: str) -> int:
    """Steps 1-2: lock, check, invalidate, insert, commit. Returns the row id."""
    ip_hash = hash_ip(ip) if ip else None
    _lock_issuance(db, user_id, phone, ip_hash)
    now = _now()  # after the locks, so waiting requests see the rows written meanwhile
    _check_cooldown(db, user_id, phone, purpose, now)
    _check_limits(db, user_id, phone, ip_hash, now)
    db.execute(
        update(PhoneVerification)
        .where(
            PhoneVerification.user_id == user_id,
            PhoneVerification.purpose == purpose,
            PhoneVerification.consumed_at.is_(None),
            PhoneVerification.invalidated_at.is_(None),
        )
        .values(invalidated_at=now)
    )
    row = PhoneVerification(
        user_id=user_id,
        phone_e164=phone,
        purpose=purpose,
        code_hash=hash_code(code, user_id=user_id, phone=phone, purpose=purpose),
        client_ip_hash=ip_hash,
        created_at=now,
        expires_at=now + timedelta(seconds=settings.otp_ttl_seconds),
        max_attempts=settings.otp_max_attempts,
    )
    db.add(row)
    db.flush()
    row_id = row.verification_id
    db.commit()
    return row_id


def _mark_delivery_failed(db: Session, row_id: int) -> None:
    now = _now()
    try:
        db.execute(
            update(PhoneVerification)
            .where(PhoneVerification.verification_id == row_id)
            .values(
                delivery_failed_at=now, invalidated_at=func.coalesce(PhoneVerification.invalidated_at, now)
            )
        )
        db.commit()
    except SQLAlchemyError as exc:
        # The code was never delivered, so it cannot be used; it simply stays
        # unusable until it expires (the user may need to wait the cooldown).
        db.rollback()
        logger.error("Could not record a failed SMS delivery (row %s): %s", row_id, type(exc).__name__)


def issue_code(
    db: Session, user: User, phone: str, ip: str | None, purpose: str = PURPOSE_PHARMACY_REGISTRATION
) -> IssuedCode:
    """Create a code for ``phone`` (E.164), store it, then send it by SMS."""
    try:
        provider = get_sms_provider()
    except SmsNotConfigured as exc:
        logger.error("SMS verification requested but SMS is not configured: %s", exc)
        raise SmsUnavailable(
            "SMS verification is not available right now. Please try again later or contact ApexRX."
        ) from None

    user_id = user.user_id
    code = generate_code()
    try:
        row_id = _record_code(db, user_id, phone, ip, purpose, code)
    except AppError:
        db.rollback()  # cooldown / limit reached: nothing recorded, nothing sent
        raise
    except SQLAlchemyError as exc:
        # Fail closed: without a working limit check nothing is sent.
        db.rollback()
        logger.error("OTP issuance failed before sending (no SMS sent): %s", type(exc).__name__)
        raise SmsUnavailable(UNAVAILABLE) from None

    try:
        provider.send(phone, sms_text(code))
    except Exception as exc:
        _mark_delivery_failed(db, row_id)
        reason = "delivery refused" if isinstance(exc, SmsDeliveryError) else type(exc).__name__
        logger.error("SMS delivery via %s to %s failed: %s", provider.name, mask_phone(phone), reason)
        raise SmsSendFailed(
            "We could not send the SMS. Check the number and try again in a moment."
        ) from None
    logger.info("Verification code sent via %s to %s", provider.name, mask_phone(phone))
    return IssuedCode(
        phone=phone, expires_in=settings.otp_ttl_seconds, resend_after=settings.otp_resend_cooldown_seconds
    )


def verify_code(
    db: Session, user: User, phone: str, code: str, purpose: str = PURPOSE_PHARMACY_REGISTRATION
) -> None:
    """Check ``code`` for ``phone``; on success mark the user's phone verified."""
    # Same lock order as issuing (user row first, then code rows): no deadlocks,
    # and a verification never interleaves with a new code being issued.
    db.execute(select(User.user_id).where(User.user_id == user.user_id).with_for_update())
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
