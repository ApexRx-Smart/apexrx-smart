"""Forgot password and reset: same public answer for every address, single-use
links, expiry, replacement, limits, sessions signed out, memberships kept."""

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.core.database import engine
from app.services.email.mock import mock_provider
from tests.helpers import PASSWORD, login, organization, user

NEW = "Fresh-Password-2026"


def _forgot(client, email, **headers):
    return client.post("/auth/password/forgot", json={"email": email}, headers=headers)


def _link(client, email):
    r = client.get("/dev/email/latest-to", params={"to": email})
    assert r.status_code == 200, r.text
    return r.json()


def test_same_answer_whether_or_not_the_account_exists(client):
    user(client, "known@x.example.com")
    known, unknown = _forgot(client, "known@x.example.com"), _forgot(client, "nobody@x.example.com")
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    assert [m.message.to for m in mock_provider.messages()] == ["known@x.example.com"]


def test_reset_flow(client):
    owner = user(client, "reset@x.example.com", "Rita Reset")
    org = organization(client, owner, "pharmacy", "Reset Pharmacy")
    other_session = login(client, "reset@x.example.com")
    _forgot(client, "Reset@X.example.com")
    mail = _link(client, "reset@x.example.com")
    assert mail["subject"] == "Reset your ApexRX Smart password" and "Hello Rita Reset" in mail["text"]
    assert mail["link"].startswith("http://frontend.test/reset-password.html#token=")
    assert "correct-horse" not in mail["text"]  # never a password by email
    check = client.post("/auth/password/reset/check", json={"token": mail["token"]})
    assert check.status_code == 200 and check.json()["email_masked"] == "r***t@x.example.com"

    r = client.post("/auth/password/reset", json={"token": mail["token"], "new_password": NEW})
    assert r.status_code == 200
    assert client.post("/auth/login", json={"email": "reset@x.example.com", "password": PASSWORD}).status_code == 401
    fresh = client.post("/auth/login", json={"email": "reset@x.example.com", "password": NEW})
    assert fresh.status_code == 200
    # Every earlier session is signed out; memberships and roles are unchanged.
    assert client.get("/auth/me", headers=owner).status_code == 401
    assert client.get("/auth/me", headers=other_session).status_code == 401
    h = {"Authorization": f"Bearer {fresh.json()['access_token']}"}
    me = client.get("/auth/me", headers=h).json()
    assert [(m["organization_id"], m["role"]) for m in me["memberships"]] == [(org, "owner")]
    # Confirmation email, and the link is single use.
    assert mock_provider.latest("reset@x.example.com").message.subject == "Your ApexRX Smart password was changed"
    again = client.post("/auth/password/reset", json={"token": mail["token"], "new_password": "Another-Pass-99"})
    assert again.status_code == 400 and again.json()["reason"] == "used"


def test_expired_and_replaced_links(client):
    user(client, "exp@x.example.com")
    _forgot(client, "exp@x.example.com")
    first = _link(client, "exp@x.example.com")["token"]
    _forgot(client, "exp@x.example.com")
    second = _link(client, "exp@x.example.com")["token"]
    r = client.post("/auth/password/reset", json={"token": first, "new_password": NEW})
    assert r.status_code == 400 and r.json()["reason"] == "superseded"
    with engine.begin() as c:
        c.execute(text("UPDATE password_reset SET created_at = now() - interval '2 hours', "
                       "expires_at = now() - interval '1 hour'"))
    r = client.post("/auth/password/reset", json={"token": second, "new_password": NEW})
    assert r.status_code == 400 and r.json()["reason"] == "expired"
    assert client.post("/auth/login", json={"email": "exp@x.example.com", "password": PASSWORD}).status_code == 200


@pytest.mark.parametrize("token", ["short", "A" * 43])
def test_invalid_links(client, token):
    r = client.post("/auth/password/reset", json={"token": token, "new_password": NEW})
    assert r.status_code == 400 and r.json()["reason"] == "invalid"


def test_weak_new_password_is_refused(client):
    user(client, "weak@x.example.com")
    _forgot(client, "weak@x.example.com")
    token = _link(client, "weak@x.example.com")["token"]
    assert client.post("/auth/password/reset", json={"token": token, "new_password": "short"}).status_code == 422
    assert client.post("/auth/password/reset/check", json={"token": token}).status_code == 200


def test_limits_apply_to_every_address(client, monkeypatch):
    monkeypatch.setattr(settings, "password_reset_max_per_user_per_hour", 2)
    user(client, "limited@x.example.com")
    for email in ("limited@x.example.com", "ghost@x.example.com"):
        assert _forgot(client, email).status_code == 202
        assert _forgot(client, email).status_code == 202
        r = _forgot(client, email)
        assert r.status_code == 429 and r.json()["retry_after"] > 0  # registered or not: same 429
    assert len([m for m in mock_provider.messages() if m.message.to == "limited@x.example.com"]) == 2


def test_limit_per_ip(client, monkeypatch):
    monkeypatch.setattr(settings, "password_reset_max_per_ip_per_hour", 2)
    monkeypatch.setattr(settings, "trusted_client_ip_header", "X-Test-Client-IP")
    ip = {"X-Test-Client-IP": "203.0.113.20"}
    assert _forgot(client, "a@x.example.com", **ip).status_code == 202
    assert _forgot(client, "b@x.example.com", **ip).status_code == 202
    assert _forgot(client, "c@x.example.com", **ip).status_code == 429
    assert _forgot(client, "c@x.example.com", **{"X-Test-Client-IP": "203.0.113.21"}).status_code == 202


def test_failed_email_invalidates_the_link(client):
    user(client, "down@x.example.com")
    mock_provider.fail_with = "outage"
    assert _forgot(client, "down@x.example.com").status_code == 202  # same public answer
    with engine.connect() as c:
        row = c.execute(text("SELECT delivery_failed_at, invalidated_at FROM password_reset")).one()
    assert row.delivery_failed_at is not None and row.invalidated_at is not None


def test_deactivated_account_gets_no_email(client):
    user(client, "off@x.example.com")
    with engine.begin() as c:
        c.execute(text("UPDATE app_user SET is_active = false WHERE email = 'off@x.example.com'"))
    assert _forgot(client, "off@x.example.com").status_code == 202
    assert mock_provider.messages() == []
