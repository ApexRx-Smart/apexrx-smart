"""Provider-independent email sending.

Business logic (app/services/email_verification.py) only calls
``get_email_provider().send()``. Each provider is an adapter implementing
``EmailProvider``; the one used is chosen by the EMAIL_PROVIDER setting
through ``PROVIDERS``.

Providers (HTTPS APIs: Render's free plan blocks outbound SMTP ports):
  * "resend": RESEND_API_KEY, EMAIL_FROM_ADDRESS (on a domain verified in Resend)
  * "brevo":  BREVO_API_KEY,  EMAIL_FROM_ADDRESS (a verified Brevo sender)
  * "mock":   development and tests only. Sends nothing; refused in production.

Rules enforced here:
  * No usable provider -> ``EmailNotConfigured`` (the API answers 503).
  * The mock provider is refused in production.
  * A failed delivery raises ``EmailDeliveryError``; it is never retried
    through another provider or the mock.
"""

import logging
from dataclasses import dataclass
from typing import Callable, Protocol

from app.core.config import settings

logger = logging.getLogger("apexrx.email")


class EmailError(Exception):
    pass


class EmailNotConfigured(EmailError):
    """No usable email provider (unset, unknown, incomplete, or mock in production)."""


class EmailDeliveryError(EmailError):
    """The provider did not accept the message."""


@dataclass(frozen=True)
class EmailMessage:
    to: str
    subject: str
    text: str
    html: str


@dataclass(frozen=True)
class EmailResult:
    provider: str
    message_id: str | None = None


class EmailProvider(Protocol):
    name: str

    def send(self, message: EmailMessage) -> EmailResult:
        """Send ``message``. Raise EmailDeliveryError on any failure."""
        ...


def _mock_factory() -> EmailProvider:
    from app.services.email.mock import mock_provider

    return mock_provider


def _resend_factory() -> EmailProvider:
    from app.services.email.http_providers import ResendProvider

    return ResendProvider.from_settings()


def _brevo_factory() -> EmailProvider:
    from app.services.email.http_providers import BrevoProvider

    return BrevoProvider.from_settings()


PROVIDERS: dict[str, Callable[[], EmailProvider]] = {
    "mock": _mock_factory,
    "resend": _resend_factory,
    "brevo": _brevo_factory,
}

_override: EmailProvider | None = None


def set_email_provider(provider: EmailProvider | None) -> None:
    """Replace the provider (tests). ``None`` restores the configured one."""
    global _override
    _override = provider


def get_email_provider() -> EmailProvider:
    if _override is not None:
        return _override
    name = settings.email_provider
    if not name:
        raise EmailNotConfigured("EMAIL_PROVIDER is not set.")
    if name == "mock" and settings.is_production:
        raise EmailNotConfigured("The mock email provider cannot be used in production.")
    if settings.is_production and not settings.frontend_base_url.startswith("https://"):
        raise EmailNotConfigured("FRONTEND_BASE_URL must use https:// in production.")
    factory = PROVIDERS.get(name)
    if factory is None:
        raise EmailNotConfigured(f"Unknown EMAIL_PROVIDER '{name}'.")
    return factory()


def email_configuration_problem() -> str | None:
    """Why email is unusable with the current settings, or None if it is usable."""
    try:
        get_email_provider()
    except EmailNotConfigured as exc:
        return str(exc)
    return None
