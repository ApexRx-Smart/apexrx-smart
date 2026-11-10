"""End-to-end check of pharmacy and supplier registration with email
verification, against a LOCAL backend and a throwaway database:

  * pharmacy journey through the UI: account -> verification email (mock
    provider, development only) -> link opened in another tab -> details with a
    structured Rwandan address -> documents -> review -> workspace; stored as a
    pharmacy with every address part, nothing about payment or subscriptions;
  * the verification link page: success, reopened link, invalid link, a link
    replaced by a newer email, resend with a countdown;
  * resuming an incomplete registration (unverified, verified without details,
    details without documents) by signing in again;
  * the reported bug: a session left in the tab (here an administrator's) is
    shown as "Signed in as …" and never silently used to register, and an
    unknown email cannot sign in;
  * supplier journey through the UI, stored as a supplier (never a pharmacy),
    admin rejection with a note -> resubmission -> approval shown on the page;
  * authorization after registration, translations, and the mobile layout.

Never point this at production: it registers accounts and organizations.

Setup: backend on http://127.0.0.1:8000 with APP_ENV=development and
EMAIL_PROVIDER=mock, frontend on http://127.0.0.1:5501, an admin account, then
  E2E_ADMIN_EMAIL=... E2E_ADMIN_PASSWORD=... python frontend/tests/e2e_registration.py
(E2E_BROWSER_CHANNEL=chrome uses the installed Chrome.)
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
ADMIN_EMAIL, ADMIN_PASSWORD = os.environ["E2E_ADMIN_EMAIL"], os.environ["E2E_ADMIN_PASSWORD"]
RUN = uuid.uuid4().hex[:6]
PASSWORD = "Registration-Pass-2026"
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


def login(email, password=PASSWORD):
    return call("POST", "/auth/login", {"email": email, "password": password})[1]["access_token"]


def admin_token():
    return login(ADMIN_EMAIL, ADMIN_PASSWORD)


def account(email):
    call("POST", "/auth/register", {"name": email.split("@")[0], "email": email, "password": PASSWORD})
    return login(email)


def latest_email(token):
    status, mail = call("GET", "/dev/email/latest", token=token)
    assert status == 200, mail
    return mail


def verify_by_api(token):
    call("POST", "/auth/email/send", {"next": "pharmacy"}, token)
    call("POST", "/auth/email/verify", {"token": latest_email(token)["token"]})


def find_org(name, type_=None):
    q = {"q": name, "limit": 5}
    if type_:
        q["type"] = type_
    page = call("GET", "/admin/organizations?" + urllib.parse.urlencode(q), token=admin_token())[1]
    return [o for o in page["items"] if o["name"] == name]


def session_token(page):
    return page.evaluate("JSON.parse(sessionStorage.getItem('apexrx_session')).token")


def on_dashboard(page, timeout=30000):
    page.wait_for_url("**/*-dashboard.html*", timeout=timeout)
    page.wait_for_selector(".nav[aria-current=page]", timeout=timeout)


def visible(page, selector, timeout=20000):
    page.wait_for_selector(f"{selector}:not([hidden])", timeout=timeout)


def wait_text(page, selector, text, timeout=15000):
    page.wait_for_function("([s, t]) => (document.querySelector(s) || {}).textContent?.includes(t)",
                           arg=[selector, text], timeout=timeout)


def new_context(browser, viewport=None):
    ctx = browser.new_context(viewport=viewport or {"width": 1366, "height": 900})
    ctx.route("**/js/config.js", lambda route: route.fulfill(
        content_type="application/javascript", body=f'window.APEX_CONFIG = {{ API_BASE_URL: "{API}" }};'))
    return ctx


def watch(page, errors, allowed=()):
    page.on("pageerror", lambda e: errors.append(f"{page.url}: {e}"))
    # Browsers log every 4xx response. The expected ones are listed per page
    # (a wrong password, links the test makes invalid on purpose).
    page.on("console", lambda m: errors.append(f"{page.url}: {m.text}")
            if m.type == "error" and not any(a in m.text for a in ("Permissions policy violation",) + tuple(allowed))
            else None)


def fill_account(page, email, confirm=True):
    page.fill("#account [name=email]", email)
    page.fill("#account [name=password]", PASSWORD)
    if confirm:
        page.fill("#account [name=confirm]", PASSWORD)
    page.click("#account-submit")


def choose_address(page):
    """Kigali City > Gasabo > Kimironko > the first cell and village in the list."""
    page.select_option("#address-fields [name=province]", "Kigali")
    page.select_option("#address-fields [name=district]", "Gasabo")
    page.select_option("#address-fields [name=sector]", "Kimironko")
    cell = page.eval_on_selector("#address-fields [name=cell]", "s => s.options[1].value")
    page.select_option("#address-fields [name=cell]", cell)
    village = page.eval_on_selector("#address-fields [name=village]", "s => s.options[1].value")
    page.select_option("#address-fields [name=village]", village)
    return cell, village


def open_link(ctx, link, errors, allowed=()):
    tab = ctx.new_page()
    watch(tab, errors, allowed)
    tab.goto(link)
    tab.wait_for_function("!document.querySelector('#verify-actions').hidden", timeout=15000)
    return tab


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=os.environ.get("E2E_BROWSER_CHANNEL") or None, headless=True)
        errors = []

        # ============================================= the reported sign-in bug
        ctx = new_context(browser)
        page = ctx.new_page()
        watch(page, errors, allowed=("status of 401",))
        page.goto(SITE + "/pharmacies.html#signin")
        fill_account(page, f"nobody-{RUN}@example.com", confirm=False)
        wait_text(page, "#form-error", "Incorrect email or password")
        check("bug: an email without an account cannot sign in",
              page.is_visible("#account") and page.is_hidden("#signed-in-as")
              and page.evaluate("sessionStorage.getItem('apexrx_session')") is None)

        # A session left in the tab by the admin portal is not used silently.
        page.goto(SITE + "/ops-console-7f3k9q.html")
        page.fill("#login-form [name=email]", ADMIN_EMAIL)
        page.fill("#login-form [name=password]", ADMIN_PASSWORD)
        page.click("#login-button")
        visible(page, "#dashboard-view")
        page.goto(SITE + "/pharmacies.html")
        visible(page, "#account-panel")
        check("bug: an existing session is named ('Signed in as …') instead of looking like a new sign-in",
              page.inner_text("#signed-in-email") == ADMIN_EMAIL and page.is_visible("#signed-in-as"))
        check("bug: an administrator is not taken into pharmacy registration",
              "administrator" in page.inner_text("#account-panel-text") and page.is_hidden("#verify-email")
              and page.is_hidden("#details"))
        page.click("#sign-out")
        visible(page, "#account")
        check("bug: 'Sign out' clears the session and shows sign in, without a false 'session expired'",
              page.evaluate("sessionStorage.getItem('apexrx_session')") is None and page.inner_text("#form-error") == ""
              and page.is_hidden("#signed-in-as"))
        ctx.close()

        # ================================================== pharmacy journey
        ctx = new_context(browser)
        page = ctx.new_page()
        watch(page, errors)
        email = f"reg-pharmacy-{RUN}@example.com"
        page.goto(SITE + "/pharmacies.html")
        check("pharmacy: no plan, payment or subscription in the registration",
              page.locator("#payment, .plan, .methods").count() == 0
              and not any(w in page.inner_text(".workspace") for w in ("RWF", "Payment", "payment", "subscription", "Plan")))
        fill_account(page, email)
        visible(page, "#verify-email")
        wait_text(page, "#verify-state", "We sent you a verification email")
        token = session_token(page)
        check("pharmacy: the verification step names the account and sends the email by itself",
              page.inner_text("#verify-address") == email and page.inner_text("#signed-in-email") == email
              and page.is_visible("#verify-expiry-row"))
        mail = latest_email(token)
        check("pharmacy: the email links to verify-email.html for the pharmacy page, token in the fragment",
              mail["to"] == email and "/verify-email.html?next=pharmacy#token=" in mail["link"]
              and "Confirm this email address" in mail["text"])
        # Not verified yet: the button says so, the backend still refuses an organization.
        page.click("#check-email")
        wait_text(page, "#form-error", "not verified yet")
        status, body = call("POST", "/organizations", {"name": "Too Early", "type": "pharmacy"}, token)
        check("pharmacy: the backend refuses an organization before verification",
              status == 403 and body.get("reason") == "email_unverified")

        tab = open_link(ctx, mail["link"], errors)
        check("verify page: success message, masked address, continue link to the pharmacy page",
              tab.inner_text("#verify-title") == "Your email address is verified."
              and tab.get_attribute("#verify-continue", "href") == "pharmacies.html"
              and email not in tab.inner_text("body") and tab.is_visible("#verify-email-row"))
        check("verify page: the token is removed from the address bar", "token" not in tab.url)
        tab.close()
        page.bring_to_front()
        visible(page, "#details")
        check("pharmacy: the registration tab continues by itself once the link is opened",
              page.inner_text("#step-title") == "Make your pharmacy easy to find.")

        # Reopening the link later changes nothing.
        tab = open_link(ctx, mail["link"], errors)
        check("verify page: a reopened link says the email is already verified",
              tab.inner_text("#verify-title") == "Your email address is already verified.")
        tab.close()

        # Details: validation, then a full structured address.
        page.click("#details-submit")
        wait_text(page, "#form-error", "Enter the pharmacy name")
        check("details: nothing is sent before validation", find_org(f"Reg Pharmacy {RUN}") == [])
        check("details: only supported fields (no license, NPC, TIN or FDA numbers)",
              sorted(page.eval_on_selector_all("#details input[name], #details select[name]", "els => els.map(e => e.name)"))
              == sorted(["name", "phone", "place", "whatsapp", "street", "latitude", "longitude",
                         "province", "district", "sector", "cell", "village"]))
        name = f"Reg Pharmacy {RUN}"
        page.fill("#details [name=name]", name)
        page.fill("#details [name=phone]", "0788 123 456")
        page.fill("#details [name=whatsapp]", "0789 222 333")
        cell, village = choose_address(page)
        check("details: the address lists cascade (district -> sector -> cell -> village)",
              page.locator("#address-fields [name=village] option").count() > 1)
        page.fill("#details [name=street]", "KG 11 Ave")
        page.fill("#details [name=latitude]", "48.85")
        page.fill("#details [name=longitude]", "2.35")
        page.click("#details-submit")
        wait_text(page, "#form-error", "outside Rwanda")
        page.fill("#details [name=latitude]", "-1.9490")
        page.fill("#details [name=longitude]", "30.1260")
        check("details: a map link checks the coordinates",
              "openstreetmap.org/?mlat=-1.949" in (page.get_attribute("#map-check", "href") or ""))
        page.click("#details-submit")
        visible(page, "#documents")
        types = page.eval_on_selector_all("#doc-list input[type=file]", "els => els.map(e => e.dataset.documentType)")
        check("documents: pharmacy documents", types == ["pharmacy_license", "business_license", "owner_id"], types)
        orgs = find_org(name)
        check("pharmacy: stored as a pending pharmacy", len(orgs) == 1 and orgs[0]["type"] == "pharmacy"
              and orgs[0]["status"] == "pending", orgs)
        detail = call("GET", f"/admin/organizations/{orgs[0]['organization_id']}", token=admin_token())[1]
        loc = detail["locations"][0]
        check("pharmacy: every address part is stored (province, district, sector, cell, village, street)",
              (loc["region"], loc["city"], loc["sector"], loc["cell"], loc["village"], loc["address"])
              == ("Kigali City", "Gasabo", "Kimironko", cell, village, "KG 11 Ave"), loc)
        check("pharmacy: phone numbers normalized, coordinates stored",
              detail["phone"] == "+250788123456" and loc["whatsapp_phone"] == "0789 222 333"
              and float(loc["latitude"]) == -1.949 and float(loc["longitude"]) == 30.126, (detail["phone"], loc))

        page.set_input_files("#doc-list input[data-document-type=pharmacy_license]",
                             files=[{"name": f"pharmacy-license-{RUN}.pdf", "mimeType": "application/pdf", "buffer": PDF}])
        page.set_input_files("#doc-list input[data-document-type=owner_id]",
                             files=[{"name": f"owner-{RUN}.pdf", "mimeType": "application/pdf", "buffer": PDF}])
        page.set_input_files("#doc-list input[data-document-type=business_license]",
                             files=[{"name": "notes.txt", "mimeType": "text/plain", "buffer": b"not a document"}])
        wait_text(page, "#form-error", "PDF, PNG or JPG")
        page.click("#documents-submit")
        visible(page, "#review")
        wait_text(page, "#review-documents", f"owner-{RUN}.pdf")
        facts = page.inner_text("#review-facts")
        check("review: pending status, both documents, summary of what was stored",
              page.inner_text("#review-status") == "Pending review"
              and f"pharmacy-license-{RUN}.pdf" in page.inner_text("#review-documents")
              and "Kimironko" in facts and "Gasabo" in facts and f"{email} (verified)" in facts and "Pharmacy" in facts)
        docs = call("GET", f"/organizations/{orgs[0]['organization_id']}/documents", token=token)[1]
        check("documents: stored and listed for the owner", sorted(d["document_type"] for d in docs) == ["owner_id", "pharmacy_license"])
        status, other = call("GET", f"/organizations/{orgs[0]['organization_id']}", token=account(f"stranger-{RUN}@example.com"))
        check("authorization: another account cannot read the new pharmacy", status == 404)

        page.click("#open-workspace")
        on_dashboard(page)
        check("dashboard: opens after registration, with the real status and no plan price",
              name in page.inner_text("#me-name") and "Pending verification" in page.inner_text("#ver")
              and "awaiting verification" in page.inner_text(".banner") and "/ month" not in page.inner_text("#view")
              and "not live yet" in page.inner_text("#plan-card").lower())
        page.click(".nav[data-v=set]")
        page.wait_for_function("!document.querySelector('#docs').textContent.includes('Loading')")
        check("dashboard: the uploaded documents are listed with their status",
              f"pharmacy-license-{RUN}.pdf" in page.inner_text("#docs") and "Pending verification" in page.inner_text("#docs"))
        page.click("#open-registration")
        page.wait_for_url("**/pharmacies.html*")
        visible(page, "#review")
        check("dashboard: 'Registration details' leads back to the review", page.inner_text("#review-status") == "Pending review")
        ctx.close()

        # Signing in again: a complete pharmacy goes to the workspace.
        ctx = new_context(browser)
        page = ctx.new_page()
        watch(page, errors)
        page.goto(SITE + "/pharmacies.html#signin")
        fill_account(page, email, confirm=False)
        on_dashboard(page)
        check("sign in: a registered pharmacy opens its dashboard", name in page.inner_text("#me-name"))
        ctx.close()

        # ================================== verification link problems, resend
        ctx = new_context(browser)
        page = ctx.new_page()
        watch(page, errors, allowed=("status of 400", "status of 429"))
        page.goto(SITE + "/pharmacies.html")
        email2 = f"reg-resend-{RUN}@example.com"
        fill_account(page, email2)
        wait_text(page, "#verify-state", "We sent you a verification email")
        token2 = session_token(page)
        first = latest_email(token2)
        check("resend: the button counts down before another email can be sent",
              page.is_disabled("#resend-email") and "Resend email in" in page.inner_text("#resend-email"))
        wait = max(1, call("GET", "/auth/email/status", token=token2)[1]["resend_after"])
        time.sleep(wait + 0.5)
        page.wait_for_function("!document.querySelector('#resend-email').disabled", timeout=10000)
        page.click("#resend-email")
        # Wait (in Python) until the new email is there: the request runs after the click.
        deadline = time.time() + 15
        second = latest_email(token2)
        while second["token"] == first["token"] and time.time() < deadline:
            time.sleep(0.3)
            second = latest_email(token2)
        check("resend: a new email with a new link", second["token"] != first["token"])
        tab = open_link(ctx, first["link"], errors, allowed=("status of 400",))
        check("verify page: the older link is refused as replaced by a newer email",
              tab.inner_text("#verify-title") == "A newer verification email was sent."
              and tab.get_attribute("#verify-continue", "href") == "pharmacies.html#signin" and tab.is_visible("#verify-help"))
        tab.goto(SITE + "/verify-email.html?next=supplier#token=" + "A" * 43)
        tab.wait_for_function("!document.querySelector('#verify-actions').hidden")
        check("verify page: an unknown link is refused", tab.inner_text("#verify-title") == "This verification link is not valid."
              and tab.get_attribute("#verify-continue", "href") == "suppliers.html#signin")
        tab.goto(SITE + "/verify-email.html")
        tab.wait_for_function("!document.querySelector('#verify-actions').hidden")
        check("verify page: no token at all", tab.inner_text("#verify-title") == "This verification link is not valid.")
        # The backend's "expired" answer (covered against the real database in
        # backend/tests/test_email_verification.py) is shown with its own message.
        cors = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "*", "Access-Control-Allow-Methods": "POST"}

        def expired(route):
            if route.request.method == "OPTIONS":
                route.fulfill(status=204, headers=cors)
                return
            route.fulfill(status=400, content_type="application/json", headers=cors, body=json.dumps(
                {"detail": "This verification link has expired. Request a new email.", "reason": "expired"}))
        tab.close()
        tab = ctx.new_page()  # a fresh page: only the fragment would change otherwise, with no reload
        watch(tab, errors, allowed=("status of 400",))
        tab.route("**/auth/email/verify", expired)
        tab.goto(SITE + "/verify-email.html#token=" + "B" * 43)
        tab.wait_for_function("!document.querySelector('#verify-actions').hidden")
        check("verify page: an expired link explains itself and offers sign in",
              tab.inner_text("#verify-title") == "This verification link has expired."
              and "Request a new email" in tab.inner_text("#verify-message"))
        tab.close()

        # Resume: the account is still unverified after signing in again.
        ctx.close()
        ctx = new_context(browser)
        page = ctx.new_page()
        watch(page, errors)
        page.goto(SITE + "/pharmacies.html#signin")
        fill_account(page, email2, confirm=False)
        visible(page, "#verify-email")
        check("resume: an unverified account returns to email verification", page.inner_text("#verify-address") == email2)
        tab = open_link(ctx, second["link"], errors)
        tab.close()
        page.bring_to_front()
        visible(page, "#details")
        check("resume: ...and continues to the details once verified", True)
        ctx.close()

        # Resume: details saved but no documents -> the review (with upload).
        email3 = f"reg-nodocs-{RUN}@example.com"
        t3 = account(email3)
        verify_by_api(t3)
        org3 = call("POST", "/organizations", {"name": f"No Docs Pharmacy {RUN}", "type": "pharmacy", "phone": "0788 000 111"}, t3)[1]
        ctx = new_context(browser)
        page = ctx.new_page()
        watch(page, errors)
        page.goto(SITE + "/pharmacies.html#signin")
        fill_account(page, email3, confirm=False)
        visible(page, "#details")
        check("resume: an organization without an address returns to the details, filled in",
              page.input_value("#details [name=name]") == f"No Docs Pharmacy {RUN}"
              and page.input_value("#details [name=phone]") == "+250788000111")
        call("POST", f"/organizations/{org3['organization_id']}/locations",
             {"name": "Main branch", "region": "Kigali City", "city": "Nyarugenge", "sector": "Nyamirambo",
              "cell": "Cyivugiza", "village": "Amizero"}, t3)
        page.goto(SITE + "/pharmacies.html")
        visible(page, "#review")
        check("resume: an address but no documents opens the review to upload them",
              "No documents uploaded yet" in page.inner_text("#review-documents") and page.is_visible("#review-upload"))
        page.click("#review-edit")
        visible(page, "#details")
        page.wait_for_function("document.querySelector('#address-fields [name=village]')?.value === 'Amizero'")
        check("resume: editing shows the stored address in the lists",
              page.input_value("#address-fields [name=province]") == "Kigali"
              and page.input_value("#address-fields [name=district]") == "Nyarugenge"
              and page.input_value("#address-fields [name=sector]") == "Nyamirambo")
        ctx.close()

        # ================================================== supplier journey
        ctx = new_context(browser)
        page = ctx.new_page()
        watch(page, errors)
        page.goto(SITE + "/suppliers.html")
        supplier_email = f"reg-supplier-{RUN}@example.com"
        fill_account(page, supplier_email)
        visible(page, "#verify-email")
        mail = latest_email(session_token(page))
        check("supplier: verification email links back to the supplier page", "?next=supplier#token=" in mail["link"])
        tab = open_link(ctx, mail["link"], errors)
        check("verify page: continue link to the supplier page", tab.get_attribute("#verify-continue", "href") == "suppliers.html")
        tab.close()
        page.bring_to_front()
        visible(page, "#details")
        check("supplier: details ask for a warehouse", "Warehouse name" in page.inner_text("#details"))
        supplier = f"Reg Supplies {RUN}"
        page.fill("#details [name=name]", supplier)
        page.fill("#details [name=phone]", "+250 788 111 222")
        page.fill("#details [name=place]", "Gikondo Warehouse")
        choose_address(page)
        page.click("#details-submit")
        visible(page, "#documents")
        types = page.eval_on_selector_all("#doc-list input[type=file]", "els => els.map(e => e.dataset.documentType)")
        check("supplier: supplier documents (no pharmacy license)", types == ["business_license", "owner_id"], types)
        page.set_input_files("#doc-list input[data-document-type=business_license]",
                             files=[{"name": f"supplier-license-{RUN}.pdf", "mimeType": "application/pdf", "buffer": PDF}])
        page.click("#documents-submit")
        visible(page, "#review")
        orgs = find_org(supplier)
        check("supplier: stored with organization type 'supplier'", len(orgs) == 1 and orgs[0]["type"] == "supplier", orgs)
        check("supplier: not registered as a pharmacy", find_org(supplier, "pharmacy") == [])
        org_id = orgs[0]["organization_id"]
        detail = call("GET", f"/admin/organizations/{org_id}", token=admin_token())[1]
        check("supplier: warehouse, owner and document saved",
              detail["locations"][0]["name"] == "Gikondo Warehouse" and detail["members"][0]["email"] == supplier_email
              and detail["members"][0]["role"] == "owner" and detail["documents"][0]["document_type"] == "business_license")

        # Rejected with a note -> shown -> resubmitted -> approved.
        doc_id = detail["documents"][0]["document_id"]
        call("POST", f"/admin/documents/{doc_id}/review", {"decision": "rejected", "rejection_reason": "The scan is unreadable."}, admin_token())
        call("POST", f"/admin/organizations/{org_id}/review", {"decision": "rejected", "notes": f"Upload a readable license {RUN}."}, admin_token())
        page.click("#review-refresh")
        wait_text(page, "#review-status", "Not approved")
        check("review: the rejection, the note from ApexRX and the document reason are shown",
              f"Upload a readable license {RUN}." in page.inner_text("#review-notes")
              and "The scan is unreadable." in page.inner_text("#review-documents") and page.is_visible("#review-resubmit"))
        page.set_input_files("#upload-file", files=[{"name": f"supplier-license-2-{RUN}.pdf", "mimeType": "application/pdf", "buffer": PDF}])
        page.select_option("#upload-type", "business_license")
        page.click("#upload-button")
        wait_text(page, "#review-documents", f"supplier-license-2-{RUN}.pdf")
        page.click("#review-resubmit")
        wait_text(page, "#review-status", "Pending review")
        check("review: resubmitting puts it back in the review queue",
              find_org(supplier)[0]["status"] == "pending" and page.is_hidden("#review-resubmit"))
        for d in call("GET", f"/admin/organizations/{org_id}", token=admin_token())[1]["documents"]:
            if d["verification_status"] == "pending":
                call("POST", f"/admin/documents/{d['document_id']}/review", {"decision": "approved"}, admin_token())
        call("POST", f"/admin/organizations/{org_id}/review", {"decision": "approved"}, admin_token())
        page.click("#review-refresh")
        wait_text(page, "#review-status", "Approved")
        check("review: approval in the admin console shows on the supplier page", True)
        page.click("#sign-out")
        visible(page, "#account")
        check("supplier: sign out returns to sign in", page.inner_text("#form-error") == "")
        fill_account(page, supplier_email, confirm=False)
        on_dashboard(page)
        check("sign in: an existing supplier opens the supplier dashboard",
              page.url.split("?")[0].endswith("/supplier-dashboard.html") and supplier in page.inner_text("#me-name"))
        ctx.close()

        # A supplier who signs in on the pharmacy page is pointed to the supplier page.
        ctx = new_context(browser)
        page = ctx.new_page()
        watch(page, errors)
        page.goto(SITE + "/pharmacies.html#signin")
        fill_account(page, supplier_email, confirm=False)
        visible(page, "#account-panel")
        check("sign in: a supplier on the pharmacy page is not asked to register a pharmacy",
              "belongs to a supplier" in page.inner_text("#account-panel-text") and page.is_hidden("#verify-email"))
        page.click("#account-panel-link")
        on_dashboard(page)
        check("sign in: ...and continues to the supplier dashboard, still signed in",
              page.url.split("?")[0].endswith("/supplier-dashboard.html") and supplier in page.inner_text("#me-name"))
        ctx.close()

        # ======================================= translations and mobile layout
        ctx = new_context(browser, {"width": 375, "height": 812})
        page = ctx.new_page()
        watch(page, errors)
        email4 = f"reg-mobile-{RUN}@example.com"
        verify_by_api(account(email4))
        page.goto(SITE + "/suppliers.html#signin")
        fill_account(page, email4, confirm=False)
        visible(page, "#details")
        page.wait_for_selector("#address-fields select[name=province]")
        check("mobile: the details step fits the screen",
              not page.evaluate("document.documentElement.scrollWidth > window.innerWidth"))
        page.select_option("#workflow-language", "fr")
        page.wait_for_function("document.querySelector('#step-title').textContent === 'Parlez-nous de votre entreprise.'")
        check("translations: the registration follows the language (French)",
              "Nom de l’entrepôt" in page.inner_text("#details") and "District" in page.inner_text("#address-fields"))
        page.select_option("#workflow-language", "en")
        ctx.close()

        # Leave the shared local review queue as it was: review the test's own pending documents.
        for name_ in (name, f"No Docs Pharmacy {RUN}"):
            for org in find_org(name_):
                for d in call("GET", f"/admin/organizations/{org['organization_id']}", token=admin_token())[1]["documents"]:
                    if d["verification_status"] == "pending":
                        call("POST", f"/admin/documents/{d['document_id']}/review",
                             {"decision": "rejected", "rejection_reason": "e2e test document"}, admin_token())

        check("no page errors or unexpected console errors", not errors, errors)
        browser.close()

    print(f"\n{'ALL PASSED' if not failures else str(len(failures)) + ' FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
