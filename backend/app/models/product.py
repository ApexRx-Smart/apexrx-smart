from sqlalchemy import BigInteger, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base


class Product(Base):
    __tablename__ = "product"

    product_id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )

    drug_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("drug.drug_id"),
        nullable=False,
    )

    product_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    brand: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    strength: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    dosage_form: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    pack_size: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    barcode: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    manufacturer: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    drug: Mapped["Drug"] = relationship(
    back_populates="products"
)

    batches: Mapped[list["Batch"]] = relationship(
    back_populates="product"
)