"""Gmail API email adapter (EMAIL_PROVIDER=gmail).

Sends from the dedicated ApexRX Gmail account over HTTPS (Render's free plan
blocks SMTP ports), with OAuth 2.0 and only the
``https://www.googleapis.com/auth/gmail.send`` scope. The account's password
is never used.

Credentials (environment only, never in the repository or the frontend):
  GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET  - the Google Cloud OAuth client
  GMAIL_REFRESH_TOKEN                   - from python -m app.scripts.gmail_authorize
  EMAIL_FROM_ADDRESS                    - the Gmail address itself

A short-lived access token is obtained from the refresh token
(https://oauth2.googleapis.com/token) and cached in memory until shortly before
it expires; a 401 from Gmail refreshes it once and retries. Messages go to
POST https://gmail.googleapis.com/gmail/v1/users/me/messages/send as a
base64url RFC 822 message. Any failure raises EmailDeliveryError with the HTTP
status and Google's error code only (never tokens or secrets), so nothing is
reported as sent unless Gmail accepted it.
"""

import base64
import threading
import time
from email.message import EmailMessage as MimeMessage
from email.utils import formataddr, make_msgid

import httpx

from app.core.config import settings
from app.services.email import EmailDeliveryError, EmailMessage, EmailNotConfigured, EmailResult

TOKEN_URL = "https://oauth2.googleapis.com/token"
SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
SCOPE = "https://www.googleapis.com/auth/gmail.send"


def _secret(value) -> str | None:
    return value.get_secret_value() if value is not None and value.get_secret_value() else None


def _google_error(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return ""
    err = data.get("error")
    if isinstance(err, dict):  # Gmail API: {"error": {"code", "status", ...}}
        return str(err.get("status") or err.get("code") or "")
    return str(err or "")  # token endpoint: {"error": "invalid_grant", ...}


class GmailProvider:
    name = "gmail"

    def __init__(self, client_id: str, client_secret: str, refresh_token: str, sender_name: str, sender: str):
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._sender_name = sender_name
        self._sender = sender
        self._lock = threading.Lock()
        self._access_token: str | None = None
        self._expires_at = 0.0

    @classmethod
    def from_settings(cls) -> "GmailProvider":
        missing = [name for name, value in (
            ("GMAIL_CLIENT_ID", settings.gmail_client_id),
            ("GMAIL_CLIENT_SECRET", _secret(settings.gmail_client_secret)),
            ("GMAIL_REFRESH_TOKEN", _secret(settings.gmail_refresh_token)),
            ("EMAIL_FROM_ADDRESS", settings.email_from_address),
        ) if not value]
        if missing:
            raise EmailNotConfigured(f"{', '.join(missing)} not set for the Gmail provider.")
        return _shared(
            settings.gmail_client_id, _secret(settings.gmail_client_secret),
            _secret(settings.gmail_refresh_token), settings.email_from_name, settings.email_from_address,
        )

    # ---------------------------------------------------------------- tokens
    def _token(self, force: bool = False) -> str:
        with self._lock:
            if not force and self._access_token and time.monotonic() < self._expires_at:
                return self._access_token
            try:
                response = httpx.post(TOKEN_URL, data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "refresh_token": self._refresh_token,
                    "grant_type": "refresh_token",
                }, timeout=settings.email_timeout_seconds)
            except httpx.HTTPError as exc:
                raise EmailDeliveryError(f"gmail: token request failed ({type(exc).__name__})") from None
            if response.status_code != 200:
                code = _google_error(response)
                # invalid_grant: the refresh token was revoked or expired (for
                # example an OAuth consent screen still in "Testing" mode).
                raise EmailDeliveryError(f"gmail: authorization refused (HTTP {response.status_code} {code})".strip())
            data = response.json()
            self._access_token = data["access_token"]
            self._expires_at = time.monotonic() + max(60, int(data.get("expires_in", 3600)) - 120)
            return self._access_token

    # ------------------------------------------------------------------ send
    def _mime(self, message: EmailMessage) -> str:
        mime = MimeMessage()
        mime["To"] = message.to
        mime["From"] = formataddr((self._sender_name, self._sender))
        mime["Subject"] = message.subject
        mime["Message-ID"] = make_msgid(domain=self._sender.split("@")[-1])
        mime.set_content(message.text)
        mime.add_alternative(message.html, subtype="html")
        return base64.urlsafe_b64encode(mime.as_bytes()).decode()

    def send(self, message: EmailMessage) -> EmailResult:
        body = {"raw": self._mime(message)}
        for attempt in (1, 2):
            token = self._token(force=attempt == 2)
            try:
                response = httpx.post(SEND_URL, json=body, headers={"Authorization": f"Bearer {token}"},
                                      timeout=settings.email_timeout_seconds)
            except httpx.HTTPError as exc:
                raise EmailDeliveryError(f"gmail: send failed ({type(exc).__name__})") from None
            if response.status_code == 401 and attempt == 1:
                continue  # access token expired or revoked: refresh once and retry
            if response.status_code >= 300:
                raise EmailDeliveryError(f"gmail: HTTP {response.status_code} {_google_error(response)}".strip())
            return EmailResult(provider=self.name, message_id=(response.json() or {}).get("id"))
        raise EmailDeliveryError("gmail: unauthorized")


# One provider per configuration, so the access token is reused between messages.
_instances: dict[tuple, GmailProvider] = {}
_instances_lock = threading.Lock()


def _shared(*config) -> GmailProvider:
    with _instances_lock:
        if config not in _instances:
            _instances.clear()
            _instances[config] = GmailProvider(*config)
        return _instances[config]
