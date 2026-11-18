"""Patient medicine reservations. See migration c8e5a1f7d2b9 and
app.services.reservations.

Most lifecycle columns are written by database triggers (actor, deadlines,
snapshots, collection stock figures); values the application sets for them
are ignored or rejected. They are mapped with FetchedValue so the ORM reads
them back after INSERT/UPDATE.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    DateTime,
    FetchedValue,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, identity_pk


def _db_set(type_, *args, **kwargs):
    """A column the database triggers write."""
    return mapped_column(type_, *args, server_default=FetchedValue(), server_onupdate=FetchedValue(), **kwargs)


class ReservationStatus:
    REQUESTED = "requested"
    CONFIRMED = "confirmed"
    DECLINED = "declined"
    CANCELLED = "cancelled"
    COLLECTED = "collected"
    EXPIRED = "expired"

    OPEN = (REQUESTED, CONFIRMED)


class OfferUnitAcknowledgement(Base):
    """An owner or manager confirms that a branch counts a product in the
    catalogue's current stock unit. Insert-only, one row per unit_version."""

    __tablename__ = "offer_unit_acknowledgement"

    location_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("location.location_id"), primary_key=True)
    product_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("product.product_id"), primary_key=True)
    unit_version: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_unit: Mapped[str] = mapped_column(String(10), nullable=False)
    unit_label: Mapped[str] = mapped_column(String(60), nullable=False)
    pack_size: Mapped[str | None] = mapped_column(String(100))  # as shown; must match a pack's contents
    acknowledged_by: Mapped[int] = _db_set(BigInteger, ForeignKey("app_user.user_id"))
    acknowledged_at: Mapped[datetime] = _db_set(DateTime(timezone=True))


class Reservation(Base):
    __tablename__ = "reservation"

    reservation_id: Mapped[int] = identity_pk()
    reference: Mapped[str] = mapped_column(String(13), nullable=False, unique=True)
    patient_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("app_user.user_id"), nullable=False)
    pharmacy_organization_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    pharmacy_org_type: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'pharmacy'"), default="pharmacy"
    )
    location_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    product_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("product.product_id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    contact_phone: Mapped[str] = mapped_column(String(30), nullable=False)
    patient_note: Mapped[str | None] = mapped_column(Text)
    client_request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'requested'"), default=ReservationStatus.REQUESTED
    )
    status_source: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default=text("'patient'"), default="patient"
    )
    decline_reason: Mapped[str | None] = mapped_column(Text)
    cancel_reason: Mapped[str | None] = mapped_column(Text)

    # Written by the triggers.
    unit_version: Mapped[int] = _db_set(Integer)
    stock_unit: Mapped[str] = _db_set(String(10))
    unit_label: Mapped[str] = _db_set(String(60))
    pack_size: Mapped[str | None] = _db_set(String(100))
    unit_price: Mapped[Decimal] = _db_set(Numeric(14, 2))
    currency: Mapped[str] = _db_set(CHAR(3))
    status_reason: Mapped[str | None] = _db_set(String(40))
    status_changed_by: Mapped[int | None] = _db_set(BigInteger, ForeignKey("app_user.user_id"))
    status_changed_at: Mapped[datetime] = _db_set(DateTime(timezone=True))
    created_at: Mapped[datetime] = _db_set(DateTime(timezone=True))
    respond_by: Mapped[datetime] = _db_set(DateTime(timezone=True))
    responded_at: Mapped[datetime | None] = _db_set(DateTime(timezone=True))
    responded_by: Mapped[int | None] = _db_set(BigInteger, ForeignKey("app_user.user_id"))
    confirmed_at: Mapped[datetime | None] = _db_set(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = _db_set(DateTime(timezone=True))
    collected_at: Mapped[datetime | None] = _db_set(DateTime(timezone=True))
    collected_by: Mapped[int | None] = _db_set(BigInteger, ForeignKey("app_user.user_id"))
    cancelled_at: Mapped[datetime | None] = _db_set(DateTime(timezone=True))
    cancelled_by_role: Mapped[str | None] = _db_set(String(10))


class ReservationStatusHistory(Base):
    """Written by trg_reservation_log_status; read-only."""

    __tablename__ = "reservation_status_history"

    history_id: Mapped[int] = identity_pk()
    reservation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("reservation.reservation_id"), nullable=False
    )
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    source: Mapped[str] = mapped_column(String(10), nullable=False)
    changed_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.user_id"))
    system_reason: Mapped[str | None] = mapped_column(String(40))
    reason: Mapped[str | None] = mapped_column(Text)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ReservationCollection(Base):
    """Insert-only record of a collection. Its trigger deducts the stock and
    records the exact stock adjustments; see the migration."""

    __tablename__ = "reservation_collection"

    reservation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("reservation.reservation_id"), primary_key=True
    )
    override: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), default=False)
    verified_on_hand: Mapped[int | None] = mapped_column(Integer)
    recorded_quantity_seen: Mapped[int | None] = mapped_column(Integer)
    override_reason: Mapped[str | None] = mapped_column(Text)

    # Written by the trigger.
    override_by: Mapped[int | None] = _db_set(BigInteger, ForeignKey("app_user.user_id"))
    collected_by: Mapped[int] = _db_set(BigInteger, ForeignKey("app_user.user_id"))
    collected_at: Mapped[datetime] = _db_set(DateTime(timezone=True))
    collected_xid: Mapped[str] = _db_set(Text)  # xid8, read as text
    quantity: Mapped[int] = _db_set(Integer)
    recorded_quantity_before: Mapped[int] = _db_set(Integer)
    quantity_after: Mapped[int] = _db_set(Integer)
    correction_adjustment_id: Mapped[int | None] = _db_set(
        BigInteger, ForeignKey("stock_adjustment.adjustment_id")
    )
    deduction_adjustment_id: Mapped[int] = _db_set(BigInteger, ForeignKey("stock_adjustment.adjustment_id"))


class ProductReservationHistory(Base):
    """Written by trg_product_reservation_log; read-only."""

    __tablename__ = "product_reservation_history"

    history_id: Mapped[int] = identity_pk()
    product_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("product.product_id"), nullable=False)
    dispensing_class: Mapped[str] = mapped_column(String(20), nullable=False)
    stock_unit: Mapped[str] = mapped_column(String(10), nullable=False)
    unit_label: Mapped[str | None] = mapped_column(String(60))
    pack_size: Mapped[str | None] = mapped_column(String(100))
    unit_version: Mapped[int] = mapped_column(Integer, nullable=False)
    max_reservation_quantity: Mapped[int | None] = mapped_column(Integer)
    reservation_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    changed_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("app_user.user_id"), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
