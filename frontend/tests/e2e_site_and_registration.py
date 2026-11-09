"""End-to-end check of the public site and the registration journeys, against a
LOCAL backend and a throwaway database:

  * landing page navigation (no "For Patients"), medicine search still works;
  * How it works, About and Legal pages, and every footer link, from the
    landing page and from other pages, on desktop and mobile;
  * the registration entry points (For Pharmacies, For Suppliers, the header's
    Sign in), the "Already have an account? Sign in" switch and the show/hide
    password control. The registration journeys themselves are tested in
    e2e_registration.py.

Never point this at production: it registers accounts and organizations.

Setup (as for e2e_admin.py): backend on http://127.0.0.1:8000 with APP_ENV=development
and EMAIL_PROVIDER=mock, frontend on http://127.0.0.1:5501, an admin account, then
  E2E_ADMIN_EMAIL=... E2E_ADMIN_PASSWORD=... python frontend/tests/e2e_site_and_registration.py
(E2E_BROWSER_CHANNEL=chrome uses the installed Chrome.)
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
API = os.environ.get("E2E_API", "http://127.0.0.1:8000")
ADMIN_EMAIL, ADMIN_PASSWORD = os.environ["E2E_ADMIN_EMAIL"], os.environ["E2E_ADMIN_PASSWORD"]
RUN = uuid.uuid4().hex[:6]
PASSWORD = "Site-Flow-Pass-2026"

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


def admin_token():
    return call("POST", "/auth/login", {"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})[1]["access_token"]


def find_org(name):
    status, page = call("GET", "/admin/organizations?" + urllib.parse.urlencode({"q": name, "limit": 5}), token=admin_token())
    return [o for o in page["items"] if o["name"] == name]


def wait_text(page, selector, text, timeout=15000):
    page.wait_for_function("([s, t]) => (document.querySelector(s) || {}).textContent?.includes(t)",
                           arg=[selector, text], timeout=timeout)


def new_context(browser, viewport):
    ctx = browser.new_context(viewport=viewport)
    ctx.route("**/js/config.js", lambda route: route.fulfill(
        content_type="application/javascript", body=f'window.APEX_CONFIG = {{ API_BASE_URL: "{API}" }};'))
    return ctx


def watch(page, errors):
    page.on("pageerror", lambda e: errors.append(f"{page.url}: {e}"))
    # The browser logs every 4xx response; the only expected one is the
    # deliberate wrong-password sign-in (401), which is checked separately.
    page.on("console", lambda m: errors.append(f"{page.url}: {m.text}")
            if m.type == "error" and "status of 401" not in m.text
            # Chrome notice from the pharmacy page's embedded background video, not our code.
            and "Permissions policy violation" not in m.text else None)
    page.on("response", lambda r: errors.append(f"{r.status} {r.url}") if r.status >= 400 and "/assets/" in r.url else None)


def password_toggle_checks(page, form, label):
    """The eye button shows and hides the password without changing it, and works from the keyboard."""
    field = page.locator(f"{form} input[name=password]")
    field.fill("Visible-Secret-123")
    eye = page.locator(f"{form} .pw-wrap:has(input[name=password]) .pw-eye")
    check(f"{label}: password hidden by default with a 'Show password' button",
          field.get_attribute("type") == "password" and eye.get_attribute("aria-label") == "Show password")
    eye.click()
    check(f"{label}: clicking shows it, value unchanged",
          field.get_attribute("type") == "text" and field.input_value() == "Visible-Secret-123"
          and eye.get_attribute("aria-label") == "Hide password" and eye.get_attribute("aria-pressed") == "true")
    eye.focus()
    page.keyboard.press("Enter")
    check(f"{label}: the keyboard hides it again and keeps focus on the button",
          field.get_attribute("type") == "password" and page.evaluate("document.activeElement.classList.contains('pw-eye')")
          and field.input_value() == "Visible-Secret-123")
    page.keyboard.press("Space")
    check(f"{label}: Space toggles too", field.get_attribute("type") == "text")
    field.fill("")


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=os.environ.get("E2E_BROWSER_CHANNEL") or None, headless=True)
        errors = []

        # ------------------------------------------------ landing navigation
        ctx = new_context(browser, {"width": 1366, "height": 900})
        page = ctx.new_page()
        watch(page, errors)
        page.goto(SITE + "/index.html")
        nav = page.locator("nav.main-nav a")
        labels = [a.strip() for a in nav.all_inner_texts()]
        check("nav: 'For Patients' removed from the main navigation", "For Patients" not in labels, labels)
        hrefs = {a: page.get_attribute(f"nav.main-nav a:has-text('{a}')", "href") for a in labels}
        check("nav: links go to the registration, How it works and About pages",
              hrefs.get("For Pharmacies", "").startswith("pharmacies.html") and hrefs.get("For Suppliers", "").startswith("suppliers.html")
              and hrefs.get("How it works") == "how-it-works.html" and hrefs.get("About") == "about.html", hrefs)
        check("landing: the two information sections are gone",
              page.locator("#audience").count() == 0 and page.locator("section#how").count() == 0)

        # The medicine search still works (needs a listed offer from the admin e2e seed, or reports none).
        page.fill("#medicineSearchInput", "paracetamol")
        page.click("#medicineSearchForm button[type=submit]")
        page.wait_for_function("document.querySelector('#medicineSearchStatus').textContent.trim().length > 0 || document.querySelectorAll('#medicineSearchResults .result-row').length > 0", timeout=15000)
        check("landing: medicine search still answers", True)

        page.click("nav.main-nav a:has-text('How it works')")
        page.wait_for_url("**/how-it-works.html")
        check("how it works: both moved sections are on the page",
              page.locator("#audience h2").inner_text().startswith("Built for everyone")
              and "three simple steps" in page.locator("section#how h2").inner_text())
        check("how it works: marked as the current page", page.get_attribute("nav.main-nav a[href='how-it-works.html']", "aria-current") == "page")
        page.click("nav.main-nav a:has-text('About')")
        page.wait_for_url("**/about.html")
        check("about: the sections are there", all(page.locator(s).count() == 1 for s in ("#about", "#mission", "#vision", "#team", "#organization")))
        check("about: team cards use placeholders, not broken images",
              page.locator(".team-card .portrait").count() >= 3 and page.evaluate(
                  "[...document.images].every(i => !i.complete || i.naturalWidth > 0)"))

        # Refreshing on the new pages works (static files).
        for path in ("how-it-works.html", "about.html", "legal.html#cookies", "suppliers.html", "pharmacies.html#signin"):
            r = page.goto(SITE + "/" + path)
            check(f"refresh: /{path} loads", r.status == 200)

        # ---------------------------------------------------- footer links
        expected = {
            "For Patients": "index.html#hero-search", "For Pharmacies": "pharmacies.html", "For Suppliers": "suppliers.html",
            "How it works": "how-it-works.html", "About": "about.html", "Careers": "about.html", "Blog": "about.html",
            "Contact": "about.html", "Privacy": "legal.html#privacy", "Terms of Service": "legal.html#terms",
            "Cookie Policy": "legal.html#cookies",
        }
        page.goto(SITE + "/about.html")
        bad = {}
        for label, target in expected.items():
            href = page.get_attribute(f"footer .footer-col a:has-text('{label}')", "href")
            if href.split("?")[0] != target and not href.startswith(target.split("#")[0] + "?"):
                bad[label] = href
        check("footer: every link has a destination (from another page)", not bad, bad)
        page.click("footer .footer-col a:has-text('For Patients')")
        page.wait_for_url("**/index.html#hero-search")
        page.wait_for_timeout(800)
        check("footer: 'For Patients' from another page lands on the medicine search",
              page.evaluate("(() => { const r = document.querySelector('#medicineSearchInput').getBoundingClientRect(); return r.top >= 0 && r.bottom <= innerHeight; })()"))
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        check("footer: on the landing page 'For Patients' is an in-page link",
              page.get_attribute("footer .footer-col a:has-text('For Patients')", "href") == "#hero-search")
        page.click("footer .footer-col a:has-text('For Patients')")
        page.wait_for_timeout(900)
        check("footer: ...and scrolls up to the search", page.evaluate("scrollY") < 300)
        page.goto(SITE + "/index.html")
        page.click("footer .footer-col a:has-text('Terms of Service')")
        page.wait_for_url("**/legal.html#terms")
        check("legal: the Terms page shows, clearly marked as a placeholder",
              page.is_visible("#terms") and page.is_hidden("#privacy") and "Placeholder" in page.inner_text("#terms .placeholder-callout"))
        page.click(".legal-nav a[data-doc=cookies]")
        page.wait_for_function("location.hash === '#cookies'")
        check("legal: switching between legal pages", page.is_visible("#cookies") and page.title().startswith("Cookie Policy"))
        page.click("footer .footer-col a:has-text('Careers')")
        page.wait_for_url("**/about.html")
        check("footer: Company links open About", True)
        check("footer: Admin Portal link still there", page.locator("footer .footer-admin-link[href='admin.html']").count() == 1)

        # Language switch on a new page.
        page.select_option("#langSelect", "fr")
        check("translations: header and footer follow the language on new pages",
              page.inner_text("nav.main-nav a[href='how-it-works.html']") != "How it works"
              and page.inner_text("footer .footer-col a[href='legal.html#privacy']") != "Privacy")
        page.select_option("#langSelect", "en")
        ctx.close()

        # ---------------------------------------------------- mobile navigation
        ctx = new_context(browser, {"width": 375, "height": 812})
        page = ctx.new_page()
        watch(page, errors)
        page.goto(SITE + "/how-it-works.html")
        page.click("#menuToggle")
        page.wait_for_selector("#mobileNav.open")
        mobile = [a.strip() for a in page.locator("#mobileNav > a").all_inner_texts()]
        check("mobile: menu has the same items, without For Patients", mobile == ["For Pharmacies", "For Suppliers", "How it works", "About"], mobile)
        page.click("#mobileNav a:has-text('About')")
        page.wait_for_url("**/about.html")
        wide = []
        for path in ("index.html", "how-it-works.html", "about.html", "legal.html", "suppliers.html", "pharmacies.html"):
            page.goto(SITE + "/" + path)
            page.wait_for_load_state("networkidle")
            if page.evaluate("document.documentElement.scrollWidth > window.innerWidth"):
                wide.append(path)
        check("mobile: no horizontal scroll on any page", not wide, wide)
        ctx.close()

        # ------------------------------------- registration entry points
        # (The full journeys are in e2e_registration.py.)
        ctx = new_context(browser, {"width": 1366, "height": 900})
        page = ctx.new_page()
        watch(page, errors)
        page.goto(SITE + "/index.html")
        page.click("nav.main-nav a:has-text('For Pharmacies')")
        page.wait_for_selector("#account:not([hidden])")
        fields = [page.locator(f"#account [name={n}]").count() for n in ("email", "password", "confirm")]
        check("pharmacy: For Pharmacies opens the registration with all account fields", fields == [1, 1, 1])
        password_toggle_checks(page, "#account", "pharmacy create")
        confirm_eye = page.locator("#account .pw-wrap:has(input[name=confirm]) .pw-eye")
        confirm_eye.click()
        check("pharmacy: the confirm field has its own toggle", page.get_attribute("#account [name=confirm]", "type") == "text")
        confirm_eye.click()
        page.click("#auth-switch")
        check("pharmacy: 'Already have an account? Sign in' switches to sign in",
              page.is_hidden("#confirm-field") and page.inner_text("#step-title") == "Sign in to ApexRX"
              and page.evaluate("location.hash") == "#signin")
        page.click("#auth-switch")
        check("pharmacy: ...and back to create account", page.is_visible("#confirm-field"))
        steps = [s.strip() for s in page.locator(".steps li").all_inner_texts()]
        check("pharmacy: steps are Account, Verify email, Details, Documents, Review (no plan or payment)",
              steps == ["Account", "Verify email", "Details", "Documents", "Review"], steps)
        ctx.close()

        ctx = new_context(browser, {"width": 1366, "height": 900})
        page = ctx.new_page()
        watch(page, errors)
        page.goto(SITE + "/index.html")
        page.click("#signInBtn")
        page.wait_for_url("**/pharmacies.html*#signin")
        check("sign in: header button opens sign-in mode", page.is_hidden("#confirm-field") and page.inner_text("#account-submit").startswith("Sign in"))
        page.goto(SITE + "/index.html")
        page.click("nav.main-nav a:has-text('For Suppliers')")
        page.wait_for_url("**/suppliers.html*")
        page.wait_for_selector("#account:not([hidden])")
        check("supplier: For Suppliers opens the supplier registration",
              "SUPPLIER" in page.inner_text(".story .eyebrow") and page.inner_text("#step-title") == "Create your supplier account")
        password_toggle_checks(page, "#account", "supplier create")
        page.click("#auth-switch")
        check("supplier: 'Already have an account? Sign in' switches to sign in", page.is_hidden("#confirm-field"))
        ctx.close()

        # Admin sign-in has the toggle too, and still works.
        ctx = new_context(browser, {"width": 1366, "height": 900})
        page = ctx.new_page()
        watch(page, errors)
        page.goto(SITE + "/admin.html")
        page.fill("#login-form [name=email]", ADMIN_EMAIL)
        page.fill("#login-form [name=password]", ADMIN_PASSWORD)
        page.click("#login-form .pw-eye")
        check("admin: password toggle on the admin sign-in", page.get_attribute("#login-form [name=password]", "type") == "text")
        page.click("#login-button")
        page.wait_for_selector("#dashboard-view:not([hidden])")
        check("admin: sign-in still works", True)
        ctx.close()

        check("no page errors, console errors or missing assets", not errors, errors)
        browser.close()

    print(f"\n{'ALL PASSED' if not failures else str(len(failures)) + ' FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
