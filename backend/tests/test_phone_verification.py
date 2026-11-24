"""Phone verification by SMS one-time code: ApexRX generates, stores (HMAC
only), limits and checks every code; the SMS provider only delivers it.

These tests use the in-memory mock provider (tests/conftest.py). They prove the
ApexRX side of the lifecycle; they do not prove that an SMS reaches a phone.
"""

import os
import re
import subprocess
import sys
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.core.config import settings
from app.core.database import engine
from app.scripts import create_admin
from app.services import otp
from app.services.sms.mock import mock_provider as sms
from tests.helpers import PASSWORD, admin, approve, login, organization

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def required(monkeypatch):
    """Mandatory verification, as on a server with live SMS."""
    monkeypatch.setattr(settings, "phone_verification_required", True)
    return settings


def signup(client, email, phone="0788 123 456", name="Pat Patient"):
    body = {"name": name, "email": email, "password": PASSWORD, "account_type": "patient"}
    if phone is not None:
        body["phone"] = phone
    r = client.post("/auth/register", json=body)
    assert r.status_code == 201, r.text
    return login(client, email)


def send(client, headers, **kw):
    return client.post("/auth/phone/send", headers=headers, **kw)


def sent_code(phone="+250788123456"):
    item = sms.latest(phone)
    assert item is not None
    return re.search(r"\b(\d{6})\b", item.message).group(1)


def verify(client, headers, challenge_id, code):
    return client.post("/auth/phone/verify", json={"challenge_id": challenge_id, "code": code}, headers=headers)


def me(client, headers):
    return client.get("/auth/me", headers=headers).json()


def rows(sql, **params):
    with engine.connect() as conn:
        return conn.execute(text(sql), params).mappings().all()


def wrong(code):
    return f"{(int(code) + 1) % 1_000_000:06d}"


def no_cooldown(monkeypatch):
    monkeypatch.setattr(settings, "otp_resend_cooldown_seconds", 0)


# ---------------------------------------------------------------------------
# Registration and the backend gate
# ---------------------------------------------------------------------------
def test_new_account_is_locked_until_its_number_is_verified(client, required):
    h = signup(client, "pat@example.com")
    data = me(client, h)
    assert data["phone"] == "+250788123456" and data["phone_verification_pending"] is True
    assert data["phone_verified"] is False and data["phone_verification_required"] is True
    # Every protected endpoint refuses the account, whatever the browser does.
    for method, path in [("get", "/reservations"), ("post", "/organizations"), ("get", "/notifications"),
                         ("get", "/organizations"), ("post", "/auth/email/send")]:
        r = getattr(client, method)(path, headers=h, **({"json": {}} if method == "post" else {}))
        assert r.status_code == 403 and r.json()["code"] == "phone_verification_required", (path, r.text)

    r = send(client, h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["phone_masked"].endswith("456") and "+250788123456" not in body["phone_masked"]
    assert set(body) == {"challenge_id", "phone_masked", "expires_at", "resend_available_at", "sandbox"}
    r = verify(client, h, body["challenge_id"], sent_code())
    assert r.status_code == 200 and r.json()["verified"] is True

    data = me(client, h)
    assert data["phone_verification_pending"] is False and data["phone_verified"] is True
    assert data["verified_phone"] == "+250788123456" and data["phone_verified_at"]
    assert client.get("/reservations", headers=h).status_code == 200


def test_sign_up_needs_a_valid_mobile_number_when_required(client, required):
    base = {"name": "N", "email": "n@example.com", "password": PASSWORD, "account_type": "patient"}
    r = client.post("/auth/register", json=base)
    assert r.status_code == 422 and r.json()["code"] == "phone_required"
    for bad in ("0252 123 456", "12345678", "abcdefghij"):
        assert client.post("/auth/register", json={"account_type": "patient", **base, "phone": bad}).status_code == 422, bad
    assert rows("SELECT count(*) AS n FROM app_user")[0]["n"] == 0


def test_client_cannot_mark_itself_verified(client, required):
    """Fields the browser might send to skip verification are ignored."""
    forged = {"name": "F", "email": "f@example.com", "password": PASSWORD, "phone": "0788123456", "account_type": "patient",
              "verified_phone": "+250788123456", "phone_verified_at": "2026-01-01T00:00:00Z",
              "phone_verification_required": False, "phone_verified": True}
    assert client.post("/auth/register", json=forged).status_code == 201
    h = login(client, "f@example.com")
    client.patch("/auth/me", json={"verified_phone": "+250788123456", "phone_verification_required": False,
                                   "phone_verified": True}, headers=h)
    assert me(client, h)["phone_verification_pending"] is True
    assert client.get("/reservations", headers=h).status_code == 403
    row = rows("SELECT verified_phone, phone_verified_at FROM app_user WHERE email = 'f@example.com'")[0]
    assert row["verified_phone"] is None and row["phone_verified_at"] is None


def test_staff_invited_with_a_new_account_verify_at_first_sign_in(client, required):
    owner = admin_owner(client)
    org = organization(client, owner, "pharmacy", "Gate Pharmacy")
    # An approved pharmacy (approved by an admin made before verification was required):
    # only the phone gate is tested here.
    previous = settings.phone_verification_required
    settings.phone_verification_required = False
    try:
        reviewer = admin(client)
    finally:
        settings.phone_verification_required = previous
    approve(client, reviewer, org)
    r = client.post(f"/organizations/{org}/invitations", json={"email": "staff@example.com", "role": "staff"},
                    headers=owner)
    assert r.status_code == 201, r.text
    token = client.get("/dev/email/latest-to", params={"to": "staff@example.com"}).json()["token"]
    r = client.post("/invitations/accept-new", json={"token": token, "name": "Sam Staff", "password": PASSWORD})
    assert r.status_code == 201, r.text
    staff = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert me(client, staff)["phone_verification_pending"] is True
    assert client.get(f"/organizations/{org}/inventory", headers=staff).status_code == 403
    # No number yet: they add one, then verify it.
    assert send(client, staff).json()["code"] == "phone_missing"
    assert client.patch("/auth/me", json={"phone": "0788 555 111"}, headers=staff).status_code == 200
    challenge = send(client, staff).json()["challenge_id"]
    assert verify(client, staff, challenge, sent_code("+250788555111")).status_code == 200
    assert client.get(f"/organizations/{org}/inventory", headers=staff).status_code == 200


def admin_owner(client):
    """An organization owner made before verification became required."""
    previous = settings.phone_verification_required
    settings.phone_verification_required = False
    try:
        h = signup(client, "owner@example.com", name="Olive Owner")
    finally:
        settings.phone_verification_required = previous
    return h


def test_existing_accounts_are_not_locked(client, monkeypatch):
    h = signup(client, "old@example.com", phone=None)  # created while not required
    monkeypatch.setattr(settings, "phone_verification_required", True)
    data = me(client, h)
    assert data["phone_verification_pending"] is False and data["phone_verified"] is False
    assert client.get("/reservations", headers=h).status_code == 200
    assert client.post("/auth/login", json={"account_type": "patient", "email": "old@example.com", "password": PASSWORD}).status_code == 200
    # Nothing was marked verified for them.
    assert rows("SELECT verified_phone FROM app_user WHERE email = 'old@example.com'")[0]["verified_phone"] is None
    # When they set (or change) their number, the new number must be verified.
    assert client.patch("/auth/me", json={"phone": "0788 777 000"}, headers=h).status_code == 200
    assert me(client, h)["phone_verification_pending"] is True
    assert client.get("/reservations", headers=h).status_code == 403
    challenge = send(client, h).json()["challenge_id"]
    assert verify(client, h, challenge, sent_code("+250788777000")).status_code == 200
    assert client.get("/reservations", headers=h).status_code == 200


def test_admins_created_by_the_script_are_exempt(client, required):
    answers = iter(["yes"])
    passwords = iter(["Str0ng-admin-password", "Str0ng-admin-password"])
    rc = create_admin.main(["--email", "boot@example.com", "--name", "Boot Admin"],
                           input_fn=lambda *_: next(answers), getpass_fn=lambda *_: next(passwords))
    assert rc == 0
    r = client.post("/auth/login", json={"account_type": "admin", "email": "boot@example.com", "password": "Str0ng-admin-password"})
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert me(client, h)["phone_verification_pending"] is False
    assert client.get("/admin/users", headers=h).status_code == 200


def test_verification_is_optional_while_not_required(client):
    h = signup(client, "opt@example.com")
    assert me(client, h)["phone_verification_pending"] is False
    assert client.get("/reservations", headers=h).status_code == 200
    challenge = send(client, h).json()["challenge_id"]
    assert verify(client, h, challenge, sent_code()).status_code == 200
    assert me(client, h)["phone_verified"] is True
    assert send(client, h).json()["code"] == "already_verified"


# ---------------------------------------------------------------------------
# OTP correctness
# ---------------------------------------------------------------------------
def test_wrong_codes_count_down_and_lock_the_challenge(client, required):
    h = signup(client, "w@example.com")
    challenge = send(client, h).json()["challenge_id"]
    code = sent_code()
    for left in (4, 3, 2, 1):
        r = verify(client, h, challenge, wrong(code))
        assert r.status_code == 400 and r.json()["code"] == "incorrect_code" and r.json()["attempts_left"] == left
    r = verify(client, h, challenge, wrong(code))
    assert r.json()["code"] == "too_many_attempts"
    # Even the right code no longer works on that challenge.
    assert verify(client, h, challenge, code).json()["code"] == "too_many_attempts"
    assert me(client, h)["phone_verification_pending"] is True


def test_expired_codes_are_refused(client, required):
    h = signup(client, "e@example.com")
    challenge = send(client, h).json()["challenge_id"]
    with engine.begin() as conn:
        conn.execute(text("UPDATE phone_verification SET created_at = created_at - interval '10 minutes', "
                          "expires_at = now() - interval '1 second'"))
    r = verify(client, h, challenge, sent_code())
    assert r.status_code == 400 and r.json()["code"] == "code_expired"
    assert verify(client, h, challenge, sent_code()).json()["code"] == "code_expired"
    assert me(client, h)["phone_verified"] is False


def test_codes_are_single_use(client):
    h = signup(client, "u@example.com")
    challenge = send(client, h).json()["challenge_id"]
    code = sent_code()
    assert verify(client, h, challenge, code).status_code == 200
    r = verify(client, h, challenge, code)
    assert r.status_code == 400 and r.json()["code"] == "code_used"
    assert rows("SELECT consumed_at FROM phone_verification")[0]["consumed_at"] is not None


def test_a_new_code_supersedes_the_previous_one(client, required, monkeypatch):
    no_cooldown(monkeypatch)
    h = signup(client, "s@example.com")
    first = send(client, h).json()["challenge_id"]
    first_code = sent_code()
    second = send(client, h).json()["challenge_id"]
    assert second != first
    r = verify(client, h, first, first_code)
    assert r.status_code == 400 and r.json()["code"] == "code_superseded"
    assert verify(client, h, second, sent_code()).status_code == 200
    assert rows("SELECT count(*) AS n FROM phone_verification WHERE consumed_at IS NULL AND invalidated_at IS NULL")[0]["n"] == 0


def test_resend_cooldown(client, required):
    h = signup(client, "c@example.com")
    assert send(client, h).status_code == 200
    r = send(client, h)
    assert r.status_code == 429 and r.json()["code"] == "resend_cooldown"
    assert 1 <= int(r.headers["Retry-After"]) <= 60
    assert len(sms.messages()) == 1
    status = client.get("/auth/phone", headers=h).json()
    assert status["challenge_id"] and status["resend_available_at"] and status["pending"] is True
    # A corrected number can get a code at once; the per-account hourly limit still applies.
    assert client.patch("/auth/me", json={"phone": "0788 123 457"}, headers=h).status_code == 200
    assert send(client, h).status_code == 200


def test_a_changed_number_invalidates_earlier_codes(client, required):
    h = signup(client, "p@example.com")
    challenge = send(client, h).json()["challenge_id"]
    code = sent_code()
    assert client.patch("/auth/me", json={"phone": "0788 999 000"}, headers=h).status_code == 200
    assert verify(client, h, challenge, code).json()["code"] == "code_superseded"
    assert me(client, h)["phone_verified"] is False


# ---------------------------------------------------------------------------
# Storage, responses and logs
# ---------------------------------------------------------------------------
def test_codes_are_stored_only_as_keyed_hmacs(client, required, app_logs):
    caplog = app_logs
    h = signup(client, "h@example.com")
    r = send(client, h)
    code = sent_code()
    row = rows("SELECT * FROM phone_verification")[0]
    assert code not in str(dict(row))
    assert re.fullmatch(r"[0-9a-f]{64}", row["code_hash"])
    assert row["code_hash"] == otp.hash_code(code, challenge_ref=row["challenge_ref"], user_id=row["user_id"],
                                             phone="+250788123456")
    # Keyed: without the server secret the stored value cannot be recomputed.
    import hashlib
    for candidate in (code, f"{row['challenge_ref']}|phone_verification|{row['user_id']}|+250788123456|{code}"):
        assert hashlib.sha256(candidate.encode()).hexdigest() != row["code_hash"]
    secret = settings.otp_hmac_secret.get_secret_value()
    status = client.get("/auth/phone", headers=h)
    done = verify(client, h, r.json()["challenge_id"], code)
    for response in (r, status, done):
        assert code not in response.text and row["code_hash"] not in response.text and secret not in response.text
    assert "Verification code sent via mock" in caplog.text and "Phone verified for user" in caplog.text
    assert code not in caplog.text and secret not in caplog.text and row["code_hash"] not in caplog.text


# ---------------------------------------------------------------------------
# Abuse prevention
# ---------------------------------------------------------------------------
def test_brute_force_across_several_codes_is_stopped(client, required, monkeypatch):
    no_cooldown(monkeypatch)
    monkeypatch.setattr(settings, "otp_max_failed_attempts_per_user_per_hour", 7)
    h = signup(client, "b@example.com")
    first = send(client, h).json()["challenge_id"]
    for _ in range(5):
        verify(client, h, first, wrong(sent_code()))
    second = send(client, h).json()["challenge_id"]
    for _ in range(2):
        assert verify(client, h, second, wrong(sent_code())).json()["code"] == "incorrect_code"
    r = verify(client, h, second, sent_code())  # even the right code: the hour's budget is spent
    assert r.status_code == 429 and r.json()["code"] == "too_many_failed_codes"
    assert send(client, h).status_code == 429
    assert me(client, h)["phone_verified"] is False


def test_per_phone_limit_holds_across_accounts_without_revealing_them(client, required, monkeypatch):
    no_cooldown(monkeypatch)
    monkeypatch.setattr(settings, "otp_max_sends_per_phone_per_hour", 2)
    a = signup(client, "a1@example.com", phone="0788 100 200")
    b = signup(client, "a2@example.com", phone="0788 100 200")
    c = signup(client, "a3@example.com", phone="0788 300 400")
    assert send(client, a).status_code == 200 and send(client, b).status_code == 200
    blocked = send(client, b)
    assert blocked.status_code == 429 and blocked.json()["code"] == "rate_limited"
    # The same answer whatever account holds the number; other numbers are unaffected.
    other = send(client, a)
    assert other.status_code == 429 and other.json()["detail"] == blocked.json()["detail"]
    assert send(client, c).status_code == 200
    # Rolling window: an hour later the number works again (no permanent lock).
    with engine.begin() as conn:
        conn.execute(text("UPDATE phone_verification SET created_at = created_at - interval '61 minutes', "
                          "expires_at = expires_at - interval '61 minutes'"))
    assert send(client, b).status_code == 200


def test_per_account_limit(client, required, monkeypatch):
    no_cooldown(monkeypatch)
    monkeypatch.setattr(settings, "otp_max_sends_per_user_per_hour", 2)
    h = signup(client, "acct@example.com")
    assert send(client, h).status_code == 200 and send(client, h).status_code == 200
    assert send(client, h).status_code == 429


def test_per_ip_limit_uses_only_a_trusted_client_ip(client, required, monkeypatch):
    no_cooldown(monkeypatch)
    monkeypatch.setattr(settings, "trusted_client_ip_header", "X-Test-Client-IP")
    monkeypatch.setattr(settings, "otp_max_sends_per_ip_per_hour", 2)
    users = [signup(client, f"ip{i}@example.com", phone=f"0788 40{i} 000") for i in range(4)]
    ip1 = {"X-Test-Client-IP": "198.51.100.7"}
    assert send(client, {**users[0], **ip1}).status_code == 200
    assert send(client, {**users[1], **ip1}).status_code == 200
    assert send(client, {**users[2], **ip1}).status_code == 429
    assert send(client, {**users[3], "X-Test-Client-IP": "203.0.113.9"}).status_code == 200
    # Only an HMAC of the IP is stored.
    assert all("198.51.100.7" not in (r["client_ip_hash"] or "") for r in rows("SELECT client_ip_hash FROM phone_verification"))


def test_platform_wide_hourly_ceiling(client, required, monkeypatch):
    monkeypatch.setattr(settings, "otp_max_sends_global_per_hour", 2)
    hs = [signup(client, f"g{i}@example.com", phone=f"0788 50{i} 000") for i in range(3)]
    assert send(client, hs[0]).status_code == 200 and send(client, hs[1]).status_code == 200
    r = send(client, hs[2])
    assert r.status_code == 429 and r.json()["code"] == "rate_limited"


def test_another_users_challenge_cannot_be_used(client, required):
    a = signup(client, "va@example.com", phone="0788 600 001")
    b = signup(client, "vb@example.com", phone="0788 600 002")
    challenge = send(client, a).json()["challenge_id"]
    code = sent_code("+250788600001")
    r = verify(client, b, challenge, code)
    assert r.status_code == 400 and r.json()["code"] == "invalid_challenge"
    assert me(client, b)["phone_verified"] is False
    assert verify(client, a, challenge, code).status_code == 200  # untouched for its owner
    # Verifying needs a session; a user can only send to their own number.
    assert client.post("/auth/phone/verify", json={"challenge_id": challenge, "code": code}).status_code == 401
    assert client.post("/auth/phone/send").status_code == 401
    assert client.post("/auth/phone/send", json={"phone": "+250788600002"}, headers=a).json()["code"] == "already_verified"


# ---------------------------------------------------------------------------
# Failures
# ---------------------------------------------------------------------------
def test_provider_outage_never_verifies_and_allows_a_retry(client, required):
    h = signup(client, "out@example.com")
    sms.fail_with = "provider_unavailable"
    r = send(client, h)
    assert r.status_code == 503 and r.json()["code"] == "sms_send_failed"
    row = rows("SELECT * FROM phone_verification")[0]
    assert row["delivery_failed_at"] and row["invalidated_at"] and row["delivery_status"] == "provider_unavailable"
    assert me(client, h)["phone_verification_pending"] is True
    sms.fail_with = None
    r = send(client, h)  # no cooldown after a failed delivery
    assert r.status_code == 200
    assert verify(client, h, r.json()["challenge_id"], sent_code()).status_code == 200


def test_number_refused_by_the_provider(client, required):
    h = signup(client, "rej@example.com")
    sms.reject_number = True
    r = send(client, h)
    assert r.status_code == 422 and r.json()["code"] == "sms_number_rejected"
    assert me(client, h)["phone_verified"] is False


def test_sms_not_configured(client, required, monkeypatch):
    h = signup(client, "nc@example.com")
    monkeypatch.setattr(settings, "sms_provider", None)
    r = send(client, h)
    assert r.status_code == 503 and r.json()["code"] == "sms_unavailable"
    assert rows("SELECT count(*) AS n FROM phone_verification")[0]["n"] == 0
    assert client.get("/auth/phone", headers=h).json()["sms_available"] is False
    monkeypatch.setattr(settings, "sms_provider", "mock")
    monkeypatch.setattr(settings, "otp_hmac_secret", None)
    assert send(client, h).json()["code"] == "sms_unavailable"


def test_database_failure_during_verification_verifies_nothing(client, required, monkeypatch):
    h = signup(client, "db@example.com")
    challenge = send(client, h).json()["challenge_id"]

    def broken(*args, **kwargs):
        raise OperationalError("SELECT 1", {}, Exception("connection lost"))
    monkeypatch.setattr(otp, "_verify", broken)
    r = verify(client, h, challenge, sent_code())
    assert r.status_code == 503 and r.json()["code"] == "verification_unavailable"
    assert me(client, h)["phone_verified"] is False


def test_database_failure_before_sending_sends_nothing(client, required, monkeypatch):
    h = signup(client, "db2@example.com")

    def broken(*args, **kwargs):
        raise OperationalError("SELECT 1", {}, Exception("connection lost"))
    monkeypatch.setattr(otp, "_record", broken)
    r = send(client, h)
    assert r.status_code == 503 and r.json()["code"] == "sms_unavailable"
    assert sms.messages() == []


# ---------------------------------------------------------------------------
# Delivery reports (signed webhook)
# ---------------------------------------------------------------------------
def test_delivery_report_webhook_is_signed_and_never_verifies(client, required, monkeypatch):
    import hashlib
    import hmac
    import json

    from pydantic import SecretStr

    h = signup(client, "dlr@example.com")
    send(client, h)
    message_id = rows("SELECT provider_message_id FROM phone_verification")[0]["provider_message_id"]
    with engine.begin() as conn:
        conn.execute(text("UPDATE phone_verification SET provider = 'esms'"))
    body = json.dumps({"event": "message.delivered", "message_id": message_id, "status": "delivered"}).encode()
    assert client.post("/webhooks/esms/delivery", content=body).status_code == 404  # no secret configured
    monkeypatch.setattr(settings, "esms_webhook_secret", SecretStr("whsec-test-signing-secret"))
    assert client.post("/webhooks/esms/delivery", content=body,
                       headers={"X-Webhook-Signature": "sha256=" + "0" * 64}).status_code == 401
    signature = "sha256=" + hmac.new(b"whsec-test-signing-secret", body, hashlib.sha256).hexdigest()
    r = client.post("/webhooks/esms/delivery", content=body, headers={"X-Webhook-Signature": signature})
    assert r.status_code == 204
    assert rows("SELECT delivery_status FROM phone_verification")[0]["delivery_status"] == "delivered"
    assert me(client, h)["phone_verified"] is False


# ---------------------------------------------------------------------------
# Startup safety
# ---------------------------------------------------------------------------
def test_production_refuses_required_verification_with_the_sandbox():
    env = {**os.environ, "APP_ENV": "production", "PHONE_VERIFICATION_REQUIRED": "true", "SMS_PROVIDER": "esms",
           "ESMS_MODE": "sandbox", "ESMS_API_KEY": "esms_test_not_a_real_key", "EMAIL_PROVIDER": "",
           "EMAIL_VERIFICATION_REQUIRED": "false", "CORS_ORIGINS": "https://example.netlify.app"}
    r = subprocess.run([sys.executable, "-c", "import app.main"], cwd=BACKEND_DIR, env=env,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode != 0
    assert "needs live SMS in production" in r.stderr
    assert "esms_test_not_a_real_key" not in r.stderr + r.stdout


def test_status_endpoint_reports_without_secrets(client, required):
    h = signup(client, "st@example.com")
    s = client.get("/auth/phone", headers=h).json()
    assert s == {**s, "phone": "+250788123456", "verified": False, "pending": True, "required": True,
                 "sms_available": True, "sandbox": False, "challenge_id": None}
    assert timedelta(seconds=settings.otp_ttl_seconds) == timedelta(minutes=5)


def test_sandbox_mode_never_blocks_or_prompts_registration(client, monkeypatch):
    """While testing with the eSMS sandbox (codes never reach a phone) and
    verification not required, sign-up and the whole app work without any SMS,
    and nobody is offered a verification they cannot complete."""
    from pydantic import SecretStr

    monkeypatch.setattr(settings, "sms_provider", "esms")
    monkeypatch.setattr(settings, "esms_mode", "sandbox")
    monkeypatch.setattr(settings, "esms_api_key", SecretStr("esms_test_unit_test_key_0123456789"))
    h = signup(client, "sandbox@example.com")
    data = me(client, h)
    assert data["phone_verification_pending"] is False and data["phone_verification_available"] is False
    assert client.get("/reservations", headers=h).status_code == 200
    org = organization(client, h, "pharmacy", "Sandbox Pharmacy")
    assert client.get(f"/organizations/{org}", headers=h).status_code == 200
    status = client.get("/auth/phone", headers=h).json()
    assert status["sandbox"] is True and status["sms_available"] is True and status["pending"] is False
