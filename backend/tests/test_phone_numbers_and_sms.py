"""Phone normalization (app/services/phone.py) and the SMS provider layer
(app/services/sms)."""

import pytest

from app.core.config import settings
from app.services import sms
from app.services.phone import PhoneNumberError, mask_phone, normalize_phone
from app.services.sms import PROVIDERS, SmsDeliveryError, SmsNotConfigured, SmsResult, get_sms_provider
from app.services.sms.mock import MockSmsProvider, mock_provider


# ---------------------------------------------------------------------------
# Phone numbers
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "raw",
    [
        "0788123456",
        "788123456",
        "+250788123456",
        "250788123456",
        "+250 788 123 456",
        "0788 123 456",
        "(078) 812-3456",
        "078.812.3456",
        " +250-788-123-456 ",
    ],
)
def test_rwandan_formats_normalize_to_e164(raw):
    assert normalize_phone(raw) == "+250788123456"


@pytest.mark.parametrize("raw", ["0728123456", "0738123456", "0798123456"])
def test_other_rwandan_mobile_prefixes(raw):
    assert normalize_phone(raw) == "+250" + raw[1:]


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("", "Enter a phone number"),
        ("   ", "Enter a phone number"),
        ("0788 abc 456", "only digits"),  # letters would otherwise become keypad digits
        ("+250788123456; DROP", "only digits"),
        ("0788123", "not a valid phone number"),
        ("07881234567", "not a valid phone number"),
        ("0700000000", "not a valid phone number"),
        ("+250700000101", "not a valid phone number"),
        ("+254712345678", "Only phone numbers from these countries"),
        ("+12025550123", "Only phone numbers from these countries"),
        ("0" * 31, "only digits"),
        ("0252123456", "mobile phone number"),  # Rwandan landline: no SMS
    ],
)
def test_invalid_numbers_are_rejected_with_clear_messages(raw, message):
    with pytest.raises(PhoneNumberError) as info:
        normalize_phone(raw)
    assert message in str(info.value)


def test_landline_allowed_when_mobile_not_required():
    assert normalize_phone("0252123456", mobile_only=False) == "+250252123456"


def test_other_countries_can_be_enabled(monkeypatch):
    monkeypatch.setattr(settings, "phone_allowed_regions", ["RW", "KE"])
    assert normalize_phone("+254712345678") == "+254712345678"
    assert normalize_phone("0788123456") == "+250788123456"  # default region still RW


def test_mask_phone():
    assert mask_phone("+250788123456") == "+2507*****456"
    assert "788123" not in mask_phone("+250788123456")


# ---------------------------------------------------------------------------
# SMS providers
# ---------------------------------------------------------------------------
def test_mock_provider_records_messages():
    result = mock_provider.send("+250788123456", "hello 123456")
    assert isinstance(result, SmsResult) and result.provider == "mock" and result.message_id
    assert mock_provider.latest("+250788123456").message == "hello 123456"
    assert mock_provider.latest("+250788999999") is None


def test_mock_provider_can_simulate_failure():
    mock_provider.fail_with = "network down"
    with pytest.raises(SmsDeliveryError):
        mock_provider.send("+250788123456", "x")
    assert mock_provider.messages() == []


def test_unset_provider_is_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "sms_provider", None)
    with pytest.raises(SmsNotConfigured, match="not set"):
        get_sms_provider()
    assert sms.sms_configuration_problem() == "SMS_PROVIDER is not set."


def test_unknown_provider_is_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "sms_provider", "carrier-pigeon")
    with pytest.raises(SmsNotConfigured, match="Unknown SMS_PROVIDER"):
        get_sms_provider()


def test_mock_provider_is_refused_in_production(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "sms_provider", "mock")
    with pytest.raises(SmsNotConfigured, match="cannot be used in production"):
        get_sms_provider()


@pytest.mark.parametrize("env", ["development", "test"])
def test_mock_provider_allowed_outside_production(monkeypatch, env):
    monkeypatch.setattr(settings, "app_env", env)
    monkeypatch.setattr(settings, "sms_provider", "mock")
    assert isinstance(get_sms_provider(), MockSmsProvider)


class RecordingAdapter:
    """Shape of a real adapter: send() or raise SmsDeliveryError."""

    name = "example"

    def __init__(self):
        self.sent = []

    def send(self, to, message):
        self.sent.append((to, message))
        return SmsResult(provider=self.name, message_id="ex-1")


def test_new_adapters_are_selected_through_the_registry(monkeypatch):
    adapter = RecordingAdapter()
    monkeypatch.setitem(PROVIDERS, "example", lambda: adapter)
    monkeypatch.setattr(settings, "app_env", "production")  # real adapters work in production
    monkeypatch.setattr(settings, "sms_provider", "example")
    assert get_sms_provider() is adapter
