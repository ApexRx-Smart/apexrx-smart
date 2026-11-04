from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, StringConstraints

from app.schemas.common import Name, ORMModel, ShortText

Barcode = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class DrugCreate(BaseModel):
    name: Name
    therapeutic_class: Name | None = None


class DrugUpdate(BaseModel):
    name: Name | None = None
    therapeutic_class: Name | None = None


class DrugResponse(ORMModel):
    drug_id: int
    name: str
    therapeutic_class: str | None
    created_at: datetime


class ProductCreate(BaseModel):
    drug_id: int
    product_name: Name
    brand: Name | None = None
    strength: ShortText | None = None
    dosage_form: ShortText | None = None
    pack_size: ShortText | None = None
    barcode: Barcode | None = None
    manufacturer: Name | None = None


class ProductUpdate(BaseModel):
    drug_id: int | None = None
    product_name: Name | None = None
    brand: Name | None = None
    strength: ShortText | None = None
    dosage_form: ShortText | None = None
    pack_size: ShortText | None = None
    barcode: Barcode | None = None
    manufacturer: Name | None = None
    is_active: bool | None = None


class ProductResponse(ORMModel):
    product_id: int
    drug_id: int
    drug_name: str
    product_name: str
    brand: str | None
    strength: str | None
    dosage_form: str | None
    pack_size: str | None
    barcode: str | None
    manufacturer: str | None
    is_active: bool
    created_at: datetime
