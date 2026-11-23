"""python -m app.scripts.check_sms, against MOCKED eSMS responses (no network).
The real run against the eSMS sandbox is manual: see the README."""

import json

import httpx
from pydantic import SecretStr

from app.core.config import settings
from app.scripts import check_sms
from app.services.sms.esms import EsmsProvider

KEY = "esms_test_unit_test_key_0123456789"


def factory(seen):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.headers["Authorization"] != f"Bearer {KEY}":
            return httpx.Response(401, json={"error": {"code": "unauthorized", "message": "Invalid API key"}})
        return httpx.Response(200, json={"id": "test_msg_1", "status": "queued", "environment": "test",
                                         "livemode": False})

    def make(api_key):
        return EsmsProvider(api_key=api_key, mode="sandbox", base_url="https://sms.esmsafrica.io/api",
                            sender_id=None, timeout=5, transport=httpx.MockTransport(handler), retry_delay=0)
    return make


def configure(monkeypatch, key=KEY, mode="sandbox"):
    monkeypatch.setattr(settings, "esms_api_key", SecretStr(key) if key else None)
    monkeypatch.setattr(settings, "esms_mode", mode)


def test_sandbox_check_passes_and_never_prints_the_key(monkeypatch, capsys):
    configure(monkeypatch)
    seen = []
    assert check_sms.main(factory(seen)) == 0
    out = capsys.readouterr().out
    assert "OK: sandbox send accepted" in out and "OK: a made-up key is refused" in out and KEY not in out
    bodies = [json.loads(r.content) for r in seen]
    # Only eSMS sandbox numbers, never a code.
    assert {b["to"] for b in bodies} == {check_sms.ACCEPTED_NUMBER, check_sms.REJECTED_NUMBER}
    assert all("code" not in b["text"].replace("verification code", "") for b in bodies)


def test_sandbox_check_reports_a_wrong_key(monkeypatch, capsys):
    configure(monkeypatch, key="esms_test_wrong_key_000000000000")
    assert check_sms.main(factory([])) == 1
    assert "FAILED: the sandbox refused the send: unauthorized" in capsys.readouterr().out


def test_sandbox_check_refuses_anything_live_or_missing(monkeypatch, capsys):
    sent = []
    for key, mode in ((None, "sandbox"), ("esms_live_real_key_000000000000", "sandbox"), (KEY, "live")):
        configure(monkeypatch, key=key, mode=mode)
        assert check_sms.main(factory(sent)) == 2
    assert sent == []  # nothing was sent
    out = capsys.readouterr().out
    assert "ESMS_API_KEY is not set" in out and "not a test key" in out and "not 'sandbox'" in out
    assert "esms_live_real_key" not in out
