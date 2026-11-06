"""Registration only proceeds with a verified phone, and that number is the
pharmacy's number. All enforced on the server, whatever the client sends."""

from sqlalchemy import text

from app.core.config import settings
from app.core.database import engine
from tests.helpers import PASSWORD, register, user, verify_phone_via_api

PHONE = "+250788123456"


def create(client, h, **extra):
    return client.post("/organizations", json={"name": "My Pharmacy", "type": "pharmacy", **extra}, headers=h)


def test_full_registration_flow(client):
    register(client, "new@x.example.com")
    token = client.post("/auth/login", json={"email": "new@x.example.com", "password": PASSWORD}).json()
    h = {"Authorization": f"Bearer {token['access_token']}"}
    assert client.get("/auth/phone/status", headers=h).json()["verified"] is False
    assert verify_phone_via_api(client, h, "0788 123 456") == PHONE
    r = create(client, h)
    assert r.status_code == 201 and r.json()["phone"] == PHONE


def test_pharmacy_requires_a_verified_phone(client):
    h = user(client, "unverified@x.example.com")
    r = create(client, h)
    assert r.status_code == 403 and "Verify your mobile number" in r.json()["detail"]
    r = create(client, h, phone="0788123456")
    assert r.status_code == 403


def test_pharmacy_phone_must_be_the_verified_number(client):
    h = user(client, "owner@x.example.com")
    verify_phone_via_api(client, h, "0788123456")
    r = create(client, h, phone="0788999888")
    assert r.status_code == 400 and PHONE in r.json()["detail"]
    r = create(client, h, phone="+250 788 123 456")  # same number, other format
    assert r.status_code == 201 and r.json()["phone"] == PHONE


def test_suppliers_are_unaffected(client):
    h = user(client, "supplier@x.example.com")
    r = client.post(
        "/organizations", json={"name": "Sup", "type": "supplier", "phone": "+250 788 1"}, headers=h
    )
    assert r.status_code == 201


def test_client_cannot_mark_itself_verified(client):
    h = user(client, "sneaky@x.example.com")
    client.patch(
        "/auth/me", json={"verified_phone": PHONE, "phone_verified_at": "2026-01-01T00:00:00Z"}, headers=h
    )
    client.post(
        "/auth/register",
        json={"name": "x", "email": "s2@x.example.com", "password": PASSWORD, "verified_phone": PHONE},
    )
    assert client.get("/auth/me", headers=h).json()["verified_phone"] is None
    client.post("/auth/phone/verify", json={"phone": PHONE, "code": "123456", "verified": True}, headers=h)
    assert client.get("/auth/me", headers=h).json()["verified_phone"] is None
    assert create(client, h).status_code == 403


def test_changing_profile_phone_does_not_transfer_verification(client):
    h = user(client, "owner@x.example.com")
    verify_phone_via_api(client, h, "0788123456")
    client.patch("/auth/me", json={"phone": "+250788999888"}, headers=h)
    me = client.get("/auth/me", headers=h).json()
    assert me["phone"] == "+250788999888" and me["verified_phone"] == PHONE
    assert create(client, h, phone="0788999888").status_code == 400
    assert create(client, h).json()["phone"] == PHONE


def test_pharmacy_phone_change_needs_verification(client):
    h = user(client, "owner@x.example.com")
    verify_phone_via_api(client, h, "0788123456")
    org = create(client, h).json()
    url = f"/organizations/{org['organization_id']}"
    assert client.patch(url, json={"phone": "0788999888"}, headers=h).status_code == 400
    assert client.patch(url, json={"phone": None}, headers=h).status_code == 400
    # Unchanged (in any format) is fine, as are other fields.
    r = client.patch(url, json={"phone": "0788 123 456", "name": "Renamed"}, headers=h)
    assert r.status_code == 200 and r.json()["phone"] == PHONE and r.json()["name"] == "Renamed"


def test_existing_pharmacy_with_legacy_phone_can_still_edit_other_fields(client):
    h = user(client, "legacy@x.example.com")
    with engine.begin() as c:
        c.execute(
            text(
                "UPDATE app_user SET verified_phone = :p, phone_verified_at = now() "
                "WHERE email = 'legacy@x.example.com'"
            ),
            {"p": PHONE},
        )
    org = create(client, h).json()
    with engine.begin() as c:
        c.execute(
            text("UPDATE organization SET phone = '+250700000101' WHERE organization_id = :o"),
            {"o": org["organization_id"]},
        )
        c.execute(
            text(
                "UPDATE app_user SET verified_phone = NULL, phone_verified_at = NULL "
                "WHERE email = 'legacy@x.example.com'"
            )
        )
    r = client.patch(
        f"/organizations/{org['organization_id']}",
        json={"name": "Still Works", "phone": "+250700000101"},
        headers=h,
    )
    assert r.status_code == 200, r.text


def test_verification_can_be_switched_off(client, monkeypatch):
    monkeypatch.setattr(settings, "phone_verification_required", False)
    h = user(client, "free@x.example.com")
    assert client.get("/auth/phone/status", headers=h).json()["required"] is False
    r = create(client, h, phone="+250 788 1")
    assert r.status_code == 201
