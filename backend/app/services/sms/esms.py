"""eSMS Africa delivery adapter (https://docs.esmsafrica.io).

Only delivers the text it is given: ApexRX generates and checks the codes.
eSMS Africa's own OTP product is NOT used.

API, as documented by eSMS Africa (SMS API reference, "Send"):
  POST {ESMS_BASE_URL}/messages/send          base: https://sms.esmsafrica.io/api
  Authorization: Bearer <key>                 esms_test_... (sandbox) / esms_live_...
  Idempotency-Key: <key>                      a repeat returns the original result
  {"to": "+2507...", "text": "...", "sender_id": "..."}   sender_id optional
  200 {"id": ..., "status": "submitted" | "scheduled" | "failed", ...}
      test keys: {"status": "queued", "environment": "test", "livemode": false, ...}
  Errors: {"error": {"code": ..., "message": ..., "request_id": ...}}
      401 unauthorized, 402 insufficient_balance, 400 invalid_phone,
      403 sender_id_required / sender_not_approved / ..., 422 validation_error,
      429 rate_limited, 5xx internal_error.
  "Treat 429 and 5xx as retryable, ideally with backoff; treat 4xx (except 429)
  as caller errors to fix." Retries reuse the same Idempotency-Key, so a retry
  never sends a second SMS.

Sandbox: a test key simulates delivery; "Nothing is sent to a real network and
nothing is billed". Sandbox numbers ending 0003 / 0404 simulate failures and
0009 an insufficient balance.

Nothing secret is logged: no key, no message text, no response body; only the
error code, HTTP status and eSMS request id.
"""

import logging
import time

import httpx

from app.core.config import settings
from app.services.phone import mask_phone
from app.services.sms import SmsDeliveryError, SmsNotConfigured, SmsResult

logger = logging.getLogger("apexrx.sms.esms")

ACCEPTED = frozenset({"submitted", "queued", "scheduled", "sent", "delivered"})
KEY_PREFIX = {"sandbox": "esms_test_", "live": "esms_live_"}
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
MAX_TRIES = 2


class EsmsProvider:
    name = "esms"

    def __init__(self, *, api_key: str, mode: str, base_url: str, sender_id: str | None,
                 timeout: float, transport: httpx.BaseTransport | None = None,
                 retry_delay: float = 0.5) -> None:
        expected = KEY_PREFIX.get(mode)
        if expected is None:
            raise SmsNotConfigured("ESMS_MODE must be sandbox or live.")
        if not api_key.startswith(expected):
            # A live key in sandbox mode (or the reverse) is refused before any
            # request: going live must be a deliberate change of both settings.
            raise SmsNotConfigured(f"ESMS_MODE={mode} needs an API key starting with {expected}.")
        self._key = api_key
        self.mode = mode
        self._url = base_url.rstrip("/") + "/messages/send"
        self._sender_id = sender_id
        self._timeout = timeout
        self._transport = transport
        self._retry_delay = retry_delay

    @classmethod
    def from_settings(cls) -> "EsmsProvider":
        if settings.esms_api_key is None or not settings.esms_api_key.get_secret_value().strip():
            raise SmsNotConfigured("ESMS_API_KEY is not set.")
        return cls(
            api_key=settings.esms_api_key.get_secret_value().strip(),
            mode=settings.esms_mode,
            base_url=settings.esms_base_url,
            sender_id=settings.esms_sender_id,
            timeout=settings.esms_timeout_seconds,
        )

    def send(self, to: str, message: str, *, idempotency_key: str) -> SmsResult:
        body = {"to": to, "text": message}
        if self._sender_id:
            body["sender_id"] = self._sender_id
        headers = {
            "Authorization": f"Bearer {self._key}",
            "Idempotency-Key": idempotency_key,
            "Accept": "application/json",
        }
        last_reason = "provider_unavailable"
        with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
            for attempt in range(1, MAX_TRIES + 1):
                try:
                    response = client.post(self._url, json=body, headers=headers)
                except httpx.TimeoutException:
                    last_reason = "timeout"
                except httpx.HTTPError:
                    last_reason = "network_error"
                else:
                    if response.status_code not in RETRYABLE_STATUS:
                        return self._result(response, to)
                    last_reason = _error_code(response) or f"http_{response.status_code}"
                    _log_refusal(response, to, last_reason, final=attempt == MAX_TRIES)
                if attempt < MAX_TRIES:
                    time.sleep(self._retry_delay)
        logger.error("eSMS send to %s failed after %s tries: %s", mask_phone(to), MAX_TRIES, last_reason)
        raise SmsDeliveryError(last_reason)

    def _result(self, response: httpx.Response, to: str) -> SmsResult:
        if response.status_code == 200:
            try:
                data = response.json()
            except ValueError:
                data = None
            status = data.get("status") if isinstance(data, dict) else None
            if status in ACCEPTED:
                environment = data.get("environment") or ("test" if data.get("livemode") is False else "live")
                if self.mode == "live" and environment == "test":
                    # Never let a simulated send pass for a real one.
                    _log_refusal(response, to, "unexpected_test_response", final=True)
                    raise SmsDeliveryError("unexpected_test_response")
                message_id = data.get("id")
                return SmsResult(provider=self.name, message_id=str(message_id)[:100] if message_id else None,
                                 status=status, environment=environment)
            reason = "provider_failed" if status == "failed" else "unexpected_response"
            _log_refusal(response, to, reason, final=True)
            raise SmsDeliveryError(reason)
        code = _error_code(response) or f"http_{response.status_code}"
        _log_refusal(response, to, code, final=True)
        if response.status_code == 401:
            logger.critical("eSMS rejected the API key (401). Check ESMS_API_KEY and ESMS_MODE.")
        raise SmsDeliveryError(code, number_rejected=code in ("invalid_phone", "recipient_opted_out"))


def _error_code(response: httpx.Response) -> str | None:
    try:
        error = response.json().get("error")
    except (ValueError, AttributeError):
        return None
    code = error.get("code") if isinstance(error, dict) else None
    return str(code)[:60] if code else None


def _log_refusal(response: httpx.Response, to: str, reason: str, *, final: bool) -> None:
    logger.log(
        logging.WARNING if final else logging.INFO,
        "eSMS refused a send to %s: HTTP %s %s (request id %s)%s",
        mask_phone(to), response.status_code, reason, response.headers.get("x-request-id", "-"),
        "" if final else ", retrying",
    )
