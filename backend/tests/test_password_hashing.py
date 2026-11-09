"""Password hashing configuration and the upgrade of non-current hashes at sign-in."""

from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from sqlalchemy import text

from app.core import security
from app.core.database import engine
from app.core.security import hash_password, verify_password
from tests.helpers import PASSWORD, register

# The cheaper parameters that were briefly in use (OWASP minimum: 19 MiB, t=2, p=1).
CHEAP = PasswordHash((Argon2Hasher(time_cost=2, memory_cost=19456, parallelism=1),))
CURRENT_PREFIX = "$argon2id$v=19$m=65536,t=3,p=4$"


def _stored_hash(email):
    with engine.connect() as c:
        return c.execute(text("SELECT password_hash FROM app_user WHERE email = :e"), {"e": email}).scalar_one()


def test_configuration_is_pwdlib_recommended():
    # Exactly one hasher: Argon2 with argon2-cffi's default parameters.
    hashers = security.password_hash.hashers
    assert len(hashers) == 1 and isinstance(hashers[0], Argon2Hasher)
    assert hash_password("x" * 12).startswith(CURRENT_PREFIX)
    assert PasswordHash.recommended().hash("x" * 12).split("$")[3] == hash_password("x" * 12).split("$")[3]


def test_new_hashes_verify():
    h = hash_password("a long enough password")
    assert h.startswith(CURRENT_PREFIX)
    assert verify_password("a long enough password", h)
    assert not verify_password("wrong password", h)


def test_registration_stores_a_current_hash(client):
    email = "hash-new@x.example.com"
    register(client, email)
    assert _stored_hash(email).startswith(CURRENT_PREFIX)


def test_cheaper_hash_still_signs_in_and_is_upgraded(client):
    email = "cheap@x.example.com"
    register(client, email)
    with engine.begin() as c:
        c.execute(text("UPDATE app_user SET password_hash = :h WHERE email = :e"),
                  {"h": CHEAP.hash(PASSWORD), "e": email})
    assert _stored_hash(email).startswith("$argon2id$v=19$m=19456,t=2,p=1$")

    r = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    upgraded = _stored_hash(email)
    assert upgraded.startswith(CURRENT_PREFIX)
    assert verify_password(PASSWORD, upgraded)

    # Signing in again works and leaves the (now current) hash alone.
    assert client.post("/auth/login", json={"email": email, "password": PASSWORD}).status_code == 200
    assert _stored_hash(email) == upgraded


def test_wrong_password_does_not_touch_a_cheaper_hash(client):
    email = "cheap2@x.example.com"
    register(client, email)
    cheap = CHEAP.hash(PASSWORD)
    with engine.begin() as c:
        c.execute(text("UPDATE app_user SET password_hash = :h WHERE email = :e"), {"h": cheap, "e": email})
    assert client.post("/auth/login", json={"email": email, "password": "not the password"}).status_code == 401
    assert _stored_hash(email) == cheap
