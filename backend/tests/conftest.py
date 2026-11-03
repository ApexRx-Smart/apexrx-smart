"""Integration tests against a real PostgreSQL database (the schema's triggers
are part of what is being tested).

Set TEST_DATABASE_URL to a disposable database whose name ends in ``_test``,
e.g. ``postgresql+psycopg://postgres:pw@localhost:5432/apexrx_test``.
The schema is rebuilt with ``alembic upgrade head`` at the start of the run and
all tables are truncated between tests.
"""

import os
import tempfile
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url

BACKEND_DIR = Path(__file__).resolve().parents[1]

_test_url = os.environ.get("TEST_DATABASE_URL")
if not _test_url:
    pytest.exit("Set TEST_DATABASE_URL to a disposable *_test database to run the tests.", returncode=2)
if not (make_url(_test_url).database or "").endswith("_test"):
    pytest.exit("Refusing to run: the TEST_DATABASE_URL database name must end with '_test'.", returncode=2)

os.environ["DATABASE_URL"] = _test_url
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough")
os.environ["UPLOAD_DIR"] = tempfile.mkdtemp(prefix="apexrx-uploads-")

from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from alembic import command  # noqa: E402
from app.core.database import engine  # noqa: E402
from app.main import app  # noqa: E402

TABLES = (
    "search_event, purchase_order_status_history, purchase_order_item, purchase_order, "
    "stock_adjustment, product_offer, stock, product, drug, organization_document, "
    "location, membership, organization, app_user"
)


@pytest.fixture(scope="session", autouse=True)
def _schema():
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.upgrade(config, "head")
    yield


@pytest.fixture(autouse=True)
def _clean():
    yield
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c
