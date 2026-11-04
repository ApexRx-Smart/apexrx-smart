import io

from sqlalchemy import text

from app.core.database import engine
from tests.helpers import (
    PASSWORD,
    admin,
    approve,
    location,
    login,
    organization,
    register,
    user,
)


def test_health(client):
    assert client.get("/health").json() == {"status": "healthy", "database": "connected"}


def test_register_login_me(client):
    created = register(client, "  Jane@Example.COM ", "Jane")
    assert created["email"] == "jane@example.com"
    assert "password_hash" not in created

    # Email is case/whitespace-insensitive and unique.
    r = client.post("/auth/register", json={"name": "J", "email": "JANE@example.com", "password": PASSWORD})
    assert r.status_code == 409

    assert client.post("/auth/login", json={"email": "jane@example.com", "password": "wrong-password"}).status_code == 401
    headers = login(client, "JANE@example.com")
    me = client.get("/auth/me", headers=headers).json()
    assert me["name"] == "Jane" and me["memberships"] == []

    assert client.get("/auth/me").status_code == 401
    assert client.get("/auth/me", headers={"Authorization": "Bearer nonsense"}).status_code == 401


def test_change_password_and_deactivated_user(client):
    headers = user(client, "a@x.example.com")
    r = client.post("/auth/me/password", json={"current_password": "nope", "new_password": "another-password"}, headers=headers)
    assert r.status_code == 400
    r = client.post("/auth/me/password", json={"current_password": PASSWORD, "new_password": "another-password"}, headers=headers)
    assert r.status_code == 200
    assert client.post("/auth/login", json={"email": "a@x.example.com", "password": "another-password"}).status_code == 200

    with engine.begin() as conn:
        conn.execute(text("UPDATE app_user SET is_active = false WHERE email = 'a@x.example.com'"))
    assert client.get("/auth/me", headers=headers).status_code == 401


def test_organization_registration_and_review(client):
    owner = user(client, "owner@x.example.com")
    admin_h = admin(client)
    org_id = organization(client, owner, "pharmacy", "Good Health")

    org = client.get(f"/organizations/{org_id}", headers=owner).json()
    assert org["status"] == "pending"
    me = client.get("/auth/me", headers=owner).json()
    assert me["memberships"][0]["role"] == "owner"

    # Non-admins cannot review; strangers cannot even see the organization.
    assert client.post(f"/admin/organizations/{org_id}/review", json={"decision": "approved"}, headers=owner).status_code == 403
    stranger = user(client, "stranger@x.example.com")
    assert client.get(f"/organizations/{org_id}", headers=stranger).status_code == 404

    # Rejection needs notes; the owner can resubmit.
    r = client.post(f"/admin/organizations/{org_id}/review", json={"decision": "rejected"}, headers=admin_h)
    assert r.status_code == 422
    r = client.post(f"/admin/organizations/{org_id}/review", json={"decision": "rejected", "notes": "License unreadable"}, headers=admin_h)
    assert r.json()["status"] == "rejected"
    assert client.post(f"/organizations/{org_id}/resubmit", headers=owner).json()["status"] == "pending"

    queue = client.get("/admin/organizations", params={"status": "pending"}, headers=admin_h).json()
    assert [o["organization_id"] for o in queue["items"]] == [org_id]

    approve(client, admin_h, org_id)
    r = client.post(f"/admin/organizations/{org_id}/review", json={"decision": "suspended", "notes": "Expired license"}, headers=admin_h)
    assert r.json()["status"] == "suspended"
    # Invalid transition
    r = client.post(f"/admin/organizations/{org_id}/review", json={"decision": "suspended", "notes": "x"}, headers=admin_h)
    assert r.status_code == 409


def test_member_roles(client):
    owner = user(client, "owner@x.example.com")
    org_id = organization(client, owner, "pharmacy", "P")
    register(client, "manager@x.example.com")
    register(client, "staff@x.example.com")
    register(client, "other@x.example.com")

    r = client.post(f"/organizations/{org_id}/members", json={"email": "manager@x.example.com", "role": "manager"}, headers=owner)
    assert r.status_code == 201
    manager_membership = r.json()["membership_id"]
    manager = login(client, "manager@x.example.com")

    # Managers add staff, but not managers/owners.
    assert client.post(f"/organizations/{org_id}/members", json={"email": "other@x.example.com", "role": "manager"}, headers=manager).status_code == 403
    r = client.post(f"/organizations/{org_id}/members", json={"email": "staff@x.example.com", "role": "staff"}, headers=manager)
    assert r.status_code == 201
    staff = login(client, "staff@x.example.com")

    assert client.post(f"/organizations/{org_id}/members", json={"email": "staff@x.example.com", "role": "staff"}, headers=owner).status_code == 409
    assert client.post(f"/organizations/{org_id}/members", json={"email": "nobody@x.example.com", "role": "staff"}, headers=owner).status_code == 404

    # Staff cannot manage members or locations.
    assert client.post(f"/organizations/{org_id}/members", json={"email": "other@x.example.com", "role": "staff"}, headers=staff).status_code == 403
    assert client.post(f"/organizations/{org_id}/locations", json={"name": "X"}, headers=staff).status_code == 403
    assert client.patch(f"/organizations/{org_id}/members/{manager_membership}", json={"role": "staff"}, headers=manager).status_code == 403

    members = client.get(f"/organizations/{org_id}/members", headers=staff).json()
    assert {m["email"]: m["role"] for m in members} == {
        "owner@x.example.com": "owner", "manager@x.example.com": "manager", "staff@x.example.com": "staff",
    }

    # The last owner cannot leave or be demoted.
    owner_membership = next(m["membership_id"] for m in members if m["role"] == "owner")
    assert client.delete(f"/organizations/{org_id}/members/{owner_membership}", headers=owner).status_code == 409
    assert client.patch(f"/organizations/{org_id}/members/{owner_membership}", json={"role": "manager"}, headers=owner).status_code == 409

    # Staff can leave on their own.
    staff_membership = next(m["membership_id"] for m in members if m["role"] == "staff")
    assert client.delete(f"/organizations/{org_id}/members/{staff_membership}", headers=staff).status_code == 204
    assert client.get(f"/organizations/{org_id}", headers=staff).status_code == 404


def test_locations(client):
    owner = user(client, "owner@x.example.com")
    org_id = organization(client, owner, "supplier", "S")
    loc = location(client, owner, org_id, "Warehouse", -1.95, 30.06, whatsapp_phone="+250788000000")
    r = client.post(f"/organizations/{org_id}/locations", json={"name": "Bad", "latitude": 10}, headers=owner)
    assert r.status_code == 422  # latitude without longitude

    r = client.patch(f"/organizations/{org_id}/locations/{loc}", json={"is_active": False}, headers=owner)
    assert r.json()["is_active"] is False
    assert client.get(f"/organizations/{org_id}/locations", headers=owner).json() == []
    assert len(client.get(f"/organizations/{org_id}/locations", params={"include_inactive": True}, headers=owner).json()) == 1


PDF = b"%PDF-1.4\n%test document\n"


def test_documents(client):
    owner = user(client, "owner@x.example.com")
    admin_h = admin(client)
    org_id = organization(client, owner, "pharmacy", "P")

    r = client.post(
        f"/organizations/{org_id}/documents",
        data={"document_type": "pharmacy_license"},
        files={"file": ("license.pdf", io.BytesIO(PDF), "application/pdf")},
        headers=owner,
    )
    assert r.status_code == 201, r.text
    doc = r.json()
    assert doc["verification_status"] == "pending" and doc["file_size_bytes"] == len(PDF)

    # Content must match the declared type; other types are refused.
    r = client.post(
        f"/organizations/{org_id}/documents",
        data={"document_type": "x"},
        files={"file": ("fake.pdf", io.BytesIO(b"MZ not a pdf"), "application/pdf")},
        headers=owner,
    )
    assert r.status_code == 415
    r = client.post(
        f"/organizations/{org_id}/documents",
        data={"document_type": "x"},
        files={"file": ("a.exe", io.BytesIO(b"MZ"), "application/octet-stream")},
        headers=owner,
    )
    assert r.status_code == 415

    r = client.get(f"/organizations/{org_id}/documents/{doc['document_id']}/download", headers=owner)
    assert r.status_code == 200 and r.content == PDF

    # Approval is blocked while documents are pending.
    r = client.post(f"/admin/organizations/{org_id}/review", json={"decision": "approved"}, headers=admin_h)
    assert r.status_code == 409

    pending = client.get("/admin/documents", headers=admin_h).json()
    assert pending["total"] == 1 and pending["items"][0]["organization_name"] == "P"
    assert client.get(f"/admin/documents/{doc['document_id']}/download", headers=admin_h).content == PDF

    r = client.post(f"/admin/documents/{doc['document_id']}/review", json={"decision": "approved"}, headers=admin_h)
    assert r.json()["verification_status"] == "approved"
    assert client.delete(f"/organizations/{org_id}/documents/{doc['document_id']}", headers=owner).status_code == 409
    approve(client, admin_h, org_id)


def test_admin_users(client):
    admin_h = admin(client)
    target = register(client, "t@x.example.com")
    me = client.get("/auth/me", headers=admin_h).json()

    assert client.patch(f"/admin/users/{me['user_id']}", json={"is_active": False}, headers=admin_h).status_code == 400
    r = client.patch(f"/admin/users/{target['user_id']}", json={"is_active": False}, headers=admin_h)
    assert r.json()["is_active"] is False
    assert client.post("/auth/login", json={"email": "t@x.example.com", "password": PASSWORD}).status_code == 401
    assert client.get("/admin/users", params={"q": "t@x"}, headers=admin_h).json()["total"] == 1
