"""End-to-end check of mandatory phone verification by SMS code, in a real
browser, against a LOCAL backend and a throwaway database:

  backend:  APP_ENV=development PHONE_VERIFICATION_REQUIRED=true SMS_PROVIDER=mock
            OTP_HMAC_SECRET=<random> EMAIL_PROVIDER=mock
  frontend: python -m http.server 5501 --directory frontend
  run:      python frontend/tests/e2e_phone_verification.py

Codes are read from the MOCK provider through the development-only
GET /dev/sms/latest. Nothing here sends a real SMS or calls eSMS Africa, so it
proves the ApexRX flow, not delivery to a phone. Never point it at production.
"""

import json
import os
import sys
import urllib.error
import urllib.request
import uuid

from playwright.sync_api import sync_playwright

SITE = os.environ.get("E2E_SITE", "http://127.0.0.1:5501")
API = os.environ.get("E2E_API", "http://127.0.0.1:8000")
RUN = uuid.uuid4().hex[:6]
PASSWORD = "Phone-Check-2026"
failures = []


def check(label, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + label + ("" if ok else f"  -> {detail}"))
    if not ok:
        failures.append(label)


def api(method, path, token=None, body=None):
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(API + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req) as r:
            text = r.read().decode()
            return r.status, json.loads(text) if text else None
    except urllib.error.HTTPError as e:
        text = e.read().decode()
        return e.code, json.loads(text) if text else None


def token_of(page):
    return page.evaluate("JSON.parse(sessionStorage.getItem('apexrx_session') || '{}').token")


def sms_code(page):
    status, body = api("GET", "/dev/sms/latest", token_of(page))
    assert status == 200, (status, body)
    return body["code"]


def verify_on_page(page, code):
    page.fill("#vp-code", code)
    page.click("#vp-verify")


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=os.environ.get("E2E_BROWSER_CHANNEL") or None, headless=True)
        ctx = browser.new_context(viewport={"width": 390, "height": 844})
        ctx.route("**/js/config.js", lambda r: r.fulfill(content_type="application/javascript",
                                                         body=f'window.APEX_CONFIG = {{ API_BASE_URL: "{API}" }};'))
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        # ---- 1. Patient sign-up: straight to verification, then the reservations page.
        email = f"phone-patient-{RUN}@example.com"
        page.goto(SITE + "/patient-register.html")
        page.fill("#patient-auth [name=name]", "Phone Patient")
        page.fill("#patient-auth [name=email]", email)
        page.fill("#patient-auth [name=phone]", "0788 431 000")
        page.fill("#patient-auth [name=password]", PASSWORD)
        page.fill("#patient-auth [name=confirm]", PASSWORD)
        page.click("#auth-submit")
        page.wait_for_url("**/verify-phone*", timeout=30000)
        page.wait_for_selector("#vp-main:not([hidden])")
        check("1. sign-up opens the verification page, showing a masked number",
              page.inner_text("#vp-number").endswith("000") and "431" not in page.inner_text("#vp-number"))
        status, _ = api("GET", "/reservations", token_of(page))
        check("1. the server refuses protected calls before verification", status == 403, status)

        page.click("#vp-send")
        page.wait_for_selector("#vp-code-form:not([hidden])")
        check("1. after sending: code field, expiry and a resend countdown",
              "expires at" in page.inner_text("#vp-expiry") and page.is_disabled("#vp-resend")
              and "s)" in page.inner_text("#vp-resend-wait"))
        code = sms_code(page)
        verify_on_page(page, "12345")
        check("1. a short code is refused in the page", "6-digit code" in page.inner_text("#vp-error"))
        verify_on_page(page, f"{(int(code) + 1) % 1_000_000:06d}")
        page.wait_for_function("document.querySelector('#vp-error').textContent.includes('attempts left')")
        check("1. a wrong code shows the attempts left", "4 attempts left" in page.inner_text("#vp-error"))
        verify_on_page(page, code)
        page.wait_for_selector("#vp-done:not([hidden])")
        check("1. the right code verifies the number", "verified" in page.inner_text("#vp-done"))
        page.click("#vp-continue")
        page.wait_for_url("**/reservations*", timeout=30000)
        page.wait_for_selector("#rs-cards .rs-empty, #rs-cards .rs-card", timeout=30000)
        check("1. then the patient's reservations open", True)
        status, me = api("GET", "/auth/me", token_of(page))
        check("1. the account is verified on the server", me["phone_verified"] and not me["phone_verification_pending"], me)
        page.click(".am-btn")
        check("1. a verified account has no 'Verify your mobile number' reminder",
              page.is_hidden("[data-am=verify-phone]"))
        page.click("[data-am=signout]")
        page.wait_for_url("**/index*")

        # ---- 2. A protected page opened directly redirects to verification and back.
        email2 = f"phone-direct-{RUN}@example.com"
        api("POST", "/auth/register", body={"name": "Direct", "email": email2, "phone": "0788 431 001", "password": PASSWORD, "account_type": "patient"})
        page.goto(SITE + "/patient-sign-in.html")
        page.fill("#patient-auth [name=email]", email2)
        page.fill("#patient-auth [name=password]", PASSWORD)
        page.click("#auth-submit")
        page.wait_for_url("**/verify-phone*", timeout=30000)
        check("2. signing in to a locked account opens verification", "next=" in page.url)
        page.goto(SITE + "/reservations.html")
        page.wait_for_url("**/verify-phone*", timeout=30000)
        check("2. opening reservations directly is redirected to verification", "reservations" in page.url)

        # ---- 3. Change the number on the page; the old code stops working.
        page.wait_for_selector("#vp-main:not([hidden])")
        page.click("#vp-send")
        page.wait_for_selector("#vp-code-form:not([hidden])")
        old_code = sms_code(page)
        page.click("#vp-change")
        page.fill("#vp-number-form [name=phone]", "0788 431 999")
        page.click("#vp-number-save")
        page.wait_for_function("document.querySelector('#vp-number').textContent.endsWith('999')")
        check("3. the new number is shown and a new code must be sent", page.is_visible("#vp-send"))
        page.click("#vp-send")
        page.wait_for_selector("#vp-code-form:not([hidden])")
        new_code = sms_code(page)
        check("3. the code went to the new number", new_code is not None and sms_code(page) == new_code)
        if old_code != new_code:
            verify_on_page(page, old_code)
            page.wait_for_function("document.querySelector('#vp-error').textContent.length > 0")
            check("3. the old number's code does not verify the new number", page.is_hidden("#vp-done"))
        verify_on_page(page, new_code)
        page.wait_for_selector("#vp-done:not([hidden])")
        page.click("#vp-continue")
        page.wait_for_url("**/reservations*", timeout=30000)
        check("3. after verifying, the page it came from opens", True)

        # ---- 4. Pharmacy owner sign-up asks for the mobile number, then verifies it.
        page.goto(SITE + "/pharmacies.html")
        page.evaluate("sessionStorage.clear()")
        page.goto(SITE + "/pharmacies.html")
        page.wait_for_selector("#account")
        page.fill("#account [name=email]", f"phone-owner-{RUN}@example.com")
        page.fill("#account [name=password]", PASSWORD)
        page.fill("#account [name=confirm]", PASSWORD)
        page.click("#account-submit")
        page.wait_for_function("document.querySelector('#form-error').textContent.includes('Enter your mobile number')")
        check("4. pharmacy sign-up requires the owner's mobile number",
              page.locator("#phone-field").is_visible() and "pharmacies" in page.url)
        page.fill("#account [name=phone]", "0788 431 222")
        page.click("#account-submit")
        page.wait_for_url("**/verify-phone*", timeout=30000)
        page.wait_for_selector("#vp-main:not([hidden])")
        page.click("#vp-send")
        page.wait_for_selector("#vp-code-form:not([hidden])")
        verify_on_page(page, sms_code(page))
        page.wait_for_selector("#vp-done:not([hidden])")
        page.click("#vp-continue")
        page.wait_for_url("**/pharmacies*", timeout=30000)
        check("4. after verifying, the pharmacy registration continues", True)

        # ---- 5. Language and layout.
        page.goto(SITE + "/verify-phone.html")
        page.wait_for_selector("#vp-main:not([hidden])")
        page.select_option("#workflow-language", "fr")
        check("5. the page is translated (French)", "Vérifiez votre numéro de mobile" in page.inner_text("#vp-title"))
        page.select_option("#workflow-language", "en")
        check("5. no sideways scrolling at phone width",
              not page.evaluate("document.documentElement.scrollWidth > innerWidth + 1"))
        check("no script errors", not errors, errors[:3])
        browser.close()
    print(f"\n{'ALL PASSED' if not failures else str(len(failures)) + ' FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
