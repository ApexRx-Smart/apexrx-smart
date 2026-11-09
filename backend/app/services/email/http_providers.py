"""Email provider adapters over HTTPS (no SMTP: Render's free plan blocks it).

Both read their credentials from settings, send one message per call, and raise
EmailDeliveryError on anything but a success response. API keys are never
logged; failures are reported with the provider's HTTP status only.
"""

import httpx

from app.core.config import settings
from app.services.email import EmailDeliveryError, EmailMessage, EmailNotConfigured, EmailResult


def _sender() -> tuple[str, str]:
    if not settings.email_from_address:
        raise EmailNotConfigured("EMAIL_FROM_ADDRESS is not set.")
    return settings.email_from_name, settings.email_from_address


def _secret(value) -> str | None:
    return value.get_secret_value() if value is not None and value.get_secret_value() else None


def _post(provider: str, url: str, headers: dict, body: dict) -> dict:
    try:
        response = httpx.post(url, headers=headers, json=body, timeout=settings.email_timeout_seconds)
    except httpx.HTTPError as exc:
        raise EmailDeliveryError(f"{provider}: {type(exc).__name__}") from None
    if response.status_code >= 300:
        raise EmailDeliveryError(f"{provider}: HTTP {response.status_code}")
    try:
        return response.json() or {}
    except ValueError:
        return {}


class ResendProvider:
    """https://resend.com/docs/api-reference/emails/send-email"""

    name = "resend"
    url = "https://api.resend.com/emails"

    def __init__(self, api_key: str, sender_name: str, sender_address: str):
        self._api_key = api_key
        self._from = f"{sender_name} <{sender_address}>"

    @classmethod
    def from_settings(cls) -> "ResendProvider":
        key = _secret(settings.resend_api_key)
        if not key:
            raise EmailNotConfigured("RESEND_API_KEY is not set.")
        return cls(key, *_sender())

    def send(self, message: EmailMessage) -> EmailResult:
        data = _post(
            self.name,
            self.url,
            {"Authorization": f"Bearer {self._api_key}"},
            {
                "from": self._from,
                "to": [message.to],
                "subject": message.subject,
                "text": message.text,
                "html": message.html,
            },
        )
        return EmailResult(provider=self.name, message_id=data.get("id"))


class BrevoProvider:
    """https://developers.brevo.com/reference/sendtransacemail"""

    name = "brevo"
    url = "https://api.brevo.com/v3/smtp/email"

    def __init__(self, api_key: str, sender_name: str, sender_address: str):
        self._api_key = api_key
        self._sender = {"name": sender_name, "email": sender_address}

    @classmethod
    def from_settings(cls) -> "BrevoProvider":
        key = _secret(settings.brevo_api_key)
        if not key:
            raise EmailNotConfigured("BREVO_API_KEY is not set.")
        return cls(key, *_sender())

    def send(self, message: EmailMessage) -> EmailResult:
        data = _post(
            self.name,
            self.url,
            {"api-key": self._api_key, "accept": "application/json"},
            {
                "sender": self._sender,
                "to": [{"email": message.to}],
                "subject": message.subject,
                "textContent": message.text,
                "htmlContent": message.html,
            },
        )
        return EmailResult(provider=self.name, message_id=data.get("messageId"))
