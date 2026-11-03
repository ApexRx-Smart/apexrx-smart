from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.enums import AvailabilityStatus, StockChangeType
from app.schemas.common import Currency, Money, Quantity


class StockUpsert(BaseModel):
    """Set the quantity on hand. Re-saving an unchanged quantity confirms it is
    still accurate and refreshes its freshness timestamp."""

    quantity: Quantity


class OfferUpsert(BaseModel):
    unit_price: Money
    currency: Currency | None = Field(
        default=None, description="ISO 4217 code. Defaults to the platform currency (RWF)."
    )
    low_stock_threshold: int = Field(default=5, ge=0, le=1_000_000)
    is_listed: bool = True


class OfferResponse(BaseModel):
    offer_id: int
    unit_price: Decimal
    currency: str
    low_stock_threshold: int
    is_listed: bool
    last_updated: datetime
    updated_by: int | None


class InventoryItem(BaseModel):
    """One product at one location, as seen by the owning organization."""

    stock_id: int
    location_id: int
    location_name: str
    product_id: int
    product_name: str
    drug_id: int
    drug_name: str
    brand: str | None
    strength: str | None
    dosage_form: str | None
    pack_size: str | None
    quantity: int
    last_updated: datetime
    updated_by: int | None
    offer: OfferResponse | None
    # What a patient (pharmacy) or pharmacy (supplier) currently sees:
    # null when the product is not listed.
    availability_status: AvailabilityStatus | None


class StockAdjustmentResponse(BaseModel):
    adjustment_id: int
    location_id: int
    product_id: int
    old_quantity: int | None
    new_quantity: int
    change_type: StockChangeType
    changed_by: int | None
    changed_by_name: str | None
    changed_at: datetime
