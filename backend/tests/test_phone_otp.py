"""SMS one-time codes: issue, verify, expiry, reuse, attempts, cooldown,
sending limits, delivery failures, configuration, and the dev endpoint."""

import logging
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import settings
from app.core.database import engine
from app.main import app
from app.services import otp
from app.services.otp import generate_code, hash_code, send_limiter
from app.services.sms import set_sms_provider
from app.services.sms.mock import mock_provider
from tests.helpers import user

PHONE = "+250788123456"
LOCAL = "0788 123 456"
BACKEND_DIR = Path(__file__).resolve().parents[1]


def send(client, h, phone=LOCAL):
    return client.post("/auth/phone/send-code", json={"phone": phone}, headers=h)


def verify(client, h, code, phone=LOCAL):
    return client.post("/auth/phone/verify", json={"phone": phone, "code": code}, headers=h)


def sent_code(phone=PHONE):
    return re.search(r"\b(\d{6})\b", mock_provider.latest(phone).message).group(1)


def rows(email=None):
    sql = "SELECT v.* FROM phone_verification v JOIN app_user u USING (user_id)"
    params = {}
    if email:
        sql += " WHERE u.email = :e"
        params["e"] = email
    with engine.connect() as c:
        return c.execute(text(sql + " ORDER BY verification_id"), params).mappings().all()


def verified_phone(email):
    with engine.connect() as c:
        return c.execute(text("SELECT verified_phone FROM app_user WHERE email = :e"), {"e": email}).scalar()


def no_cooldown(monkeypatch):
    monkeypatch.setattr(settings, "otp_resend_cooldown_seconds", 0)


@pytest.fixture
def h(client):
    return user(client, "owner@x.example.com")


# ---------------------------------------------------------------------------
# Generation and storage
# ---------------------------------------------------------------------------
def test_generated_codes_are_six_random_digits():
    codes = {generate_code() for _ in range(2000)}
    assert all(re.fullmatch(r"\d{6}", c) for c in codes)
    assert len(codes) > 1900  # random, not a fixed or sequential value
    assert "472916" not in codes or len(codes) > 1900


def test_send_code_normalizes_and_never_returns_the_code(client, h):
    r = send(client, h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {"phone": PHONE, "phone_masked": "+2507*****456", "expires_in": 300, "resend_after": 60}
    assert sent_code() not in r.text
    assert "Your ApexRX verification code is" in mock_provider.latest(PHONE).message


def test_only_a_hash_is_stored(client, h):
    send(client, h)
    [row] = rows()
    code = sent_code()
    assert code not in str(dict(row))
    assert re.fullmatch(r"[0-9a-f]{64}", row["code_hash"])
    assert row["code_hash"] == hash_code(
        code, user_id=row["user_id"], phone=PHONE, purpose=otp.PURPOSE_PHARMACY_REGISTRATION
    )
    assert row["phone_e164"] == PHONE and row["attempts"] == 0 and row["max_attempts"] == 5
    assert (row["expires_at"] - row["created_at"]).total_seconds() == 300


def test_hash_is_bound_to_user_phone_and_purpose():
    base = hash_code("123456", user_id=1, phone=PHONE, purpose="a")
    assert base != hash_code("123456", user_id=2, phone=PHONE, purpose="a")
    assert base != hash_code("123456", user_id=1, phone="+250788123457", purpose="a")
    assert base != hash_code("123456", user_id=1, phone=PHONE, purpose="b")


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------
def test_successful_verification(client, h):
    send(client, h)
    r = verify(client, h, sent_code())
    assert r.status_code == 200 and r.json() == {"verified": True, "verified_phone": PHONE}
    assert verified_phone("owner@x.example.com") == PHONE
    status = client.get("/auth/phone/status", headers=h).json()
    assert status == {"required": True, "verified": True, "verified_phone": PHONE, "sms_available": True}
    me = client.get("/auth/me", headers=h).json()
    assert me["verified_phone"] == PHONE and me["phone_verified_at"]


def test_code_with_spaces_is_accepted(client, h):
    send(client, h)
    code = sent_code()
    assert verify(client, h, f"{code[:3]} {code[3:]}").status_code == 200


@pytest.mark.parametrize("bad", ["12345", "1234567", "abcdef", "12345a", "+12345"])
def test_badly_formatted_codes_are_rejected(client, h, bad):
    send(client, h)
    r = verify(client, h, bad)
    assert r.status_code == 400 and r.json()["reason"] == "format"
    assert rows()[0]["attempts"] == 0  # not counted as a guess


def test_incorrect_code(client, h):
    send(client, h)
    wrong = "000000" if sent_code() != "000000" else "111111"
    r = verify(client, h, wrong)
    assert r.status_code == 400
    assert r.json() == {
        "detail": "Incorrect code. 4 attempts left.",
        "reason": "incorrect",
        "attempts_left": 4,
    }
    assert verified_phone("owner@x.example.com") is None


def test_code_cannot_be_reused(client, h):
    send(client, h)
    code = sent_code()
    assert verify(client, h, code).status_code == 200
    r = verify(client, h, code)
    assert r.status_code == 400 and r.json()["reason"] == "no_active_code"


def test_expired_code_is_rejected(client, h):
    send(client, h)
    code = sent_code()
    with engine.begin() as c:
        c.execute(
            text(
                "UPDATE phone_verification SET expires_at = now() - interval '1 second', "
                "created_at = now() - interval '6 minutes'"
            )
        )
    r = verify(client, h, code)
    assert r.status_code == 400 and r.json() == {
        "detail": "This code has expired. Request a new code.",
        "reason": "expired",
    }
    # Expired codes stay dead.
    assert verify(client, h, code).json()["reason"] == "no_active_code"


def test_maximum_attempts(client, h, monkeypatch):
    monkeypatch.setattr(settings, "otp_max_attempts", 3)
    send(client, h)
    code = sent_code()
    wrong = "000000" if code != "000000" else "111111"
    assert verify(client, h, wrong).json()["attempts_left"] == 2
    assert verify(client, h, wrong).json()["attempts_left"] == 1
    r = verify(client, h, wrong)
    assert r.status_code == 400 and r.json()["reason"] == "too_many_attempts"
    # Even the right code no longer works.
    assert verify(client, h, code).json()["reason"] == "no_active_code"
    assert verified_phone("owner@x.example.com") is None


def test_code_for_one_number_does_not_verify_another(client, h):
    send(client, h, "0788123456")
    code = sent_code("+250788123456")
    r = verify(client, h, code, phone="0788654321")
    assert r.status_code == 400 and r.json()["reason"] == "no_active_code"
    assert verified_phone("owner@x.example.com") is None


def test_code_is_bound_to_the_user(client, h):
    other = user(client, "other@x.example.com")
    send(client, h)
    code = sent_code()
    r = verify(client, other, code)
    assert r.status_code == 400 and r.json()["reason"] == "no_active_code"
    assert verified_phone("other@x.example.com") is None


# ---------------------------------------------------------------------------
# Resending
# ---------------------------------------------------------------------------
def test_resend_cooldown(client, h):
    assert send(client, h).status_code == 200
    r = send(client, h)
    assert r.status_code == 429
    assert 1 <= int(r.headers["retry-after"]) <= 60 and r.json()["retry_after"] == int(
        r.headers["retry-after"]
    )
    assert "Please wait" in r.json()["detail"]
    assert len(mock_provider.messages()) == 1


def test_resend_invalidates_the_previous_code(client, h, monkeypatch):
    no_cooldown(monkeypatch)
    send(client, h)
    first = sent_code()
    send(client, h)
    second = sent_code()
    assert [r["invalidated_at"] is not None for r in rows()] == [True, False]
    if first != second:
        assert verify(client, h, first).json()["reason"] == "incorrect"
    assert verify(client, h, second).status_code == 200


def test_new_number_invalidates_code_for_old_number(client, h, monkeypatch):
    no_cooldown(monkeypatch)
    send(client, h, "0788123456")
    old = sent_code("+250788123456")
    send(client, h, "0788654321")
    assert verify(client, h, old, phone="0788123456").json()["reason"] == "no_active_code"


# ---------------------------------------------------------------------------
# Sending limits
# ---------------------------------------------------------------------------
@pytest.fixture
def small_send_limits(monkeypatch):
    no_cooldown(monkeypatch)
    monkeypatch.setattr(settings, "otp_max_sends_per_phone_per_hour", 2)
    monkeypatch.setattr(settings, "otp_max_sends_per_user_per_hour", 3)
    monkeypatch.setattr(settings, "otp_max_sends_per_ip_per_hour", 4)
    send_limiter.configure()
    yield
    monkeypatch.undo()
    send_limiter.configure()


def test_per_phone_limit_across_users(client, small_send_limits):
    a, b = user(client, "a@x.example.com"), user(client, "b@x.example.com")
    assert send(client, a).status_code == 200
    assert send(client, b).status_code == 200
    r = send(client, user(client, "c@x.example.com"))
    assert r.status_code == 429 and "Too many codes requested" in r.json()["detail"]


def test_per_user_limit_across_numbers(client, h, small_send_limits):
    for phone in ("0788100001", "0788100002", "0788100003"):
        assert send(client, h, phone).status_code == 200
    assert send(client, h, "0788100004").status_code == 429


def test_per_ip_limit_when_ip_is_trustworthy(small_send_limits):
    with TestClient(app, client=("81.2.69.40", 5000)) as c:
        for i in range(4):
            hh = user(c, f"ip{i}@x.example.com")
            assert send(c, hh, f"078820000{i}").status_code == 200
        assert send(c, user(c, "ip9@x.example.com"), "0788200009").status_code == 429
    with TestClient(app, client=("41.186.0.9", 5000)) as other:
        assert send(other, user(other, "elsewhere@x.example.com"), "0788300001").status_code == 200


def test_rejected_requests_send_nothing(client, h, small_send_limits):
    for phone in ("0788100001", "0788100002", "0788100003", "0788100004"):
        send(client, h, phone)
    assert len(mock_provider.messages()) == 3


# ---------------------------------------------------------------------------
# Validation, delivery failure and configuration
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("bad", ["0788 abc 456", "12345", "+12025550123", "0252123456", ""])
def test_invalid_phone_numbers(client, h, bad):
    r = send(client, h, bad)
    assert r.status_code == 422 and isinstance(r.json()["detail"], str)
    assert mock_provider.messages() == [] and rows() == []


def test_provider_failure_is_reported_and_stores_nothing(client, h, monkeypatch):
    no_cooldown(monkeypatch)
    send(client, h)
    good = sent_code()
    mock_provider.fail_with = "provider rejected"
    r = send(client, h)
    assert r.status_code == 502 and "could not send the SMS" in r.json()["detail"]
    assert len(rows()) == 1 and rows()[0]["invalidated_at"] is None
    # The earlier, delivered code still works.
    assert verify(client, h, good).status_code == 200


def test_sms_not_configured_fails_safely(client, h, monkeypatch):
    monkeypatch.setattr(settings, "sms_provider", None)
    r = send(client, h)
    assert r.status_code == 503 and "not available" in r.json()["detail"]
    assert client.get("/auth/phone/status", headers=h).json()["sms_available"] is False
    assert rows() == []


def test_production_refuses_the_mock_provider(client, h, monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "sms_provider", "mock")
    r = send(client, h)
    assert r.status_code == 503
    assert mock_provider.messages() == []


def test_endpoints_require_sign_in(client):
    assert client.post("/auth/phone/send-code", json={"phone": LOCAL}).status_code == 401
    assert client.post("/auth/phone/verify", json={"phone": LOCAL, "code": "123456"}).status_code == 401
    assert client.get("/auth/phone/status").status_code == 401
    assert client.get("/dev/sms/latest").status_code == 401


def test_codes_never_appear_in_logs(client, h, caplog, monkeypatch):
    no_cooldown(monkeypatch)
    # Alembic's logging config (run by the test session) disables loggers that
    # already exist; the application itself never does that.
    for name in ("apexrx.otp", "apexrx.sms"):
        monkeypatch.setattr(logging.getLogger(name), "disabled", False)
    caplog.set_level(logging.DEBUG)
    send(client, h)
    code = sent_code()
    verify(client, h, "000000" if code != "000000" else "111111")
    verify(client, h, code)
    mock_provider.fail_with = "x"
    send(client, h)
    assert code not in caplog.text
    assert PHONE not in caplog.text and "+2507*****456" in caplog.text


# ---------------------------------------------------------------------------
# Development-only code retrieval
# ---------------------------------------------------------------------------
def test_dev_endpoint_returns_own_latest_code(client, h):
    send(client, h)
    r = client.get("/dev/sms/latest", headers=h)
    assert r.status_code == 200 and r.json()["code"] == sent_code() and r.json()["to"] == PHONE
    other = user(client, "other@x.example.com")
    assert client.get("/dev/sms/latest", headers=other).status_code == 404


def test_dev_endpoint_refuses_in_production(client, h, monkeypatch):
    send(client, h)
    monkeypatch.setattr(settings, "app_env", "production")
    assert client.get("/dev/sms/latest", headers=h).status_code == 404


def test_dev_endpoint_needs_the_mock_provider(client, h):
    send(client, h)

    class Real:
        name = "real"

        def send(self, to, message):
            raise AssertionError

    set_sms_provider(Real())
    assert client.get("/dev/sms/latest", headers=h).status_code == 404


def _import_app(env):
    full = {**os.environ, **env}
    return subprocess.run(
        [sys.executable, "-c", "import app.main"], cwd=BACKEND_DIR, env=full, capture_output=True, text=True
    )


def test_production_does_not_mount_dev_routes():
    script = "; ".join(
        [
            "import app.main as m",
            "from fastapi.testclient import TestClient",
            "print('/dev/sms/latest' in m.app.openapi()['paths'])",
            "print(TestClient(m.app).get('/dev/sms/latest').status_code)",
        ]
    )
    env = {**os.environ, "APP_ENV": "production", "SMS_PROVIDER": ""}
    env.pop("RENDER", None)
    out = subprocess.run(
        [sys.executable, "-c", script], cwd=BACKEND_DIR, env=env, capture_output=True, text=True
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.split() == ["False", "404"]


def test_render_refuses_to_start_outside_production():
    out = _import_app({"RENDER": "true", "APP_ENV": "development"})
    assert out.returncode != 0 and "must run with APP_ENV=production" in out.stderr
    ok = _import_app({"RENDER": "true", "APP_ENV": "production", "SMS_PROVIDER": ""})
    assert ok.returncode == 0, ok.stderr


def test_concurrent_verification_uses_the_code_once(client, h):
    """Two simultaneous requests with the same correct code: the row lock
    (SELECT ... FOR UPDATE) lets exactly one succeed."""
    import threading

    send(client, h)
    code = sent_code()
    barrier = threading.Barrier(2)
    results = []

    def attempt():
        with TestClient(app) as c:
            barrier.wait()
            results.append(verify(c, h, code).status_code)

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [200, 400]
    with engine.connect() as c:
        assert (
            c.execute(text("SELECT count(*) FROM phone_verification WHERE consumed_at IS NOT NULL")).scalar()
            == 1
        )
