from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

from app.models.enums import OrderStatus
from app.schemas.common import Currency, LongText, Money, PositiveQuantity


class OrderItemCreate(BaseModel):
    product_id: int
    quantity: PositiveQuantity


class OrderItemUpdate(BaseModel):
    quantity: PositiveQuantity


class PurchaseOrderCreate(BaseModel):
    pharmacy_organization_id: int
    supplier_organization_id: int
    pharmacy_location_id: int = Field(description="Pharmacy branch that receives the order.")
    supplier_location_id: int | None = Field(
        default=None,
        description="Preferred supplier warehouse. Prices are taken from this "
        "warehouse's offers; if omitted, the supplier's lowest listed price is used.",
    )
    currency: Currency | None = None
    notes: LongText | None = None
    items: list[OrderItemCreate] = Field(default_factory=list, max_length=200)

    @field_validator("items")
    @classmethod
    def _unique_products(cls, items: list[OrderItemCreate]):
        ids = [item.product_id for item in items]
        if len(ids) != len(set(ids)):
            raise ValueError("each product may appear only once per order")
        return items


class PurchaseOrderUpdate(BaseModel):
    """Draft-only edits."""

    pharmacy_location_id: int | None = None
    supplier_location_id: int | None = None
    notes: LongText | None = None


class CounterItem(BaseModel):
    purchase_order_item_id: int
    confirmed_quantity: PositiveQuantity
    confirmed_unit_price: Money


class CounterRequest(BaseModel):
    items: list[CounterItem] = Field(min_length=1)
    note: LongText | None = None


class AcceptRequest(BaseModel):
    supplier_location_id: int | None = Field(
        default=None, description="Warehouse that will fulfil the order."
    )
    note: LongText | None = None


class ReasonRequest(BaseModel):
    reason: LongText = Field(min_length=1)


class NoteRequest(BaseModel):
    note: LongText | None = None


class OrderItemResponse(BaseModel):
    purchase_order_item_id: int
    product_id: int
    product_name: str
    drug_name: str
    strength: str | None
    dosage_form: str | None
    pack_size: str | None
    requested_quantity: int
    requested_unit_price: Decimal
    confirmed_quantity: int | None
    confirmed_unit_price: Decimal | None
    requested_line_total: Decimal
    confirmed_line_total: Decimal | None


class StatusHistoryResponse(BaseModel):
    history_id: int
    from_status: OrderStatus | None
    to_status: OrderStatus
    changed_by: int | None
    changed_by_name: str | None
    changed_at: datetime
    note: str | None


class OrderPartyResponse(BaseModel):
    organization_id: int
    name: str
    location_id: int | None
    location_name: str | None
    phone: str | None
    whatsapp_phone: str | None


class PurchaseOrderSummary(BaseModel):
    purchase_order_id: int
    status: OrderStatus
    currency: str
    pharmacy: OrderPartyResponse
    supplier: OrderPartyResponse
    item_count: int
    requested_total: Decimal
    confirmed_total: Decimal | None
    created_at: datetime
    updated_at: datetime
    submitted_at: datetime | None
    responded_at: datetime | None


class PurchaseOrderResponse(PurchaseOrderSummary):
    notes: str | None
    rejection_reason: str | None
    created_by: int
    responded_by: int | None
    status_changed_by: int | None
    items: list[OrderItemResponse]
    history: list[StatusHistoryResponse]
    # Actions the calling user may perform next (drives UI buttons).
    allowed_actions: list[str]


class PriceChange(BaseModel):
    purchase_order_item_id: int
    product_id: int
    previous_unit_price: Decimal
    current_unit_price: Decimal | None
