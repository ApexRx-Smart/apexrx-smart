"""Browser test of the pharmacy workspace: branches, employees, inventory,
purchase orders, organization switching and joining an existing pharmacy.

LOCAL backend and throwaway database only - never a shared environment.

  1. Backend on http://127.0.0.1:8000 with APP_ENV=development and
     EMAIL_PROVIDER=mock (organizations need a verified email), and an admin
     (see e2e_admin.py).
  2. Frontend on http://127.0.0.1:5501 (python -m http.server 5501 --directory frontend).
  3. E2E_ADMIN_EMAIL=... E2E_ADMIN_PASSWORD=... python frontend/tests/e2e_workspace.py

Each run creates its own accounts, organizations and catalogue entries
(suffixed with a random id) through the API, then drives the UI.
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
ADMIN_EMAIL, ADMIN_PASSWORD = os.environ["E2E_ADMIN_EMAIL"], os.environ["E2E_ADMIN_PASSWORD"]
RUN = uuid.uuid4().hex[:6]
PW = "Workspace-Pass-2026"
failures = []


def check(label, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + label + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        failures.append(label)


# ------------------------------------------------------------------ API setup
def call(method, path, body=None, token=None, expect_error=False):
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(API + path, data=json.dumps(body).encode() if body is not None else None,
                                 method=method, headers=headers)
    try:
        with urllib.request.urlopen(req) as r:
            text = r.read().decode()
            return (r.status, json.loads(text) if text else None) if expect_error else (json.loads(text) if text else None)
    except urllib.error.HTTPError as e:
        payload = e.read().decode()
        if expect_error:
            return e.code, json.loads(payload) if payload else None
        raise SystemExit(f"{method} {path} -> {e.code}: {payload}") from None


def account(email, name):
    call("POST", "/auth/register", {"name": name, "email": email, "password": PW})
    return call("POST", "/auth/login", {"email": email, "password": PW})["access_token"]


def verify_email(token):
    """The real email flow with the mock provider: send a link, read it, open it."""
    status = call("GET", "/auth/email/status", token=token)
    if status["verified"] or not status["required"]:
        return
    call("POST", "/auth/email/send", {"next": "pharmacy"}, token)
    req = urllib.request.Request(API + "/dev/email/latest", headers={"Authorization": f"Bearer {token}"})
    link_token = json.loads(urllib.request.urlopen(req).read())["token"]
    call("POST", "/auth/email/verify", {"token": link_token})


def seed():
    admin = call("POST", "/auth/login", {"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})["access_token"]
    approve = lambda org: call("POST", f"/admin/organizations/{org}/review", {"decision": "approved"}, admin)  # noqa: E731
    w = {"admin": admin}
    w["owner"] = account(f"ws-owner-{RUN}@example.com", "Workspace Owner")
    verify_email(w["owner"])
    w["org"] = call("POST", "/organizations", {"name": f"Kigali Care {RUN}", "type": "pharmacy"}, w["owner"])["organization_id"]
    w["kim"] = call("POST", f"/organizations/{w['org']}/locations", {"name": "Kimihurura Branch", "city": "Kigali", "latitude": -1.9536, "longitude": 30.089}, w["owner"])["location_id"]
    w["rem"] = call("POST", f"/organizations/{w['org']}/locations", {"name": "Remera Branch", "city": "Kigali"}, w["owner"])["location_id"]
    approve(w["org"])
    # Employees (accounts exist; the owner adds them through the UI).
    for role in ("manager", "staff", "helper"):
        w[role + "_email"] = f"ws-{role}-{RUN}@example.com"
        w[role] = account(w[role + "_email"], f"Workspace {role.title()}")
    # A second pharmacy (other owner), to test organization switching.
    w["owner2"] = account(f"ws-owner2-{RUN}@example.com", "Second Owner")
    verify_email(w["owner2"])
    w["org2"] = call("POST", "/organizations", {"name": f"Second Pharmacy {RUN}", "type": "pharmacy"}, w["owner2"])["organization_id"]
    call("POST", f"/organizations/{w['org2']}/locations", {"name": f"Nyamirambo {RUN}"}, w["owner2"])
    approve(w["org2"])
    call("POST", f"/organizations/{w['org2']}/members", {"email": w["manager_email"], "role": "manager"}, w["owner2"])
    # Catalogue + supplier stock.
    drug = call("POST", "/catalogue/drugs", {"name": f"Wstestamol {RUN}"}, admin)["drug_id"]
    w["prod"] = call("POST", "/catalogue/products", {"drug_id": drug, "product_name": f"Wstestamol {RUN} 500mg"}, admin)["product_id"]
    w["prod_name"] = f"Wstestamol {RUN} 500mg"
    sup_owner = account(f"ws-supplier-{RUN}@example.com", "Supplier Owner")
    verify_email(sup_owner)
    w["sup_owner"] = sup_owner
    w["sup"] = call("POST", "/organizations", {"name": f"Rwanda Distributors {RUN}", "type": "supplier"}, sup_owner)["organization_id"]
    wh = call("POST", f"/organizations/{w['sup']}/locations", {"name": "Gikondo Warehouse"}, sup_owner)["location_id"]
    approve(w["sup"])
    call("PUT", f"/organizations/{w['sup']}/locations/{wh}/stock/{w['prod']}", {"quantity": 5000}, sup_owner)
    call("PUT", f"/organizations/{w['sup']}/locations/{wh}/stock/{w['prod']}/offer", {"unit_price": "900"}, sup_owner)
    # Different stock per branch (set through the API; edited in the UI below).
    for loc, qty in ((w["kim"], 120), (w["rem"], 45)):
        call("PUT", f"/organizations/{w['org']}/locations/{loc}/stock/{w['prod']}", {"quantity": qty}, w["owner"])
    return w


def inventory_row(token, org, loc, product):
    items = call("GET", f"/organizations/{org}/inventory?location_id={loc}&limit=100", token=token)["items"]
    return next(i for i in items if i["product_id"] == product)


# ------------------------------------------------------------------ UI helpers
def new_page(browser):
    ctx = browser.new_context(viewport={"width": 1366, "height": 900})
    ctx.route("**/js/config.js", lambda r: r.fulfill(content_type="application/javascript",
                                                     body=f'window.APEX_CONFIG = {{ API_BASE_URL: "{API}" }};'))
    ctx.route("https://apexrx-smart.onrender.com/**", lambda r: r.abort())
    page = ctx.new_page()
    page.dialog_answers = []
    page.on("dialog", lambda d: d.accept(page.dialog_answers.pop(0) if d.type == "prompt" and page.dialog_answers else None))
    page.errors = []
    page.on("pageerror", lambda e: page.errors.append(str(e)))
    return page


def sign_in(page, email):
    page.goto(SITE + "/pharmacies.html")
    for field, value in (("email", email), ("password", PW), ("confirm", PW)):
        page.fill(f"#account [name={field}]", value)
    page.click("#account button.primary")
    page.wait_for_function("!document.querySelector('#dashboard').hidden || !document.querySelector('#verify-email').hidden"
                           " || !document.querySelector('#details').hidden || !document.querySelector('#review').hidden",
                           timeout=20000)


def open_view(page, name):
    page.click(f".sidebar [data-view={name}]")
    page.wait_for_function("() => { const s = document.querySelector('#workspace-section');"
                           " return !s.hidden && !s.textContent.startsWith('Loading'); }", timeout=15000)


def open_order(page, order_id):
    open_view(page, "orders")
    back = page.get_by_role("button", name="← Back to orders")
    if back.count():
        back.click()
    page.wait_for_selector(f"tr[data-order='{order_id}']")
    page.locator(f"tr[data-order='{order_id}']").get_by_role("button", name="Open").click()
    page.wait_for_selector("#order-actions")


def wait_text(page, selector, text, timeout=15000):
    page.wait_for_function("([s, t]) => (document.querySelector(s) || {}).textContent?.includes(t)", arg=[selector, text], timeout=timeout)


def main():
    w = seed()
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=os.environ.get("E2E_BROWSER_CHANNEL") or None, headless=True)
        owner = new_page(browser)
        sign_in(owner, f"ws-owner-{RUN}@example.com")
        check("owner lands in the workspace", owner.is_visible("#dashboard"))

        # Overview from real data.
        wait_text(owner, "#workspace-section", "Active branches")
        ov = owner.text_content("#workspace-section")
        check("overview shows live organization, status and branch count",
              f"Kigali Care {RUN}" in ov and "Approved" in ov and "2: " in ov, ov[:200])

        # 1-4 Branches.
        open_view(owner, "branches")
        names = owner.locator("tr[data-branch] strong").all_text_contents()
        check("1. all branches listed", {"Kimihurura Branch", "Remera Branch"} <= set(names), names)
        f = owner.locator("#branch-form")
        f.locator("[name=name]").fill(f"Kicukiro {RUN}")
        f.locator("[name=address]").fill("KK 15 Rd")
        f.locator("[name=latitude]").fill("-1.98")
        f.locator("[name=longitude]").fill("30.104")
        f.locator("button.primary-sm").click()
        wait_text(owner, "#workspace-section", f"Kicukiro {RUN}")
        locs = call("GET", f"/organizations/{w['org']}/locations?include_inactive=true", token=w["owner"])
        new = next((loc for loc in locs if loc["name"] == f"Kicukiro {RUN}"), None)
        check("2. branch created under the same organization", new is not None and new["organization_id"] == w["org"]
              and len(call("GET", "/organizations", token=w["owner"])) == 1)
        row = owner.locator(f"tr[data-branch='{new['location_id']}']")
        row.get_by_role("button", name="Edit").click()
        f.locator("[name=address]").fill("KK 16 Avenue")
        f.locator("button.primary-sm").click()
        wait_text(owner, "#workspace-section", "KK 16 Avenue")
        upd = call("GET", f"/organizations/{w['org']}/locations/{new['location_id']}", token=w["owner"])
        check("3. branch updated", upd["address"] == "KK 16 Avenue" and upd["name"] == f"Kicukiro {RUN}")
        owner.locator(f"tr[data-branch='{new['location_id']}']").get_by_role("button", name="Deactivate").click()
        owner.wait_for_function("id => document.querySelector(`tr[data-branch='${id}'] .ws-badge`)?.textContent === 'Inactive'", arg=new["location_id"])
        upd = call("GET", f"/organizations/{w['org']}/locations/{new['location_id']}", token=w["owner"])
        check("4. branch deactivated (soft)", upd["is_active"] is False)

        # 5-7 Employees.
        open_view(owner, "employees")
        check("5. members listed", f"ws-owner-{RUN}@example.com" in owner.text_content("#workspace-section"))
        m = owner.locator("#member-form")
        for key, role in (("manager", "manager"), ("staff", "staff"), ("helper", "staff")):
            m.locator("[name=email]").fill(w[key + "_email"])
            m.locator("[name=role]").select_option(role)
            m.locator("button.primary-sm").click()
            owner.wait_for_selector(f"tr[data-member='{w[key + '_email']}']")
        members = {x["email"]: x["role"] for x in call("GET", f"/organizations/{w['org']}/members", token=w["owner"])}
        check("6. existing accounts added with their roles (no new accounts)",
              members.get(w["manager_email"]) == "manager" and members.get(w["staff_email"]) == "staff")
        hr = owner.locator(f"tr[data-member='{w['helper_email']}']")
        hr.locator("select").select_option("manager")
        hr.get_by_role("button", name="Save role").click()
        wait_text(owner, "#notice", f"{w['helper_email']} is now manager")  # the save finished
        members = {x["email"]: x["role"] for x in call("GET", f"/organizations/{w['org']}/members", token=w["owner"])}
        check("7. role updated by the owner", members.get(w["helper_email"]) == "manager")
        s, body = call("POST", f"/organizations/{w['org']}/members", {"email": f"nobody-{RUN}@example.com", "role": "staff"}, w["owner"], expect_error=True)
        m.locator("[name=email]").fill(f"nobody-{RUN}@example.com")
        m.locator("button.primary-sm").click()
        wait_text(owner, "#member-form", "Ask them to register first")
        check("   adding an unknown email shows the backend's error", s == 404)

        # 8-10 Inventory per branch.
        open_view(owner, "inventory")
        owner.select_option("#inventory-branch", str(w["kim"]))
        owner.wait_for_selector(f"tr[data-product='{w['prod_name']}']")
        kim_qty = owner.locator(f"tr[data-product='{w['prod_name']}'] input[type=number]").first.input_value()
        owner.select_option("#inventory-branch", str(w["rem"]))
        wait_text(owner, "#workspace-section", "Inventory at Remera Branch")
        rem_qty = owner.locator(f"tr[data-product='{w['prod_name']}'] input[type=number]").first.input_value()
        check("8. inventory differs per branch", (kim_qty, rem_qty) == ("120", "45"), (kim_qty, rem_qty))
        row = owner.locator(f"tr[data-product='{w['prod_name']}']")
        row.locator("input[type=number]").first.fill("50")
        row.get_by_role("button", name="Save", exact=True).click()
        # The section stays on screen (dimmed) while it saves, so the typed value is
        # already there: wait for the save to finish instead.
        wait_text(owner, "#notice", "Remera Branch: 50 in stock")
        owner.wait_for_selector("#workspace-section:not(.ws-refreshing)")
        check("9. stock updated at Remera only",
              inventory_row(w["owner"], w["org"], w["rem"], w["prod"])["quantity"] == 50
              and inventory_row(w["owner"], w["org"], w["kim"], w["prod"])["quantity"] == 120)
        owner.select_option("#inventory-branch", str(w["kim"]))
        wait_text(owner, "#workspace-section", "Inventory at Kimihurura Branch")
        row = owner.locator(f"tr[data-product='{w['prod_name']}']")
        row.locator("input[placeholder=Price]").fill("1500")
        row.get_by_role("button", name="Save price").click()
        wait_text(owner, "#workspace-section", "in stock")
        kim, rem = inventory_row(w["owner"], w["org"], w["kim"], w["prod"]), inventory_row(w["owner"], w["org"], w["rem"], w["prod"])
        check("10. owner sets a price at Kimihurura only", kim["offer"] and kim["offer"]["unit_price"] == "1500.00" and rem["offer"] is None)

        # 11 Staff cannot edit prices (UI and backend).
        staff = new_page(browser)
        sign_in(staff, w["staff_email"])
        open_view(staff, "inventory")
        staff.select_option("#inventory-branch", str(w["kim"]))
        wait_text(staff, "#workspace-section", "Inventory at Kimihurura Branch")
        srow = staff.locator(f"tr[data-product='{w['prod_name']}']")
        s, _ = call("PUT", f"/organizations/{w['org']}/locations/{w['kim']}/stock/{w['prod']}/offer", {"unit_price": "1"}, w["staff"], expect_error=True)
        check("11. staff cannot edit prices (no price controls; backend 403)",
              srow.locator("input[placeholder=Price]").count() == 0 and "1,500" in srow.text_content() and s == 403)

        # 12-14 Purchase orders as a manager.
        mgr = new_page(browser)
        sign_in(mgr, w["manager_email"])
        if mgr.is_visible("#org-switch-label"):
            mgr.select_option("#org-switch", str(w["org"]))
            wait_text(mgr, "#pharmacy-name", f"Kigali Care {RUN}")
        open_view(mgr, "orders")
        mgr.get_by_role("button", name="New purchase order").click()
        mgr.wait_for_selector("#order-branch")
        mgr.select_option("#order-branch", str(w["rem"]))
        mgr.fill("#order-search [name=q]", f"wstestamol {RUN}")
        mgr.click("#order-search button")
        mgr.wait_for_selector(".ws-results tr button")
        mgr.click(".ws-results tr button")
        mgr.wait_for_selector("input[aria-label^='Quantity of']")
        mgr.fill("input[aria-label^='Quantity of']", "20")
        mgr.get_by_role("button", name="Save draft").click()
        mgr.wait_for_selector("#order-actions")
        wait_text(mgr, "#workspace-section", "Draft")
        orders = call("GET", f"/purchase-orders?organization_id={w['org']}", token=w["owner"])["items"]
        o1 = orders[0]
        check("12. order created for the organization, receiving branch Remera",
              o1["pharmacy"]["organization_id"] == w["org"] and o1["pharmacy"]["location_name"] == "Remera Branch"
              and o1["supplier"]["organization_id"] == w["sup"] and o1["item_count"] == 1)
        check("13. saved as a draft", o1["status"] == "draft")
        mgr.get_by_role("button", name="Submit to supplier").click()
        wait_text(mgr, "#workspace-section", "Awaiting supplier")
        st = call("GET", f"/purchase-orders/{o1['purchase_order_id']}", token=w["owner"])["status"]
        check("14. manager submits the order", st == "submitted")

        # 15 Staff prepares a draft but cannot submit.
        open_view(staff, "orders")
        staff.get_by_role("button", name="New purchase order").click()
        staff.wait_for_selector("#order-branch")
        staff.fill("#order-search [name=q]", f"wstestamol {RUN}")
        staff.click("#order-search button")
        staff.wait_for_selector(".ws-results tr button")
        staff.click(".ws-results tr button")
        staff.get_by_role("button", name="Save draft").click()
        staff.wait_for_selector("#order-actions")
        staff_order = call("GET", f"/purchase-orders?organization_id={w['org']}", token=w["owner"])["items"][0]
        s, body = call("POST", f"/purchase-orders/{staff_order['purchase_order_id']}/submit", None, w["staff"], expect_error=True)
        check("15. staff draft saved; no Submit button; backend refuses (403)",
              staff_order["status"] == "draft" and staff.get_by_role("button", name="Submit to supplier").count() == 0
              and "Only owners and managers" in staff.text_content("#workspace-section") and s == 403)

        # 17 Staff cannot cancel a submitted order.
        staff.get_by_role("button", name="← Back to orders").click()
        staff.wait_for_selector(f"tr[data-order='{o1['purchase_order_id']}']")
        staff.locator(f"tr[data-order='{o1['purchase_order_id']}']").get_by_role("button", name="Open").click()
        staff.wait_for_selector("#order-actions")
        s, _ = call("POST", f"/purchase-orders/{o1['purchase_order_id']}/cancel", {"reason": "staff"}, w["staff"], expect_error=True)
        check("17. staff cannot cancel (no button; backend 403)",
              staff.get_by_role("button", name="Cancel order").count() == 0 and s == 403)

        # 16 Owner cancels with a reason.
        open_view(owner, "orders")
        owner.locator(f"tr[data-order='{o1['purchase_order_id']}']").get_by_role("button", name="Open").click()
        owner.wait_for_selector("#order-actions")
        owner.dialog_answers.append("Ordered by mistake (e2e)")
        owner.get_by_role("button", name="Cancel order").click()
        wait_text(owner, "#workspace-section", "Cancelled")
        o = call("GET", f"/purchase-orders/{o1['purchase_order_id']}", token=w["owner"])
        check("16. owner cancels with a reason; history recorded",
              o["status"] == "cancelled" and "Ordered by mistake (e2e)" in owner.text_content("#workspace-section"))

        # Counteroffers: staff see the revised terms but cannot accept; a manager can.
        body = {"pharmacy_organization_id": w["org"], "supplier_organization_id": w["sup"],
                "pharmacy_location_id": w["kim"], "items": [{"product_id": w["prod"], "quantity": 30}]}
        co = call("POST", "/purchase-orders", body, w["owner"])
        call("POST", f"/purchase-orders/{co['purchase_order_id']}/submit", {}, w["owner"])
        call("POST", f"/purchase-orders/{co['purchase_order_id']}/counter", {"items": [{
            "purchase_order_item_id": co["items"][0]["purchase_order_item_id"], "confirmed_quantity": 25,
            "confirmed_unit_price": "880.00"}], "note": "25 available"}, w["sup_owner"])
        open_order(staff, co["purchase_order_id"])
        stext = staff.text_content("#workspace-section")
        s, _ = call("POST", f"/purchase-orders/{co['purchase_order_id']}/accept-counter", {}, w["staff"], expect_error=True)
        check("counteroffer: staff see the revised terms, no Accept button, backend 403",
              "Counteroffer received" in stext and "25 at" in stext
              and staff.get_by_role("button", name="Accept counteroffer").count() == 0 and s == 403)
        open_order(mgr, co["purchase_order_id"])
        mgr.get_by_role("button", name="Accept counteroffer").click()
        wait_text(mgr, "#workspace-section", "Accepted")
        st = call("GET", f"/purchase-orders/{co['purchase_order_id']}", token=w["owner"])
        check("counteroffer: manager accepts in the UI", st["status"] == "accepted" and st["confirmed_total"] == "22000.00")

        # 18 Switching organizations.
        check("18a. selector shown for a user in two pharmacies", mgr.is_visible("#org-switch-label")
              and mgr.locator("#org-switch option").count() == 2)
        mgr.select_option("#org-switch", str(w["org2"]))
        wait_text(mgr, "#pharmacy-name", f"Second Pharmacy {RUN}")
        open_view(mgr, "branches")
        txt = mgr.text_content("#workspace-section")
        check("18b. workspace actions use the selected organization",
              f"Nyamirambo {RUN}" in txt and "Kimihurura Branch" not in txt)

        # Joining an existing pharmacy instead of registering one.
        joiner = new_page(browser)
        email = f"ws-joiner-{RUN}@example.com"
        sign_in(joiner, email)
        joiner.click("#join-existing")
        joiner.wait_for_selector("#join-wait:not([hidden])")
        joiner.click("#join-check")
        wait_text(joiner, "#join-status", "not been added")
        call("POST", f"/organizations/{w['org']}/members", {"email": email, "role": "staff"}, w["owner"])
        joiner.click("#join-check")
        joiner.wait_for_selector("#dashboard:not([hidden])")
        check("employee who registered waits, then joins without creating a pharmacy",
              joiner.text_content("#pharmacy-name") == f"Kigali Care {RUN}"
              and len(call("GET", "/organizations", token=call("POST", "/auth/login", {"email": email, "password": PW})["access_token"])) == 1)

        # Mobile layout: workspace sections usable at 375px.
        mobile = browser.new_context(viewport={"width": 375, "height": 812})
        mobile.route("**/js/config.js", lambda r: r.fulfill(content_type="application/javascript",
                                                           body=f'window.APEX_CONFIG = {{ API_BASE_URL: "{API}" }};'))
        mp = mobile.new_page()
        mp.dialog_answers, mp.errors = [], []
        sign_in(mp, f"ws-owner-{RUN}@example.com")
        open_view(mp, "inventory")
        check("mobile: no horizontal page scroll in the inventory section",
              mp.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"))

        errors = owner.errors + staff.errors + mgr.errors + joiner.errors
        check("no page errors", not errors, errors[:3])
        browser.close()

    print(f"\n{'ALL PASSED' if not failures else str(len(failures)) + ' FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
