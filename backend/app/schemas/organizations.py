from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, EmailStr, model_validator

from app.models.enums import (
    DocumentStatus,
    MembershipRole,
    OrganizationStatus,
    OrganizationType,
)
from app.schemas.common import (
    Latitude,
    Longitude,
    LongText,
    Name,
    ORMModel,
    Phone,
    ShortText,
)


# Organizations ----------------------------------------------------------------
class OrganizationCreate(BaseModel):
    name: Name
    type: OrganizationType
    phone: Phone | None = None
    email: EmailStr | None = None


class OrganizationUpdate(BaseModel):
    name: Name | None = None
    phone: Phone | None = None
    email: EmailStr | None = None


class OrganizationResponse(ORMModel):
    organization_id: int
    name: str
    type: OrganizationType
    status: OrganizationStatus
    phone: str | None
    email: str | None
    created_at: datetime
    updated_at: datetime
    reviewed_at: datetime | None
    review_notes: str | None


class MyOrganizationResponse(OrganizationResponse):
    my_role: MembershipRole


# Members ----------------------------------------------------------------------
class MemberCreate(BaseModel):
    """Add an existing ApexRx user (by their account email) to the organization."""

    email: EmailStr
    role: MembershipRole


class MemberUpdate(BaseModel):
    role: MembershipRole | None = None
    is_active: bool | None = None


class MemberResponse(BaseModel):
    membership_id: int
    user_id: int
    name: str
    email: str
    phone: str | None
    role: MembershipRole
    is_active: bool
    created_at: datetime


# Locations --------------------------------------------------------------------
class _LocationFields(BaseModel):
    address: LongText | None = None
    city: ShortText | None = None
    region: ShortText | None = None
    latitude: Latitude | None = None
    longitude: Longitude | None = None
    phone: Phone | None = None
    whatsapp_phone: Phone | None = None

    @model_validator(mode="after")
    def _coordinates_together(self):
        fields = self.model_fields_set
        if ("latitude" in fields) != ("longitude" in fields):
            raise ValueError("latitude and longitude must be provided together")
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must both be set or both be null")
        return self


class LocationCreate(_LocationFields):
    name: Name


class LocationUpdate(_LocationFields):
    name: Name | None = None
    # Locations are deactivated, never deleted: their stock audit trail and
    # purchase orders keep referencing them.
    is_active: bool | None = None


class LocationResponse(ORMModel):
    location_id: int
    organization_id: int
    name: str
    address: str | None
    city: str | None
    region: str | None
    latitude: Decimal | None
    longitude: Decimal | None
    phone: str | None
    whatsapp_phone: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


# Documents --------------------------------------------------------------------
class DocumentResponse(ORMModel):
    document_id: int
    organization_id: int
    document_type: str
    file_name: str
    mime_type: str
    file_size_bytes: int
    verification_status: DocumentStatus
    uploaded_at: datetime
    reviewed_at: datetime | None
    rejection_reason: str | None
