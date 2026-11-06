"""Phone number validation and normalization (E.164).

Uses ``phonenumbers`` (the Python port of Google's libphonenumber), so other
countries can be enabled through PHONE_ALLOWED_REGIONS without code changes.
Rwanda (RW, +250) is the default region: local formats such as 0788 123 456,
788123456, 250788123456 and +250 788 123 456 all normalize to +250788123456.

For SMS verification only mobile numbers are accepted.
"""

import re

import phonenumbers
from phonenumbers import NumberParseException, PhoneNumberType

from app.core.config import settings

# Digits, spaces and common separators only. phonenumbers would otherwise turn
# letters into keypad digits ("0788 abc 456" -> +250788222456).
_ALLOWED_CHARACTERS = re.compile(r"^\+?[0-9 ()./\-]+$")
_MOBILE_TYPES = {PhoneNumberType.MOBILE, PhoneNumberType.FIXED_LINE_OR_MOBILE}


class PhoneNumberError(ValueError):
    """A user-facing explanation of why a phone number was rejected."""


def normalize_phone(raw: str, *, mobile_only: bool = True) -> str:
    """Return the number in E.164 format, or raise PhoneNumberError."""
    text = (raw or "").strip()
    if not text:
        raise PhoneNumberError("Enter a phone number.")
    if len(text) > 30 or not _ALLOWED_CHARACTERS.match(text):
        raise PhoneNumberError(
            "Phone numbers may contain only digits, spaces, '+', '-', '.', '/' and brackets."
        )
    digits = re.sub(r"\D", "", text)
    # "250788123456" (country code without the plus) is common in Rwanda.
    if not text.startswith("+") and digits.startswith("250") and len(digits) == 12:
        text = "+" + digits
    try:
        number = phonenumbers.parse(text, settings.phone_default_region)
    except NumberParseException:
        raise PhoneNumberError("This is not a valid phone number.") from None
    if not phonenumbers.is_valid_number(number):
        raise PhoneNumberError("This is not a valid phone number. Check the number of digits.")
    region = phonenumbers.region_code_for_number(number)
    if region not in settings.phone_allowed_regions:
        allowed = ", ".join(settings.phone_allowed_regions)
        raise PhoneNumberError(f"Only phone numbers from these countries are supported: {allowed}.")
    if mobile_only and phonenumbers.number_type(number) not in _MOBILE_TYPES:
        raise PhoneNumberError("Enter a mobile phone number that can receive SMS.")
    return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)


def mask_phone(e164: str) -> str:
    """+250788123456 -> +250 7** *** 456 (safe for responses and logs)."""
    if not e164 or len(e164) < 8:
        return "***"
    return f"{e164[:5]}{'*' * (len(e164) - 8)}{e164[-3:]}"
