"""email verification and structured Rwandan addresses

* app_user.email_verified_at, set by a successful email verification.
* email_verification: one row per verification link sent (only a SHA-256 hash
  of the link token and an HMAC of the client IP are stored; at most one usable
  link per user; delivery failures are recorded).
* location.sector / cell / village (with region = province and city = district,
  the existing columns, this holds a full Rwandan address).

Additive only. The former SMS phone verification data (phone_verification,
app_user.verified_phone / phone_verified_at) is left untouched: the code no
longer writes it, and it can be dropped by a later migration once confirmed.

Revision ID: e7b2f4a1c9d3
Revises: c4d1e8f2a9b7
Create Date: 2026-11-09 12:00:00
"""

from typing import Sequence, Union

from alembic import op

revision: str = "e7b2f4a1c9d3"
down_revision: Union[str, Sequence[str], None] = "c4d1e8f2a9b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE app_user ADD COLUMN email_verified_at TIMESTAMPTZ;

        CREATE TABLE email_verification (
            verification_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES app_user(user_id) ON DELETE CASCADE,
            email VARCHAR(255) NOT NULL,
            token_hash VARCHAR(64) NOT NULL UNIQUE,
            client_ip_hash VARCHAR(64),
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMPTZ NOT NULL,
            consumed_at TIMESTAMPTZ,
            invalidated_at TIMESTAMPTZ,
            delivery_failed_at TIMESTAMPTZ,
            CONSTRAINT email_verification_expiry_check CHECK (expires_at > created_at),
            CONSTRAINT email_verification_failed_check
                CHECK (delivery_failed_at IS NULL OR invalidated_at IS NOT NULL)
        );
        CREATE INDEX ix_email_verification_user_created ON email_verification (user_id, created_at);
        CREATE INDEX ix_email_verification_ip_created ON email_verification (client_ip_hash, created_at);
        -- At most one usable link per user, enforced by the database.
        CREATE UNIQUE INDEX uq_email_verification_one_active
            ON email_verification (user_id)
            WHERE consumed_at IS NULL AND invalidated_at IS NULL;

        ALTER TABLE location
            ADD COLUMN sector VARCHAR(100),
            ADD COLUMN cell VARCHAR(100),
            ADD COLUMN village VARCHAR(100);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE location
            DROP COLUMN IF EXISTS village,
            DROP COLUMN IF EXISTS cell,
            DROP COLUMN IF EXISTS sector;
        DROP TABLE IF EXISTS email_verification;
        ALTER TABLE app_user DROP COLUMN IF EXISTS email_verified_at;
        """
    )
