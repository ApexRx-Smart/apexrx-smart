"""Browser test of one reservation across BOTH interfaces, as people use them:

  patient (search.html -> reservations.html)       pharmacy owner (pharmacy-dashboard.html)
  1 signs in (creates an account) from Reserve
  2 submits a reservation
                                                   3 signs in, 4 sees the new request
                                                   5 confirms it
  6 sees "confirmed" and the update without reloading
                                                   7 opens it, 8 types the reference the
                                                     patient shows (a wrong one is refused)
                                                   9 collects the full quantity
  10 sees "collected"; the stock and its audit trail show one deduction

Also: My stock shows recorded / reserved / free and warns before a quantity below
the reservations; handled request notifications stop counting as unread; opening a
reservation marks its updates read; the indicative-price wording; the header
account button leads a patient to their reservations and a pharmacy owner to the
pharmacy workspace.

LOCAL backend and throwaway database only. Setup the patient cannot do (the admin's
medicine settings; the owner's pharmacy, stock and unit acknowledgement) goes
through the API, the way those people do it; nothing is written to the database
directly. Backend on :8000 (APP_ENV=development, EMAIL_PROVIDER=mock), frontend on
:5501, then E2E_ADMIN_EMAIL=... E2E_ADMIN_PASSWORD=... python frontend/tests/e2e_reservation_journey.py
"""

import os
import re
import sys

from playwright.sync_api import sync_playwright

sys.path.insert(0, os.path.dirname(__file__))
import e2e_dashboards as D  # noqa: E402  (shared API and UI helpers)

RUN, call, check, failures = D.RUN, D.call, D.check, D.failures
MED = f"Journeymol {RUN}"
PATIENT = {"name": "Patient Uwase", "email": f"journey-patient-{RUN}@example.com"}
REFERENCE = re.compile(r"RX-[A-Z0-9]{10}")


def seed():
    admin = call("POST", "/auth/login", {"email": D.ADMIN_EMAIL, "password": D.ADMIN_PASSWORD})["access_token"]
    drug = call("POST", "/catalogue/drugs", {"name": MED, "therapeutic_class": "Analgesic"}, admin)["drug_id"]
    product = call("POST", "/catalogue/products", {"drug_id": drug, "product_name": f"{MED} 500mg", "strength": "500mg",
                                                   "pack_size": "B/20"}, admin)["product_id"]
    call("PATCH", f"/catalogue/products/{product}/reservation-settings",
         {"dispensing_class": "non_prescription", "stock_unit": "pack", "unit_label": "box",
          "max_reservation_quantity": 4, "reservation_enabled": True}, admin)
    owner_email = f"journey-owner-{RUN}@example.com"
    owner, org, (loc,) = D.org_with_owner(owner_email, f"Owner Mugisha {RUN}", f"Nyarutarama Pharmacy {RUN}", "pharmacy",
                                          [{"name": "Nyarutarama Branch", "latitude": -1.94, "longitude": 30.1}], admin=admin)
    base = f"/organizations/{org}/locations/{loc}/stock/{product}"
    call("PUT", base, {"quantity": 10}, owner)
    call("PUT", base + "/offer", {"unit_price": "2500"}, owner)
    s = call("GET", f"/catalogue/products/{product}/reservation-settings", token=admin)
    call("POST", f"/organizations/{org}/locations/{loc}/products/{product}/unit-acknowledgement",
         {k: s[k] for k in ("unit_version", "stock_unit", "unit_label", "pack_size")}, owner)
    return {"admin": admin, "owner": owner, "owner_email": owner_email, "org": org, "loc": loc, "product": product}


def stock(w):
    items = call("GET", f"/organizations/{w['org']}/inventory?location_id={w['loc']}", token=w["owner"])["items"]
    return next(i for i in items if i["product_id"] == w["product"])


def wait_text(page, selector, text, timeout=20000):
    page.wait_for_function("([s, t]) => (document.querySelector(s) || {}).textContent?.includes(t)",
                           arg=[selector, text], timeout=timeout)


def main():
    w = seed()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel=os.environ.get("E2E_BROWSER_CHANNEL") or None, headless=True)
        errors = []

        # ------------------------------------------------ 1-2 patient: search, sign in, reserve
        patient = D.new_page(browser)
        patient.context.add_init_script("window.APEX_RES_POLL_MS = 2000;")  # quicker background refresh for the test
        patient.on("pageerror", lambda e: errors.append(str(e)))
        patient.goto(f"{D.SITE}/search.html?q={MED.replace(' ', '%20')}&lang=en")
        patient.wait_for_selector(".ps-card")
        patient.locator(".ps-card button").first.click()
        patient.wait_for_selector("#ps-reserve-btn")
        check("search: Reserve is offered, with the indicative-price note",
              "indicative" in patient.inner_text("#ps-reserve"))
        patient.click("#ps-reserve-btn")
        patient.wait_for_selector("#rs-auth:not([hidden])")
        patient.click("#rs-tab-create")
        patient.fill("#rs-name", PATIENT["name"]); patient.fill("#rs-email", PATIENT["email"]); patient.fill("#rs-password", D.PW)
        patient.click("#rs-auth-submit")
        patient.wait_for_selector("#rs-reserve-form")
        check("form: the price is the pharmacy's listed price, indicative, paid at the pharmacy",
              "indicative, not a guaranteed final price" in patient.inner_text("#rs-reserve-body"))
        patient.fill("#rs-qty", "2"); patient.fill("#rs-phone", "0788 321 654")
        patient.click("#rs-submit")
        patient.wait_for_selector("#rs-success:not([hidden])")
        ref = patient.inner_text("#rs-success .rs-reference")
        check("patient: the request is sent with a reference", REFERENCE.fullmatch(ref) is not None, ref)
        patient.goto(f"{D.SITE}/reservations.html?lang=en")
        patient.wait_for_selector(f".rs-card a[data-ref='{ref}']")
        check("patient: the list shows it awaiting confirmation", "Awaiting confirmation" in patient.inner_text(".rs-card"))

        # ------------------------------------------------ 3-5 pharmacy: sees it, confirms
        pharmacy = D.new_page(browser)
        pharmacy.on("pageerror", lambda e: errors.append(str(e)))
        D.sign_in(pharmacy, w["owner_email"])
        check("pharmacy: the Reservations badge shows the new request", pharmacy.inner_text("#b-res") == "1")
        org_unread = lambda: call("GET", f"/notifications?organization_id={w['org']}", token=w["owner"])["unread_count"]  # noqa: E731
        check("pharmacy: the new request is an unread notification", org_unread() == 1)
        D.open_view(pharmacy, "res")
        pharmacy.wait_for_selector(f"#rv-list button.rv-ref[data-r='{ref}']")
        check("pharmacy: the request is listed with the patient and the quantity",
              PATIENT["name"] in pharmacy.inner_text("#rv-list") and "2 × box (B/20)" in pharmacy.inner_text("#rv-list"))
        pharmacy.click(f"#rv-list button.rv-ref[data-r='{ref}']")
        pharmacy.wait_for_selector("#rv-title")
        check("pharmacy: the price is presented as indicative", "indicative" in pharmacy.inner_text("#rv-detail"))
        pharmacy.click("#rv-detail [data-x=confirm]")
        pharmacy.check("#dlgf input[name=sure]"); pharmacy.click("#dlgf button.solid")
        wait_text(pharmacy, "#rv-detail", "Confirmed commitment")
        check("pharmacy: once handled, the request notification no longer counts as unread", org_unread() == 0)

        # ------------------------------------------------ 6 patient: sees the change without reloading
        wait_text(patient, "#rs-cards", "Confirmed", timeout=20000)
        patient.wait_for_selector(f".rs-notes li.unread a[data-ref='{ref}']", timeout=20000)
        check("patient: the list and the update arrive by themselves (no reload)",
              "is confirmed" in patient.inner_text("#rs-notes"))
        patient.goto(f"{D.SITE}/reservations.html?ref={ref}&lang=en")  # opened directly, not from the update
        patient.wait_for_selector("#rs-detail-title")
        shown_ref = patient.inner_text("#rs-detail-title .rs-reference")
        patient.wait_for_timeout(800)
        personal = call("POST", "/auth/login", {"email": PATIENT["email"], "password": D.PW})["access_token"]
        check("patient: opening the reservation marks its update read",
              call("GET", "/notifications", token=personal)["unread_count"] == 0)
        check("patient: the detail says confirmed, with the indicative price note",
              "Confirmed" in patient.inner_text(".rs-badge") and "indicative" in patient.inner_text("#rs-detail-body"))

        # ------------------------------------------------ My stock: reservations shown, warning before a shortfall
        D.open_view(pharmacy, "stk")
        pharmacy.wait_for_selector("#srows tr[data-product]")
        row = pharmacy.locator(f"#srows tr[data-product='{w['product']}']")
        # Opening My stock re-reads the branch from the API (the confirmation happened after the dashboard loaded).
        wait_text(pharmacy, f"#srows tr[data-product='{w['product']}']", "Reserved 2 · free 8")
        check("My stock: recorded quantity with reserved and free, re-read from the API", "Reserved 2 · free 8" in row.inner_text())
        qty = row.locator("input[data-f=qty]")
        qty.fill("1"); qty.dispatch_event("change")
        pharmacy.wait_for_selector("#dlg[open]")
        check("My stock: a quantity below the reservations asks first and explains",
              "Stock below confirmed reservations" in pharmacy.inner_text("#dlgf") and "1 recorded, 2 reserved (1 short)" in pharmacy.inner_text("#dlgf"))
        pharmacy.click("#dlg-x")
        pharmacy.wait_for_timeout(500)
        check("My stock: cancelling saves nothing", stock(w)["quantity"] == 10)

        # ------------------------------------------------ 7-9 pharmacy: reference, then collection
        D.open_view(pharmacy, "res")
        # The workspace keeps the reservation that was open.
        pharmacy.wait_for_selector("#rv-detail [data-x=collect]")
        check("pharmacy: coming back to Reservations keeps the open reservation", pharmacy.inner_text("#rv-title") == ref)
        wrong = "RX-" + ("A" * 10 if not ref.endswith("A" * 10) else "B" * 10)
        pharmacy.click("#rv-detail [data-x=collect]")
        pharmacy.fill("#dlgf [name=reference]", wrong); pharmacy.check("#dlgf input[name=sure]")
        pharmacy.click("#dlgf button.solid")
        wait_text(pharmacy, "#rv-detail", "does not match this reservation")
        check("collect: a wrong reference is refused; nothing collected, stock unchanged",
              call("GET", f"/organizations/{w['org']}/reservations/{ref}", token=w["owner"])["status"] == "confirmed"
              and stock(w)["quantity"] == 10)
        adjustments_before = call("GET", f"/organizations/{w['org']}/locations/{w['loc']}/stock/{w['product']}/adjustments",
                                  token=w["owner"])["total"]
        pharmacy.click("#rv-detail [data-x=collect]")
        pharmacy.fill("#dlgf [name=reference]", shown_ref.lower()); pharmacy.check("#dlgf input[name=sure]")
        pharmacy.locator("#dlgf button.solid").dblclick()
        wait_text(pharmacy, "#rv-detail", "Quantity handed over")
        after = stock(w)
        adjustments = call("GET", f"/organizations/{w['org']}/locations/{w['loc']}/stock/{w['product']}/adjustments",
                           token=w["owner"])
        newest = adjustments["items"][0]
        check("collect: the reference the patient showed is accepted; the full quantity is deducted once",
              after["quantity"] == 8 and after["allocated_quantity"] == 0 and adjustments["total"] == adjustments_before + 1
              and (newest["old_quantity"], newest["new_quantity"]) == (10, 8), (after["quantity"], newest))

        # ------------------------------------------------ 10 patient sees it collected
        wait_text(patient, "#rs-detail-body", "Collected", timeout=20000)
        check("patient: the open reservation updates to collected by itself", "You collected this medicine" in patient.inner_text("#rs-detail-body"))

        # ------------------------------------------------ header account buttons
        patient.goto(f"{D.SITE}/index.html?lang=en")
        patient.click("#signInBtn")
        patient.wait_for_url("**/reservations.html*", timeout=15000)
        check("header: a signed-in patient's account button opens their reservations", "reservations.html" in patient.url)
        pharmacy.goto(f"{D.SITE}/index.html?lang=en")
        pharmacy.click("#signInBtn")
        pharmacy.wait_for_url(re.compile(r".*(pharmacies\.html|pharmacy-dashboard\.html).*"), timeout=15000)
        check("header: a pharmacy owner's account button still opens the pharmacy workspace", "pharmac" in pharmacy.url)

        check("no page errors", not errors, errors[:3])
        browser.close()

    print(f"\n{'ALL PASSED' if not failures else str(len(failures)) + ' FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
