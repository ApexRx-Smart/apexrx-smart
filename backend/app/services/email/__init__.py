"""Provider-independent email sending.

Email delivery is TEMPORARILY DISABLED: no real email provider is integrated
(the Gmail API, Resend and Brevo adapters were removed). The workflows that
need email (email verification, password-reset links, invitation emails) call
``get_email_provider()``; while no provider exists they report themselves as
unavailable instead of pretending to send anything:

  * email verification is not required (EMAIL_VERIFICATION_REQUIRED defaults to
    false) and sending a verification link answers 503;
  * "Forgot password?" answers 503 for every address;
  * staff invitations are shared by the inviter as a link (shown once to them),
    never reported as emailed.

Only the in-memory "mock" provider remains, for development and automated tests
of those dormant workflows; it sends nothing and is refused in production.

Re-enabling email later: add an adapter implementing ``EmailProvider`` (for
example ``app/services/email/<name>.py``), register it in ``PROVIDERS``, set
EMAIL_PROVIDER on the server, and send a real test message before relying on it.
"""

import logging
from dataclasses import dataclass
from typing import Callable, Protocol

from app.core.config import settings

logger = logging.getLogger("apexrx.email")


class EmailError(Exception):
    pass


class EmailNotConfigured(EmailError):
    """No usable email provider (unset, unknown, or mock in production)."""


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


# name -> factory. No real provider is registered at the moment.
PROVIDERS: dict[str, Callable[[], EmailProvider]] = {
    "mock": _mock_factory,
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
        raise EmailNotConfigured("Email delivery is not configured.")
    if name == "mock" and settings.is_production:
        raise EmailNotConfigured("The mock email provider cannot be used in production.")
    factory = PROVIDERS.get(name)
    if factory is None:
        raise EmailNotConfigured(f"Unknown EMAIL_PROVIDER '{name}' (no real email provider is integrated).")
    return factory()


def email_configuration_problem() -> str | None:
    """Why email is unusable with the current settings, or None if it is usable."""
    try:
        get_email_provider()
    except EmailNotConfigured as exc:
        return str(exc)
    return None


def email_delivery_available() -> bool:
    return email_configuration_problem() is None
