"""Shared medicine catalogue: drugs (active ingredients) and products (SKUs)."""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, ForeignKey, Index, String, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, created_at_column, identity_pk


class Drug(Base):
    __tablename__ = "drug"

    drug_id: Mapped[int] = identity_pk()
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    therapeutic_class: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = created_at_column()

    products: Mapped[list["Product"]] = relationship(back_populates="drug")

    __table_args__ = (Index("uq_drug_name", func.lower(func.btrim(name)), unique=True),)


class Product(Base):
    __tablename__ = "product"

    product_id: Mapped[int] = identity_pk()
    drug_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("drug.drug_id"), nullable=False)
    product_name: Mapped[str] = mapped_column(String(255), nullable=False)
    brand: Mapped[str | None] = mapped_column(String(255))
    strength: Mapped[str | None] = mapped_column(String(100))
    dosage_form: Mapped[str | None] = mapped_column(String(100))
    pack_size: Mapped[str | None] = mapped_column(String(100))
    barcode: Mapped[str | None] = mapped_column(String(100))
    manufacturer: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true"), default=True
    )
    created_at: Mapped[datetime] = created_at_column()

    drug: Mapped[Drug] = relationship(back_populates="products", lazy="joined")

    __table_args__ = (
        # Prevent duplicate catalogue entries (NULL-safe).
        Index(
            "uq_product_identity",
            drug_id,
            func.lower(func.btrim(func.coalesce(brand, ""))),
            func.lower(func.btrim(func.coalesce(strength, ""))),
            func.lower(func.btrim(func.coalesce(dosage_form, ""))),
            func.lower(func.btrim(func.coalesce(pack_size, ""))),
            func.lower(func.btrim(func.coalesce(manufacturer, ""))),
            unique=True,
        ),
        Index(
            "uq_product_barcode",
            func.lower(func.btrim(barcode)),
            unique=True,
            postgresql_where=text("barcode IS NOT NULL AND btrim(barcode) <> ''"),
        ),
        Index("idx_product_drug", "drug_id"),
    )
