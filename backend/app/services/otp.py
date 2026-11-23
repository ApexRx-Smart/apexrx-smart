"""SMS one-time codes for phone verification. ApexRX owns the whole lifecycle;
the SMS provider (app/services/sms) only delivers the text.

Codes ("challenges")
* 6 digits from ``secrets``, valid OTP_TTL_SECONDS (default 5 minutes).
* Each challenge has a random public ``challenge_ref``. Only an HMAC-SHA256 of
  the code is stored, keyed with OTP_HMAC_SECRET (a server-side secret, never
  the JWT secret) over (challenge_ref, purpose, user, phone, code). A leaked row
  reveals neither the code nor anything usable for another challenge, user or
  number. Codes are compared with ``hmac.compare_digest``.
* One usable challenge per user and purpose: a new one supersedes the earlier
  ones (database-enforced). Single use; OTP_MAX_ATTEMPTS wrong codes per
  challenge; the row is locked (FOR UPDATE) while it is checked, so two
  concurrent requests cannot both use it.
* A challenge only verifies the number it was sent to, and only while that is
  still the account's number.

Issuing (all in PostgreSQL, so limits hold across restarts and instances)
1. One transaction: lock the user's row, then advisory locks for the phone
   number, the client IP (when trustworthy) and the platform-wide counter, in
   that fixed order. Check: resend cooldown (per account and number), sends per phone /
   account / IP per hour, every send on the platform per hour, and wrong codes
   per account per hour across challenges. Supersede earlier challenges, insert
   the new one, COMMIT.
2. Only then send the SMS (Idempotency-Key = challenge_ref, so a provider-side
   retry never sends twice). If delivery fails, the challenge is marked
   delivery_failed and invalidated: it still counts towards the hourly limits
   (a failing provider cannot be hammered) but not the cooldown.
* A database error while checking or recording fails CLOSED: nothing is sent.
* Limits are rolling one-hour windows: someone requesting codes for another
  person's number can delay them for at most an hour, never lock them out.

The code never appears in responses or logs. In development/test the mock
provider keeps messages in memory for GET /dev/sms/latest.
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
from app.services.phone import PhoneNumberError, mask_phone, normalize_phone
from app.services.sms import SmsDeliveryError, SmsNotConfigured, get_sms_provider

logger = logging.getLogger("apexrx.otp")

PURPOSE = "phone_verification"
_CODE_CONTEXT = b"apexrx-sms-otp-v2"
_IP_CONTEXT = b"apexrx-otp-client-ip-v2"
LIMIT_WINDOW = timedelta(hours=1)
UNAVAILABLE = "Verification codes cannot be sent right now. Please try again in a few minutes."
RATE_LIMITED = "Too many verification codes were requested. Please wait about {minutes} minute{s} and try again."


# ---------------------------------------------------------------------------
# Errors (user-facing; none says anything about other accounts or numbers)
# ---------------------------------------------------------------------------
class SmsUnavailable(AppError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE


class OtpRejected(AppError):
    status_code = status.HTTP_400_BAD_REQUEST


def _too_many(message: str, wait: int, code: str) -> TooManyRequests:
    return TooManyRequests(message, headers={"Retry-After": str(wait)}, extra={"code": code, "retry_after": wait})


def _rejected(message: str, code: str, **extra) -> OtpRejected:
    return OtpRejected(message, extra={"code": code, **extra})


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------
def _secret() -> bytes:
    if settings.otp_hmac_secret is None:
        raise SmsNotConfigured("OTP_HMAC_SECRET is not set.")
    return settings.otp_hmac_secret.get_secret_value().encode()


def _key(context: bytes) -> bytes:
    return hmac.new(_secret(), context, hashlib.sha256).digest()


def hash_code(code: str, *, challenge_ref: str, user_id: int, phone: str, purpose: str = PURPOSE) -> str:
    message = f"{challenge_ref}|{purpose}|{user_id}|{phone}|{code}".encode()
    return hmac.new(_key(_CODE_CONTEXT), message, hashlib.sha256).hexdigest()


def hash_ip(ip: str) -> str:
    """Client IPs are only stored as an HMAC (enough to count, not to read)."""
    return hmac.new(_key(_IP_CONTEXT), ip.encode(), hashlib.sha256).hexdigest()


def generate_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def sms_text(code: str) -> str:
    minutes = max(1, settings.otp_ttl_seconds // 60)
    return f"Your ApexRX verification code is {code}. It expires in {minutes} minutes. Never share this code."


# ---------------------------------------------------------------------------
# Account state
# ---------------------------------------------------------------------------
def _now() -> datetime:
    return datetime.now(timezone.utc)


def phone_verified(user: User) -> bool:
    """The account's current number is the one it verified."""
    return user.verified_phone is not None and user.phone is not None and user.verified_phone == user.phone


def verification_pending(user: User) -> bool:
    """This account must verify its number before using ApexRX. Off for every
    account while PHONE_VERIFICATION_REQUIRED is false (the safety switch)."""
    return bool(settings.phone_verification_required and user.phone_verification_required
                and not phone_verified(user))


def mark_new_account(user: User) -> None:
    """Accounts created from now on (sign-up, accepted invitations) must verify."""
    user.phone_verification_required = bool(settings.phone_verification_required)


def phone_changed(db: Session, user: User) -> None:
    """The account's number changed: earlier challenges stop counting, and when
    verification is required the new number must be verified (any account)."""
    db.execute(
        update(PhoneVerification)
        .where(PhoneVerification.user_id == user.user_id, PhoneVerification.purpose == PURPOSE,
               PhoneVerification.consumed_at.is_(None), PhoneVerification.invalidated_at.is_(None))
        .values(invalidated_at=_now())
    )
    if settings.phone_verification_required and not phone_verified(user):
        user.phone_verification_required = True


def _account_phone(user: User) -> str:
    if not user.phone:
        raise AppError("Add your mobile number first.", status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                       extra={"code": "phone_missing"})
    try:
        return normalize_phone(user.phone, mobile_only=True)
    except PhoneNumberError as exc:
        raise AppError(str(exc), status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                       extra={"code": "invalid_phone"}) from None


# ---------------------------------------------------------------------------
# Locks and limits (inside the issuing transaction)
# ---------------------------------------------------------------------------
def _advisory_lock(db: Session, key: str) -> None:
    # Released automatically at COMMIT/ROLLBACK; shared by all app instances.
    db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": key})


def _lock_user(db: Session, user_id: int) -> None:
    db.execute(select(User.user_id).where(User.user_id == user_id).with_for_update())


def _check_failed_attempts(db: Session, user_id: int, now: datetime) -> None:
    """Wrong codes across all of the account's challenges in the last hour."""
    failed, oldest = db.execute(
        select(func.coalesce(func.sum(PhoneVerification.attempts), 0), func.min(PhoneVerification.created_at)).where(
            PhoneVerification.user_id == user_id, PhoneVerification.purpose == PURPOSE,
            PhoneVerification.created_at > now - LIMIT_WINDOW,
        )
    ).one()
    if failed >= settings.otp_max_failed_attempts_per_user_per_hour:
        wait = max(1, math.ceil((oldest + LIMIT_WINDOW - now).total_seconds()))
        minutes = max(1, math.ceil(wait / 60))
        raise _too_many(
            f"Too many incorrect codes. Please wait about {minutes} minute{'s' if minutes != 1 else ''} and try again.",
            wait, "too_many_failed_codes",
        )


def _check_cooldown(db: Session, user_id: int, phone: str, now: datetime) -> None:
    """Per account and number: correcting a mistyped number needs no wait (the
    hourly per-account limit still caps switching numbers)."""
    cooldown = settings.otp_resend_cooldown_seconds
    if not cooldown:
        return
    last = db.scalar(
        select(func.max(PhoneVerification.created_at)).where(
            PhoneVerification.user_id == user_id, PhoneVerification.purpose == PURPOSE,
            PhoneVerification.phone_e164 == phone, PhoneVerification.delivery_failed_at.is_(None),
        )
    )
    if last is not None and (elapsed := (now - last).total_seconds()) < cooldown:
        wait = max(1, math.ceil(cooldown - elapsed))
        raise _too_many(f"Please wait {wait} seconds before requesting another code.", wait, "resend_cooldown")


def _check_limit(db: Session, condition, limit: int, now: datetime, code: str = "rate_limited") -> None:
    count, oldest = db.execute(
        select(func.count(), func.min(PhoneVerification.created_at)).where(
            condition, PhoneVerification.created_at > now - LIMIT_WINDOW
        )
    ).one()
    if count >= limit:
        wait = max(1, math.ceil((oldest + LIMIT_WINDOW - now).total_seconds()))
        minutes = max(1, math.ceil(wait / 60))
        raise _too_many(RATE_LIMITED.format(minutes=minutes, s="s" if minutes != 1 else ""), wait, code)


def _check_limits(db: Session, user_id: int, phone: str, ip_hash: str | None, now: datetime) -> None:
    _check_failed_attempts(db, user_id, now)
    _check_cooldown(db, user_id, phone, now)
    _check_limit(db, PhoneVerification.phone_e164 == phone, settings.otp_max_sends_per_phone_per_hour, now)
    _check_limit(db, PhoneVerification.user_id == user_id, settings.otp_max_sends_per_user_per_hour, now)
    if ip_hash:
        _check_limit(db, PhoneVerification.client_ip_hash == ip_hash, settings.otp_max_sends_per_ip_per_hour, now)
    # Platform-wide ceiling (cost and SMS pumping). Same generic answer.
    _check_limit(db, PhoneVerification.purpose == PURPOSE, settings.otp_max_sends_global_per_hour, now)


# ---------------------------------------------------------------------------
# Issue
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class IssuedChallenge:
    challenge_id: str
    phone: str
    expires_at: datetime
    resend_available_at: datetime


def _record(db: Session, user_id: int, phone: str, ip: str | None, code: str) -> PhoneVerification:
    ip_hash = hash_ip(ip) if ip else None
    _lock_user(db, user_id)
    _advisory_lock(db, f"apexrx-otp-phone:{phone}")
    if ip_hash:
        _advisory_lock(db, f"apexrx-otp-ip:{ip_hash}")
    _advisory_lock(db, "apexrx-otp-global")
    now = _now()  # after the locks, so waiting requests see the rows written meanwhile
    _check_limits(db, user_id, phone, ip_hash, now)
    db.execute(
        update(PhoneVerification)
        .where(PhoneVerification.user_id == user_id, PhoneVerification.purpose == PURPOSE,
               PhoneVerification.consumed_at.is_(None), PhoneVerification.invalidated_at.is_(None))
        .values(invalidated_at=now)
    )
    ref = secrets.token_urlsafe(24)
    row = PhoneVerification(
        user_id=user_id, phone_e164=phone, purpose=PURPOSE, challenge_ref=ref,
        code_hash=hash_code(code, challenge_ref=ref, user_id=user_id, phone=phone),
        client_ip_hash=ip_hash, created_at=now, expires_at=now + timedelta(seconds=settings.otp_ttl_seconds),
        max_attempts=settings.otp_max_attempts,
    )
    db.add(row)
    db.flush()
    db.commit()
    return row


def _record_delivery(db: Session, row_id: int, *, failed: bool, provider: str, message_id: str | None,
                     delivery_status: str | None) -> None:
    now = _now()
    values = {"provider": provider, "provider_message_id": message_id,
              "delivery_status": (delivery_status or "")[:30] or None, "delivery_status_at": now}
    if failed:
        values.update(delivery_failed_at=now, invalidated_at=func.coalesce(PhoneVerification.invalidated_at, now))
    try:
        db.execute(update(PhoneVerification).where(PhoneVerification.verification_id == row_id).values(**values))
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        # A failed delivery that cannot be recorded: the code was never sent, so it
        # cannot be used; it stays unusable until it expires.
        logger.error("Could not record SMS delivery for challenge row %s: %s", row_id, type(exc).__name__)


def issue_code(db: Session, user: User, ip: str | None) -> IssuedChallenge:
    """Create a challenge for the account's mobile number, store it, then send it."""
    phone = _account_phone(user)
    try:
        provider = get_sms_provider()
        _secret()
    except SmsNotConfigured as exc:
        logger.error("SMS verification requested but SMS is not configured: %s", exc)
        raise SmsUnavailable(UNAVAILABLE, extra={"code": "sms_unavailable"}) from None

    user_id = user.user_id
    code = generate_code()
    try:
        row = _record(db, user_id, phone, ip, code)
    except AppError:
        db.rollback()  # cooldown / limit reached: nothing recorded, nothing sent
        raise
    except SQLAlchemyError as exc:
        db.rollback()  # fail closed: without a working limit check nothing is sent
        logger.error("OTP issuance failed before sending (no SMS sent): %s", type(exc).__name__)
        raise SmsUnavailable(UNAVAILABLE, extra={"code": "sms_unavailable"}) from None
    row_id, ref, created, expires = row.verification_id, row.challenge_ref, row.created_at, row.expires_at

    try:
        result = provider.send(phone, sms_text(code), idempotency_key=ref)
    except Exception as exc:
        number_rejected = isinstance(exc, SmsDeliveryError) and exc.number_rejected
        reason = exc.reason if isinstance(exc, SmsDeliveryError) else type(exc).__name__
        _record_delivery(db, row_id, failed=True, provider=provider.name, message_id=None, delivery_status=reason)
        logger.error("SMS delivery via %s to %s failed: %s", provider.name, mask_phone(phone), reason)
        if number_rejected:
            raise AppError("This number cannot receive SMS. Check it, or use another mobile number.",
                           status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                           extra={"code": "sms_number_rejected"}) from None
        raise SmsUnavailable("We could not send the SMS right now. Please try again in a few minutes.",
                             extra={"code": "sms_send_failed"}) from None
    _record_delivery(db, row_id, failed=False, provider=result.provider, message_id=result.message_id,
                     delivery_status=result.status)
    logger.info("Verification code sent via %s (%s) to %s", result.provider, result.environment or "-",
                mask_phone(phone))
    return IssuedChallenge(
        challenge_id=ref, phone=phone, expires_at=expires,
        resend_available_at=created + timedelta(seconds=settings.otp_resend_cooldown_seconds),
    )


def active_challenge(db: Session, user: User) -> PhoneVerification | None:
    now = _now()
    return db.scalar(
        select(PhoneVerification)
        .where(PhoneVerification.user_id == user.user_id, PhoneVerification.purpose == PURPOSE,
               PhoneVerification.consumed_at.is_(None), PhoneVerification.invalidated_at.is_(None),
               PhoneVerification.challenge_ref.is_not(None), PhoneVerification.expires_at > now)
        .order_by(PhoneVerification.created_at.desc())
        .limit(1)
    )


# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------
def verify_code(db: Session, user: User, challenge_id: str, code: str) -> None:
    """Check ``code`` against the account's challenge; on success mark the
    account's number verified. Every refusal is recorded before answering."""
    try:
        _verify(db, user, challenge_id, code)
    except AppError:
        db.rollback()  # releases the row locks; refusals that count were committed first
        raise
    except SQLAlchemyError as exc:
        db.rollback()  # nothing is verified when the database fails
        logger.error("OTP verification failed on a database error: %s", type(exc).__name__)
        raise SmsUnavailable("Verification is temporarily unavailable. Please try again.",
                             extra={"code": "verification_unavailable"}) from None


def _verify(db: Session, user: User, challenge_id: str, code: str) -> None:
    _lock_user(db, user.user_id)  # same lock order as issuing: no deadlocks
    now = _now()
    _check_failed_attempts(db, user.user_id, now)
    row = db.scalar(
        select(PhoneVerification)
        .where(PhoneVerification.challenge_ref == challenge_id, PhoneVerification.user_id == user.user_id,
               PhoneVerification.purpose == PURPOSE)
        .with_for_update()
    )
    if row is None:
        db.rollback()
        raise _rejected("This code is not valid. Request a new code.", "invalid_challenge")
    if row.consumed_at is not None:
        db.rollback()
        raise _rejected("This code has already been used.", "code_used")
    if row.invalidated_at is not None:
        db.rollback()
        if row.attempts >= row.max_attempts:
            raise _rejected("Too many incorrect attempts. Request a new code.", "too_many_attempts")
        if row.delivery_failed_at is not None:
            raise _rejected("This code was never delivered. Request a new code.", "invalid_challenge")
        if row.expires_at <= row.invalidated_at:
            raise _rejected("This code has expired. Request a new code.", "code_expired")
        raise _rejected("A newer code was sent. Enter the code from the latest SMS.", "code_superseded")
    try:
        current = _account_phone(user)
    except AppError:
        current = None
    if current != row.phone_e164:
        row.invalidated_at = now
        db.commit()
        raise _rejected("Your number changed since this code was sent. Request a new code.", "phone_changed")
    if row.expires_at <= now:
        row.invalidated_at = now
        db.commit()
        raise _rejected("This code has expired. Request a new code.", "code_expired")

    expected = hash_code(code, challenge_ref=row.challenge_ref, user_id=user.user_id, phone=row.phone_e164)
    if not hmac.compare_digest(expected.encode(), row.code_hash.encode()):
        row.attempts += 1
        remaining = row.max_attempts - row.attempts
        if remaining <= 0:
            row.invalidated_at = now
        db.commit()
        if remaining <= 0:
            raise _rejected("Too many incorrect attempts. Request a new code.", "too_many_attempts")
        raise _rejected(f"Incorrect code. {remaining} attempt{'s' if remaining != 1 else ''} left.",
                        "incorrect_code", attempts_left=remaining)

    row.consumed_at = now
    user.phone = row.phone_e164
    user.verified_phone = row.phone_e164
    user.phone_verified_at = now
    user.phone_verification_required = False
    db.commit()
    logger.info("Phone verified for user %s (%s)", user.user_id, mask_phone(row.phone_e164))


# ---------------------------------------------------------------------------
# Delivery reports
# ---------------------------------------------------------------------------
def record_delivery_report(db: Session, provider: str, message_id: str, delivery_status: str) -> bool:
    """Store the provider's latest delivery status for a challenge. Never
    verifies anything. Returns whether a challenge matched."""
    result = db.execute(
        update(PhoneVerification)
        .where(PhoneVerification.provider == provider, PhoneVerification.provider_message_id == message_id[:100])
        .values(delivery_status=delivery_status[:30], delivery_status_at=_now())
    )
    db.commit()
    return bool(result.rowcount)
