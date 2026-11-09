"""Browser test of the footer "Admin Portal" link on the homepage, against a
LOCAL backend. Never point this at production.

  1. Backend on http://127.0.0.1:8000 with a disposable database and an admin
     (see e2e_admin.py for the setup).
  2. Frontend on http://127.0.0.1:5501 (python -m http.server 5501 --directory frontend).
  3. E2E_ADMIN_EMAIL=... E2E_ADMIN_PASSWORD=... python frontend/tests/e2e_admin_link.py

The link is navigation only; this also checks that admin.html and the /admin
API still refuse anyone who is not a platform admin.
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
ADMIN_EMAIL = os.environ["E2E_ADMIN_EMAIL"]
ADMIN_PASSWORD = os.environ["E2E_ADMIN_PASSWORD"]
PLAIN_EMAIL = f"plain-link-{uuid.uuid4().hex[:6]}@example.com"
PLAIN_PASSWORD = "Plain-User-Pass-2026"
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


def link_checks(page, label):
    link = page.locator("footer .footer-bottom a.footer-admin-link")
    link.scroll_into_view_if_needed()
    check(f"[{label}] link is visible in the footer bottom row", link.count() == 1 and link.is_visible())
    check(f"[{label}] relative href to admin.html", link.get_attribute("href") == "admin.html")
    sizes = page.evaluate("""() => {
      const a = document.querySelector('.footer-admin-link'), s = document.querySelector('.footer-bottom span');
      const search = document.querySelector('#medicineSearchForm button[type=submit]');
      const fs = el => parseFloat(getComputedStyle(el).fontSize);
      const r = a.getBoundingClientRect();
      return {link: fs(a), copyright: fs(s), search: fs(search), height: r.height,
              left: r.left < window.innerWidth / 2,
              sameColor: getComputedStyle(a).color === getComputedStyle(s).color,
              scroll: document.documentElement.scrollWidth <= window.innerWidth};
    }""")
    check(f"[{label}] styled like the copyright text {sizes}",
          sizes["link"] == sizes["copyright"] and sizes["sameColor"])
    check(f"[{label}] less prominent than the medicine search", sizes["link"] < sizes["search"])
    check(f"[{label}] tap target at least 24px high", sizes["height"] >= 24)
    check(f"[{label}] no horizontal page scroll", sizes["scroll"])
    # Netlify pins its "Powered by Netlify" badge to the bottom-right corner.
    check(f"[{label}] link sits on the left, clear of the Netlify badge", sizes["left"])


def main():
    assert status_of("POST", "/auth/register", {"name": "Plain", "email": PLAIN_EMAIL, "password": PLAIN_PASSWORD}) == 201

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
            page.goto(SITE + "/index.html")
            check(f"[{label}] homepage loads with the medicine search", page.is_visible("#medicineSearchInput"))
            link_checks(page, label)

            page.click("footer .footer-admin-link")
            page.wait_for_url("**/admin.html")
            page.wait_for_selector("#login-view:not([hidden])")
            check(f"[{label}] link opens admin.html at its sign-in screen",
                  page.url.endswith("/admin.html") and page.is_hidden("#dashboard-view"))
            check(f"[{label}] no page errors", not errors)
            ctx.close()

        # Languages: the label is translated with the rest of the footer.
        ctx = browser.new_context()
        ctx.route("**/js/config.js", lambda r: r.fulfill(
            content_type="application/javascript", body=f'window.APEX_CONFIG = {{ API_BASE_URL: "{API}" }};'))
        page = ctx.new_page()
        page.goto(SITE + "/index.html")
        labels = {}
        for lang in ("fr", "rw", "en"):
            page.select_option("#langSelect", lang)
            page.wait_for_timeout(200)
            labels[lang] = page.text_content(".footer-admin-link")
        check(f"label follows the language switch {labels}",
              labels["en"] == "Admin Portal" and labels["fr"] == "Portail administrateur" and labels["rw"] != "Admin Portal")

        # Access control is unchanged: navigation alone grants nothing.
        page.goto(SITE + "/admin.html")
        page.fill("#login-form [name=email]", PLAIN_EMAIL)
        page.fill("#login-form [name=password]", PLAIN_PASSWORD)
        page.click("#login-button")
        page.wait_for_function("document.querySelector('#login-error').textContent.includes('not an ApexRX administrator')")
        check("non-admin account is refused by admin.html", page.is_hidden("#dashboard-view"))
        check("/admin API without a token is 401", status_of("GET", "/admin/organizations") == 401)
        plain = json.loads(urllib.request.urlopen(urllib.request.Request(
            API + "/auth/login", data=json.dumps({"email": PLAIN_EMAIL, "password": PLAIN_PASSWORD}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")).read())["access_token"]
        check("/admin API with a non-admin token is 403", status_of("GET", "/admin/organizations", token=plain) == 403)

        page.fill("#login-form [name=email]", ADMIN_EMAIL)
        page.fill("#login-form [name=password]", ADMIN_PASSWORD)
        page.click("#login-button")
        page.wait_for_selector("#dashboard-view:not([hidden])")
        check("existing admin login still works", page.is_visible("#dashboard-view"))
        browser.close()

    print(f"\n{'ALL PASSED' if not failures else str(len(failures)) + ' FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
