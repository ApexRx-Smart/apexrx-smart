"""Browser test: what pharmacies.html does with the phone-verification status,
including when GET /auth/phone/status fails. LOCAL backend only.

Run it once per backend configuration:
  E2E_EXPECT_REQUIRED=true   backend with APP_ENV=development SMS_PROVIDER=mock
                             (PHONE_VERIFICATION_REQUIRED defaults to true)
  E2E_EXPECT_REQUIRED=false  backend with PHONE_VERIFICATION_REQUIRED=false
                             (e.g. no SMS provider, like the current Render setup)

  python frontend/tests/e2e_phone_status_fallback.py

An unknown status (404 from an older backend during a deploy, a network
error, a malformed answer) must let the user continue to the profile step,
and must never count as "verified": when verification is required the
backend still refuses the pharmacy (403) and the page returns to the verify
step. Each scenario registers a throwaway account.
"""

import json
import os
import sys
import uuid

from playwright.sync_api import sync_playwright

SITE = os.environ.get("E2E_SITE", "http://127.0.0.1:5501")
API = os.environ.get("E2E_API", "http://127.0.0.1:8000")
REQUIRED = os.environ.get("E2E_EXPECT_REQUIRED", "true").lower() == "true"
PASSWORD = "Status-Fallback-Pass-2026"
failures = []


def check(label, ok):
    print(("PASS " if ok else "FAIL ") + label)
    if not ok:
        failures.append(label)


def scenario(browser, name, status_route=None):
    """Register a new account; optionally replace the status response."""
    ctx = browser.new_context()
    ctx.route("**/js/config.js", lambda r: r.fulfill(
        content_type="application/javascript", body=f'window.APEX_CONFIG = {{ API_BASE_URL: "{API}" }};'))
    ctx.route("https://apexrx-smart.onrender.com/**", lambda r: r.abort())
    if status_route:
        ctx.route("**/auth/phone/status", status_route)
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(SITE + "/pharmacies.html")
    email = f"fallback-{name}-{uuid.uuid4().hex[:6]}@example.com"
    for field, value in (("email", email), ("password", PASSWORD), ("confirm", PASSWORD)):
        page.fill(f"#account [name={field}]", value)
    page.click("#account button.primary")
    page.wait_for_function(
        "!!document.querySelector('#verify') || !!document.querySelector('#profile')", timeout=20000)
    return ctx, page, errors


def visible_step(page):
    return "verify" if page.is_visible("#verify") else "profile" if page.is_visible("#profile") else "other"


def submit_profile(page, name):
    page.fill("#profile [name=name]", f"Fallback {name} Pharmacy")
    page.fill("#profile [name=npc]", "NPC/RWA/2026/00456")
    page.fill("#profile [name=lic]", "PH-FB")
    if not page.locator("#profile [name=phone]").evaluate("e => e.readOnly"):
        page.fill("#profile [name=phone]", "+250 788 444 333")
    for field in ("dist", "sect", "cell", "vill"):
        page.select_option(f"[data-a={field}]", index=1)
    page.click("#profile button.primary")
    page.wait_for_function(
        "!!document.querySelector('#payment') || !!document.querySelector('#verify')"
        " || document.querySelector('#form-error').textContent.length > 0", timeout=20000)


def my_organizations(page):
    return page.evaluate("""async (api) => {
      const s = JSON.parse(sessionStorage.getItem('apexrx_session'));
      return (await fetch(api + '/organizations', { headers: { Authorization: 'Bearer ' + s.token } })).json();
    }""", API)


UNKNOWN = {
    "404 (older backend)": lambda r: r.fulfill(status=404, content_type="application/json", body='{"detail":"Not Found"}'),
    "network failure": lambda r: r.abort("connectionrefused"),
    "malformed answer": lambda r: r.fulfill(status=200, content_type="application/json",
                                            body=json.dumps({"unexpected": True, "verified": "yes"})),
}


def main():
    mode = "required" if REQUIRED else "not required"
    print(f"Backend expected: phone verification {mode}\n")
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=os.environ.get("E2E_BROWSER_CHANNEL") or None, headless=True)

        # The real status from the backend.
        ctx, page, errors = scenario(browser, "real")
        if REQUIRED:
            check("[real status, required] the OTP step is shown", visible_step(page) == "verify")
        else:
            check("[real status, not required] goes straight to the profile", visible_step(page) == "profile")
            submit_profile(page, "real")
            orgs = my_organizations(page)
            check("[real status, not required] registration completes without OTP",
                  page.is_visible("#payment") and len(orgs) == 1)
        check("[real status] no page errors", not errors)
        ctx.close()

        # Unknown status: always continue to the profile step, never "verified".
        for label, route in UNKNOWN.items():
            ctx, page, errors = scenario(browser, label.split()[0], route)
            check(f"[{label}] continues to the profile step", visible_step(page) == "profile")
            check(f"[{label}] not treated as verified (phone editable)",
                  not page.locator("#profile [name=phone]").evaluate("e => e.readOnly"))
            submit_profile(page, label.split()[0])
            orgs = my_organizations(page)
            if REQUIRED:
                check(f"[{label}] backend refuses the unverified pharmacy; page returns to the OTP step "
                      f"({page.text_content('#form-error')!r})",
                      visible_step(page) == "verify" and "Verify your mobile number" in page.text_content("#form-error")
                      and orgs == [])
            else:
                check(f"[{label}] registration completes without OTP", page.is_visible("#payment") and len(orgs) == 1)
            check(f"[{label}] no page errors", not errors)
            ctx.close()
        browser.close()

    print(f"\n{'ALL PASSED' if not failures else str(len(failures)) + ' FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
