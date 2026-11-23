"""account type: patient, pharmacy or supplier

Until now an account's kind was implied: an account with no organization
membership was treated as a patient, and any account could sign in on any
sign-in page. Each account now records which kind of customer it is, so
sign-in, registration and invitations can enforce it.

app_user.account_type, NOT NULL, one of 'patient' / 'pharmacy' / 'supplier'.
Existing accounts are filled in from their memberships (active or not):

* an account with memberships takes the type of the organization of its
  earliest membership (an account in both a pharmacy and a supplier keeps
  the first; the upgrade prints how many such accounts exist);
* an account with no membership becomes 'patient'. This includes anyone who
  started a business registration but never created the organization: they
  can finish it only after an administrator corrects the type (the upgrade
  prints how many accounts have no membership and no reservation).

Nothing else changes: no row is deleted, and no status or permission changes.

Revision ID: b8d2f6a3c1e7
Revises: a6c3e9d1f4b2
Create Date: 2026-11-23 18:00:00
"""

from typing import Sequence, Union

from sqlalchemy import text

from alembic import op

revision: str = "b8d2f6a3c1e7"
down_revision: Union[str, Sequence[str], None] = "a6c3e9d1f4b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE app_user
            ADD COLUMN account_type VARCHAR(20) NOT NULL DEFAULT 'patient',
            ADD CONSTRAINT app_user_account_type_check
                CHECK (account_type IN ('patient', 'pharmacy', 'supplier'));

        UPDATE app_user u
           SET account_type = first.type
          FROM (
                SELECT DISTINCT ON (m.user_id) m.user_id, o.type
                  FROM membership m
                  JOIN organization o ON o.organization_id = m.organization_id
                 ORDER BY m.user_id, m.membership_id
               ) AS first
         WHERE first.user_id = u.user_id;
        """
    )
    conn = op.get_bind()
    mixed = conn.execute(text(
        """
        SELECT count(*) FROM (
            SELECT m.user_id FROM membership m
              JOIN organization o ON o.organization_id = m.organization_id
             GROUP BY m.user_id HAVING count(DISTINCT o.type) > 1
        ) x
        """
    )).scalar()
    unclaimed = conn.execute(text(
        """
        SELECT count(*) FROM app_user u
         WHERE NOT u.is_platform_admin
           AND NOT EXISTS (SELECT 1 FROM membership m WHERE m.user_id = u.user_id)
           AND NOT EXISTS (SELECT 1 FROM reservation r WHERE r.patient_user_id = u.user_id)
        """
    )).scalar()
    counts = dict(conn.execute(text("SELECT account_type, count(*) FROM app_user GROUP BY 1")).all())
    print(f"account_type: {counts}; accounts in both a pharmacy and a supplier: {mixed}; "
          f"patient accounts with no membership and no reservation (review): {unclaimed}")


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE app_user
            DROP CONSTRAINT IF EXISTS app_user_account_type_check,
            DROP COLUMN IF EXISTS account_type;
        """
    )
