from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base


class Organization(Base):
    __tablename__ = "organization"

    organization_id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )

    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    memberships: Mapped[list["Membership"]] = relationship(
    back_populates="organization"
)

    locations: Mapped[list["Location"]] = relationship(
    back_populates="organization"
)