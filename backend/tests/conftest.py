"""Integration tests against a real PostgreSQL database (the schema's triggers
are part of what is being tested).

Set TEST_DATABASE_URL to a disposable database whose name ends in ``_test``,
e.g. ``postgresql+psycopg://postgres:pw@localhost:5432/apexrx_test``.
The schema is rebuilt with ``alembic upgrade head`` at the start of the run and
all tables are truncated between tests.
"""

import os
import secrets
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
# A fresh random signing secret per run (placeholders are rejected at startup).
os.environ["JWT_SECRET_KEY"] = secrets.token_urlsafe(48)
# Set (not just removed): the app's settings also read backend/.env, so a value a
# developer keeps there must not change the tests. Empty means unset.
os.environ["TRUSTED_CLIENT_IP_HEADER"] = ""
# Test mode with the in-memory mock email provider (never a real provider).
os.environ["APP_ENV"] = "test"
os.environ["EMAIL_PROVIDER"] = "mock"
os.environ["FRONTEND_BASE_URL"] = "http://frontend.test"
# Most suites exercise the email-dependent code paths (kept for when email is
# re-enabled) with the mock provider and verification required. The production
# configuration (no email provider, verification off) is in test_without_email.py.
os.environ["EMAIL_VERIFICATION_REQUIRED"] = "true"
# SMS codes: the in-memory mock provider (never eSMS Africa, sandbox or live) and
# a random HMAC secret per run. Phone verification is NOT required by default, so
# the other suites run as existing accounts do; tests/test_phone_verification.py
# switches it on. Every SMS setting is set explicitly (empty = unset) so that an
# eSMS key or PHONE_VERIFICATION_REQUIRED kept in backend/.env for the real
# sandbox check (python -m app.scripts.check_sms) is never used by the tests.
os.environ["SMS_PROVIDER"] = "mock"
os.environ["OTP_HMAC_SECRET"] = secrets.token_urlsafe(48)
os.environ["PHONE_VERIFICATION_REQUIRED"] = "false"
os.environ["ESMS_MODE"] = "sandbox"
for _name in ("ESMS_API_KEY", "ESMS_WEBHOOK_SECRET", "ESMS_SENDER_ID", "ESMS_BASE_URL"):
    os.environ[_name] = ""
os.environ.pop("RATE_LIMIT_STORAGE_URI", None)
os.environ["UPLOAD_DIR"] = tempfile.mkdtemp(prefix="apexrx-uploads-")
# Never touch a real Supabase bucket by accident: tests use the local backend or
# the in-memory fake (see fake_bucket). tests/test_supabase_live.py builds its
# own client and only runs when SUPABASE_LIVE_TESTS=1.
os.environ["DOCUMENT_STORAGE"] = "local"

from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from storage3.exceptions import StorageApiError  # noqa: E402

from alembic import command  # noqa: E402
from app.core.database import engine  # noqa: E402
from app.main import app  # noqa: E402

TABLES = (
    "reservation_collection, reservation_status_history, reservation, offer_unit_acknowledgement, "
    "product_reservation_history, "
    "notification_read, notification, conversation_read, message, quotation_item, quotation, "
    "procurement_request_item, procurement_request, conversation, "
    "auth_session, organization_invitation, password_reset, email_verification, phone_verification, search_event, purchase_order_status_history, purchase_order_item, purchase_order, "
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
    from app.core.rate_limit import login_limiter, message_limiter, procurement_limiter, reservation_limiter
    from app.services.email import set_email_provider
    from app.services.email.mock import mock_provider
    from app.services.password_reset import limiter as reset_limiter
    from app.services.sms import set_sms_provider
    from app.services.sms.mock import mock_provider as sms_mock

    for reset in (login_limiter.reset, mock_provider.reset, reset_limiter.reset,
                  message_limiter.reset, procurement_limiter.reset, reservation_limiter.reset):
        reset()
    yield
    for reset in (login_limiter.reset, mock_provider.reset, reset_limiter.reset, sms_mock.reset):
        reset()
    set_email_provider(None)
    set_sms_provider(None)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


class FakeBucketFiles:
    """Mimics storage3's ``from_(bucket)`` file API, in memory."""

    def __init__(self, store: "FakeSupabase"):
        self.store = store

    def _check(self):
        if self.store.fail:
            raise StorageApiError("Service unavailable", "InternalError", 503)

    def upload(self, path, file, file_options=None):
        self._check()
        if path in self.store.objects:
            raise StorageApiError("The resource already exists", "Duplicate", 409)
        self.store.objects[path] = (bytes(file), dict(file_options or {}))
        return {"path": path}

    def download(self, path, options=None, query_params=None):
        self._check()
        if path not in self.store.objects:
            raise StorageApiError("Object not found", "not_found", 404)
        return self.store.objects[path][0]

    def remove(self, paths):
        self._check()
        for path in paths:
            self.store.objects.pop(path, None)
        return []


class FakeSupabase:
    def __init__(self):
        self.objects: dict[str, tuple[bytes, dict]] = {}
        self.buckets: list[str] = []
        self.fail = False

    def from_(self, bucket):
        self.buckets.append(bucket)
        return FakeBucketFiles(self)


@pytest.fixture
def fake_bucket():
    """Route document storage through the real SupabaseBackend, backed by an
    in-memory fake of the storage3 client."""
    from app.services import storage

    fake = FakeSupabase()
    storage.set_backend(storage.SupabaseBackend(fake, "organization-documents"))
    yield fake
    storage.set_backend(None)


@pytest.fixture
def app_logs(caplog):
    """caplog that also sees the application's "apexrx" loggers (which do not
    propagate to the root logger)."""
    import logging

    caplog.set_level(logging.DEBUG)
    # alembic's fileConfig (run by _schema) disables loggers that already exist.
    disabled = [lg for name, lg in logging.root.manager.loggerDict.items()
                if name.startswith("apexrx") and isinstance(lg, logging.Logger) and lg.disabled]
    for lg in disabled:
        lg.disabled = False
    logger = logging.getLogger("apexrx")
    previous = logger.level
    logger.addHandler(caplog.handler)
    logger.setLevel(logging.DEBUG)
    yield caplog
    logger.removeHandler(caplog.handler)
    logger.setLevel(previous)
    for lg in disabled:
        lg.disabled = True
