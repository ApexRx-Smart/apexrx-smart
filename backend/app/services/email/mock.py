"""Mock email provider for development and tests.

It sends nothing. Messages are kept in a small in-memory outbox (never in the
database or logs) so a developer can open a test verification link through the
development-only endpoint GET /dev/email/latest. It is refused in production
(see app/services/email/__init__.py), so it can never stand in for real
verification on the hosted service.
"""

import secrets
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.services.email import EmailDeliveryError, EmailMessage, EmailResult

OUTBOX_SIZE = 200


@dataclass(frozen=True)
class MockEmail:
    message: EmailMessage
    message_id: str
    sent_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class MockEmailProvider:
    name = "mock"

    def __init__(self) -> None:
        self._outbox: deque[MockEmail] = deque(maxlen=OUTBOX_SIZE)
        self._lock = threading.Lock()
        # Tests set this to simulate a provider outage.
        self.fail_with: str | None = None

    def send(self, message: EmailMessage) -> EmailResult:
        if self.fail_with:
            raise EmailDeliveryError(self.fail_with)
        item = MockEmail(message=message, message_id=f"mock-{secrets.token_hex(6)}")
        with self._lock:
            self._outbox.append(item)
        return EmailResult(provider=self.name, message_id=item.message_id)

    def latest(self, to: str) -> MockEmail | None:
        to = to.strip().lower()
        with self._lock:
            for item in reversed(self._outbox):
                if item.message.to.strip().lower() == to:
                    return item
        return None

    def messages(self) -> list[MockEmail]:
        with self._lock:
            return list(self._outbox)

    def reset(self) -> None:
        with self._lock:
            self._outbox.clear()
        self.fail_with = None


mock_provider = MockEmailProvider()
