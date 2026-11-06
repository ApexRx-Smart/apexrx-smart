"""Provider-independent SMS sending.

Business logic (app/services/otp.py) only calls ``get_sms_provider().send()``.
Each provider is an adapter implementing ``SmsProvider``; the one used is
chosen by the SMS_PROVIDER setting through ``PROVIDERS``.

Adding a real provider (see the root README, "Phone verification"):
  1. Create app/services/sms/<name>.py with a class implementing
     ``send(to, message)`` that calls the provider's API and raises
     ``SmsDeliveryError`` on any failure (never returns silently).
  2. Read its credentials from settings/environment inside the adapter.
  3. Register a factory in ``PROVIDERS`` below, then set SMS_PROVIDER=<name>.

Rules enforced here:
  * No provider configured -> ``SmsNotConfigured`` (the API answers 503).
  * The mock provider is refused in production.
  * A failed delivery is never retried through another provider or the mock.
"""

import logging
from dataclasses import dataclass
from typing import Callable, Protocol

from app.core.config import settings

logger = logging.getLogger("apexrx.sms")


class SmsError(Exception):
    pass


class SmsNotConfigured(SmsError):
    """No usable SMS provider (unset, unknown, or mock in production)."""


class SmsDeliveryError(SmsError):
    """The provider did not accept the message."""


@dataclass(frozen=True)
class SmsResult:
    provider: str
    message_id: str | None = None


class SmsProvider(Protocol):
    name: str

    def send(self, to: str, message: str) -> SmsResult:
        """Send ``message`` to the E.164 number ``to``. Raise SmsDeliveryError on failure."""
        ...


def _mock_factory() -> SmsProvider:
    from app.services.sms.mock import mock_provider

    return mock_provider


# name -> factory. Real adapters are registered here when a provider is chosen.
PROVIDERS: dict[str, Callable[[], SmsProvider]] = {
    "mock": _mock_factory,
}

_override: SmsProvider | None = None


def set_sms_provider(provider: SmsProvider | None) -> None:
    """Replace the provider (tests). ``None`` restores the configured one."""
    global _override
    _override = provider


def get_sms_provider() -> SmsProvider:
    if _override is not None:
        return _override
    name = settings.sms_provider
    if not name:
        raise SmsNotConfigured("SMS_PROVIDER is not set.")
    if name == "mock" and settings.is_production:
        raise SmsNotConfigured("The mock SMS provider cannot be used in production.")
    factory = PROVIDERS.get(name)
    if factory is None:
        raise SmsNotConfigured(f"Unknown SMS_PROVIDER '{name}'.")
    return factory()


def sms_configuration_problem() -> str | None:
    """Why SMS is unusable with the current settings, or None if it is usable."""
    try:
        get_sms_provider()
    except SmsNotConfigured as exc:
        return str(exc)
    return None
