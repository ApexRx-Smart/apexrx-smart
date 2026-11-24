"""business applications: submitted_at (registration started vs submitted)

A pharmacy or supplier application moves through:

  1. registration started   status 'pending', submitted_at NULL
  2. submitted for review   status 'pending', submitted_at set: only possible
                            once every required document is uploaded
  3. reviewed               'approved', 'rejected' or 'suspended'

organization.submitted_at TIMESTAMPTZ NULL is the only new column; the
existing status column keeps its meaning (no second status field).

Existing organizations:

* approved, rejected or suspended: they were reviewed, so they count as
  submitted (the first document upload, or the registration date when there
  is none). Nothing about their status or access changes.
* pending with every required document uploaded and not rejected (pharmacy:
  pharmacy_license, business_license, owner_id; supplier: business_license,
  owner_id): submitted when the last of them was uploaded. They stay in the
  administrators' review queue.
* pending with a required document missing: registration in progress
  (submitted_at stays NULL). The owner uploads what is missing and submits;
  an administrator cannot approve them before that.

The upgrade prints how many organizations are in each group. Nothing is
deleted and no status changes.

Revision ID: c9e4a7b2d6f1
Revises: b8d2f6a3c1e7
Create Date: 2026-11-24 10:00:00
"""

from typing import Sequence, Union

from sqlalchemy import text

from alembic import op

revision: str = "c9e4a7b2d6f1"
down_revision: Union[str, Sequence[str], None] = "b8d2f6a3c1e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The same list as app/services/applications.py (kept here so the migration
# does not change if the application code does).
REQUIRED = {
    "pharmacy": ("pharmacy_license", "business_license", "owner_id"),
    "supplier": ("business_license", "owner_id"),
}


def upgrade() -> None:
    op.execute("ALTER TABLE organization ADD COLUMN submitted_at TIMESTAMPTZ")
    op.execute(
        """
        UPDATE organization o
           SET submitted_at = COALESCE(
                   (SELECT min(d.uploaded_at) FROM organization_document d
                     WHERE d.organization_id = o.organization_id),
                   o.created_at)
         WHERE o.status IN ('approved', 'rejected', 'suspended')
        """
    )
    for org_type, docs in REQUIRED.items():
        op.get_bind().execute(
            text(
                """
                UPDATE organization o
                   SET submitted_at = (
                         SELECT max(d.uploaded_at) FROM organization_document d
                          WHERE d.organization_id = o.organization_id
                            AND d.document_type = ANY(:docs)
                            AND d.verification_status <> 'rejected')
                 WHERE o.status = 'pending' AND o.type = :type
                   AND (SELECT count(DISTINCT d.document_type) FROM organization_document d
                         WHERE d.organization_id = o.organization_id
                           AND d.document_type = ANY(:docs)
                           AND d.verification_status <> 'rejected') = :needed
                """
            ),
            {"docs": list(docs), "type": org_type, "needed": len(docs)},
        )
    rows = op.get_bind().execute(text(
        """
        SELECT CASE WHEN status <> 'pending' THEN status
                    WHEN submitted_at IS NOT NULL THEN 'pending, submitted (awaiting review)'
                    ELSE 'pending, in progress (documents missing)' END AS stage, count(*)
          FROM organization GROUP BY 1 ORDER BY 1
        """
    )).all()
    print("organizations: " + "; ".join(f"{stage}: {n}" for stage, n in rows))


def downgrade() -> None:
    op.execute("ALTER TABLE organization DROP COLUMN IF EXISTS submitted_at")
