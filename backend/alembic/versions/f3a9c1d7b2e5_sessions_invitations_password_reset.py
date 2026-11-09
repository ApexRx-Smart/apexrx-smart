"""server-side sessions, staff invitations and password resets

* auth_session: one row per sign-in. Access tokens name it, and the backend
  refuses tokens whose session was signed out, is idle for longer than
  SESSION_IDLE_TIMEOUT_MINUTES or is older than SESSION_MAX_AGE_HOURS. Needed
  because a JWT alone cannot be revoked (sign-out) or expire on inactivity.
* organization_invitation: invitations by email and role. The membership is
  created only when the invitation is accepted; only token hashes are stored.
* password_reset: emailed single-use reset links (token hashes only).

Additive only: no existing table or row changes. Tokens issued before this
migration carry no session id and are refused, so users sign in once again.

Revision ID: f3a9c1d7b2e5
Revises: e7b2f4a1c9d3
Create Date: 2026-11-10 09:00:00
"""

from typing import Sequence, Union

from alembic import op

revision: str = "f3a9c1d7b2e5"
down_revision: Union[str, Sequence[str], None] = "e7b2f4a1c9d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE auth_session (
            session_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES app_user(user_id) ON DELETE CASCADE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_activity_at TIMESTAMPTZ NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            revoked_at TIMESTAMPTZ,
            revoked_reason VARCHAR(30),
            CONSTRAINT auth_session_expiry_check CHECK (expires_at > created_at),
            CONSTRAINT auth_session_revoked_check CHECK ((revoked_at IS NULL) = (revoked_reason IS NULL))
        );
        CREATE INDEX ix_auth_session_user_active ON auth_session (user_id) WHERE revoked_at IS NULL;

        CREATE TABLE organization_invitation (
            invitation_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            organization_id BIGINT NOT NULL REFERENCES organization(organization_id) ON DELETE CASCADE,
            email VARCHAR(255) NOT NULL,
            role VARCHAR(30) NOT NULL,
            invited_by BIGINT REFERENCES app_user(user_id) ON DELETE SET NULL,
            token_hash VARCHAR(64) NOT NULL UNIQUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMPTZ NOT NULL,
            sent_at TIMESTAMPTZ,
            send_count INTEGER NOT NULL DEFAULT 0,
            send_failed_at TIMESTAMPTZ,
            accepted_at TIMESTAMPTZ,
            accepted_by BIGINT REFERENCES app_user(user_id) ON DELETE SET NULL,
            account_created BOOLEAN,
            revoked_at TIMESTAMPTZ,
            revoked_by BIGINT REFERENCES app_user(user_id) ON DELETE SET NULL,
            CONSTRAINT organization_invitation_role_check CHECK (role IN ('owner', 'manager', 'staff')),
            CONSTRAINT organization_invitation_expiry_check CHECK (expires_at > created_at),
            CONSTRAINT organization_invitation_state_check
                CHECK (NOT (accepted_at IS NOT NULL AND revoked_at IS NOT NULL))
        );
        CREATE INDEX ix_organization_invitation_org ON organization_invitation (organization_id, created_at);
        CREATE UNIQUE INDEX uq_organization_invitation_open
            ON organization_invitation (organization_id, email)
            WHERE accepted_at IS NULL AND revoked_at IS NULL;

        CREATE TABLE password_reset (
            reset_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES app_user(user_id) ON DELETE CASCADE,
            token_hash VARCHAR(64) NOT NULL UNIQUE,
            client_ip_hash VARCHAR(64),
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMPTZ NOT NULL,
            used_at TIMESTAMPTZ,
            invalidated_at TIMESTAMPTZ,
            delivery_failed_at TIMESTAMPTZ,
            CONSTRAINT password_reset_expiry_check CHECK (expires_at > created_at)
        );
        CREATE INDEX ix_password_reset_user_created ON password_reset (user_id, created_at);
        CREATE INDEX ix_password_reset_ip_created ON password_reset (client_ip_hash, created_at);
        CREATE UNIQUE INDEX uq_password_reset_one_active
            ON password_reset (user_id) WHERE used_at IS NULL AND invalidated_at IS NULL;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS password_reset;
        DROP TABLE IF EXISTS organization_invitation;
        DROP TABLE IF EXISTS auth_session;
        """
    )
