"""phone verification by SMS one-time code

Adds app_user.verified_phone / phone_verified_at and the phone_verification
table (one row per code sent; only HMACs of the code and of the client IP are
stored; delivery failures are recorded).

Revision ID: c4d1e8f2a9b7
Revises: a6f0c2d9e1b4
Create Date: 2026-11-06 12:00:00
"""

from typing import Sequence, Union

from alembic import op

revision: str = "c4d1e8f2a9b7"
down_revision: Union[str, Sequence[str], None] = "a6f0c2d9e1b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE app_user
            ADD COLUMN verified_phone VARCHAR(20),
            ADD COLUMN phone_verified_at TIMESTAMPTZ,
            ADD CONSTRAINT app_user_verified_phone_check
                CHECK ((verified_phone IS NULL) = (phone_verified_at IS NULL)),
            ADD CONSTRAINT app_user_verified_phone_e164_check
                CHECK (verified_phone IS NULL OR verified_phone ~ '^\\+[1-9][0-9]{6,14}$');

        CREATE TABLE phone_verification (
            verification_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES app_user(user_id) ON DELETE CASCADE,
            phone_e164 VARCHAR(20) NOT NULL CHECK (phone_e164 ~ '^\\+[1-9][0-9]{6,14}$'),
            purpose VARCHAR(40) NOT NULL,
            code_hash VARCHAR(64) NOT NULL,
            client_ip_hash VARCHAR(64),
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMPTZ NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL,
            consumed_at TIMESTAMPTZ,
            invalidated_at TIMESTAMPTZ,
            delivery_failed_at TIMESTAMPTZ,
            CONSTRAINT phone_verification_attempts_check CHECK (attempts >= 0),
            CONSTRAINT phone_verification_max_attempts_check CHECK (max_attempts > 0),
            CONSTRAINT phone_verification_expiry_check CHECK (expires_at > created_at),
            CONSTRAINT phone_verification_failed_check
                CHECK (delivery_failed_at IS NULL OR invalidated_at IS NOT NULL)
        );
        CREATE INDEX ix_phone_verification_user_purpose
            ON phone_verification (user_id, purpose, created_at);
        CREATE INDEX ix_phone_verification_phone_created
            ON phone_verification (phone_e164, created_at);
        CREATE INDEX ix_phone_verification_ip_created
            ON phone_verification (client_ip_hash, created_at);
        -- At most one usable code per user and purpose, enforced by the database.
        CREATE UNIQUE INDEX uq_phone_verification_one_active
            ON phone_verification (user_id, purpose)
            WHERE consumed_at IS NULL AND invalidated_at IS NULL;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS phone_verification;
        ALTER TABLE app_user
            DROP CONSTRAINT IF EXISTS app_user_verified_phone_e164_check,
            DROP CONSTRAINT IF EXISTS app_user_verified_phone_check,
            DROP COLUMN IF EXISTS phone_verified_at,
            DROP COLUMN IF EXISTS verified_phone;
        """
    )
