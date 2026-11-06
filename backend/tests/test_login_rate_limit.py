"""Login throttling per account and per client IP (app/core/rate_limit.py)."""

import time

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.core.config import settings
from app.core.rate_limit import client_ip, login_limiter
from app.main import app
from tests.helpers import PASSWORD, register

ACCOUNT_LIMIT = 3
IP_LIMIT = 5


@pytest.fixture(autouse=True)
def small_limits():
    """Small limits for these tests; restored (and counters cleared) afterwards."""
    saved = {
        k: getattr(settings, k)
        for k in (
            "login_max_failures_per_account",
            "login_max_failures_per_ip",
            "login_failure_window_seconds",
            "trusted_client_ip_header",
        )
    }
    settings.login_max_failures_per_account = ACCOUNT_LIMIT
    settings.login_max_failures_per_ip = IP_LIMIT
    settings.login_failure_window_seconds = 60
    login_limiter.configure()
    yield
    for k, v in saved.items():
        setattr(settings, k, v)
    login_limiter.configure()


def client_from(ip: str) -> TestClient:
    return TestClient(app, client=(ip, 50000))


def attempt(c, email, password="wrong-password-1", headers=None):
    return c.post("/auth/login", json={"email": email, "password": password}, headers=headers or {})


def test_successful_login_is_unaffected(client):
    register(client, "ok@x.example.com")
    for _ in range(ACCOUNT_LIMIT + 2):
        r = attempt(client, "ok@x.example.com", PASSWORD)
        assert r.status_code == 200 and "access_token" in r.json()
        assert "retry-after" not in r.headers


def test_repeated_failures_lock_the_account(client):
    register(client, "victim@x.example.com")
    for _ in range(ACCOUNT_LIMIT):
        assert attempt(client, "victim@x.example.com").status_code == 401
    r = attempt(client, "victim@x.example.com")
    assert r.status_code == 429
    assert "Too many failed sign-in attempts" in r.json()["detail"]
    assert 1 <= int(r.headers["retry-after"]) <= 60
    # Even the right password is refused while locked (otherwise guessing continues).
    assert attempt(client, "victim@x.example.com", PASSWORD).status_code == 429
    # Case and whitespace variants are the same account.
    assert attempt(client, "  VICTIM@x.example.com ", PASSWORD).status_code == 429


def test_unknown_email_behaves_the_same(client):
    """No account enumeration: an unregistered email is throttled identically."""
    register(client, "real@x.example.com")
    with client_from("81.2.69.11") as a, client_from("81.2.69.12") as b:  # separate IP budgets
        real = [attempt(a, "real@x.example.com").status_code for _ in range(ACCOUNT_LIMIT + 1)]
        ghost = [attempt(b, "ghost@x.example.com").status_code for _ in range(ACCOUNT_LIMIT + 1)]
        assert real == ghost == [401] * ACCOUNT_LIMIT + [429]
        assert attempt(a, "real@x.example.com").json() == attempt(b, "ghost@x.example.com").json()


def test_account_limit_applies_across_ips():
    for i in range(ACCOUNT_LIMIT):
        with client_from(f"81.2.69.{i + 1}") as c:
            assert attempt(c, "target@x.example.com").status_code == 401
    with client_from("41.186.0.77") as c:
        assert attempt(c, "target@x.example.com").status_code == 429


def test_ip_limit_across_many_accounts(client):
    register(client, "innocent@x.example.com")
    with client_from("81.2.69.50") as attacker:
        # Spread below the per-account limit, but over the per-IP limit.
        for i in range(IP_LIMIT):
            assert attempt(attacker, f"spray{i}@x.example.com").status_code == 401
        assert attempt(attacker, "fresh@x.example.com").status_code == 429
        # The block is per IP: this IP cannot sign in to any account for now...
        assert attempt(attacker, "innocent@x.example.com", PASSWORD).status_code == 429
    # ...while other clients are unaffected.
    with client_from("41.186.0.20") as other:
        assert attempt(other, "innocent@x.example.com", PASSWORD).status_code == 200


def test_success_clears_account_counter_but_not_ip(client):
    register(client, "forgetful@x.example.com")
    with client_from("81.2.69.60") as c:
        for _ in range(ACCOUNT_LIMIT - 1):
            assert attempt(c, "forgetful@x.example.com").status_code == 401
        assert attempt(c, "forgetful@x.example.com", PASSWORD).status_code == 200
        # The account budget is fresh again...
        for _ in range(ACCOUNT_LIMIT - 1):
            assert attempt(c, "forgetful@x.example.com").status_code == 401
        assert attempt(c, "forgetful@x.example.com", PASSWORD).status_code == 200
        # ...but the IP counter kept all 4 failures; one more reaches IP_LIMIT (5).
        assert attempt(c, "someone-else@x.example.com").status_code == 401
        assert attempt(c, "forgetful@x.example.com", PASSWORD).status_code == 429


def test_limit_expires(client):
    settings.login_failure_window_seconds = 1
    login_limiter.configure()
    register(client, "patient@x.example.com")
    for _ in range(ACCOUNT_LIMIT):
        attempt(client, "patient@x.example.com")
    assert attempt(client, "patient@x.example.com", PASSWORD).status_code == 429
    time.sleep(1.3)
    assert attempt(client, "patient@x.example.com", PASSWORD).status_code == 200


def test_forged_x_forwarded_for_does_not_evade_ip_limit():
    with client_from("81.2.69.70") as c:
        for i in range(IP_LIMIT):
            r = attempt(c, f"s{i}@x.example.com", headers={"X-Forwarded-For": f"10.9.8.{i}"})
            assert r.status_code == 401
        assert attempt(c, "s9@x.example.com", headers={"X-Forwarded-For": "1.2.3.4"}).status_code == 429


def test_trusted_header_identifies_clients_behind_a_proxy():
    settings.trusted_client_ip_header = "True-Client-IP"
    with client_from("10.21.157.68") as proxy:  # Render's private proxy address
        for i in range(IP_LIMIT):
            r = attempt(proxy, f"p{i}@x.example.com", headers={"True-Client-IP": "81.2.69.80"})
            assert r.status_code == 401
        assert attempt(proxy, "p9@x.example.com", headers={"True-Client-IP": "81.2.69.80"}).status_code == 429
        # A different real client behind the same proxy is not blocked.
        assert (
            attempt(proxy, "p9@x.example.com", headers={"True-Client-IP": "41.186.0.81"}).status_code == 401
        )


def test_private_proxy_peer_without_header_skips_ip_limit():
    """Without a trusted header, all Render traffic comes from a private proxy
    address. Counting it as one IP would let one attacker lock out everyone,
    so the IP limit is skipped and only the per-account limit applies."""
    with client_from("10.21.157.68") as proxy:
        for i in range(IP_LIMIT + 3):
            assert attempt(proxy, f"q{i}@x.example.com").status_code == 401
        for _ in range(ACCOUNT_LIMIT):
            attempt(proxy, "q-target@x.example.com")
        assert attempt(proxy, "q-target@x.example.com").status_code == 429


def _request(peer, headers=None):
    scope = {
        "type": "http",
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        "client": (peer, 1234) if peer else None,
    }
    return Request(scope)


@pytest.mark.parametrize(
    ("header_setting", "peer", "headers", "expected"),
    [
        (None, "81.2.69.9", {}, "81.2.69.9"),
        (None, "81.2.69.9", {"X-Forwarded-For": "1.1.1.1"}, "81.2.69.9"),
        (None, "10.0.0.5", {}, None),
        (None, "127.0.0.1", {}, None),
        (None, None, {}, None),
        ("True-Client-IP", "10.0.0.5", {"True-Client-IP": "41.186.0.4"}, "41.186.0.4"),
        ("True-Client-IP", "10.0.0.5", {"True-Client-IP": "not-an-ip"}, None),
        ("True-Client-IP", "10.0.0.5", {}, None),
        ("True-Client-IP", "81.2.69.9", {"True-Client-IP": "2001:db8::1"}, "2001:db8::1"),
    ],
)
def test_client_ip(header_setting, peer, headers, expected):
    settings.trusted_client_ip_header = header_setting
    assert client_ip(_request(peer, headers)) == expected
