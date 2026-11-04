"""Stock, offers and the stock audit trail.

``updated_by`` / ``last_updated`` are stamped by triggers from the
transaction actor (``app.user_id``); any value the application sets is
overwritten. See ``app.core.database.set_session_actor``.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    CheckConstraint,
    FetchedValue,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    created_at_column,
    identity_pk,
    server_timestamp_column,
)


def _trigger_actor_column():
    return mapped_column(
        BigInteger,
        ForeignKey("app_user.user_id"),
        server_default=FetchedValue(),
        server_onupdate=FetchedValue(),
    )


class Stock(Base):
    """Quantity of a catalogue product held at a location."""

    __tablename__ = "stock"

    stock_id: Mapped[int] = identity_pk()
    location_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("location.location_id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("product.product_id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    last_updated: Mapped[datetime] = server_timestamp_column()
    updated_by: Mapped[int | None] = _trigger_actor_column()

    __table_args__ = (
        CheckConstraint("quantity >= 0", name="stock_quantity_check"),
        UniqueConstraint("location_id", "product_id", name="stock_location_id_product_id_key"),
        Index("idx_stock_product_location", "product_id", "location_id"),
    )


class ProductOffer(Base):
    """A location lists a product at a price. Availability is derived from stock."""

    __tablename__ = "product_offer"

    offer_id: Mapped[int] = identity_pk()
    location_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    product_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False, server_default=text("'RWF'"))
    low_stock_threshold: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("5"), default=5
    )
    is_listed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true"), default=True
    )
    last_updated: Mapped[datetime] = server_timestamp_column()
    updated_by: Mapped[int | None] = _trigger_actor_column()

    __table_args__ = (
        CheckConstraint("unit_price >= 0", name="product_offer_unit_price_check"),
        CheckConstraint("low_stock_threshold >= 0", name="product_offer_low_stock_threshold_check"),
        UniqueConstraint("location_id", "product_id", name="product_offer_location_id_product_id_key"),
        # Guarantees every offer has a matching stock row.
        ForeignKeyConstraint(
            ["location_id", "product_id"],
            ["stock.location_id", "stock.product_id"],
            ondelete="CASCADE",
            name="product_offer_location_id_product_id_fkey",
        ),
        Index("idx_offer_product_listed", "product_id", "is_listed"),
    )


class StockAdjustment(Base):
    """Audit trail written by triggers. Read-only from the application."""

    __tablename__ = "stock_adjustment"

    adjustment_id: Mapped[int] = identity_pk()
    location_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("location.location_id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("product.product_id"), nullable=False)
    old_quantity: Mapped[int | None] = mapped_column(Integer)
    new_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    changed_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.user_id"))
    changed_at: Mapped[datetime] = created_at_column()
    change_type: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'quantity_update'")
    )

    __table_args__ = (
        CheckConstraint(
            "old_quantity IS NULL OR old_quantity >= 0", name="stock_adjustment_old_quantity_check"
        ),
        CheckConstraint("new_quantity >= 0", name="stock_adjustment_new_quantity_check"),
        CheckConstraint(
            "change_type IN ('initial_stock', 'quantity_update', 'stock_deleted')",
            name="stock_adjustment_change_type_check",
        ),
        Index("idx_stock_adjustment_lookup", "location_id", "product_id", "changed_at"),
    )


class SearchEvent(Base):
    """Anonymous patient search log (demand signal). Coarse location only."""

    __tablename__ = "search_event"

    search_event_id: Mapped[int] = identity_pk()
    query_text: Mapped[str] = mapped_column(String(255), nullable=False)
    drug_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("drug.drug_id", ondelete="SET NULL")
    )
    product_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("product.product_id", ondelete="SET NULL")
    )
    approx_latitude: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    approx_longitude: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    results_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), default=0
    )
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        CheckConstraint("results_count >= 0", name="search_event_results_count_check"),
        CheckConstraint(
            "approx_latitude IS NULL OR approx_latitude BETWEEN -90 AND 90",
            name="search_event_approx_latitude_check",
        ),
        CheckConstraint(
            "approx_longitude IS NULL OR approx_longitude BETWEEN -180 AND 180",
            name="search_event_approx_longitude_check",
        ),
        Index("idx_search_event_created", "created_at"),
        Index(
            "idx_search_event_product",
            "product_id",
            postgresql_where=text("product_id IS NOT NULL"),
        ),
    )
