from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, model_validator

from app.schemas.common import LongText, Money, PositiveQuantity

MedicineName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
Spec = Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)]
ItemNote = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]


class RequestItemCreate(BaseModel):
    """A catalogue product (``product_id``), or a medicine described in words
    when it is not in the catalogue (``medicine_name`` and optional details)."""

    product_id: int | None = None
    medicine_name: MedicineName | None = None
    strength: Spec | None = None
    dosage_form: Spec | None = None
    pack_size: Spec | None = None
    quantity: PositiveQuantity
    notes: ItemNote | None = None

    @model_validator(mode="after")
    def _product_or_name(self):
        if self.product_id is None and not self.medicine_name:
            raise ValueError("give a catalogue product_id or a medicine_name")
        return self


class ProcurementRequestCreate(BaseModel):
    pharmacy_organization_id: int
    supplier_organization_id: int
    pharmacy_location_id: int = Field(description="Pharmacy branch the medicines are for.")
    notes: LongText | None = None
    needed_by: date | None = None
    items: list[RequestItemCreate] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def _unique_products(self):
        ids = [i.product_id for i in self.items if i.product_id is not None]
        if len(ids) != len(set(ids)):
            raise ValueError("each catalogue product may appear only once per request")
        return self


class QuotationItemInput(BaseModel):
    procurement_request_item_id: int
    available: bool
    quantity: PositiveQuantity | None = None
    unit_price: Money | None = None
    note: ItemNote | None = None


class QuotationInput(BaseModel):
    items: list[QuotationItemInput] = Field(min_length=1, max_length=100)
    note: LongText | None = None
    estimated_days: int | None = Field(default=None, ge=0, le=365)
    submit: bool = Field(default=True, description="Send it now; false saves a draft.")


class ReasonInput(BaseModel):
    reason: LongText = Field(min_length=1)


class NoteInput(BaseModel):
    note: LongText | None = None


class ConvertInput(BaseModel):
    pharmacy_location_id: int | None = Field(
        default=None, description="Branch receiving the order; the request's branch when omitted."
    )


class RequestItemResponse(BaseModel):
    procurement_request_item_id: int
    line_no: int
    product_id: int | None
    in_catalogue: bool
    medicine_name: str
    strength: str | None
    dosage_form: str | None
    pack_size: str | None
    quantity: int
    notes: str | None


class QuotationItemResponse(BaseModel):
    quotation_item_id: int
    procurement_request_item_id: int
    available: bool
    quantity: int | None
    unit_price: Decimal | None
    line_total: Decimal | None
    note: str | None


class QuotationResponse(BaseModel):
    quotation_id: int
    revision: int
    status: str
    currency: str
    note: str | None
    estimated_days: int | None
    total: Decimal
    submitted_by_name: str | None
    submitted_at: datetime | None
    responded_by_name: str | None
    responded_at: datetime | None
    response_note: str | None
    updated_at: datetime
    items: list[QuotationItemResponse]


class Party(BaseModel):
    organization_id: int
    name: str
    location_id: int | None = None
    location_name: str | None = None


class ProcurementRequestSummary(BaseModel):
    procurement_request_id: int
    status: str
    pharmacy: Party
    supplier: Party
    conversation_id: int
    item_count: int
    currency: str
    latest_quotation_status: str | None
    latest_quotation_total: Decimal | None
    purchase_order_id: int | None
    created_at: datetime
    updated_at: datetime
    needs_my_action: bool


class ProcurementRequestResponse(ProcurementRequestSummary):
    notes: str | None
    needed_by: date | None
    status_reason: str | None
    created_by_name: str | None
    viewed_at: datetime | None
    items: list[RequestItemResponse]
    quotations: list[QuotationResponse]
    allowed_actions: list[str]


class ConvertResponse(BaseModel):
    purchase_order_id: int
    created: bool
    request: ProcurementRequestResponse
