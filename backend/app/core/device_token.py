"""Signed "known device" tokens for login lockout protection.

A successful sign-in returns a device token; the browser keeps it and sends
it with later sign-ins for the same account. While someone is hammering an
account with wrong passwords (which locks it for unrecognised browsers), the
owner's usual browser is counted separately and can still sign in. This is
the device-cookie approach from OWASP's brute-force guidance, sent in the
login body because the frontend and API are on different sites.

A device token is NOT a credential: it never signs anyone in by itself (the
password is still required) and it only exempts the holder from the
account-wide lockout, not from its own per-device limit. It is bound to one
user id, expires, and is signed with a key derived from JWT_SECRET_KEY, so
rotating that secret invalidates all device tokens.
"""

import base64
import hashlib
import hmac
import json
import secrets
import time

from app.core.config import settings

MAX_TOKEN_LENGTH = 512
_CONTEXT = b"apexrx-login-device-token-v1"


def _key() -> bytes:
    return hmac.new(settings.jwt_secret_key.encode(), _CONTEXT, hashlib.sha256).digest()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(payload: bytes) -> str:
    return _b64(hmac.new(_key(), payload, hashlib.sha256).digest())


def issue(user_id: int) -> str:
    expires = int(time.time()) + settings.device_token_max_age_days * 86400
    payload = json.dumps(
        {"u": int(user_id), "d": secrets.token_hex(16), "exp": expires}, separators=(",", ":")
    )
    body = _b64(payload.encode())
    return f"{body}.{_sign(body.encode())}"


def device_id_for(token: str | None, user_id: int | None) -> str | None:
    """The device id if ``token`` is a valid, unexpired token for ``user_id``.

    Never raises on client input: any malformed token (including non-ASCII
    characters) is simply not a valid token, so the request falls back to the
    normal per-account limit with the same response as for any other client.
    """
    if not token or user_id is None or len(token) > MAX_TOKEN_LENGTH or token.count(".") != 1:
        return None
    body, signature = token.split(".")
    # Compare bytes: hmac.compare_digest raises TypeError for str arguments
    # containing non-ASCII characters. Bytes comparison stays constant-time.
    expected = _sign(body.encode("utf-8", "surrogatepass"))
    if not hmac.compare_digest(signature.encode("utf-8", "surrogatepass"), expected.encode("ascii")):
        return None
    try:
        data = json.loads(_unb64(body))
        if int(data["u"]) != int(user_id) or int(data["exp"]) < time.time():
            return None
        device = str(data["d"])
    except (ValueError, KeyError, TypeError):
        return None
    return device if len(device) == 32 else None
