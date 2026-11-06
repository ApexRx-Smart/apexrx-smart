"""Mock SMS provider for development and tests.

It sends nothing. Messages are kept in a small in-memory outbox (never in the
database or logs) so a developer can read a test code through the
development-only endpoint GET /dev/sms/latest. It is refused in production
(see app/services/sms/__init__.py).
"""

import secrets
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.services.sms import SmsDeliveryError, SmsResult

OUTBOX_SIZE = 200


@dataclass(frozen=True)
class MockMessage:
    to: str
    message: str
    message_id: str
    sent_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class MockSmsProvider:
    name = "mock"

    def __init__(self) -> None:
        self._outbox: deque[MockMessage] = deque(maxlen=OUTBOX_SIZE)
        self._lock = threading.Lock()
        # Tests set this to simulate a provider outage.
        self.fail_with: str | None = None

    def send(self, to: str, message: str) -> SmsResult:
        if self.fail_with:
            raise SmsDeliveryError(self.fail_with)
        item = MockMessage(to=to, message=message, message_id=f"mock-{secrets.token_hex(6)}")
        with self._lock:
            self._outbox.append(item)
        return SmsResult(provider=self.name, message_id=item.message_id)

    def latest(self, to: str) -> MockMessage | None:
        with self._lock:
            for item in reversed(self._outbox):
                if item.to == to:
                    return item
        return None

    def messages(self) -> list[MockMessage]:
        with self._lock:
            return list(self._outbox)

    def reset(self) -> None:
        with self._lock:
            self._outbox.clear()
        self.fail_with = None


mock_provider = MockSmsProvider()
