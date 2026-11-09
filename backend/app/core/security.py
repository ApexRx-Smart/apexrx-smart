from datetime import datetime, timedelta, timezone

import jwt
from pwdlib import PasswordHash

from app.core.config import settings

# pwdlib's recommended configuration (Argon2id, argon2-cffi defaults:
# 64 MiB, 3 passes, 4 lanes). A hash made with any other parameters (for
# example the cheaper ones briefly used in November 2026) still verifies and is
# re-hashed with these on the next successful sign-in (verify_password_and_update).
password_hash = PasswordHash.recommended()

# Verified against when the email is unknown, so failed logins take the same
# time whether or not the account exists.
_DUMMY_HASH = password_hash.hash("apexrx-timing-equaliser")


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed_password: str | None) -> bool:
    if not hashed_password:
        password_hash.verify(password, _DUMMY_HASH)
        return False
    return password_hash.verify(password, hashed_password)


def verify_password_and_update(password: str, hashed_password: str | None) -> tuple[bool, str | None]:
    """Like verify_password, and also return a new hash when the stored one uses
    outdated parameters (``None`` when it is current)."""
    if not hashed_password:
        password_hash.verify(password, _DUMMY_HASH)
        return False, None
    return password_hash.verify_and_update(password, hashed_password)


def create_access_token(subject: str, session_id: int, not_after: datetime | None = None) -> tuple[str, int]:
    """Return ``(token, expires_in_seconds)``. The token names its server-side
    session (``sid``); it never outlives ``not_after`` (the session's maximum age)."""
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=settings.access_token_expire_minutes)
    if not_after is not None:
        expires_at = min(expires_at, not_after)
    payload = {
        "sub": subject,
        "sid": str(session_id),
        "iat": now,
        "exp": expires_at,
        "type": "access",
    }
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return token, max(1, int((expires_at - now).total_seconds()))


def decode_access_token(token: str) -> tuple[str, str] | None:
    """Return ``(subject, session_id)``, or ``None`` if the token is invalid,
    expired or names no session."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["sub", "exp", "sid"]},
        )
    except jwt.PyJWTError:
        return None
    if payload.get("type") != "access":
        return None
    subject, sid = payload.get("sub"), payload.get("sid")
    if not isinstance(subject, str) or not isinstance(sid, str):
        return None
    return subject, sid
