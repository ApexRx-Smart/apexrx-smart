"""Browser test of the expanded patient search (search.html): "See more" from the
homepage, price filters, location (granted, denied, unavailable, typed place, map
tap), radius, sorting, the selected pharmacy with its map, route and directions,
missing coordinates, empty and error states, language and mobile layout.

LOCAL backend and throwaway database only - never a shared environment.

  1. Backend on http://127.0.0.1:8000 (APP_ENV=development) and an admin (see e2e_admin.py).
  2. Frontend on http://127.0.0.1:5501 (python -m http.server 5501 --directory frontend).
  3. E2E_ADMIN_EMAIL=... E2E_ADMIN_PASSWORD=... python frontend/tests/e2e_patient_search.py

Each run creates its own medicine and four approved pharmacies (suffixed with a
random id) through the API. Pharmacy data, prices and distances come from the
backend. Only the third-party map services are replaced in the browser: the route
(FOSSGIS OSRM) and place search (Nominatim) answer fixed responses, and map tiles
are not loaded, so the test does not depend on, or load, public servers.
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
PW = "Patient-Search-2026"
MED = f"Pstestamol {RUN}"
PATIENT = {"latitude": -1.9530, "longitude": 30.1240}  # near Kimironko
failures = []


def check(label, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + label + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        failures.append(label)


def call(method, path, body=None, token=None):
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(API + path, data=json.dumps(body).encode() if body is not None else None, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req) as r:
            text = r.read().decode()
            return json.loads(text) if text else None
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{method} {path} -> {e.code}: {e.read().decode()}") from None


def seed():
    admin = call("POST", "/auth/login", {"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})["access_token"]
    drug = call("POST", "/catalogue/drugs", {"name": MED, "therapeutic_class": "Analgesic"}, admin)["drug_id"]
    product = call("POST", "/catalogue/products", {"drug_id": drug, "product_name": f"{MED} 500mg", "pack_size": "B/30"}, admin)["product_id"]
    pharmacies = {}
    for key, name, place, lat, lng, price in (
        ("kim", "Kimironko Care", "KG 11 Ave, Kimironko", -1.9499, 30.1260, "1200"),
        ("rem", "Remera Health", "KG 17 Ave, Remera", -1.9577, 30.1127, "900"),
        ("nya", "Nyamirambo Family", "KN 2 St, Nyamirambo", -1.9785, 30.0448, "1500"),
        ("nomap", "No Map Pharmacy", "KN 4 Ave, Kigali", None, None, "700"),
    ):
        email = f"ps-{key}-{RUN}@example.com"
        call("POST", "/auth/register", {"name": name, "email": email, "password": PW})
        token = call("POST", "/auth/login", {"email": email, "password": PW})["access_token"]
        org = call("POST", "/organizations", {"name": f"{name} {RUN}", "type": "pharmacy"}, token)["organization_id"]
        loc_body = {"name": f"{name} Branch", "address": place, "city": "Kigali", "phone": "+250788123456"}
        if lat is not None:
            loc_body.update(latitude=lat, longitude=lng)
        loc = call("POST", f"/organizations/{org}/locations", loc_body, token)["location_id"]
        call("POST", f"/admin/organizations/{org}/review", {"decision": "approved"}, admin)
        call("PUT", f"/organizations/{org}/locations/{loc}/stock/{product}", {"quantity": 40}, token)
        call("PUT", f"/organizations/{org}/locations/{loc}/stock/{product}/offer", {"unit_price": price}, token)
        pharmacies[key] = {"org": org, "loc": loc, "name": f"{name} {RUN}", "price": price}
    return admin, pharmacies


def insights_count(admin):
    rows = call("GET", "/admin/insights/searches?days=1&limit=100", token=admin)
    return sum(r["searches"] for r in rows if r["query"].lower() == MED.lower())


ROUTE_OK = {"code": "Ok", "routes": [{"distance": 1830.0, "duration": 312.0, "geometry": {
    "type": "LineString", "coordinates": [[30.1240, -1.9530], [30.1190, -1.9550], [30.1127, -1.9577]]}}]}
PLACES = [{"lat": "-1.9496", "lon": "30.1263", "display_name": "Kimironko, Gasabo, Kigali, Rwanda"}]


def context(browser, viewport=None, geo=None, deny=False, no_geo_api=False):
    ctx = browser.new_context(viewport=viewport or {"width": 1366, "height": 900},
                              geolocation=geo, permissions=["geolocation"] if geo else [])
    ctx.route("**/js/config.js", lambda r: r.fulfill(content_type="application/javascript", body=f'window.APEX_CONFIG = {{ API_BASE_URL: "{API}" }};'))
    ctx.route("https://apexrx-smart.onrender.com/**", lambda r: r.abort())
    ctx.route("https://tile.openstreetmap.org/**", lambda r: r.abort())
    ctx.routes_seen = []

    def routing(r):
        ctx.routes_seen.append(r.request.url)
        if getattr(ctx, "route_fail", False):
            r.fulfill(status=503, body="busy")
        else:
            r.fulfill(content_type="application/json", body=json.dumps(ROUTE_OK))
    ctx.route("https://routing.openstreetmap.de/**", routing)
    ctx.route("https://nominatim.openstreetmap.org/**", lambda r: r.fulfill(content_type="application/json", body=json.dumps(PLACES)))
    if no_geo_api:
        ctx.add_init_script("Object.defineProperty(navigator, 'geolocation', { value: undefined, configurable: true });")
    return ctx


def watch(page, errors):
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" and not any(
        s in m.text for s in ("Failed to load resource", "ERR_FAILED", "status of 400", "status of 404", "status of 503")) else None)


def wait_text(page, selector, text, timeout=15000):
    page.wait_for_function("([s, t]) => (document.querySelector(s) || {}).textContent?.includes(t)", arg=[selector, text], timeout=timeout)


def prices(page):
    page.wait_for_function("document.querySelector('#ps-results').getAttribute('aria-busy') === 'false'")
    return [p.replace(" ", " ") for p in page.locator(".ps-card .ps-price").all_inner_texts()]


def names(page):
    return [n for n in page.locator(".ps-card .ps-place").all_inner_texts()]


def settle(page):
    page.wait_for_timeout(600)  # debounce (450 ms) + the request
    page.wait_for_function("document.querySelector('#ps-results').getAttribute('aria-busy') === 'false'")


def main():
    admin, ph = seed()
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=os.environ.get("E2E_BROWSER_CHANNEL") or None, headless=True)
        errors = []

        # =============================================== 1-4 homepage, then "See more"
        ctx = context(browser, geo=PATIENT)
        page = ctx.new_page(); watch(page, errors)
        before = insights_count(admin)
        page.goto(SITE + "/index.html")
        page.fill("#medicineSearchInput", MED)
        page.click("#medicineSearchForm button[type=submit]")
        page.wait_for_selector("#medicineSearchResults .result-row")
        rows = page.locator("#medicineSearchResults .result-row").count()
        more = page.locator("#medicineSearchMore")
        check("1-2. homepage search shows the real results and a 'See more' link",
              rows == 4 and more.is_visible() and more.get_attribute("href") == f"search.html?q={urllib.parse.quote(MED)}&lang=en", (rows, more.get_attribute("href")))
        check("   the homepage search is counted once in search insights", insights_count(admin) == before + 1)
        searches = []
        page.on("request", lambda r: searches.append(r.url) if "/search/pharmacies" in r.url else None)
        more.click()
        page.wait_for_url("**/search.html?*")
        page.wait_for_selector(".ps-card")
        check("3-4. the expanded page keeps the query", page.input_value("#ps-q") == MED and MED in urllib.parse.unquote_plus(page.url))
        got = prices(page)
        check("   all four pharmacies, lowest price first (backend sort)", got == ["RWF 700", "RWF 900", "RWF 1,200", "RWF 1,500"], got)
        check("   the lowest price is marked", page.locator(".ps-card").first.locator(".ps-best").count() == 1
              and page.locator(".ps-best").count() == 1)
        check("   prices use the site's currency format and the count is shown", "4 pharmacies" in page.inner_text("#ps-count"))

        # =============================================== 5-6 price range
        page.fill("#ps-min", "800"); page.fill("#ps-max", "1300"); settle(page)
        got = prices(page)
        check("5-6. a min and max price keep only 900 and 1,200 (server-side filter)", got == ["RWF 900", "RWF 1,200"], got)
        check("   the filters are in the URL", "min=800" in page.url and "max=1300" in page.url)
        check("   the request carried min_price, max_price and record=false",
              any("min_price=800" in u and "max_price=1300" in u and "record=false" in u for u in searches))
        page.select_option("#ps-sort", "price_desc"); settle(page)
        check("8a. highest price first", prices(page) == ["RWF 1,200", "RWF 900"])
        n = len(searches)
        page.fill("#ps-min", "2000"); page.wait_for_timeout(700)
        check("invalid range: a clear message, no request, results kept",
              "cannot be higher" in page.inner_text("#ps-filter-error") and len(searches) == n and len(prices(page)) == 2)
        page.fill("#ps-min", "-5"); page.wait_for_timeout(700)
        check("invalid price: negative values are refused", "0 or more" in page.inner_text("#ps-filter-error") and len(searches) == n)
        page.fill("#ps-min", ""); page.fill("#ps-max", "1"); settle(page)
        check("empty state when nothing matches", "No pharmacy matches" in page.inner_text("#ps-results") and page.is_hidden("#ps-more"))
        page.fill("#ps-max", ""); settle(page)

        # =============================================== 7-8 location: granted
        page.click("#ps-geo")
        wait_text(page, "#ps-origin-text", "current location")
        settle(page)
        order = names(page)
        check("7. 'Use my location' sorts nearest first; the pharmacy without coordinates comes last",
              [x.split(f" {RUN}")[0] for x in order] == ["Kimironko Care", "Remera Health", "Nyamirambo Family", "No Map Pharmacy"], order)
        cards = page.locator(".ps-card")
        last_meta = cards.last.locator(".ps-meta").inner_text()
        first_meta = cards.first.locator(".ps-meta").inner_text()
        check("   real distances from the backend; no invented distance for the branch without coordinates",
              re.search(r"0\.\d km away", first_meta) is not None and "No map location" in last_meta and "km away" not in last_meta, (first_meta, last_meta))
        check("   the sort shows 'Nearest first' and the radius is enabled",
              page.input_value("#ps-sort") == "distance" and page.is_enabled("#ps-radius"))
        page.select_option("#ps-radius", "2"); settle(page)
        within = [x for x in names(page)]
        check("   within 2 km: Kimironko and Remera only", len(within) == 2 and all(("Kimironko" in x or "Remera" in x) for x in within), within)
        page.fill("#ps-max", "1000"); settle(page)
        check("   filters combine: within 2 km AND at most 1,000", names(page) == [f"{ph['rem']['name']} (Remera Health Branch)"], names(page))
        page.select_option("#ps-sort", "price"); settle(page)
        check("8b. sorting by price keeps the distance shown", "km away" in page.locator(".ps-card").first.inner_text())
        page.click("#ps-reset"); settle(page)
        check("reset clears price, distance, location and sort", len(prices(page)) == 4 and page.input_value("#ps-min") == ""
              and page.is_hidden("#ps-origin") and page.is_disabled("#ps-radius") and page.input_value("#ps-sort") == "price")

        # =============================================== 9-11 a pharmacy, with the patient's location
        page.click("#ps-geo"); wait_text(page, "#ps-origin-text", "current location"); settle(page)
        rem_card = page.locator(f".ps-card[data-location='{ph['rem']['loc']}']")
        rem_card.locator("button").click()
        page.wait_for_selector("#ps-detail-title")
        info = page.inner_text("#ps-info")
        check("9-10. selecting a pharmacy shows its details from GET /search/pharmacies/{id}",
              ph["rem"]["name"] in info and "KG 17 Ave, Remera" in info and "+250788123456" in info and "RWF 900" in info, info[:200])
        check("   URL names the pharmacy (shareable)", f"pharmacy={ph['rem']['loc']}" in page.url)
        page.wait_for_selector("#ps-map .leaflet-marker-icon")
        wait_text(page, "#ps-route-msg", "km")
        check("11. map with pharmacy and patient markers, and the route from the patient",
              page.locator("#ps-map .ps-pin.pharmacy").count() == 1 and page.locator("#ps-map .ps-pin.origin").count() == 1
              and page.locator("#ps-map path.leaflet-interactive").count() >= 1 and "1.8 km" in page.inner_text("#ps-route-msg"), page.inner_text("#ps-route-msg"))
        check("   the route was asked for from the patient's position to the pharmacy (car)",
              any("routed-car" in u and "30.124,-1.953;30.1127,-1.9577" in u for u in ctx.routes_seen), ctx.routes_seen[-1:])
        g = page.get_attribute("#ps-dir-google", "href")
        check("   Google Maps directions carry origin, destination and mode",
              "origin=-1.95300%2C30.12400" in g and "destination=-1.9577%2C30.1127" in g and "travelmode=driving" in g, g)
        check("   OpenStreetMap directions from the patient", "route=-1.95300,30.12400;-1.9577,30.1127" in page.get_attribute("#ps-dir-osm", "href"))
        page.click("#ps-mode-foot"); wait_text(page, "#ps-route-msg", "km")
        check("   on foot: the walking route and walking directions",
              any("routed-foot" in u for u in ctx.routes_seen) and "travelmode=walking" in page.get_attribute("#ps-dir-google", "href"))
        ctx.route_fail = True
        page.click("#ps-mode-car"); wait_text(page, "#ps-route-msg", "could not be calculated")
        check("routing unavailable: a labelled straight line, directions buttons still there",
              page.locator("#ps-map path[stroke-dasharray]").count() == 1 and page.is_visible("#ps-dir-google"))
        ctx.route_fail = False
        page.click("#ps-back-results")
        page.wait_for_selector("#ps-list-view:not([hidden])")
        check("back to results keeps the filters and the list", "pharmacy=" not in page.url and len(prices(page)) == 4)
        page.go_forward(); page.wait_for_selector("#ps-detail-title")
        page.go_back(); page.wait_for_selector("#ps-list-view:not([hidden])")
        check("browser Back and Forward move between the list and the pharmacy", True)

        # Missing coordinates
        page.locator(f".ps-card[data-location='{ph['nomap']['loc']}'] button").click()
        page.wait_for_selector("#ps-detail-title")
        wait_text(page, "#ps-map-empty", "not added its map location")
        g = page.get_attribute("#ps-dir-google", "href")
        check("missing coordinates: no map or distance, directions use the address",
              page.is_hidden("#ps-map") and "destination=KN+4+Ave%2C+Kigali%2C+Rwanda" in g and page.locator("#ps-dir-osm").count() == 0, g)
        page.click("#ps-back-results"); page.wait_for_selector("#ps-list-view:not([hidden])")
        page.locator(f".ps-card[data-location='{ph['kim']['loc']}'] button").click()
        page.wait_for_selector("#ps-map .leaflet-marker-icon")
        check("   opening a pharmacy with coordinates afterwards shows its map again, without the message",
              page.is_visible("#ps-map") and page.is_hidden("#ps-map-empty"))
        page.click("#ps-back-results"); page.wait_for_selector("#ps-list-view:not([hidden])")

        # Language
        page.select_option("#langSelect", "fr")
        wait_text(page, "#ps-count", "pharmacies")
        check("language: switching to French translates the page and the results",
              "Filtrer et trier" in page.inner_text("#ps-filters") and "Voir la pharmacie" in page.inner_text("#ps-results") and "lang=fr" in page.url)
        page.select_option("#langSelect", "rw")
        wait_text(page, "#ps-filters", "Shungura")
        check("language: Kinyarwanda too", "Farumasi" in page.inner_text("#ps-count"))
        page.select_option("#langSelect", "en")

        # Back to the homepage search (not counted again)
        count_before_back = insights_count(admin)
        page.click("#ps-back")
        page.wait_for_url("**/index.html?*")
        page.wait_for_selector("#medicineSearchResults .result-row")
        check("'Back to search' returns to the homepage with the same search, not counted again",
              page.input_value("#medicineSearchInput") == MED and insights_count(admin) == count_before_back == before + 1,
              (insights_count(admin), count_before_back, before))
        ctx.close()

        # =============================================== 12 location denied: typed place, map tap
        ctx = context(browser)  # no geolocation permission
        page = ctx.new_page(); watch(page, errors)
        page.goto(f"{SITE}/search.html?q={urllib.parse.quote(MED)}")
        page.wait_for_selector(".ps-card")
        check("no location line until the patient sets one", page.is_hidden("#ps-origin") and page.is_hidden("#ps-places"))
        page.click("#ps-geo")
        wait_text(page, "#ps-loc-msg", "denied")
        check("12. permission denied: a clear message, search still works", len(prices(page)) == 4)
        page.fill("#ps-place", "Kimironko"); page.press("#ps-place", "Enter")
        page.wait_for_selector("#ps-places button")
        page.click("#ps-places button")
        wait_text(page, "#ps-origin-text", "Kimironko"); settle(page)
        check("   a typed place (Nominatim) is used instead: nearest first from it",
              names(page)[0].startswith(ph["kim"]["name"]) and "km away" in page.locator(".ps-card").first.inner_text())
        page.locator(f".ps-card[data-location='{ph['kim']['loc']}'] button").click()
        page.wait_for_selector("#ps-map .ps-pin.origin")
        check("   the pharmacy map routes from the typed place", page.get_attribute("#ps-dir-google", "href").count("origin=-1.94960") == 1)
        page.click("#ps-origin-clear") if page.is_visible("#ps-origin-clear") else None
        box = page.locator("#ps-map").bounding_box()
        page.mouse.click(box["x"] + box["width"] * 0.3, box["y"] + box["height"] * 0.7)
        page.wait_for_function("document.querySelector('#ps-origin-text').textContent.includes('map')")
        check("   tapping the map sets the starting point", page.locator("#ps-map .ps-pin.origin").count() == 1)
        ctx.close()

        # Geolocation not available at all
        ctx = context(browser, no_geo_api=True)
        page = ctx.new_page(); watch(page, errors)
        page.goto(f"{SITE}/search.html?q={urllib.parse.quote(MED)}")
        page.wait_for_selector(".ps-card")
        page.click("#ps-geo")
        wait_text(page, "#ps-loc-msg", "not available")
        check("geolocation unavailable: a clear message, nothing breaks", len(prices(page)) == 4)
        # A shared link to one pharmacy opens it; Back to results stays on the site.
        page.goto(f"{SITE}/search.html?q={urllib.parse.quote(MED)}&pharmacy={ph['kim']['loc']}")
        page.wait_for_selector("#ps-detail-title")
        check("a shared pharmacy link opens it and highlights the searched medicine",
              ph["kim"]["name"] in page.inner_text("#ps-info") and page.locator(".ps-medlist li.match").count() == 1)
        page.click("#ps-back-results")
        page.wait_for_selector("#ps-list-view:not([hidden])")
        check("   'Back to results' from a shared link stays on the page", "search.html" in page.url and len(prices(page)) == 4)
        ctx.close()

        # API failure and loading state
        ctx = context(browser)
        page = ctx.new_page(); watch(page, errors)
        ctx.route(re.compile(r".*/search/pharmacies\?.*"), lambda r: r.fulfill(status=500, body="{}"))
        page.goto(f"{SITE}/search.html?q={urllib.parse.quote(MED)}")
        wait_text(page, "#ps-results", "Unable to load")
        check("API failure: an error message instead of results", page.locator(".ps-card").count() == 0)
        ctx.close()

        # =============================================== mobile
        ctx = context(browser, viewport={"width": 390, "height": 844}, geo=PATIENT)
        page = ctx.new_page(); watch(page, errors)
        page.goto(f"{SITE}/search.html?q={urllib.parse.quote(MED)}")
        page.wait_for_selector(".ps-card")
        wide = lambda: page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1")  # noqa: E731
        list_ok = not wide()
        page.click("#ps-geo"); wait_text(page, "#ps-origin-text", "current location"); settle(page)
        page.locator(".ps-card button").first.click()
        page.wait_for_selector("#ps-map .leaflet-marker-icon")
        mbox = page.locator("#ps-map").bounding_box(); ibox = page.locator("#ps-info").bounding_box()
        check("mobile: no sideways scroll; the map comes first, full width, above the details",
              list_ok and not wide() and mbox["height"] >= 250 and mbox["width"] >= 330 and mbox["y"] < ibox["y"], (mbox, ibox))
        covered = page.evaluate("""() => { const b = document.querySelector('#ps-back-results').getBoundingClientRect();
          const hit = document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2);
          return !(hit && (hit.id === 'ps-back-results' || hit.closest('#ps-back-results'))); }""")
        check("mobile: 'Back to results' is not hidden under the floating header", not covered)
        ctx.close()

        check("no page errors or unexpected console errors", not errors, errors[:3])
        browser.close()

    print(f"\n{'ALL PASSED' if not failures else str(len(failures)) + ' FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
