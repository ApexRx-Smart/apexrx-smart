"""JWT signing secret validation at startup (app.core.config.Settings)."""

import secrets
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings

DB = "postgresql+psycopg://user:pw@localhost:5432/apexrx_v6_test"
BACKEND_DIR = Path(__file__).resolve().parents[1]


def build(**values):
    return Settings(_env_file=None, database_url=DB, **values)


def assert_rejected(secret, expected_message):
    with pytest.raises(ValidationError) as info:
        build(jwt_secret_key=secret)
    text = str(info.value)
    assert expected_message in text
    # The secret itself is never echoed back (startup logs would show it).
    if secret and len(secret) >= 6:
        assert secret not in text
        assert "input_value" not in text


def test_missing_secret_fails_clearly(monkeypatch):
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    with pytest.raises(ValidationError) as info:
        build()
    assert "jwt_secret_key" in str(info.value) and "Field required" in str(info.value)


@pytest.mark.parametrize("secret", ["", "   ", "\t\n"])
def test_empty_secret_rejected(secret):
    assert_rejected(secret, "JWT_SECRET_KEY is empty")


@pytest.mark.parametrize(
    "secret",
    [
        "replace-with-a-long-random-secret",  # the old .env.example value
        "test-secret-key-that-is-long-enough",  # the old test default
        "REPLACE-WITH-A-LONG-RANDOM-SECRET",
        "CHANGE-ME-generate-with-python-secrets-token-urlsafe-48",
        "this-is-a-placeholder-value-that-is-long-enough-to-pass",
        "your-secret-goes-here-0123456789abcdefghij",
        "changeme",
    ],
)
def test_known_placeholders_rejected(secret):
    assert_rejected(secret, "placeholder")


def test_env_example_value_is_rejected():
    line = next(
        line
        for line in (BACKEND_DIR / ".env.example").read_text(encoding="utf-8").splitlines()
        if line.startswith("JWT_SECRET_KEY=")
    )
    assert_rejected(line.split("=", 1)[1].strip(), "placeholder")


@pytest.mark.parametrize("length", [1, 16, 31])
def test_short_secret_rejected(length):
    assert_rejected(secrets.token_hex(32)[:length], "at least 32 characters")


@pytest.mark.parametrize("secret", [secrets.token_hex(16), secrets.token_urlsafe(48), "A" * 31 + "b"])
def test_valid_secret_accepted(secret):
    assert len(secret) >= 32
    assert build(jwt_secret_key=secret).jwt_secret_key == secret


def test_x_forwarded_for_is_refused_as_trusted_header():
    with pytest.raises(ValidationError) as info:
        build(jwt_secret_key=secrets.token_urlsafe(48), trusted_client_ip_header="X-Forwarded-For")
    assert "must not be X-Forwarded-For" in str(info.value)
    blank = build(jwt_secret_key=secrets.token_urlsafe(48), trusted_client_ip_header="  ")
    assert blank.trusted_client_ip_header is None


def test_database_errors_never_carry_statement_parameters():
    """Unexpected database errors are logged with their stack trace
    (app/core/errors.py); the engine hides bound parameters so personal data
    such as a patient's phone number can never reach the logs."""
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    from app.core.database import engine
    from app.core.errors import describe_db_error

    phone = "+250788999111"
    with engine.connect() as conn, pytest.raises(DBAPIError) as info:
        conn.execute(text("SELECT CAST(:value AS integer)"), {"value": phone})
    # SQLAlchemy's own text no longer lists the parameters...
    assert "[SQL parameters hidden due to hide_parameters=True]" in str(info.value)
    # ...but PostgreSQL's message can still quote the value, so the API logs a
    # description built only from safe fields.
    logged = describe_db_error(info.value)
    assert phone not in logged and "788999111" not in logged
    assert "22003" in logged and "NumericValueOutOfRange" in logged


def test_constraint_failures_are_logged_without_the_failing_row():
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    from app.core.database import engine
    from app.core.errors import describe_db_error

    with engine.connect() as conn, pytest.raises(DBAPIError) as info:
        conn.execute(text("CREATE TEMP TABLE t (phone text CHECK (phone LIKE '0%'))"))
        conn.execute(text("INSERT INTO t VALUES ('+250788777666')"))
    assert "+250788777666" in str(info.value)  # PostgreSQL's detail quotes the row...
    logged = describe_db_error(info.value)
    assert "+250788777666" not in logged and "constraint=t_phone_check" in logged  # ...the log does not
