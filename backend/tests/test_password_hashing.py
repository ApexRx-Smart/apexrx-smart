"""Password hashing parameters and the upgrade of older hashes at sign-in."""

from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from sqlalchemy import text

from app.core.database import engine
from app.core.security import hash_password, verify_password
from tests.helpers import PASSWORD, register

# pwdlib's default ("recommended") parameters, used before this change.
LEGACY = PasswordHash((Argon2Hasher(),))


def _stored_hash(email):
    with engine.connect() as c:
        return c.execute(text("SELECT password_hash FROM app_user WHERE email = :e"), {"e": email}).scalar_one()


def test_new_hashes_use_owasp_argon2id_parameters():
    h = hash_password("a long enough password")
    assert h.startswith("$argon2id$v=19$m=19456,t=2,p=1$")
    assert verify_password("a long enough password", h)
    assert not verify_password("wrong password", h)


def test_legacy_hash_still_signs_in_and_is_upgraded(client):
    email = "legacy@x.example.com"
    register(client, email)
    with engine.begin() as c:
        c.execute(text("UPDATE app_user SET password_hash = :h WHERE email = :e"),
                  {"h": LEGACY.hash(PASSWORD), "e": email})
    assert _stored_hash(email).startswith("$argon2id$v=19$m=65536,t=3,p=4$")

    r = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    upgraded = _stored_hash(email)
    assert upgraded.startswith("$argon2id$v=19$m=19456,t=2,p=1$")
    assert verify_password(PASSWORD, upgraded)

    # Signing in again works and leaves the (now current) hash alone.
    assert client.post("/auth/login", json={"email": email, "password": PASSWORD}).status_code == 200
    assert _stored_hash(email) == upgraded


def test_wrong_password_does_not_touch_a_legacy_hash(client):
    email = "legacy2@x.example.com"
    register(client, email)
    legacy = LEGACY.hash(PASSWORD)
    with engine.begin() as c:
        c.execute(text("UPDATE app_user SET password_hash = :h WHERE email = :e"), {"h": legacy, "e": email})
    assert client.post("/auth/login", json={"email": email, "password": "not the password"}).status_code == 401
    assert _stored_hash(email) == legacy
