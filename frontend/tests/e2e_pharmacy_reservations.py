"""Browser test of the pharmacy Reservations workspace (Phase 4) in the pharmacy
dashboard: access for each kind of account, groups and counts, server-side
filters, sorting and pages, the detail (deadlines, patient phone while open,
stock and shortfall), confirm / decline / cancel / collect, the owner-or-manager
physical-count override and its stale-count refusal, duplicate submissions, the
reservation settings (the branch minimum kept for walk-in customers and each
medicine's stock breakdown), notifications, suspension (read only), the three
languages, a 390px phone and basic accessibility.

LOCAL backend and throwaway database only - never a shared environment.

  1. Backend on http://127.0.0.1:8000 (APP_ENV=development, EMAIL_PROVIDER=mock,
     migrated to head) and an admin account (see e2e_admin.py).
  2. Frontend on http://127.0.0.1:5501 (python -m http.server 5501 --directory frontend).
  3. E2E_ADMIN_EMAIL=... E2E_ADMIN_PASSWORD=... python frontend/tests/e2e_pharmacy_reservations.py

Everything is created through the API as the application does it (the admin
classifies medicines, the owner stocks them and adds members, patients reserve). Nothing is written to the database directly. One case cannot
happen live in a test - a 24-hour deadline passing - so it is replayed by
answering one request in the browser with the API's documented 409 response.
"""

import json
import os
import re
import sys
import uuid

from playwright.sync_api import sync_playwright

THRESHOLD_TEXT = ('Set the minimum quantity of each medicine you want to retain for walk-in customers. Medicines will a'
                  'utomatically become unavailable for public reservations when their remaining unallocated stock reaches this threshold.')

sys.path.insert(0, os.path.dirname(__file__))
import e2e_dashboards as D  # noqa: E402  (shared API and UI helpers)

RUN, call, check, failures = D.RUN, D.call, D.check, D.failures
PHONE = "+250788444555"
REFERENCE = re.compile(r"RX-[A-Z0-9]{10}")
INTERNAL = {"patient_user_id", "deduction_adjustment_id", "correction_adjustment_id", "collected_xid",
            "status_changed_by", "responded_by", "client_request_id"}


def settings(admin, product):
    return call("GET", f"/catalogue/products/{product}/reservation-settings", token=admin)


def reserve(token, admin, loc, product, quantity):
    return call("POST", "/reservations", {
        "location_id": loc, "product_id": product, "quantity": quantity,
        "unit_version": settings(admin, product)["unit_version"],
        "client_request_id": str(uuid.uuid4()), "contact_phone": PHONE}, token)["reference"]


def seed():
    admin = call("POST", "/auth/login", {"email": D.ADMIN_EMAIL, "password": D.ADMIN_PASSWORD})["access_token"]
    w = {"admin": admin}
    drug = call("POST", "/catalogue/drugs", {"name": f"Reservamol {RUN}", "therapeutic_class": "Analgesic"}, admin)["drug_id"]
    for key, strength, enable in (("main", "500mg", True), ("two", "250mg", True), ("three", "1g", True),
                                  ("setup", "125mg", True), ("stale", "750mg", True), ("off", "50mg", False)):
        pid = call("POST", "/catalogue/products", {"drug_id": drug, "product_name": f"Reservamol {RUN} {strength}",
                                                   "strength": strength, "pack_size": "B/20"}, admin)["product_id"]
        if enable:  # classified: reservable wherever a branch lists it with stock above its minimum
            call("PATCH", f"/catalogue/products/{pid}/reservation-settings",
                 {"dispensing_class": "non_prescription", "stock_unit": "pack", "unit_label": "box",
                  "max_reservation_quantity": 5}, admin)
        w[key] = pid
    w["owner_email"] = f"pr-owner-{RUN}@example.com"
    w["owner"], w["org"], (w["b1"], w["b2"]) = D.org_with_owner(
        w["owner_email"], f"Owner Habimana {RUN}", f"Kimihurura Pharmacy {RUN}", "pharmacy",
        [{"name": "Kimihurura Branch"}, {"name": "Remera Branch"}], admin=admin)
    for role in ("manager", "staff"):
        email = f"pr-{role}-{RUN}@example.com"
        D.account(email, f"{role.title()} {RUN}")
        call("POST", f"/organizations/{w['org']}/members", {"email": email, "role": role}, w["owner"])
        w[role + "_email"] = email
    w["other_email"] = f"pr-other-{RUN}@example.com"
    w["other"], w["other_org"], _ = D.org_with_owner(w["other_email"], "Other Owner", f"Other Pharmacy {RUN}", "pharmacy",
                                                     [{"name": "Other Branch"}], admin=admin)
    w["sup_email"] = f"pr-sup-{RUN}@example.com"
    D.org_with_owner(w["sup_email"], "Supplier Owner", f"Supply Co {RUN}", "supplier", [{"name": "Depot"}], admin=admin)

    base = lambda loc, p: f"/organizations/{w['org']}/locations/{loc}/stock/{p}"  # noqa: E731
    for loc, products in ((w["b1"], ("main", "two", "three", "setup", "stale", "off")), (w["b2"], ("main",))):
        for key in products:
            call("PUT", base(loc, w[key]), {"quantity": 10}, w["owner"])
            call("PUT", base(loc, w[key]) + "/offer", {"unit_price": "1200"}, w["owner"])

    patients = {}
    for n in range(1, 6):
        email = f"pr-patient{n}-{RUN}@example.com"
        patients[n] = D.account(email, f"Patient {n} {RUN}")
    w["patients"] = patients
    p = patients
    # Closed reservations for paging (22 cancelled by their patients).
    for n in (4, 5):
        for _ in range(11):
            ref = reserve(p[n], admin, w["b1"], w["main"], 1)
            call("POST", f"/reservations/{ref}/cancel", {}, p[n])
    w["r_confirm"] = reserve(p[1], admin, w["b1"], w["main"], 2)
    w["r_short"] = reserve(p[2], admin, w["b1"], w["main"], 5)
    w["r_decline"] = reserve(p[1], admin, w["b1"], w["two"], 3)
    w["r_cancel"] = reserve(p[2], admin, w["b1"], w["two"], 2)
    w["r_collect"] = reserve(p[3], admin, w["b1"], w["three"], 4)
    w["r_override"] = reserve(p[3], admin, w["b2"], w["main"], 3)
    org_path = f"/organizations/{w['org']}/reservations"
    for key in ("r_cancel", "r_collect", "r_override"):
        call("POST", f"{org_path}/{w[key]}/confirm", None, w["owner"])
    return w


def stock_of(w, loc, product):
    items = call("GET", f"/organizations/{w['org']}/inventory?location_id={loc}&limit=100", token=w["owner"])["items"]
    return next(i for i in items if i["product_id"] == product)


def set_stock(w, loc, product, qty):
    call("PUT", f"/organizations/{w['org']}/locations/{loc}/stock/{product}", {"quantity": qty, "allow_below_reserved": True}, w["owner"])


def page_for(browser, email, viewport=None, kind="pharmacy"):
    page = D.new_page(browser, viewport)
    page.bodies = []

    def on_response(resp):
        if resp.url.startswith(D.API) and "/reservations" in resp.url and "json" in (resp.headers.get("content-type") or ""):
            try:
                page.bodies.append(resp.json())
            except Exception:  # noqa: BLE001
                pass
    page.on("response", on_response)
    if email:
        D.sign_in(page, email, kind)
    return page


def keys(value):
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in keys(v)}
    return set()


def workspace(page):
    D.open_view(page, "res")
    page.wait_for_selector("#rv-list .rv-card, #rv-list .empty, #rv-list .err")


def listed(page):
    page.wait_for_function("() => { const l = document.querySelector('#rv-list'); return l && !l.hasAttribute('aria-busy'); }")
    return page.locator("#rv-list .rv-card .rv-ref").all_inner_texts()


def group(page, status):
    page.click(f"#rv-groups [data-s='{status}']")
    page.wait_for_timeout(100)
    return listed(page)


def open_ref(page, ref):
    """Find one reservation with the reference filter and open it."""
    if not page.locator("#rv-filters").count():
        if page.locator("[data-a=rvback]").count():
            page.click("[data-a=rvback]")
        page.wait_for_selector("#rv-filters")
    page.click("#rv-groups [data-s='']")
    page.select_option("#rv-loc", "")
    page.fill("#rv-ref", ref)
    page.click("#rv-filters button[type=submit]")
    page.wait_for_selector(f"#rv-list button.rv-ref[data-r='{ref}']")
    page.click(f"#rv-list button.rv-ref[data-r='{ref}']")
    page.wait_for_selector("#rv-title")


def detail_text(page):
    return page.inner_text("#rv-detail")


def act(page, action, reason=None, sure=True, submit=True, fill=None):
    page.click(f"#rv-detail [data-a=rvact][data-x={action}]")
    page.wait_for_selector("#dlg[open] #dlgf")
    if reason is not None:
        page.fill("#dlgf textarea[name=reason]", reason)
    for name, value in (fill or {}).items():
        page.fill(f"#dlgf [name={name}]", value)
    if sure and page.locator("#dlgf input[name=sure]").count():
        page.check("#dlgf input[name=sure]")
    if submit:
        page.click("#dlgf button.solid")


def wait_detail(page, text, timeout=15000):
    page.wait_for_function("t => (document.querySelector('#rv-detail') || {}).textContent?.includes(t)", arg=text, timeout=timeout)


def unlabeled(page, root="#view"):
    return page.evaluate("""root => [...document.querySelectorAll(root + ' input, ' + root + ' select, ' + root + ' textarea, ' + root + ' button')]
      .filter(el => el.offsetParent !== null && el.type !== 'hidden')
      .filter(el => el.matches('button') ? !(el.textContent.trim() || el.getAttribute('aria-label'))
                                         : !((el.labels && el.labels.length) || el.getAttribute('aria-label')))
      .map(el => el.id || el.outerHTML.slice(0, 80))""", root)


def wide(page):
    return page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1")


def main():
    w = seed()
    org_path = f"/organizations/{w['org']}/reservations"
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel=os.environ.get("E2E_BROWSER_CHANNEL") or None, headless=True)
        errors = []

        # ========================================================= access
        anon = page_for(browser, None)
        anon.goto(f"{D.SITE}/pharmacy-dashboard.html")
        anon.wait_for_url("**/pharmacy-sign-in.html*", timeout=15000)
        check("access: signed out, the dashboard sends you to the pharmacy sign-in page", "pharmacy-sign-in.html" in anon.url)
        anon.context.close()

        patient = page_for(browser, f"pr-patient1-{RUN}@example.com")
        patient.goto(f"{D.SITE}/pharmacy-dashboard.html")
        patient.wait_for_url(re.compile(r".*pharmacies\.html.*"), timeout=15000)
        status, _ = call("GET", org_path, token=w["patients"][1], expect_error=True)
        check("access: a patient never reaches the workspace (redirected; the API says 404)",
              "pharmacy-dashboard" not in patient.url and status == 404 and not patient.bodies)
        patient.context.close()

        sup = page_for(browser, w["sup_email"], kind="supplier")
        sup.goto(f"{D.SITE}/pharmacy-dashboard.html")
        sup.wait_for_url("**/supplier-dashboard.html*", timeout=15000)
        D.ready(sup)
        check("access: a supplier is sent to its own dashboard, which has no Reservations",
              sup.locator(".nav[data-v=res]").count() == 0)
        sup.context.close()

        other = page_for(browser, w["other_email"])
        workspace(other)
        check("access: another pharmacy sees only its own (empty) reservations", other.locator("#rv-list .rv-card").count() == 0)
        status_a, _ = call("GET", f"{org_path}/{w['r_confirm']}", token=w["other"], expect_error=True)
        status_b, _ = call("GET", f"/organizations/{w['other_org']}/reservations/{w['r_confirm']}", token=w["other"], expect_error=True)
        check("access: another pharmacy cannot read this pharmacy's reservation by reference", status_a == 404 and status_b == 404)
        other.context.close()

        # ========================================================= overview, groups, filters (staff)
        staff = page_for(browser, w["staff_email"])
        staff.on("pageerror", lambda e: errors.append(str(e)))
        badge = staff.locator("#b-res")
        check("nav: Reservations for every active role, with the number of new requests",
              staff.locator(".nav[data-v=res]").count() == 1 and badge.is_visible() and badge.inner_text() == "3", badge.inner_text())
        workspace(staff)
        counts = {s: staff.inner_text(f"#rv-groups [data-s='{s}'] .rv-n") for s in
                  ("requested", "confirmed", "collected", "declined", "cancelled", "expired")}
        check("groups: counts per status from the API", counts == {"requested": "3", "confirmed": "3", "collected": "0",
                                                                    "declined": "0", "cancelled": "22", "expired": "0"}, counts)
        new = listed(staff)
        check("groups: New requests is the default and lists only requests",
              set(new) == {w["r_confirm"], w["r_short"], w["r_decline"]})
        first = staff.locator("#rv-list .rv-card").first.inner_text()
        check("list: reference, patient, medicine, quantity and unit, branch, time, status and response deadline",
              "Patient" in first and "Reservamol" in first and "× box (B/20)" in first and "Kimihurura Branch" in first
              and "Respond by" in first and "New request" in first, first)
        check("list: a new request is not presented as a commitment",
              "no stock" in staff.inner_text(".rv-intro").lower() and "Confirmed" not in first)
        conf = group(staff, "confirmed")
        check("groups: Awaiting collection shows the collection deadline",
              set(conf) == {w["r_cancel"], w["r_collect"], w["r_override"]}
              and "Collect by" in staff.locator("#rv-list .rv-card").first.inner_text())
        check("groups: an empty group says so", group(staff, "expired") == [] and "No reservations with this status" in staff.inner_text("#rv-list"))
        cancelled = group(staff, "cancelled")
        check("pages: 20 per page with the page count", len(cancelled) == 20 and "Page 1 of 2" in staff.inner_text(".rv-pager"))
        staff.click(".rv-pager [data-d='1']")
        check("pages: the second page has the rest", len(listed(staff)) == 2)
        staff.click("#rv-groups [data-s='']")
        staff.select_option("#rv-loc", str(w["b2"])); staff.click("#rv-filters button[type=submit]")
        got = listed(staff)
        check("filter: branch (server side)", got == [w["r_override"]], got)
        staff.select_option("#rv-loc", ""); staff.fill("#rv-ref", w["r_decline"].lower()); staff.click("#rv-filters button[type=submit]")
        got = listed(staff)
        check("filter: reference (case-insensitive)", got == [w["r_decline"]], got)
        staff.fill("#rv-ref", "nope"); staff.click("#rv-filters button[type=submit]")
        check("filter: an invalid reference is explained", "RX-" in staff.inner_text("#rv-ferr"))
        staff.fill("#rv-ref", "")
        staff.fill("#rv-from", "2099-01-01"); staff.click("#rv-filters button[type=submit]")
        check("filter: a future date range is empty", listed(staff) == [] and "match these filters" in staff.inner_text("#rv-list"))
        staff.fill("#rv-from", "2026-12-31"); staff.fill("#rv-to", "2026-01-01"); staff.click("#rv-filters button[type=submit]")
        check("filter: a start after the end is refused", "after the end" in staff.inner_text("#rv-ferr"))
        staff.click("[data-a=rvreset]"); staff.wait_for_selector("#rv-list .rv-card")
        check("filter: reset returns to New requests with no filters",
              staff.input_value("#rv-from") == "" and staff.locator("#rv-groups [data-s=requested].on").count() == 1)
        staff.click("#rv-groups [data-s='']")
        listed(staff)
        staff.select_option("#rv-sort", "newest"); staff.click("#rv-filters button[type=submit]")
        newest = listed(staff)[0]
        staff.select_option("#rv-sort", "deadline"); staff.click("#rv-filters button[type=submit]")
        urgent = staff.locator("#rv-list .rv-card").first.inner_text()
        check("sort: newest first, or most urgent (open ones first, by deadline)",
              newest == w["r_override"] and ("New request" in urgent or "awaiting collection" in urgent), (newest, urgent))
        staff.select_option("#rv-loc", str(w["b1"])); staff.click("#rv-filters button[type=submit]"); listed(staff)
        staff.click(f"#rv-list button.rv-ref[data-r='{w['r_decline']}']"); staff.wait_for_selector("#rv-title")
        staff.click("[data-a=rvback]"); staff.wait_for_selector("#rv-filters")
        check("filters are kept between the list and a reservation", staff.input_value("#rv-loc") == str(w["b1"]))

        # ========================================================= detail and confirm (staff)
        open_ref(staff, w["r_confirm"])
        txt = detail_text(staff)
        check("detail: a request, its response deadline, the patient's phone while open, stock figures",
              "Patient request: no stock is committed yet" in txt and "Response deadline" in txt and PHONE in txt
              and "Recorded stock" in txt and "Unallocated" in txt and "Collection deadline" not in txt, txt[:400])
        check("detail: staff may confirm or decline, not cancel or override",
              staff.locator("#rv-detail [data-x=confirm]").count() == 1 and staff.locator("#rv-detail [data-x=decline]").count() == 1
              and staff.locator("#rv-detail [data-x=cancel]").count() == 0 and staff.locator("#rv-detail [data-x=override]").count() == 0)
        act(staff, "confirm", submit=False)
        dlg = staff.inner_text("#dlgf")
        check("confirm: the dialog shows medicine, quantity, branch, stock, availability, deadline and the commitment",
              "2 × box (B/20)" in dlg and "Kimihurura Branch" in dlg and "Recorded stock" in dlg and "Unallocated" in dlg
              and "Respond by" in dlg and "full 2 × box" in dlg)
        staff.uncheck("#dlgf input[name=sure]"); staff.click("#dlgf button.solid")
        check("confirm: nothing happens without the explicit check", staff.locator("#dlg[open]").count() == 1)
        posts = []
        staff.on("request", lambda r: posts.append(r.url) if r.method == "POST" and "/reservations/" in r.url else None)
        staff.check("#dlgf input[name=sure]")
        staff.locator("#dlgf button.solid").dblclick()
        wait_detail(staff, "Confirmed commitment")
        check("confirm: one request; the reservation is now a confirmed commitment with a collection deadline",
              len([u for u in posts if u.endswith("/confirm")]) == 1 and "Collection deadline" in detail_text(staff)
              and call("GET", f"{org_path}/{w['r_confirm']}", token=w["owner"])["status"] == "confirmed")
        st = call("GET", f"{org_path}/{w['r_confirm']}", token=w["owner"])["stock"]
        txt = detail_text(staff).replace("\t", "\n")
        check("confirm: stock figures refreshed from the API (held by open requests and confirmed reservations)",
              f"Held by reservations\n{st['allocated_quantity']}" in txt and f"Unallocated\n{st['available_to_reserve']}" in txt
              and f"Reservable now\n{st['reservable_quantity']}" in txt, (st, txt[:400]))

        # Conflict: the stock fell after the page was opened.
        open_ref(staff, w["r_short"])
        set_stock(w, w["b1"], w["main"], 6)  # 6 recorded - 2 held = 4 < 5 requested
        act(staff, "confirm", submit=False)
        warned = "will be refused" not in staff.inner_text("#dlgf")  # the dialog shows what the page loaded (10)
        staff.click("#dlgf button.solid")
        wait_detail(staff, "Not confirmed")
        txt = detail_text(staff)
        check("confirm conflict: the API refuses, the reason and current availability are shown, figures refreshed",
              "covers only 4" in txt and "New request" in txt and "Recorded stock\n6" in txt.replace("\t", "\n"), txt[:500])
        act(staff, "confirm", submit=False)
        check("confirm: the dialog warns when unreserved stock is too low", warned and "will be refused" in staff.inner_text("#dlgf"))
        staff.click("#dlg-x")

        # Deadline passed (replayed: the API's 409 for a request past its response deadline).
        staff.route(re.compile(r".*/reservations/" + w["r_short"] + "/confirm$"), lambda r: r.fulfill(
            status=409, content_type="application/json",
            body=json.dumps({"detail": "This reservation has expired.", "code": "expired", "status": "expired"})))
        act(staff, "confirm")
        wait_detail(staff, "has expired")
        check("confirm after the deadline: explained, nothing confirmed", call("GET", f"{org_path}/{w['r_short']}", token=w["owner"])["status"] == "requested")
        staff.unroute(re.compile(r".*/reservations/" + w["r_short"] + "/confirm$"))
        set_stock(w, w["b1"], w["main"], 10)

        # ========================================================= decline (staff)
        open_ref(staff, w["r_decline"])
        act(staff, "decline", reason="")
        check("decline: a reason is required", staff.locator("#dlg[open]").count() == 1)
        check("decline: the dialog explains it closes the request", "closes the request" in staff.inner_text("#dlgf"))
        staff.fill("#dlgf textarea[name=reason]", "Out of this brand today")
        staff.click("#dlgf button.solid")
        wait_detail(staff, "Closed: nothing more")
        txt = detail_text(staff)
        check("decline: closed, reason shown, the patient's phone is now hidden",
              "Declined" in txt and "Out of this brand today" in txt and PHONE not in txt and "Hidden: the reservation is closed" in txt)

        # ========================================================= collect (staff) and duplicates
        before = stock_of(w, w["b1"], w["three"])["quantity"]
        open_ref(staff, w["r_collect"])
        check("detail: a confirmed commitment shows its collection deadline, not the response deadline",
              "Confirmed commitment: 4 × box (B/20)" in detail_text(staff) and "Collection deadline" in detail_text(staff)
              and "Response deadline" not in detail_text(staff))
        posts.clear()
        act(staff, "collect", submit=False)
        dlg = staff.inner_text("#dlgf")
        check("collect: full quantity only, the reference must be typed (not shown), stock reduced in the same step",
              "Partial collection is not possible" in dlg and w["r_collect"] not in dlg and "reduced by 4" in dlg
              and staff.locator("#dlgf input[name=reference][required]").count() == 1
              and staff.locator("#dlgf input[type=number]").count() == 0)
        staff.fill("#dlgf [name=reference]", w["r_collect"].lower())
        staff.locator("#dlgf button.solid").dblclick()
        wait_detail(staff, "Collection")
        wait_detail(staff, "Quantity handed over")
        after = stock_of(w, w["b1"], w["three"])["quantity"]
        check("collect: one request; collected; stock reduced by exactly 4; status and stock refreshed",
              len([u for u in posts if u.endswith("/collect")]) == 1 and before - after == 4
              and "Collected" in detail_text(staff) and f"{before} → {after}" in detail_text(staff), (before, after))

        # ========================================================= insufficient record; override rules
        set_stock(w, w["b2"], w["main"], 1)  # 3 confirmed, 1 recorded: shortfall 2
        open_ref(staff, w["r_override"])
        txt = detail_text(staff)
        check("shortfall: warned with medicine and branch; commitments kept; how to resolve; link to My stock",
              "Stock shortfall" in txt and "Remera Branch" in txt and "nothing is cancelled automatically" in txt
              and staff.locator("[data-a=rvstock]").count() == 1)
        act(staff, "collect", fill={"reference": w["r_override"]})
        wait_detail(staff, "Not collected")
        txt = detail_text(staff)
        check("collect: an insufficient record is refused, explained, the reservation stays confirmed",
              "recorded stock (1) is lower than the reserved quantity (3)" in txt and "Confirmed commitment" in txt
              and "ask an owner or manager" in txt and stock_of(w, w["b2"], w["main"])["quantity"] == 1)
        check("override: not offered to staff", staff.locator("#rv-detail [data-x=override]").count() == 0)
        staff.click("[data-a=rvstock]")
        staff.wait_for_selector("#sf")
        check("shortfall: the link opens My stock at that branch, filtered to the medicine",
              staff.input_value("#sf").startswith("Reservamol") and staff.input_value("#br") == str(w["b2"]))
        staff.context.close()

        manager = page_for(browser, w["manager_email"])
        manager.on("pageerror", lambda e: errors.append(str(e)))
        workspace(manager)
        open_ref(manager, w["r_override"])
        check("override: offered to managers, labelled as an exception",
              "Physical-count override (exception)" in detail_text(manager))
        act(manager, "override", submit=False)
        dlg = manager.inner_text("#dlgf")
        check("override: explains the exception, shows the recorded quantity seen, warns about a changed record",
              "Exception" in dlg and "Recorded stock you are correcting: 1" in dlg and "refused and you must count again" in dlg)
        manager.fill("#dlgf [name=reference]", w["r_override"])
        manager.fill("#dlgf [name=count]", "2")
        manager.fill("#dlgf textarea[name=reason]", "Counted twice on the shelf")
        manager.check("#dlgf input[name=sure]")
        manager.click("#dlgf button.solid")
        check("override: a count below the reserved quantity is refused in the form (no partial collection)",
              manager.locator("#dlg[open]").count() == 1)
        manager.fill("#dlgf [name=count]", "5")
        set_stock(w, w["b2"], w["main"], 2)  # the record changes while the manager is counting
        manager.click("#dlgf button.solid")
        wait_detail(manager, "changed since you looked")
        check("override: a stale count is refused; nothing collected", call("GET", f"{org_path}/{w['r_override']}", token=w["owner"])["status"] == "confirmed")
        act(manager, "override", fill={"count": "5", "reference": w["r_override"]}, reason="Counted twice on the shelf")
        wait_detail(manager, "Quantity handed over")
        txt = detail_text(manager)
        check("override: recorded with who, the count, what the record showed and why; stock 5 - 3 = 2",
              "Collected" in txt and "counted 5, the record showed 2" in txt and "Counted twice on the shelf" in txt
              and stock_of(w, w["b2"], w["main"])["quantity"] == 2)

        # ========================================================= cancel (manager), privacy
        open_ref(manager, w["r_cancel"])
        act(manager, "cancel", submit=False)
        check("cancel: explains it breaks a commitment and needs a reason", "breaks a commitment" in manager.inner_text("#dlgf"))
        manager.fill("#dlgf textarea[name=reason]", "Batch recalled by supplier"); manager.check("#dlgf input[name=sure]")
        manager.click("#dlgf button.solid")
        wait_detail(manager, "Closed: nothing more")
        check("cancel: cancelled with the reason; phone hidden",
              "Batch recalled by supplier" in detail_text(manager) and PHONE not in detail_text(manager))
        leaked = [k for b in manager.bodies for k in keys(b) & INTERNAL]
        check("privacy: no internal ids (adjustments, transactions, user ids) in any reservation response", not leaked, leaked[:5])
        check("privacy: the patient's email never appears", "pr-patient" not in manager.content())

        # ========================================================= reservation settings
        manager.click("[data-a=rvback]"); manager.wait_for_selector("#rv-filters")
        manager.click("[data-a=rvmode][data-m=setup]")
        manager.wait_for_selector("#rv-meds table")
        manager.select_option("#rv-setup-loc", str(w["b1"]))
        manager.wait_for_function("() => document.querySelectorAll('#rv-meds tbody tr').length >= 6")
        check("settings: the branch minimum is explained in the words agreed",
              THRESHOLD_TEXT in manager.inner_text("#rv-setup"), manager.inner_text(".rv-min"))
        check("settings: the minimum starts at 0", manager.input_value("#rv-min") == "0")

        def med_row(page, strength):
            return page.locator("#rv-meds tbody tr", has_text=f"Reservamol {RUN} {strength}").inner_text()

        row = med_row(manager, "125mg")
        check("settings: each medicine shows recorded, held, unallocated, kept back and reservable stock",
              re.search(r"\b10\s+0\s+10\s+0\s+10\b", row) is not None and "Reservable" in row and "Up to 5" in row, row)
        off = med_row(manager, "50mg")
        check("settings: a medicine ApexRX has not classified says so", "Not reservable" in off and "not classified" in off, off)

        manager.fill("#rv-min", "10"); manager.click("#rv-min-f button")
        manager.wait_for_function("() => document.querySelector('#toast').textContent.includes('keeps 10')")
        manager.wait_for_function(f"() => [...document.querySelectorAll('#rv-meds tbody tr')].some(r => r.textContent.includes('{RUN} 125mg') && r.textContent.includes('Not reservable'))")
        row = med_row(manager, "125mg")
        check("settings: at the minimum the medicine is no longer reservable, and the reason is given",
              "minimum kept for walk-in customers" in row, row)
        opts = call("GET", f"/reservations/options?location_id={w['b1']}&product_id={w['setup']}", token=w["patients"][1])
        check("settings: patients see it as not reservable (no stock figures)",
              opts["reservable"] is False and opts["reason"] == "no_reservable_stock" and "quantity" not in opts, opts)
        other_branch = call("GET", f"/organizations/{w['org']}/locations", token=w["owner"])
        check("settings: the minimum is per branch",
              {loc["location_id"]: loc["reservation_min_stock"] for loc in other_branch}.get(w["b2"]) == 0)
        manager.fill("#rv-min", "-1"); manager.click("#rv-min-f button")
        check("settings: a negative minimum is refused in the page",
              call("GET", f"/organizations/{w['org']}/locations", token=w["owner"])[0]["reservation_min_stock"] in (0, 10))
        manager.fill("#rv-min", "0"); manager.click("#rv-min-f button")
        manager.wait_for_function("() => document.querySelector('#toast').textContent.includes('keeps 0')")
        manager.wait_for_function(f"() => [...document.querySelectorAll('#rv-meds tbody tr')].some(r => r.textContent.includes('{RUN} 125mg') && r.textContent.includes('Up to 5'))")
        check("settings: back at 0, the medicine is reservable again", True)

        manager.locator("#rv-meds tbody tr", has_text=f"Reservamol {RUN} 750mg").locator("[data-a=rvsettings]").click()
        manager.wait_for_selector("#dlg[open]")
        dlg = manager.inner_text("#dlgf")
        check("settings: catalogue settings are read only for pharmacies",
              "Only ApexRX administrators" in dlg and manager.locator("#dlgf input:not([type=hidden]), #dlgf select, #dlgf textarea").count() == 0)
        manager.click("#dlg-x")
        status, _ = call("PATCH", f"/catalogue/products/{w['main']}/reservation-settings", {"max_reservation_quantity": 1},
                         w["owner"], expect_error=True)
        check("settings: the API refuses a pharmacy owner editing shared settings", status == 403)
        check("accessibility: every visible control in the workspace has a name", not unlabeled(manager), unlabeled(manager))
        manager.context.close()

        staff = page_for(browser, w["staff_email"])
        workspace(staff)
        staff.click("[data-a=rvmode][data-m=setup]"); staff.wait_for_selector("#rv-meds table")
        check("settings: staff see the minimum and the breakdown but cannot change the minimum",
              staff.locator("#rv-min").count() == 0 and "Owners and managers change this." in staff.inner_text("#rv-setup"))
        staff_token = call("POST", "/auth/login", {"email": w["staff_email"], "password": D.PW})["access_token"]
        status, _ = call("PATCH", f"/organizations/{w['org']}/locations/{w['b1']}", {"reservation_min_stock": 3},
                         staff_token, expect_error=True)
        check("settings: the API refuses a staff member changing the minimum", status == 403)
        staff.context.close()

        # ========================================================= notifications, languages, phone
        owner = page_for(browser, w["owner_email"], viewport={"width": 390, "height": 844})
        owner.on("pageerror", lambda e: errors.append(str(e)))
        owner.click("#bell"); owner.wait_for_selector("#npanel:not([hidden])")
        notes = owner.locator("#npanel .np-i").all_inner_texts()
        reqs = [n for n in notes if "New reservation request" in n]
        refs = [REFERENCE.search(n).group(0) for n in reqs if REFERENCE.search(n)]
        check("notifications: reservation events with their reference, once each, no patient details",
              reqs and len(refs) == len(reqs) and len(set(refs)) == len(refs)
              and any(w["r_short"] in n for n in reqs) and not any(PHONE in n or "Patient" in n for n in notes), notes[:3])
        target = owner.locator("#npanel .np-i", has_text=w["r_short"])
        target.click()
        owner.wait_for_selector("#rv-title")
        check("notifications: opening one shows that reservation", owner.inner_text("#rv-title") == w["r_short"])
        check("390px: the reservation detail has no sideways scrolling", not wide(owner))
        act(owner, "confirm", submit=False)
        check("390px: the confirmation dialog fits", not wide(owner) and owner.locator("#dlgf").bounding_box()["width"] <= 390)
        owner.click("#dlg-x")
        owner.click("[data-a=rvback]"); owner.wait_for_selector("#rv-filters")
        check("390px: the list and filters have no sideways scrolling", not wide(owner))
        for lang, nav, chip, word in (("fr", "Réservations", "Expirée", "Demande d’un patient"),
                                      ("rw", "Ibyabikishijwe", "Ibisabwa bishya", "Ubusabe bw’umurwayi")):
            owner.select_option("#lang", lang)
            owner.wait_for_function("l => document.documentElement.lang === l", arg=lang)
            D.ready(owner)
            workspace(owner)
            nav_text, chips = owner.inner_text(".nav[data-v=res]"), owner.inner_text("#rv-groups")
            open_ref(owner, w["r_short"])
            check(f"{lang}: navigation, groups and the detail are translated",
                  nav_text.startswith(nav) and chip in chips and word in detail_text(owner) and "Patient request" not in detail_text(owner),
                  (nav_text, chips[:80], detail_text(owner)[:160]))
            check(f"{lang}: no sideways scrolling at 390px", not wide(owner))
        owner.select_option("#lang", "en"); owner.wait_for_function("() => document.documentElement.lang === 'en'")
        owner.context.close()

        # ========================================================= suspension: read only
        call("POST", f"/admin/organizations/{w['org']}/review", {"decision": "suspended", "notes": "Licence check"}, w["admin"])
        owner = page_for(browser, w["owner_email"])
        workspace(owner)
        owner.click("#rv-groups [data-s='']")
        rows = listed(owner)
        open_ref(owner, w["r_short"])
        check("suspended: reservations can still be read; open ones were closed by the suspension; no actions",
              len(rows) > 0 and "read reservations but not act" in owner.inner_text("#view")
              and owner.locator("#rv-detail [data-a=rvact]").count() == 0 and "Cancelled" in detail_text(owner))
        owner.context.close()

        check("no page errors", not errors, errors[:3])
        browser.close()

    print(f"\n{'ALL PASSED' if not failures else str(len(failures)) + ' FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
