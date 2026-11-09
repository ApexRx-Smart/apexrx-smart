"""End-to-end check of the public site and the registration journeys, against a
LOCAL backend and a throwaway database:

  * landing page navigation (no "For Patients"), medicine search still works;
  * How it works, About and Legal pages, and every footer link, from the
    landing page and from other pages, on desktop and mobile;
  * pharmacy registration through the UI (account, SMS code with the mock
    provider, profile) and its "Already have an account? Sign in" switch;
  * supplier registration through the UI, and that the organization is stored
    with type "supplier" (and not as a pharmacy);
  * sign-in for existing accounts and the show/hide password control.

Never point this at production: it registers accounts and organizations.

Setup (as for e2e_admin.py): backend on http://127.0.0.1:8000 with APP_ENV=development
and SMS_PROVIDER=mock, frontend on http://127.0.0.1:5501, an admin account, then
  E2E_ADMIN_EMAIL=... E2E_ADMIN_PASSWORD=... python frontend/tests/e2e_site_and_registration.py
(E2E_BROWSER_CHANNEL=chrome uses the installed Chrome.)
"""

import json
import os
import random
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
PHARMACY_PHONE = f"0788{random.randint(0, 999999):06d}"
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

        # ---------------------------------------------------- pharmacy registration
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

        email = f"site-pharmacy-{RUN}@example.com"
        page.fill("#account [name=email]", email)
        page.fill("#account [name=password]", PASSWORD)
        page.fill("#account [name=confirm]", PASSWORD)
        page.click("#account .pw-wrap:has(input[name=password]) .pw-eye")  # visible when submitting
        page.click("#account-submit")
        page.wait_for_selector("#verify:not([hidden])")
        check("pharmacy: submitting hides the password again", page.get_attribute("#account [name=password]", "type") == "password")
        page.fill("#verify [name=phone]", PHARMACY_PHONE)
        page.click("#send-code")
        page.wait_for_selector("#code-area:not([hidden])")
        token = page.evaluate("JSON.parse(sessionStorage.getItem('apexrx_session')).token")
        code = call("GET", "/dev/sms/latest", token=token)[1]["code"]
        page.fill("#verify [name=code]", code)
        page.click("#verify-code")
        page.wait_for_selector("#profile:not([hidden])")
        check("pharmacy: profile fields still present",
              all(page.locator(f"#profile [name={n}]").count() == 1 for n in ("name", "license", "phone", "address", "latitude", "longitude"))
              and page.locator("#profile input[data-document-type=pharmacy_license]").count() == 1)
        pharmacy_name = f"Site Pharmacy {RUN}"
        page.fill("#profile [name=name]", pharmacy_name)
        page.fill("#profile [name=license]", "PH-SITE")
        page.fill("#profile [name=address]", "KG 2 Ave, Kigali")
        page.click("#profile button.primary")
        page.wait_for_selector("#payment:not([hidden])")
        orgs = find_org(pharmacy_name)
        check("pharmacy: registered through the existing API as a pharmacy",
              len(orgs) == 1 and orgs[0]["type"] == "pharmacy" and orgs[0]["status"] == "pending", orgs)
        ctx.close()

        # Existing pharmacy user signs in from the header's Sign in button (sign-in mode).
        ctx = new_context(browser, {"width": 1366, "height": 900})
        page = ctx.new_page()
        watch(page, errors)
        page.goto(SITE + "/index.html")
        page.click("#signInBtn")
        page.wait_for_url("**/pharmacies.html*#signin")
        check("sign in: header button opens sign-in mode", page.is_hidden("#confirm-field") and page.inner_text("#account-submit").startswith("Sign in"))
        page.fill("#account [name=email]", email)
        page.fill("#account [name=password]", "wrong-password")
        page.click("#account-submit")
        wait_text(page, "#form-error", "Incorrect email or password")
        check("sign in: wrong password is refused", page.is_visible("#account"))
        page.fill("#account [name=password]", PASSWORD)
        page.click("#account-submit")
        page.wait_for_selector("#dashboard:not([hidden])")
        check("sign in: an existing pharmacy user reaches the workspace", pharmacy_name in page.inner_text("#pharmacy-name"))
        ctx.close()

        # ---------------------------------------------------- supplier registration
        ctx = new_context(browser, {"width": 1366, "height": 900})
        page = ctx.new_page()
        watch(page, errors)
        page.goto(SITE + "/index.html")
        page.click("nav.main-nav a:has-text('For Suppliers')")
        page.wait_for_url("**/suppliers.html*")
        page.wait_for_selector("#account:not([hidden])")
        check("supplier: For Suppliers opens the supplier registration",
              "SUPPLIER" in page.inner_text(".story .eyebrow") and page.inner_text("#step-title") == "Create your supplier account")
        password_toggle_checks(page, "#account", "supplier create")
        page.click("#auth-switch")
        check("supplier: 'Already have an account? Sign in' switches to sign in", page.is_hidden("#confirm-field"))
        page.click("#auth-switch")
        supplier_email = f"site-supplier-{RUN}@example.com"
        page.fill("#account [name=email]", supplier_email)
        page.fill("#account [name=password]", PASSWORD)
        page.fill("#account [name=confirm]", PASSWORD + "x")
        page.click("#account-submit")
        wait_text(page, "#form-error", "do not match")
        page.fill("#account [name=confirm]", PASSWORD)
        page.click("#account-submit")
        page.wait_for_selector("#business:not([hidden])")
        check("supplier: no SMS step (the backend only requires it for pharmacies)", page.locator("#verify").count() == 0)
        types = page.eval_on_selector_all("#business input[type=file]", "els => els.map(e => e.dataset.documentType)")
        check("supplier: supplier documents (no pharmacy license)", types == ["business_license", "owner_id"], types)
        page.click("#business-submit")
        wait_text(page, "#form-error", "business name")
        check("supplier: validation before anything is sent", True)
        supplier_name = f"Site Supplies {RUN}"
        page.fill("#business [name=name]", supplier_name)
        page.fill("#business [name=phone]", "+250 788 111 222")
        page.fill("#business [name=warehouse]", "Gikondo Warehouse")
        page.fill("#business [name=address]", "KK 15 Rd, Gikondo")
        page.set_input_files("#business input[data-document-type=business_license]",
                             files=[{"name": f"license-{RUN}.pdf", "mimeType": "application/pdf", "buffer": PDF}])
        page.click("#business-submit")
        page.wait_for_selector("#review:not([hidden])")
        wait_text(page, "#review-name", supplier_name)
        check("supplier: review shows the pending registration and the uploaded document",
              page.inner_text("#review-status").lower() == "pending" and f"license-{RUN}.pdf" in page.inner_text("#review-documents"))
        orgs = find_org(supplier_name)
        check("supplier: stored with organization type 'supplier'", len(orgs) == 1 and orgs[0]["type"] == "supplier", orgs)
        status, as_pharmacy = call("GET", "/admin/organizations?" + urllib.parse.urlencode({"q": supplier_name, "type": "pharmacy"}), token=admin_token())
        check("supplier: not registered as a pharmacy", as_pharmacy["total"] == 0)
        detail = call("GET", f"/admin/organizations/{orgs[0]['organization_id']}", token=admin_token())[1]
        check("supplier: warehouse, owner and document saved",
              detail["locations"][0]["name"] == "Gikondo Warehouse" and detail["members"][0]["email"] == supplier_email
              and detail["members"][0]["role"] == "owner" and detail["documents"][0]["document_type"] == "business_license")
        page.set_input_files("#upload-file", files=[{"name": f"id-{RUN}.pdf", "mimeType": "application/pdf", "buffer": PDF}])
        page.select_option("#upload-type", "owner_id")
        page.click("#upload-button")
        wait_text(page, "#review-documents", f"id-{RUN}.pdf")
        check("supplier: a missing document can be added later", True)

        # Approval in the admin console is reflected on the supplier page.
        call("POST", f"/admin/documents/{detail['documents'][0]['document_id']}/review", {"decision": "approved"}, admin_token())
        docs = call("GET", f"/admin/organizations/{orgs[0]['organization_id']}", token=admin_token())[1]["documents"]
        for d in docs:
            if d["verification_status"] == "pending":
                call("POST", f"/admin/documents/{d['document_id']}/review", {"decision": "approved"}, admin_token())
        call("POST", f"/admin/organizations/{orgs[0]['organization_id']}/review", {"decision": "approved"}, admin_token())
        page.click("#review-refresh")
        page.wait_for_function("document.querySelector('#review-status').textContent === 'approved'")
        check("supplier: the existing verification and approval process applies", True)
        page.click("#review-signout")
        page.wait_for_selector("#account:not([hidden])")
        check("supplier: sign out returns to sign in (no false 'session expired')", page.inner_text("#form-error") == "")

        # Existing supplier signs in on the supplier page.
        page.fill("#account [name=email]", supplier_email)
        page.fill("#account [name=password]", PASSWORD)
        page.click("#account-submit")
        page.wait_for_selector("#review:not([hidden])")
        check("sign in: an existing supplier sees their registration", supplier_name in page.inner_text("#review-name"))
        ctx.close()

        # A supplier who signs in on the pharmacy page is pointed to the supplier page.
        ctx = new_context(browser, {"width": 1366, "height": 900})
        page = ctx.new_page()
        watch(page, errors)
        page.goto(SITE + "/pharmacies.html#signin")
        page.fill("#account [name=email]", supplier_email)
        page.fill("#account [name=password]", PASSWORD)
        page.click("#account-submit")
        page.wait_for_selector("#supplier-continue:not([hidden])")
        check("sign in: a supplier on the pharmacy page is not asked to register a pharmacy",
              page.is_visible("#account") and page.is_hidden("#verify"))
        page.click("#supplier-continue a")
        page.wait_for_selector("#review:not([hidden])")
        check("sign in: ...and continues on the supplier page, still signed in", supplier_name in page.inner_text("#review-name"))
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
