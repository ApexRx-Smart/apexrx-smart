from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at_column, identity_pk


class PhoneVerification(Base):
    """One SMS one-time code. Only an HMAC of the code is stored, bound to the
    user, the phone number and the purpose (see app/services/otp.py)."""

    __tablename__ = "phone_verification"

    verification_id: Mapped[int] = identity_pk()
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("app_user.user_id", ondelete="CASCADE"), nullable=False
    )
    phone_e164: Mapped[str] = mapped_column(String(20), nullable=False)
    purpose: Mapped[str] = mapped_column(String(40), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # HMAC of the client IP (only when trustworthy), used to count sends per IP.
    client_ip_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = created_at_column()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set when the SMS provider did not accept the message (row also invalidated).
    delivery_failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("attempts >= 0", name="phone_verification_attempts_check"),
        CheckConstraint("max_attempts > 0", name="phone_verification_max_attempts_check"),
        CheckConstraint(
            "delivery_failed_at IS NULL OR invalidated_at IS NOT NULL", name="phone_verification_failed_check"
        ),
        Index("ix_phone_verification_user_purpose", "user_id", "purpose", "created_at"),
        Index("ix_phone_verification_phone_created", "phone_e164", "created_at"),
        Index("ix_phone_verification_ip_created", "client_ip_hash", "created_at"),
        # At most one usable code per user and purpose (also enforced in the DB).
        Index(
            "uq_phone_verification_one_active",
            "user_id",
            "purpose",
            unique=True,
            postgresql_where=text("consumed_at IS NULL AND invalidated_at IS NULL"),
        ),
    )
