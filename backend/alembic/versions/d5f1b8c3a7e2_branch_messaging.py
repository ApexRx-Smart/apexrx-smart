"""branch-scoped pharmacy messaging

A pharmacy-to-supplier conversation now belongs to one pharmacy BRANCH (like
a shared chat for that branch), and pharmacy managers and staff are assigned
to the branches they work at:

* conversation.pharmacy_location_id (NOT NULL): the pharmacy branch. It must
  be a branch of the conversation's pharmacy (composite foreign key on
  location (location_id, organization_id)). One conversation per branch and
  supplier: uq_conversation_branch replaces uq_conversation_pair.
* membership_branch (membership_id, location_id): the branches a pharmacy
  manager or staff member works at. Owners see every branch and need no rows.
  The branch must belong to the membership's organization (composite foreign
  keys; membership gets a (membership_id, organization_id) unique key for it).

Who sees what (enforced in app/services/messaging.py): pharmacy owners, every
branch of their pharmacy; pharmacy managers and staff, the conversations of
their assigned branches; supplier members, every conversation of their
supplier. Nobody else.

Existing records (nothing is deleted; no message changes):

* Each existing conversation gets the branch of its procurement requests when
  it has any (they name the pharmacy branch), otherwise the pharmacy's main
  branch (its first active branch, or its first branch).
* Pharmacy managers and staff of a pharmacy with exactly one active branch
  are assigned to it. In a pharmacy with several branches they are not
  assigned: they see no conversation until an owner assigns their branches
  (team settings). The upgrade prints how many are waiting.

Revision ID: d5f1b8c3a7e2
Revises: c9e4a7b2d6f1
Create Date: 2026-11-24 14:00:00
"""

from typing import Sequence, Union

from sqlalchemy import text

from alembic import op

revision: str = "d5f1b8c3a7e2"
down_revision: Union[str, Sequence[str], None] = "c9e4a7b2d6f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    op.execute(
        """
        ALTER TABLE membership
            ADD CONSTRAINT membership_membership_id_organization_id_key UNIQUE (membership_id, organization_id);

        CREATE TABLE membership_branch (
            membership_id   BIGINT NOT NULL,
            organization_id BIGINT NOT NULL,
            location_id     BIGINT NOT NULL,
            assigned_by     BIGINT REFERENCES app_user (user_id),
            assigned_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT membership_branch_pkey PRIMARY KEY (membership_id, location_id),
            CONSTRAINT membership_branch_membership_fkey FOREIGN KEY (membership_id, organization_id)
                REFERENCES membership (membership_id, organization_id) ON DELETE CASCADE,
            CONSTRAINT membership_branch_location_fkey FOREIGN KEY (location_id, organization_id)
                REFERENCES location (location_id, organization_id)
        );
        CREATE INDEX ix_membership_branch_location ON membership_branch (location_id);

        ALTER TABLE conversation ADD COLUMN pharmacy_location_id BIGINT;

        -- The branch named by the conversation's procurement requests ...
        UPDATE conversation cv
           SET pharmacy_location_id = pr.pharmacy_location_id
          FROM (SELECT DISTINCT ON (conversation_id) conversation_id, pharmacy_location_id
                  FROM procurement_request
                 ORDER BY conversation_id, procurement_request_id) pr
         WHERE pr.conversation_id = cv.conversation_id;

        -- ... otherwise the pharmacy's main branch (first active, else first).
        UPDATE conversation cv
           SET pharmacy_location_id = (
                 SELECT l.location_id FROM location l
                  WHERE l.organization_id = cv.pharmacy_organization_id
                  ORDER BY l.is_active DESC, l.location_id
                  LIMIT 1)
         WHERE cv.pharmacy_location_id IS NULL;
        """
    )
    missing = conn.execute(text("SELECT count(*) FROM conversation WHERE pharmacy_location_id IS NULL")).scalar()
    if missing:
        raise RuntimeError(f"{missing} conversation(s) belong to a pharmacy without any branch; add a branch first.")
    op.execute(
        """
        ALTER TABLE conversation
            ALTER COLUMN pharmacy_location_id SET NOT NULL,
            ADD CONSTRAINT conversation_pharmacy_location_fkey
                FOREIGN KEY (pharmacy_location_id, pharmacy_organization_id)
                REFERENCES location (location_id, organization_id),
            DROP CONSTRAINT uq_conversation_pair,
            ADD CONSTRAINT uq_conversation_branch UNIQUE (pharmacy_location_id, supplier_organization_id);

        -- Managers and staff of a single-branch pharmacy work at that branch.
        INSERT INTO membership_branch (membership_id, organization_id, location_id)
        SELECT m.membership_id, m.organization_id, only_branch.location_id
          FROM membership m
          JOIN organization o ON o.organization_id = m.organization_id AND o.type = 'pharmacy'
          JOIN LATERAL (
                SELECT min(l.location_id) AS location_id, count(*) AS n
                  FROM location l WHERE l.organization_id = m.organization_id AND l.is_active
               ) only_branch ON only_branch.n = 1
         WHERE m.role <> 'owner';
        """
    )
    counts = conn.execute(text(
        """
        SELECT
          (SELECT count(*) FROM conversation),
          (SELECT count(*) FROM membership_branch),
          (SELECT count(*) FROM membership m JOIN organization o ON o.organization_id = m.organization_id
            WHERE o.type = 'pharmacy' AND m.is_active AND m.role <> 'owner'
              AND NOT EXISTS (SELECT 1 FROM membership_branch b WHERE b.membership_id = m.membership_id))
        """
    )).one()
    print(f"conversations placed on a branch: {counts[0]}; managers/staff assigned to their only branch: {counts[1]}; "
          f"managers/staff waiting for an owner to assign their branches: {counts[2]}")


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE conversation
            DROP CONSTRAINT IF EXISTS uq_conversation_branch,
            DROP CONSTRAINT IF EXISTS conversation_pharmacy_location_fkey;
        """
    )
    # Back to one conversation per pharmacy and supplier: only possible while no
    # pharmacy has two branch conversations with the same supplier.
    dup = op.get_bind().execute(text(
        "SELECT count(*) FROM (SELECT 1 FROM conversation GROUP BY pharmacy_organization_id, supplier_organization_id "
        "HAVING count(*) > 1) x"
    )).scalar()
    if dup:
        raise RuntimeError(f"{dup} pharmacy/supplier pair(s) have several branch conversations; cannot downgrade.")
    op.execute(
        """
        ALTER TABLE conversation
            ADD CONSTRAINT uq_conversation_pair UNIQUE (pharmacy_organization_id, supplier_organization_id),
            DROP COLUMN pharmacy_location_id;
        DROP TABLE IF EXISTS membership_branch;
        ALTER TABLE membership DROP CONSTRAINT IF EXISTS membership_membership_id_organization_id_key;
        """
    )
