from datetime import datetime, timedelta, timezone

import jwt
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

from app.core.config import settings

# Argon2id with OWASP's recommended parameters (19 MiB, 2 passes, 1 lane).
# pwdlib's default (64 MiB, 3 passes, 4 lanes) costs about three times as much
# CPU per sign-in and is noticeably slow on small hosting instances. Hashes made
# with the old parameters still verify, and are re-hashed with these on the
# next successful sign-in (see verify_password_and_update).
password_hash = PasswordHash((Argon2Hasher(time_cost=2, memory_cost=19456, parallelism=1),))

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


def create_access_token(subject: str) -> tuple[str, int]:
    """Return ``(token, expires_in_seconds)``."""
    expires_in = settings.access_token_expire_minutes * 60
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(seconds=expires_in),
        "type": "access",
    }
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return token, expires_in


def decode_access_token(token: str) -> str | None:
    """Return the token subject, or ``None`` if the token is invalid/expired."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["sub", "exp"]},
        )
    except jwt.PyJWTError:
        return None
    if payload.get("type") != "access":
        return None
    subject = payload.get("sub")
    return subject if isinstance(subject, str) else None
