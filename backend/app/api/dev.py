"""Development/test-only helpers. NEVER available in production.

Two independent guards:
  * app/main.py only mounts this router when APP_ENV is not "production";
  * every request checks APP_ENV again and answers 404 in production.
The mock email provider is itself refused in production.
"""

import re

from fastapi import APIRouter

from app.api.deps import CurrentUser, SignedInUser
from app.core.config import settings
from app.core.errors import NotFound
from app.services.email import EmailNotConfigured, get_email_provider
from app.services.email.mock import MockEmailProvider
from app.services.sms import SmsNotConfigured, get_sms_provider
from app.services.sms.mock import MockSmsProvider

router = APIRouter()

_LINK = re.compile(r"https?://\S+?\.html\S*?#token=([A-Za-z0-9_-]+)")


@router.get("/email/latest")
def latest_test_email(user: CurrentUser):
    """The latest mock email sent to the signed-in user's address, including
    its link (verification, invitation or password reset). Only with the mock
    provider, never in production."""
    if settings.is_production:
        raise NotFound("Not found.")
    try:
        provider = get_email_provider()
    except EmailNotConfigured:
        raise NotFound("No test email available.") from None
    if not isinstance(provider, MockEmailProvider):
        raise NotFound("No test email available (not using the mock provider).")
    return _describe(provider.latest(user.email))


@router.get("/email/latest-to")
def latest_test_email_to(to: str):
    """The latest mock email to any address: for local tests of flows where
    the recipient has no account or session yet (invitations, password reset).
    Development/test only, mock provider only."""
    if settings.is_production:
        raise NotFound("Not found.")
    try:
        provider = get_email_provider()
    except EmailNotConfigured:
        raise NotFound("No test email available.") from None
    if not isinstance(provider, MockEmailProvider):
        raise NotFound("No test email available (not using the mock provider).")
    return _describe(provider.latest(to))


def _describe(item):
    if item is None:
        raise NotFound("No test email has been sent to this address yet.")
    found = _LINK.search(item.message.text)
    return {
        "to": item.message.to,
        "subject": item.message.subject,
        "text": item.message.text,
        "link": found.group(0) if found else None,
        "token": found.group(1) if found else None,
        "sent_at": item.sent_at,
    }


_SMS_CODE = re.compile(r"\b(\d{6})\b")


@router.get("/sms/latest")
def latest_test_sms(user: SignedInUser):
    """The latest mock SMS sent to the signed-in user's number, with its code.
    Development/test only, mock provider only (never a real or sandbox SMS)."""
    return _latest_sms(user)


def _latest_sms(user):
    if settings.is_production:
        raise NotFound("Not found.")
    try:
        provider = get_sms_provider()
    except SmsNotConfigured:
        raise NotFound("No test SMS available.") from None
    if not isinstance(provider, MockSmsProvider) or not user.phone:
        raise NotFound("No test SMS available (not using the mock provider).")
    item = provider.latest(user.phone)
    if item is None:
        raise NotFound("No test SMS has been sent to this number yet.")
    found = _SMS_CODE.search(item.message)
    return {"to": item.to, "code": found.group(1) if found else None, "sent_at": item.sent_at}
