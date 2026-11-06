from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, EmailStr, Field, StringConstraints

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


class UserResponse(ORMModel):
    user_id: int
    name: str
    email: EmailStr
    phone: str | None
    verified_phone: str | None = None
    phone_verified_at: datetime | None = None
    is_platform_admin: bool
    is_active: bool
    created_at: datetime


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


# Phone verification (SMS one-time code) --------------------------------------
class PhoneCodeRequest(BaseModel):
    # Validated and normalized by app/services/phone.py (clear messages).
    phone: str = Field(max_length=40)


class PhoneVerifyRequest(BaseModel):
    phone: str = Field(max_length=40)
    code: str = Field(max_length=20)


class PhoneCodeSentResponse(BaseModel):
    phone: str  # the normalized E.164 number the code was sent to
    phone_masked: str
    expires_in: int
    resend_after: int


class PhoneStatusResponse(BaseModel):
    required: bool  # creating a pharmacy needs a verified phone
    verified: bool
    verified_phone: str | None
    sms_available: bool


class PhoneVerifiedResponse(BaseModel):
    verified: bool = True
    verified_phone: str
