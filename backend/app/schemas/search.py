from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel

from app.models.enums import AvailabilityStatus


class MedicineMatch(BaseModel):
    product_id: int
    product_name: str
    drug_id: int
    drug_name: str
    brand: str | None
    strength: str | None
    dosage_form: str | None
    pack_size: str | None
    # Number of pharmacy locations currently reporting it in stock or low stock.
    available_pharmacy_count: int


class PharmacySort(StrEnum):
    DISTANCE = "distance"
    PRICE = "price"  # lowest first
    PRICE_DESC = "price_desc"  # highest first
    FRESHNESS = "freshness"


class PharmacyAvailability(BaseModel):
    """Patient-facing result. Never includes the exact quantity."""

    offer_id: int
    product_id: int
    product_name: str
    drug_id: int
    drug_name: str
    strength: str | None
    dosage_form: str | None
    pharmacy_organization_id: int
    pharmacy_name: str
    location_id: int
    location_name: str
    address: str | None
    latitude: Decimal | None
    longitude: Decimal | None
    phone: str | None
    unit_price: Decimal
    currency: str
    availability_status: AvailabilityStatus
    last_updated: datetime
    distance_km: float | None
    directions_url: str | None


class PharmacyLocationDetail(BaseModel):
    pharmacy_organization_id: int
    pharmacy_name: str
    location_id: int
    location_name: str
    address: str | None
    city: str | None
    region: str | None
    latitude: Decimal | None
    longitude: Decimal | None
    phone: str | None
    directions_url: str | None
    medicines: list[PharmacyAvailability]


class SupplierSort(StrEnum):
    PRICE = "price"
    DISTANCE = "distance"
    QUANTITY = "quantity"
    FRESHNESS = "freshness"


class SupplierOffer(BaseModel):
    """Pharmacy-facing supplier listing, WITH exact quantity."""

    offer_id: int
    product_id: int
    product_name: str
    drug_id: int
    drug_name: str
    strength: str | None
    dosage_form: str | None
    pack_size: str | None
    supplier_organization_id: int
    supplier_name: str
    supplier_location_id: int
    location_name: str
    city: str | None
    latitude: Decimal | None
    longitude: Decimal | None
    phone: str | None
    whatsapp_phone: str | None
    whatsapp_url: str | None
    unit_price: Decimal
    currency: str
    quantity: int
    last_updated: datetime
    distance_km: float | None


class LegacyAvailability(BaseModel):
    """Shape consumed by the current static frontend search box."""

    drug_name: str
    product_name: str
    brand: str | None
    strength: str | None
    dosage_form: str | None
    pharmacy_name: str
    city: str | None
    availability: str
    unit_price: Decimal
    currency: str
    last_updated: datetime
