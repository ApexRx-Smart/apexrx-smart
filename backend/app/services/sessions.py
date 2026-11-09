"""Server-side sign-in sessions (auth_session).

Three separate limits:
* access token expiry (ACCESS_TOKEN_EXPIRE_MINUTES, default 30): each JWT is
  short-lived; the page gets a fresh one from POST /auth/session/activity while
  the user is active;
* inactivity (SESSION_IDLE_TIMEOUT_MINUTES, default 30): the session ends when
  no user activity was reported for that long. Only sign-in and
  POST /auth/session/activity move ``last_activity_at``; ordinary API calls
  (including background refreshes) never do, so automated requests cannot keep
  a session alive;
* maximum age (SESSION_MAX_AGE_HOURS, default 12): sign in again after that.

Signing out revokes only the current session: other people (and the same
person's other sign-ins) are not affected, and nothing about memberships,
roles or the organization changes.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import create_access_token
from app.models import AuthSession, User


def now() -> datetime:
    return datetime.now(timezone.utc)


def idle_timeout() -> timedelta:
    return timedelta(minutes=settings.session_idle_timeout_minutes)


@dataclass(frozen=True)
class IssuedToken:
    token: str
    expires_in: int
    session: AuthSession


def start(db: Session, user: User) -> IssuedToken:
    """Create a session for a successful sign-in and its first access token."""
    t = now()
    session = AuthSession(
        user_id=user.user_id,
        created_at=t,
        last_activity_at=t,
        expires_at=t + timedelta(hours=settings.session_max_age_hours),
    )
    db.add(session)
    db.flush()
    token, expires_in = create_access_token(str(user.user_id), session.session_id, session.expires_at)
    db.commit()
    return IssuedToken(token, expires_in, session)


def renew(db: Session, session: AuthSession) -> IssuedToken:
    """Record user activity and issue a fresh access token for the same session."""
    session.last_activity_at = now()
    token, expires_in = create_access_token(str(session.user_id), session.session_id, session.expires_at)
    db.commit()
    return IssuedToken(token, expires_in, session)


def problem(session: AuthSession | None, user_id: int) -> tuple[str, str] | None:
    """Why a session can no longer be used, as ``(reason, message)``; None if it can."""
    if session is None or session.user_id != user_id:
        return "session_revoked", "Your session has ended. Please sign in again."
    if session.revoked_at is not None:
        if session.revoked_reason == "idle":
            return "session_idle", idle_message()
        return "session_revoked", "Your session has ended. Please sign in again."
    t = now()
    if t >= session.expires_at:
        return "session_expired", "Your session has expired. Please sign in again."
    if t - session.last_activity_at > idle_timeout():
        return "session_idle", idle_message()
    return None


def idle_message() -> str:
    minutes = settings.session_idle_timeout_minutes
    return f"You were signed out after {minutes} minutes of inactivity. Please sign in again."


def revoke(db: Session, session: AuthSession, reason: str) -> None:
    if session.revoked_at is None:
        session.revoked_at = now()
        session.revoked_reason = reason
    db.commit()


def revoke_all(db: Session, user_id: int, reason: str, *, keep: int | None = None) -> int:
    """End every active session of a user (optionally keeping one). Returns the count."""
    stmt = (
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=now(), revoked_reason=reason)
    )
    if keep is not None:
        stmt = stmt.where(AuthSession.session_id != keep)
    return db.execute(stmt).rowcount or 0
