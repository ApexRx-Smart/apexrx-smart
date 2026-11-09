"""Staff invitations: invite by email (no account needed), accept with a new or
an existing account, binding to the invited address, expiry, revocation,
reuse, permissions, and email failures that leave the invitation recoverable."""

import pytest
from sqlalchemy import text

from app.core.database import engine
from app.services.email.mock import mock_provider
from tests.helpers import PASSWORD, login, organization, register, user

NEW_PASSWORD = "Employee-Own-Pass-1"


@pytest.fixture
def team(client):
    owner = user(client, "owner@pharmacy.example.com", "Olive Owner")
    org = organization(client, owner, "pharmacy", "Invite Pharmacy")
    return client, owner, org


def _invite(client, headers, org, email, role="staff"):
    return client.post(f"/organizations/{org}/invitations", json={"email": email, "role": role}, headers=headers)


def _token(client, email):
    r = client.get("/dev/email/latest-to", params={"to": email})
    assert r.status_code == 200, r.text
    return r.json()


def _users(email):
    with engine.connect() as c:
        return c.execute(text("SELECT count(*) FROM app_user WHERE lower(email) = lower(:e)"), {"e": email}).scalar()


def _memberships(client, headers):
    return {(m["organization_name"], m["role"]) for m in client.get("/auth/me", headers=headers).json()["memberships"]}


def test_invite_someone_without_an_account(team):
    client, owner, org = team
    r = _invite(client, owner, org, "New.Person@Example.com")
    assert r.status_code == 201, r.text
    inv = r.json()
    assert inv["email"] == "new.person@example.com" and inv["status"] == "pending" and inv["delivery"] == "sent"
    assert inv["email_sent"] is True and inv["send_count"] == 1 and inv["invited_by_name"] == "Olive Owner"
    assert "token" not in r.text
    mail = _token(client, "new.person@example.com")
    assert mail["subject"] == "You're invited to join Invite Pharmacy on ApexRX Smart"
    assert "Olive Owner invited you to join Invite Pharmacy" in mail["text"] and "a staff member" in mail["text"]
    assert mail["link"].startswith("http://frontend.test/accept-invitation.html#token=")
    # No membership and no account until accepted.
    assert _users("new.person@example.com") == 0
    assert len(client.get(f"/organizations/{org}/members", headers=owner).json()) == 1

    preview = client.post("/invitations/inspect", json={"token": mail["token"]}).json()
    assert preview == {**preview, "organization_name": "Invite Pharmacy", "organization_type": "pharmacy",
                       "role": "staff", "email": "new.person@example.com", "account_exists": False}

    r = client.post("/invitations/accept-new", json={"token": mail["token"], "name": "Nia Person", "password": NEW_PASSWORD})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["organization_id"] == org and body["role"] == "staff" and body["access_token"]
    signed_in = {"Authorization": f"Bearer {body['access_token']}"}
    me = client.get("/auth/me", headers=signed_in).json()
    assert me["email"] == "new.person@example.com" and me["name"] == "Nia Person" and me["email_verified"] is True
    assert _memberships(client, signed_in) == {("Invite Pharmacy", "staff")}
    # The employee signs in on their own, with their own password.
    assert client.post("/auth/login", json={"email": "new.person@example.com", "password": NEW_PASSWORD}).status_code == 200
    listed = client.get(f"/organizations/{org}/invitations", headers=owner).json()[0]
    assert listed["status"] == "accepted" and listed["account_created"] is True and listed["accepted_at"]
    # Single use.
    again = client.post("/invitations/accept-new", json={"token": mail["token"], "name": "X", "password": NEW_PASSWORD})
    assert again.status_code == 400 and again.json()["reason"] == "used"


def test_invite_an_existing_account(team, client):
    _, owner, org = team
    other_owner = user(client, "boss@elsewhere.example.com")
    other_org = organization(client, other_owner, "pharmacy", "Other Pharmacy")
    staff = user(client, "veteran@example.com", "Vera Veteran")
    client.post(f"/organizations/{other_org}/members", json={"email": "veteran@example.com", "role": "manager"},
                headers=other_owner)
    assert _invite(client, owner, org, "veteran@example.com", "staff").status_code == 201
    token = _token(client, "veteran@example.com")["token"]
    assert client.post("/invitations/inspect", json={"token": token}).json()["account_exists"] is True
    # A new account cannot be created for an address that has one.
    r = client.post("/invitations/accept-new", json={"token": token, "name": "Dup", "password": NEW_PASSWORD})
    assert r.status_code == 409 and r.json()["reason"] == "account_exists"
    assert client.post("/invitations/accept", json={"token": token}).status_code == 401  # needs sign-in
    r = client.post("/invitations/accept", json={"token": token}, headers=staff)
    assert r.status_code == 200 and r.json()["organization_id"] == org and r.json()["role"] == "staff"
    assert _users("veteran@example.com") == 1
    assert _memberships(client, staff) == {("Invite Pharmacy", "staff"), ("Other Pharmacy", "manager")}


def test_invitation_cannot_be_accepted_by_another_address(team, client):
    _, owner, org = team
    _invite(client, owner, org, "intended@example.com")
    token = _token(client, "intended@example.com")["token"]
    intruder = user(client, "intruder@example.com")
    r = client.post("/invitations/accept", json={"token": token}, headers=intruder)
    assert r.status_code == 403 and r.json()["reason"] == "email_mismatch"
    assert "intended@example.com" not in r.json()["detail"]  # masked
    assert _memberships(client, intruder) == set()
    assert client.get(f"/organizations/{org}/invitations", headers=owner).json()[0]["status"] == "pending"


def test_expired_revoked_and_replaced_links(team, client):
    _, owner, org = team
    inv = _invite(client, owner, org, "late@example.com").json()
    token = _token(client, "late@example.com")["token"]
    with engine.begin() as c:
        c.execute(text("UPDATE organization_invitation SET created_at = now() - interval '4 days', "
                       "expires_at = now() - interval '1 day'"))
    r = client.post("/invitations/inspect", json={"token": token})
    assert r.status_code == 400 and r.json()["reason"] == "expired"
    assert client.get(f"/organizations/{org}/invitations", headers=owner).json()[0]["status"] == "expired"
    # Resending gives a new link and a new period; the old link stays dead.
    r = client.post(f"/organizations/{org}/invitations/{inv['invitation_id']}/resend", headers=owner)
    assert r.status_code == 200 and r.json()["status"] == "pending" and r.json()["send_count"] == 2
    new_token = _token(client, "late@example.com")["token"]
    assert new_token != token
    assert client.post("/invitations/inspect", json={"token": token}).json()["reason"] == "invalid"
    # Revoked: the new link no longer works either.
    r = client.post(f"/organizations/{org}/invitations/{inv['invitation_id']}/revoke", headers=owner)
    assert r.json()["status"] == "revoked"
    r = client.post("/invitations/accept-new", json={"token": new_token, "name": "L", "password": NEW_PASSWORD})
    assert r.status_code == 400 and r.json()["reason"] == "revoked"
    assert _users("late@example.com") == 0
    assert client.post(f"/organizations/{org}/invitations/{inv['invitation_id']}/resend",
                       headers=owner).status_code == 409


@pytest.mark.parametrize("token", ["", "short", "A" * 43])
def test_invalid_tokens(client, token):
    r = client.post("/invitations/inspect", json={"token": token})
    assert r.status_code == (422 if token == "" else 400)


def test_duplicates_and_existing_members(team, client):
    _, owner, org = team
    assert _invite(client, owner, org, "dup@example.com").status_code == 201
    r = _invite(client, owner, org, "DUP@example.com")
    assert r.status_code == 409 and r.json()["reason"] == "already_invited"
    r = _invite(client, owner, org, "owner@pharmacy.example.com")
    assert r.status_code == 409 and r.json()["reason"] == "already_member"


def test_resend_cooldown(team, client):
    _, owner, org = team
    inv = _invite(client, owner, org, "wait@example.com").json()
    r = client.post(f"/organizations/{org}/invitations/{inv['invitation_id']}/resend", headers=owner)
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0


def test_permissions(team, client):
    _, owner, org = team
    for email, role in (("mgr@example.com", "manager"), ("st@example.com", "staff")):
        user(client, email)
        client.post(f"/organizations/{org}/members", json={"email": email, "role": role}, headers=owner)
    manager, staff = login(client, "mgr@example.com"), login(client, "st@example.com")
    assert _invite(client, manager, org, "s2@example.com", "staff").status_code == 201
    assert _invite(client, manager, org, "m2@example.com", "manager").status_code == 403
    assert _invite(client, manager, org, "o2@example.com", "owner").status_code == 403
    assert _invite(client, staff, org, "s3@example.com", "staff").status_code == 403
    assert client.get(f"/organizations/{org}/invitations", headers=staff).status_code == 403
    outsider = user(client, "out@example.com")
    assert _invite(client, outsider, org, "s4@example.com").status_code == 404
    assert client.post("/organizations/1/invitations", json={"email": "x@example.com", "role": "staff"}).status_code == 401
    # Owners may invite managers.
    assert _invite(client, owner, org, "m3@example.com", "manager").status_code == 201
    inv = client.get(f"/organizations/{org}/invitations", headers=owner).json()
    manager_inv = next(i for i in inv if i["email"] == "m3@example.com")
    # A manager cannot revoke an owner's manager invitation.
    assert client.post(f"/organizations/{org}/invitations/{manager_inv['invitation_id']}/revoke",
                       headers=manager).status_code == 403


def test_email_failure_keeps_the_invitation_and_never_activates(team, client):
    _, owner, org = team
    mock_provider.fail_with = "mock outage"
    r = _invite(client, owner, org, "unlucky@example.com")
    assert r.status_code == 201
    body = r.json()
    assert body["email_sent"] is False and body["delivery"] == "failed" and "could not be sent" in body["detail"]
    assert body["status"] == "pending" and body["send_count"] == 0
    assert _users("unlucky@example.com") == 0 and len(client.get(f"/organizations/{org}/members", headers=owner).json()) == 1
    mock_provider.fail_with = None
    r = client.post(f"/organizations/{org}/invitations/{body['invitation_id']}/resend", headers=owner)
    assert r.json()["email_sent"] is True and r.json()["delivery"] == "sent"
    token = _token(client, "unlucky@example.com")["token"]
    assert client.post("/invitations/accept-new", json={"token": token, "name": "U", "password": NEW_PASSWORD}).status_code == 201


def test_deactivated_member_is_reactivated_with_the_invited_role(team, client):
    _, owner, org = team
    user(client, "back@example.com")
    m = client.post(f"/organizations/{org}/members", json={"email": "back@example.com", "role": "manager"},
                    headers=owner).json()
    client.patch(f"/organizations/{org}/members/{m['membership_id']}", json={"is_active": False}, headers=owner)
    _invite(client, owner, org, "back@example.com", "staff")
    token = _token(client, "back@example.com")["token"]
    h = login(client, "back@example.com")
    assert client.post("/invitations/accept", json={"token": token}, headers=h).json()["role"] == "staff"
    members = {x["email"]: (x["role"], x["is_active"]) for x in client.get(f"/organizations/{org}/members", headers=owner).json()}
    assert members["back@example.com"] == ("staff", True)


def test_new_account_password_rules(team, client):
    _, owner, org = team
    _invite(client, owner, org, "weak@example.com")
    token = _token(client, "weak@example.com")["token"]
    r = client.post("/invitations/accept-new", json={"token": token, "name": "W", "password": "short"})
    assert r.status_code == 422 and _users("weak@example.com") == 0
    register(client, "unrelated@example.com")
    assert client.post("/auth/login", json={"email": "unrelated@example.com", "password": PASSWORD}).status_code == 200
