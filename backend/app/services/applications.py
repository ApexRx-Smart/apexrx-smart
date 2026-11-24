"""Pharmacy and supplier applications: required documents and the stage of a
registration.

  in_progress      status 'pending', not submitted yet (documents may be missing)
  awaiting_review  status 'pending', submitted: every required document uploaded
  approved / rejected / suspended   the administrators' decision

Only an approved organization uses ApexRX's operational features (stock,
offers, orders, procurement, messages, reservations, dashboards); see
app/api/deps.py get_org_access(require_approved=True).

The required documents are the ones the registration has always asked for;
nothing else is required.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Organization, OrganizationDocument
from app.models.enums import DocumentStatus, OrganizationStatus

REQUIRED_DOCUMENTS: dict[str, tuple[str, ...]] = {
    "pharmacy": ("pharmacy_license", "business_license", "owner_id"),
    "supplier": ("business_license", "owner_id"),
}
DOCUMENT_LABELS = {
    "pharmacy_license": "Pharmacy license",
    "business_license": "Business license",
    "owner_id": "Owner ID",
}
# A document of each type counts by its best status: approved, then pending
# (uploaded, awaiting review), then rejected (must be replaced).
_RANK = {DocumentStatus.APPROVED: 2, DocumentStatus.PENDING: 1, DocumentStatus.REJECTED: 0}


@dataclass
class ChecklistItem:
    document_type: str
    label: str
    status: str  # missing / pending / approved / rejected
    document_id: int | None
    file_name: str | None
    uploaded_at: datetime | None
    rejection_reason: str | None


def allowed_document_types(org_type: str) -> tuple[str, ...]:
    return REQUIRED_DOCUMENTS.get(org_type, ())


def checklist(db: Session, organization: Organization) -> list[ChecklistItem]:
    docs = db.scalars(
        select(OrganizationDocument)
        .where(OrganizationDocument.organization_id == organization.organization_id)
        .order_by(OrganizationDocument.uploaded_at.desc(), OrganizationDocument.document_id.desc())
    ).all()
    items = []
    for doc_type in allowed_document_types(organization.type):
        mine = [d for d in docs if d.document_type == doc_type]
        best = max(mine, key=lambda d: (_RANK[DocumentStatus(d.verification_status)], d.uploaded_at), default=None)
        items.append(ChecklistItem(
            document_type=doc_type,
            label=DOCUMENT_LABELS[doc_type],
            status=best.verification_status if best else "missing",
            document_id=best.document_id if best else None,
            file_name=best.file_name if best else None,
            uploaded_at=best.uploaded_at if best else None,
            rejection_reason=best.rejection_reason if best else None,
        ))
    return items


def missing(items: list[ChecklistItem]) -> list[ChecklistItem]:
    """Required documents with no usable upload (none yet, or only rejected ones)."""
    return [i for i in items if i.status in ("missing", DocumentStatus.REJECTED)]


def not_approved(items: list[ChecklistItem]) -> list[ChecklistItem]:
    return [i for i in items if i.status != DocumentStatus.APPROVED]


def stage(organization: Organization) -> str:
    if organization.status != OrganizationStatus.PENDING:
        return organization.status
    return "awaiting_review" if organization.submitted_at is not None else "in_progress"
