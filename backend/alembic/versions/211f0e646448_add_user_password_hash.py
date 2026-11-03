"""add user password hash

Revision ID: 211f0e646448
Revises: 5c11125c47b6
Create Date: 2026-10-12 09:23:21.085874

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '211f0e646448'
down_revision: Union[str, Sequence[str], None] = '5c11125c47b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _app_user_exists() -> bool:
    # On an empty database (fresh setup via `alembic upgrade head`) the
    # baseline schema was never created; a6f0c2d9e1b4 builds the v6 schema.
    return sa.inspect(op.get_bind()).has_table("app_user")


def upgrade() -> None:
    """Upgrade schema."""
    if _app_user_exists():
        op.add_column('app_user', sa.Column('password_hash', sa.String(length=255), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    if _app_user_exists():
        op.drop_column('app_user', 'password_hash')
