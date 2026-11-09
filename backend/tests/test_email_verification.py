"""Email verification by emailed link (app/services/email_verification.py,
app/api/email_verification.py) and its use in organization registration.

Uses the in-memory mock provider (APP_ENV=test); never a real provider.
"""

import hashlib
import re
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import text

from app.core.config import settings
from app.core.database import engine
from app.services import email as email_service
from app.services.email import EmailDeliveryError, EmailMessage, EmailNotConfigured, get_email_provider
from app.services.email.http_providers import BrevoProvider, ResendProvider
from app.services.email.mock import mock_provider
from tests.helpers import user


def _send(client, headers, next_page="pharmacy"):
    return client.post("/auth/email/send", json={"next": next_page}, headers=headers)


def _latest(client, headers):
    r = client.get("/dev/email/latest", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _verify(client, token):
    return client.post("/auth/email/verify", json={"token": token})


def _status(client, headers):
    r = client.get("/auth/email/status", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _rows(email):
    with engine.connect() as c:
        return c.execute(
            text(
                "SELECT ev.* FROM email_verification ev JOIN app_user u USING (user_id) "
                "WHERE u.email = :e ORDER BY verification_id"
            ),
            {"e": email},
        ).mappings().all()


@pytest.fixture
def no_cooldown(monkeypatch):
    monkeypatch.setattr(settings, "email_verification_resend_cooldown_seconds", 0)


# ---------------------------------------------------------------------------
# The happy path
# ---------------------------------------------------------------------------
def test_status_starts_unverified(client):
    h = user(client, "new@x.example.com")
    s = _status(client, h)
    assert s["email"] == "new@x.example.com"
    assert s["verified"] is False and s["verified_at"] is None
    assert s["required"] is True and s["delivery_available"] is True
    assert s["pending"] is False and s["resend_after"] == 0
    assert client.get("/auth/me", headers=h).json()["email_verified"] is False


def test_send_and_verify(client):
    h = user(client, "amina@x.example.com", "Amina K")
    r = _send(client, h, "supplier")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {"email_masked": "a***a@x.example.com", "expires_in": 24 * 3600, "resend_after": 60}
    assert "token" not in r.text

    mail = _latest(client, h)
    assert mail["to"] == "amina@x.example.com"
    assert mail["subject"] == "Verify your email for ApexRX Smart"
    assert "Hello Amina K" in mail["text"] and "expires in 24 hours" in mail["text"]
    link = urlparse(mail["link"])
    assert f"{link.scheme}://{link.netloc}{link.path}" == "http://frontend.test/verify-email.html"
    assert parse_qs(link.query) == {"next": ["supplier"]}
    assert link.fragment == f"token={mail['token']}"

    s = _status(client, h)
    assert s["pending"] is True and s["expires_at"] and 0 < s["resend_after"] <= 60

    r = _verify(client, mail["token"])  # no session needed
    assert r.status_code == 200, r.text
    assert r.json() == {"verified": True, "already_verified": False, "email_masked": "a***a@x.example.com"}
    s = _status(client, h)
    assert s["verified"] is True and s["verified_at"] and s["pending"] is False
    assert client.get("/auth/me", headers=h).json()["email_verified"] is True


def test_only_a_hash_of_the_token_is_stored(client):
    h = user(client, "hash@x.example.com")
    _send(client, h)
    token = _latest(client, h)["token"]
    (row,) = _rows("hash@x.example.com")
    assert row["token_hash"] == hashlib.sha256(token.encode()).hexdigest()
    assert token not in str(dict(row))
    assert row["email"] == "hash@x.example.com"


def test_html_email_escapes_the_users_name(client):
    h = user(client, "xss@x.example.com", "<script>alert(1)</script>")
    _send(client, h)
    html = mock_provider.latest("xss@x.example.com").message.html
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_send_without_next_links_to_the_plain_page(client):
    h = user(client, "plain@x.example.com")
    assert client.post("/auth/email/send", json={}, headers=h).status_code == 200
    assert "/verify-email.html#token=" in _latest(client, h)["link"]
    assert client.post("/auth/email/send", json={"next": "admin"}, headers=h).status_code == 422


# ---------------------------------------------------------------------------
# Used, expired, superseded and invalid links
# ---------------------------------------------------------------------------
def test_reusing_a_link_after_verification_changes_nothing(client):
    h = user(client, "reuse@x.example.com")
    _send(client, h)
    token = _latest(client, h)["token"]
    assert _verify(client, token).status_code == 200
    first = _status(client, h)["verified_at"]
    r = _verify(client, token)
    assert r.status_code == 200 and r.json()["already_verified"] is True
    assert _status(client, h)["verified_at"] == first


def test_expired_link_is_rejected_and_a_new_one_works(client, no_cooldown):
    h = user(client, "late@x.example.com")
    _send(client, h)
    token = _latest(client, h)["token"]
    with engine.begin() as c:
        c.execute(text("UPDATE email_verification SET created_at = now() - interval '2 days', "
                       "expires_at = now() - interval '1 day'"))
    assert _status(client, h)["pending"] is False
    r = _verify(client, token)
    assert r.status_code == 400 and r.json()["reason"] == "expired"
    assert _rows("late@x.example.com")[0]["invalidated_at"] is not None
    assert _status(client, h)["verified"] is False

    assert _send(client, h).status_code == 200
    assert _verify(client, _latest(client, h)["token"]).status_code == 200


def test_resending_supersedes_the_earlier_link(client, no_cooldown):
    h = user(client, "twice@x.example.com")
    _send(client, h)
    old = _latest(client, h)["token"]
    _send(client, h)
    new = _latest(client, h)["token"]
    assert old != new
    r = _verify(client, old)
    assert r.status_code == 400 and r.json()["reason"] == "superseded"
    assert _verify(client, new).status_code == 200
    # Once verified, the old link reports that rather than an error.
    assert _verify(client, old).json()["already_verified"] is True
    rows = _rows("twice@x.example.com")
    assert [r["consumed_at"] is not None for r in rows] == [False, True]


@pytest.mark.parametrize("token", ["", "short", "x" * 43 + "!", "A" * 43])
def test_invalid_tokens(client, token):
    r = _verify(client, token)
    if token == "":
        assert r.status_code == 422
    else:
        assert r.status_code == 400 and r.json()["reason"] == "invalid"


def test_link_stops_working_if_the_account_email_changes(client):
    h = user(client, "old@x.example.com")
    _send(client, h)
    token = _latest(client, h)["token"]
    with engine.begin() as c:
        c.execute(text("UPDATE app_user SET email = 'changed@x.example.com' WHERE email = 'old@x.example.com'"))
    r = _verify(client, token)
    assert r.status_code == 400 and r.json()["reason"] == "invalid"


def test_link_for_a_deactivated_account_is_rejected(client):
    h = user(client, "gone@x.example.com")
    _send(client, h)
    token = _latest(client, h)["token"]
    with engine.begin() as c:
        c.execute(text("UPDATE app_user SET is_active = false WHERE email = 'gone@x.example.com'"))
    assert _verify(client, token).json()["reason"] == "invalid"


def test_one_users_link_never_verifies_another(client, no_cooldown):
    a = user(client, "a@x.example.com")
    b = user(client, "b@x.example.com")
    _send(client, a)
    _send(client, b)
    assert _verify(client, _latest(client, a)["token"]).status_code == 200
    assert _status(client, a)["verified"] is True
    assert _status(client, b)["verified"] is False


# ---------------------------------------------------------------------------
# Sending rules
# ---------------------------------------------------------------------------
def test_send_requires_a_session(client):
    assert client.post("/auth/email/send", json={}).status_code == 401
    assert client.get("/auth/email/status").status_code == 401


def test_resend_cooldown(client):
    h = user(client, "wait@x.example.com")
    assert _send(client, h).status_code == 200
    r = _send(client, h)
    assert r.status_code == 429
    assert 0 < int(r.headers["Retry-After"]) <= 60 and r.json()["retry_after"] == int(r.headers["Retry-After"])
    assert len(mock_provider.messages()) == 1


def test_hourly_limit_per_user(client, no_cooldown, monkeypatch):
    monkeypatch.setattr(settings, "email_verification_max_sends_per_user_per_hour", 3)
    h = user(client, "many@x.example.com")
    for _ in range(3):
        assert _send(client, h).status_code == 200
    r = _send(client, h)
    assert r.status_code == 429 and "Too many verification emails" in r.json()["detail"]
    assert len(_rows("many@x.example.com")) == 3


def test_hourly_limit_per_ip(client, no_cooldown, monkeypatch):
    monkeypatch.setattr(settings, "email_verification_max_sends_per_ip_per_hour", 2)
    monkeypatch.setattr(settings, "trusted_client_ip_header", "X-Test-Client-IP")
    ip = {"X-Test-Client-IP": "203.0.113.9"}
    for i in range(2):
        h = user(client, f"ip{i}@x.example.com")
        assert client.post("/auth/email/send", json={}, headers={**h, **ip}).status_code == 200
    h = user(client, "ip2@x.example.com")
    assert client.post("/auth/email/send", json={}, headers={**h, **ip}).status_code == 429
    other = {"X-Test-Client-IP": "203.0.113.10"}
    assert client.post("/auth/email/send", json={}, headers={**h, **other}).status_code == 200


def test_already_verified_cannot_send_again(client):
    h = user(client, "done@x.example.com")
    _send(client, h)
    _verify(client, _latest(client, h)["token"])
    r = _send(client, h)
    assert r.status_code == 409 and r.json()["reason"] == "already_verified"


def test_provider_failure_records_nothing_usable_and_allows_a_retry(client):
    h = user(client, "fail@x.example.com")
    mock_provider.fail_with = "mock outage"
    r = _send(client, h)
    assert r.status_code == 502 and "could not send" in r.json()["detail"]
    (row,) = _rows("fail@x.example.com")
    assert row["delivery_failed_at"] is not None and row["invalidated_at"] is not None
    assert _status(client, h)["pending"] is False

    mock_provider.fail_with = None
    assert _send(client, h).status_code == 200  # no cooldown after a failed delivery
    assert _verify(client, _latest(client, h)["token"]).status_code == 200


def test_unconfigured_email_answers_503(client, monkeypatch):
    monkeypatch.setattr(settings, "email_provider", None)
    h = user(client, "nomail@x.example.com")
    assert _status(client, h)["delivery_available"] is False
    r = _send(client, h)
    assert r.status_code == 503 and "not available" in r.json()["detail"]
    assert _rows("nomail@x.example.com") == []


def test_mock_provider_is_refused_in_production(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "email_provider", "mock")
    monkeypatch.setattr(settings, "frontend_base_url", "https://apexrx.example.com")
    with pytest.raises(EmailNotConfigured, match="mock"):
        get_email_provider()


def test_production_requires_an_https_frontend(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "email_provider", "resend")
    monkeypatch.setattr(settings, "resend_api_key", SecretStr("re_test"))
    monkeypatch.setattr(settings, "email_from_address", "no-reply@apexrx.example.com")
    monkeypatch.setattr(settings, "frontend_base_url", "http://apexrx.example.com")
    with pytest.raises(EmailNotConfigured, match="https"):
        get_email_provider()
    monkeypatch.setattr(settings, "frontend_base_url", "https://apexrx.example.com")
    assert isinstance(get_email_provider(), ResendProvider)


@pytest.mark.parametrize(
    ("name", "missing"),
    [("resend", "RESEND_API_KEY"), ("brevo", "BREVO_API_KEY"), ("postmark", "Unknown")],
)
def test_incomplete_provider_settings_are_not_configured(monkeypatch, name, missing):
    monkeypatch.setattr(settings, "email_provider", name)
    monkeypatch.setattr(settings, "resend_api_key", None)
    monkeypatch.setattr(settings, "brevo_api_key", None)
    assert missing in (email_service.email_configuration_problem() or "")


def test_provider_needs_a_sender_address(monkeypatch):
    monkeypatch.setattr(settings, "email_provider", "brevo")
    monkeypatch.setattr(settings, "brevo_api_key", SecretStr("xkeysib-test"))
    monkeypatch.setattr(settings, "email_from_address", None)
    assert "EMAIL_FROM_ADDRESS" in email_service.email_configuration_problem()


# ---------------------------------------------------------------------------
# HTTP adapters (no network: httpx.post is replaced)
# ---------------------------------------------------------------------------
MESSAGE = EmailMessage(to="owner@x.example.com", subject="S", text="T", html="<p>H</p>")


class _Recorder:
    def __init__(self, status=200, payload=None, raises=None):
        self.status, self.payload, self.raises, self.calls = status, payload or {}, raises, []

    def __call__(self, url, headers=None, json=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        if self.raises:
            raise self.raises
        return httpx.Response(self.status, json=self.payload, request=httpx.Request("POST", url))


def test_resend_request(monkeypatch):
    rec = _Recorder(payload={"id": "re-123"})
    monkeypatch.setattr(httpx, "post", rec)
    result = ResendProvider("re_secret", "ApexRX Smart", "no-reply@apexrx.example.com").send(MESSAGE)
    assert result.message_id == "re-123"
    (call,) = rec.calls
    assert call["url"] == "https://api.resend.com/emails"
    assert call["headers"] == {"Authorization": "Bearer re_secret"}
    assert call["json"] == {"from": "ApexRX Smart <no-reply@apexrx.example.com>", "to": ["owner@x.example.com"],
                            "subject": "S", "text": "T", "html": "<p>H</p>"}


def test_brevo_request(monkeypatch):
    rec = _Recorder(status=201, payload={"messageId": "<b-1@brevo>"})
    monkeypatch.setattr(httpx, "post", rec)
    result = BrevoProvider("xkeysib-secret", "ApexRX Smart", "no-reply@apexrx.example.com").send(MESSAGE)
    assert result.message_id == "<b-1@brevo>"
    (call,) = rec.calls
    assert call["url"] == "https://api.brevo.com/v3/smtp/email"
    assert call["headers"]["api-key"] == "xkeysib-secret"
    assert call["json"]["sender"] == {"name": "ApexRX Smart", "email": "no-reply@apexrx.example.com"}
    assert call["json"]["to"] == [{"email": "owner@x.example.com"}]


@pytest.mark.parametrize("rec", [_Recorder(status=403, payload={"message": "bad key re_secret"}),
                                 _Recorder(raises=httpx.ConnectTimeout("timed out"))])
def test_provider_errors_raise_without_leaking_the_key(monkeypatch, rec):
    monkeypatch.setattr(httpx, "post", rec)
    with pytest.raises(EmailDeliveryError) as info:
        ResendProvider("re_secret", "ApexRX Smart", "no-reply@apexrx.example.com").send(MESSAGE)
    assert "re_secret" not in str(info.value)
    assert re.match(r"^resend: ", str(info.value))


# ---------------------------------------------------------------------------
# Registration requires a verified email
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("type_", ["pharmacy", "supplier"])
def test_organization_registration_requires_a_verified_email(client, type_):
    h = user(client, f"{type_}@x.example.com")
    r = client.post("/organizations", json={"name": "Unverified Co", "type": type_}, headers=h)
    assert r.status_code == 403 and r.json()["reason"] == "email_unverified"
    assert client.get("/organizations", headers=h).json() == []

    _send(client, h, type_)
    assert _verify(client, _latest(client, h)["token"]).status_code == 200
    r = client.post("/organizations", json={"name": "Verified Co", "type": type_}, headers=h)
    assert r.status_code == 201, r.text
    assert r.json()["type"] == type_ and r.json()["status"] == "pending" and r.json()["my_role"] == "owner"


def test_verification_can_be_switched_off(client, monkeypatch):
    monkeypatch.setattr(settings, "email_verification_required", False)
    h = user(client, "off@x.example.com")
    assert _status(client, h)["required"] is False
    r = client.post("/organizations", json={"name": "No Check Co", "type": "pharmacy"}, headers=h)
    assert r.status_code == 201, r.text


def test_no_phone_verification_is_involved(client):
    """Phone numbers are contact details: no SMS endpoints, no phone requirement."""
    h = user(client, "nophone@x.example.com")
    for path in ("/auth/phone/status", "/auth/phone/send-code", "/auth/phone/verify", "/dev/sms/latest"):
        assert client.request("GET" if path.endswith(("status", "latest")) else "POST", path, headers=h,
                              json={}).status_code in (404, 405)
    _send(client, h)
    _verify(client, _latest(client, h)["token"])
    r = client.post("/organizations", json={"name": "Any Phone Pharmacy", "type": "pharmacy",
                                            "phone": "0788 123 456"}, headers=h)
    assert r.status_code == 201, r.text
    assert r.json()["phone"] == "+250788123456"  # normalized contact number, nobody proved ownership
