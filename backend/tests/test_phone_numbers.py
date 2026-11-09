"""Phone normalization (app/services/phone.py). Phone numbers are business
contact details (and future Mobile Money); they are not used for verification."""

import pytest

from app.core.config import settings
from app.services.phone import PhoneNumberError, mask_phone, normalize_phone


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
