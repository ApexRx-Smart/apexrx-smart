from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, EmailStr, Field, StringConstraints, computed_field

from app.models.enums import MembershipRole, OrganizationStatus, OrganizationType
from app.schemas.common import ORMModel, Phone

PersonName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]
Password = Annotated[str, Field(min_length=8, max_length=128)]


class RegisterRequest(BaseModel):
    name: PersonName
    email: EmailStr
    phone: Phone | None = None
    password: Password


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    # Returned by an earlier successful sign-in on this browser (see
    # app/core/device_token.py). Optional; never a credential on its own.
    device_token: str | None = Field(default=None, max_length=512)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    # Keep on this browser and send with later sign-ins for this account.
    device_token: str | None = None
    # The server-side session: signed out after this many seconds without
    # user activity, and at session_expires_at at the latest.
    idle_timeout_seconds: int | None = None
    session_expires_at: datetime | None = None


class SessionResponse(BaseModel):
    idle_timeout_seconds: int
    last_activity_at: datetime
    idle_expires_at: datetime
    expires_at: datetime


class UserResponse(ORMModel):
    user_id: int
    name: str
    email: EmailStr
    phone: str | None
    email_verified_at: datetime | None = None
    # Historical (former SMS verification); no longer set.
    verified_phone: str | None = None
    phone_verified_at: datetime | None = None
    is_platform_admin: bool
    is_active: bool
    created_at: datetime

    @computed_field
    @property
    def email_verified(self) -> bool:
        return self.email_verified_at is not None


class MembershipSummary(BaseModel):
    membership_id: int
    organization_id: int
    organization_name: str
    organization_type: OrganizationType
    organization_status: OrganizationStatus
    role: MembershipRole


class MeResponse(UserResponse):
    memberships: list[MembershipSummary]


class UpdateMeRequest(BaseModel):
    name: PersonName | None = None
    phone: Phone | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: Password


# Email verification (emailed link) -----------------------------------------
class EmailSendRequest(BaseModel):
    # Which registration page the link returns to after verification.
    next: Literal["pharmacy", "supplier"] | None = None


class EmailSentResponse(BaseModel):
    email_masked: str
    expires_in: int
    resend_after: int


class EmailStatusResponse(BaseModel):
    email: EmailStr
    verified: bool
    verified_at: datetime | None
    required: bool  # registering an organization needs a verified email
    delivery_available: bool  # an email provider is configured
    pending: bool  # an unexpired link was sent to this address
    expires_at: datetime | None
    resend_after: int  # seconds until another email may be requested


class EmailVerifyRequest(BaseModel):
    token: str = Field(min_length=1, max_length=200)


class EmailVerifiedResponse(BaseModel):
    verified: bool = True
    already_verified: bool
    email_masked: str
