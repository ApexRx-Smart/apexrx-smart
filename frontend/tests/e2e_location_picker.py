"""The map location picker in a real browser, against a LOCAL backend and a
throwaway database (run like the other e2e tests):

  1. Registration: no latitude/longitude fields; "Use my current location"
     (browser geolocation, granted), address search, a click on the map and
     dragging the pin each set the location; saving stores those coordinates
     on the organization's main branch.
  2. Location permission refused, and a device outside Rwanda: a clear
     message, and the map remains the way to choose.
  3. Dashboard: editing a branch shows its saved pin and saves a new one; a
     new branch is placed by clicking the map (nobody needs to be there).
  4. Phone width: the dialog and the map fit.

OpenStreetMap is not contacted: map tiles and the address search are answered
by stubs in the browser (a fixed Kigali place), so the test does not depend on
an outside service. The backend checks the coordinates itself (in Rwanda).
"""

import base64
import json
import sys

from playwright.sync_api import sync_playwright

import e2e_dashboards as D  # noqa: E402

RUN, PW, check, failures = D.RUN, D.PW, D.check, D.failures
TILE = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMB/6XIRlUAAAAASUVORK5CYII=")
KIMIRONKO = {"display_name": "KG 11 Ave, Kimironko, Gasabo, Kigali, Rwanda", "lat": "-1.9490", "lon": "30.1260"}
REMERA = {"display_name": "KG 17 Ave, Remera, Gasabo, Kigali, Rwanda", "lat": "-1.9577", "lon": "30.1127"}


def fresh(browser, width=1280, height=900, geo=None, grant=True, place=KIMIRONKO):
    opts = {"viewport": {"width": width, "height": height}}
    if geo:
        opts["geolocation"] = geo
    ctx = browser.new_context(**opts)
    if geo and grant:
        ctx.grant_permissions(["geolocation"], origin=D.SITE)
    ctx.route("**/js/config.js", lambda r: r.fulfill(content_type="application/javascript",
                                                     body=f'window.APEX_CONFIG = {{ API_BASE_URL: "{D.API}" }};'))
    ctx.route("https://tile.openstreetmap.org/**", lambda r: r.fulfill(content_type="image/png", body=TILE))
    ctx.route("https://nominatim.openstreetmap.org/**", lambda r: r.fulfill(
        content_type="application/json", body=json.dumps([place]), headers={"Access-Control-Allow-Origin": "*"}))
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    # A missing file (for example a map marker image) would be a 404 here.
    page.on("response", lambda r: errors.append(f"{r.status} {r.url}") if r.status == 404 else None)
    return ctx, page, errors


def coords(page, scope="#location-picker"):
    return page.inner_text(f"{scope} .lp-status")


def sign_in(page, email):
    page.goto(D.SITE + "/pharmacy-sign-in.html")
    page.fill("#account [name=email]", email)
    page.fill("#account [name=password]", PW)
    page.click("#account-submit")


def main():
    admin = D.call("POST", "/auth/login", {"email": D.ADMIN_EMAIL, "password": D.ADMIN_PASSWORD,
                                           "account_type": "admin"})["access_token"]
    email = f"map-owner-{RUN}@example.com"
    token = D.account(email, "Map Owner", "pharmacy")
    D.verify_email(token)
    org = D.call("POST", "/organizations", {"name": f"Map Pharmacy {RUN}", "type": "pharmacy", "phone": "0788 123 456"},
                 token)["organization_id"]

    with sync_playwright() as p:
        browser = p.chromium.launch(channel=D.os.environ.get("E2E_BROWSER_CHANNEL") or None, headless=True)
        all_errors = []

        # ---- 1. registration: current location, search, click, drag; then save
        ctx, page, errors = fresh(browser, geo={"latitude": -1.9441, "longitude": 30.0619})
        sign_in(page, email)
        page.wait_for_selector("#details:not([hidden])", timeout=30000)
        page.wait_for_selector("#location-picker .lp-map .leaflet-container, #location-picker .lp-map.leaflet-container",
                               timeout=20000)
        check("1. no latitude or longitude fields to type", page.locator("#details [name=latitude], #details [name=longitude]").count() == 0)
        check("1. no location until one is chosen", "No location chosen yet." in coords(page))
        page.click("#location-picker .lp-gps")
        page.wait_for_function("document.querySelector('#location-picker .lp-status').textContent.includes('-1.944100')")
        check("1. 'Use my current location' places the pin where the device is", "30.061900" in coords(page))

        page.fill("#location-picker .lp-query", "Kimironko")
        page.click("#location-picker .lp-find")
        page.wait_for_selector("#location-picker .lp-results:not([hidden]) button")
        page.click("#location-picker .lp-results button")
        page.wait_for_function("document.querySelector('#location-picker .lp-status').textContent.includes('-1.949000')")
        check("1. a location is required: no 'Remove the location' button", page.is_hidden("#location-picker .lp-clear"))
        check("1. a searched place moves the pin and fills the empty street field",
              "30.126000" in coords(page) and page.input_value("#details [name=street]").startswith("KG 11 Ave"))

        before = coords(page)
        box = page.locator("#location-picker .lp-map").bounding_box()
        page.mouse.click(box["x"] + box["width"] * 0.3, box["y"] + box["height"] * 0.3)
        page.wait_for_function(f"document.querySelector('#location-picker .lp-status').textContent !== {json.dumps(before)}")
        check("1. clicking the map moves the pin", "Selected location" in coords(page))

        before = coords(page)
        pin = page.locator("#location-picker .leaflet-marker-icon").bounding_box()
        page.mouse.move(pin["x"] + pin["width"] / 2, pin["y"] + pin["height"] / 2)
        page.mouse.down()
        page.mouse.move(pin["x"] + pin["width"] / 2 + 40, pin["y"] + pin["height"] / 2 + 25, steps=8)
        page.mouse.up()
        page.wait_for_function(f"document.querySelector('#location-picker .lp-status').textContent !== {json.dumps(before)}")
        chosen = page.inner_text("#location-picker .lp-coords")
        lat, lng = (float(x) for x in chosen.split(","))
        check("1. dragging the pin adjusts it", -2.9 <= lat <= -1.0 and 28.8 <= lng <= 31.0, chosen)

        page.select_option("#address-fields [name=province]", "Kigali")
        page.select_option("#address-fields [name=district]", "Gasabo")
        page.select_option("#address-fields [name=sector]", "Kimironko")
        for level in ("cell", "village"):
            value = page.eval_on_selector(f"#address-fields [name={level}]", "s => s.options[1].value")
            page.select_option(f"#address-fields [name={level}]", value)
        page.click("#details-submit")
        page.wait_for_selector("#documents:not([hidden])", timeout=30000)
        locs = D.call("GET", f"/organizations/{org}/locations", token=token)
        check("1. saving stores exactly the chosen point on the organization's main branch",
              len(locs) == 1 and round(float(locs[0]["latitude"]), 6) == lat and round(float(locs[0]["longitude"]), 6) == lng,
              (locs, lat, lng))
        all_errors += errors
        ctx.close()

        # ---- 2. permission refused; a device outside Rwanda
        ctx, page, errors = fresh(browser, geo={"latitude": -1.9441, "longitude": 30.0619}, grant=False)
        sign_in(page, email)
        page.wait_for_selector("#documents:not([hidden])", timeout=30000)
        page.click("#documents-back")
        page.wait_for_selector("#details:not([hidden])")
        page.wait_for_function("document.querySelector('#location-picker .lp-status').textContent.includes('Selected location')")
        check("2. the saved location is shown when the details are opened again", f"{lat:.6f}" in coords(page))
        page.click("#location-picker .lp-gps")
        page.wait_for_function("document.querySelector('#location-picker .lp-message').textContent.length > 0", timeout=20000)
        check("2. permission refused: a clear message, the pin stays and the map remains usable",
              "not allowed" in page.inner_text("#location-picker .lp-message") and f"{lat:.6f}" in coords(page))
        all_errors += errors
        ctx.close()

        ctx, page, errors = fresh(browser, geo={"latitude": -1.2921, "longitude": 36.8219})  # Nairobi
        sign_in(page, email)
        page.wait_for_selector("#documents:not([hidden])", timeout=30000)
        page.click("#documents-back")
        page.wait_for_selector("#details:not([hidden])")
        page.click("#location-picker .lp-gps")
        page.wait_for_function("document.querySelector('#location-picker .lp-message').textContent.length > 0", timeout=20000)
        check("2. a device outside Rwanda: refused with a message, the saved pin is kept",
              "not in Rwanda" in page.inner_text("#location-picker .lp-message") and f"{lat:.6f}" in coords(page))
        all_errors += errors
        ctx.close()

        # ---- 3. dashboard: edit the branch location; add a remote branch by clicking the map
        D.complete_application(org, token, admin)
        D.call("POST", f"/admin/organizations/{org}/review", {"decision": "approved"}, admin)
        branch = D.call("GET", f"/organizations/{org}/locations", token=token)[0]
        for width, height, size in ((1280, 900, "desktop"), (390, 844, "phone")):
            ctx, page, errors = fresh(browser, width, height, place=REMERA)
            sign_in(page, email)
            page.wait_for_url("**/pharmacy-dashboard.html*", timeout=30000)
            D.ready(page)
            D.open_view(page, "set")
            page.click(f"[data-a=editloc][data-l='{branch['location_id']}']")
            page.wait_for_selector("#dlg[open] #loc-picker .lp-map")
            saved_lat = f"{lat:.6f}" if size == "desktop" else "-1.957700"  # moved to Remera on desktop
            check(f"3. {size}: the branch dialog shows the saved pin, with no coordinate fields",
                  saved_lat in coords(page, "#loc-picker")
                  and page.locator("#dlg [name=latitude], #dlg [name=longitude]").count() == 0)
            if size == "desktop":
                page.fill("#loc-picker .lp-query", "Remera")
                page.click("#loc-picker .lp-find")
                page.wait_for_selector("#loc-picker .lp-results:not([hidden]) button")
                page.click("#loc-picker .lp-results button")
                page.wait_for_function("document.querySelector('#loc-picker .lp-status').textContent.includes('-1.957700')")
                page.click("#dlgf button.solid")
                page.wait_for_function("!document.querySelector('#dlg').open")
                page.wait_for_timeout(800)
                saved = next(l for l in D.call("GET", f"/organizations/{org}/locations", token=token)
                             if l["location_id"] == branch["location_id"])
                check("3. editing saves the new location on that branch",
                      round(float(saved["latitude"]), 4) == -1.9577 and round(float(saved["longitude"]), 4) == 30.1127, saved)

                D.open_view(page, "set")
                page.click("[data-a=addloc]")
                page.wait_for_selector("#dlg[open] #loc-picker .lp-map")
                page.fill("#dlgf [name=name]", f"Remote Branch {RUN}")
                page.wait_for_timeout(300)
                page.click("#dlgf button.solid")  # no pin yet
                page.wait_for_function("document.querySelector('#dlg-err').textContent.length > 0")
                check("3. a branch cannot be saved without a map location (the dialog stays open, nothing saved)",
                      page.evaluate("document.querySelector('#dlg').open")
                      and "Place the branch on the map" in page.inner_text("#dlg-err")
                      and not [l for l in D.call("GET", f"/organizations/{org}/locations", token=token)
                               if l["name"] == f"Remote Branch {RUN}"])
                the_map = page.locator("#loc-picker .lp-map")
                the_map.scroll_into_view_if_needed()
                box = the_map.bounding_box()
                the_map.click(position={"x": box["width"] / 2, "y": box["height"] / 2})
                page.wait_for_function("document.querySelector('#loc-picker .lp-status').textContent.includes('Selected location')")
                page.click("#dlgf button.solid")
                page.wait_for_function("!document.querySelector('#dlg').open")
                page.wait_for_timeout(800)
                added = [l for l in D.call("GET", f"/organizations/{org}/locations", token=token) if l["name"] == f"Remote Branch {RUN}"]
                check("3. a new branch placed by clicking the map is saved with a location in Rwanda",
                      len(added) == 1 and added[0]["latitude"] is not None
                      and -2.9 <= float(added[0]["latitude"]) <= -1.0 and 28.8 <= float(added[0]["longitude"]) <= 31.0, added)
            else:
                map_box = page.locator("#loc-picker .lp-map").bounding_box()
                check("4. phone: the map is visible inside the dialog, and nothing scrolls sideways",
                      map_box["width"] > 250 and map_box["height"] > 150
                      and not page.evaluate("document.documentElement.scrollWidth > innerWidth + 1"))
                page.click("#dlg-x")
            all_errors += errors
            ctx.close()

        # ---- 5. a branch saved before map locations were required
        old = D.call("POST", f"/organizations/{org}/locations", {"name": f"Old Branch {RUN}", **D.KIGALI}, token)
        D.unplace_location(old["location_id"])
        ctx, page, errors = fresh(browser, place=REMERA)
        sign_in(page, email)
        page.wait_for_url("**/pharmacy-dashboard.html*", timeout=30000)
        D.ready(page)
        D.open_view(page, "set")
        row = f"tr[data-branch='{old['location_id']}']"
        check("5. a branch without a map location is flagged in the list", "No map location" in page.inner_text(row))
        page.click(f"{row} [data-a=editloc]")
        page.wait_for_selector("#dlg[open] #loc-picker .lp-map")
        page.click("#dlgf button.solid")
        page.wait_for_function("document.querySelector('#dlg-err').textContent.length > 0")
        check("5. ...and editing it asks for the location first", page.evaluate("document.querySelector('#dlg').open"))
        page.fill("#loc-picker .lp-query", "Remera")
        page.click("#loc-picker .lp-find")
        page.click("#loc-picker .lp-results button")
        page.wait_for_function("document.querySelector('#loc-picker .lp-status').textContent.includes('-1.957700')")
        page.click("#dlgf button.solid")
        page.wait_for_function("!document.querySelector('#dlg').open")
        page.wait_for_timeout(800)
        placed = next(l for l in D.call("GET", f"/organizations/{org}/locations", token=token) if l["location_id"] == old["location_id"])
        check("5. ...and once placed it is saved and no longer flagged",
              placed["latitude"] is not None and "No map location" not in page.inner_text(row), placed)
        all_errors += errors
        ctx.close()

        check("no script errors", not all_errors, all_errors[:3])
        browser.close()
    print(f"\n{'ALL PASSED' if not failures else str(len(failures)) + ' FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
