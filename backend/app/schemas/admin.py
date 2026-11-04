from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, model_validator

from app.models.enums import OrganizationType
from app.schemas.common import LongText
from app.schemas.organizations import (
    DocumentResponse,
    LocationResponse,
    MemberResponse,
    OrganizationResponse,
)


class OrganizationDecision(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"
    SUSPENDED = "suspended"


class OrganizationReview(BaseModel):
    decision: OrganizationDecision
    notes: LongText | None = None

    @model_validator(mode="after")
    def _notes_required_for_negative(self):
        if self.decision != OrganizationDecision.APPROVED and not self.notes:
            raise ValueError("notes are required when rejecting or suspending an organization")
        return self


class DocumentDecision(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"


class DocumentReview(BaseModel):
    decision: DocumentDecision
    rejection_reason: LongText | None = None

    @model_validator(mode="after")
    def _reason_required(self):
        if self.decision == DocumentDecision.REJECTED and not self.rejection_reason:
            raise ValueError("rejection_reason is required when rejecting a document")
        return self


class AdminOrganizationDetail(OrganizationResponse):
    reviewed_by: int | None
    members: list[MemberResponse]
    locations: list[LocationResponse]
    documents: list[DocumentResponse]


class AdminDocumentResponse(DocumentResponse):
    organization_name: str
    organization_type: OrganizationType
    reviewed_by: int | None


class AdminUserUpdate(BaseModel):
    is_active: bool | None = None
    is_platform_admin: bool | None = None


class SearchInsight(BaseModel):
    query: str
    searches: int
    zero_result_searches: int
    last_searched_at: datetime
