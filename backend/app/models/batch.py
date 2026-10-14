from datetime import date

from sqlalchemy import BigInteger, Date, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base


class Batch(Base):
    __tablename__ = "batch"

    batch_id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )

    product_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("product.product_id"),
        nullable=False,
    )

    batch_number: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    expiry_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "product_id",
            "batch_number",
            name="uq_batch_product",
        ),
    )

    product: Mapped["Product"] = relationship(
    back_populates="batches"
)