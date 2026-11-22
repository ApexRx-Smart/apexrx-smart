"""Browser test of patient reservations (Phase 3): public discovery and the Reserve
button on search.html, the signed-out sign-in / create-account handoff, the
reservation form (validation, duplicate protection, retries, stale unit, errors),
the patient's list (status filter, pages), details and history, cancellation and
conflicts, personal notifications, ownership isolation, privacy, the three
languages, a 390px phone and basic accessibility.

LOCAL backend and throwaway database only - never a shared environment.

  1. Backend on http://127.0.0.1:8000 (APP_ENV=development, migrated to head) and an
     admin account (see e2e_admin.py).
  2. Frontend on http://127.0.0.1:5501 (python -m http.server 5501 --directory frontend).
  3. E2E_ADMIN_EMAIL=... E2E_ADMIN_PASSWORD=... python frontend/tests/e2e_reservations.py

Each run creates its own medicines, pharmacy and accounts (suffixed with a random
id) through the API, the way the application does: the admin classifies the
medicines, the pharmacy owner stocks them, the owner
confirms and collects. Nothing is written to the database directly. js/config.js
is replaced in the browser so pages call the local API, and the hosted backend's
address is blocked.
"""

import json
import os
import re
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
PW = "Reservation-Test-2026"
MED = f"Rstamol {RUN}"
OWNER_NAME = f"Owner Kalisa {RUN}"
PATIENT_A = {"name": "Patient Aline", "email": f"res-a-{RUN}@example.com"}
PATIENT_B = {"name": "Patient Bosco", "email": f"res-b-{RUN}@example.com"}
REFERENCE = re.compile(r"RX-[ABCDEFGHJKMNPQRSTUVWXYZ23456789]{10}")
# Keys the patient-facing and public API responses must never contain.
PRIVATE_KEYS = {"quantity_on_hand", "recorded_quantity", "allocated_quantity", "available_to_reserve", "shortfall",
                "reservation_id", "patient_user_id", "deduction_adjustment_id", "correction_adjustment_id",
                "collected_xid", "verified_on_hand", "override_reason", "status_changed_by", "responded_by"}
failures = []


def check(label, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + label + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        failures.append(label)


def call(method, path, body=None, token=None, ok=True):
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(API + path, data=json.dumps(body).encode() if body is not None else None,
                                 method=method, headers=headers)
    try:
        with urllib.request.urlopen(req) as r:
            text = r.read().decode()
            return json.loads(text) if text else None
    except urllib.error.HTTPError as e:
        if ok:
            raise SystemExit(f"{method} {path} -> {e.code}: {e.read().decode()}") from None
        return {"_status": e.code, **json.loads(e.read().decode() or "{}")}


def login(email):
    return call("POST", "/auth/login", {"email": email, "password": PW})["access_token"]


def seed():
    admin = call("POST", "/auth/login", {"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})["access_token"]
    drug = call("POST", "/catalogue/drugs", {"name": MED, "therapeutic_class": "Analgesic"}, admin)["drug_id"]
    products = {}
    for key, name, strength in (("main", f"{MED} 500mg", "500mg"), ("stale", f"{MED} Syrup", "120mg/5ml"),
                                ("off", f"{MED} Forte", "1g"), ("bulk", f"{MED} Junior", "250mg")):
        pid = call("POST", "/catalogue/products", {"drug_id": drug, "product_name": name, "strength": strength,
                                                    "pack_size": "B/20"}, admin)["product_id"]
        # "off": prescription-only, so it can never be reserved.
        settings = {"dispensing_class": "prescription_only" if key == "off" else "non_prescription",
                    "stock_unit": "pack", "unit_label": "box", "max_reservation_quantity": 3}
        call("PATCH", f"/catalogue/products/{pid}/reservation-settings", settings, admin)
        products[key] = pid
    call("POST", "/auth/register", {"name": OWNER_NAME, "email": f"res-owner-{RUN}@example.com", "password": PW})
    owner = login(f"res-owner-{RUN}@example.com")
    org = call("POST", "/organizations", {"name": f"Gisozi Pharmacy {RUN}", "type": "pharmacy"}, owner)["organization_id"]
    loc = call("POST", f"/organizations/{org}/locations", {
        "name": "Gisozi Branch", "address": "KG 14 Ave, Gisozi", "city": "Kigali", "phone": "+250788555111",
        "latitude": -1.9235, "longitude": 30.0631}, owner)["location_id"]
    call("POST", f"/admin/organizations/{org}/review", {"decision": "approved"}, admin)
    for key, pid in products.items():
        call("PUT", f"/organizations/{org}/locations/{loc}/stock/{pid}", {"quantity": 40}, owner)
        call("PUT", f"/organizations/{org}/locations/{loc}/stock/{pid}/offer", {"unit_price": "1500"}, owner)
    for person in (PATIENT_B,):
        call("POST", "/auth/register", {**person, "password": PW})
    return {"admin": admin, "owner": owner, "org": org, "loc": loc, "products": products}


def context(browser, viewport=None):
    ctx = browser.new_context(viewport=viewport or {"width": 1366, "height": 900})
    ctx.route("**/js/config.js", lambda r: r.fulfill(content_type="application/javascript",
                                                     body=f'window.APEX_CONFIG = {{ API_BASE_URL: "{API}" }};'))
    ctx.route("https://apexrx-smart.onrender.com/**", lambda r: r.abort())
    ctx.route("https://tile.openstreetmap.org/**", lambda r: r.abort())
    ctx.route("https://routing.openstreetmap.de/**", lambda r: r.abort())
    ctx.bodies, ctx.urls = [], []

    def on_response(resp):
        if resp.url.startswith(API) and "json" in (resp.headers.get("content-type") or ""):
            try:
                ctx.bodies.append((resp.url, resp.json()))
            except Exception:  # noqa: BLE001 - not every response has a body
                pass
    ctx.on("response", on_response)
    ctx.on("request", lambda req: ctx.urls.append(req.url) if req.is_navigation_request() else None)
    return ctx


def keys(value):
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in keys(v)}
    return set()


def watch(page, errors):
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" and not any(
        s in m.text for s in ("Failed to load resource", "ERR_FAILED", "status of 40", "status of 503")) else None)


def wait_text(page, selector, text, timeout=15000):
    page.wait_for_function("([s, t]) => (document.querySelector(s) || {}).textContent?.includes(t)",
                           arg=[selector, text], timeout=timeout)


def wide(page):
    return page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1")


def unlabeled(page):
    """Form controls and buttons without an accessible name, on visible parts of the page."""
    return page.evaluate("""() => [...document.querySelectorAll('main input, main select, main textarea, main button, main a.rs-btn')]
      .filter(el => el.offsetParent !== null)
      .filter(el => {
        if (el.matches('button, a')) return !(el.textContent.trim() || el.getAttribute('aria-label'));
        return !(el.labels && el.labels.length) && !el.getAttribute('aria-label');
      }).map(el => el.id || el.outerHTML.slice(0, 60))""")


def open_reserve_from_search(page, product_name):
    page.goto(f"{SITE}/search.html?q={urllib.parse.quote(product_name)}&lang=en")
    page.wait_for_selector(".ps-card")
    page.locator(".ps-card button").first.click()
    page.wait_for_function("() => { const b = document.querySelector('#ps-reserve');"
                           " return b && b.textContent.trim() && !b.textContent.includes('Checking'); }", timeout=15000)


def main():
    w = seed()
    pid = w["products"]
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=os.environ.get("E2E_BROWSER_CHANNEL") or None, headless=True)
        errors = []

        # ===================================================== 1 public discovery (signed out)
        ctx = context(browser)
        page = ctx.new_page(); watch(page, errors)
        open_reserve_from_search(page, f"{MED} 500mg")
        btn = page.locator("#ps-reserve-btn")
        check("public: Reserve appears for an eligible medicine at this branch, signed out", btn.is_visible())
        check("public: the note says a reservation is a request and availability is not guaranteed",
              "not guaranteed" in page.locator("#ps-reserve").inner_text())
        open_reserve_from_search(page, f"{MED} Forte")
        check("public: no Reserve for a prescription-only medicine, and the reason is given",
              page.locator("#ps-reserve-btn").count() == 0
              and "Prescription-only" in page.locator("#ps-reserve").inner_text(), page.locator("#ps-reserve").inner_text())
        public = [b for u, b in ctx.bodies if "/search/" in u or "/reservations/options" in u]
        check("public: search and options responses carry no stock quantity or private field",
              public and not any(keys(b) & (PRIVATE_KEYS | {"quantity"}) for b in public))

        # ===================================================== 2 sign-in handoff
        open_reserve_from_search(page, f"{MED} 500mg")
        page.keyboard.press("Tab")
        page.locator("#ps-reserve-btn").focus(); page.keyboard.press("Enter")  # keyboard operable
        page.wait_for_selector("#rs-auth:not([hidden])")
        url = page.url
        check("handoff: Reserve opens the sign-in panel for this medicine and branch",
              f"location={w['loc']}" in url and f"product={pid['main']}" in url
              and page.locator("#rs-auth-title").inner_text() == "Sign in to reserve")
        wait_text(page, "#rs-auth-context", "Gisozi Pharmacy")
        check("handoff: the panel says what is being reserved",
              f"{MED} 500mg" in page.locator("#rs-auth-context").inner_text())
        page.click("#rs-tab-create")
        page.fill("#rs-name", PATIENT_A["name"]); page.fill("#rs-email", PATIENT_A["email"]); page.fill("#rs-password", "short")
        page.click("#rs-auth-submit")
        check("handoff: a short password is refused before anything is sent",
              "8 characters" in page.locator("#rs-auth-error").inner_text())
        page.fill("#rs-password", PW); page.click("#rs-auth-submit")
        page.wait_for_selector("#rs-reserve-form")
        check("handoff: after creating the account the patient is back on the same reservation",
              f"{MED} 500mg" in page.locator("#rs-reserve-body").inner_text()
              and "Gisozi Pharmacy" in page.locator("#rs-reserve-body").inner_text())
        body = page.locator("#rs-reserve-body").inner_text()
        check("form: unit, maximum, the 24-hour rules and 'not confirmed' are explained",
              "box (B/20)" in body and "From 1 to 3" in body and "24 hours" in body and "not a confirmed reservation" in body, body)

        # ===================================================== 3 validation
        page.fill("#rs-qty", "5"); page.click("#rs-submit")
        check("form: a quantity above the maximum is refused in the page", "from 1 to 3" in page.locator("#rs-reserve-error").inner_text())
        page.fill("#rs-qty", "2"); page.fill("#rs-phone", ""); page.click("#rs-submit")
        check("form: the phone number is required", "Enter a phone number" in page.locator("#rs-reserve-error").inner_text())
        page.fill("#rs-phone", "123456"); page.click("#rs-submit")
        wait_text(page, "#rs-reserve-error", "valid phone")
        check("form: the server's phone check is explained", True)

        # ===================================================== 4 lost response, retry, double click
        posts = []
        state = {"lose": True}

        def lose_first(route):
            posts.append(json.loads(route.request.post_data))
            if state["lose"]:
                state["lose"] = False
                route.fetch()  # the server creates the reservation...
                route.abort()  # ...but the browser never sees the answer
            else:
                route.continue_()
        page.route(f"{API}/reservations", lose_first)
        page.fill("#rs-phone", "0788 123 456"); page.fill("#rs-note", "After 5pm")
        page.click("#rs-submit")
        wait_text(page, "#rs-reserve-error", "could not be sent")
        page.locator("#rs-submit").dblclick()
        page.wait_for_selector("#rs-success:not([hidden])")
        page.unroute(f"{API}/reservations")
        ref_a = page.locator("#rs-success .rs-reference").inner_text()
        token_a = login(PATIENT_A["email"])
        mine = call("GET", "/reservations", token=token_a)
        check("retry: the same request id is resent, one double click sends one request",
              len(posts) == 2 and posts[0]["client_request_id"] == posts[1]["client_request_id"], posts)
        check("retry: exactly one reservation exists after a lost response and a double click",
              mine["total"] == 1 and mine["items"][0]["reference"] == ref_a)
        success = page.locator("#rs-success").inner_text()
        check("success: the response deadline is shown while awaiting confirmation", "Pharmacy responds by" in page.locator("#rs-success").inner_text())
        check("success: reference, 'Awaiting confirmation', medicine, pharmacy and a link",
              REFERENCE.fullmatch(ref_a) is not None and "Awaiting confirmation" in success and f"{MED} 500mg" in success
              and "Gisozi" in success and page.locator("#rs-success-view").is_visible())
        check("handoff: no email, phone or note was ever put in an address",
              not any(s in u for u in ctx.urls for s in ("@", "788", "After")), [u for u in ctx.urls if "@" in u or "788" in u])

        # The same medicine again: the existing open reservation is pointed to.
        page.goto(f"{SITE}/reservations.html?location={w['loc']}&product={pid['main']}&lang=en")
        page.wait_for_selector("#rs-reserve-form")
        page.fill("#rs-phone", "0788 123 456"); page.click("#rs-submit")
        wait_text(page, "#rs-reserve-error", "already have an open reservation")
        check("errors: an existing open reservation is linked by its reference",
              page.locator("#rs-reserve-error a").get_attribute("href").find(ref_a) > 0)

        # ===================================================== 5 stale unit
        page.goto(f"{SITE}/reservations.html?location={w['loc']}&product={pid['stale']}&lang=en")
        page.wait_for_selector("#rs-reserve-form")
        call("PATCH", f"/catalogue/products/{pid['stale']}/reservation-settings", {"unit_label": "carton"}, w["admin"])
        page.fill("#rs-phone", "0788 123 456"); page.click("#rs-submit")
        page.wait_for_selector(".rs-notice")
        check("stale unit: the page reloads the unit and asks the patient to review it",
              "has changed" in page.locator(".rs-notice").inner_text() and "carton (B/20)" in page.locator("#rs-reserve-body").inner_text())
        page.fill("#rs-phone", "0788 123 456"); page.click("#rs-submit")
        page.wait_for_selector("#rs-success:not([hidden])")
        ref_stale = page.locator("#rs-success .rs-reference").inner_text()
        check("stale unit: sending again after review works", REFERENCE.fullmatch(ref_stale) is not None)

        # A prescription-only medicine reached directly.
        page.goto(f"{SITE}/reservations.html?location={w['loc']}&product={pid['off']}&lang=en")
        wait_text(page, "#rs-reserve-body", "Prescription-only")
        check("not reservable: no form, the reason is shown", page.locator("#rs-reserve-form").count() == 0)

        # ===================================================== 6 list, pages, filter, detail, history
        for _ in range(10):  # closed reservations (cancelled) for paging; open ones are capped
            r = call("POST", "/reservations", {"location_id": w["loc"], "product_id": pid["bulk"], "quantity": 1,
                                               "unit_version": call("GET", f"/catalogue/products/{pid['bulk']}/reservation-settings", token=w["admin"])["unit_version"],
                                               "client_request_id": str(uuid.uuid4()), "contact_phone": "0788123456"}, token_a)
            call("POST", f"/reservations/{r['reference']}/cancel", {}, token_a)
        call("POST", f"/organizations/{w['org']}/reservations/{ref_a}/confirm", None, w["owner"])
        page.goto(f"{SITE}/reservations.html?lang=en")
        page.wait_for_selector(".rs-card")
        first_page = page.locator(".rs-card").count()
        check("list: 10 per page with page count", first_page == 10 and "Page 1 of 2" in page.locator("#rs-page").inner_text())
        page.click("#rs-next"); page.wait_for_function("document.querySelector('#rs-page').textContent.includes('Page 2')")
        check("list: the next page holds the rest", page.locator(".rs-card").count() == 2)
        page.select_option("#rs-status", "confirmed")
        page.wait_for_function("document.querySelectorAll('.rs-card').length === 1")
        card = page.locator(".rs-card").inner_text()
        check("list: status filter; the card has reference, medicine, branch, quantity and collect-by date",
              ref_a in card and "Confirmed" in card and "2 × box (B/20)" in card and "Collect by" in card and "Gisozi" in card, card)
        page.select_option("#rs-status", "expired")
        wait_text(page, "#rs-cards", "No reservations with this status")
        check("list: empty state for a filter", True)

        # Notifications: the confirmation is shown once, unread, and links to the reservation.
        page.select_option("#rs-status", "")
        page.wait_for_selector(".rs-notes li.unread")
        notes = page.locator(".rs-notes li").all_inner_texts()
        check("updates: the confirmation appears once, marked new, with the reference",
              sum(ref_a in n and "confirmed" in n for n in notes) == 1 and "1 new" in page.locator("#rs-unread").inner_text(), notes)
        page.locator(f".rs-notes a[data-ref='{ref_a}']").click()
        page.wait_for_selector("#rs-detail-title")
        detail = page.locator("#rs-detail-body").inner_text()
        history = page.locator(".rs-history li").all_inner_texts()
        labels = page.locator("#rs-detail-body dt").all_inner_texts()
        check("detail: opened from the update; next step, both deadlines, chronological history",
              ref_a in detail and "Go to the pharmacy before" in detail and "Collect by" in labels
              and "Confirmed" in labels and "Pharmacy responds by" not in labels and "Price per box" in labels
              and len(history) == 2 and "Request sent" in history[0] and "Confirmed by the pharmacy" in history[1], (detail, history))
        check("detail: no staff names, stock figures or internal records",
              OWNER_NAME not in page.content() and "recorded" not in detail.lower()
              and not any(keys(b) & PRIVATE_KEYS for u, b in ctx.bodies if "/reservations" in u))
        check("detail: the status is given in words, not colour alone",
              page.locator("#rs-detail-body .rs-badge").inner_text().strip().endswith("Confirmed: ready to collect"))
        page.goto(f"{SITE}/reservations.html?lang=en"); page.wait_for_selector(".rs-notes li")
        check("updates: opening it marked it read", page.locator(".rs-notes li.unread").count() == 0)

        # ===================================================== 7 cancellation and conflict
        page.goto(f"{SITE}/reservations.html?ref={ref_stale}&lang=en")
        page.wait_for_selector("#rs-cancel-open")
        page.click("#rs-cancel-open"); page.click("#rs-cancel-no")
        check("cancel: asks first, and 'Keep it' leaves it", page.locator("#rs-cancel-open").is_visible())
        page.click("#rs-cancel-open"); page.fill("#rs-cancel-reason", "Bought elsewhere")
        cancels = []
        page.on("request", lambda r: cancels.append(r.url) if r.method == "POST" and r.url.endswith("/cancel") else None)
        page.locator("#rs-cancel-yes").dblclick()
        wait_text(page, "#rs-flash", "Reservation cancelled")
        check("cancel: one request, then the refreshed reservation shows Cancelled with no Cancel button",
              len(cancels) == 1 and "Cancelled" in page.locator(".rs-badge").inner_text() and page.locator("#rs-cancel-open").count() == 0)
        page.goto(f"{SITE}/reservations.html?ref={ref_a}&lang=en")
        page.wait_for_selector("#rs-cancel-open")
        call("POST", f"/organizations/{w['org']}/reservations/{ref_a}/collect", {"reference": ref_a}, w["owner"])
        page.click("#rs-cancel-open"); page.click("#rs-cancel-yes")
        wait_text(page, "#rs-flash", "can no longer be cancelled")
        check("cancel: a conflict (collected meanwhile) is explained and the page refreshed",
              "Collected" in page.locator(".rs-badge").inner_text())

        # ===================================================== 8 languages
        for lang, heading, status in (("fr", "Mes réservations", "Retirée"), ("rw", "Ibyo nabikishije", "Wafashwe")):
            page.select_option("#langSelect", lang)
            page.wait_for_function("([h]) => document.querySelector('.rs-badge') && document.querySelector('h1').textContent === h", arg=[heading])
            text = page.locator("main").inner_text()
            check(f"{lang}: the reservation page is translated", status in text and "rs_" not in text, text[:200])
        page.goto(f"{SITE}/reservations.html?location={w['loc']}&product={pid['main']}&lang=fr")
        page.wait_for_selector("#rs-reserve-form")
        check("fr: the form and its explanations are translated",
              "Envoyer la demande de réservation" in page.locator("#rs-submit").inner_text()
              and "24 heures" in page.locator("#rs-reserve-body").inner_text())
        page.select_option("#langSelect", "rw")
        page.wait_for_function("document.querySelector('#rs-submit') && document.querySelector('#rs-submit').textContent.includes('Ohereza')")
        check("rw: the form is translated", "amasaha 24" in page.locator("#rs-reserve-body").inner_text())
        page.select_option("#langSelect", "en")
        check("accessibility: every visible control has a name (form)", not unlabeled(page), unlabeled(page))
        page.goto(f"{SITE}/reservations.html?lang=en"); page.wait_for_selector(".rs-card")
        check("accessibility: every visible control has a name (list)", not unlabeled(page), unlabeled(page))

        # Signing out returns to the sign-in panel.
        page.click("#rs-signout")
        page.wait_for_selector("#rs-auth:not([hidden])")
        check("sign out: the panel asks to sign in again and no reservation stays on screen",
              page.locator("#rs-cards").is_hidden() and ref_a not in page.locator("main").inner_text())
        ctx.close()

        # ===================================================== 9 ownership isolation
        ctx = context(browser)
        page = ctx.new_page(); watch(page, errors)
        page.goto(f"{SITE}/reservations.html?ref={ref_a}&lang=en")
        page.wait_for_selector("#rs-auth:not([hidden])")
        page.fill("#rs-email", PATIENT_B["email"]); page.fill("#rs-password", PW); page.click("#rs-auth-submit")
        wait_text(page, "#rs-detail-body", "Reservation not found")
        check("isolation: another patient's reference is 'not found'", ref_a not in page.locator("#rs-detail-body").inner_text())
        page.goto(f"{SITE}/reservations.html?lang=en")
        wait_text(page, "#rs-cards", "no reservations yet")
        check("isolation: the other patient's list is empty, with a way to search", page.locator(".rs-find").is_visible())
        ctx.close()

        # ===================================================== 10 phone layout (390px)
        ctx = context(browser, viewport={"width": 390, "height": 844})
        page = ctx.new_page(); watch(page, errors)
        open_reserve_from_search(page, f"{MED} 500mg")
        search_ok = not wide(page)
        page.goto(f"{SITE}/reservations.html?lang=en")
        page.wait_for_selector("#rs-auth:not([hidden])")
        page.fill("#rs-email", PATIENT_A["email"]); page.fill("#rs-password", PW); page.click("#rs-auth-submit")
        page.wait_for_selector(".rs-card")
        list_ok = not wide(page)
        page.goto(f"{SITE}/reservations.html?ref={ref_a}&lang=rw"); page.wait_for_selector("#rs-detail-title")
        detail_ok = not wide(page)
        page.goto(f"{SITE}/reservations.html?location={w['loc']}&product={pid['main']}&lang=fr"); page.wait_for_selector("#rs-reserve-form")
        form_ok = not wide(page)
        tap = page.locator("#rs-submit").bounding_box()
        check("390px: search, list, detail (rw) and form (fr) have no sideways scrolling",
              search_ok and list_ok and detail_ok and form_ok, (search_ok, list_ok, detail_ok, form_ok))
        check("390px: the submit button is a comfortable tap target", tap["height"] >= 44)
        ctx.close()

        check("no page errors or unexpected console errors", not errors, errors[:3])
        browser.close()

    print(f"\n{'ALL PASSED' if not failures else str(len(failures)) + ' FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
