"""Notification emails sent after the response (FastAPI background tasks).

They open their own database session (the request's is closed by then), never
raise, and log failures without addresses or links."""

import logging

from app.core.database import SessionLocal
from app.models import User
from app.services.email import get_email_provider, templates

logger = logging.getLogger("apexrx.email")


def send_password_changed(user_id: int) -> None:
    try:
        with SessionLocal() as db:
            user = db.get(User, user_id)
            if user is None:
                return
            message = templates.password_changed(to=user.email, name=user.name)
        get_email_provider().send(message)
    except Exception as exc:  # noqa: BLE001 - a notification must never break anything
        logger.warning("Password-changed email for user %s not sent: %s", user_id, type(exc).__name__)
