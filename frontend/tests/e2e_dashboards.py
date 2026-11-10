"""Browser test of the pharmacy and supplier dashboards (pharmacy-dashboard.html,
supplier-dashboard.html): sign-in hand-off, branches/depots, team and
invitations, stock per branch, supplier prices, purchase orders on both sides,
organization switching, what is not connected yet, sign-out and mobile layout.

LOCAL backend and throwaway database only - never a shared environment.

  1. Backend on http://127.0.0.1:8000 with APP_ENV=development and
     EMAIL_PROVIDER=mock (invitations are then emailed to the in-memory outbox),
     and an admin (see e2e_admin.py).
  2. Frontend on http://127.0.0.1:5501 (python -m http.server 5501 --directory frontend).
  3. E2E_ADMIN_EMAIL=... E2E_ADMIN_PASSWORD=... python frontend/tests/e2e_dashboards.py

Each run creates its own accounts, organizations and catalogue entries
(suffixed with a random id) through the API, then drives the UI.
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
PW = "Dashboard-Pass-2026"
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
    """The email flow with the mock provider, when the server requires it."""
    status = call("GET", "/auth/email/status", token=token)
    if status["verified"] or not status["required"]:
        return
    call("POST", "/auth/email/send", {"next": "pharmacy"}, token)
    req = urllib.request.Request(API + "/dev/email/latest", headers={"Authorization": f"Bearer {token}"})
    link_token = json.loads(urllib.request.urlopen(req).read())["token"]
    call("POST", "/auth/email/verify", {"token": link_token})


def org_with_owner(email, name, org_name, kind, locations, approve=True, admin=None):
    token = account(email, name)
    verify_email(token)
    org = call("POST", "/organizations", {"name": org_name, "type": kind}, token)["organization_id"]
    locs = [call("POST", f"/organizations/{org}/locations", loc, token)["location_id"] for loc in locations]
    if approve:
        call("POST", f"/admin/organizations/{org}/review", {"decision": "approved"}, admin)
    return token, org, locs


def seed():
    admin = call("POST", "/auth/login", {"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})["access_token"]
    w = {"admin": admin}
    w["owner_email"] = f"db-owner-{RUN}@example.com"
    w["owner"], w["org"], (w["kim"], w["rem"]) = org_with_owner(
        w["owner_email"], "Dashboard Owner", f"Kigali Care {RUN}", "pharmacy",
        [{"name": "Kimihurura Branch", "city": "Gasabo", "latitude": -1.9536, "longitude": 30.089},
         {"name": "Remera Branch", "city": "Gasabo"}], admin=admin)
    for role in ("manager", "staff", "helper"):
        w[role + "_email"] = f"db-{role}-{RUN}@example.com"
        w[role] = account(w[role + "_email"], f"Dashboard {role.title()}")
    # A second pharmacy (other owner) where the manager is also a manager: organization switching.
    w["owner2"], w["org2"], _ = org_with_owner(f"db-owner2-{RUN}@example.com", "Second Owner", f"Second Pharmacy {RUN}",
                                               "pharmacy", [{"name": f"Nyamirambo {RUN}"}], admin=admin)
    call("POST", f"/organizations/{w['org2']}/members", {"email": w["manager_email"], "role": "manager"}, w["owner2"])
    # A pharmacy still waiting for approval.
    w["pend_email"] = f"db-pending-{RUN}@example.com"
    _, w["pend"], _ = org_with_owner(w["pend_email"], "Pending Owner", f"Pending Pharmacy {RUN}", "pharmacy",
                                     [{"name": "Kacyiru"}], approve=False)
    # Catalogue + a supplier with stock and a price.
    drug = call("POST", "/catalogue/drugs", {"name": f"Dbtestamol {RUN}", "therapeutic_class": "Analgesic"}, admin)["drug_id"]
    w["prod"] = call("POST", "/catalogue/products", {"drug_id": drug, "product_name": f"Dbtestamol {RUN} 500mg"}, admin)["product_id"]
    w["sup_email"] = f"db-supplier-{RUN}@example.com"
    w["sup_owner"], w["sup"], (w["wh"],) = org_with_owner(w["sup_email"], "Supplier Owner", f"Rwanda Distributors {RUN}",
                                                          "supplier", [{"name": "Gikondo Warehouse", "phone": "+250788111222"}], admin=admin)
    call("PUT", f"/organizations/{w['sup']}/locations/{w['wh']}/stock/{w['prod']}", {"quantity": 5000}, w["sup_owner"])
    call("PUT", f"/organizations/{w['sup']}/locations/{w['wh']}/stock/{w['prod']}/offer", {"unit_price": "900"}, w["sup_owner"])
    for loc, qty in ((w["kim"], 120), (w["rem"], 45)):
        call("PUT", f"/organizations/{w['org']}/locations/{loc}/stock/{w['prod']}", {"quantity": qty}, w["owner"])
    return w


def inventory_row(token, org, loc, product):
    items = call("GET", f"/organizations/{org}/inventory?location_id={loc}&limit=100", token=token)["items"]
    return next(i for i in items if i["product_id"] == product)


def orders_of(w, org=None):
    return call("GET", f"/purchase-orders?organization_id={org or w['org']}", token=w["owner"] if not org else w["sup_owner"])["items"]


# ------------------------------------------------------------------ UI helpers
def new_page(browser, viewport=None):
    ctx = browser.new_context(viewport=viewport or {"width": 1366, "height": 900})
    ctx.route("**/js/config.js", lambda r: r.fulfill(content_type="application/javascript",
                                                     body=f'window.APEX_CONFIG = {{ API_BASE_URL: "{API}" }};'))
    ctx.route("https://apexrx-smart.onrender.com/**", lambda r: r.abort())
    page = ctx.new_page()
    page.errors = []
    page.on("pageerror", lambda e: page.errors.append(str(e)))
    return page


def sign_in(page, email, kind="pharmacy", org=None):
    page.goto(f"{SITE}/{'pharmacies' if kind == 'pharmacy' else 'suppliers'}.html")
    for field, value in (("email", email), ("password", PW), ("confirm", PW)):
        page.fill(f"#account [name={field}]", value)
    page.click("#account button.primary")
    page.wait_for_function("location.pathname.endsWith('-dashboard.html') || !document.querySelector('#org-choice').hidden"
                           " || !document.querySelector('#join-wait')?.hidden || !document.querySelector('#details').hidden"
                           " || !document.querySelector('#review').hidden || !document.querySelector('#verify-email').hidden", timeout=20000)
    if "-dashboard.html" not in page.url and page.is_visible("#org-choice"):
        page.click(f"#org-choice-list button[data-org='{org}']" if org else "#org-choice-list button")
    if "-dashboard.html" not in page.url and page.is_visible("#review"):  # e.g. documents still to upload
        page.click("#open-workspace")
    if "-dashboard.html" not in page.url and not page.is_visible("#details") and not page.is_visible("#verify-email"):
        page.wait_for_url("**/*-dashboard.html*", timeout=20000)
    if "-dashboard.html" in page.url:
        ready(page)


def ready(page):
    page.wait_for_selector(".nav[aria-current=page]", timeout=30000)


def open_view(page, name):
    page.click(f".nav[data-v={name}]")
    page.wait_for_function("() => !document.querySelector('#view').textContent.includes('Loading')", timeout=20000)


def wait_text(page, selector, text, timeout=15000):
    page.wait_for_function("([s, t]) => (document.querySelector(s) || {}).textContent?.includes(t)", arg=[selector, text], timeout=timeout)


def confirm(page, fields=None):
    """Answer the page's own dialog (<dialog id=dlg>)."""
    page.wait_for_selector("#dlg[open]")
    for name, value in (fields or {}).items():
        page.fill(f"#dlg [name={name}]", value)
    page.click("#dlg button.solid")
    page.wait_for_selector("#dlg[open]", state="detached")


def change(page, selector, value):
    page.evaluate("document.querySelector('#toast').textContent = ''")  # wait for this save's message
    page.fill(selector, value)
    page.dispatch_event(selector, "change")


def main():
    w = seed()
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=os.environ.get("E2E_BROWSER_CHANNEL") or None, headless=True)

        # ============================================================ owner
        owner = new_page(browser)
        sign_in(owner, w["owner_email"])
        check("owner signs in on pharmacies.html and lands on the pharmacy dashboard",
              owner.url.split("?")[0].endswith("/pharmacy-dashboard.html") and owner.inner_text("#title") == "Overview")
        check("top bar: organization, verification and the signed-in user with their role",
              owner.inner_text("#me-name") == f"Kigali Care {RUN}" and "NPC verified" in owner.inner_text("#ver")
              and owner.inner_text("#dash-user") == f"{w['owner_email']} · Owner" and owner.is_hidden("#org"))
        home = owner.inner_text("#view")
        check("overview: live data, no sample strip, patient ordering and expiry shown as not live",
              f"Kigali Care {RUN}" in home and "Preview with sample data" not in home
              and "Patient ordering is coming soon" in home and "not connected yet" in owner.inner_text("#shelf-life"))

        # Branches
        open_view(owner, "set")
        names = owner.locator("tr[data-branch] strong").all_text_contents()
        check("branches: all listed", {"Kimihurura Branch", "Remera Branch"} <= set(names), names)
        owner.click("[data-a=addloc]")
        confirm(owner, {"name": f"Kicukiro {RUN}", "address": "KK 15 Rd", "latitude": "-1.98", "longitude": "30.104"})
        owner.wait_for_selector(f"tr[data-branch] >> text=Kicukiro {RUN}")
        locs = call("GET", f"/organizations/{w['org']}/locations?include_inactive=true", token=w["owner"])
        new = next((loc for loc in locs if loc["name"] == f"Kicukiro {RUN}"), None)
        check("branches: created under the same organization", new is not None and new["organization_id"] == w["org"]
              and len(call("GET", "/organizations", token=w["owner"])) == 1)
        owner.click(f"tr[data-branch='{new['location_id']}'] [data-a=editloc]")
        owner.wait_for_selector("#dlg[open]")
        check("branches: edit form is prefilled", owner.input_value("#dlg [name=address]") == "KK 15 Rd")
        confirm(owner, {"address": "KK 16 Avenue"})
        wait_text(owner, f"tr[data-branch='{new['location_id']}']", "KK 16 Avenue")
        upd = call("GET", f"/organizations/{w['org']}/locations/{new['location_id']}", token=w["owner"])
        check("branches: updated", upd["address"] == "KK 16 Avenue" and upd["name"] == f"Kicukiro {RUN}" and str(upd["latitude"]).startswith("-1.98"))
        owner.click(f"tr[data-branch='{new['location_id']}'] [data-a=offloc]")
        confirm(owner)
        wait_text(owner, f"tr[data-branch='{new['location_id']}']", "Inactive")
        upd = call("GET", f"/organizations/{w['org']}/locations/{new['location_id']}", token=w["owner"])
        check("branches: deactivated (soft), and no longer offered as a branch", upd["is_active"] is False
              and f"Kicukiro {RUN}" not in owner.inner_text("#br"))

        # Team: invitations with the owner's chosen roles; the person accepts with their own account.
        owner.wait_for_selector(f"tr[data-member='{w['owner_email']}']")
        check("team: members listed; the owner cannot change their own role",
              owner.locator(f"tr[data-member='{w['owner_email']}'] select").count() == 0)
        wait_text(owner, "#invite-submit", "Send invitation")
        for key, role in (("manager", "manager"), ("staff", "staff"), ("helper", "staff")):
            owner.fill("#invite-form [name=email]", w[key + "_email"])
            owner.select_option("#invite-form [name=role]", role)
            owner.click("#invite-submit")
            wait_text(owner, "#invite-status", f"Invitation emailed to {w[key + '_email']}")
            mail = call("GET", "/dev/email/latest-to?" + urllib.parse.urlencode({"to": w[key + "_email"]}))
            call("POST", "/invitations/accept", {"token": mail["token"]}, w[key])
        open_view(owner, "home")
        open_view(owner, "set")
        for key in ("manager", "staff", "helper"):
            owner.wait_for_selector(f"tr[data-member='{w[key + '_email']}']")
        members = {x["email"]: x["role"] for x in call("GET", f"/organizations/{w['org']}/members", token=w["owner"])}
        check("team: invited accounts joined with their roles", members.get(w["manager_email"]) == "manager"
              and members.get(w["staff_email"]) == "staff" and members.get(w["helper_email"]) == "staff")
        owner.select_option(f"tr[data-member='{w['helper_email']}'] select", "manager")
        wait_text(owner, "#toast", "Saved.")
        members = {x["email"]: x["role"] for x in call("GET", f"/organizations/{w['org']}/members", token=w["owner"])}
        check("team: role changed by the owner", members.get(w["helper_email"]) == "manager")
        owner.wait_for_selector(f"tr[data-member='{w['helper_email']}'] [data-a=tglmem]")
        owner.click(f"tr[data-member='{w['helper_email']}'] [data-a=tglmem]")
        confirm(owner)
        wait_text(owner, f"tr[data-member='{w['helper_email']}']", "Deactivated")
        active = {x["email"]: x["is_active"] for x in call("GET", f"/organizations/{w['org']}/members", token=w["owner"])}
        check("team: member deactivated", active.get(w["helper_email"]) is False)
        owner.fill("#invite-form [name=email]", f"nobody-{RUN}@example.com")
        owner.click("#invite-submit")
        wait_text(owner, "#invite-status", f"Invitation emailed to nobody-{RUN}@example.com")
        owner.wait_for_selector(f"tr[data-invite='nobody-{RUN}@example.com']")
        members = {x["email"] for x in call("GET", f"/organizations/{w['org']}/members", token=w["owner"])}
        check("team: an email without an account gets a pending invitation, not a membership",
              f"nobody-{RUN}@example.com" not in members and "Pending" in owner.inner_text(f"tr[data-invite='nobody-{RUN}@example.com']"))
        owner.click(f"tr[data-invite='nobody-{RUN}@example.com'] [data-a=revoke]")
        confirm(owner)
        wait_text(owner, f"tr[data-invite='nobody-{RUN}@example.com']", "Revoked")
        check("team: invitation revoked", True)

        # Stock per branch
        owner.select_option("#br", str(w["kim"]))
        open_view(owner, "stk")
        row = f"tr[data-product='{w['prod']}']"
        owner.wait_for_selector(row)
        kim_qty = owner.input_value(f"{row} input[data-f=qty]")
        owner.select_option("#br", str(w["rem"]))
        wait_text(owner, "#view h2", "Stock of Remera Branch")
        rem_qty = owner.input_value(f"{row} input[data-f=qty]")
        check("stock: differs per branch", (kim_qty, rem_qty) == ("120", "45"), (kim_qty, rem_qty))
        check("stock: batch number and expiry date shown as not connected (disabled)",
              owner.is_disabled("#a-b") and owner.is_disabled("#a-e") and owner.is_visible("#batches-off")
              and owner.locator(f"{row} [data-a=addbatch]").count() == 0)
        change(owner, f"{row} input[data-f=qty]", "50")
        wait_text(owner, "#toast", "Saved")
        check("stock: updated at Remera only", inventory_row(w["owner"], w["org"], w["rem"], w["prod"])["quantity"] == 50
              and inventory_row(w["owner"], w["org"], w["kim"], w["prod"])["quantity"] == 120)
        owner.select_option("#br", str(w["kim"]))
        wait_text(owner, "#view h2", "Stock of Kimihurura Branch")
        change(owner, f"{row} input[data-f=price]", "1500")
        wait_text(owner, "#toast", "Patients now see")
        kim, rem = inventory_row(w["owner"], w["org"], w["kim"], w["prod"]), inventory_row(w["owner"], w["org"], w["rem"], w["prod"])
        check("stock: owner sets a price at Kimihurura only",
              kim["offer"] and kim["offer"]["unit_price"] == "1500.00" and rem["offer"] is None, (kim["offer"], rem["offer"]))

        # ============================================================ staff
        staff = new_page(browser)
        sign_in(staff, w["staff_email"])
        check("staff land on the same pharmacy, labelled Staff", staff.inner_text("#dash-user") == f"{w['staff_email']} · Staff")
        staff.select_option("#br", str(w["kim"]))
        open_view(staff, "stk")
        staff.wait_for_selector(row)
        s, _ = call("PUT", f"/organizations/{w['org']}/locations/{w['kim']}/stock/{w['prod']}/offer", {"unit_price": "1"}, w["staff"], expect_error=True)
        check("staff: price controls disabled, quantity editable; backend refuses prices (403)",
              staff.is_disabled(f"{row} input[data-f=price]") and staff.is_enabled(f"{row} input[data-f=qty]")
              and staff.locator("#addf").count() == 0 and s == 403)
        open_view(staff, "set")
        check("staff: no team or branch management",
              staff.locator("#invite-form, [data-a=addloc], [data-a=editloc], [data-a=tglmem]").count() == 0)

        # ============================================================ orders
        mgr = new_page(browser)
        sign_in(mgr, w["manager_email"], org=w["org"])
        if mgr.inner_text("#me-name") != f"Kigali Care {RUN}":
            mgr.select_option("#org", f"pharmacy:{w['org']}")
            ready(mgr)
        mgr.select_option("#br", str(w["rem"]))
        open_view(mgr, "cmp")
        mgr.fill("#q", f"dbtestamol {RUN}")
        mgr.wait_for_selector(f"#rows >> text=Rwanda Distributors {RUN}")
        mgr.click("#rows [data-a=quote]")
        confirm(mgr, {"qty": "20"})
        wait_text(mgr, "#toast", f"Request sent to Rwanda Distributors {RUN}")
        o1 = orders_of(w)[0]
        check("compare prices: the manager's quote request is a submitted order from Remera",
              o1["status"] == "submitted" and o1["pharmacy"]["location_name"] == "Remera Branch"
              and o1["supplier"]["organization_id"] == w["sup"] and o1["item_count"] == 1)

        open_view(staff, "cmp")
        staff.fill("#q", f"dbtestamol {RUN}")
        staff.wait_for_selector(f"#rows >> text=Rwanda Distributors {RUN}")
        staff.click("#rows [data-a=quote]")
        confirm(staff, {"qty": "5"})
        wait_text(staff, "#toast", "Saved as draft")
        draft = orders_of(w)[0]
        s, _ = call("POST", f"/purchase-orders/{draft['purchase_order_id']}/submit", None, w["staff"], expect_error=True)
        check("staff: a quote request stays a draft and is never reported as sent; backend refuses submit (403)",
              draft["status"] == "draft" and "was not sent" in staff.inner_text("#toast") and s == 403)

        open_view(staff, "ord")
        staff.wait_for_selector(f"tr[data-order='{o1['purchase_order_id']}']")
        s, _ = call("POST", f"/purchase-orders/{o1['purchase_order_id']}/cancel", {"reason": "staff"}, w["staff"], expect_error=True)
        check("staff: cannot cancel a submitted order (no button; backend 403)",
              staff.locator(f"tr[data-order='{o1['purchase_order_id']}'] [data-x=cancel]").count() == 0 and s == 403)

        open_view(owner, "ord")
        owner.click(f"tr[data-order='{o1['purchase_order_id']}'] [data-x=cancel]")
        confirm(owner, {"reason": "Ordered by mistake (e2e)"})
        wait_text(owner, f"tr[data-order='{o1['purchase_order_id']}']", "Cancelled")
        o = call("GET", f"/purchase-orders/{o1['purchase_order_id']}", token=w["owner"])
        check("orders: owner cancels with a reason", o["status"] == "cancelled" and o["history"][-1]["note"] == "Ordered by mistake (e2e)", (o["status"], o["history"][-1]))
        owner.click(f"tr[data-order='{draft['purchase_order_id']}'] [data-x=delete]")
        confirm(owner)
        owner.wait_for_selector(f"tr[data-order='{draft['purchase_order_id']}']", state="detached")
        s, _ = call("GET", f"/purchase-orders/{draft['purchase_order_id']}", token=w["owner"], expect_error=True)
        check("orders: owner deletes the staff draft", s == 404)

        # Counteroffer: staff see it but cannot accept; a manager accepts.
        body = {"pharmacy_organization_id": w["org"], "supplier_organization_id": w["sup"],
                "pharmacy_location_id": w["kim"], "items": [{"product_id": w["prod"], "quantity": 30}]}
        co = call("POST", "/purchase-orders", body, w["owner"])
        call("POST", f"/purchase-orders/{co['purchase_order_id']}/submit", {}, w["owner"])
        call("POST", f"/purchase-orders/{co['purchase_order_id']}/counter", {"items": [{
            "purchase_order_item_id": co["items"][0]["purchase_order_item_id"], "confirmed_quantity": 25,
            "confirmed_unit_price": "880.00"}], "note": "25 available"}, w["sup_owner"])
        open_view(staff, "home")
        open_view(staff, "ord")
        srow = f"tr[data-order='{co['purchase_order_id']}']"
        staff.wait_for_selector(srow)
        s, _ = call("POST", f"/purchase-orders/{co['purchase_order_id']}/accept-counter", {}, w["staff"], expect_error=True)
        check("counteroffer: staff see 'Offer received' but no Accept button; backend 403",
              "Offer received" in staff.inner_text(srow) and staff.locator(f"{srow} [data-x=accept-counter]").count() == 0 and s == 403)
        open_view(mgr, "home")
        wait_text(mgr, "#view", "1 price offer waiting for your answer")  # the overview refreshes the orders
        check("overview: the manager is told an offer waits for an answer", True)
        open_view(mgr, "ord")
        mgr.click(f"{srow} [data-x=accept-counter]")
        wait_text(mgr, srow, "Accepted")
        st = call("GET", f"/purchase-orders/{co['purchase_order_id']}", token=w["owner"])
        check("counteroffer: manager accepts in the UI", st["status"] == "accepted" and st["confirmed_total"] == "22000.00")

        # ============================================================ supplier
        nb = {"pharmacy_organization_id": w["org"], "supplier_organization_id": w["sup"],
              "pharmacy_location_id": w["kim"], "items": [{"product_id": w["prod"], "quantity": 12}]}
        req = call("POST", "/purchase-orders", nb, w["owner"])
        call("POST", f"/purchase-orders/{req['purchase_order_id']}/submit", {}, w["owner"])
        sup = new_page(browser)
        sign_in(sup, w["sup_email"], kind="supplier")
        check("supplier signs in on suppliers.html and lands on the supplier dashboard",
              sup.url.split("?")[0].endswith("/supplier-dashboard.html") and sup.inner_text("#me-name") == f"Rwanda Distributors {RUN}"
              and "Licence verified" in sup.inner_text("#ver"))
        home = sup.inner_text("#view")
        check("supplier overview: pipeline, open value and requests from real orders",
              "SUPPLIER OVERVIEW" in home and "New requests" in home and "1 request waiting for your offer" in home)
        check("supplier overview: expiry tracking shown as not connected, not as zero",
              "Expiry tracking is not connected yet" in home and sup.inner_text(".chipf.c3 b") == "—")
        sup.wait_for_function("() => !document.querySelector('#toprq').textContent.includes('Loading')")
        check("supplier overview: most requested medicines from real orders", f"Dbtestamol {RUN}" in sup.inner_text("#toprq"))
        open_view(sup, "ord")
        rr = f"tr[data-order='{req['purchase_order_id']}']"
        sup.wait_for_selector(rr)
        check("supplier orders: the draft the staff made is never visible to the supplier",
              sup.locator(f"tr[data-order='{draft['purchase_order_id']}']").count() == 0)
        sup.click(f"{rr} [data-x=counter]")
        sup.wait_for_selector("#dlg[open]")
        sup.fill(f"#dlg [name=p{req['items'][0]['purchase_order_item_id']}]", "850")
        confirm(sup, {"note": "Volume price"})
        wait_text(sup, rr, "Offer sent")
        st = call("GET", f"/purchase-orders/{req['purchase_order_id']}", token=w["owner"])
        check("supplier: writes an offer (counter) in the UI", st["status"] == "countered" and st["confirmed_total"] == "10200.00")
        call("POST", f"/purchase-orders/{req['purchase_order_id']}/accept-counter", {}, w["owner"])
        open_view(sup, "home")
        open_view(sup, "ord")
        for action, status in (("start-processing", "processing"), ("dispatch", "dispatched")):
            sup.click(f"{rr} [data-x={action}]")
            sup.wait_for_function("([s, a]) => !document.querySelector(s + ' [data-x=' + a + ']')", arg=[rr, action])
        st = call("GET", f"/purchase-orders/{req['purchase_order_id']}", token=w["owner"])["status"]
        check("supplier: prepares and dispatches the order", st == "dispatched")
        open_view(owner, "home")
        open_view(owner, "ord")
        owner.click(f"{rr} [data-x=mark-delivered]")
        wait_text(owner, rr, "Delivered")
        check("pharmacy: marks the order delivered",
              call("GET", f"/purchase-orders/{req['purchase_order_id']}", token=w["owner"])["status"] == "delivered")

        open_view(sup, "stk")
        sup.wait_for_selector(row)
        check("supplier catalogue: real stock and price", sup.input_value(f"{row} input[data-f=qty]") == "5000"
              and float(sup.input_value(f"{row} input[data-f=price]")) == 900)
        change(sup, f"{row} input[data-f=price]", "950")
        wait_text(sup, "#toast", "Pharmacies now see")
        check("supplier catalogue: price saved", inventory_row(w["sup_owner"], w["sup"], w["wh"], w["prod"])["offer"]["unit_price"] == "950.00")
        open_view(sup, "prem")
        check("forecast: labelled as example data", "Example data" in sup.inner_text("#view"))

        # ============================================================ not live yet
        open_view(owner, "por")
        txt = owner.inner_text("#view")
        check("patient orders: 'coming soon', no sample orders or buttons in the live dashboard",
              "Patient ordering is coming soon" in txt and owner.locator("#view [data-a=pya]").count() == 0)

        # ============================================================ switching organizations
        check("switcher shown for a user in two pharmacies", mgr.is_visible("#org") and mgr.locator("#org option").count() == 2)
        mgr.select_option("#org", f"pharmacy:{w['org2']}")
        ready(mgr)
        wait_text(mgr, "#me-name", f"Second Pharmacy {RUN}")
        open_view(mgr, "set")
        txt = mgr.inner_text("#view")
        check("switching: the dashboard uses the selected organization only",
              f"Nyamirambo {RUN}" in txt and "Kimihurura Branch" not in txt and mgr.inner_text("#dash-user").endswith("· Manager"))
        mgr.reload()
        ready(mgr)
        check("switching: the choice is kept for this tab", mgr.inner_text("#me-name") == f"Second Pharmacy {RUN}")

        # ============================================================ pending organization
        pend = new_page(browser)
        sign_in(pend, w["pend_email"])
        check("pending pharmacy: banner, status and locked supplier prices",
              "Pending verification" in pend.inner_text("#ver") and "awaiting verification" in pend.inner_text(".banner"))
        open_view(pend, "cmp")
        wait_text(pend, "#rows", "open once your pharmacy is approved")
        check("pending pharmacy: supplier prices locked", True)

        # ============================================================ joining an existing pharmacy
        joiner = new_page(browser)
        email = f"db-joiner-{RUN}@example.com"
        sign_in(joiner, email)
        joiner.click("#join-existing")
        joiner.wait_for_selector("#join-wait:not([hidden])")
        call("POST", f"/organizations/{w['org']}/invitations", {"email": email, "role": "staff"}, w["owner"])
        link_token = call("GET", "/dev/email/latest-to?" + urllib.parse.urlencode({"to": email}))["token"]
        call("POST", "/invitations/accept", {"token": link_token}, call("POST", "/auth/login", {"email": email, "password": PW})["access_token"])
        joiner.click("#join-check")
        joiner.wait_for_url("**/pharmacy-dashboard.html*")
        ready(joiner)
        check("an employee who registered, then joined, opens that pharmacy's dashboard",
              joiner.inner_text("#me-name") == f"Kigali Care {RUN}")

        # ============================================================ sign-out and guards
        owner.click("#out")
        owner.wait_for_url("**/pharmacies.html*")
        check("sign out returns to sign-in and ends the session",
              owner.evaluate("!sessionStorage.getItem('apexrx_session')") and "#signin" in owner.url)
        owner.goto(SITE + "/pharmacy-dashboard.html")
        owner.wait_for_url("**/pharmacies.html*")
        check("a signed-out visit to a dashboard goes to sign-in", True)
        anon = new_page(browser)
        anon.goto(SITE + "/supplier-dashboard.html")
        anon.wait_for_url("**/suppliers.html*")
        check("supplier dashboard requires sign-in", True)
        s, _ = call("GET", f"/organizations/{w['org']}/inventory?location_id={w['kim']}", token=w["sup_owner"], expect_error=True)
        check("backend still refuses another organization's data", s in (403, 404))

        # ============================================================ mobile
        for kind, email in (("pharmacy", w["manager_email"]), ("supplier", w["sup_email"])):
            mp = new_page(browser, {"width": 375, "height": 812})
            sign_in(mp, email, kind=kind, org=w["org"])
            bad = []
            for v in mp.eval_on_selector_all(".nav", "b => b.map(x => x.dataset.v)"):
                open_view(mp, v)
                if mp.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1"):
                    bad.append(v)
            check(f"mobile {kind}: no horizontal page scroll in any section", not bad, bad)
            mp.errors and failures.append("mobile errors")

        errors = owner.errors + staff.errors + mgr.errors + sup.errors + pend.errors + joiner.errors
        check("no page errors", not errors, errors[:3])
        browser.close()

    print(f"\n{'ALL PASSED' if not failures else str(len(failures)) + ' FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
