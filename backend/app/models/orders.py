"""Purchase orders between a pharmacy and a supplier.

created_by, status_changed_by, responded_by, responded_at and submitted_at are
maintained by ``purchase_order_before_write``; status history rows are written
by ``purchase_order_log_status``. The application only changes ``status`` and
the editable fields.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CHAR,
    BigInteger,
    CheckConstraint,
    DateTime,
    FetchedValue,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    Base,
    created_at_column,
    identity_pk,
    server_timestamp_column,
)

_ORDER_STATUSES = (
    "'draft', 'submitted', 'countered', 'accepted', 'rejected', "
    "'processing', 'dispatched', 'delivered', 'cancelled'"
)


def _trigger_column(type_, *args, **kwargs):
    return mapped_column(
        type_, *args, server_default=FetchedValue(), server_onupdate=FetchedValue(), **kwargs
    )


class PurchaseOrder(Base):
    __tablename__ = "purchase_order"

    purchase_order_id: Mapped[int] = identity_pk()
    pharmacy_organization_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    supplier_organization_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # Constant columns that let the composite FKs enforce each organization's type.
    pharmacy_org_type: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'pharmacy'"), default="pharmacy"
    )
    supplier_org_type: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'supplier'"), default="supplier"
    )
    pharmacy_location_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    supplier_location_id: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'draft'"), default="draft"
    )
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False, server_default=text("'RWF'"))
    notes: Mapped[str | None] = mapped_column(Text)
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int] = _trigger_column(
        BigInteger, ForeignKey("app_user.user_id"), nullable=False
    )
    responded_by: Mapped[int | None] = _trigger_column(BigInteger, ForeignKey("app_user.user_id"))
    status_changed_by: Mapped[int | None] = _trigger_column(
        BigInteger, ForeignKey("app_user.user_id")
    )
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = server_timestamp_column()
    submitted_at: Mapped[datetime | None] = _trigger_column(DateTime(timezone=True))
    responded_at: Mapped[datetime | None] = _trigger_column(DateTime(timezone=True))

    items: Mapped[list["PurchaseOrderItem"]] = relationship(
        back_populates="purchase_order",
        order_by="PurchaseOrderItem.purchase_order_item_id",
        passive_deletes=True,
    )
    history: Mapped[list["PurchaseOrderStatusHistory"]] = relationship(
        order_by="PurchaseOrderStatusHistory.history_id",
        viewonly=True,
    )

    __table_args__ = (
        CheckConstraint("pharmacy_org_type = 'pharmacy'", name="purchase_order_pharmacy_org_type_check"),
        CheckConstraint("supplier_org_type = 'supplier'", name="purchase_order_supplier_org_type_check"),
        CheckConstraint(f"status IN ({_ORDER_STATUSES})", name="purchase_order_status_check"),
        CheckConstraint(
            "pharmacy_organization_id <> supplier_organization_id", name="purchase_order_check"
        ),
        CheckConstraint(
            "status IN ('draft', 'cancelled') OR submitted_at IS NOT NULL", name="purchase_order_check1"
        ),
        CheckConstraint(
            "status IN ('draft', 'submitted', 'cancelled') OR responded_at IS NOT NULL",
            name="purchase_order_check2",
        ),
        ForeignKeyConstraint(
            ["pharmacy_organization_id", "pharmacy_org_type"],
            ["organization.organization_id", "organization.type"],
            name="purchase_order_pharmacy_organization_id_pharmacy_org_type_fkey",
        ),
        ForeignKeyConstraint(
            ["supplier_organization_id", "supplier_org_type"],
            ["organization.organization_id", "organization.type"],
            name="purchase_order_supplier_organization_id_supplier_org_type_fkey",
        ),
        ForeignKeyConstraint(
            ["pharmacy_location_id", "pharmacy_organization_id"],
            ["location.location_id", "location.organization_id"],
            name="purchase_order_pharmacy_location_id_pharmacy_organizatio_fkey",
        ),
        ForeignKeyConstraint(
            ["supplier_location_id", "supplier_organization_id"],
            ["location.location_id", "location.organization_id"],
            name="purchase_order_supplier_location_id_supplier_organizatio_fkey",
        ),
        Index("idx_purchase_order_pharmacy", "pharmacy_organization_id", "created_at"),
        Index("idx_purchase_order_supplier", "supplier_organization_id", "status", "created_at"),
    )


class PurchaseOrderItem(Base):
    __tablename__ = "purchase_order_item"

    purchase_order_item_id: Mapped[int] = identity_pk()
    purchase_order_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("purchase_order.purchase_order_id", ondelete="CASCADE"),
        nullable=False,
    )
    product_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("product.product_id"), nullable=False)
    requested_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    # Supplier price the pharmacy saw when ordering (snapshot).
    requested_unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    # Supplier's accepted values, or proposed values while status = 'countered'.
    confirmed_quantity: Mapped[int | None] = mapped_column(Integer)
    confirmed_unit_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))

    purchase_order: Mapped[PurchaseOrder] = relationship(back_populates="items")

    __table_args__ = (
        CheckConstraint("requested_quantity > 0", name="purchase_order_item_requested_quantity_check"),
        CheckConstraint(
            "requested_unit_price >= 0", name="purchase_order_item_requested_unit_price_check"
        ),
        CheckConstraint("confirmed_quantity > 0", name="purchase_order_item_confirmed_quantity_check"),
        CheckConstraint(
            "confirmed_unit_price >= 0", name="purchase_order_item_confirmed_unit_price_check"
        ),
        CheckConstraint(
            "confirmed_quantity IS NULL OR confirmed_quantity <= requested_quantity",
            name="purchase_order_item_check",
        ),
        CheckConstraint(
            "(confirmed_quantity IS NULL) = (confirmed_unit_price IS NULL)",
            name="purchase_order_item_check1",
        ),
        UniqueConstraint(
            "purchase_order_id", "product_id", name="purchase_order_item_purchase_order_id_product_id_key"
        ),
        Index("idx_purchase_order_item_product", "product_id"),
    )


class PurchaseOrderStatusHistory(Base):
    """Written by the purchase_order_log_status trigger."""

    __tablename__ = "purchase_order_status_history"

    history_id: Mapped[int] = identity_pk()
    purchase_order_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("purchase_order.purchase_order_id", ondelete="CASCADE"),
        nullable=False,
    )
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    changed_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.user_id"))
    changed_at: Mapped[datetime] = created_at_column()
    note: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(f"to_status IN ({_ORDER_STATUSES})", name="purchase_order_status_history_to_status_check"),
        CheckConstraint(
            f"from_status IS NULL OR from_status IN ({_ORDER_STATUSES})",
            name="purchase_order_status_history_check",
        ),
        Index("idx_po_status_history_po", "purchase_order_id", "changed_at"),
    )
