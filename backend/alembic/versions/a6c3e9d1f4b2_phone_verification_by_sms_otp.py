"""phone verification by SMS one-time code (eSMS Africa)

Reuses the phone_verification table and app_user.verified_phone /
phone_verified_at from c4d1e8f2a9b7 (left in place when email verification
replaced SMS). Additive only, nothing is dropped or rewritten:

* app_user.phone_verification_required: true for accounts that must verify
  their mobile number before using ApexRX (set by the application for accounts
  created while PHONE_VERIFICATION_REQUIRED is on, and when an account changes
  its number). Every existing account gets false: no one is locked out, and no
  existing number is marked verified.
* phone_verification.challenge_ref: the public, random identifier of a code
  (part of its HMAC). Older rows have none.
* phone_verification.provider / provider_message_id / delivery_status /
  delivery_status_at: what the SMS provider reported (no message content).
* Indexes for the platform-wide hourly ceiling and delivery reports.

Revision ID: a6c3e9d1f4b2
Revises: d4a7e2c9b1f8
Create Date: 2026-11-23 12:00:00
"""

from typing import Sequence, Union

from alembic import op

revision: str = "a6c3e9d1f4b2"
down_revision: Union[str, Sequence[str], None] = "d4a7e2c9b1f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE app_user
            ADD COLUMN phone_verification_required BOOLEAN NOT NULL DEFAULT false;

        ALTER TABLE phone_verification
            ADD COLUMN challenge_ref VARCHAR(43),
            ADD COLUMN provider VARCHAR(20),
            ADD COLUMN provider_message_id VARCHAR(100),
            ADD COLUMN delivery_status VARCHAR(30),
            ADD COLUMN delivery_status_at TIMESTAMPTZ,
            ADD CONSTRAINT phone_verification_challenge_ref_check
                CHECK (challenge_ref IS NULL OR challenge_ref ~ '^[A-Za-z0-9_-]{16,43}$');
        CREATE UNIQUE INDEX uq_phone_verification_challenge_ref
            ON phone_verification (challenge_ref) WHERE challenge_ref IS NOT NULL;
        CREATE INDEX ix_phone_verification_created
            ON phone_verification (created_at);
        CREATE INDEX ix_phone_verification_provider_message
            ON phone_verification (provider, provider_message_id) WHERE provider_message_id IS NOT NULL;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS ix_phone_verification_provider_message;
        DROP INDEX IF EXISTS ix_phone_verification_created;
        DROP INDEX IF EXISTS uq_phone_verification_challenge_ref;
        ALTER TABLE phone_verification
            DROP CONSTRAINT IF EXISTS phone_verification_challenge_ref_check,
            DROP COLUMN IF EXISTS delivery_status_at,
            DROP COLUMN IF EXISTS delivery_status,
            DROP COLUMN IF EXISTS provider_message_id,
            DROP COLUMN IF EXISTS provider,
            DROP COLUMN IF EXISTS challenge_ref;
        ALTER TABLE app_user DROP COLUMN IF EXISTS phone_verification_required;
        """
    )
