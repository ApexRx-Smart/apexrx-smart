"""End-to-end check of the configuration being deployed while email delivery is
disabled (no EMAIL_PROVIDER, EMAIL_VERIFICATION_REQUIRED unset), against a
LOCAL backend and a throwaway database:

  * pharmacy registration goes from the account straight to the details (no
    verification email), says why, and still ends pending ApexRX review;
  * "Forgot password?" says the feature is temporarily unavailable;
  * invitations: the owner gets a link to give the employee (nothing is
    emailed), the employee joins with their own account, the link works once,
    "New link" replaces it, and staff still cannot invite;
  * no email of any kind was produced.

Setup: a backend on http://127.0.0.1:8002 with APP_ENV=development and WITHOUT
EMAIL_PROVIDER, the frontend on http://127.0.0.1:5501, then
  E2E_ADMIN_EMAIL=... E2E_ADMIN_PASSWORD=... python frontend/tests/e2e_no_email.py
Never point this at production.
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

from playwright.sync_api import sync_playwright

SITE = os.environ.get("E2E_SITE", "http://127.0.0.1:5501")
API = os.environ.get("E2E_NO_EMAIL_API", "http://127.0.0.1:8002")
ADMIN_EMAIL, ADMIN_PASSWORD = os.environ["E2E_ADMIN_EMAIL"], os.environ["E2E_ADMIN_PASSWORD"]
RUN = uuid.uuid4().hex[:6]
PW = "No-Email-Pass-2026"
PDF = b"%PDF-1.4\n% ApexRx e2e dummy document, not a real license\n%%EOF\n"
failures = []


def check(label, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + label + (f"  {detail}" if detail and not condition else ""))
    if not condition:
        failures.append(label)


def call(method, path, body=None, token=None):
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    if data:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(API + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req) as res:
            text = res.read().decode()
            return res.status, (json.loads(text) if text else None)
    except urllib.error.HTTPError as e:
        text = e.read().decode()
        try:
            return e.code, json.loads(text)
        except ValueError:
            return e.code, text


def context(browser, viewport=None):
    ctx = browser.new_context(viewport=viewport or {"width": 1366, "height": 900})
    ctx.route("**/js/config.js", lambda route: route.fulfill(
        content_type="application/javascript", body=f'window.APEX_CONFIG = {{ API_BASE_URL: "{API}" }};'))
    return ctx


def watch(page, errors):
    page.on("pageerror", lambda e: errors.append(f"{page.url}: {e}"))
    page.on("console", lambda m: errors.append(f"{page.url}: {m.text}") if m.type == "error" and not any(
        x in m.text for x in ("status of 400", "status of 401", "status of 409", "status of 503", "Permissions policy")) else None)


def visible(page, selector, timeout=20000):
    page.wait_for_selector(f"{selector}:not([hidden])", timeout=timeout)


def wait_text(page, selector, text, timeout=20000):
    page.wait_for_function("([s, t]) => (document.querySelector(s) || {}).textContent?.includes(t)",
                           arg=[selector, text], timeout=timeout)


def no_email_to(address):
    status, _ = call("GET", "/dev/email/latest-to?" + urllib.parse.urlencode({"to": address}))
    return status == 404


def main():
    caps = call("GET", "/auth/capabilities")[1]
    if caps.get("email_delivery"):
        raise SystemExit(f"{API} has email delivery configured; run this against a backend without EMAIL_PROVIDER.")

    with sync_playwright() as p:
        browser = p.chromium.launch(channel=os.environ.get("E2E_BROWSER_CHANNEL") or None, headless=True)
        errors = []

        # ===================================== registration without email
        ctx = context(browser)
        page = ctx.new_page()
        watch(page, errors)
        owner_email = f"ne-owner-{RUN}@example.com"
        page.goto(SITE + "/pharmacies.html")
        page.fill("#account [name=email]", owner_email)
        page.fill("#account [name=password]", PW)
        page.fill("#account [name=confirm]", PW)
        page.click("#account-submit")
        visible(page, "#details")
        check("registration: no verification step; the details step explains why",
              page.is_hidden("#verify-email") and page.is_visible("#email-off-note")
              and "temporarily unavailable" in page.inner_text("#email-off-note"))
        name = f"No Email Pharmacy {RUN}"
        page.fill("#details [name=name]", name)
        page.fill("#details [name=phone]", "0788 123 456")
        page.select_option("#address-fields [name=province]", "Kigali")
        page.select_option("#address-fields [name=district]", "Gasabo")
        page.select_option("#address-fields [name=sector]", "Kimironko")
        for level in ("cell", "village"):
            value = page.eval_on_selector(f"#address-fields [name={level}]", "s => s.options[1].value")
            page.select_option(f"#address-fields [name={level}]", value)
        page.click("#details-submit")
        visible(page, "#documents")
        page.set_input_files("#doc-list input[data-document-type=pharmacy_license]",
                             files=[{"name": f"license-{RUN}.pdf", "mimeType": "application/pdf", "buffer": PDF}])
        page.click("#documents-submit")
        visible(page, "#review")
        wait_text(page, "#review-status", "Pending review")
        facts = page.inner_text("#review-facts")
        check("registration: stored as a pharmacy pending ApexRX review; the email is not shown as verified",
              "Pharmacy" in facts and owner_email in facts and "(verified)" not in facts)
        check("registration: no email was produced", no_email_to(owner_email))

        # ===================================== invitations shared as links
        page.click("#open-workspace")
        visible(page, "#dashboard")
        page.click(".sidebar [data-view=employees]")
        page.wait_for_selector("#invite-form")
        check("invitations: the form says email is unavailable and offers a link instead",
              "Email is temporarily unavailable" in page.inner_text("#invite-form")
              and page.inner_text("#invite-form button.primary-sm") == "Create invitation link")
        staff_email = f"ne-staff-{RUN}@example.com"
        page.fill("#invite-form [name=email]", staff_email)
        page.click("#invite-form button.primary-sm")
        page.wait_for_selector("#invite-link")
        link = page.input_value("#invite-link")
        check("invitations: the owner gets a single-use link, not a claim that an email was sent",
              "/accept-invitation.html#token=" in link and "no email was sent" in page.inner_text("#invite-status")
              and "Link given by you (no email)" in page.inner_text(f"tr[data-invite='{staff_email}']"))
        check("invitations: no email was produced", no_email_to(staff_email))

        staff_ctx = context(browser)
        staff = staff_ctx.new_page()
        watch(staff, errors)
        staff.goto(link)
        visible(staff, "#new-account")
        staff.fill("#new-account [name=name]", "Shema Staff")
        staff.fill("#new-account [name=password]", PW)
        staff.fill("#new-account [name=confirm]", PW)
        staff.click("#new-account-submit")
        visible(staff, "#invite-actions")
        staff.click("#invite-continue")
        visible(staff, "#dashboard")
        check("invitations: the employee joins with their own account and the Staff role",
              name in staff.inner_text("#pharmacy-name") and staff.inner_text("#dash-user") == f"{staff_email} · Staff")
        staff_token = staff.evaluate("JSON.parse(sessionStorage.getItem('apexrx_session')).token")
        me = call("GET", "/auth/me", token=staff_token)[1]
        check("invitations: joining by a shared link does not mark the address verified", me["email_verified"] is False)
        check("invitations: staff still cannot invite",
              call("POST", f"/organizations/{me['memberships'][0]['organization_id']}/invitations",
                   {"email": "x@example.com", "role": "staff"}, staff_token)[0] == 403)
        staff.goto("about:blank")
        staff.goto(link)
        staff.wait_for_function("document.querySelector('#invite-title').textContent.includes('already been accepted')")
        check("invitations: the link works only once", True)
        staff_ctx.close()

        # New link replaces the old one.
        second_email = f"ne-second-{RUN}@example.com"
        page.fill("#invite-form [name=email]", second_email)
        page.click("#invite-form button.primary-sm")
        page.wait_for_function(f"document.querySelector('#invite-link')?.value && document.querySelector('#invite-status').textContent.includes('{second_email}')")
        old_link = page.input_value("#invite-link")
        page.click(f"tr[data-invite='{second_email}'] button:has-text('New link')")
        page.wait_for_function(f"document.querySelector('#invite-link')?.value && document.querySelector('#invite-link').value !== '{old_link}'")
        new_link = page.input_value("#invite-link")
        tab = ctx.new_page()
        tab.goto(old_link)
        tab.wait_for_function("document.querySelector('#invite-title').textContent.includes('not valid')")
        tab.goto("about:blank")
        tab.goto(new_link)
        visible(tab, "#new-account")
        check("invitations: 'New link' replaces the link; the old one stops working", True)
        tab.close()
        ctx.close()

        # ========================================== forgot password
        ctx = context(browser, {"width": 390, "height": 844})
        page = ctx.new_page()
        watch(page, errors)
        page.goto(SITE + "/pharmacies.html#staff")
        page.click("#forgot-link")
        page.wait_for_url("**/reset-password.html*")
        wait_text(page, "#reset-title", "temporarily unavailable")
        check("forgot password: the page says it is temporarily unavailable and shows no form",
              page.is_hidden("#forgot-form") and "contact ApexRX support" in page.inner_text("#reset-message"))
        check("forgot password: the backend refuses it the same way for every address",
              call("POST", "/auth/password/forgot", {"email": owner_email})[1]
              == call("POST", "/auth/password/forgot", {"email": f"nobody-{RUN}@example.com"})[1])
        check("mobile: no horizontal scroll on the unavailable page",
              not page.evaluate("document.documentElement.scrollWidth > window.innerWidth"))
        ctx.close()

        check("no page errors or unexpected console errors", not errors, errors)
        browser.close()

    print(f"\n{'ALL PASSED' if not failures else str(len(failures)) + ' FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
