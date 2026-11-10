"""Regression tests: ordinary users cannot become platform admins, and admin
rights come from the database, not from the token."""

import base64
import json
from datetime import datetime, timedelta, timezone

import jwt
from sqlalchemy import text

from app.core.config import settings
from app.core.database import engine
from tests.helpers import PASSWORD, admin, login, mark_email_verified, organization, register, user


def _is_admin(email):
    with engine.connect() as c:
        return c.execute(
            text("SELECT is_platform_admin FROM app_user WHERE email = :e"), {"e": email}
        ).scalar()


def _token(sub, key=None, **claims):
    exp = datetime.now(timezone.utc) + timedelta(minutes=5)
    return jwt.encode(
        {"sub": str(sub), "exp": exp, "type": "access", **claims},
        key or settings.jwt_secret_key,
        algorithm="HS256",
    )


def test_registration_cannot_set_admin(client):
    r = client.post(
        "/auth/register",
        json={
            "name": "M",
            "email": "m@x.example.com",
            "password": PASSWORD,
            "is_platform_admin": True,
            "is_active": True,
            "user_id": 1,
        },
    )
    assert r.status_code == 201 and r.json()["is_platform_admin"] is False
    assert _is_admin("m@x.example.com") is False


def test_profile_update_cannot_set_admin(client):
    h = user(client, "m@x.example.com")
    r = client.patch("/auth/me", json={"name": "M2", "is_platform_admin": True, "is_active": True}, headers=h)
    assert r.status_code == 200 and r.json()["name"] == "M2" and r.json()["is_platform_admin"] is False
    assert _is_admin("m@x.example.com") is False


def test_non_admin_cannot_use_admin_user_endpoint_on_self(client):
    h = user(client, "m@x.example.com")
    me = client.get("/auth/me", headers=h).json()
    r = client.patch(f"/admin/users/{me['user_id']}", json={"is_platform_admin": True}, headers=h)
    assert r.status_code == 403 and _is_admin("m@x.example.com") is False


def test_organization_requests_cannot_self_approve_or_promote(client):
    h = user(client, "m@x.example.com")
    mark_email_verified(client, h)
    org = client.post(
        "/organizations",
        json={"name": "Mine", "type": "pharmacy", "status": "approved", "is_platform_admin": True},
        headers=h,
    ).json()
    assert org["status"] == "pending"
    client.patch(f"/organizations/{org['organization_id']}", json={"status": "approved"}, headers=h)
    assert client.get(f"/organizations/{org['organization_id']}", headers=h).json()["status"] == "pending"
    assert _is_admin("m@x.example.com") is False


def test_admin_claims_in_token_are_ignored(client):
    register(client, "m@x.example.com")
    uid = client.post("/auth/login", json={"email": "m@x.example.com", "password": PASSWORD})
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {uid.json()['access_token']}"}).json()
    # A real session id, so only the extra claims differ from a genuine token.
    sid = jwt.decode(uid.json()["access_token"], options={"verify_signature": False})["sid"]
    forged = _token(me["user_id"], sid=sid, is_platform_admin=True, role="admin", admin=True)
    r = client.get("/admin/organizations", headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 403


def test_unsigned_and_foreign_key_tokens_are_rejected(client):
    admin(client)
    with engine.connect() as c:
        admin_id = c.execute(text("SELECT user_id FROM app_user WHERE is_platform_admin")).scalar_one()

    def b64(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()

    exp = int((datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp())
    tokens = [
        b64({"alg": "none", "typ": "JWT"})
        + "."
        + b64({"sub": str(admin_id), "exp": exp, "type": "access"})
        + ".",
        _token(admin_id, key="replace-with-a-long-random-secret"),
        _token(admin_id, key="test-secret-key-that-is-long-enough"),
        jwt.encode(
            {"sub": str(admin_id), "exp": exp, "type": "access"}, settings.jwt_secret_key, algorithm="HS512"
        ),
        _token(admin_id, type="refresh"),
    ]
    for t in tokens:
        assert client.get("/admin/organizations", headers={"Authorization": f"Bearer {t}"}).status_code == 401


def test_revocation_and_deactivation_apply_to_existing_tokens(client):
    h = admin(client, "boss@x.example.com")
    assert client.get("/admin/organizations", headers=h).status_code == 200
    with engine.begin() as c:
        c.execute(text("UPDATE app_user SET is_platform_admin = false WHERE email = 'boss@x.example.com'"))
    assert client.get("/admin/organizations", headers=h).status_code == 403
    with engine.begin() as c:
        c.execute(text("UPDATE app_user SET is_active = false WHERE email = 'boss@x.example.com'"))
    assert client.get("/auth/me", headers=h).status_code == 401
    # And a deactivated account cannot sign in again (generic 401).
    r = client.post("/auth/login", json={"email": "boss@x.example.com", "password": PASSWORD})
    assert r.status_code == 401 and r.json()["detail"] == "Invalid email or password."


def test_admin_functionality_still_works(client):
    a = admin(client)
    owner = user(client, "owner@x.example.com")
    org_id = organization(client, owner, "pharmacy", "Review Me")
    r = client.post(f"/admin/organizations/{org_id}/review", json={"decision": "approved"}, headers=a)
    assert r.status_code == 200 and r.json()["status"] == "approved"
    me = client.get("/auth/me", headers=owner).json()
    r = client.patch(f"/admin/users/{me['user_id']}", json={"is_active": False}, headers=a)
    assert r.status_code == 200 and r.json()["is_active"] is False
    assert login is not None  # helper import kept for parity with other suites
