"""End-to-end check of the admin dashboard (frontend/admin.html), plus the
patient search on the homepage, against a LOCAL backend.

Never point this at production: it registers accounts and changes statuses.

Setup (see the root README, "Admin dashboard"):
  1. Backend on http://127.0.0.1:8000 with a disposable database, and an admin:
       APEXRX_ADMIN_PASSWORD=... python -m app.scripts.create_admin --email e2e-admin@example.com --yes
  2. Frontend served on http://127.0.0.1:5501 (python -m http.server 5501 --directory frontend)
  3. pip install playwright && playwright install chromium
  4. E2E_ADMIN_EMAIL=e2e-admin@example.com E2E_ADMIN_PASSWORD=... python frontend/tests/e2e_admin.py

js/config.js (which points at Render) is replaced in the browser by one that
points at E2E_API, so no file needs editing. Uploaded files are dummy PDFs.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid

from playwright.sync_api import sync_playwright

SITE = os.environ.get("E2E_SITE", "http://127.0.0.1:5501")
API = os.environ.get("E2E_API", "http://127.0.0.1:8000")
ADMIN_EMAIL = os.environ["E2E_ADMIN_EMAIL"]
ADMIN_PASSWORD = os.environ["E2E_ADMIN_PASSWORD"]
PASSWORD = "E2e-User-Pass-2026"
RUN = uuid.uuid4().hex[:6]
PDF = b"%PDF-1.4\n% ApexRx e2e dummy document, not a real license\n%%EOF\n"
XSS_NAME = f'<img src=x onerror="window.__xss=1"> Supplier {RUN}'

failures = []


def check(label, condition):
    print(("PASS " if condition else "FAIL ") + label)
    if not condition:
        failures.append(label)


# --------------------------------------------------------------- API seeding
def call(method, path, body=None, token=None, multipart=None):
    headers = {"Accept": "application/json"}
    data = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if multipart:
        boundary = uuid.uuid4().hex
        fields, (fname, content, mime) = multipart
        parts = [
            f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
            for k, v in fields.items()
        ]
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{fname}"\r\n'
            f"Content-Type: {mime}\r\n\r\n".encode() + content + b"\r\n"
        )
        data = b"".join(parts) + f"--{boundary}--\r\n".encode()
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(API + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req) as res:
            text = res.read().decode()
            return json.loads(text) if text else None
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{method} {path} -> {e.code}: {e.read().decode()}")


def account(email, name):
    call("POST", "/auth/register", {"name": name, "email": email, "password": PASSWORD})
    return call("POST", "/auth/login", {"email": email, "password": PASSWORD})["access_token"]


def seed():
    admin = call("POST", "/auth/login", {"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})["access_token"]

    owner = account(f"owner-{RUN}@example.com", "Pending Owner")
    pending = call("POST", "/organizations", {"name": f"Pending Pharmacy {RUN}", "type": "pharmacy",
                                               "email": f"contact-{RUN}@example.com", "phone": "+250 788 100 200"}, owner)
    call("POST", f"/organizations/{pending['organization_id']}/locations",
         {"name": "Remera Branch", "address": "KG 11 Ave", "city": "Kigali", "latitude": -1.95, "longitude": 30.11}, owner)
    for doc_type, fname in [("pharmacy_license", "license-dummy.pdf"), ("owner_id", "owner-id-dummy.pdf")]:
        call("POST", f"/organizations/{pending['organization_id']}/documents", token=owner,
             multipart=({"document_type": doc_type}, (fname, PDF, "application/pdf")))

    supplier_owner = account(f"supplier-{RUN}@example.com", "Supplier Owner")
    supplier = call("POST", "/organizations", {"name": XSS_NAME, "type": "supplier"}, supplier_owner)

    # An approved pharmacy with a listed offer, for the patient search check.
    seller = account(f"seller-{RUN}@example.com", "Seller")
    shop = call("POST", "/organizations", {"name": f"Search Pharmacy {RUN}", "type": "pharmacy"}, seller)
    call("POST", f"/admin/organizations/{shop['organization_id']}/review", {"decision": "approved"}, admin)
    loc = call("POST", f"/organizations/{shop['organization_id']}/locations",
               {"name": "Kacyiru", "latitude": -1.94, "longitude": 30.06}, seller)
    drug = call("POST", "/catalogue/drugs", {"name": f"E2etestol {RUN}"}, admin)
    product = call("POST", "/catalogue/products", {"drug_id": drug["drug_id"], "product_name": f"E2etestol {RUN} 500mg"}, admin)
    base = f"/organizations/{shop['organization_id']}/locations/{loc['location_id']}/stock/{product['product_id']}"
    call("PUT", base, {"quantity": 50}, seller)
    call("PUT", base + "/offer", {"unit_price": "1200.00"}, seller)

    plain = account(f"plain-{RUN}@example.com", "Plain User")
    del plain
    return pending, supplier


def counts(page):
    page.wait_for_function("document.querySelector('[data-count=pending]').textContent !== '–'")
    time.sleep(0.5)
    return {k: page.text_content(f"[data-count={k}]") for k in
            ("total", "pharmacy", "supplier", "pending", "approved", "rejected", "suspended")}


def main():
    before = call("GET", "/admin/organizations?limit=1",
                  token=call("POST", "/auth/login", {"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})["access_token"])["total"]
    pending, supplier = seed()

    with sync_playwright() as p:
        browser = p.chromium.launch(channel=os.environ.get("E2E_BROWSER_CHANNEL") or None, headless=True)
        ctx = browser.new_context(accept_downloads=True)
        ctx.route("**/js/config.js", lambda route: route.fulfill(
            content_type="application/javascript", body=f'window.APEX_CONFIG = {{ API_BASE_URL: "{API}" }};'))
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("dialog", lambda d: d.accept())

        # 1. A non-admin account is refused.
        page.goto(SITE + "/admin.html")
        page.fill("#login-form [name=email]", f"plain-{RUN}@example.com")
        page.fill("#login-form [name=password]", PASSWORD)
        page.click("#login-button")
        page.wait_for_function("document.querySelector('#login-error').textContent.includes('not an ApexRX administrator')")
        check("non-admin is refused", page.is_hidden("#dashboard-view"))
        check("non-admin token is cleared", page.evaluate("sessionStorage.getItem('apexrx_session')") is None)

        # Wrong password.
        page.fill("#login-form [name=email]", ADMIN_EMAIL)
        page.fill("#login-form [name=password]", "wrong-password")
        page.click("#login-button")
        page.wait_for_function("document.querySelector('#login-error').textContent.includes('Incorrect')")
        check("wrong password message", True)

        # 2. Admin signs in; overview counts.
        page.fill("#login-form [name=password]", ADMIN_PASSWORD)
        page.click("#login-button")
        page.wait_for_selector("#dashboard-view:not([hidden])")
        c = counts(page)
        print("  counts:", c)
        check("total count", int(c["total"]) == before + 3)
        check("pending count includes the two new organizations", int(c["pending"]) >= 2)
        check("type counts add up", int(c["pharmacy"]) + int(c["supplier"]) == int(c["total"]))
        check("status counts add up",
              sum(int(c[k]) for k in ("pending", "approved", "rejected", "suspended")) == int(c["total"]))

        # 3. Filters and the injection attempt rendered as text.
        page.select_option("#filters [name=type]", "supplier")
        page.fill("#filters [name=q]", RUN)
        page.click("#filters button")
        page.wait_for_function(f"document.querySelector('#org-rows').innerText.includes('Supplier {RUN}')")
        page.wait_for_timeout(1000)  # let every in-flight list request settle
        check("supplier filter shows only the supplier", page.locator("#org-rows tr").count() == 1)
        check("organization name is shown as text, not HTML",
              page.locator("#org-rows img").count() == 0 and page.evaluate("window.__xss") is None)
        page.select_option("#filters [name=type]", "")
        page.select_option("#filters [name=status]", "pending")
        page.wait_for_function(f"document.querySelector('#org-rows').innerText.includes('Pending Pharmacy {RUN}')")
        page.wait_for_timeout(1000)  # let every in-flight list request settle
        rows = page.inner_text("#org-rows")
        check("status filter", "Search Pharmacy" not in rows and f"Supplier {RUN}" in rows)

        # 4. Pharmacy detail, documents and approval.
        page.click(f"#org-rows tr:has-text('Pending Pharmacy {RUN}') button")
        page.wait_for_selector("#detail-view:not([hidden])")
        detail = page.inner_text("#detail-view")
        check("detail shows contact", f"contact-{RUN}@example.com" in detail and "+250 788 100 200" in detail)
        check("detail shows location", "Remera Branch" in detail and "KG 11 Ave" in detail)
        check("detail shows members", f"owner-{RUN}@example.com" in detail)
        check("detail shows both documents", "license-dummy.pdf" in detail and "owner-id-dummy.pdf" in detail)
        approve = page.locator("#review-box [data-decision=approved]")
        check("approve disabled while documents are pending", approve.is_disabled())
        check("suspend hidden for a pending organization", page.is_hidden("#review-box [data-decision=suspended]"))

        with page.expect_download() as dl:
            page.click("#documents .item:has-text('license-dummy.pdf') button:has-text('Download')")
        download = dl.value
        check("download keeps the file name", download.suggested_filename == "license-dummy.pdf")
        with open(download.path(), "rb") as f:
            check("downloaded bytes match the upload", f.read() == PDF)

        page.click("#documents .item:has-text('owner-id-dummy.pdf') button:has-text('Reject document')")
        page.wait_for_function("document.querySelector('#detail-message').textContent.includes('Enter a reason')")
        check("document rejection needs a reason", True)
        page.click("#documents .item:has-text('license-dummy.pdf') button:has-text('Approve document')")
        page.wait_for_function("document.querySelector('#detail-message').textContent.includes('license-dummy.pdf approved')")
        page.fill("#documents .item:has-text('owner-id-dummy.pdf') input", "Photo is blurry (e2e)")
        page.click("#documents .item:has-text('owner-id-dummy.pdf') button:has-text('Reject document')")
        page.wait_for_function("document.querySelector('#detail-message').textContent.includes('rejected')")
        check("document statuses updated", "Photo is blurry (e2e)" in page.inner_text("#documents"))
        check("approve enabled once documents are reviewed", not approve.is_disabled())

        approve.click()
        page.wait_for_function("document.querySelector('#detail-status').textContent === 'approved'")
        check("organization approved", "is now approved" in page.inner_text("#detail-message"))
        check("suspend now available", page.is_visible("#review-box [data-decision=suspended]"))
        org = call("GET", f"/admin/organizations/{pending['organization_id']}",
                   token=call("POST", "/auth/login", {"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})["access_token"])
        check("approval persisted", org["status"] == "approved")

        # 5. Supplier rejection needs notes.
        page.click("#back")
        page.select_option("#filters [name=status]", "pending")
        page.fill("#filters [name=q]", RUN)
        page.click("#filters button")
        page.wait_for_function(f"document.querySelector('#org-rows').innerText.includes('Supplier {RUN}')")
        page.click(f"#org-rows tr:has-text('Supplier {RUN}') button")
        page.wait_for_selector("#detail-view:not([hidden])")
        check("detail heading is text", page.locator("#detail-name img").count() == 0)
        page.click("#review-box [data-decision=rejected]")
        page.wait_for_function("document.querySelector('#detail-message').textContent.includes('Add review notes')")
        check("rejection needs notes", page.text_content("#detail-status") == "pending")
        page.fill("#review-notes", "No verification documents submitted (e2e)")
        page.click("#review-box [data-decision=rejected]")
        page.wait_for_function("document.querySelector('#detail-status').textContent === 'rejected'")
        check("supplier rejected with notes", "No verification documents submitted (e2e)" in page.inner_text("#detail-info"))

        # 6. An invalid or expired token sends the admin back to sign in.
        page.evaluate("""() => { const s = JSON.parse(sessionStorage.getItem('apexrx_session'));
                                 s.token = 'invalid.token.value'; sessionStorage.setItem('apexrx_session', JSON.stringify(s)); }""")
        page.click("#refresh")
        page.wait_for_selector("#login-view:not([hidden])")
        check("invalid token returns to sign in",
              "session has expired" in page.text_content("#login-error") and page.is_hidden("#dashboard-view"))

        # 7. Sign out.
        page.fill("#login-form [name=email]", ADMIN_EMAIL)
        page.fill("#login-form [name=password]", ADMIN_PASSWORD)
        page.click("#login-button")
        page.wait_for_selector("#dashboard-view:not([hidden])")
        page.reload()
        page.wait_for_selector("#dashboard-view:not([hidden])")
        check("session survives a reload", True)
        page.click("#sign-out")
        page.wait_for_selector("#login-view:not([hidden])")
        check("sign out clears the session", page.evaluate("sessionStorage.getItem('apexrx_session')") is None)

        # 8. Narrow screen: no horizontal page scroll.
        page.set_viewport_size({"width": 375, "height": 800})
        page.fill("#login-form [name=email]", ADMIN_EMAIL)
        page.fill("#login-form [name=password]", ADMIN_PASSWORD)
        page.click("#login-button")
        page.wait_for_selector("#dashboard-view:not([hidden])")
        check("no horizontal scroll at 375px",
              page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))

        # 9. Patient search on the homepage still works.
        page.set_viewport_size({"width": 1280, "height": 800})
        page.goto(SITE + "/index.html")
        page.fill("#medicineSearchInput", f"E2etestol {RUN}")
        page.click("#medicineSearchForm button[type=submit]")
        page.wait_for_selector("#medicineSearchResults .result-row", timeout=10000)
        results = page.inner_text("#medicineSearchResults")
        check("patient search returns the listed offer", f"Search Pharmacy {RUN}" in results)

        check("no page errors", not errors)
        for e in errors:
            print("  page error:", e)
        browser.close()

    print(f"\n{'ALL PASSED' if not failures else str(len(failures)) + ' FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
