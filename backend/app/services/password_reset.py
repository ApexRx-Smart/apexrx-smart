"""Forgot password: emailed single-use reset links.

* Requesting a reset always gets the same response, whether or not the email
  has an account; the email itself is sent after the response (background
  task), so the response time does not reveal it either.
* Limits per email address (hashed, applied to every address, registered or
  not) and per client IP, in the same counter store as the sign-in limits, so
  a 429 does not reveal accounts either.
* Token: 32 random bytes in the fragment of
  <FRONTEND_BASE_URL>/reset-password.html#token=...; only its SHA-256 is stored;
  valid PASSWORD_RESET_TTL_MINUTES (default 60); single use; a new request
  invalidates earlier links (database-enforced: one usable link per user).
* A successful reset changes the password (same hashing as everywhere), signs
  out every session of the account, marks the email verified (the link proved
  it), and emails a confirmation. Memberships and roles are untouched.
"""

import hashlib
import logging
import math
import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import BackgroundTasks, status
from limits import RateLimitItemPerHour
from limits.storage import storage_from_string
from limits.strategies import MovingWindowRateLimiter
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.errors import AppError, TooManyRequests
from app.models import PasswordReset, User
from app.services import sessions
from app.services.email import EmailDeliveryError, email_delivery_available, get_email_provider, templates
from app.services.email_verification import hash_ip, mask_email

logger = logging.getLogger("apexrx.password_reset")
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{43}$")
PUBLIC_MESSAGE = ("If an ApexRX account uses this email address, we have sent it a link to reset the password. "
                  "Check your inbox and spam folder.")


class ResetRejected(AppError):
    status_code = status.HTTP_400_BAD_REQUEST


def now() -> datetime:
    return datetime.now(timezone.utc)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class _Limiter:
    def __init__(self) -> None:
        self._limiter = None

    def _get(self):
        if self._limiter is None:
            self._storage = storage_from_string(settings.rate_limit_storage_uri)
            self._limiter = MovingWindowRateLimiter(self._storage)
        return self._limiter

    def hit(self, ip: str | None, email: str) -> int | None:
        """Count one request; seconds to wait if a limit is reached, else None."""
        try:
            limiter = self._get()
            checks = [(RateLimitItemPerHour(settings.password_reset_max_per_user_per_hour),
                       "pwreset-email", hashlib.sha256(email.encode()).hexdigest())]
            if ip:
                checks.append((RateLimitItemPerHour(settings.password_reset_max_per_ip_per_hour), "pwreset-ip", ip))
            for item, *key in checks:
                if not limiter.test(item, *key):
                    reset_at = limiter.get_window_stats(item, *key).reset_time
                    return max(1, math.ceil(reset_at - datetime.now().timestamp()))
            for item, *key in checks:
                limiter.hit(item, *key)
        except Exception as exc:  # pragma: no cover - counter store outage: fail open, log
            logger.error("Password reset limiter unavailable: %s", type(exc).__name__)
        return None

    def reset(self) -> None:
        if self._limiter is not None:
            self._storage.reset()


limiter = _Limiter()


def request_reset(db: Session, email: str, ip: str | None, background: BackgroundTasks) -> None:
    if not email_delivery_available():
        # Decided before looking at the address: the same answer for everyone.
        raise AppError("Password reset by email is temporarily unavailable. Contact ApexRX support for help "
                       "with your account.", status_code=503, extra={"reason": "email_unavailable"})
    email = str(email).strip().lower()
    wait = limiter.hit(ip, email)
    if wait is not None:
        raise TooManyRequests("Too many password reset requests. Please wait a while and try again.",
                              headers={"Retry-After": str(wait)}, extra={"retry_after": wait})
    user = db.scalar(select(User).where(func.lower(func.btrim(User.email)) == email))
    if user is None or not user.is_active:
        return  # same response; nothing sent
    t = now()
    db.execute(select(User.user_id).where(User.user_id == user.user_id).with_for_update())
    db.execute(
        update(PasswordReset)
        .where(PasswordReset.user_id == user.user_id, PasswordReset.used_at.is_(None),
               PasswordReset.invalidated_at.is_(None))
        .values(invalidated_at=t)
    )
    token = secrets.token_urlsafe(32)
    row = PasswordReset(user_id=user.user_id, token_hash=hash_token(token), client_ip_hash=hash_ip(ip) if ip else None,
                        created_at=t, expires_at=t + timedelta(minutes=settings.password_reset_ttl_minutes))
    db.add(row)
    db.flush()
    reset_id = row.reset_id
    db.commit()
    background.add_task(_deliver, reset_id, user.user_id, token)


def _deliver(reset_id: int, user_id: int, token: str) -> None:
    """Send the reset email (after the response). A failure invalidates the link."""
    with SessionLocal() as db:
        user = db.get(User, user_id)
        if user is None:
            return
        message = templates.password_reset(
            to=user.email, name=user.name, url=templates.link("reset-password.html", token),
            expires_minutes=settings.password_reset_ttl_minutes,
        )
        try:
            get_email_provider().send(message)
            logger.info("Password reset email sent to %s", mask_email(user.email))
        except Exception as exc:  # noqa: BLE001
            reason = str(exc) if isinstance(exc, EmailDeliveryError) else type(exc).__name__
            logger.error("Password reset email to %s failed: %s", mask_email(user.email), reason)
            t = now()
            db.execute(update(PasswordReset).where(PasswordReset.reset_id == reset_id)
                       .values(delivery_failed_at=t, invalidated_at=func.coalesce(PasswordReset.invalidated_at, t)))
            db.commit()


def _usable(db: Session, token: str, *, lock: bool) -> PasswordReset:
    token = (token or "").strip()
    invalid = ResetRejected("This password reset link is not valid. Request a new one.", extra={"reason": "invalid"})
    if not _TOKEN.match(token):
        raise invalid
    stmt = select(PasswordReset).where(PasswordReset.token_hash == hash_token(token))
    row = db.scalar(stmt.with_for_update() if lock else stmt)
    if row is None or row.delivery_failed_at is not None:
        raise invalid
    if row.used_at is not None:
        raise ResetRejected("This password reset link has already been used. Request a new one if you need to.",
                            extra={"reason": "used"})
    if row.invalidated_at is not None:
        raise ResetRejected("A newer password reset email was sent. Use the link in the most recent email.",
                            extra={"reason": "superseded"})
    if row.expires_at <= now():
        raise ResetRejected("This password reset link has expired. Request a new one.", extra={"reason": "expired"})
    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        raise invalid
    return row


def check(db: Session, token: str) -> User:
    return db.get(User, _usable(db, token, lock=False).user_id)


def complete(db: Session, token: str, new_password_hash: str) -> User:
    row = _usable(db, token, lock=True)
    user = db.scalar(select(User).where(User.user_id == row.user_id).with_for_update())
    t = now()
    user.password_hash = new_password_hash
    if user.email_verified_at is None:
        user.email_verified_at = t
    row.used_at = t
    db.execute(update(PasswordReset).where(PasswordReset.user_id == user.user_id, PasswordReset.used_at.is_(None),
                                           PasswordReset.invalidated_at.is_(None)).values(invalidated_at=t))
    sessions.revoke_all(db, user.user_id, "password_reset")
    db.commit()
    return user
