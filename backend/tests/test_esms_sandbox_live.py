"""Opt-in check against the REAL eSMS Africa sandbox (free, simulated).

Runs only with ESMS_LIVE_TESTS=1 and an eSMS TEST key in ESMS_SANDBOX_API_KEY
(esms_test_...; a live key is refused). Put the key in backend/.env, never in
chat or git. Sandbox sends reach no phone and cost nothing, so this proves the
request format, authentication and the sandbox's answers, NOT delivery to a
handset. Numbers ending 0003 simulate a carrier rejection (eSMS sandbox docs).

    ESMS_LIVE_TESTS=1 pytest tests/test_esms_sandbox_live.py -v
"""

import os
import secrets

import pytest

from app.services.sms import SmsDeliveryError
from app.services.sms.esms import EsmsProvider

KEY = os.environ.get("ESMS_SANDBOX_API_KEY", "")
pytestmark = pytest.mark.skipif(
    os.environ.get("ESMS_LIVE_TESTS") != "1" or not KEY.startswith("esms_test_"),
    reason="Set ESMS_LIVE_TESTS=1 and ESMS_SANDBOX_API_KEY=esms_test_... to call the real eSMS sandbox.",
)


def sandbox():
    return EsmsProvider(api_key=KEY, mode="sandbox", base_url=os.environ.get("ESMS_BASE_URL", "https://sms.esmsafrica.io/api"),
                        sender_id=None, timeout=20)


def test_sandbox_accepts_a_send():
    result = sandbox().send("+250788120001", "ApexRX sandbox test 000000. Not a real code.",
                            idempotency_key=f"apexrx-test-{secrets.token_hex(8)}")
    assert result.environment == "test" and result.status in {"queued", "submitted"} and result.message_id
    print(f"sandbox accepted: id={result.message_id} status={result.status} environment={result.environment}")


def test_sandbox_failure_number():
    try:
        result = sandbox().send("+250788120003", "ApexRX sandbox failure test.",
                                idempotency_key=f"apexrx-test-{secrets.token_hex(8)}")
    except SmsDeliveryError as exc:
        print(f"sandbox refused the failure number: {exc.reason}")
        return
    # Accepted for sending; the simulated failure then comes as a delivery report.
    print(f"sandbox accepted the failure number for sending: status={result.status}")
    assert result.environment == "test"


def test_sandbox_rejects_a_bad_key():
    bad = EsmsProvider(api_key="esms_test_" + "0" * 32, mode="sandbox", base_url="https://sms.esmsafrica.io/api",
                       sender_id=None, timeout=20)
    with pytest.raises(SmsDeliveryError) as exc:
        bad.send("+250788120001", "ApexRX bad key test", idempotency_key=f"apexrx-test-{secrets.token_hex(8)}")
    assert exc.value.reason in {"unauthorized", "http_401"}
