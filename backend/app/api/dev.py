"""Development/test-only helpers. NEVER available in production.

Two independent guards:
  * app/main.py only mounts this router when APP_ENV is not "production";
  * every request checks APP_ENV again and answers 404 in production.
The mock email provider is itself refused in production.
"""

import re

from fastapi import APIRouter

from app.api.deps import CurrentUser
from app.core.config import settings
from app.core.errors import NotFound
from app.services.email import EmailNotConfigured, get_email_provider
from app.services.email.mock import MockEmailProvider

router = APIRouter()

_LINK = re.compile(r"https?://\S+/verify-email\.html\S*#token=([A-Za-z0-9_-]+)")


@router.get("/email/latest")
def latest_test_email(user: CurrentUser):
    """The latest mock email sent to the signed-in user's address, including
    the verification link. Only with the mock provider, never in production."""
    if settings.is_production:
        raise NotFound("Not found.")
    try:
        provider = get_email_provider()
    except EmailNotConfigured:
        raise NotFound("No test email available.") from None
    if not isinstance(provider, MockEmailProvider):
        raise NotFound("No test email available (not using the mock provider).")
    item = provider.latest(user.email)
    if item is None:
        raise NotFound("No test email has been sent to your address yet.")
    found = _LINK.search(item.message.text)
    return {
        "to": item.message.to,
        "subject": item.message.subject,
        "text": item.message.text,
        "link": found.group(0) if found else None,
        "token": found.group(1) if found else None,
        "sent_at": item.sent_at,
    }
