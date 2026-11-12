"""Browser test of how the admin console is reached, against a LOCAL backend.
Never point this at production.

  * no public page links to the admin console (desktop and mobile, every language);
  * the old address (admin.html) no longer exists;
  * the console is at ops-console-7f3k9q.html, opened directly;
  * access is still decided by the backend: a non-admin is refused there and by
    the /admin API, and an administrator signs in.

  1. Backend on http://127.0.0.1:8000 with a disposable database and an admin
     (see e2e_admin.py for the setup).
  2. Frontend on http://127.0.0.1:5501 (python -m http.server 5501 --directory frontend).
  3. E2E_ADMIN_EMAIL=... E2E_ADMIN_PASSWORD=... python frontend/tests/e2e_admin_access.py
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
CONSOLE = "ops-console-7f3k9q.html"
ADMIN_EMAIL = os.environ["E2E_ADMIN_EMAIL"]
ADMIN_PASSWORD = os.environ["E2E_ADMIN_PASSWORD"]
PLAIN_EMAIL = f"plain-access-{uuid.uuid4().hex[:6]}@example.com"
PLAIN_PASSWORD = "Plain-User-Pass-2026"
PUBLIC_PAGES = ("index.html", "how-it-works.html", "about.html", "legal.html", "pharmacies.html", "suppliers.html")
failures = []


def check(label, ok):
    print(("PASS " if ok else "FAIL ") + label)
    if not ok:
        failures.append(label)


def status_of(method, path, body=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(API + path, data=json.dumps(body).encode() if body else None,
                                 method=method, headers=headers)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def site_status(path):
    try:
        with urllib.request.urlopen(SITE + "/" + path) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


ADMIN_LINKS = """() => [...document.querySelectorAll('a[href]')].map(a => a.getAttribute('href'))
  .filter(h => /admin|ops-console/i.test(h))"""


def main():
    assert status_of("POST", "/auth/register", {"name": "Plain", "email": PLAIN_EMAIL, "password": PLAIN_PASSWORD}) == 201
    check("the old address admin.html no longer exists", site_status("admin.html") == 404)
    check(f"the console is served at {CONSOLE}", site_status(CONSOLE) == 200)

    with sync_playwright() as p:
        browser = p.chromium.launch(channel=os.environ.get("E2E_BROWSER_CHANNEL") or None, headless=True)
        for label, viewport in (("desktop", {"width": 1366, "height": 900}), ("mobile", {"width": 375, "height": 812})):
            ctx = browser.new_context(viewport=viewport)
            ctx.route("**/js/config.js", lambda r: r.fulfill(
                content_type="application/javascript", body=f'window.APEX_CONFIG = {{ API_BASE_URL: "{API}" }};'))
            ctx.route("https://apexrx-smart.onrender.com/**", lambda r: r.abort())
            page = ctx.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            for path in PUBLIC_PAGES:
                page.goto(f"{SITE}/{path}")
                page.wait_for_load_state("load")
                found = page.evaluate(ADMIN_LINKS)
                check(f"[{label}] {path}: no link to the admin console {found}", not found
                      and "Admin Portal" not in page.inner_text("body"))
            page.goto(SITE + "/index.html")
            check(f"[{label}] homepage loads with the medicine search", page.is_visible("#medicineSearchInput"))
            check(f"[{label}] footer still fits (no horizontal scroll)",
                  page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))
            check(f"[{label}] no page errors", not errors)
            ctx.close()

        ctx = browser.new_context()
        ctx.route("**/js/config.js", lambda r: r.fulfill(
            content_type="application/javascript", body=f'window.APEX_CONFIG = {{ API_BASE_URL: "{API}" }};'))
        page = ctx.new_page()
        page.goto(SITE + "/index.html")
        for lang in ("fr", "rw"):
            page.select_option("#langSelect", lang)
            page.wait_for_timeout(200)
            check(f"[{lang}] no admin link after switching language", not page.evaluate(ADMIN_LINKS))

        # Opened directly: sign-in screen; access decided by the backend.
        page.goto(f"{SITE}/{CONSOLE}")
        page.wait_for_selector("#login-view:not([hidden])")
        check("the console opens directly at its sign-in screen", page.is_hidden("#dashboard-view"))
        page.fill("#login-form [name=email]", PLAIN_EMAIL)
        page.fill("#login-form [name=password]", PLAIN_PASSWORD)
        page.click("#login-button")
        page.wait_for_function("document.querySelector('#login-error').textContent.includes('not an ApexRX administrator')")
        check("a non-admin account is refused by the console", page.is_hidden("#dashboard-view"))
        check("/admin API without a token is 401", status_of("GET", "/admin/organizations") == 401)
        plain = json.loads(urllib.request.urlopen(urllib.request.Request(
            API + "/auth/login", data=json.dumps({"email": PLAIN_EMAIL, "password": PLAIN_PASSWORD}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")).read())["access_token"]
        check("/admin API with a non-admin token is 403", status_of("GET", "/admin/organizations", token=plain) == 403)

        page.fill("#login-form [name=email]", ADMIN_EMAIL)
        page.fill("#login-form [name=password]", ADMIN_PASSWORD)
        page.click("#login-button")
        page.wait_for_selector("#dashboard-view:not([hidden])")
        check("an administrator signs in at the new address", page.is_visible("#dashboard-view"))
        browser.close()

    print(f"\n{'ALL PASSED' if not failures else str(len(failures)) + ' FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
