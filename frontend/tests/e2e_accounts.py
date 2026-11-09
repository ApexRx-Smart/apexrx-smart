"""End-to-end check of accounts, staff access and sessions, against LOCAL
backends and a throwaway database:

  * sign-out from the workspace ends the server session, other people are not
    affected, back navigation shows nothing private, the public site shows who
    is signed in, signing in again and switching accounts work;
  * staff invitations from the workspace: a new employee sets up their own
    account from the emailed link; an existing account accepts by signing in
    (no duplicate account, other memberships kept); the wrong account is
    refused; revoke and resend; staff sign-in; the pharmacy chooser and switcher;
    no access to a pharmacy the user does not belong to;
  * forgot password: same answer for unknown addresses, reset, single use,
    old password refused, memberships kept;
  * inactivity (second backend with SESSION_IDLE_TIMEOUT_MINUTES=1): activity
    in one tab keeps the other alive, background requests do not, the warning
    and "Stay signed in", automatic sign-out in every tab with a message, the
    server refuses the old token, and sign-out in one tab signs out the other.

Setup: backend on http://127.0.0.1:8000 (APP_ENV=development, EMAIL_PROVIDER=mock,
INVITATION_RESEND_COOLDOWN_SECONDS=2), a second one on http://127.0.0.1:8001 with
SESSION_IDLE_TIMEOUT_MINUTES=1 (same database), frontend on http://127.0.0.1:5501, then
  E2E_ADMIN_EMAIL=... E2E_ADMIN_PASSWORD=... python frontend/tests/e2e_accounts.py
Never point this at production.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from playwright.sync_api import sync_playwright

SITE = os.environ.get("E2E_SITE", "http://127.0.0.1:5501")
API = os.environ.get("E2E_API", "http://127.0.0.1:8000")
IDLE_API = os.environ.get("E2E_IDLE_API", "http://127.0.0.1:8001")
ADMIN_EMAIL, ADMIN_PASSWORD = os.environ["E2E_ADMIN_EMAIL"], os.environ["E2E_ADMIN_PASSWORD"]
RUN = uuid.uuid4().hex[:6]
PW = "Accounts-Pass-2026"
failures = []


def check(label, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + label + (f"  {detail}" if detail and not condition else ""))
    if not condition:
        failures.append(label)


def call(method, path, body=None, token=None, api=API):
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    if data:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(api + path, data=data, method=method, headers=headers)
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


def ok(method, path, body=None, token=None):
    status, data = call(method, path, body, token)
    if status >= 300:
        raise SystemExit(f"{method} {path} -> {status}: {data}")
    return data


def login(email, password=PW):
    return ok("POST", "/auth/login", {"email": email, "password": password})["access_token"]


def mail_to(email):
    return ok("GET", "/dev/email/latest-to?" + urllib.parse.urlencode({"to": email}))


def owner_with_pharmacy(email, name, org_name):
    ok("POST", "/auth/register", {"name": name, "email": email, "password": PW})
    token = login(email)
    ok("POST", "/auth/email/send", {"next": "pharmacy"}, token)
    ok("POST", "/auth/email/verify", {"token": mail_to(email)["token"]})
    org = ok("POST", "/organizations", {"name": org_name, "type": "pharmacy", "phone": "0788 100 200"}, token)["organization_id"]
    ok("POST", f"/organizations/{org}/locations", {"name": "Main branch", "region": "Kigali City", "city": "Gasabo"}, token)
    admin = login(ADMIN_EMAIL, ADMIN_PASSWORD)
    ok("POST", f"/admin/organizations/{org}/review", {"decision": "approved"}, admin)
    return org


def context(browser, api=API, viewport=None):
    ctx = browser.new_context(viewport=viewport or {"width": 1366, "height": 900})
    ctx.route("**/js/config.js", lambda route: route.fulfill(
        content_type="application/javascript", body=f'window.APEX_CONFIG = {{ API_BASE_URL: "{api}" }};'))
    return ctx


def watch(page, errors):
    page.on("pageerror", lambda e: errors.append(f"{page.url}: {e}"))
    page.on("console", lambda m: errors.append(f"{page.url}: {m.text}") if m.type == "error" and not any(
        x in m.text for x in ("status of 401", "status of 400", "status of 403", "status of 409", "Permissions policy")) else None)


def visible(page, selector, timeout=20000):
    page.wait_for_selector(f"{selector}:not([hidden])", timeout=timeout)


def wait_text(page, selector, text, timeout=20000):
    page.wait_for_function("([s, t]) => (document.querySelector(s) || {}).textContent?.includes(t)",
                           arg=[selector, text], timeout=timeout)


def token_of(page):
    return page.evaluate("JSON.parse(sessionStorage.getItem('apexrx_session') || 'null')?.token || null")


def refused(token, api=API, seconds=5):
    """True once the server refuses the token (sign-out is sent in the background)."""
    end = time.time() + seconds
    while time.time() < end:
        if call("GET", "/auth/me", token=token, api=api)[0] == 401:
            return True
        time.sleep(0.25)
    return False


def staff_sign_in(page, email, password=PW):
    page.goto("about:blank")  # a fresh load (a hash change alone would not reload the page)
    page.goto(SITE + "/pharmacies.html#staff")
    page.wait_for_selector("#account:not([hidden]), #dashboard:not([hidden])")
    if page.is_visible("#dashboard"):
        page.click("#dash-signout")
        page.wait_for_selector("#account:not([hidden])")
    if page.get_attribute("#tab-signin", "aria-selected") != "true":
        page.click("#tab-signin")
    page.fill("#account [name=email]", email)
    page.fill("#account [name=password]", password)
    page.click("#account-submit")


def open_employees(page):
    page.click(".sidebar [data-view=employees]")
    page.wait_for_selector("#invite-form", timeout=20000)


def main():
    owner_email = f"acc-owner-{RUN}@example.com"
    org = owner_with_pharmacy(owner_email, "Amani Owner", f"Accounts Pharmacy {RUN}")
    other_email = f"acc-other-{RUN}@example.com"
    other_org = owner_with_pharmacy(other_email, "Bea Other", f"Other Pharmacy {RUN}")

    with sync_playwright() as p:
        browser = p.chromium.launch(channel=os.environ.get("E2E_BROWSER_CHANNEL") or None, headless=True)
        errors = []

        # ============================================ sign-out and identity
        ctx = context(browser)
        page = ctx.new_page()
        watch(page, errors)
        staff_sign_in(page, owner_email)
        visible(page, "#dashboard")
        check("sign in: the owner reaches the workspace, identity shown",
              f"Accounts Pharmacy {RUN}" in page.inner_text("#pharmacy-name")
              and page.inner_text("#dash-user") == f"{owner_email} · Owner" and page.inner_text("#dash-signout") == "Sign out")
        old_token = token_of(page)
        page.goto(SITE + "/index.html")
        page.wait_for_function("document.querySelector('#signInBtn').textContent.includes('@')")
        check("public site: the header shows who is signed in, and offers Sign out",
              page.inner_text("#signInBtn") == owner_email and page.inner_text("#getStartedBtn") == "Sign out")
        page.click("#signInBtn")
        visible(page, "#dashboard")
        check("public site: the account button returns to the workspace", True)
        page.goto(SITE + "/index.html")
        page.click("#getStartedBtn")
        page.wait_for_function("document.querySelector('#signInBtn').textContent === 'Sign in'")
        check("public site: Sign out from the header ends the session",
              refused(old_token) and token_of(page) is None)
        page.go_back()
        page.wait_for_load_state("load")
        visible(page, "#account")
        check("back button: the workspace is not shown again after signing out",
              page.is_hidden("#dashboard") and f"Accounts Pharmacy {RUN}" not in page.inner_text("body"))
        page.goto(SITE + "/pharmacies.html")
        check("protected page: visiting it again asks to sign in", page.is_visible("#account") and page.is_hidden("#dashboard"))

        # Sign in again, then sign out from the workspace button.
        staff_sign_in(page, owner_email)
        visible(page, "#dashboard")
        second = token_of(page)
        other_session = login(owner_email)  # the same person on another device
        page.click("#dash-signout")
        visible(page, "#account")
        check("workspace sign-out: back to sign in, this session ended on the server",
              refused(second) and token_of(page) is None)
        me = call("GET", "/auth/me", token=other_session)[1]
        check("workspace sign-out: other sessions, membership, role and pharmacy unchanged",
              [(m["organization_id"], m["role"], m["organization_status"]) for m in me["memberships"]] == [(org, "owner", "approved")])

        # Switching accounts on the same tab.
        staff_sign_in(page, other_email)
        visible(page, "#dashboard")
        check("switching accounts: the second account sees only its own pharmacy",
              f"Other Pharmacy {RUN}" in page.inner_text("#pharmacy-name") and page.inner_text("#dash-user").startswith(other_email))
        page.click("#dash-signout")
        visible(page, "#account")
        ctx.close()

        # ============================================ invitations (new account)
        ctx = context(browser)
        page = ctx.new_page()
        watch(page, errors)
        staff_sign_in(page, owner_email)
        visible(page, "#dashboard")
        open_employees(page)
        new_email = f"acc-newstaff-{RUN}@example.com"
        page.fill("#invite-form [name=email]", new_email)
        page.select_option("#invite-form [name=role]", "staff")
        page.click("#invite-form button.primary-sm")
        wait_text(page, "#invite-status", f"Invitation emailed to {new_email}")
        check("invite: an employee without an account is invited by email and role",
              "Pending" in page.inner_text(f"tr[data-invite='{new_email}']") and "Email sent" in page.inner_text(f"tr[data-invite='{new_email}']"))
        status, users = call("GET", "/admin/users?" + urllib.parse.urlencode({"q": new_email}), token=login(ADMIN_EMAIL, ADMIN_PASSWORD))
        members = ok("GET", f"/organizations/{org}/members", token=login(owner_email))
        check("invite: no account and no membership before acceptance",
              users["total"] == 0 and all(m["email"] != new_email for m in members))
        link = mail_to(new_email)["link"]

        invitee_ctx = context(browser)
        inv = invitee_ctx.new_page()
        watch(inv, errors)
        inv.goto(link)
        visible(inv, "#new-account")
        check("accept: the link shows the pharmacy, role and address, and asks for their own password",
              inv.inner_text("#invite-org") == f"Accounts Pharmacy {RUN}" and inv.inner_text("#invite-role") == "Staff"
              and inv.inner_text("#invite-email") == new_email and "token" not in inv.url)
        inv.fill("#new-account [name=name]", "Neza Staff")
        inv.fill("#new-account [name=password]", PW)
        inv.fill("#new-account [name=confirm]", PW + "x")
        inv.click("#new-account-submit")
        wait_text(inv, "#form-error", "do not match")
        inv.fill("#new-account [name=confirm]", PW)
        inv.click("#new-account-submit")
        visible(inv, "#invite-actions")
        check("accept: the account is created and joined", f"You have joined Accounts Pharmacy {RUN}." == inv.inner_text("#invite-title"))
        inv.click("#invite-continue")
        visible(inv, "#dashboard")
        check("staff: opens the right pharmacy with the Staff role, without registering a pharmacy",
              f"Accounts Pharmacy {RUN}" in inv.inner_text("#pharmacy-name") and inv.inner_text("#dash-user") == f"{new_email} · Staff")
        inv.click(".sidebar [data-view=employees]")
        wait_text(inv, "#workspace-section", "Only owners and managers can invite")
        check("staff: cannot invite employees", inv.locator("#invite-form").count() == 0)
        staff_token = token_of(inv)
        check("staff: the backend refuses invitations and other pharmacies",
              call("POST", f"/organizations/{org}/invitations", {"email": "x@example.com", "role": "staff"}, staff_token)[0] == 403
              and call("GET", f"/organizations/{other_org}", token=staff_token)[0] == 404)
        inv.evaluate(f"sessionStorage.setItem('apexrx_selected_pharmacy', '{other_org}')")
        inv.reload()
        visible(inv, "#dashboard")
        check("staff: changing the stored pharmacy id in the browser does not open another pharmacy",
              f"Other Pharmacy {RUN}" not in inv.inner_text("#pharmacy-name"))
        inv.click("#dash-signout")
        visible(inv, "#account")
        staff_sign_in(inv, new_email)
        visible(inv, "#dashboard")
        check("staff sign-in: the employee signs in on their own and reaches the workspace", True)
        inv.goto(link)
        inv.wait_for_function("document.querySelector('#invite-title').textContent.includes('already been accepted')")
        check("accept: the invitation link works only once", True)
        invitee_ctx.close()
        page.reload()
        visible(page, "#dashboard")
        open_employees(page)
        wait_text(page, f"tr[data-invite='{new_email}']", "Accepted")
        check("invitations: the owner sees it accepted with a new account",
              "new account" in page.inner_text(f"tr[data-invite='{new_email}']")
              and new_email in page.inner_text("#workspace-section table"))

        # ======================================= invitations (existing account)
        page.fill("#invite-form [name=email]", other_email)
        page.select_option("#invite-form [name=role]", "manager")
        page.click("#invite-form button.primary-sm")
        wait_text(page, "#invite-status", "Invitation emailed")
        link = mail_to(other_email)["link"]
        existing_ctx = context(browser)
        ex = existing_ctx.new_page()
        watch(ex, errors)
        # Signed in as someone else first: refused.
        staff_sign_in(ex, new_email)
        visible(ex, "#dashboard")
        ex.goto(link)
        visible(ex, "#signed-in")
        check("accept: a different signed-in account cannot accept it",
              ex.is_hidden("#accept-button") and f"This invitation is for {other_email}" in ex.inner_text("#form-error"))
        ex.click("#switch-account")
        visible(ex, "#sign-in")
        check("accept: an existing account is asked to sign in, not to create another",
              ex.input_value("#sign-in [name=email]") == other_email and ex.is_hidden("#new-account"))
        ex.fill("#sign-in [name=password]", PW)
        ex.click("#sign-in-submit")
        visible(ex, "#invite-actions")
        status, users = call("GET", "/admin/users?" + urllib.parse.urlencode({"q": other_email}), token=login(ADMIN_EMAIL, ADMIN_PASSWORD))
        roles = {(m["organization_id"], m["role"]) for m in ok("GET", "/auth/me", token=login(other_email))["memberships"]}
        check("accept: no duplicate account; the new membership is added and the existing one kept",
              users["total"] == 1 and roles == {(org, "manager"), (other_org, "owner")}, roles)
        existing_ctx.close()

        # Several pharmacies: choose at sign-in, then switch.
        ctx2 = context(browser)
        multi = ctx2.new_page()
        watch(multi, errors)
        staff_sign_in(multi, other_email)
        visible(multi, "#org-choice")
        choices = [t.strip() for t in multi.locator("#org-choice-list strong").all_inner_texts()]
        check("several pharmacies: a chooser lists the user's own pharmacies with role and status",
              sorted(choices) == sorted([f"Accounts Pharmacy {RUN}", f"Other Pharmacy {RUN}"])
              and "Manager" in multi.inner_text("#org-choice-list") and "Owner" in multi.inner_text("#org-choice-list"))
        multi.click(f"#org-choice-list button[data-org='{org}']")
        visible(multi, "#dashboard")
        check("several pharmacies: the chosen pharmacy opens with that role",
              f"Accounts Pharmacy {RUN}" in multi.inner_text("#pharmacy-name") and multi.inner_text("#dash-user").endswith("Manager"))
        multi.select_option("#org-switch", str(other_org))
        multi.wait_for_function(f"document.querySelector('#pharmacy-name').textContent.includes('Other Pharmacy {RUN}')")
        check("several pharmacies: switching without signing out loads the other role",
              multi.inner_text("#dash-user").endswith("Owner"))
        ctx2.close()

        # Revoke and resend.
        revoke_email, resend_email = f"acc-revoke-{RUN}@example.com", f"acc-resend-{RUN}@example.com"
        for email in (revoke_email, resend_email):
            page.fill("#invite-form [name=email]", email)
            page.click("#invite-form button.primary-sm")
            wait_text(page, "#invite-status", f"Invitation emailed to {email}")
        revoke_link = mail_to(revoke_email)["link"]
        page.once("dialog", lambda d: d.accept())
        page.click(f"tr[data-invite='{revoke_email}'] button:has-text('Revoke')")
        wait_text(page, f"tr[data-invite='{revoke_email}']", "Revoked")
        first_link = mail_to(resend_email)["link"]
        time.sleep(2.5)  # INVITATION_RESEND_COOLDOWN_SECONDS=2 on the test backend
        page.click(f"tr[data-invite='{resend_email}'] button:has-text('Resend')")
        wait_text(page, "#invite-status", "The earlier link no longer works")
        second_link = mail_to(resend_email)["link"]
        tab = ctx.new_page()
        tab.goto(revoke_link)
        tab.wait_for_function("document.querySelector('#invite-title').textContent.includes('withdrawn')")
        check("revoke: a revoked invitation's link is refused", True)
        tab.goto("about:blank")
        tab.goto(first_link)
        tab.wait_for_function("document.querySelector('#invite-title').textContent.includes('not valid')")
        check("resend: the earlier link stops working and a new one is sent", first_link != second_link)
        tab.close()
        ctx.close()

        # ================================================ forgot password
        ctx = context(browser)
        page = ctx.new_page()
        watch(page, errors)
        page.goto(SITE + "/pharmacies.html#staff")
        page.click("#forgot-link")
        page.wait_for_url("**/reset-password.html*")
        visible(page, "#forgot-form")
        page.fill("#forgot-form [name=email]", f"nobody-{RUN}@example.com")
        page.click("#forgot-submit")
        wait_text(page, "#reset-title", "Check your email")
        unknown_answer = page.inner_text("#reset-message")
        page.goto(SITE + "/reset-password.html?next=pharmacy")
        page.fill("#forgot-form [name=email]", new_email)
        page.click("#forgot-submit")
        wait_text(page, "#reset-title", "Check your email")
        check("forgot: the same answer whether or not the address has an account", page.inner_text("#reset-message") == unknown_answer)
        time.sleep(1)  # the email is sent after the response
        reset_link = mail_to(new_email)["link"]
        check("forgot: the reset email links to reset-password.html", "/reset-password.html#token=" in reset_link)
        page.goto(reset_link)
        visible(page, "#reset-form")
        page.fill("#reset-form [name=password]", "Brand-New-Pass-77")
        page.fill("#reset-form [name=confirm]", "Brand-New-Pass-77")
        page.click("#reset-submit")
        wait_text(page, "#reset-title", "Your password has been changed.")
        check("reset: the old password no longer works, the new one does",
              call("POST", "/auth/login", {"email": new_email, "password": PW})[0] == 401
              and call("POST", "/auth/login", {"email": new_email, "password": "Brand-New-Pass-77"})[0] == 200)
        page.goto("about:blank")
        page.goto(reset_link)
        page.wait_for_function("document.querySelector('#reset-title').textContent.includes('already been used')")
        check("reset: the link works only once", True)
        staff_sign_in(page, new_email, "Brand-New-Pass-77")
        visible(page, "#dashboard")
        check("reset: membership and role are unchanged", page.inner_text("#dash-user") == f"{new_email} · Staff")
        ctx.close()

        # ===================================== inactivity across two tabs (1 min)
        ctx = context(browser, api=IDLE_API)
        a = ctx.new_page()
        watch(a, errors)
        staff_sign_in(a, owner_email)
        visible(a, "#dashboard")
        with ctx.expect_page() as opened:
            a.evaluate("window.open('pharmacies.html', '_blank')")
        b = opened.value
        watch(b, errors)
        visible(b, "#dashboard")
        check("tabs: a second tab of the same session opens the workspace",
              b.evaluate("JSON.parse(sessionStorage.getItem('apexrx_session')).sid") == a.evaluate("JSON.parse(sessionStorage.getItem('apexrx_session')).sid"))
        b_token = token_of(b)
        # Activity only in tab A for 80 s (longer than the 1-minute limit).
        start = time.time()
        while time.time() - start < 80:
            a.bring_to_front()
            a.keyboard.press("Shift")  # real input: a keydown
            time.sleep(10)
        check("tabs: activity in one tab keeps the other tab signed in",
              b.is_visible("#dashboard") and token_of(b) is not None)
        check("server: the session is still valid after more than the limit thanks to activity",
              call("GET", "/auth/me", token=b_token, api=IDLE_API)[0] == 200)
        # No more user activity; background requests every 10 s must not help.
        b.wait_for_selector("#apex-idle-warning", timeout=70000)
        a.wait_for_selector("#apex-idle-warning", timeout=10000)  # each tab checks every 5 s
        check("warning: shown before automatic sign-out, with a countdown",
              "signed out soon" in b.inner_text("#apex-idle-warning") and a.is_visible("#apex-idle-warning"))
        b.click("#apex-idle-stay")
        a.wait_for_selector("#apex-idle-warning", state="detached", timeout=10000)
        check("warning: 'Stay signed in' in one tab continues the session in both", b.locator("#apex-idle-warning").count() == 0)
        idle_start = time.time()
        while not a.is_visible("#account") and time.time() - idle_start < 100:
            b.evaluate("ApexAPI.auth.me().catch(() => {})")  # automated, not activity
            time.sleep(10)
        elapsed = time.time() - idle_start
        visible(a, "#account", timeout=5000)
        visible(b, "#account", timeout=15000)
        check("inactivity: both tabs are signed out about a minute after the last activity, despite background requests",
              55 <= elapsed <= 100, f"{elapsed:.0f}s")
        check("inactivity: a clear message explains why",
              "minutes of inactivity" in a.inner_text("#form-error") and "minutes of inactivity" in b.inner_text("#form-error"))
        status, body = call("GET", "/auth/me", token=b_token, api=IDLE_API)
        check("inactivity: the server refuses the old token", status == 401, body)
        # Manual sign-out in one tab signs out the other.
        staff_sign_in(a, owner_email)
        visible(a, "#dashboard")
        with ctx.expect_page() as opened:
            a.evaluate("window.open('pharmacies.html', '_blank')")
        c = opened.value
        visible(c, "#dashboard")
        a.click("#dash-signout")
        visible(c, "#account", timeout=10000)
        check("tabs: signing out in one tab signs out the other", "another tab" in c.inner_text("#form-error"))
        ctx.close()

        check("no page errors or unexpected console errors", not errors, errors)
        browser.close()

    print(f"\n{'ALL PASSED' if not failures else str(len(failures)) + ' FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
