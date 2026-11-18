"""Login throttling: failed sign-in attempts per account and per client IP.

Uses the ``limits`` library (moving window). Counters are kept in
``settings.rate_limit_storage_uri``: in-process memory by default, which suits
the single Render instance; use a shared store (e.g. Redis) when running
several instances, or the limits become per instance.

* Account limit: failed attempts from browsers the account does not recognise,
  keyed on a SHA-256 of the normalized email whether or not an account exists,
  so a 429 does not reveal which emails are registered. A successful sign-in
  from such a browser clears it.
* Device limit: a browser that signed in to the account before presents a
  signed device token (app/core/device_token.py). Its attempts are counted
  per device instead, so an attacker who locks the account (5 wrong passwords)
  does NOT lock out the owner on their usual browser.
* IP limit: keyed on the client IP (see ``client_ip``), only when that IP can
  be trusted. Not cleared by a successful sign-in, so one valid account cannot
  reset an attacker's budget.
* Both are checked BEFORE the password is verified, and a blocked request gets
  the same 429 whatever the password.
* If the counter store fails, sign-in is allowed (fail open) and the error is
  logged: an outage of the store must not lock everyone out.
"""

import hashlib
import ipaddress
import logging
import math
import time

from fastapi import Request
from limits import RateLimitItemPerSecond
from limits.storage import storage_from_string
from limits.strategies import MovingWindowRateLimiter

from app.core.config import settings

logger = logging.getLogger("apexrx.rate_limit")


def client_ip(request: Request) -> str | None:
    """The client IP for the per-IP limit, or None when it cannot be trusted.

    * If TRUSTED_CLIENT_IP_HEADER is configured and holds a valid IP, use it.
      Only configure a header that the proxy in front of the app is VERIFIED
      to overwrite on every request (tools/render-ip-check); a header the
      client can set would let it pick its own rate-limit key.
    * Otherwise use the TCP peer. A private/loopback peer is a proxy or a
      local machine, not a client: return None so all users do not share
      one bucket (which an attacker could use to lock everyone out).
    """
    header = settings.trusted_client_ip_header
    if header:
        raw = request.headers.get(header, "").split(",")[0].strip()
        try:
            return str(ipaddress.ip_address(raw))
        except ValueError:
            pass
    peer = request.client.host if request.client else None
    if not peer:
        return None
    try:
        address = ipaddress.ip_address(peer)
    except ValueError:
        return peer  # e.g. the test client's "testclient"
    if not address.is_global:  # private, loopback, carrier-grade NAT, link-local...
        return None
    return str(address)


Subject = tuple[str, str]


def account_subject(email: str) -> Subject:
    """Attempts for an account from a browser it does not recognise."""
    return ("login-account", hashlib.sha256(email.strip().lower().encode()).hexdigest())


def device_subject(device_id: str) -> Subject:
    """Attempts from one browser that has signed in to this account before
    (see app/core/device_token.py). Locking the account does not affect it."""
    return ("login-device", device_id)


class LoginRateLimiter:
    def __init__(self) -> None:
        self.configure()

    def configure(self) -> None:
        """(Re)build from settings. Also clears all counters."""
        self._storage = storage_from_string(settings.rate_limit_storage_uri)
        self._limiter = MovingWindowRateLimiter(self._storage)
        window = settings.login_failure_window_seconds
        # The same budget applies to an account (unrecognised browsers) and to
        # each recognised browser.
        self.subject_limit = RateLimitItemPerSecond(settings.login_max_failures_per_account, window)
        self.ip_limit = RateLimitItemPerSecond(settings.login_max_failures_per_ip, window)

    def _checks(self, ip: str | None, subject: Subject):
        yield self.subject_limit, subject
        if ip:
            yield self.ip_limit, ("login-ip", ip)

    def retry_after(self, ip: str | None, subject: Subject) -> int | None:
        """Seconds to wait if the next attempt is blocked, otherwise None."""
        try:
            waits = []
            for item, keys in self._checks(ip, subject):
                if not self._limiter.test(item, *keys):
                    reset_time = self._limiter.get_window_stats(item, *keys).reset_time
                    waits.append(max(1, math.ceil(reset_time - time.time())))
            return max(waits) if waits else None
        except Exception as exc:  # pragma: no cover - storage outage
            logger.error("Login rate-limit check failed (allowing the attempt): %s", type(exc).__name__)
            return None

    def record_failure(self, ip: str | None, subject: Subject) -> None:
        try:
            for item, keys in self._checks(ip, subject):
                self._limiter.hit(item, *keys)
        except Exception as exc:  # pragma: no cover - storage outage
            logger.error("Could not record a failed login: %s", type(exc).__name__)

    def record_success(self, subject: Subject) -> None:
        try:
            self._limiter.clear(self.subject_limit, *subject)
        except Exception as exc:  # pragma: no cover - storage outage
            logger.error("Could not clear the login counter: %s", type(exc).__name__)

    def reset(self) -> None:
        """Clear every counter (tests, or an operator unblocking users)."""
        self._storage.reset()


login_limiter = LoginRateLimiter()


class ActionRateLimiter:
    """Caps how often one subject (e.g. a user) may perform an action, such as
    sending chat messages or procurement requests. Same store as the login
    limiter; fails open if the store is down."""

    def __init__(self, name: str, limit: int, window_seconds: int) -> None:
        self.name, self.limit, self.window_seconds = name, limit, window_seconds
        self.configure()

    def configure(self) -> None:
        self._storage = storage_from_string(settings.rate_limit_storage_uri)
        self._limiter = MovingWindowRateLimiter(self._storage)
        self._item = RateLimitItemPerSecond(self.limit, self.window_seconds)

    def hit(self, subject: str) -> int | None:
        """Count one action. Returns the seconds to wait if it is over the
        limit (the action must then be refused), otherwise None."""
        try:
            if self._limiter.hit(self._item, self.name, subject):
                return None
            reset_time = self._limiter.get_window_stats(self._item, self.name, subject).reset_time
            return max(1, math.ceil(reset_time - time.time()))
        except Exception as exc:  # pragma: no cover - storage outage
            logger.error("%s rate-limit check failed (allowing it): %s", self.name, type(exc).__name__)
            return None

    def reset(self) -> None:
        self._storage.reset()


# Chat: 30 messages a minute per user. Procurement requests: 30 an hour per user.
message_limiter = ActionRateLimiter("chat-message", 30, 60)
procurement_limiter = ActionRateLimiter("procurement-request", 30, 3600)
# New patient reservation requests: 20 an hour per patient (retries of an
# existing request are not counted; RESERVATION_MAX_OPEN_PER_PATIENT caps open ones).
reservation_limiter = ActionRateLimiter("reservation-request", 20, 3600)
