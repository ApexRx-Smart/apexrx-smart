"""Registration while SMS is in eSMS SANDBOX mode and verification is not
required (the configuration for testing with the sandbox), against a LOCAL
backend and a throwaway database:

  backend:  APP_ENV=development SMS_PROVIDER=esms ESMS_MODE=sandbox
            ESMS_API_KEY=esms_test_<anything> OTP_HMAC_SECRET=<random>
            (PHONE_VERIFICATION_REQUIRED unset)

Checks that sign-up and the patient workspace need no SMS, that nobody is
prompted to verify (sandbox SMS reach no phone), and that verify-phone.html says
it is in test mode. It never presses "Send code", so eSMS is never contacted.
"""

import os
import sys
import uuid

from playwright.sync_api import sync_playwright

SITE = os.environ.get("E2E_SITE", "http://127.0.0.1:5501")
API = os.environ.get("E2E_API", "http://127.0.0.1:8000")
RUN = uuid.uuid4().hex[:6]
PASSWORD = "Sandbox-Check-2026"
failures = []


def check(label, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + label + ("" if ok else f"  -> {detail}"))
    if not ok:
        failures.append(label)


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=os.environ.get("E2E_BROWSER_CHANNEL") or None, headless=True)
        ctx = browser.new_context(viewport={"width": 390, "height": 844})
        ctx.route("**/js/config.js", lambda r: r.fulfill(content_type="application/javascript",
                                                         body=f'window.APEX_CONFIG = {{ API_BASE_URL: "{API}" }};'))
        sends = []
        ctx.on("request", lambda r: sends.append(r.url) if "/auth/phone/send" in r.url or "esmsafrica" in r.url else None)
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        page.goto(SITE + "/patient-register.html")
        page.fill("#patient-auth [name=name]", "Sandbox Patient")
        page.fill("#patient-auth [name=email]", f"sandbox-{RUN}@example.com")
        page.fill("#patient-auth [name=phone]", "0788 431 500")
        page.fill("#patient-auth [name=password]", PASSWORD)
        page.fill("#patient-auth [name=confirm]", PASSWORD)
        page.click("#auth-submit")
        page.wait_for_url("**/reservations*", timeout=30000)
        page.wait_for_selector("#rs-cards .rs-empty, #rs-cards .rs-card", timeout=30000)
        check("sign-up goes straight to the patient's reservations (no SMS step)", "verify-phone" not in page.url)
        page.click(".am-btn")
        check("no 'Verify your mobile number' prompt while SMS is sandbox-only", page.is_hidden("[data-am=verify-phone]"))
        page.keyboard.press("Escape")

        page.goto(SITE + "/verify-phone.html")
        page.wait_for_selector("#vp-main:not([hidden])")
        check("verify-phone.html still opens and says it is in test mode", page.is_visible("#vp-sandbox"))
        check("nothing was sent to eSMS", sends == [], sends)
        check("no script errors", not errors, errors[:3])
        browser.close()
    print(f"\n{'ALL PASSED' if not failures else str(len(failures)) + ' FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
