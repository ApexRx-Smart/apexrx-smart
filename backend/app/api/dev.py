"""Development/test-only helpers. NEVER available in production.

Two independent guards:
  * app/main.py only mounts this router when APP_ENV is not "production";
  * every request checks APP_ENV again and answers 404 in production.
"""

import re

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.config import settings
from app.core.errors import NotFound
from app.models import PhoneVerification
from app.services.sms import SmsNotConfigured, get_sms_provider
from app.services.sms.mock import MockSmsProvider

router = APIRouter()


@router.get("/sms/latest")
def latest_test_sms(user: CurrentUser, db: DbSession):
    """The latest mock SMS sent to the signed-in user's most recent number,
    including the test code. Only with the mock provider, never in production."""
    if settings.is_production:
        raise NotFound("Not found.")
    try:
        provider = get_sms_provider()
    except SmsNotConfigured:
        raise NotFound("No test SMS available.") from None
    if not isinstance(provider, MockSmsProvider):
        raise NotFound("No test SMS available (not using the mock provider).")
    phone = db.scalar(
        select(PhoneVerification.phone_e164)
        .where(PhoneVerification.user_id == user.user_id)
        .order_by(PhoneVerification.created_at.desc())
        .limit(1)
    )
    message = provider.latest(phone) if phone else None
    if message is None:
        raise NotFound("No test SMS has been sent to your number yet.")
    found = re.search(r"\b(\d{6})\b", message.message)
    return {
        "to": message.to,
        "message": message.message,
        "code": found.group(1) if found else None,
        "sent_at": message.sent_at,
    }
