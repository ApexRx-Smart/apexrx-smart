"""Sign-in sessions, staff invitations and password resets."""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at_column, identity_pk


class AuthSession(Base):
    """One signed-in session (a sign-in on one browser tab). Access tokens carry
    its id (``sid``) and are only accepted while it is not revoked, not idle for
    longer than SESSION_IDLE_TIMEOUT_MINUTES and younger than
    SESSION_MAX_AGE_HOURS (see app/api/deps.py)."""

    __tablename__ = "auth_session"

    session_id: Mapped[int] = identity_pk()
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("app_user.user_id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = created_at_column()
    # Moved forward only by real user activity (POST /auth/session/activity) and sign-in.
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # signed_out | idle | expired | password_changed | password_reset
    revoked_reason: Mapped[str | None] = mapped_column(String(30))

    __table_args__ = (
        CheckConstraint("expires_at > created_at", name="auth_session_expiry_check"),
        CheckConstraint("(revoked_at IS NULL) = (revoked_reason IS NULL)", name="auth_session_revoked_check"),
        Index("ix_auth_session_user_active", "user_id", postgresql_where=text("revoked_at IS NULL")),
    )


class OrganizationInvitation(Base):
    """An owner's or manager's invitation for an email address to join an
    organization with a role. The membership is only created when the person
    who controls that address accepts it. Only a SHA-256 hash of the link's
    token is stored; resending replaces it (one usable link per invitation)."""

    __tablename__ = "organization_invitation"

    invitation_id: Mapped[int] = identity_pk()
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organization.organization_id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)  # normalized (lower case)
    role: Mapped[str] = mapped_column(String(30), nullable=False)
    invited_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("app_user.user_id", ondelete="SET NULL")
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = created_at_column()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Email delivery: the last time the provider accepted the message, or the
    # last failure (cleared by a later successful send).
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    send_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    send_failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("app_user.user_id", ondelete="SET NULL")
    )
    account_created: Mapped[bool | None] = mapped_column()  # True: accepted by setting up a new account
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("app_user.user_id", ondelete="SET NULL")
    )

    __table_args__ = (
        CheckConstraint("role IN ('owner', 'manager', 'staff')", name="organization_invitation_role_check"),
        CheckConstraint("expires_at > created_at", name="organization_invitation_expiry_check"),
        CheckConstraint("NOT (accepted_at IS NOT NULL AND revoked_at IS NOT NULL)", name="organization_invitation_state_check"),
        Index("ix_organization_invitation_org", "organization_id", "created_at"),
        # At most one open invitation per organization and address.
        Index(
            "uq_organization_invitation_open",
            "organization_id",
            "email",
            unique=True,
            postgresql_where=text("accepted_at IS NULL AND revoked_at IS NULL"),
        ),
    )


class PasswordReset(Base):
    """One emailed password-reset link. Only a SHA-256 hash of its token is
    stored; single use; requesting a new one invalidates the earlier ones."""

    __tablename__ = "password_reset"

    reset_id: Mapped[int] = identity_pk()
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("app_user.user_id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    client_ip_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = created_at_column()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivery_failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("expires_at > created_at", name="password_reset_expiry_check"),
        Index("ix_password_reset_user_created", "user_id", "created_at"),
        Index("ix_password_reset_ip_created", "client_ip_hash", "created_at"),
        Index(
            "uq_password_reset_one_active",
            "user_id",
            unique=True,
            postgresql_where=text("used_at IS NULL AND invalidated_at IS NULL"),
        ),
    )
