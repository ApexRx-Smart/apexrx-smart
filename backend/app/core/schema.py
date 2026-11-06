"""Database schema version check.

The service does not run migrations by itself (Render only starts uvicorn),
and the ORM models expect the latest schema: code deployed before
``alembic upgrade head`` fails on every query that loads a user (sign-in,
registration, the workspace, admin). This module lets /health and the startup
log report that clearly instead of a generic database error.
"""

from functools import lru_cache
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

BACKEND_DIR = Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def expected_revision() -> str:
    """The newest migration shipped with this code (Alembic head)."""
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return ScriptDirectory.from_config(config).get_current_head()


def current_revision(connection: Connection) -> str | None:
    try:
        return connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except SQLAlchemyError:
        connection.rollback()
        return None


def schema_problem(connection: Connection) -> str | None:
    """A message if the database is not at the code's migration head."""
    expected = expected_revision()
    current = current_revision(connection)
    if current == expected:
        return None
    return (
        f"Database schema is not up to date (database: {current or 'unknown'}, code expects: {expected}). "
        "Apply the migrations with `alembic upgrade head` before deploying this code."
    )
