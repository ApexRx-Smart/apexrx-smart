"""End-to-end check of the admin console sections (frontend/admin.html):
Overview, Documents, Users, Catalogue (drugs and products) and Search
insights, against a LOCAL backend and a throwaway database.

Never point this at production: it registers accounts, changes account
status and admin rights, and adds catalogue entries.

Setup (as for e2e_admin.py):
  1. Backend on http://127.0.0.1:8000 with a disposable database, APP_ENV=development
     and EMAIL_PROVIDER=mock, and an admin account:
       APEXRX_ADMIN_PASSWORD=... python -m app.scripts.create_admin --email e2e-admin@example.com --yes
  2. Frontend on http://127.0.0.1:5501 (python -m http.server 5501 --directory frontend)
  3. E2E_ADMIN_EMAIL=e2e-admin@example.com E2E_ADMIN_PASSWORD=... python frontend/tests/e2e_admin_console.py
     (E2E_BROWSER_CHANNEL=chrome uses the installed Chrome instead of Playwright's.)

Each run creates its own accounts, organization, drugs, products and searches,
named with a random run id, so runs never collide. js/config.js is replaced in
the browser by one that points at E2E_API.
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
PASSWORD = "Console-Pass-2026"
RUN = uuid.uuid4().hex[:6]
PHONE = f"+250788{random.randint(0, 999999):06d}"
PDF = b"%PDF-1.4\n% ApexRx e2e dummy document, not a real license\n%%EOF\n"

failures = []


def check(label, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + label + (f"  {detail}" if detail and not condition else ""))
    if not condition:
        failures.append(label)


# --------------------------------------------------------------- API helpers
def call(method, path, body=None, token=None, multipart=None):
    """Returns (status, json). Never raises on HTTP errors."""
    headers = {"Accept": "application/json"}
    data = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if multipart:
        boundary = uuid.uuid4().hex
        fields, (fname, content, mime) = multipart
        parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
                 for k, v in fields.items()]
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{fname}"\r\n'
                     f"Content-Type: {mime}\r\n\r\n".encode() + content + b"\r\n")
        data = b"".join(parts) + f"--{boundary}--\r\n".encode()
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    elif body is not None:
        data = json.dumps(body).encode()
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


def ok(method, path, body=None, token=None, **kw):
    status, data = call(method, path, body, token, **kw)
    if status >= 300:
        raise SystemExit(f"seed failed: {method} {path} -> {status}: {data}")
    return data


def login(email, password=PASSWORD):
    return call("POST", "/auth/login", {"email": email, "password": password})


def account(email, name):
    ok("POST", "/auth/register", {"name": name, "email": email, "password": PASSWORD})
    return login(email)[1]["access_token"]


def admin_token():
    return login(ADMIN_EMAIL, ADMIN_PASSWORD)[1]["access_token"]


def seed():
    owner = account(f"console-owner-{RUN}@example.com", f"Console Owner {RUN}")
    # The real email verification flow with the mock provider (development only).
    ok("POST", "/auth/email/send", {"next": "pharmacy"}, owner)
    req = urllib.request.Request(API + "/dev/email/latest", headers={"Authorization": f"Bearer {owner}"})
    with urllib.request.urlopen(req) as res:
        link_token = json.loads(res.read())["token"]
    ok("POST", "/auth/email/verify", {"token": link_token})
    org = ok("POST", "/organizations", {"name": f"Console Pharmacy {RUN}", "type": "pharmacy"}, owner)
    for doc_type, fname in [("pharmacy_license", f"license-{RUN}.pdf"), ("owner_id", f"id-{RUN}.pdf")]:
        ok("POST", f"/organizations/{org['organization_id']}/documents", token=owner,
           multipart=({"document_type": doc_type}, (fname, PDF, "application/pdf")))
    target = account(f"console-target-{RUN}@example.com", f"Console Target {RUN}")
    # Patient searches (anonymous): one that finds nothing. Searched once more
    # than today's most searched term, so it ranks first whatever earlier runs left.
    top = ok("GET", "/admin/insights/searches?days=7&limit=1", token=admin_token())
    searches = (top[0]["searches"] if top else 0) + 1
    for _ in range(searches):
        ok("GET", "/search/pharmacies?" + urllib.parse.urlencode({"q": f"Unmetmedicine {RUN}"}))
    return {"owner": owner, "org": org, "target": target, "searches": searches}


# ------------------------------------------------------------ page helpers
def wait_text(page, selector, text, timeout=15000):
    page.wait_for_function("([s, t]) => (document.querySelector(s) || {}).textContent?.includes(t)",
                           arg=[selector, text], timeout=timeout)


def open_tab(page, name):
    page.click(f"#admin-tabs [data-tab={name}]")
    page.wait_for_selector(f"[data-panel={name}]:not([hidden])")


def settled(page, rows):
    page.wait_for_function("s => !document.querySelector(s).classList.contains('loading')", arg=rows)


def main():
    world = seed()
    org_id = world["org"]["organization_id"]

    # ---- Backend authorization for every operation the console uses (no UI involved).
    plain = world["target"]
    ops = [
        ("GET", "/admin/users", None), ("PATCH", f"/admin/users/{1}", {"is_platform_admin": True}),
        ("GET", "/admin/documents", None), ("GET", "/admin/insights/searches", None),
        ("POST", "/catalogue/drugs", {"name": f"Forbidden {RUN}"}),
        ("POST", "/catalogue/products", {"drug_id": 1, "product_name": f"Forbidden {RUN}"}),
        ("PATCH", "/catalogue/drugs/1", {"name": f"Forbidden {RUN}"}),
        ("PATCH", "/catalogue/products/1", {"is_active": False}),
    ]
    check("backend: a regular user gets 403 on every admin operation",
          all(call(m, p, b, plain)[0] == 403 for m, p, b in ops),
          [(p, call(m, p, b, plain)[0]) for m, p, b in ops])
    check("backend: no token gets 401 on every admin operation",
          all(call(m, p, b)[0] == 401 for m, p, b in ops))

    with sync_playwright() as p:
        browser = p.chromium.launch(channel=os.environ.get("E2E_BROWSER_CHANNEL") or None, headless=True)
        ctx = browser.new_context(accept_downloads=True, viewport={"width": 1280, "height": 900})
        ctx.route("**/js/config.js", lambda route: route.fulfill(
            content_type="application/javascript", body=f'window.APEX_CONFIG = {{ API_BASE_URL: "{API}" }};'))
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        dialogs = {"answer": True, "seen": []}

        def on_dialog(d):
            dialogs["seen"].append(d.message)
            d.accept() if dialogs["answer"] else d.dismiss()
        page.on("dialog", on_dialog)

        # ---- 1. Access: a regular account cannot open the console.
        page.goto(SITE + "/admin.html")
        page.fill("#login-form [name=email]", f"console-target-{RUN}@example.com")
        page.fill("#login-form [name=password]", PASSWORD)
        page.click("#login-button")
        wait_text(page, "#login-error", "not an ApexRX administrator")
        check("1. a regular account is refused and sees no admin sections", page.is_hidden("#dashboard-view"))

        page.fill("#login-form [name=email]", ADMIN_EMAIL)
        page.fill("#login-form [name=password]", ADMIN_PASSWORD)
        page.click("#login-button")
        page.wait_for_selector("[data-panel=overview]:not([hidden])")
        check("1. an admin lands on the Overview", page.url.endswith("/admin.html") or page.url.endswith("#overview"))

        # ---- 2. Overview numbers come from the backend.
        page.wait_for_function("!['–', '…'].includes(document.querySelector('[data-overview=docs_pending]').textContent)")
        page.wait_for_function("!['–', '…'].includes(document.querySelector('[data-overview=products_retired]').textContent)")
        admin = admin_token()
        expected = {
            "orgs_pending": ok("GET", "/admin/organizations?limit=1&status=pending", token=admin)["total"],
            "docs_pending": ok("GET", "/admin/documents?limit=1&status=pending", token=admin)["total"],
            "users_total": ok("GET", "/admin/users?limit=1", token=admin)["total"],
            "users_admins": ok("GET", "/admin/users?limit=1&is_platform_admin=true", token=admin)["total"],
            "drugs_total": ok("GET", "/catalogue/drugs?limit=1")["total"],
            "products_active": ok("GET", "/catalogue/products?limit=1")["total"],
        }
        shown = {k: page.text_content(f"[data-overview={k}]") for k in expected}
        check("2. overview cards match the API totals", all(shown[k] == str(v) for k, v in expected.items()), (shown, expected))
        wait_text(page, "#overview-unmet", f"unmetmedicine {RUN}")
        check("2. overview lists the unmet search", f"{world['searches']} searches" in page.inner_text("#overview-unmet"))
        page.click("[data-overview=docs_pending] >> xpath=..")
        page.wait_for_selector("[data-panel=documents]:not([hidden])")
        check("2. the documents card opens the document queue", True)

        # ---- 3. Document queue: validation, approve, reject with a reason, open organization.
        settled(page, "#doc-rows")
        wait_text(page, "#doc-rows", f"license-{RUN}.pdf")
        lic = f"#doc-rows tr:has-text('license-{RUN}.pdf')"
        idr = f"#doc-rows tr:has-text('id-{RUN}.pdf')"
        with page.expect_download() as dl:
            page.click(f"{lic} button:has-text('Download')")
        with open(dl.value.path(), "rb") as f:
            check("3. document downloads through the backend with the right bytes", f.read() == PDF)
        page.click(f"{idr} button:has-text('Reject')")
        wait_text(page, "#doc-message", "Enter a reason")
        check("3. rejecting needs a reason (nothing sent)",
              call("GET", f"/admin/organizations/{org_id}", token=admin)[1]["documents"][1]["verification_status"] == "pending")
        page.click(f"{lic} button:has-text('Approve')")
        wait_text(page, "#doc-message", f"license-{RUN}.pdf (Console Pharmacy {RUN}) approved")
        settled(page, "#doc-rows")
        check("3. approved document leaves the pending queue without a reload",
              f"license-{RUN}.pdf" not in page.inner_text("#doc-rows"))
        page.fill(f"{idr} input", "Photo is blurry (console e2e)")
        page.click(f"{idr} button:has-text('Reject')")
        wait_text(page, "#doc-message", "rejected")
        docs = {d["file_name"]: d for d in call("GET", f"/admin/organizations/{org_id}", token=admin)[1]["documents"]}
        check("3. reviews persisted in the backend",
              docs[f"license-{RUN}.pdf"]["verification_status"] == "approved"
              and docs[f"id-{RUN}.pdf"]["rejection_reason"] == "Photo is blurry (console e2e)")
        page.select_option("#doc-filters [name=status]", "rejected")
        # The backend lists documents oldest first (right for the pending queue),
        # so on a database with history the newest rejection can be on a later page.
        for _ in range(50):
            settled(page, "#doc-rows")
            if f"id-{RUN}.pdf" in page.inner_text("#doc-rows") or page.is_disabled("[data-page='documents:next']"):
                break
            page.click("[data-page='documents:next']")
        statuses = page.locator("#doc-rows .badge").all_inner_texts()
        check("3. rejected filter lists only rejected documents", statuses and all(t.lower() == "rejected" for t in statuses), statuses)
        check("3. status filter shows the rejected document and its reason",
              "Photo is blurry (console e2e)" in page.inner_text(f"#doc-rows tr:has-text('id-{RUN}.pdf')"))
        page.click(f"#doc-rows tr:has-text('id-{RUN}.pdf') button:has-text('Open organization')")
        page.wait_for_selector("#detail-view:not([hidden])")
        wait_text(page, "#detail-name", f"Console Pharmacy {RUN}")
        check("3. 'Open organization' opens its review screen", page.is_visible("[data-panel=organizations]"))

        # ---- 4/5. Users: search, deactivate, reactivate, admin rights, self-protection.
        open_tab(page, "users")
        page.fill("#user-filters [name=q]", f"console-target-{RUN}")
        page.click("#user-filters button")
        row = f"#user-rows tr[data-user='console-target-{RUN}@example.com']"
        page.wait_for_selector(row)
        settled(page, "#user-rows")
        check("4. user search finds the account", page.locator("#user-rows tr").count() == 1)

        dialogs["answer"] = False
        page.click(f"{row} button:has-text('Deactivate')")
        page.wait_for_timeout(300)
        check("4. cancelling the confirmation changes nothing",
              login(f"console-target-{RUN}@example.com")[0] == 200 and "active" in page.inner_text(row).lower())
        dialogs["answer"] = True
        page.click(f"{row} button:has-text('Deactivate')")
        wait_text(page, "#user-message", "has been deactivated")
        check("4. deactivation asks for confirmation", "lose access" in dialogs["seen"][-1])
        check("4. row shows 'inactive' without a reload", "inactive" in page.inner_text(row).lower())
        check("4. a deactivated account cannot sign in (backend)", login(f"console-target-{RUN}@example.com")[0] == 401)
        check("4. ...and its existing token stops working", call("GET", "/auth/me", token=world["target"])[0] == 401)
        page.click(f"{row} button:has-text('Reactivate')")
        wait_text(page, "#user-message", "has been reactivated")
        check("4. reactivated account can sign in again", login(f"console-target-{RUN}@example.com")[0] == 200)

        page.click(f"{row} button:has-text('Make admin')")
        wait_text(page, "#user-message", "is now a platform administrator")
        target_token = login(f"console-target-{RUN}@example.com")[1]["access_token"]
        check("5. granting admin works in the backend", call("GET", "/admin/users", token=target_token)[0] == 200)
        check("5. row shows the admin badge", page.locator(f"{row} .badge.admin").count() == 1)
        page.select_option("#user-filters [name=role]", "admins")
        page.wait_for_selector(row)
        page.click(f"{row} button:has-text('Remove admin')")
        wait_text(page, "#user-message", "is no longer a platform administrator")
        settled(page, "#user-rows")
        check("5. revoking admin works in the backend", call("GET", "/admin/users", token=target_token)[0] == 403)
        check("5. the row leaves the 'administrators' list", page.locator(row).count() == 0)

        page.select_option("#user-filters [name=role]", "")
        page.fill("#user-filters [name=q]", ADMIN_EMAIL)
        page.click("#user-filters button")
        self_row = f"#user-rows tr[data-user='{ADMIN_EMAIL}']"
        page.wait_for_selector(self_row)
        check("5. no deactivate/remove-admin buttons on your own account",
              page.locator(f"{self_row} button").count() == 0 and "Your account" in page.inner_text(self_row))
        page.fill("#user-filters [name=q]", f"nobody-{RUN}")
        page.click("#user-filters button")
        wait_text(page, "#user-rows", "No accounts match")
        check("10. empty state for a search with no matches", True)

        # ---- 6. Drugs: validation, create, duplicate detection, double submit, edit.
        open_tab(page, "catalogue")
        page.click("[data-catalogue-view=drugs]")
        page.click("#drug-new")
        page.click("#drug-save")
        wait_text(page, "#drug-form-error", "Enter the drug name")
        check("8. drug name is required", True)
        drug_name = f"Consoletol {RUN}"
        page.fill("#drug-form [name=name]", drug_name)
        page.fill("#drug-form [name=therapeutic_class]", "Analgesic")
        page.dblclick("#drug-save")  # a double click must not create two drugs
        wait_text(page, "#drug-message", f"{drug_name} added to the catalogue")
        created = ok("GET", "/catalogue/drugs?" + urllib.parse.urlencode({"q": drug_name}))
        check("6. drug created (once, despite the double click)", created["total"] == 1, created)
        drug_id = created["items"][0]["drug_id"]
        page.click("#drug-new")
        page.fill("#drug-form [name=name]", drug_name.upper())
        page.click("#drug-save")
        wait_text(page, "#drug-form-error", "already exists")
        check("8. duplicate drug name is reported by the backend (409)", page.is_visible("#drug-form"))
        page.click("#drug-cancel")
        page.fill("#drug-filters [name=q]", drug_name)
        page.click("#drug-filters button")
        drow = f"#drug-rows tr[data-drug='{drug_name}']"
        page.wait_for_selector(drow)
        page.click(f"{drow} button:has-text('Edit')")
        page.fill("#drug-form [name=therapeutic_class]", "Analgesic and antipyretic")
        page.click("#drug-save")
        wait_text(page, "#drug-message", f"{drug_name} updated")
        check("6. drug edited", ok("GET", f"/catalogue/drugs/{drug_id}")["therapeutic_class"] == "Analgesic and antipyretic")
        check("6. list shows the change without a reload", "Analgesic and antipyretic" in page.inner_text(drow))

        # ---- 7. Products: drug relationship, validation, duplicates, edit, retire, reactivate.
        page.click(f"{drow} button:has-text('View products')")
        page.wait_for_selector("#products-view:not([hidden])")
        wait_text(page, "#product-drug-filter", drug_name)
        wait_text(page, "#product-rows", "No products match")
        check("7. 'View products' filters by the drug (empty so far)", True)
        page.click("#product-new")
        page.wait_for_function(f"document.querySelector('#product-drug').value === '{drug_id}'")
        check("7. new product form starts with the filtered drug", True)
        page.select_option("#product-drug", "")
        page.fill("#product-form [name=product_name]", f"Consoletol {RUN} 500mg tablets")
        page.click("#product-save")
        wait_text(page, "#product-form-error", "Choose the drug")
        check("8. a product needs a drug", True)
        page.fill("#product-drug-search", drug_name)
        page.wait_for_function(f"[...document.querySelector('#product-drug').options].some(o => o.value === '{drug_id}')")
        page.select_option("#product-drug", str(drug_id))
        page.fill("#product-form [name=strength]", "500mg")
        page.fill("#product-form [name=dosage_form]", "tablet")
        page.fill("#product-form [name=barcode]", f"BC{RUN}")
        page.click("#product-save")
        pname = f"Consoletol {RUN} 500mg tablets"
        wait_text(page, "#product-message", f"{pname} added to the catalogue")
        prow = f"#product-rows tr[data-product='{pname}']"
        page.wait_for_selector(prow)
        product = ok("GET", "/catalogue/products?" + urllib.parse.urlencode({"q": pname}))["items"][0]
        check("7. product created and linked to the drug", product["drug_id"] == drug_id and product["strength"] == "500mg")

        page.click("#product-new")
        page.select_option("#product-drug", str(drug_id))
        page.fill("#product-form [name=product_name]", f"Another name {RUN}")
        page.fill("#product-form [name=strength]", "250mg")
        page.fill("#product-form [name=barcode]", f"BC{RUN}")
        page.click("#product-save")
        wait_text(page, "#product-form-error", "Barcode is already used")
        check("8. duplicate barcode reported by the backend (409)", page.is_visible("#product-form"))
        page.click("#product-cancel")

        page.click(f"{prow} button:has-text('Edit')")
        page.wait_for_function(f"document.querySelector('#product-form [name=product_name]').value === '{pname}'")
        page.click("#product-save")
        wait_text(page, "#product-form-error", "Nothing has changed")
        page.fill("#product-form [name=pack_size]", "100 tablets")
        page.fill("#product-form [name=barcode]", "")  # cleared: sent as null
        page.click("#product-save")
        wait_text(page, "#product-message", f"{pname} updated")
        edited = ok("GET", f"/catalogue/products/{product['product_id']}")
        check("7. product edited (new pack size, barcode removed)", edited["pack_size"] == "100 tablets" and edited["barcode"] is None, edited)

        page.click(f"{prow} button:has-text('Retire')")
        wait_text(page, "#product-message", "has been retired")
        settled(page, "#product-rows")
        check("7. retiring asked for confirmation", "Retired products no longer appear" in dialogs["seen"][-1])
        check("7. retired product is hidden from the default list", page.locator(prow).count() == 0)
        check("7. backend marks it inactive", ok("GET", f"/catalogue/products/{product['product_id']}")["is_active"] is False)
        page.check("#product-filters [name=include_inactive]")
        page.wait_for_selector(f"{prow}.retired")
        check("7. 'include retired' shows it, clearly marked", "retired" in page.inner_text(f"{prow} .badge").lower())
        page.click(f"{prow} button:has-text('Reactivate')")
        wait_text(page, "#product-message", "is active again")
        check("7. reactivated", ok("GET", f"/catalogue/products/{product['product_id']}")["is_active"] is True)

        # ---- 7b. Organization detail: stock, stock history and orders (read only).
        ok("POST", f"/admin/organizations/{org_id}/review", {"decision": "approved"}, admin_token())
        loc = ok("POST", f"/organizations/{org_id}/locations", {"name": f"Branch {RUN}", "latitude": -1.95, "longitude": 30.06}, world["owner"])
        stock = f"/organizations/{org_id}/locations/{loc['location_id']}/stock/{product['product_id']}"
        ok("PUT", stock, {"quantity": 40}, world["owner"])
        ok("PUT", stock, {"quantity": 35}, world["owner"])
        open_tab(page, "organizations")
        page.wait_for_selector("#detail-view:not([hidden])")  # the tab reopens the last organization viewed
        page.click("#back")
        page.wait_for_selector("#list-view:not([hidden])")
        page.fill("#filters [name=q]", f"Console Pharmacy {RUN}")
        page.click("#filters button")
        page.wait_for_selector(f"#org-rows tr:has-text('Console Pharmacy {RUN}')")
        page.click(f"#org-rows tr:has-text('Console Pharmacy {RUN}') button")
        wait_text(page, "#org-inventory", pname)
        stock_row = f"#org-inventory tr:has-text('{pname}')"
        check("7b. admin sees the organization's stock (read only)",
              f"Branch {RUN}" in page.inner_text(stock_row) and "35" in page.inner_text(stock_row)
              and page.locator("#org-inventory input").count() == 0)
        page.click(f"{stock_row} button:has-text('History')")
        wait_text(page, "#org-inventory .history", "40 → 35")
        check("7b. stock history shows the change", True)
        wait_text(page, "#org-orders", "No purchase orders yet")
        check("7b. empty order list is explained", True)

        # ---- 9. Search insights: unmet demand and the catalogue link.
        open_tab(page, "insights")
        q = f"unmetmedicine {RUN}"
        wait_text(page, "#insight-rows", q)
        cells = page.inner_text(f"#insight-rows tr[data-query='{q}']")
        check("9. search insights show the query with its counts", str(world["searches"]) in cells and "100%" in cells, cells)
        page.check("#insight-filters [name=only_unmet]")
        settled(page, "#insight-rows")
        rows = page.locator("#insight-rows tr[data-query]")
        check("9. 'only searches that found nothing' keeps only unmet rows",
              rows.count() >= 1 and all("%" in rows.nth(i).inner_text() for i in range(rows.count())))
        page.click(f"#insight-rows tr[data-query='{q}'] button:has-text('Check catalogue')")
        page.wait_for_selector("#products-view:not([hidden])")
        wait_text(page, "#product-rows", "No products match")
        check("9. 'Check catalogue' searches the catalogue for it (a gap: nothing found)",
              page.input_value("#product-filters [name=q]") == q)

        # ---- 10. Loading and error states.
        open_tab(page, "users")
        page.route("**/admin/users?*", lambda r: r.fulfill(status=503, content_type="application/json",
                                                           body='{"detail": "A database error occurred."}'))
        page.click("[data-refresh=users]")
        wait_text(page, "#user-list-message", "A database error occurred.")
        check("10. backend errors are shown in the section", True)
        page.unroute("**/admin/users?*")
        page.evaluate("""() => { const f = window.fetch; window.__slow = true;
            window.fetch = (u, o) => window.__slow && String(u).includes('/admin/users')
              ? new Promise(r => setTimeout(r, 1200)).then(() => f(u, o)) : f(u, o); }""")
        page.click("[data-refresh=users]")
        page.wait_for_timeout(300)
        check("10. a loading message shows while waiting", page.text_content("#user-list-message") == "Loading…")
        page.wait_for_function("document.querySelector('#user-list-message').textContent === ''")
        page.evaluate("window.__slow = false")

        # ---- 11. Expired session in a new section returns to sign-in.
        page.evaluate("""() => { const s = JSON.parse(sessionStorage.getItem('apexrx_session'));
                                 s.token = 'expired.token.value'; sessionStorage.setItem('apexrx_session', JSON.stringify(s)); }""")
        open_tab(page, "catalogue")
        page.click("[data-catalogue-view=drugs]")
        page.click("#drug-new")
        page.fill("#drug-form [name=name]", f"Never saved {RUN}")
        page.click("#drug-save")
        page.wait_for_selector("#login-view:not([hidden])")
        check("11. an expired session returns to sign in", "session has expired" in page.text_content("#login-error"))
        check("11. nothing was saved with the expired session",
              ok("GET", "/catalogue/drugs?" + urllib.parse.urlencode({"q": f"Never saved {RUN}"}))["total"] == 0)

        # ---- Phone width: every section fits without sideways scrolling.
        page.fill("#login-form [name=email]", ADMIN_EMAIL)
        page.fill("#login-form [name=password]", ADMIN_PASSWORD)
        page.click("#login-button")
        page.wait_for_selector("#dashboard-view:not([hidden])")
        page.set_viewport_size({"width": 375, "height": 800})
        wide = []
        for tab in ("overview", "organizations", "documents", "users", "catalogue", "insights"):
            open_tab(page, tab)
            page.wait_for_timeout(400)
            if page.evaluate("document.documentElement.scrollWidth > window.innerWidth"):
                wide.append(tab)
        check("mobile: no horizontal page scroll in any section", not wide, wide)

        check("no page errors", not errors, errors)
        browser.close()

    print(f"\n{'ALL PASSED' if not failures else str(len(failures)) + ' FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
