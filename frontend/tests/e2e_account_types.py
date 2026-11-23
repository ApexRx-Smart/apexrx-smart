"""Account types in a real browser, against a LOCAL backend and a throwaway
database (run like the other e2e tests; PHONE_VERIFICATION_REQUIRED off):

  1. Every sign-in page accepts only its own kind of account: all nine
     combinations. A refused sign-in shows the error on the same page, leaves
     no session in the browser and goes nowhere.
  2. A signed-in account that opens another group's sign-in page is offered
     its own workspace or signing out, never a registration.
  3. Signed in, the ApexRX logo leads to the account's own workspace, and the
     public landing page sends the visitor there (desktop and phone widths).
     Signed out, or with an expired session, the public site works as before.
  4. The dashboards' floating counters and scanning animation are gone.

Accounts are created through the API with made-up example.com addresses in the
throwaway database only. Never point it at production.
"""

import sys

from playwright.sync_api import sync_playwright

import e2e_dashboards as D  # shared API helpers  # noqa: E402

RUN = D.RUN
PW = D.PW
failures = D.failures
check = D.check
EMAIL = {k: f"types-{k}-{RUN}@example.com" for k in ("patient", "pharmacy", "supplier")}
PAGES = {
    "patient": ("/patient-sign-in.html", "#patient-auth", "#auth-submit", "**/reservations*"),
    "pharmacy": ("/pharmacy-sign-in.html", "#account", "#account-submit", "**/pharmacy-dashboard*"),
    "supplier": ("/suppliers.html#signin", "#account", "#account-submit", "**/supplier-dashboard*"),
}
WORKSPACE = {"patient": "reservations.html", "pharmacy": "pharmacy-dashboard.html", "supplier": "supplier-dashboard.html"}


def seed():
    admin = D.call("POST", "/auth/login", {"email": D.ADMIN_EMAIL, "password": D.ADMIN_PASSWORD,
                                           "account_type": "admin"})["access_token"]
    D.account(EMAIL["patient"], "Types Patient", "patient")
    D.org_with_owner(EMAIL["pharmacy"], "Types Pharmacist", f"Types Pharmacy {RUN}", "pharmacy",
                     [{"name": "Types Branch", "city": "Gasabo"}], admin=admin)
    D.org_with_owner(EMAIL["supplier"], "Types Supplier", f"Types Supplies {RUN}", "supplier",
                     [{"name": "Types Warehouse", "city": "Gasabo"}], admin=admin)


def fresh_page(browser, width=1280, height=900):
    ctx = browser.new_context(viewport={"width": width, "height": height})
    ctx.route("**/js/config.js", lambda r: r.fulfill(content_type="application/javascript",
                                                     body=f'window.APEX_CONFIG = {{ API_BASE_URL: "{D.API}" }};'))
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    return ctx, page, errors


def session_token(page):
    return page.evaluate("(JSON.parse(sessionStorage.getItem('apexrx_session') || '{}')).token || null")


def sign_in(page, kind, email):
    path, form, submit, _ = PAGES[kind]
    page.goto(D.SITE + path)
    page.wait_for_selector(f"{form} [name=email]:visible")
    page.fill(f"{form} [name=email]", email)
    page.fill(f"{form} [name=password]", PW)
    page.click(submit)


def main():
    seed()
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=D.os.environ.get("E2E_BROWSER_CHANNEL") or None, headless=True)
        all_errors = []

        # ---- 1. nine combinations
        for page_kind in PAGES:
            for account_kind in EMAIL:
                ctx, page, errors = fresh_page(browser)
                sign_in(page, page_kind, EMAIL[account_kind])
                label = f"1. {page_kind} sign-in with a {account_kind} account"
                if page_kind == account_kind:
                    page.wait_for_url(PAGES[page_kind][3], timeout=30000)
                    check(label + ": accepted, opens its workspace", session_token(page) is not None)
                else:
                    page.wait_for_function("document.querySelector('#form-error').textContent.trim().length > 0",
                                           timeout=30000)
                    page.wait_for_timeout(600)  # nothing may happen afterwards either
                    text = page.inner_text("#form-error")
                    check(label + ": refused on the same page with a clear message",
                          "can't sign in here" in text and PAGES[page_kind][0].split("#")[0] in page.url, text)
                    check(label + ": no session was stored in the browser", session_token(page) is None)
                    check(label + ": no registration step is shown",
                          page.locator("#details:visible, #verify-email:visible, #documents:visible").count() == 0)
                all_errors += errors
                ctx.close()

        # ---- 2. signed in, opening another group's sign-in page
        for account_kind, other in (("patient", "pharmacy"), ("pharmacy", "supplier"), ("supplier", "patient")):
            ctx, page, errors = fresh_page(browser)
            sign_in(page, account_kind, EMAIL[account_kind])
            page.wait_for_url(PAGES[account_kind][3], timeout=30000)
            page.goto(D.SITE + PAGES[other][0])
            try:
                page.wait_for_selector("#account-panel:not([hidden])", timeout=30000)
            except Exception:
                print("DEBUG", page.url, page.inner_text("#form-error"), errors, session_token(page) is not None)
                raise
            text = page.inner_text("#account-panel")
            link = "#account-panel-link" if other != "patient" else "#account-workspace"
            check(f"2. a signed-in {account_kind} on the {other} sign-in page is offered its workspace or signing out",
                  "signed in with" in text and page.get_attribute(link, "href") == WORKSPACE[account_kind]
                  and page.locator("#details:visible, #verify-email:visible").count() == 0, text)
            all_errors += errors
            ctx.close()

        # ---- 3. logo and landing page, desktop and phone
        for width, height, size in ((1280, 900, "desktop"), (390, 844, "phone")):
            for kind in EMAIL:
                ctx, page, errors = fresh_page(browser, width, height)
                sign_in(page, kind, EMAIL[kind])
                page.wait_for_url(PAGES[kind][3], timeout=30000)
                page.goto(D.SITE + "/index.html")
                page.wait_for_url(f"**/{WORKSPACE[kind]}*", timeout=30000)
                check(f"3. {size}: a signed-in {kind} opening the landing page goes to their workspace", True)
                page.goto(D.SITE + "/how-it-works.html")
                page.wait_for_load_state("load")
                href = page.get_attribute("a.brand", "href")
                check(f"3. {size}: the logo on public pages leads a signed-in {kind} to their workspace",
                      href == WORKSPACE[kind], href)
                page.click("a.brand")
                page.wait_for_url(f"**/{WORKSPACE[kind]}*", timeout=30000)
                all_errors += errors
                ctx.close()
            # signed out: the public landing page and registration stay reachable
            ctx, page, errors = fresh_page(browser, width, height)
            page.goto(D.SITE + "/index.html")
            page.wait_for_timeout(800)
            check(f"3. {size}: signed out, the landing page stays", page.url.split("?")[0].endswith("/index.html"))
            page.goto(D.SITE + "/pharmacies.html")
            page.wait_for_selector("#account [name=email]:visible")
            check(f"3. {size}: signed out, registration opens normally", "pharmacies.html" in page.url)
            # an expired session counts as signed out (no redirect loop)
            page.evaluate("""() => sessionStorage.setItem('apexrx_session', JSON.stringify(
                {token: 'x.e30.y', expiresAt: Date.now() - 1000, accountType: 'patient'}))""")
            page.goto(D.SITE + "/index.html")
            page.wait_for_timeout(800)
            check(f"3. {size}: an expired session stays on the landing page",
                  page.url.split("?")[0].endswith("/index.html") and page.get_attribute("a.brand", "href") == "#top")
            all_errors += errors
            ctx.close()

        # an operations-console session is not a customer: the landing page stays public for it
        ctx, page, errors = fresh_page(browser)
        page.goto(D.SITE + "/ops-console-7f3k9q.html")
        page.fill("#login-form [name=email]", D.ADMIN_EMAIL)
        page.fill("#login-form [name=password]", D.ADMIN_PASSWORD)
        page.click("#login-button")
        page.wait_for_selector("#dashboard-view:not([hidden])", timeout=30000)
        page.wait_for_timeout(1500)  # the console has read /auth/me by now
        page.goto(D.SITE + "/index.html")
        page.wait_for_timeout(1500)
        check("3. an administrator opening the landing page stays on it (no customer workspace)",
              page.url.split("?")[0].endswith("/index.html"), page.url)
        all_errors += errors
        ctx.close()

        # ---- 4. dashboard decorations removed (pharmacy; the supplier is checked in e2e_dashboards.py)
        for width, height in ((1280, 900), (390, 844)):
            ctx, page, errors = fresh_page(browser, width, height)
            sign_in(page, "pharmacy", EMAIL["pharmacy"])
            page.wait_for_url("**/pharmacy-dashboard*", timeout=30000)
            page.wait_for_selector(".hero", state="attached", timeout=30000)
            text = page.inner_text(".hero")
            check(f"4. {width}px: the pharmacy hero has no floating counters or scanning frame",
                  page.locator(".hero .chipf, .hero .scan, .hero .mini, .hero .plus").count() == 0
                  and "offers waiting" not in text and "running low" not in text)
            check(f"4. {width}px: the dashboard's work list and tabs are still there",
                  page.locator(".ov-act").count() >= 1)
            check(f"4. {width}px: no sideways scrolling",
                  not page.evaluate("document.documentElement.scrollWidth > innerWidth + 1"))
            all_errors += errors
            ctx.close()

        check("no script errors", not all_errors, all_errors[:3])
        browser.close()
    print(f"\n{'ALL PASSED' if not failures else str(len(failures)) + ' FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
