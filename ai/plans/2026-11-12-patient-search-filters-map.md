# Plan: patient search — See more, price and location filters, map and directions

Branch: `feature/patient-search-filters-map`, from `main` at 0322069.

## What already existed (inspected first)
- `GET /search/pharmacies` already supports:
  - `lat`/`lng`, `radius_km`, `max_price` and paging;
  - `sort=distance|price|freshness`;
  - per result: `distance_km`, coordinates, phone and `directions_url`.
- `GET /search/pharmacies/{location_id}` (one pharmacy with all its listed medicines) existed, but no screen used it.
- The homepage (`js/script.js`) used only `q`, sorted by freshness and showed 20 rows.
- The site had no maps.

## Changes
- **Backend** (`app/api/search.py`, `app/schemas/search.py`), extending the existing endpoint with no new route:
  - `min_price`; refuses `min_price > max_price` with 400.
  - `sort=price_desc`.
  - `record=false`, so refinements on the expanded page don't count again in search insights.
  - **Bug fix:** a location without coordinates got a distance of about 20,015 km, because PostgreSQL's `LEAST()` ignores NULLs. It now gets NULL. This also corrects supplier-offer distances on the pharmacy dashboard.
- **Homepage:** "See more" link under the results to `search.html?q=`. `index.html?q=` repeats a search without counting it again.
- **`search.html` and `js/patient-search.js`:**
  - Filters run on the server and combine: price range, sort, location (current position, a typed place via Nominatim, or a tap on the map) and radius.
  - The state lives in the URL (no coordinates), with history for the pharmacy view.
  - The pharmacy view shows its details beside a Leaflet map (stacked on phones), with the route from FOSSGIS OSRM (car or foot).
  - Directions open Google Maps or OpenStreetMap.
  - Handled: missing coordinates, denied or unavailable location, routing failure, empty results, API errors and loading states.
- **Leaflet 1.9.4** is kept in `frontend/vendor/leaflet/`: BSD-2, hash-verified, no CDN.
- **Translations:** English, French and Kinyarwanda strings in `js/script.js`. The Kinyarwanda should be checked by a native speaker.

## Costs and limits
None of the map services needs a key or billing. All are OpenStreetMap community services with usage policies and no uptime guarantee:
- Tiles: light use, attribution required.
- Routing: fair use.
- Nominatim: at most one request per second; the page sends a request only when the patient presses Find.

Heavy production traffic would need a hosted provider, which may cost money. That is to be discussed first.

## Tests
- **Backend:** `test_patient_search_price_and_location_filters` covers price range, both price sorts, invalid ranges, nearest first with a branch without coordinates, radius, combined filters and `record=false`.
- **Browser:** `frontend/tests/e2e_patient_search.py` covers the full journey against the real local backend. Only the third-party map services are stubbed. The real services were checked once separately.
