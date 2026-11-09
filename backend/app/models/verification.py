from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at_column, identity_pk


class EmailVerification(Base):
    """One emailed verification link. Only a SHA-256 hash of the link's random
    token is stored, bound to the user and to the address it was sent to (see
    app/services/email_verification.py)."""

    __tablename__ = "email_verification"

    verification_id: Mapped[int] = identity_pk()
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("app_user.user_id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    # HMAC of the client IP (only when trustworthy), used to count sends per IP.
    client_ip_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = created_at_column()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set when a newer link replaces this one, or when delivery failed.
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set when the email provider did not accept the message (row also invalidated).
    delivery_failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("expires_at > created_at", name="email_verification_expiry_check"),
        CheckConstraint(
            "delivery_failed_at IS NULL OR invalidated_at IS NOT NULL", name="email_verification_failed_check"
        ),
        Index("ix_email_verification_user_created", "user_id", "created_at"),
        Index("ix_email_verification_ip_created", "client_ip_hash", "created_at"),
        # At most one usable link per user (also enforced in the database).
        Index(
            "uq_email_verification_one_active",
            "user_id",
            unique=True,
            postgresql_where=text("consumed_at IS NULL AND invalidated_at IS NULL"),
        ),
    )
