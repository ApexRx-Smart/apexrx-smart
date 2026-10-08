from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base


class Drug(Base):
    __tablename__ = "drug"

    drug_id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )

    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    therapeutic_class: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    products: Mapped[list["Product"]] = relationship(
    back_populates="drug"
)