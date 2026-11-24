"""Pharmacy and supplier applications in a real browser, against a LOCAL backend
and a throwaway database (run like the other e2e tests):

  1. A new pharmacy cannot submit until every required document is chosen;
     submitting opens the application status page ("awaiting review").
  2. Pending: the dashboard sends the user to the status page, and the server
     refuses operational data (403 organization_not_approved).
  3. Rejected: the status page shows the outcome, ApexRX's note and the
     document's reason, and offers "Correct and resubmit".
  4. Approved: the status page opens the workspace; the dashboard works.
  5. Suspended: the dashboard is closed again; the status page explains.
  6. Phone width and French.

Documents are labelled dummy PDFs ("not a real licence"); accounts use
example.com addresses in the throwaway database only.
"""

import sys

from playwright.sync_api import sync_playwright

import e2e_dashboards as D  # noqa: E402

RUN, PW, check, failures = D.RUN, D.PW, D.check, D.failures
DOC = {"name": "test-licence.pdf", "mimeType": "application/pdf", "buffer": D.TEST_PDF}


def fresh(browser, width=1280, height=900):
    ctx = browser.new_context(viewport={"width": width, "height": height})
    ctx.route("**/js/config.js", lambda r: r.fulfill(content_type="application/javascript",
                                                     body=f'window.APEX_CONFIG = {{ API_BASE_URL: "{D.API}" }};'))
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    return ctx, page, errors


def sign_in(page, email):
    page.goto(D.SITE + "/pharmacy-sign-in.html")
    page.fill("#account [name=email]", email)
    page.fill("#account [name=password]", PW)
    page.click("#account-submit")


def main():
    admin = D.call("POST", "/auth/login", {"email": D.ADMIN_EMAIL, "password": D.ADMIN_PASSWORD,
                                           "account_type": "admin"})["access_token"]
    email = f"apply-owner-{RUN}@example.com"
    token = D.account(email, "Apply Owner", "pharmacy")
    D.verify_email(token)
    org = D.call("POST", "/organizations", {"name": f"Apply Pharmacy {RUN}", "type": "pharmacy"}, token)["organization_id"]
    D.call("POST", f"/organizations/{org}/locations", {"name": "Apply Branch", "city": "Gasabo"}, token)

    with sync_playwright() as p:
        browser = p.chromium.launch(channel=D.os.environ.get("E2E_BROWSER_CHANNEL") or None, headless=True)
        all_errors = []

        # ---- 1. documents, then submit
        ctx, page, errors = fresh(browser)
        sign_in(page, email)
        page.wait_for_selector("#documents:not([hidden])", timeout=30000)
        check("1. an unfinished registration continues at the documents step", True)
        check("1. 'Submit for review' is disabled with no documents", page.is_disabled("#documents-submit"))
        inputs = page.locator("#doc-list input[type=file]")
        check("1. three required documents are asked for (pharmacy licence, business licence, owner ID)", inputs.count() == 3)
        inputs.nth(0).set_input_files(DOC)
        inputs.nth(1).set_input_files(DOC)
        check("1. still disabled with one document missing", page.is_disabled("#documents-submit"))
        inputs.nth(2).set_input_files(DOC)
        check("1. enabled once every document is chosen", page.is_enabled("#documents-submit"))
        page.click("#documents-submit")
        page.wait_for_url("**/business-status.html*", timeout=30000)
        page.wait_for_selector("#bs-main:not([hidden])", timeout=30000)
        text = page.inner_text("#bs-main")
        check("1. after submitting: the status page says it is received and awaiting review",
              "We have received your application." in text and "Awaiting review" in page.inner_text("#bs-badge")
              and "workspace stays closed until your application is approved" in text, text[:300])
        check("1. each required document shows as awaiting review",
              page.locator("#bs-docs li").count() == 3 and page.inner_text("#bs-docs").count("Awaiting review") == 3)
        check("1. the page says how to get help", "Contact" in page.inner_text("#bs-contact"))

        # ---- 2. pending: no dashboard, no operational data
        page.goto(D.SITE + "/pharmacy-dashboard.html")
        page.wait_for_url("**/business-status.html*", timeout=30000)
        check("2. a pending pharmacy opening its dashboard is sent to the status page", True)
        status, body = D.call("GET", f"/organizations/{org}/inventory", token=token, expect_error=True)
        check("2. the server refuses operational data while pending",
              status == 403 and body["code"] == "organization_not_approved", (status, body))

        # ---- 3. rejected
        app = D.call("GET", f"/organizations/{org}/application", token=token)
        licence = app["required_documents"][0]
        D.call("POST", f"/admin/documents/{licence['document_id']}/review",
               {"decision": "rejected", "rejection_reason": "This licence has expired (browser test)."}, admin)
        D.call("POST", f"/admin/organizations/{org}/review",
               {"decision": "rejected", "notes": "Please upload a current pharmacy licence."}, admin)
        page.click("#bs-refresh")
        page.wait_for_function("document.querySelector('#bs-badge').textContent.includes('Not approved')", timeout=20000)
        text = page.inner_text("#bs-main")
        check("3. rejected: outcome, ApexRX's note and the document's reason are shown",
              "Your application was not approved." in text and "Please upload a current pharmacy licence." in text
              and "This licence has expired (browser test)." in text)
        check("3. rejected: 'Correct and resubmit' leads to the registration review",
              page.inner_text("#bs-action").startswith("Correct and resubmit")
              and page.get_attribute("#bs-action", "href") == "pharmacy-sign-in.html#review")
        page.click("#bs-action")
        page.wait_for_selector("#review:not([hidden])", timeout=30000)
        page.select_option("#upload-type", "pharmacy_license")
        page.set_input_files("#upload-file", DOC)
        page.click("#upload-button")
        page.wait_for_function("document.querySelector('#review-documents').textContent.split('Awaiting review').length > 3",
                               timeout=20000)
        page.click("#review-resubmit")
        page.wait_for_url("**/business-status.html*", timeout=30000)
        page.wait_for_function("document.querySelector('#bs-badge').textContent.includes('Awaiting review')", timeout=20000)
        check("3. resubmitted with a replacement licence: awaiting review again", True)

        # ---- 4. approved
        for d in D.call("GET", f"/organizations/{org}/application", token=token)["required_documents"]:
            if d["status"] == "pending":
                D.call("POST", f"/admin/documents/{d['document_id']}/review", {"decision": "approved"}, admin)
        D.call("POST", f"/admin/organizations/{org}/review", {"decision": "approved"}, admin)
        page.click("#bs-refresh")
        page.wait_for_function("document.querySelector('#bs-badge').textContent.includes('Approved')", timeout=20000)
        check("4. approved: the status page offers the workspace",
              page.inner_text("#bs-action").startswith("Open your workspace")
              and page.get_attribute("#bs-action", "href") == "pharmacy-dashboard.html")
        page.click("#bs-action")
        page.wait_for_url("**/pharmacy-dashboard.html*", timeout=30000)
        page.wait_for_selector(".nav[aria-current=page]", timeout=30000)
        check("4. approved: the dashboard opens", "business-status" not in page.url)
        all_errors += errors
        ctx.close()

        # ---- 5. suspended
        D.call("POST", f"/admin/organizations/{org}/review", {"decision": "suspended", "notes": "Browser test suspension."}, admin)
        ctx, page, errors = fresh(browser, 390, 844)
        sign_in(page, email)
        page.wait_for_url("**/business-status.html*", timeout=30000)
        page.wait_for_selector("#bs-main:not([hidden])", timeout=30000)
        text = page.inner_text("#bs-main")
        check("5. suspended: signing in opens the status page, not the dashboard",
              "Your account is suspended." in text and "Browser test suspension." in text and page.is_hidden("#bs-action"))
        page.goto(D.SITE + "/pharmacy-dashboard.html")
        page.wait_for_url("**/business-status.html*", timeout=30000)
        check("5. suspended: the dashboard stays closed", True)

        # ---- 6. phone width and French
        check("6. no sideways scrolling at 390px", not page.evaluate("document.documentElement.scrollWidth > innerWidth + 1"))
        page.select_option("#workflow-language", "fr")
        page.wait_for_function("document.querySelector('#bs-lead').textContent.includes('Votre compte est suspendu')",
                               timeout=10000)
        check("6. the status page is translated (French)", True)
        all_errors += errors
        ctx.close()

        check("no script errors", not all_errors, all_errors[:3])
        browser.close()
    print(f"\n{'ALL PASSED' if not failures else str(len(failures)) + ' FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
