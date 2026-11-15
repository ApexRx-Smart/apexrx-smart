"""Procurement requests (a pharmacy asks one supplier for prices) and the
supplier's quotations. See migration b7c3e9d1f4a6 and app.services.procurement."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, created_at_column, identity_pk


class ProcurementRequest(Base):
    __tablename__ = "procurement_request"

    procurement_request_id: Mapped[int] = identity_pk()
    pharmacy_organization_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    supplier_organization_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    pharmacy_org_type: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'pharmacy'"), default="pharmacy"
    )
    supplier_org_type: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'supplier'"), default="supplier"
    )
    pharmacy_location_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    conversation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("conversation.conversation_id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="submitted")
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False, server_default=text("'RWF'"))
    notes: Mapped[str | None] = mapped_column(Text)
    needed_by: Mapped[date | None] = mapped_column(Date)
    status_reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.user_id"))
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = created_at_column()
    viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    items: Mapped[list["ProcurementRequestItem"]] = relationship(
        order_by="ProcurementRequestItem.line_no", passive_deletes=True
    )
    quotations: Mapped[list["Quotation"]] = relationship(
        order_by="Quotation.revision", passive_deletes=True
    )


class ProcurementRequestItem(Base):
    __tablename__ = "procurement_request_item"

    procurement_request_item_id: Mapped[int] = identity_pk()
    procurement_request_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("procurement_request.procurement_request_id", ondelete="CASCADE"),
        nullable=False,
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    product_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("product.product_id"))
    medicine_name: Mapped[str] = mapped_column(String(255), nullable=False)
    strength: Mapped[str | None] = mapped_column(String(100))
    dosage_form: Mapped[str | None] = mapped_column(String(100))
    pack_size: Mapped[str | None] = mapped_column(String(100))
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)


class Quotation(Base):
    __tablename__ = "quotation"

    quotation_id: Mapped[int] = identity_pk()
    procurement_request_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("procurement_request.procurement_request_id", ondelete="CASCADE"),
        nullable=False,
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False, server_default=text("'RWF'"))
    note: Mapped[str | None] = mapped_column(Text)
    estimated_days: Mapped[int | None] = mapped_column(Integer)
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.user_id"))
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = created_at_column()
    submitted_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.user_id"))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    responded_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.user_id"))
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    response_note: Mapped[str | None] = mapped_column(Text)

    items: Mapped[list["QuotationItem"]] = relationship(
        order_by="QuotationItem.quotation_item_id", cascade="all, delete-orphan", passive_deletes=True
    )


class QuotationItem(Base):
    __tablename__ = "quotation_item"

    quotation_item_id: Mapped[int] = identity_pk()
    quotation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("quotation.quotation_id", ondelete="CASCADE"), nullable=False
    )
    procurement_request_item_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("procurement_request_item.procurement_request_item_id"), nullable=False
    )
    available: Mapped[bool] = mapped_column(Boolean, nullable=False)
    quantity: Mapped[int | None] = mapped_column(Integer)
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    note: Mapped[str | None] = mapped_column(Text)
