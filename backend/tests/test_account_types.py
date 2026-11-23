"""Account types: each account is a patient, a pharmacy or a supplier account,
and is accepted only by its own sign-in, registration and invitation routes.

A refused sign-in never creates a session: the check runs after the password
and before any session row or token exists."""

import pytest
from sqlalchemy import text

from app.core.database import engine
from tests.helpers import PASSWORD, admin, approve, login, mark_email_verified, register

TYPES = ("patient", "pharmacy", "supplier")


def _sessions() -> int:
    with engine.connect() as c:
        return c.execute(text("SELECT count(*) FROM auth_session")).scalar()


def _sign_in(client, email, page):
    return client.post("/auth/login", json={"email": email, "password": PASSWORD, "account_type": page})


@pytest.fixture
def accounts(client):
    for t in TYPES:
        register(client, f"{t}@types.example.com", t.title(), account_type=t)
    return client


@pytest.mark.parametrize("page", TYPES)
@pytest.mark.parametrize("account", TYPES)
def test_each_sign_in_page_accepts_only_its_own_account_type(accounts, account, page):
    client = accounts
    before = _sessions()
    r = _sign_in(client, f"{account}@types.example.com", page)
    if account == page:
        assert r.status_code == 200 and r.json()["access_token"]
        assert _sessions() == before + 1
        me = client.get("/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}).json()
        assert me["account_type"] == account
    else:
        assert r.status_code == 403, r.text
        body = r.json()
        assert body["code"] == "wrong_account_type"
        assert "access_token" not in body and "device_token" not in body
        # Says which page this is, never what the account is.
        assert account not in body["detail"].replace(page, "").replace("pharmacies", "")
        assert _sessions() == before  # no session was ever created


def test_wrong_password_on_another_page_is_the_usual_generic_error(accounts):
    r = accounts.post("/auth/login", json={"email": "patient@types.example.com", "password": "not-it-123",
                                           "account_type": "pharmacy"})
    assert r.status_code == 401 and r.json()["detail"] == "Invalid email or password."


def test_the_page_is_required_and_must_be_known(accounts):
    for extra in ({}, {"account_type": "owner"}, {"account_type": ""}):
        r = accounts.post("/auth/login", json={"email": "patient@types.example.com", "password": PASSWORD, **extra})
        assert r.status_code == 422, extra
    r = accounts.post("/auth/register", json={"name": "X", "email": "x@types.example.com", "password": PASSWORD})
    assert r.status_code == 422


def test_admin_console_sign_in_is_for_platform_admins_only(accounts):
    client = accounts
    assert _sign_in(client, "patient@types.example.com", "admin").status_code == 403
    admin(client, "boss@types.example.com")  # signs in with "admin"
    assert _sign_in(client, "boss@types.example.com", "admin").status_code == 200


def test_a_patient_cannot_register_a_business(accounts):
    client = accounts
    h = login(client, "patient@types.example.com")
    mark_email_verified(client, h)
    for kind in ("pharmacy", "supplier"):
        r = client.post("/organizations", json={"name": f"Sneaky {kind}", "type": kind}, headers=h)
        assert r.status_code == 403 and r.json()["code"] == "wrong_account_type"
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM organization")).scalar() == 0


def test_a_business_account_registers_only_its_own_kind(accounts):
    client = accounts
    h = login(client, "pharmacy@types.example.com")
    mark_email_verified(client, h)
    assert client.post("/organizations", json={"name": "Wrong kind", "type": "supplier"}, headers=h).status_code == 403
    assert client.post("/organizations", json={"name": "Right kind", "type": "pharmacy"}, headers=h).status_code == 201


def test_business_accounts_cannot_use_patient_reservations(accounts):
    client = accounts
    for t in ("pharmacy", "supplier"):
        h = login(client, f"{t}@types.example.com")
        r = client.get("/reservations", headers=h)
        assert r.status_code == 403 and r.json()["code"] == "wrong_account_type"
    assert client.get("/reservations", headers=login(client, "patient@types.example.com")).status_code == 200


def _pharmacy_with_owner(client):
    h = login(client, "pharmacy@types.example.com")
    mark_email_verified(client, h)
    org = client.post("/organizations", json={"name": "Typed Pharmacy", "type": "pharmacy"}, headers=h).json()
    return h, org["organization_id"]


def test_only_accounts_of_the_same_kind_can_be_added_or_invited(accounts):
    client = accounts
    owner, org = _pharmacy_with_owner(client)
    for email in ("patient@types.example.com", "supplier@types.example.com"):
        r = client.post(f"/organizations/{org}/members", json={"email": email, "role": "staff"}, headers=owner)
        assert r.status_code == 409 and r.json()["code"] == "wrong_account_type"
    # An invitation sent to a patient's address cannot be accepted by that patient account.
    client.post(f"/organizations/{org}/invitations", json={"email": "patient@types.example.com", "role": "staff"},
                headers=owner)
    token = client.get("/dev/email/latest-to", params={"to": "patient@types.example.com"}).json()["token"]
    r = client.post("/invitations/accept", json={"token": token}, headers=login(client, "patient@types.example.com"))
    assert r.status_code == 403 and r.json()["reason"] == "wrong_account_type"
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM membership WHERE organization_id = :o"), {"o": org}).scalar() == 1


def test_an_invitation_creates_an_account_of_the_organizations_kind(accounts):
    client = accounts
    owner, org = _pharmacy_with_owner(client)
    client.post(f"/organizations/{org}/invitations", json={"email": "new.staff@types.example.com", "role": "staff"},
                headers=owner)
    token = client.get("/dev/email/latest-to", params={"to": "new.staff@types.example.com"}).json()["token"]
    r = client.post("/invitations/accept-new", json={"token": token, "name": "New Staff", "password": PASSWORD})
    assert r.status_code == 201, r.text
    assert _sign_in(client, "new.staff@types.example.com", "pharmacy").status_code == 200
    assert _sign_in(client, "new.staff@types.example.com", "patient").status_code == 403


def test_a_membership_of_the_wrong_kind_grants_nothing(accounts):
    """Even a membership row that should never exist (older data) gives a
    patient account no access to the organization."""
    client = accounts
    adm = admin(client, "boss@types.example.com")
    owner, org = _pharmacy_with_owner(client)
    approve(client, adm, org)
    patient = login(client, "patient@types.example.com")
    with engine.begin() as c:
        c.execute(text("INSERT INTO membership (user_id, organization_id, role) "
                       "SELECT user_id, :o, 'manager' FROM app_user WHERE email = 'patient@types.example.com'"),
                  {"o": org})
    for path in (f"/organizations/{org}", f"/organizations/{org}/members", f"/conversations?organization_id={org}"):
        assert client.get(path, headers=patient).status_code == 404, path
    assert client.get(f"/organizations/{org}", headers=owner).status_code == 200


def test_a_session_from_one_page_does_not_open_another_groups_features(accounts):
    """Signing in elsewhere is refused; an existing patient session stays a patient session."""
    client = accounts
    owner, org = _pharmacy_with_owner(client)
    patient = login(client, "patient@types.example.com")
    assert client.get(f"/organizations/{org}", headers=patient).status_code == 404
    assert client.get("/organizations", headers=patient).json() == []
    assert client.get("/reservations", headers=owner).status_code == 403
