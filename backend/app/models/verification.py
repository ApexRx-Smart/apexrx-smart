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
    created_at: Mapped[datetime] = created_at_column()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("attempts >= 0", name="phone_verification_attempts_check"),
        CheckConstraint("max_attempts > 0", name="phone_verification_max_attempts_check"),
        Index("ix_phone_verification_user_purpose", "user_id", "purpose", "created_at"),
        Index("ix_phone_verification_phone_created", "phone_e164", "created_at"),
    )
