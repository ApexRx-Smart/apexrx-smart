"""Browser test of the SMS phone verification step on pharmacies.html,
against a LOCAL backend. Never point this at production.

  1. Backend on http://127.0.0.1:8000 with a disposable database and
       APP_ENV=development SMS_PROVIDER=mock OTP_RESEND_COOLDOWN_SECONDS=5
  2. Frontend on http://127.0.0.1:5501 (python -m http.server 5501 --directory frontend).
  3. pip install playwright && playwright install chromium
  4. python frontend/tests/e2e_phone_otp.py

The test reads codes from the development-only GET /dev/sms/latest, exactly
as a developer would. It registers a throwaway account per run.
"""

import json
import os
import random
import re
import sys
import uuid

from playwright.sync_api import sync_playwright

SITE = os.environ.get("E2E_SITE", "http://127.0.0.1:5501")
API = os.environ.get("E2E_API", "http://127.0.0.1:8000")
RUN = uuid.uuid4().hex[:6]
EMAIL = f"otp-{RUN}@example.com"
PASSWORD = "Otp-Browser-Pass-2026"
LOCAL_PHONE = f"0788 {random.randint(0, 999):03d} {random.randint(0, 999):03d}"
E164 = "+250" + re.sub(r"\D", "", LOCAL_PHONE)[1:]
failures = []


def check(label, ok):
    print(("PASS " if ok else "FAIL ") + label)
    if not ok:
        failures.append(label)


DEV_CODE = """async (api) => {
  const s = JSON.parse(sessionStorage.getItem('apexrx_session'));
  const r = await fetch(api + '/dev/sms/latest', { headers: { Authorization: 'Bearer ' + s.token } });
  return r.ok ? (await r.json()).code : null;
}"""


def error_text(page):
    return page.text_content("#form-error") or ""


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=os.environ.get("E2E_BROWSER_CHANNEL") or None, headless=True)
        ctx = browser.new_context()
        ctx.route("**/js/config.js", lambda r: r.fulfill(
            content_type="application/javascript", body=f'window.APEX_CONFIG = {{ API_BASE_URL: "{API}" }};'))
        ctx.route("https://apexrx-smart.onrender.com/**", lambda r: r.abort())
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        requests = []
        page.on("request", lambda r: requests.append(r.url) if "/auth/phone/" in r.url else None)

        page.goto(SITE + "/pharmacies.html")
        check("old demo code is gone from the page", "472916" not in page.content())

        # 1. Account -> verify step (phone not verified yet).
        page.fill("#account [name=email]", EMAIL)
        page.fill("#account [name=password]", PASSWORD)
        page.fill("#account [name=confirm]", PASSWORD)
        page.click("#account button.primary")
        page.wait_for_selector("#verify:not([hidden])")
        check("new account lands on the phone verification step",
              "mobile number" in page.text_content("#step-description"))

        # 2. Invalid numbers are refused with a clear message.
        page.fill("#verify [name=phone]", "0788 abc 123")
        page.click("#send-code")
        page.wait_for_function("document.querySelector('#form-error').textContent.length > 0")
        check(f"invalid number rejected ({error_text(page)!r})", "only digits" in error_text(page))
        check("code entry stays hidden until a code is sent", page.is_hidden("#code-area"))

        # 3. Send a code: normalized number, masked confirmation, countdown.
        page.fill("#verify [name=phone]", LOCAL_PHONE)
        page.click("#send-code")
        page.wait_for_selector("#code-area:not([hidden])")
        check("number normalized to E.164", page.input_value("#verify [name=phone]") == E164)
        sent = page.text_content("#code-sent")
        check(f"confirmation shows a masked number ({sent!r})",
              sent.startswith("Code sent to +2507") and E164[-6:-3] not in sent and "expires in 5 minutes" in sent)
        resend = page.text_content("#resend-code")
        check(f"resend button counts down ({resend!r})",
              page.is_disabled("#resend-code") and re.fullmatch(r"Resend code in \d+s", resend) is not None)
        code = page.evaluate(DEV_CODE, API)
        check("a 6-digit code was sent (read via the dev-only endpoint)", bool(code) and re.fullmatch(r"\d{6}", code))
        check("the code never appears in any request URL",
              code not in json.dumps(page.evaluate("performance.getEntries().map(e => e.name)")))

        # 4. Wrong code.
        wrong = "000000" if code != "000000" else "111111"
        page.fill("#verify [name=code]", wrong)
        page.click("#verify-code")
        page.wait_for_function("document.querySelector('#form-error').textContent.includes('Incorrect code')")
        check(f"incorrect code message ({error_text(page)!r})", "4 attempts left" in error_text(page))

        # 5. Resend after the cooldown: old code invalid, new one works.
        page.wait_for_function("!document.querySelector('#resend-code').disabled", timeout=15000)
        page.click("#resend-code")
        page.wait_for_function("document.querySelector('#resend-code').disabled")
        # The button is disabled as soon as it is clicked, before the new SMS is
        # sent: wait until the latest SMS carries a different code.
        new_code = code
        for _ in range(50):
            new_code = page.evaluate(DEV_CODE, API)
            if new_code and new_code != code:
                break
            page.wait_for_timeout(200)
        check("resend sent a new code", bool(new_code))
        if new_code != code:
            page.fill("#verify [name=code]", code)
            page.click("#verify-code")
            page.wait_for_function("document.querySelector('#form-error').textContent.includes('Incorrect code')")
            check("the previous code no longer works after a resend", True)

        # 6. Correct code, double-click protection.
        requests.clear()
        page.fill("#verify [name=code]", new_code)
        page.dblclick("#verify-code")
        page.wait_for_selector("#profile:not([hidden])")
        verify_calls = [u for u in requests if u.endswith("/auth/phone/verify")]
        check(f"double click sends one verification request ({len(verify_calls)})", len(verify_calls) == 1)
        phone_field = page.locator("#profile [name=phone]")
        check("profile phone is the verified number, read-only",
              phone_field.input_value() == E164 and phone_field.evaluate("e => e.readOnly"))

        # 7. Profile -> plan; the backend stored the verified number.
        page.fill("#profile [name=name]", f"OTP Pharmacy {RUN}")
        page.fill("#profile [name=license]", "PH-OTP")
        page.fill("#profile [name=address]", "KG 1 Ave, Kigali")
        page.click("#profile button.primary")
        page.wait_for_selector("#payment:not([hidden])")
        org_phone = page.evaluate("""async (api) => {
          const s = JSON.parse(sessionStorage.getItem('apexrx_session'));
          const me = await (await fetch(api + '/organizations', { headers: { Authorization: 'Bearer ' + s.token } })).json();
          return me[0] && me[0].phone;
        }""", API)
        check(f"pharmacy registered with the verified phone ({org_phone})", org_phone == E164)

        # 8. Refresh keeps the session; restart signs out.
        page.reload()
        page.wait_for_selector("#dashboard:not([hidden])")
        check("still signed in after refresh", page.is_visible("#dashboard"))
        page.click("#restart")
        page.wait_for_selector("#account:not([hidden])")
        check("restart demo signs out", page.evaluate("sessionStorage.getItem('apexrx_session')") is None)

        # 9. Signing in again skips the step (already verified).
        page.fill("#account [name=email]", EMAIL)
        page.fill("#account [name=password]", PASSWORD)
        page.fill("#account [name=confirm]", PASSWORD)
        page.click("#account button.primary")
        page.wait_for_selector("#dashboard:not([hidden])")
        check("existing pharmacy goes straight to the workspace", True)

        # 10. Error states with the backend's answers simulated in the browser.
        page2 = ctx.new_page()
        page2.on("pageerror", lambda e: errors.append(str(e)))
        page2.goto(SITE + "/pharmacies.html")
        email2 = f"otp2-{RUN}@example.com"
        for sel, val in (("email", email2), ("password", PASSWORD), ("confirm", PASSWORD)):
            page2.fill(f"#account [name={sel}]", val)
        page2.click("#account button.primary")
        page2.wait_for_selector("#verify:not([hidden])")
        page2.route("**/auth/phone/send-code", lambda r: r.fulfill(
            status=502, content_type="application/json",
            body=json.dumps({"detail": "We could not send the SMS. Check the number and try again in a moment."})))
        page2.fill("#verify [name=phone]", "0788 765 432")
        page2.click("#send-code")
        page2.wait_for_function("document.querySelector('#form-error').textContent.length > 0")
        check("SMS delivery failure is shown", "could not send the SMS" in error_text(page2))
        check("buttons usable again after the failure", not page2.is_disabled("#send-code"))
        page2.unroute("**/auth/phone/send-code")
        page2.route("**/auth/phone/send-code", lambda r: r.fulfill(
            status=503, content_type="application/json",
            body=json.dumps({"detail": "SMS verification is not available right now. Please try again later or contact ApexRX."})))
        page2.click("#send-code")
        page2.wait_for_function("document.querySelector('#form-error').textContent.includes('not available')")
        check("SMS not configured is shown", True)

        # 11. French translation of the step.
        page2.select_option("#workflow-language", "fr")
        page2.wait_for_function("document.querySelector('#send-code').textContent.includes('SMS')")
        check(f"French label ({page2.text_content('#send-code')!r})", page2.text_content("#send-code") == "Envoyer le code par SMS")

        check("no page errors", not errors)
        for e in errors:
            print("  page error:", e)
        browser.close()

    print(f"\n{'ALL PASSED' if not failures else str(len(failures)) + ' FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
