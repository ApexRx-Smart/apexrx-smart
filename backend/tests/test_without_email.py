"""The deployed configuration while email delivery is disabled: no provider,
email verification not required. Registration and accounts keep working
securely; every email-dependent feature says it is unavailable instead of
pretending to send anything."""

import pytest
from sqlalchemy import text

from app.core.config import Settings, settings
from app.core.database import engine
from app.services.email.mock import mock_provider
from tests.helpers import admin, approve, login, user

PW = "No-Email-Pass-2026"


@pytest.fixture(autouse=True)
def no_email(monkeypatch):
    monkeypatch.setattr(settings, "email_provider", None)
    monkeypatch.setattr(settings, "email_verification_required", False)


def _count(table):
    with engine.connect() as c:
        return c.execute(text(f"SELECT count(*) FROM {table}")).scalar()


def test_defaults_need_no_email_provider():
    fields = Settings.model_fields
    assert fields["email_verification_required"].default is False
    assert fields["email_provider"].default is None
    for removed in ("gmail_client_id", "gmail_refresh_token", "resend_api_key", "brevo_api_key", "email_from_address"):
        assert removed not in fields


def test_capabilities_say_what_is_unavailable(client):
    assert client.get("/auth/capabilities").json() == {
        "email_delivery": False, "email_verification_required": False,
        "password_reset": False, "invitation_emails": False,
    }


@pytest.mark.parametrize("type_", ["pharmacy", "supplier"])
def test_registration_without_email_still_needs_approval(client, type_):
    h = user(client, f"{type_}@noemail.example.com")
    status = client.get("/auth/email/status", headers=h).json()
    assert status["required"] is False and status["verified"] is False and status["delivery_available"] is False
    r = client.post("/organizations", json={"name": f"No Email {type_}", "type": type_}, headers=h)
    assert r.status_code == 201 and r.json()["status"] == "pending" and r.json()["type"] == type_
    org = r.json()["organization_id"]
    if type_ == "pharmacy":
        # Approval-gated features stay closed until ApexRX approves.
        r = client.get("/supplier-offers", params={"pharmacy_organization_id": org, "q": "x"}, headers=h)
        assert r.status_code == 403
    assert client.get("/admin/organizations", headers=h).status_code == 403
    approve(client, admin(client), org)
    assert client.get(f"/organizations/{org}", headers=h).json()["status"] == "approved"


def test_verification_email_is_unavailable_not_faked(client):
    h = user(client, "verify@noemail.example.com")
    r = client.post("/auth/email/send", json={"next": "pharmacy"}, headers=h)
    assert r.status_code == 503 and "not available" in r.json()["detail"]
    assert _count("email_verification") == 0 and mock_provider.messages() == []
    assert client.get("/auth/me", headers=h).json()["email_verified"] is False


def test_forgot_password_is_unavailable_for_every_address(client):
    user(client, "known@noemail.example.com")
    known = client.post("/auth/password/forgot", json={"email": "known@noemail.example.com"})
    unknown = client.post("/auth/password/forgot", json={"email": "nobody@noemail.example.com"})
    assert known.status_code == unknown.status_code == 503
    assert known.json() == unknown.json() and known.json()["reason"] == "email_unavailable"
    assert _count("password_reset") == 0 and mock_provider.messages() == []


def test_invitation_link_is_shared_by_the_inviter(client):
    owner = user(client, "owner@noemail.example.com")
    org = client.post("/organizations", json={"name": "Link Pharmacy", "type": "pharmacy"}, headers=owner).json()["organization_id"]
    r = client.post(f"/organizations/{org}/invitations", json={"email": "new@noemail.example.com", "role": "staff"},
                    headers=owner)
    assert r.status_code == 201
    inv = r.json()
    assert inv["email_sent"] is False and inv["delivery"] == "link" and inv["sent_at"] is None
    assert inv["share_token"] and "no email was sent" in inv["detail"]
    assert mock_provider.messages() == []
    listed = client.get(f"/organizations/{org}/invitations", headers=owner).json()
    assert "share_token" not in listed[0] and listed[0]["delivery"] == "link"
    assert inv["share_token"] not in client.get(f"/organizations/{org}/invitations", headers=owner).text

    # The employee uses the link: own account, membership, but the address is not verified.
    r = client.post("/invitations/accept-new", json={"token": inv["share_token"], "name": "Neo", "password": PW})
    assert r.status_code == 201 and r.json()["role"] == "staff"
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    me = client.get("/auth/me", headers=h).json()
    assert me["email_verified"] is False and [m["role"] for m in me["memberships"]] == ["staff"]
    assert client.post("/auth/login", json={"email": "new@noemail.example.com", "password": PW}).status_code == 200
    # Single use, and staff still cannot invite.
    again = client.post("/invitations/accept-new", json={"token": inv["share_token"], "name": "X", "password": PW})
    assert again.json()["reason"] == "used"
    assert client.post(f"/organizations/{org}/invitations", json={"email": "z@noemail.example.com", "role": "staff"},
                       headers=h).status_code == 403


def test_new_link_replaces_the_old_one_and_existing_accounts_must_sign_in(client):
    owner = user(client, "owner2@noemail.example.com")
    org = client.post("/organizations", json={"name": "Link Two", "type": "pharmacy"}, headers=owner).json()["organization_id"]
    existing = user(client, "existing@noemail.example.com")
    inv = client.post(f"/organizations/{org}/invitations", json={"email": "existing@noemail.example.com", "role": "manager"},
                      headers=owner).json()
    renewed = client.post(f"/organizations/{org}/invitations/{inv['invitation_id']}/resend", headers=owner).json()
    assert renewed["share_token"] and renewed["share_token"] != inv["share_token"]
    assert client.post("/invitations/inspect", json={"token": inv["share_token"]}).json()["reason"] == "invalid"
    preview = client.post("/invitations/inspect", json={"token": renewed["share_token"]}).json()
    assert preview["account_exists"] is True
    # No second account for an existing address; the right account must sign in.
    r = client.post("/invitations/accept-new", json={"token": renewed["share_token"], "name": "D", "password": PW})
    assert r.status_code == 409
    other = user(client, "someone-else@noemail.example.com")
    assert client.post("/invitations/accept", json={"token": renewed["share_token"]}, headers=other).status_code == 403
    r = client.post("/invitations/accept", json={"token": renewed["share_token"]}, headers=existing)
    assert r.status_code == 200 and r.json()["role"] == "manager"
    assert client.get("/auth/me", headers=login(client, "existing@noemail.example.com")).json()["email_verified"] is False


def test_sessions_and_password_change_work_without_email(client):
    h = user(client, "pw@noemail.example.com")
    from tests.helpers import PASSWORD
    r = client.post("/auth/me/password", json={"current_password": PASSWORD, "new_password": "Changed-Pass-2026"},
                    headers=h)
    assert r.status_code == 200 and r.json()["detail"] == "Password updated."
    assert client.post("/auth/logout", headers=h).status_code == 204
    assert client.get("/auth/me", headers=h).status_code == 401
