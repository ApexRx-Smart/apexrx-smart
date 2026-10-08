from sqlalchemy import BigInteger, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base


class Membership(Base):
    __tablename__ = "membership"

    membership_id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("app_user.user_id"),
        nullable=False,
    )

    organization_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("organization.organization_id"),
        nullable=False,
    )

    role: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    user: Mapped["User"] = relationship(
    back_populates="memberships"
)

    organization: Mapped["Organization"] = relationship(
    back_populates="memberships"
)

    __table_args__ = (
    UniqueConstraint(
        "user_id",
        "organization_id",
        name="uq_membership",
    ),
)