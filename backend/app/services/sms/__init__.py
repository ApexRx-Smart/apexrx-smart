"""Provider-independent SMS delivery.

The OTP service (app/services/otp.py) only calls ``get_sms_provider().send()``.
Providers only DELIVER messages: they never generate, store or check codes.

* ``esms``: eSMS Africa (app/services/sms/esms.py). Sandbox or live is decided
  by ESMS_MODE and the key; switching to live is a configuration change only.
* ``mock``: development and tests. Messages stay in memory; refused in production.

Rules enforced here:
  * No usable provider -> ``SmsNotConfigured`` (the API answers 503).
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
    """No usable SMS provider (unset, unknown, missing key, or mock in production)."""


class SmsDeliveryError(SmsError):
    """The provider did not take the message. ``reason`` is a short code safe to
    log (never message text or credentials). ``number_rejected`` is true when the
    provider refused the recipient number itself, which the user can fix."""

    def __init__(self, reason: str, *, number_rejected: bool = False) -> None:
        super().__init__(reason)
        self.reason = reason
        self.number_rejected = number_rejected


@dataclass(frozen=True)
class SmsResult:
    provider: str
    message_id: str | None = None
    status: str | None = None
    # "test" for sandbox sends (nothing reaches a phone), "live" otherwise.
    environment: str | None = None


class SmsProvider(Protocol):
    name: str

    def send(self, to: str, message: str, *, idempotency_key: str) -> SmsResult:
        """Send ``message`` to the E.164 number ``to``. Raise SmsDeliveryError on
        any failure; never return without the provider having accepted it."""
        ...


def _mock_factory() -> SmsProvider:
    from app.services.sms.mock import mock_provider

    return mock_provider


def _esms_factory() -> SmsProvider:
    from app.services.sms.esms import EsmsProvider

    return EsmsProvider.from_settings()


PROVIDERS: dict[str, Callable[[], SmsProvider]] = {
    "mock": _mock_factory,
    "esms": _esms_factory,
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
    """Why SMS codes cannot be sent with the current settings, or None."""
    if settings.otp_hmac_secret is None:
        return "OTP_HMAC_SECRET is not set."
    try:
        get_sms_provider()
    except SmsNotConfigured as exc:
        return str(exc)
    return None


def sms_is_sandbox() -> bool:
    """True when codes are only simulated (eSMS test key): nothing reaches a phone."""
    return settings.sms_provider == "esms" and settings.esms_mode == "sandbox"
