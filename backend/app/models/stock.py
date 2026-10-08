from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    TIMESTAMP,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Stock(Base):
    __tablename__ = "stock"

    stock_id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )

    location_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("location.location_id"),
        nullable=False,
    )

    batch_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("batch.batch_id"),
        nullable=False,
    )

    quantity: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )

    availability: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    last_updated: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    __table_args__ = (
        UniqueConstraint(
            "location_id",
            "batch_id",
            name="uq_stock_location_batch",
        ),
        CheckConstraint(
            "quantity >= 0",
            name="chk_stock_quantity",
        ),
    )