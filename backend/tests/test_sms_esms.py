"""The eSMS Africa adapter against MOCKED HTTP responses (httpx.MockTransport):
request format, success, failures, timeouts and retries. No network is used;
python -m app.scripts.check_sms is the manual check against the real sandbox.
Response bodies follow the examples in the eSMS Africa API reference."""

import json

import httpx
import pytest

from app.services.sms import SmsDeliveryError, SmsNotConfigured
from app.services.sms.esms import EsmsProvider

TEST_KEY = "esms_test_unit_test_key_0123456789"
LIVE_KEY = "esms_live_unit_test_key_0123456789"
SANDBOX_OK = {"id": "test_msg_1", "status": "queued", "environment": "test", "livemode": False,
              "segments": 1, "balance_after": None}
LIVE_OK = {"id": "msg_abc123", "status": "submitted", "segments": 1, "encoding": "GSM7"}


def error(code, message="x"):
    return {"error": {"code": code, "message": message, "request_id": "req_1"}}


def provider(handler, *, mode="sandbox", key=TEST_KEY, sender_id=None):
    return EsmsProvider(api_key=key, mode=mode, base_url="https://sms.esmsafrica.io/api", sender_id=sender_id,
                        timeout=5, transport=httpx.MockTransport(handler), retry_delay=0)


class Recorder:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        status, body = item
        return httpx.Response(status, json=body, headers={"X-Request-Id": "req_1"})


def test_request_format():
    rec = Recorder((200, SANDBOX_OK))
    result = provider(rec, sender_id="ApexRX").send("+250788123456", "Your code is 123456", idempotency_key="ref-1")
    req = rec.requests[0]
    assert req.method == "POST" and str(req.url) == "https://sms.esmsafrica.io/api/messages/send"
    assert req.headers["Authorization"] == f"Bearer {TEST_KEY}"
    assert req.headers["Idempotency-Key"] == "ref-1" and req.headers["Content-Type"] == "application/json"
    assert json.loads(req.content) == {"to": "+250788123456", "text": "Your code is 123456", "sender_id": "ApexRX"}
    assert (result.provider, result.message_id, result.status, result.environment) == ("esms", "test_msg_1", "queued", "test")


def test_sender_id_is_optional():
    rec = Recorder((200, SANDBOX_OK))
    provider(rec).send("+250788123456", "hi", idempotency_key="r")
    assert "sender_id" not in json.loads(rec.requests[0].content)


def test_live_success():
    rec = Recorder((200, LIVE_OK))
    result = provider(rec, mode="live", key=LIVE_KEY).send("+250788123456", "hi", idempotency_key="r")
    assert (result.message_id, result.status, result.environment) == ("msg_abc123", "submitted", "live")


def test_live_mode_refuses_a_simulated_send():
    rec = Recorder((200, SANDBOX_OK))
    with pytest.raises(SmsDeliveryError) as exc:
        provider(rec, mode="live", key=LIVE_KEY).send("+250788123456", "hi", idempotency_key="r")
    assert exc.value.reason == "unexpected_test_response"


@pytest.mark.parametrize("mode,key", [("sandbox", LIVE_KEY), ("live", TEST_KEY), ("sandbox", "sk_other")])
def test_mode_and_key_must_match(mode, key):
    with pytest.raises(SmsNotConfigured):
        provider(Recorder(), mode=mode, key=key)


def test_failed_delivery_status():
    rec = Recorder((200, {"id": "msg_2", "status": "failed"}))
    with pytest.raises(SmsDeliveryError) as exc:
        provider(rec).send("+250788120003", "hi", idempotency_key="r")
    assert exc.value.reason == "provider_failed" and not exc.value.number_rejected


@pytest.mark.parametrize("status,code,number_rejected", [
    (401, "unauthorized", False), (402, "insufficient_balance", False), (400, "invalid_phone", True),
    (403, "sender_not_approved", False), (422, "validation_error", False),
])
def test_refusals_are_not_retried(status, code, number_rejected):
    rec = Recorder((status, error(code)))
    with pytest.raises(SmsDeliveryError) as exc:
        provider(rec).send("+250788123456", "hi", idempotency_key="r")
    assert exc.value.reason == code and exc.value.number_rejected is number_rejected
    assert len(rec.requests) == 1


def test_invalid_credentials_are_logged_without_the_key(app_logs):
    caplog = app_logs
    with pytest.raises(SmsDeliveryError):
        provider(Recorder((401, error("unauthorized", "Invalid API key")))).send(
            "+250788123456", "Your code is 654321", idempotency_key="r")
    assert "401" in caplog.text and TEST_KEY not in caplog.text and "654321" not in caplog.text
    assert "+250788123456" not in caplog.text  # numbers are masked


def test_rate_limit_and_server_errors_are_retried_once_with_the_same_key():
    rec = Recorder((429, error("rate_limited")), (200, SANDBOX_OK))
    assert provider(rec).send("+250788123456", "hi", idempotency_key="same").message_id == "test_msg_1"
    assert [r.headers["Idempotency-Key"] for r in rec.requests] == ["same", "same"]

    rec = Recorder((500, error("internal_error")), (503, {}))
    with pytest.raises(SmsDeliveryError) as exc:
        provider(rec).send("+250788123456", "hi", idempotency_key="r")
    assert exc.value.reason == "http_503" and len(rec.requests) == 2


def test_timeouts_and_network_errors():
    req = httpx.Request("POST", "https://sms.esmsafrica.io/api/messages/send")
    rec = Recorder(httpx.ReadTimeout("slow", request=req), httpx.ReadTimeout("slow", request=req))
    with pytest.raises(SmsDeliveryError) as exc:
        provider(rec).send("+250788123456", "hi", idempotency_key="r")
    assert exc.value.reason == "timeout" and len(rec.requests) == 2

    rec = Recorder(httpx.ConnectError("down", request=req), (200, SANDBOX_OK))
    assert provider(rec).send("+250788123456", "hi", idempotency_key="r").status == "queued"


def test_unexpected_responses_are_failures():
    for body in ({"status": "weird"}, ["not", "a", "dict"]):
        rec = Recorder((200, body))
        with pytest.raises(SmsDeliveryError):
            provider(rec).send("+250788123456", "hi", idempotency_key="r")
