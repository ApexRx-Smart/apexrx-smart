"""Server-side sessions: sign-out, inactivity, maximum age, activity renewal,
password change, and that signing out affects nobody else."""

import jwt
from sqlalchemy import text

from app.core.config import settings
from app.core.database import engine
from tests.helpers import PASSWORD, login, organization, register, user


def _token_of(headers):
    return headers["Authorization"].split()[1]


def _sid(headers):
    return int(jwt.decode(_token_of(headers), options={"verify_signature": False})["sid"])


def _session(sid):
    with engine.connect() as c:
        return c.execute(text("SELECT * FROM auth_session WHERE session_id = :s"), {"s": sid}).mappings().one()


def _idle_for(sid, minutes):
    with engine.begin() as c:
        c.execute(text("UPDATE auth_session SET last_activity_at = now() - make_interval(mins => :m) "
                       "WHERE session_id = :s"), {"m": minutes, "s": sid})


def test_login_returns_session_limits(client):
    register(client, "s@x.example.com")
    r = client.post("/auth/login", json={"email": "s@x.example.com", "password": PASSWORD})
    body = r.json()
    assert body["idle_timeout_seconds"] == 30 * 60 and body["session_expires_at"]
    assert 0 < body["expires_in"] <= 30 * 60
    claims = jwt.decode(body["access_token"], options={"verify_signature": False})
    assert claims["sid"] and claims["type"] == "access"
    row = _session(int(claims["sid"]))
    assert row["revoked_at"] is None
    assert (row["expires_at"] - row["created_at"]).total_seconds() == settings.session_max_age_hours * 3600


def test_logout_ends_only_this_session(client):
    register(client, "two@x.example.com")
    first, second = login(client, "two@x.example.com"), login(client, "two@x.example.com")
    org = organization(client, first, "pharmacy", "Logout Pharmacy")
    assert client.post("/auth/logout", headers=first).status_code == 204
    r = client.get("/auth/me", headers=first)
    assert r.status_code == 401 and r.json()["reason"] == "session_revoked"
    assert _session(_sid(first))["revoked_reason"] == "signed_out"
    # The other sign-in, the membership, the role and the organization are untouched.
    me = client.get("/auth/me", headers=second).json()
    assert [(m["organization_id"], m["role"]) for m in me["memberships"]] == [(org, "owner")]
    assert client.get(f"/organizations/{org}", headers=second).json()["status"] == "pending"
    # Signing out again with the dead token is refused, not an error.
    assert client.post("/auth/logout", headers=first).status_code == 401


def test_logout_does_not_affect_colleagues(client):
    owner = user(client, "owner@x.example.com")
    org = organization(client, owner, "pharmacy", "Team Pharmacy")
    staff = user(client, "staff@x.example.com")
    client.post(f"/organizations/{org}/members", json={"email": "staff@x.example.com", "role": "staff"}, headers=owner)
    assert client.post("/auth/logout", headers=staff).status_code == 204
    assert client.get(f"/organizations/{org}/members", headers=owner).status_code == 200
    members = client.get(f"/organizations/{org}/members", headers=owner).json()
    assert {m["email"]: (m["role"], m["is_active"]) for m in members}["staff@x.example.com"] == ("staff", True)


def test_inactivity_ends_the_session_on_the_server(client):
    h = user(client, "idle@x.example.com")
    _idle_for(_sid(h), 29)
    assert client.get("/auth/me", headers=h).status_code == 200
    _idle_for(_sid(h), 31)
    r = client.get("/auth/me", headers=h)
    assert r.status_code == 401 and r.json()["reason"] == "session_idle"
    assert "30 minutes of inactivity" in r.json()["detail"]
    assert _session(_sid(h))["revoked_reason"] == "idle"
    # Once ended it stays ended, even if the clock were moved back.
    _idle_for(_sid(h), 0)
    assert client.get("/auth/me", headers=h).json()["reason"] == "session_idle"


def test_ordinary_requests_are_not_activity(client):
    """Background requests (reads, refreshes) never extend the session."""
    h = user(client, "poll@x.example.com")
    _idle_for(_sid(h), 20)
    before = _session(_sid(h))["last_activity_at"]
    for _ in range(3):
        assert client.get("/auth/me", headers=h).status_code == 200
        assert client.get("/auth/session", headers=h).status_code == 200
    assert _session(_sid(h))["last_activity_at"] == before
    _idle_for(_sid(h), 31)
    assert client.get("/auth/me", headers=h).status_code == 401


def test_activity_renews_the_session_and_the_token(client):
    h = user(client, "busy@x.example.com")
    _idle_for(_sid(h), 25)
    r = client.post("/auth/session/activity", headers=h)
    assert r.status_code == 200
    fresh = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert _sid(fresh) == _sid(h)  # same session, new token
    s = client.get("/auth/session", headers=fresh).json()
    assert s["idle_timeout_seconds"] == 1800
    _idle_for(_sid(h), 10)
    assert client.get("/auth/me", headers=fresh).status_code == 200
    assert client.get("/auth/me", headers=h).status_code == 200  # the older token is the same session


def test_activity_cannot_revive_an_ended_session(client):
    h = user(client, "late@x.example.com")
    client.post("/auth/logout", headers=h)
    assert client.post("/auth/session/activity", headers=h).status_code == 401
    h2 = login(client, "late@x.example.com")
    _idle_for(_sid(h2), 45)
    assert client.post("/auth/session/activity", headers=h2).status_code == 401


def test_maximum_age(client):
    h = user(client, "old@x.example.com")
    with engine.begin() as c:
        c.execute(text("UPDATE auth_session SET created_at = now() - interval '13 hours', "
                       "expires_at = now() - interval '1 hour' WHERE session_id = :s"), {"s": _sid(h)})
    r = client.get("/auth/me", headers=h)
    assert r.status_code == 401 and r.json()["reason"] == "session_expired"


def test_token_without_a_session_is_refused(client):
    h = user(client, "nosid@x.example.com")
    claims = jwt.decode(_token_of(h), options={"verify_signature": False})
    claims.pop("sid")
    legacy = jwt.encode(claims, settings.jwt_secret_key, algorithm="HS256")
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {legacy}"}).status_code == 401


def test_session_of_another_user_is_refused(client):
    a = user(client, "a@x.example.com")
    b = user(client, "b@x.example.com")
    claims = jwt.decode(_token_of(a), options={"verify_signature": False})
    claims["sid"] = str(_sid(b))
    mixed = jwt.encode(claims, settings.jwt_secret_key, algorithm="HS256")
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {mixed}"}).status_code == 401


def test_password_change_signs_out_the_other_sessions(client):
    register(client, "pw@x.example.com")
    here, elsewhere = login(client, "pw@x.example.com"), login(client, "pw@x.example.com")
    r = client.post("/auth/me/password", json={"current_password": PASSWORD, "new_password": "brand-new-pass-1"},
                    headers=here)
    assert r.status_code == 200
    assert client.get("/auth/me", headers=here).status_code == 200
    assert client.get("/auth/me", headers=elsewhere).status_code == 401
    assert _session(_sid(elsewhere))["revoked_reason"] == "password_changed"


def test_signed_in_responses_are_not_cached(client):
    h = user(client, "cache@x.example.com")
    assert client.get("/auth/me", headers=h).headers["cache-control"] == "no-store"
    assert "no-store" not in client.get("/health").headers.get("cache-control", "")
