"""Lockout protection: a browser that signed in before (device token) keeps
working while someone else locks the account with wrong passwords."""

import json
import time

import pytest

from app.core import device_token
from app.core.config import settings
from app.core.rate_limit import login_limiter
from tests.helpers import PASSWORD, register

LIMIT = 3


@pytest.fixture(autouse=True)
def small_limits():
    saved = {
        k: getattr(settings, k)
        for k in (
            "login_max_failures_per_account",
            "login_max_failures_per_ip",
            "login_failure_window_seconds",
        )
    }
    settings.login_max_failures_per_account = LIMIT
    settings.login_max_failures_per_ip = 1000
    settings.login_failure_window_seconds = 60
    login_limiter.configure()
    yield
    for k, v in saved.items():
        setattr(settings, k, v)
    login_limiter.configure()


def login(client, email, password=PASSWORD, token=None):
    body = {"email": email, "password": password}
    if token is not None:
        body["device_token"] = token
    return client.post("/auth/login", json=body)


def known_browser(client, email):
    r = login(client, email)
    assert r.status_code == 200
    return r.json()["device_token"]


def lock(client, email):
    for _ in range(LIMIT):
        assert login(client, email, "attacker-guess").status_code == 401
    assert login(client, email, "attacker-guess").status_code == 429


def user_id(client, email):
    r = login(client, email)
    return client.get("/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}).json()[
        "user_id"
    ]


def test_login_returns_a_new_device_token_each_time(client):
    register(client, "a@x.example.com")
    t1, t2 = known_browser(client, "a@x.example.com"), known_browser(client, "a@x.example.com")
    assert t1 and t2 and t1 != t2


def test_owner_on_known_browser_survives_lockout(client):
    register(client, "owner@x.example.com")
    token = known_browser(client, "owner@x.example.com")
    lock(client, "owner@x.example.com")  # attacker, no token

    # Unknown browsers stay locked, even with the right password...
    assert login(client, "owner@x.example.com").status_code == 429
    # ...but the owner's known browser signs in.
    r = login(client, "owner@x.example.com", token=token)
    assert r.status_code == 200 and r.json()["access_token"]
    # The attacker is still locked out afterwards.
    assert login(client, "owner@x.example.com", "attacker-guess").status_code == 429


def test_known_browser_has_its_own_limit(client):
    register(client, "typo@x.example.com")
    token = known_browser(client, "typo@x.example.com")
    for _ in range(LIMIT):
        assert login(client, "typo@x.example.com", "wrong", token=token).status_code == 401
    assert login(client, "typo@x.example.com", token=token).status_code == 429
    # Its failures did not lock the account for other browsers.
    assert login(client, "typo@x.example.com").status_code == 200


def test_success_on_known_browser_does_not_unlock_the_account(client):
    register(client, "b@x.example.com")
    token = known_browser(client, "b@x.example.com")
    lock(client, "b@x.example.com")
    assert login(client, "b@x.example.com", token=token).status_code == 200
    assert login(client, "b@x.example.com").status_code == 429


def test_token_for_another_account_is_ignored(client):
    register(client, "victim@x.example.com")
    register(client, "attacker@x.example.com")
    attacker_token = known_browser(client, "attacker@x.example.com")
    lock(client, "victim@x.example.com")
    # The attacker's own valid token does not exempt them on the victim's account.
    assert login(client, "victim@x.example.com", "guess", token=attacker_token).status_code == 429
    assert login(client, "victim@x.example.com", token=attacker_token).status_code == 429


@pytest.mark.parametrize("mangle", ["tamper", "garbage", "empty", "two-dots"])
def test_invalid_tokens_are_ignored(client, mangle):
    register(client, "c@x.example.com")
    token = known_browser(client, "c@x.example.com")
    bad = {
        "tamper": token[:-2] + ("AA" if not token.endswith("AA") else "BB"),
        "garbage": "not-a-token",
        "empty": "",
        "two-dots": token + ".x",
    }[mangle]
    lock(client, "c@x.example.com")
    assert login(client, "c@x.example.com", token=bad).status_code == 429


def test_oversized_token_is_rejected(client):
    r = login(client, "d@x.example.com", token="x" * 600)
    assert r.status_code == 422


def test_unknown_email_with_a_token_behaves_like_any_unknown_browser(client):
    register(client, "e@x.example.com")
    token = known_browser(client, "e@x.example.com")
    codes = [login(client, "ghost@x.example.com", "guess", token=token).status_code for _ in range(LIMIT + 1)]
    assert codes == [401] * LIMIT + [429]


def test_expired_token_is_ignored(client):
    register(client, "f@x.example.com")
    uid = user_id(client, "f@x.example.com")
    # A correctly signed token for this user whose expiry has passed.
    body = device_token._b64(json.dumps({"u": uid, "d": "0" * 32, "exp": int(time.time()) - 1}).encode())
    expired = f"{body}.{device_token._sign(body.encode())}"
    assert device_token.device_id_for(expired, uid) is None
    lock(client, "f@x.example.com")
    assert login(client, "f@x.example.com", token=expired).status_code == 429


def test_rotating_the_jwt_secret_invalidates_device_tokens(client, monkeypatch):
    register(client, "g@x.example.com")
    uid = user_id(client, "g@x.example.com")
    token = device_token.issue(uid)
    assert device_token.device_id_for(token, uid)
    monkeypatch.setattr(settings, "jwt_secret_key", settings.jwt_secret_key[::-1] + "x")
    assert device_token.device_id_for(token, uid) is None


def test_device_token_unit_checks():
    token = device_token.issue(42)
    device = device_token.device_id_for(token, 42)
    assert device and len(device) == 32
    assert device_token.device_id_for(token, 43) is None
    assert device_token.device_id_for(token, None) is None
    assert device_token.device_id_for(None, 42) is None
    assert device_token.device_id_for("a.b", 42) is None
