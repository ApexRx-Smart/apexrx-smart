from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, text
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


class PhoneVerification(Base):
    """One SMS one-time code ("challenge"). Only a keyed HMAC of the code is
    stored, bound to the challenge, the user, the phone number and the purpose
    (see app/services/otp.py). ``challenge_ref`` is the public identifier the
    client sends back with the code; rows from the former SMS feature have none
    and can never be verified."""

    __tablename__ = "phone_verification"

    verification_id: Mapped[int] = identity_pk()
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("app_user.user_id", ondelete="CASCADE"), nullable=False
    )
    phone_e164: Mapped[str] = mapped_column(String(20), nullable=False)
    purpose: Mapped[str] = mapped_column(String(40), nullable=False)
    challenge_ref: Mapped[str | None] = mapped_column(String(43))
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # HMAC of the client IP (only when trustworthy), used to count sends per IP.
    client_ip_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = created_at_column()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set when a newer code replaces this one, when it expires or runs out of
    # attempts, or when delivery failed.
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set when the SMS provider did not accept the message (row also invalidated).
    delivery_failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # What the provider reported: its message id and latest delivery status.
    provider: Mapped[str | None] = mapped_column(String(20))
    provider_message_id: Mapped[str | None] = mapped_column(String(100))
    delivery_status: Mapped[str | None] = mapped_column(String(30))
    delivery_status_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("attempts >= 0", name="phone_verification_attempts_check"),
        CheckConstraint("max_attempts > 0", name="phone_verification_max_attempts_check"),
        CheckConstraint("expires_at > created_at", name="phone_verification_expiry_check"),
        CheckConstraint(
            "delivery_failed_at IS NULL OR invalidated_at IS NOT NULL", name="phone_verification_failed_check"
        ),
        CheckConstraint(
            "challenge_ref IS NULL OR challenge_ref ~ '^[A-Za-z0-9_-]{16,43}$'",
            name="phone_verification_challenge_ref_check",
        ),
        Index("ix_phone_verification_user_purpose", "user_id", "purpose", "created_at"),
        Index("ix_phone_verification_phone_created", "phone_e164", "created_at"),
        Index("ix_phone_verification_ip_created", "client_ip_hash", "created_at"),
        Index("ix_phone_verification_created", "created_at"),
        Index(
            "uq_phone_verification_challenge_ref",
            "challenge_ref",
            unique=True,
            postgresql_where=text("challenge_ref IS NOT NULL"),
        ),
        Index(
            "ix_phone_verification_provider_message",
            "provider",
            "provider_message_id",
            postgresql_where=text("provider_message_id IS NOT NULL"),
        ),
        # At most one usable code per user and purpose (also enforced in the DB).
        Index(
            "uq_phone_verification_one_active",
            "user_id",
            "purpose",
            unique=True,
            postgresql_where=text("consumed_at IS NULL AND invalidated_at IS NULL"),
        ),
    )
