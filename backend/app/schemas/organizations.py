from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, EmailStr, Field, StringConstraints, model_validator

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
    # Rwandan address: region = province, city = district, then sector, cell
    # and village; address = street or landmark.
    address: LongText | None = None
    city: ShortText | None = None
    region: ShortText | None = None
    sector: ShortText | None = None
    cell: ShortText | None = None
    village: ShortText | None = None
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
    sector: str | None = None
    cell: str | None = None
    village: str | None = None
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


# Invitations ------------------------------------------------------------------
class InvitationCreate(BaseModel):
    email: EmailStr
    role: MembershipRole


class InvitationResponse(BaseModel):
    invitation_id: int
    email: str
    role: MembershipRole
    status: str  # pending | accepted | revoked | expired
    delivery: str  # sent | failed | not_sent | link (shared by the inviter while email is disabled)
    created_at: datetime
    expires_at: datetime
    sent_at: datetime | None
    send_count: int
    accepted_at: datetime | None
    account_created: bool | None
    revoked_at: datetime | None
    invited_by_name: str | None


class InvitationSendResponse(InvitationResponse):
    email_sent: bool
    detail: str
    # Only while email is disabled: the link's token, for the inviter to share.
    share_token: str | None = None


class InvitationTokenRequest(BaseModel):
    token: str = Field(min_length=1, max_length=200)


class InvitationPreview(BaseModel):
    organization_name: str
    organization_type: OrganizationType
    role: MembershipRole
    email: str  # the invited address (the link holder controls that mailbox)
    invited_by_name: str | None
    expires_at: datetime
    account_exists: bool


class InvitationAcceptNew(InvitationTokenRequest):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]
    password: Annotated[str, Field(min_length=8, max_length=128)]


class InvitationAccepted(BaseModel):
    organization_id: int
    organization_name: str
    organization_type: OrganizationType
    role: MembershipRole
