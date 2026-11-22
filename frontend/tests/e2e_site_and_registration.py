"""End-to-end check of the public site and the registration journeys, against a
LOCAL backend and a throwaway database:

  * landing page navigation (For Patients / Pharmacies / Suppliers -> each group's
    registration; no Sign in / Get started), the restored interactive map, medicine search;
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
        body = page.inner_text("body")
        check("home: no made-up pharmacy names, stock cards or numerical claims",
              page.locator("section.stats, [data-count]").count() == 0
              and not any(x in body for x in ("250+", "1000+", "99.5%", "All of Kigali connected", "Kacyiru Central", "In stock", "Low stock")))
        # The interactive map (restored from before 7845078): pins on the drawn pharmacies,
        # the canvas network animating, cards on hover/click and cycling by themselves.
        pins = page.locator("#mapLayer .pin")
        check("map: pins and the animated network canvas are back", pins.count() == 11 and page.locator("#mapFx").count() == 1)
        frames = page.evaluate("""() => new Promise(done => { const c = document.querySelector('#mapFx');
          const a = c.toDataURL(); setTimeout(() => done(a !== c.toDataURL()), 900); })""")
        check("map: the canvas is animating (two frames differ)", frames)
        page.wait_for_function("document.querySelectorAll('#mapLayer .pin.show-card').length === 1", timeout=8000)
        check("map: a card appears by itself and names an area only",
              page.locator(".pin.show-card .med").inner_text() == "Search medicines in this area")
        # Pins whose centre is not under the header or the search card (what a visitor can point at).
        free = page.evaluate("""() => [...document.querySelectorAll('#mapLayer .pin')].map((p, i) => {
          if (p.hidden) return -1; const r = p.getBoundingClientRect();
          const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
          return hit && (hit === p || p.contains(hit)) ? i : -1; }).filter(i => i >= 0)""")
        check("map: several pins can be pointed at", len(free) >= 2, free)
        visible_pin = pins.nth(free[0])
        def centre(loc):
            b = loc.bounding_box(); return b["x"] + b["width"] / 2, b["y"] + b["height"] / 2
        page.mouse.move(*centre(visible_pin)); page.wait_for_timeout(500)  # the pins pulse, so no "stable" wait
        check("map: hovering a pin shows its card",
              visible_pin.locator(".pin-card").evaluate("e => getComputedStyle(e).opacity") == "1")
        # A pin whose card is not already showing (the cards also cycle by themselves; clicking
        # an open card closes it, like before).
        page.mouse.move(5, 5)
        shown = page.evaluate("[...document.querySelectorAll('#mapLayer .pin')].findIndex(p => p.classList.contains('show-card'))")
        other = pins.nth([i for i in free[1:] if i != shown][0])
        page.mouse.click(*centre(other)); page.wait_for_timeout(300)
        check("map: clicking a pin opens its card (one at a time)",
              "show-card" in (other.get_attribute("class") or "") and page.locator(".pin.show-card").count() == 1)
        check("map: every pin has an accessible name", all((pins.nth(i).get_attribute("aria-label") or "").strip() for i in range(pins.count())))
        check("home: no Sign in / Get started on the landing page, and nobody's identity in the header",
              page.locator("#signInBtn, #getStartedBtn, #accountChooser, .am-btn").count() == 0)
        check("home: copy describes reported availability, not live stock",
              page.inner_text(".live-badge") == "Availability reported by pharmacies"
              and "Live stock" not in body and "Real-time" not in body and "last updated" in page.inner_text(".lede"))
        check("home: the decorative Kigali map background stays", page.locator("#mapLayer img.map-bg-img").count() == 1)
        nav = page.locator("nav.main-nav a")
        labels = [a.strip() for a in nav.all_inner_texts()]
        check("nav: For Patients, For Pharmacies, For Suppliers, How it works, About",
              labels == ["For Patients", "For Pharmacies", "For Suppliers", "How it works", "About"], labels)
        hrefs = {a: page.get_attribute(f"nav.main-nav a:has-text('{a}')", "href") for a in labels}
        check("nav: For Patients, For Pharmacies and For Suppliers open each group's registration page",
              hrefs.get("For Patients", "").startswith("patient-register.html")
              and hrefs.get("For Pharmacies", "").startswith("pharmacies.html") and hrefs.get("For Suppliers", "").startswith("suppliers.html")
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
        for path in ("how-it-works.html", "about.html", "legal.html#cookies", "suppliers.html", "pharmacies.html",
                     "pharmacy-sign-in.html", "patient-register.html", "patient-sign-in.html"):
            r = page.goto(SITE + "/" + path)
            check(f"refresh: /{path} loads", r.status == 200)
        page.goto(SITE + "/pharmacies.html?lang=en#signin")
        page.wait_for_url("**/pharmacy-sign-in.html?lang=en")
        check("old link: pharmacies.html#signin opens the dedicated sign-in page, keeping the language", True)
        page.goto(SITE + "/pharmacies.html#staff")
        page.wait_for_url("**/pharmacy-sign-in.html")
        check("old link: pharmacies.html#staff opens the dedicated sign-in page", True)

        # ---------------------------------------------------- footer links
        expected = {
            "For Patients": "patient-register.html", "Find a medicine": "index.html#hero-search",
            "For Pharmacies": "pharmacies.html", "For Suppliers": "suppliers.html",
            "How it works": "how-it-works.html", "About": "about.html", "Careers": "about.html", "Blog": "about.html",
            "Contact": "about.html", "Privacy": "legal.html#privacy", "Terms of Service": "legal.html#terms",
            "Cookie Policy": "legal.html#cookies",
        }
        page.goto(SITE + "/about.html")
        bad = {}
        for label, target in expected.items():
            href = page.get_attribute(f"footer .footer-col a:has-text('{label}')", "href")
            if href.split("?")[0] != target and not (href.startswith(target.split("#")[0] + "?")
                                                       and href.endswith("#" + target.split("#")[1] if "#" in target else "")):
                bad[label] = href
        check("footer: every link has a destination (from another page)", not bad, bad)
        check("footer: no 'My reservations' in the public quick links",
              page.locator("footer a:has-text('My reservations'), footer a[href^='reservations.html']").count() == 0)
        check("footer: the YouTube link opens the channel",
              page.get_attribute("footer a[aria-label=YouTube]", "href") == "https://www.youtube.com/channel/UCS3w0RILCJPdfTgQaqm1AwQ")
        page.click("footer .footer-col a:has-text('Find a medicine')")
        page.wait_for_url("**/index.html#hero-search")
        page.wait_for_timeout(800)
        check("footer: 'Find a medicine' from another page lands on the medicine search",
              page.evaluate("(() => { const r = document.querySelector('#medicineSearchInput').getBoundingClientRect(); return r.top >= 0 && r.bottom <= innerHeight; })()"))
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        check("footer: on the landing page 'Find a medicine' is an in-page link",
              page.get_attribute("footer .footer-col a:has-text('Find a medicine')", "href") == "#hero-search")
        page.click("footer .footer-col a:has-text('Find a medicine')")
        page.wait_for_timeout(900)
        check("footer: ...and scrolls up to the search", page.evaluate("scrollY") < 300)
        page.goto(SITE + "/index.html")
        page.click("footer .footer-col a:has-text('Terms of Service')")
        page.wait_for_url("**/legal.html#terms")
        check("legal: the Terms page shows, clearly marked as not published or approved",
              page.is_visible("#terms") and page.is_hidden("#privacy")
              and "not yet been published or approved" in page.inner_text("#terms .placeholder-callout"))
        check("legal: no Lorem Ipsum on any legal page", "lorem" not in page.content().lower())
        page.click(".legal-nav a[data-doc=cookies]")
        page.wait_for_function("location.hash === '#cookies'")
        check("legal: switching between legal pages", page.is_visible("#cookies") and page.title().startswith("Cookie Policy"))
        page.click("footer .footer-col a:has-text('Careers')")
        page.wait_for_url("**/about.html")
        check("footer: Company links open About", True)
        check("footer: no admin link on the public site", page.locator("footer a[href*='admin'], footer a[href*='ops-console']").count() == 0)

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
        check("mobile: menu has the same items, with For Patients",
              mobile == ["For Patients", "For Pharmacies", "For Suppliers", "How it works", "About"], mobile)
        check("mobile: no Sign in / Get started in the menu either", page.locator("#signInBtnMobile, #getStartedBtnMobile").count() == 0)
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
        check("pharmacy: the registration page has no sign-in form, tabs or other groups' links",
              page.locator("[data-auth-tab], #tab-signin").count() == 0 and page.is_hidden("#forgot-row")
              and page.locator("#onboarding a[href*='suppliers.html'], #onboarding a[href*='reservations.html']").count() == 0)
        page.click("#auth-switch-link")
        page.wait_for_url("**/pharmacy-sign-in.html*")
        page.wait_for_selector("#account:not([hidden])")
        check("pharmacy: 'Sign in to your pharmacy' opens the dedicated sign-in page",
              page.is_hidden("#confirm-field") and page.inner_text("#step-title") == "Pharmacy sign-in"
              and page.is_visible("#forgot-link") and page.title().startswith("Pharmacy sign-in"))
        check("pharmacy sign-in: no tabs and no other groups' links",
              page.locator("[data-auth-tab]").count() == 0
              and page.locator("#onboarding a[href*='suppliers.html'], #onboarding a[href*='reservations.html']").count() == 0)
        check("pharmacy sign-in: forgot password leads to recovery that returns here",
              page.get_attribute("#forgot-link", "href") == "reset-password.html?next=pharmacy")
        page.click("#auth-switch-link")
        page.wait_for_url("**/pharmacies.html*")
        page.wait_for_selector("#account:not([hidden])")
        check("pharmacy: ...and 'Register your pharmacy' returns to registration", page.is_visible("#confirm-field"))
        steps = [s.strip() for s in page.locator(".steps li").all_inner_texts()]
        check("pharmacy: steps are Account, Verify email, Details, Documents, Review (no plan or payment)",
              steps == ["Account", "Verify email", "Details", "Documents", "Review"], steps)
        ctx.close()

        ctx = new_context(browser, {"width": 1366, "height": 900})
        page = ctx.new_page()
        watch(page, errors)
        page.goto(SITE + "/index.html")
        page.click("nav.main-nav a:has-text('For Patients')")
        page.wait_for_url("**/patient-register.html*")
        check("patients: For Patients opens the patient registration page, with no public header",
              page.inner_text("#step-title") == "Create your patient account" and page.locator("#siteHeader, nav.main-nav").count() == 0
              and page.locator("#onboarding a[href*='pharmac'], #onboarding a[href*='suppliers']").count() == 0)
        password_toggle_checks(page, "#patient-auth", "patient register")
        check("patients: 'Already have an account? Sign in' links to the patient sign-in page",
              "Already have an account?" in page.inner_text(".auth-switch") and page.get_attribute("#auth-other", "href").startswith("patient-sign-in.html"))
        page.click("#auth-other")
        page.wait_for_url("**/patient-sign-in.html*")
        check("patients: the sign-in page says 'Don't have an account? Sign up' (to registration)",
              "Don’t have an account?" in page.inner_text(".auth-switch") and page.inner_text("#auth-other") == "Sign up"
              and page.get_attribute("#auth-other", "href").startswith("patient-register.html"))
        password_toggle_checks(page, "#patient-auth", "patient sign-in")
        check("patients: forgot-password goes to patient recovery",
              page.get_attribute("#forgot-link", "href") == "reset-password.html?next=patient")
        page.click("#forgot-link")
        page.wait_for_url("**/reset-password.html?next=patient")
        page.wait_for_selector("#back-to-signin")
        check("patient recovery: 'Back to sign in' returns to the patient sign-in page",
              page.get_attribute("#back-to-signin", "href") == "patient-sign-in.html")
        page.goto(SITE + "/patient-sign-in.html?next=" + urllib.parse.quote("https://evil.example/x"))
        page.fill("#patient-auth [name=email]", "nobody@example.com"); page.fill("#patient-auth [name=password]", "x")
        page.evaluate("() => document.querySelector('#patient-auth').dispatchEvent(new Event('submit', {cancelable: true}))")
        page.wait_for_function("document.querySelector('#form-error').textContent.length > 0")
        check("patients: a wrong password is refused on the page", "Incorrect email or password" in page.inner_text("#form-error"))
        page.goto(SITE + "/index.html")
        page.click("nav.main-nav a:has-text('For Suppliers')")
        page.wait_for_url("**/suppliers.html*")
        page.wait_for_selector("#account:not([hidden])")
        check("supplier: For Suppliers opens the supplier registration",
              "SUPPLIER" in page.inner_text(".story .eyebrow") and page.inner_text("#step-title") == "Create your supplier account")
        password_toggle_checks(page, "#account", "supplier create")
        check("supplier: no link to the pharmacy or patient sign-in",
              page.locator("#onboarding a[href*='pharmac'], #onboarding a[href*='reservations.html']").count() == 0)
        page.click("#auth-switch")
        check("supplier: 'Already have an account? Sign in' switches to sign in, with password recovery",
              page.is_hidden("#confirm-field") and page.get_attribute("#forgot-link", "href") == "reset-password.html?next=supplier")
        ctx.close()

        # Admin sign-in has the toggle too, and still works.
        ctx = new_context(browser, {"width": 1366, "height": 900})
        page = ctx.new_page()
        watch(page, errors)
        page.goto(SITE + "/ops-console-7f3k9q.html")
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
