"""Regression tests for the PR #24 review: fail-closed limits, atomic limit
consumption, serialized issuance, persistence ordering, and schema safety."""

import os
import subprocess
import sys
import threading
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.core import schema
from app.core.config import settings
from app.core.database import engine
from app.main import app
from app.services import otp
from app.services.sms import PROVIDERS, SmsResult
from app.services.sms.mock import mock_provider
from tests.helpers import PASSWORD, user

BACKEND_DIR = Path(__file__).resolve().parents[1]
PHONE = "+250788123456"


def send(client, h, phone="0788123456"):
    return client.post("/auth/phone/send-code", json={"phone": phone}, headers=h)


def count(sql, **params):
    with engine.connect() as c:
        return c.execute(text(sql), params).scalar()


def active_codes():
    return count(
        "SELECT count(*) FROM phone_verification WHERE consumed_at IS NULL AND invalidated_at IS NULL"
    )


def run_concurrently(n, fn):
    """Start ``n`` calls at the same moment (barrier), each with its own client."""
    barrier = threading.Barrier(n)
    results, errors = [None] * n, []

    def worker(i):
        try:
            with TestClient(app, client=("81.2.69.200", 40000 + i)) as c:
                barrier.wait()
                results[i] = fn(c, i)
        except Exception as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors
    return results


@pytest.fixture
def h(client):
    return user(client, "owner@x.example.com")


class RealishAdapter:
    """Stands in for a real provider (allowed in production)."""

    name = "realish"

    def __init__(self):
        self.sent = []

    def send(self, to, message):
        self.sent.append(to)
        return SmsResult(provider=self.name)


@pytest.fixture
def production_with_real_provider(monkeypatch):
    adapter = RealishAdapter()
    monkeypatch.setitem(PROVIDERS, "realish", lambda: adapter)
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "sms_provider", "realish")
    return adapter


# ---------------------------------------------------------------------------
# B. Fail closed
# ---------------------------------------------------------------------------
def _boom(*args, **kwargs):
    raise OperationalError("SELECT ...", {}, Exception("connection reset by the rate-limit store"))


@pytest.mark.parametrize("target", ["_check_limits", "_lock_issuance", "_check_cooldown"])
def test_limit_storage_failure_sends_nothing_in_production(
    client, h, production_with_real_provider, monkeypatch, target
):
    monkeypatch.setattr(otp, target, _boom)
    r = send(client, h)
    assert r.status_code == 503
    assert r.json() == {"detail": otp.UNAVAILABLE}  # nothing internal leaks
    assert "OperationalError" not in r.text and "connection reset" not in r.text
    assert production_with_real_provider.sent == []
    assert count("SELECT count(*) FROM phone_verification") == 0


def test_limit_storage_failure_also_fails_closed_in_development(client, h, monkeypatch):
    monkeypatch.setattr(otp, "_check_limits", _boom)
    assert send(client, h).status_code == 503
    assert mock_provider.messages() == []


def test_commit_failure_before_sending_sends_nothing(client, h, production_with_real_provider, monkeypatch):
    """The code is persisted (committed) before the SMS is sent, so a failed
    write can never leave a delivered-but-unsaved code."""
    real_commit = Session.commit
    calls = {"n": 0}

    def failing_commit(self):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OperationalError("COMMIT", {}, Exception("disk full"))
        return real_commit(self)

    monkeypatch.setattr(Session, "commit", failing_commit)
    r = send(client, h)
    assert r.status_code == 503 and r.json()["detail"] == otp.UNAVAILABLE
    assert production_with_real_provider.sent == []
    assert count("SELECT count(*) FROM phone_verification") == 0


def test_failure_to_record_a_failed_delivery_is_contained(client, h, monkeypatch):
    mock_provider.fail_with = "down"

    real_execute = Session.execute

    def execute(self, statement, *args, **kwargs):
        sql = str(statement)
        if sql.startswith("UPDATE phone_verification SET") and "delivery_failed_at=" in sql:
            raise OperationalError("UPDATE", {}, Exception("db down"))
        return real_execute(self, statement, *args, **kwargs)

    monkeypatch.setattr(Session, "execute", execute)
    r = send(client, h)
    assert r.status_code == 502  # the user still gets the delivery error
    # The undelivered code stays stored but unknown to anyone; it expires.
    assert count("SELECT count(*) FROM phone_verification WHERE delivery_failed_at IS NULL") == 1


# ---------------------------------------------------------------------------
# C. Atomic limit consumption under concurrency
# ---------------------------------------------------------------------------
def test_per_phone_limit_holds_under_concurrency(client, monkeypatch):
    monkeypatch.setattr(settings, "otp_resend_cooldown_seconds", 0)
    monkeypatch.setattr(settings, "otp_max_sends_per_phone_per_hour", 3)
    monkeypatch.setattr(settings, "otp_max_sends_per_ip_per_hour", 1000)
    tokens = [user(client, f"u{i}@x.example.com") for i in range(8)]
    codes = run_concurrently(8, lambda c, i: send(c, tokens[i]).status_code)
    assert sorted(codes) == [200] * 3 + [429] * 5
    assert count("SELECT count(*) FROM phone_verification") == 3
    assert len(mock_provider.messages()) == 3


def test_per_user_limit_holds_under_concurrency(client, h, monkeypatch):
    monkeypatch.setattr(settings, "otp_resend_cooldown_seconds", 0)
    monkeypatch.setattr(settings, "otp_max_sends_per_user_per_hour", 3)
    monkeypatch.setattr(settings, "otp_max_sends_per_ip_per_hour", 1000)
    codes = run_concurrently(7, lambda c, i: send(c, h, f"078810000{i}").status_code)
    assert sorted(codes) == [200] * 3 + [429] * 4
    assert count("SELECT count(*) FROM phone_verification") == 3


def test_per_ip_limit_holds_under_concurrency(client, monkeypatch):
    monkeypatch.setattr(settings, "otp_resend_cooldown_seconds", 0)
    monkeypatch.setattr(settings, "otp_max_sends_per_ip_per_hour", 2)
    tokens = [user(client, f"ip{i}@x.example.com") for i in range(6)]
    codes = run_concurrently(6, lambda c, i: send(c, tokens[i], f"078820000{i}").status_code)
    assert sorted(codes) == [200] * 2 + [429] * 4
    # The IP is stored only as an HMAC.
    assert count("SELECT count(DISTINCT client_ip_hash) FROM phone_verification") == 1
    assert count("SELECT count(*) FROM phone_verification WHERE client_ip_hash LIKE '81.%'") == 0


def test_limits_survive_a_restart_of_the_process(client, h, monkeypatch):
    """Counts come from PostgreSQL, not process memory."""
    monkeypatch.setattr(settings, "otp_resend_cooldown_seconds", 0)
    monkeypatch.setattr(settings, "otp_max_sends_per_user_per_hour", 2)
    send(client, h, "0788100001")
    send(client, h, "0788100002")
    mock_provider.reset()  # in-memory state gone
    assert send(client, h, "0788100003").status_code == 429


# ---------------------------------------------------------------------------
# D. Serialized issuance and single use
# ---------------------------------------------------------------------------
def test_concurrent_issuance_with_cooldown_sends_once(client, h):
    codes = run_concurrently(6, lambda c, i: send(c, h).status_code)
    assert sorted(codes) == [200] + [429] * 5
    assert count("SELECT count(*) FROM phone_verification") == 1
    assert active_codes() == 1 and len(mock_provider.messages()) == 1


def test_concurrent_issuance_without_cooldown_leaves_one_valid_code(client, h, monkeypatch):
    monkeypatch.setattr(settings, "otp_resend_cooldown_seconds", 0)
    for limit in ("phone", "user", "ip"):  # this test is about serialization, not limits
        monkeypatch.setattr(settings, f"otp_max_sends_per_{limit}_per_hour", 100)
    codes = run_concurrently(6, lambda c, i: send(c, h).status_code)
    assert codes == [200] * 6  # serialized, not failed
    assert count("SELECT count(*) FROM phone_verification") == 6
    assert active_codes() == 1


def test_database_refuses_two_valid_codes(client, h):
    send(client, h)
    with pytest.raises(IntegrityError), engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO phone_verification (user_id, phone_e164, purpose, code_hash, expires_at, max_attempts) "
                "SELECT user_id, phone_e164, purpose, repeat('0', 64), now() + interval '5 minutes', 5 "
                "FROM phone_verification LIMIT 1"
            )
        )


def test_concurrent_verification_succeeds_once(client, h):
    send(client, h)
    code = mock_provider.latest(PHONE).message.split("code is ")[1][:6]
    body = {"phone": "0788123456", "code": code}
    results = run_concurrently(5, lambda c, i: c.post("/auth/phone/verify", json=body, headers=h).status_code)
    assert sorted(results) == [200] + [400] * 4
    assert count("SELECT count(*) FROM phone_verification WHERE consumed_at IS NOT NULL") == 1


def test_issue_and_verify_racing_never_errors(client, h, monkeypatch):
    monkeypatch.setattr(settings, "otp_resend_cooldown_seconds", 0)
    send(client, h)
    code = mock_provider.latest(PHONE).message.split("code is ")[1][:6]

    def act(c, i):
        if i % 2:
            return send(c, h).status_code
        return c.post("/auth/phone/verify", json={"phone": "0788123456", "code": code}, headers=h).status_code

    results = run_concurrently(6, act)
    assert all(r in (200, 400) for r in results), results  # no deadlock / 5xx
    assert active_codes() <= 1


# ---------------------------------------------------------------------------
# A. Schema version check
# ---------------------------------------------------------------------------
def test_health_reports_schema_up_to_date(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["schema"] == "up to date"


def test_health_fails_when_schema_is_behind(client, monkeypatch):
    monkeypatch.setattr(schema, "expected_revision", lambda: "ffffffffffff")
    r = client.get("/health")
    assert r.status_code == 503
    assert r.json()["schema"] == "outdated" and "alembic upgrade head" in r.json()["detail"]


def test_old_schema_breaks_sign_in_until_migrated():
    """Finding A, reproduced: new code on the previous schema breaks sign-in
    even with PHONE_VERIFICATION_REQUIRED=false; /health says so; after
    `alembic upgrade head` everything works and existing rows are kept."""
    url = make_url(os.environ["DATABASE_URL"])
    name = "apexrx_oldschema_test"
    admin_dsn = url.set(drivername="postgresql", database="postgres").render_as_string(hide_password=False)
    try:
        with psycopg.connect(admin_dsn, autocommit=True) as c:
            c.execute(f"DROP DATABASE IF EXISTS {name}")
            c.execute(f"CREATE DATABASE {name}")
    except psycopg.Error as exc:
        pytest.skip(f"cannot create a scratch database here: {type(exc).__name__}")
    old_url = url.set(database=name).render_as_string(hide_password=False)
    env = {**os.environ, "DATABASE_URL": old_url, "PHONE_VERIFICATION_REQUIRED": "false"}
    env.pop("RENDER", None)

    def alembic(*args):
        out = subprocess.run(
            [sys.executable, "-m", "alembic", *args], cwd=BACKEND_DIR, env=env, capture_output=True, text=True
        )
        assert out.returncode == 0, out.stderr

    probe = (
        "import logging; logging.disable(logging.CRITICAL)\n"
        "from fastapi.testclient import TestClient\n"
        "from app.main import app\n"
        "c = TestClient(app, raise_server_exceptions=False)\n"
        "print(c.get('/health').status_code)\n"
        f"print(c.post('/auth/login', json={{'email': 'old@example.com', 'password': '{PASSWORD}'}}).status_code)\n"
    )

    def run_probe():
        out = subprocess.run(
            [sys.executable, "-c", probe], cwd=BACKEND_DIR, env=env, capture_output=True, text=True
        )
        assert out.returncode == 0, out.stderr
        return out.stdout.split()

    try:
        alembic("upgrade", "a6f0c2d9e1b4")  # the schema currently deployed
        with psycopg.connect(
            url.set(drivername="postgresql", database=name).render_as_string(hide_password=False),
            autocommit=True,
        ) as c:
            from app.core.security import hash_password

            c.execute(
                "INSERT INTO app_user (name, email, password_hash) VALUES ('Old', 'old@example.com', %s)",
                (hash_password(PASSWORD),),
            )
        assert run_probe() == ["503", "503"]  # health flags it; sign-in is broken
        alembic("upgrade", "head")
        assert run_probe() == ["200", "200"]  # migrated: works, the old account kept
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as c:
            c.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
