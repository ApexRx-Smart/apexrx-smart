"""End-to-end check of the admin console's Medicines tab (frontend/ops-console-7f3k9q.html#medicines):
classifying a catalogue medicine as non-prescription (or prescription only) and setting
its stock unit, which decides whether patients can reserve it.

Same setup as e2e_admin_console.py (LOCAL backend, throwaway database, an admin account):
  E2E_ADMIN_EMAIL=... E2E_ADMIN_PASSWORD=... python frontend/tests/e2e_admin_medicines.py

Never point this at production: it adds catalogue entries and changes their settings.
"""

import os
import sys

from playwright.sync_api import sync_playwright

import e2e_admin_console as C

check, call, ok, RUN = C.check, C.call, C.ok, C.RUN


def seed():
    admin = C.admin_token()
    drug = ok("POST", "/catalogue/drugs", {"name": f"Medtestcillin {RUN}"}, admin)
    product = ok("POST", "/catalogue/products", {"drug_id": drug["drug_id"], "product_name": f"Medtest 500mg {RUN}",
                                                  "dosage_form": "capsule", "pack_size": "20 capsules"}, admin)
    plain = C.account(f"medicines-user-{RUN}@example.com", f"Medicines User {RUN}")
    return admin, product["product_id"], plain


def settings_of(admin, product_id):
    return ok("GET", f"/catalogue/products/{product_id}/reservation-settings", token=admin)


def main():
    admin, product_id, plain = seed()
    name = f"Medtest 500mg {RUN}"

    # ---- Backend: only platform admins list or change the settings.
    url = f"/catalogue/products/{product_id}/reservation-settings"
    check("backend: a regular user gets 403 on the medicines list and on a change",
          call("GET", "/catalogue/reservation-settings", token=plain)[0] == 403
          and call("PATCH", url, {"dispensing_class": "non_prescription"}, plain)[0] == 403)
    check("backend: no token gets 401", call("GET", "/catalogue/reservation-settings")[0] == 401)

    with sync_playwright() as p:
        browser = p.chromium.launch(channel=os.environ.get("E2E_BROWSER_CHANNEL") or None, headless=True)
        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        ctx.route("**/js/config.js", lambda route: route.fulfill(
            content_type="application/javascript", body=f'window.APEX_CONFIG = {{ API_BASE_URL: "{C.API}" }};'))
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        dialogs = {"answer": True, "seen": []}

        def on_dialog(d):
            dialogs["seen"].append(d.message)
            d.accept() if dialogs["answer"] else d.dismiss()
        page.on("dialog", on_dialog)

        page.goto(C.SITE + "/ops-console-7f3k9q.html")
        page.fill("#login-form [name=email]", C.ADMIN_EMAIL)
        page.fill("#login-form [name=password]", C.ADMIN_PASSWORD)
        page.click("#login-button")
        page.wait_for_selector("[data-panel=overview]:not([hidden])")

        # ---- 1. Overview: unclassified medicines are a to-do.
        page.wait_for_function("!['–', '…'].includes(document.querySelector('[data-overview=meds_unclassified]').textContent)")
        unclassified = ok("GET", "/catalogue/reservation-settings?limit=1&dispensing_class=unclassified", token=admin)["total"]
        check("1. overview counts medicines not classified yet",
              page.text_content("[data-overview=meds_unclassified]") == str(unclassified))
        page.click("[data-goto-medicines=unclassified]")
        page.wait_for_selector("[data-panel=medicines]:not([hidden])")
        C.settled(page, "#med-rows")
        check("1. it opens the Medicines tab filtered to unclassified medicines",
              page.input_value("#med-filters [name=dispensing_class]") == "unclassified" and page.url.endswith("#medicines"))
        page.wait_for_function("!['–', '…'].includes(document.querySelector('[data-med-count=all]').textContent)")
        totals = {k: ok("GET", "/catalogue/reservation-settings?limit=1" + (f"&dispensing_class={k}" if k != "all" else ""),
                        token=admin)["total"] for k in ("unclassified", "non_prescription", "prescription_only", "all")}
        shown = {k: page.text_content(f"[data-med-count={k}]") for k in totals}
        check("1. the tab's counts match the API", all(shown[k] == str(v) for k, v in totals.items()), (shown, totals))

        # ---- 2. Find the new medicine: not classified, cannot be reserved, and why.
        page.select_option("#med-filters [name=dispensing_class]", "")
        page.fill("#med-filters [name=q]", RUN)
        page.click("#med-filters button")
        C.settled(page, "#med-rows")
        row = page.locator(f"#med-rows tr[data-medicine='{name}']")
        text = row.inner_text()
        check("2. the medicine shows 'Not classified yet', 'No' and the reasons",
              "Not classified yet" in text and "Only medicines classified as non-prescription can be reserved." in text
              and "Choose the stock unit" in text, text)

        # ---- 3. Classify it: validation in the page, then a confirmation.
        row.locator("button", has_text="Classify").click()
        form = page.locator("#med-rows .med-form-row form")
        form.locator("[name=dispensing_class]").select_option("non_prescription")
        form.locator("[name=stock_unit]").select_option("pack")
        check("3. the pack size is prefilled from the catalogue", form.locator("[name=pack_size]").input_value() == "20 capsules")
        form.locator("button.primary").click()
        check("3. a unit name is required before sending", "Name the unit" in form.locator(".error").inner_text())
        form.locator("[name=unit_label]").fill("box")
        dialogs["answer"] = False
        form.locator("button.primary").click()
        page.wait_for_timeout(500)
        check("3. classifying as non-prescription asks for confirmation",
              any("non-prescription" in m and "without a prescription" in m for m in dialogs["seen"]))
        check("3. cancelling the confirmation saves nothing", settings_of(admin, product_id)["dispensing_class"] == "unclassified")
        dialogs["answer"] = True
        form.locator("button.primary").click()
        C.wait_text(page, "#med-message", "Patients can now reserve it")
        saved = settings_of(admin, product_id)
        check("3. saved: non-prescription, packs of box, ready for reservations",
              (saved["dispensing_class"], saved["stock_unit"], saved["unit_label"], saved["ready"]) ==
              ("non_prescription", "pack", "box", True), saved)
        text = page.locator(f"#med-rows tr[data-medicine='{name}']").inner_text()
        check("3. the row shows Non-prescription, the unit and 'Yes'",
              "Non-prescription" in text and "Packs (box) of 20 capsules" in text and "Yes" in text, text)

        # ---- 4. Edit: the most per reservation, then prescription only.
        page.locator(f"#med-rows tr[data-medicine='{name}'] button", has_text="Edit").click()
        form = page.locator("#med-rows .med-form-row form")
        form.locator("[name=max_reservation_quantity]").fill("0")
        form.locator("button.primary").click()
        check("4. an invalid maximum is refused in the page", "whole number from 1 to 1000" in form.locator(".error").inner_text())
        form.locator("[name=max_reservation_quantity]").fill("3")
        before = len(dialogs["seen"])
        form.locator("button.primary").click()
        page.wait_for_selector("#med-rows .med-form-row", state="detached")  # the list repaints after saving
        C.settled(page, "#med-rows")
        check("4. no confirmation when the classification does not change", len(dialogs["seen"]) == before)
        check("4. the maximum is saved", settings_of(admin, product_id)["effective_max_quantity"] == 3)
        page.locator(f"#med-rows tr[data-medicine='{name}'] button", has_text="Edit").click()
        page.locator("#med-rows .med-form-row [name=dispensing_class]").select_option("prescription_only")
        page.locator("#med-rows .med-form-row button.primary").click()
        C.wait_text(page, "#med-message", "prescription only")
        text = page.locator(f"#med-rows tr[data-medicine='{name}']").inner_text()
        check("4. prescription only: patients cannot reserve it",
              "Prescription only" in text and "Prescription-only medicines cannot be reserved." in text
              and "Choose the stock unit" not in text and settings_of(admin, product_id)["ready"] is False, text)

        # ---- 5. The classification filter.
        page.select_option("#med-filters [name=dispensing_class]", "non_prescription")
        C.settled(page, "#med-rows")
        check("5. filtering by non-prescription hides it", page.locator(f"#med-rows tr[data-medicine='{name}']").count() == 0)
        page.click("[data-med-class=prescription_only]")
        C.settled(page, "#med-rows")
        page.fill("#med-filters [name=q]", RUN)
        page.click("#med-filters button")
        C.settled(page, "#med-rows")
        check("5. the Prescription only card shows it", page.locator(f"#med-rows tr[data-medicine='{name}']").count() == 1)

        # ---- Phone width.
        page.set_viewport_size({"width": 375, "height": 800})
        page.wait_for_timeout(400)
        check("mobile: no horizontal page scroll", not page.evaluate("document.documentElement.scrollWidth > window.innerWidth"))
        check("no page errors", not errors, errors)
        browser.close()

    # Leave the throwaway product retired so it does not clutter later runs' lists.
    call("PATCH", f"/catalogue/products/{product_id}", {"is_active": False}, admin)
    print(f"\n{'ALL PASSED' if not C.failures else str(len(C.failures)) + ' FAILED'}")
    return 1 if C.failures else 0


if __name__ == "__main__":
    sys.exit(main())
