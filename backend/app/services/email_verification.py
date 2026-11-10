"""Email verification by emailed link.

Links
* ``<FRONTEND_BASE_URL>/verify-email.html?next=<pharmacy|supplier>#token=<token>``.
  The token is 32 random bytes from ``secrets`` (URL-safe base64). It sits in
  the URL fragment, so browsers never send it to a server in a request line or
  Referer; verify-email.html posts it to POST /auth/email/verify.
* Only a SHA-256 hash of the token is stored, with the user and the address the
  link was sent to. A leaked row does not reveal a usable link.
* Valid for EMAIL_VERIFICATION_TTL_MINUTES (default 24 hours) and single-use.
  At most one usable link per user: sending a new one invalidates the earlier
  ones (database-enforced). Verifying needs no session: opening the link proves
  access to the mailbox, which is what is being verified. The link only counts
  while the account still has that address and is active.

Sending (all in PostgreSQL, so it holds across processes and instances)
1. One transaction: lock the user's row (FOR UPDATE) and, when trustworthy, a
   transaction-scoped advisory lock for the client IP; check the resend
   cooldown and the hourly limits per user and per IP by counting rows;
   invalidate earlier links; insert the new row; COMMIT.
2. Only then send the email. If the provider fails, the row is marked
   delivery_failed and invalidated; it still counts towards the hourly limits
   but not towards the cooldown, so the user can retry at once.
* A database error while checking or recording the limits fails closed: no
  email is sent and the client gets a generic 503.

Tokens never appear in API responses or logs. In development/test, the mock
provider keeps messages in memory for GET /dev/email/latest.
"""

import hashlib
import hmac
import logging
import math
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import status
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import AppError, Conflict, TooManyRequests
from app.models import EmailVerification, User
from app.services.email import (
    EmailDeliveryError,
    EmailMessage,
    EmailNotConfigured,
    get_email_provider,
    templates,
)

logger = logging.getLogger("apexrx.email_verification")

_IP_CONTEXT = b"apexrx-email-verification-client-ip-v1"
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{43}$")  # secrets.token_urlsafe(32)
LIMIT_WINDOW = timedelta(hours=1)
UNAVAILABLE = "Verification emails cannot be sent right now. Please try again in a few minutes."
NEXT_PAGES = {"pharmacy", "supplier"}


# ---------------------------------------------------------------------------
# Errors (user-facing; none reveals anything about other accounts)
# ---------------------------------------------------------------------------
class EmailUnavailable(AppError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE


class EmailSendFailed(AppError):
    status_code = status.HTTP_502_BAD_GATEWAY


class LinkRejected(AppError):
    status_code = status.HTTP_400_BAD_REQUEST


def _too_many(message: str, wait: int) -> TooManyRequests:
    return TooManyRequests(message, headers={"Retry-After": str(wait)}, extra={"retry_after": wait})


# ---------------------------------------------------------------------------
# Hashing and helpers
# ---------------------------------------------------------------------------
def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def hash_ip(ip: str) -> str:
    """Client IPs are only stored as an HMAC (enough to count, not to read)."""
    key = hmac.new(settings.jwt_secret_key.encode(), _IP_CONTEXT, hashlib.sha256).digest()
    return hmac.new(key, ip.encode(), hashlib.sha256).hexdigest()


def normalize_email(email: str) -> str:
    return str(email).strip().lower()


def mask_email(email: str) -> str:
    """amina.k@example.com -> a*****k@example.com (safe for responses and logs)."""
    local, _, domain = normalize_email(email).partition("@")
    if not domain:
        return "***"
    if len(local) <= 2:
        return f"{local[:1]}*@{domain}"
    return f"{local[0]}{'*' * (len(local) - 2)}{local[-1]}@{domain}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def verification_link(token: str, next_page: str | None) -> str:
    query = f"?next={next_page}" if next_page in NEXT_PAGES else ""
    return f"{settings.frontend_base_url}/verify-email.html{query}#token={token}"


def build_message(user: User, link: str) -> EmailMessage:
    return templates.verification(
        to=user.email, name=user.name, url=link, expires_minutes=settings.email_verification_ttl_minutes
    )


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class LinkState:
    pending: bool  # a usable, unexpired link was sent to the current address
    expires_at: datetime | None
    resend_after: int  # seconds until another link may be requested (cooldown)


def link_state(db: Session, user: User) -> LinkState:
    now = _now()
    active = db.scalar(_active_query(user.user_id).limit(1))
    pending = bool(
        active and active.expires_at > now and active.email == normalize_email(user.email)
    )
    last = _last_delivered(db, user.user_id)
    wait = 0
    cooldown = settings.email_verification_resend_cooldown_seconds
    if cooldown and last is not None:
        wait = max(0, math.ceil(cooldown - (now - last).total_seconds()))
    return LinkState(pending=pending, expires_at=active.expires_at if pending else None, resend_after=wait)


# ---------------------------------------------------------------------------
# Locks and limits (inside the sending transaction)
# ---------------------------------------------------------------------------
def _active_query(user_id: int):
    return (
        select(EmailVerification)
        .where(
            EmailVerification.user_id == user_id,
            EmailVerification.consumed_at.is_(None),
            EmailVerification.invalidated_at.is_(None),
        )
        .order_by(EmailVerification.created_at.desc(), EmailVerification.verification_id.desc())
    )


def _last_delivered(db: Session, user_id: int) -> datetime | None:
    return db.scalar(
        select(func.max(EmailVerification.created_at)).where(
            EmailVerification.user_id == user_id, EmailVerification.delivery_failed_at.is_(None)
        )
    )


def _check_cooldown(db: Session, user_id: int, now: datetime) -> None:
    cooldown = settings.email_verification_resend_cooldown_seconds
    last = _last_delivered(db, user_id) if cooldown else None
    if last is not None and (elapsed := (now - last).total_seconds()) < cooldown:
        wait = max(1, math.ceil(cooldown - elapsed))
        raise _too_many(f"Please wait {wait} seconds before requesting another email.", wait)


def _check_limit(db: Session, condition, limit: int, now: datetime) -> None:
    count, oldest = db.execute(
        select(func.count(), func.min(EmailVerification.created_at)).where(
            condition, EmailVerification.created_at > now - LIMIT_WINDOW
        )
    ).one()
    if count >= limit:
        wait = max(1, math.ceil((oldest + LIMIT_WINDOW - now).total_seconds()))
        minutes = max(1, math.ceil(wait / 60))
        raise _too_many(
            f"Too many verification emails requested. Please wait about {minutes} "
            f"minute{'s' if minutes != 1 else ''}.",
            wait,
        )


def _record_link(db: Session, user: User, ip: str | None, token: str) -> int:
    """Lock, check, invalidate, insert, commit. Returns the row id."""
    ip_hash = hash_ip(ip) if ip else None
    db.execute(select(User.user_id).where(User.user_id == user.user_id).with_for_update())
    if ip_hash:
        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"apexrx-email-verification-ip:{ip_hash}"},
        )
    now = _now()  # after the locks, so waiting requests see the rows written meanwhile
    _check_cooldown(db, user.user_id, now)
    _check_limit(
        db, EmailVerification.user_id == user.user_id,
        settings.email_verification_max_sends_per_user_per_hour, now,
    )
    if ip_hash:
        _check_limit(
            db, EmailVerification.client_ip_hash == ip_hash,
            settings.email_verification_max_sends_per_ip_per_hour, now,
        )
    db.execute(
        update(EmailVerification)
        .where(
            EmailVerification.user_id == user.user_id,
            EmailVerification.consumed_at.is_(None),
            EmailVerification.invalidated_at.is_(None),
        )
        .values(invalidated_at=now)
    )
    row = EmailVerification(
        user_id=user.user_id,
        email=normalize_email(user.email),
        token_hash=hash_token(token),
        client_ip_hash=ip_hash,
        created_at=now,
        expires_at=now + timedelta(minutes=settings.email_verification_ttl_minutes),
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
            update(EmailVerification)
            .where(EmailVerification.verification_id == row_id)
            .values(
                delivery_failed_at=now,
                invalidated_at=func.coalesce(EmailVerification.invalidated_at, now),
            )
        )
        db.commit()
    except SQLAlchemyError as exc:
        # Never delivered, so it cannot be used; it stays unusable until it expires.
        db.rollback()
        logger.error("Could not record a failed verification email (row %s): %s", row_id, type(exc).__name__)


# ---------------------------------------------------------------------------
# Send and verify
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SentLink:
    email: str
    expires_in: int
    resend_after: int


def send_link(db: Session, user: User, ip: str | None, next_page: str | None = None) -> SentLink:
    """Create a link for the user's current email, store it, then email it."""
    if user.email_verified_at is not None:
        raise Conflict("Your email address is already verified.", extra={"reason": "already_verified"})
    try:
        provider = get_email_provider()
    except EmailNotConfigured as exc:
        logger.error("Email verification requested but email is not configured: %s", exc)
        raise EmailUnavailable(
            "Email verification is not available right now. Please try again later or contact ApexRX."
        ) from None

    token = secrets.token_urlsafe(32)
    try:
        row_id = _record_link(db, user, ip, token)
    except AppError:
        db.rollback()  # cooldown / limit reached: nothing recorded, nothing sent
        raise
    except SQLAlchemyError as exc:
        db.rollback()  # fail closed: without a working limit check nothing is sent
        logger.error("Verification link issuance failed before sending (no email sent): %s", type(exc).__name__)
        raise EmailUnavailable(UNAVAILABLE) from None

    try:
        provider.send(build_message(user, verification_link(token, next_page)))
    except Exception as exc:
        _mark_delivery_failed(db, row_id)
        logger.error(
            "Verification email via %s to %s failed: %s",
            provider.name, mask_email(user.email), str(exc) if isinstance(exc, EmailDeliveryError) else type(exc).__name__,
        )
        raise EmailSendFailed("We could not send the verification email. Please try again in a moment.") from None
    logger.info("Verification email sent via %s to %s", provider.name, mask_email(user.email))
    return SentLink(
        email=user.email,
        expires_in=settings.email_verification_ttl_minutes * 60,
        resend_after=settings.email_verification_resend_cooldown_seconds,
    )


@dataclass(frozen=True)
class Verified:
    email: str
    already_verified: bool


def _reject(message: str, reason: str) -> LinkRejected:
    return LinkRejected(message, extra={"reason": reason})


def verify_token(db: Session, token: str) -> Verified:
    """Consume ``token``; on success mark the account's email verified."""
    token = (token or "").strip()
    invalid = _reject("This verification link is not valid. Request a new email.", "invalid")
    if not _TOKEN.match(token):
        raise invalid
    row = db.scalar(
        select(EmailVerification).where(EmailVerification.token_hash == hash_token(token)).with_for_update()
    )
    if row is None:
        db.rollback()
        raise invalid
    user = db.scalar(select(User).where(User.user_id == row.user_id).with_for_update())
    same_address = user is not None and normalize_email(user.email) == row.email
    if user is None or not user.is_active or not same_address:
        db.rollback()
        raise invalid
    if user.email_verified_at is not None:
        # Already verified (by this link or another): nothing changes.
        db.rollback()
        return Verified(email=user.email, already_verified=True)
    now = _now()
    if row.consumed_at is not None:
        db.rollback()
        raise _reject("This verification link has already been used. Request a new email.", "used")
    if row.delivery_failed_at is not None:
        db.rollback()
        raise invalid
    if row.invalidated_at is not None:
        db.rollback()
        raise _reject(
            "A newer verification email was sent. Use the link in the most recent email.", "superseded"
        )
    if row.expires_at <= now:
        row.invalidated_at = now
        db.commit()
        raise _reject("This verification link has expired. Request a new email.", "expired")

    row.consumed_at = now
    user.email_verified_at = now
    db.commit()
    logger.info("Email verified for user %s", user.user_id)
    return Verified(email=user.email, already_verified=False)
