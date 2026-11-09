"""The admin endpoints the dashboard (frontend/admin.html) relies on: access
control, listing and filters, detail, and organization review transitions."""

import io
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from sqlalchemy import text

from app.core.config import settings
from app.core.database import engine
from tests.helpers import admin, approve, location, organization, user

PDF = b"%PDF-1.4\n% dummy test document\n%%EOF\n"

ADMIN_GETS = [
    "/admin/organizations",
    "/admin/organizations/counts",
    "/admin/documents",
    "/admin/users",
    "/admin/insights/searches",
]


def _status_in_db(org_id: int):
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT status, reviewed_by, review_notes FROM organization WHERE organization_id = :id"),
            {"id": org_id},
        ).one()
    return row.status, row.reviewed_by, row.review_notes


def _admin_id() -> int:
    with engine.connect() as conn:
        return conn.execute(text("SELECT user_id FROM app_user WHERE is_platform_admin")).scalar_one()


def _review(client, headers, org_id, decision, notes=None):
    body = {"decision": decision}
    if notes:
        body["notes"] = notes
    return client.post(f"/admin/organizations/{org_id}/review", json=body, headers=headers)


# ---------------------------------------------------------------------------
# Authentication and authorization
# ---------------------------------------------------------------------------
def test_admin_login_and_access(client):
    headers = admin(client)
    assert client.get("/auth/me", headers=headers).json()["is_platform_admin"] is True
    for path in ADMIN_GETS:
        assert client.get(path, headers=headers).status_code == 200, path


def test_ordinary_user_is_denied(client):
    headers = user(client, "someone@x.example.com")
    org_id = organization(client, headers, "pharmacy", "Own Pharmacy")
    for path in ADMIN_GETS:
        r = client.get(path, headers=headers)
        assert r.status_code == 403, path
    # Not even for their own organization.
    assert client.get(f"/admin/organizations/{org_id}", headers=headers).status_code == 403
    assert _review(client, headers, org_id, "approved").status_code == 403
    assert _status_in_db(org_id)[0] == "pending"


@pytest.mark.parametrize("auth", [None, "Bearer not-a-jwt", "Basic YWRtaW46YWRtaW4="])
def test_unauthenticated_and_malformed_tokens_are_denied(client, auth):
    headers = {"Authorization": auth} if auth else {}
    for path in ADMIN_GETS:
        assert client.get(path, headers=headers).status_code == 401, path


def test_expired_and_forged_tokens_are_denied(client):
    admin(client)
    admin_id = _admin_id()
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    expired = jwt.encode(
        {"sub": str(admin_id), "iat": past - timedelta(minutes=30), "exp": past, "type": "access"},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    forged = jwt.encode(
        {"sub": str(admin_id), "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        "some-other-secret-that-is-long-enough",
        algorithm="HS256",
    )
    for token in (expired, forged):
        r = client.get("/admin/organizations", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401
        assert r.headers["www-authenticate"] == "Bearer"


def test_revoked_admin_loses_access(client):
    headers = admin(client)
    with engine.begin() as conn:
        conn.execute(text("UPDATE app_user SET is_platform_admin = false"))
    assert client.get("/admin/organizations", headers=headers).status_code == 403


# ---------------------------------------------------------------------------
# Organization listing, filters and detail
# ---------------------------------------------------------------------------
@pytest.fixture
def orgs(client):
    admin_h = admin(client)
    owners, ids = {}, {}
    for key, type_, name in [
        ("p1", "pharmacy", "Remera Pharmacy"),
        ("p2", "pharmacy", "Kacyiru Pharmacy"),
        ("p3", "pharmacy", "Nyamirambo Pharmacy"),
        ("s1", "supplier", "Inyange Supplies"),
    ]:
        owners[key] = user(client, f"{key}@x.example.com", f"Owner {key}")
        ids[key] = organization(client, owners[key], type_, name)
    approve(client, admin_h, ids["p1"])
    assert _review(client, admin_h, ids["p2"], "rejected", "License unreadable").status_code == 200
    approve(client, admin_h, ids["s1"])
    assert _review(client, admin_h, ids["s1"], "suspended", "Expired license").status_code == 200
    return {"admin": admin_h, "owners": owners, "ids": ids}


def test_list_and_counts_by_filter(client, orgs):
    h = orgs["admin"]

    def total(**params):
        r = client.get("/admin/organizations", params={"limit": 1, **params}, headers=h)
        assert r.status_code == 200, r.text
        return r.json()["total"]

    # Exactly what the dashboard overview computes.
    assert total() == 4
    assert total(type="pharmacy") == 3
    assert total(type="supplier") == 1
    assert total(status="pending") == 1
    assert total(status="approved") == 1
    assert total(status="rejected") == 1
    assert total(status="suspended") == 1
    assert total(type="pharmacy", status="approved") == 1

    r = client.get("/admin/organizations", params={"q": "kacyiru"}, headers=h).json()
    assert [o["name"] for o in r["items"]] == ["Kacyiru Pharmacy"]
    assert {"organization_id", "name", "type", "status", "email", "phone", "created_at", "review_notes"} <= set(
        r["items"][0]
    )

    page = client.get("/admin/organizations", params={"limit": 2, "offset": 2}, headers=h).json()
    assert page["total"] == 4 and len(page["items"]) == 2

    assert client.get("/admin/organizations", params={"status": "bogus"}, headers=h).status_code == 422


def test_overview_counts_in_one_request(client, orgs):
    r = client.get("/admin/organizations/counts", headers=orgs["admin"])
    assert r.status_code == 200, r.text
    # The same numbers as the per-filter totals above.
    assert r.json() == {
        "total": 4, "pharmacy": 3, "supplier": 1,
        "pending": 1, "approved": 1, "rejected": 1, "suspended": 1,
    }
    # "counts" is not mistaken for an organization id.
    assert client.get("/admin/organizations/999999", headers=orgs["admin"]).status_code == 404


def test_overview_counts_when_empty(client):
    r = client.get("/admin/organizations/counts", headers=admin(client))
    assert r.json() == dict.fromkeys(
        ("total", "pharmacy", "supplier", "pending", "approved", "rejected", "suspended"), 0
    )


def test_organization_detail(client, orgs, fake_bucket):
    h, owner, org_id = orgs["admin"], orgs["owners"]["p3"], orgs["ids"]["p3"]
    location(client, owner, org_id, "Nyamirambo Branch", -1.98, 30.04, address="KN 2 Rd")
    r = client.post(
        f"/organizations/{org_id}/documents",
        data={"document_type": "pharmacy_license"},
        files={"file": ("license.pdf", io.BytesIO(PDF), "application/pdf")},
        headers=owner,
    )
    assert r.status_code == 201, r.text

    d = client.get(f"/admin/organizations/{org_id}", headers=h).json()
    assert d["name"] == "Nyamirambo Pharmacy" and d["status"] == "pending"
    assert [loc["name"] for loc in d["locations"]] == ["Nyamirambo Branch"]
    assert d["locations"][0]["address"] == "KN 2 Rd"
    assert [m["email"] for m in d["members"]] == ["p3@x.example.com"]
    assert d["members"][0]["role"] == "owner"
    assert [doc["file_name"] for doc in d["documents"]] == ["license.pdf"]
    # The storage key is internal and never returned.
    assert "storage_key" not in d["documents"][0]

    assert client.get("/admin/organizations/999999", headers=h).status_code == 404


# ---------------------------------------------------------------------------
# Review transitions
# ---------------------------------------------------------------------------
def test_approve_reject_suspend_persist(client, orgs):
    h, ids = orgs["admin"], orgs["ids"]
    admin_id = _admin_id()

    approve(client, h, ids["p3"])
    assert _status_in_db(ids["p3"]) == ("approved", admin_id, None)

    r = _review(client, h, ids["p3"], "suspended", "Inspection pending")
    assert r.status_code == 200 and r.json()["status"] == "suspended"
    assert _status_in_db(ids["p3"]) == ("suspended", admin_id, "Inspection pending")

    assert _review(client, h, ids["p3"], "rejected", "Inspection failed").status_code == 200
    assert _status_in_db(ids["p3"]) == ("rejected", admin_id, "Inspection failed")


def test_invalid_transitions_are_rejected(client, orgs):
    h, ids = orgs["admin"], orgs["ids"]
    cases = [
        (ids["p1"], "approved", None),  # approved -> approved
        (ids["p1"], "rejected", "x"),  # approved -> rejected (must suspend first)
        (ids["p2"], "suspended", "x"),  # rejected -> suspended
        (ids["p2"], "rejected", "x"),  # rejected -> rejected
    ]
    for org_id, decision, notes in cases:
        before = _status_in_db(org_id)
        r = _review(client, h, org_id, decision, notes)
        assert r.status_code == 409, (decision, r.text)
        assert _status_in_db(org_id) == before

    # Notes are mandatory for negative decisions; "pending" is not a decision.
    pending = organization(client, orgs["owners"]["p3"], "supplier", "Second Org")
    assert _review(client, h, pending, "rejected").status_code == 422
    assert _review(client, h, pending, "suspended").status_code == 422
    assert _review(client, h, pending, "pending").status_code == 422
    assert _status_in_db(pending)[0] == "pending"


def test_approval_requires_reviewed_documents(client, orgs, fake_bucket):
    h, owner, org_id = orgs["admin"], orgs["owners"]["p3"], orgs["ids"]["p3"]
    doc = client.post(
        f"/organizations/{org_id}/documents",
        data={"document_type": "owner_id"},
        files={"file": ("id.pdf", io.BytesIO(PDF), "application/pdf")},
        headers=owner,
    ).json()
    r = _review(client, h, org_id, "approved")
    assert r.status_code == 409 and "pending document" in r.json()["detail"]
    assert _status_in_db(org_id)[0] == "pending"

    review = f"/admin/documents/{doc['document_id']}/review"
    assert client.post(review, json={"decision": "rejected"}, headers=h).status_code == 422
    r = client.post(review, json={"decision": "rejected", "rejection_reason": "Blurry"}, headers=h)
    assert r.json()["verification_status"] == "rejected" and r.json()["rejection_reason"] == "Blurry"
    assert client.post(review, json={"decision": "approved"}, headers=h).status_code == 409

    approve(client, h, org_id)
    assert _status_in_db(org_id)[0] == "approved"


# ---------------------------------------------------------------------------
# Every write the admin console (frontend/js/admin-console.js) can make is
# refused to regular users and anonymous callers, and leaves nothing changed.
# ---------------------------------------------------------------------------
def test_admin_console_writes_require_platform_admin(client):
    admin_h = admin(client)
    drug = client.post("/catalogue/drugs", json={"name": "Consoletol"}, headers=admin_h).json()
    product = client.post("/catalogue/products", json={"drug_id": drug["drug_id"], "product_name": "Consoletol 500mg"},
                          headers=admin_h).json()
    regular = user(client, "regular@x.example.com")
    target = client.get("/admin/users", params={"q": "regular@x.example.com"}, headers=admin_h).json()["items"][0]

    writes = [
        ("patch", f"/admin/users/{target['user_id']}", {"is_platform_admin": True}),
        ("patch", f"/admin/users/{target['user_id']}", {"is_active": False}),
        ("post", "/catalogue/drugs", {"name": "Sneakytol"}),
        ("patch", f"/catalogue/drugs/{drug['drug_id']}", {"name": "Renamed"}),
        ("post", "/catalogue/products", {"drug_id": drug["drug_id"], "product_name": "Sneaky 1mg"}),
        ("patch", f"/catalogue/products/{product['product_id']}", {"is_active": False}),
    ]
    for method, path, body in writes:
        assert getattr(client, method)(path, json=body, headers=regular).status_code == 403, path
        assert getattr(client, method)(path, json=body).status_code == 401, path

    me = client.get("/auth/me", headers=regular).json()
    assert me["is_platform_admin"] is False and me["is_active"] is True
    assert client.get(f"/catalogue/drugs/{drug['drug_id']}").json()["name"] == "Consoletol"
    assert client.get(f"/catalogue/products/{product['product_id']}").json()["is_active"] is True
    assert client.get("/catalogue/drugs", params={"q": "Sneakytol"}).json()["total"] == 0
