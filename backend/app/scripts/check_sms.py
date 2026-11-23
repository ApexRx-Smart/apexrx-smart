"""Check the eSMS Africa SANDBOX configuration against the real eSMS API.

    python -m app.scripts.check_sms

Reads the same settings as the API (environment, otherwise backend/.env):
ESMS_API_KEY (an esms_test_ key), ESMS_MODE=sandbox, and optionally
ESMS_BASE_URL / ESMS_SENDER_ID / ESMS_TIMEOUT_SECONDS. Needs no database.

Sandbox only: it refuses to run with ESMS_MODE=live or a live key, so it can
never send a real (paid) SMS. Sandbox sends are free and simulated: nothing
reaches a phone, so this proves the request format, the key and the sandbox's
answers, NOT delivery to a handset. It sends to eSMS sandbox numbers (by their
last four digits: 0001 is delivered, 0003 is rejected by the carrier), never to
a real person's number, and the text holds no code. No key is printed.

Exit status 0 when the sandbox accepted the send and refused a wrong key.
"""

import secrets
import sys
from collections.abc import Callable

from app.core.config import settings
from app.services.sms import SmsDeliveryError, SmsNotConfigured
from app.services.sms.esms import EsmsProvider

ACCEPTED_NUMBER = "+250788120001"
REJECTED_NUMBER = "+250788120003"
TEXT = "ApexRX sandbox check. Not a verification code."


def _provider(api_key: str) -> EsmsProvider:
    return EsmsProvider(api_key=api_key, mode="sandbox", base_url=settings.esms_base_url,
                        sender_id=settings.esms_sender_id, timeout=settings.esms_timeout_seconds)


def main(make_provider: Callable[[str], EsmsProvider] = _provider) -> int:
    key = settings.esms_api_key.get_secret_value().strip() if settings.esms_api_key else ""
    if settings.esms_mode != "sandbox":
        print("Refused: ESMS_MODE is not 'sandbox'. This check never sends live (paid) SMS.")
        return 2
    if not key:
        print("ESMS_API_KEY is not set. Add your eSMS TEST key (esms_test_...) to backend/.env.")
        return 2
    if not key.startswith("esms_test_"):
        print("Refused: ESMS_API_KEY is not a test key (esms_test_...). This check never sends live SMS.")
        return 2
    print(f"eSMS sandbox check: {settings.esms_base_url} (key esms_test_... is set; not shown)")
    try:
        provider = make_provider(key)
    except SmsNotConfigured as exc:
        print(f"FAILED: {exc}")
        return 1

    ok = True
    try:
        result = provider.send(ACCEPTED_NUMBER, TEXT, idempotency_key=f"apexrx-check-{secrets.token_hex(8)}")
        good = result.environment == "test" and bool(result.message_id)
        ok &= good
        print(f"{'OK' if good else 'FAILED'}: sandbox send accepted: id={result.message_id} "
              f"status={result.status} environment={result.environment}")
    except SmsDeliveryError as exc:
        ok = False
        hint = " (check that the key is a valid TEST key)" if exc.reason in ("unauthorized", "http_401") else ""
        print(f"FAILED: the sandbox refused the send: {exc.reason}{hint}")

    try:
        result = provider.send(REJECTED_NUMBER, TEXT, idempotency_key=f"apexrx-check-{secrets.token_hex(8)}")
        print(f"INFO: carrier-rejection number accepted for sending (status={result.status}); "
              "the simulated failure arrives as a delivery report.")
    except SmsDeliveryError as exc:
        print(f"INFO: carrier-rejection number refused: {exc.reason}")

    try:
        make_provider("esms_test_" + "0" * 32).send(ACCEPTED_NUMBER, TEXT,
                                                     idempotency_key=f"apexrx-check-{secrets.token_hex(8)}")
        ok = False
        print("FAILED: a made-up key was accepted.")
    except SmsDeliveryError as exc:
        good = exc.reason in ("unauthorized", "http_401")
        ok &= good
        print(f"{'OK' if good else 'FAILED'}: a made-up key is refused ({exc.reason})")

    print("Sandbox check passed. Remember: sandbox SMS never reach a phone." if ok else "Sandbox check FAILED.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
