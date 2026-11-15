# Frontend

A static site (HTML, CSS and vanilla JavaScript, no build step) that talks to the FastAPI backend in `backend/`.

## Run locally

1. Start the backend on port 8000 (see the root README).
2. Serve this folder on port 5501, which the backend allows through CORS by default:

   ```bash
   cd frontend
   python -m http.server 5501 --bind 127.0.0.1
   ```

   VS Code Live Server works too. `.vscode/settings.json` sets it to port 5501.
3. Open http://127.0.0.1:5501/index.html.

The backend address is set in `js/config.js` (`window.APEX_CONFIG.API_BASE_URL`), which every page loads before `js/api.js`. It points at the hosted Render backend. To use a local backend, change it to `http://127.0.0.1:8000` and don't commit that change. Whichever backend you use must list the site's address in `CORS_ORIGINS`.

## Public pages

| Page | What it is |
|---|---|
| `index.html` | Landing page: medicine search (`#hero-search`), the numbers and the call to action. `index.html?q=` repeats a search (search.html's "Back to search") |
| `search.html` | Expanded patient search, from the homepage's **See more**: price range, location (current position, a typed place or a tap on the map), distance, sorting, then the selected pharmacy beside a map with the route and directions (`js/patient-search.js`) |
| `how-it-works.html` | "Built for everyone in the medicine chain" and "How it works", moved from the landing page |
| `about.html` | About ApexRX_Smart, Our Mission, Our Vision, Our Team and Our Organization. Placeholder copy (Lorem ipsum, "Team member name") to replace; see the comment at the top of the file |
| `legal.html#privacy`, `#terms`, `#cookies` | One layout for the legal pages (`js/legal.js` shows the one in the address). Clearly marked placeholders, not approved policies |
| `pharmacies.html` | Pharmacy registration and sign-in (`js/registration.js`), then `pharmacy-dashboard.html` |
| `suppliers.html` | Supplier registration and sign-in (`js/registration.js`, the same journey with `<body data-role="supplier">`), then `supplier-dashboard.html` |
| `pharmacy-dashboard.html`, `supplier-dashboard.html` | The dashboards (`js/dashboard.js`); see below. `?preview=1` shows sample data |
| `verify-email.html` | Opened from the verification email; sends the link's token to `POST /auth/email/verify` (`js/verify-email.js`) |
| `accept-invitation.html` | Opened from a staff invitation: set up your own account, or sign in, and join (`js/accept-invitation.js`) |
| `reset-password.html` | "Forgot password?": says it is temporarily unavailable while email is disabled (`GET /auth/capabilities`); the reset form works again once email returns (`js/reset-password.js`) |
| `ops-console-7f3k9q.html` | Admin console (staff only). Not linked from any public page; open the URL directly |

- **Shared header and footer:** `js/site-layout.js` provides them for `index.html`, `how-it-works.html`, `about.html` and `legal.html`, so the navigation is defined once.
  - Each page includes it twice: `data-part="header"` and `data-part="footer"`. It renders in place, before `js/script.js`.
  - `<body data-page="…">` marks the current page.
  - `js/script.js` adds the translations, the mobile menu, and the **Sign in** / **Get started** buttons on every one of these pages.
- **Main navigation:** For Pharmacies, For Suppliers, How it works, About. **For Patients** is not in the main navigation: patients use the search on the landing page.
- **Footer links:**
  - Product: For Patients goes to `index.html#hero-search` (`#hero-search` on the landing page itself). The others go to the registration pages and How it works.
  - Company: all four links go to `about.html` for now.
  - Legal: the three legal pages.
  - There is no admin link: the admin console is never linked from the public site.
- **Show/hide password:** `js/password-toggle.js` adds an eye button to every password field on `pharmacies.html`, `suppliers.html` and `ops-console-7f3k9q.html`.
  - It has a "Show password" / "Hide password" label (English, French, Kinyarwanda) and `aria-pressed`, and works from the keyboard.
  - Fields go back to hidden when their form is submitted.
- **Sign in or create account:** both registration pages have an "Already have an account? Sign in" switch on their first step, and `#signin` opens it directly; the homepage **Sign in** button uses `pharmacies.html#signin`.
  - Sign-in mode asks only for email and password, and calls `POST /auth/login`.
  - A supplier-only account signing in on the pharmacy page is pointed to `suppliers.html`, instead of being asked to register a pharmacy (and the other way round). An ApexRX administrator is told to sign out instead.
  - A session already in the tab (a refresh, another ApexRX page, the admin portal) is continued, and the page always says which account it is: "Signed in as … · Sign out".

## How the pages use the API

All requests go through `js/api.js` (`window.ApexAPI`). It covers every backend endpoint. It turns error responses into `ApiError` objects with a readable `message`. It keeps the access token in `sessionStorage`, so the token is cleared when the tab closes.

| Page / control | Endpoint |
|---|---|
| Homepage medicine search | `GET /search/pharmacies?q=`: availability status, price, location and freshness. Never exact quantities. **See more** opens `search.html?q=` |
| `search.html` results and filters | `GET /search/pharmacies?q=&min_price=&max_price=&lat=&lng=&radius_km=&sort=price\|price_desc\|distance\|freshness&record=false`. Filtering and sorting run on the server, so they combine and work on any number of results; pages of 30 with **Show more pharmacies**. `record=false` keeps refinements out of search insights (the homepage already counted the search). Branches without coordinates have no distance: they are listed last when sorting by distance and left out by a distance limit |
| `search.html` selected pharmacy | `GET /search/pharmacies/{location_id}`: details and every medicine it lists. The map uses OpenStreetMap tiles; the route comes from FOSSGIS OSRM (`routing.openstreetmap.de`, car or foot); a typed place from Nominatim. Leaflet 1.9.4 is in `vendor/leaflet/`. If routing fails the map shows a labelled straight line. Directions buttons open Google Maps or OpenStreetMap (with the starting point when known) |
| Homepage **Sign in** / **Get started** | Open `pharmacies.html#signin` / `pharmacies.html` |
| Pharmacy page: *Register a pharmacy* / *Staff sign-in* tabs (`#staff`, `#signin`) | Staff sign-in is `POST /auth/login` with the person's own account, then `GET /auth/me`. Several pharmacies: a chooser, then the dashboard. **Forgot password?** opens `reset-password.html` |
| Dashboard **Sign out**, public header **Sign out** | `POST /auth/logout`: ends this session only |
| Session activity, inactivity warning, other tabs | `js/api.js`: `POST /auth/session/activity` on real user activity; see the root README, "Sessions" |
| Branches and team → Invite a team member (email disabled: **Create invitation link** shows the link once, with **Copy link**), invitation list (New link / Resend, Revoke) | `POST/GET /organizations/{id}/invitations`, `.../{inv}/resend`, `.../{inv}/revoke` (owners and managers) |
| Registration step 1, Account (both pages) | **Create account:** `POST /auth/register`, then `POST /auth/login` (an email that already has an account signs in). **Sign in:** `POST /auth/login` only. Then everything below is decided from `GET /auth/me`, `GET /auth/email/status` and the organization's records, so an incomplete registration resumes where it stopped |
| Step 2, Verify email | `GET /auth/email/status`; `POST /auth/email/send {next}` sends the link (automatically the first time). **I've verified my email** re-checks the status; the page also re-checks when it regains focus and when `verify-email.html` reports success in the same browser. **Resend** counts down `resend_after` |
| `verify-email.html` | `POST /auth/email/verify {token}` (no session). Messages for verified, already verified, invalid, expired, used and superseded links |
| Step 3, Details | `POST /organizations` (`type` from the page's `data-role`; 403 `email_unverified` brings the user back to step 2), then `POST /organizations/{id}/locations` with `name`, `region` (province), `city` (district), `sector`, `cell`, `village`, `address` (street or landmark), `phone`, `whatsapp_phone`, `latitude`/`longitude` (optional; "Use my current location", checked against Rwanda's bounds). Coming back updates the same records with `PATCH`. Province to village come from `data/rwanda-locations.json` |
| Step 4, Documents | `POST /organizations/{id}/documents` per selected file. Pharmacies: pharmacy license, business license, owner ID. Suppliers: business license, owner ID |
| Step 5, Review | `GET /organizations/{id}`, `/locations`, `/documents`: status, review note, stored details, document statuses and reasons. Owners and managers can **Edit details** and **Add a document**; owners can **Resubmit for review** after a rejection (`POST /organizations/{id}/resubmit`). **Open your workspace** opens the dashboard; `pharmacies.html#review` (the dashboard's **Registration details and review →**) comes back here |
| Dashboards | See [Pharmacy and supplier dashboards](#pharmacy-and-supplier-dashboards-pharmacy-dashboardhtml-supplier-dashboardhtml) |

The supplier page uses the same steps and endpoints, with `type: "supplier"` and a depot (warehouse) instead of a branch.

### Pharmacy and supplier dashboards (`pharmacy-dashboard.html`, `supplier-dashboard.html`)

Both pages share `js/dashboard.js` (`<body data-role>` picks the role), `js/dashboard-data.js` (the data layer), `js/dashboard-i18n.js` (English, French, Kinyarwanda), `js/dashboard-forecast.js`, `js/theme.js` (light/dark) and `css/dashboard.css`. The design comes from the `feature/dashboards-and-registration` branch.

- **Who sees which:** after sign-in, registration (`js/registration.js`) opens `pharmacy-dashboard.html` for a pharmacy membership and `supplier-dashboard.html` for a supplier one. The dashboard loads the organization chosen for the tab (`sessionStorage`: `apexrx_selected_pharmacy` / `apexrx_selected_supplier`), otherwise the one the user owns, manages, or any. Only memberships returned by `GET /auth/me` are used, and every request is authorized by the backend, so changing a stored id opens nothing.
- **Several organizations:** an **Organization** selector in the top bar lists all the user's memberships (pharmacies and suppliers). Choosing one remembers it for the tab and opens the matching dashboard.
- **Not signed in:** the page goes to `pharmacies.html#signin` / `suppliers.html#signin`. Sign-out, inactivity and other-tab sign-out return there too, with the reason.
- **Preview:** `?preview=1` (**Just exploring?** on both registration pages) shows sample data from `DashData.preview()`, held in the browser only. A strip says "Preview with sample data. Nothing you do here is saved or sent to anyone", and every confirmation adds "(Preview: nothing was saved or sent.)". The preview never creates invitation links.

| Section | Pharmacy | Supplier | Endpoints |
|---|---|---|---|
| Top bar | Organization, branch selector, verification status, user and role, language, theme, Sign out | Same, with depots | `GET /auth/me`, `GET /organizations/{id}`, `GET /organizations/{id}/locations?include_inactive=true` |
| Overview | Greeting, counts (offers waiting, running low, listed), what needs attention, recent supplier conversations. Owners and managers also: stock health per branch | What needs attention, recent pharmacy conversations. Owners and managers also: order pipeline (new, offers sent, to prepare, dispatched, delivered), open order value, most requested medicines | `GET /purchase-orders?organization_id=`, `GET /organizations/{id}/inventory?location_id=`; charts: `GET /organizations/{id}/insights?location_id=` (owners and managers) |
| Compare prices | Supplier offers by medicine or category, best price, distance from the branch, **Ask for quote**, **Message** | — | `GET /catalogue/drugs`, `GET /supplier-offers` (approved pharmacies only), `POST /purchase-orders`, `POST /purchase-orders/{id}/submit` |
| Messages / Requests and chat | Each supplier's orders as a conversation; **Write an order list** (one line per item); **Send on WhatsApp** opens WhatsApp | Each pharmacy's requests as a conversation; offers and status changes | Orders as above; WhatsApp links (no in-app messaging) |
| Supplier orders / Orders | Status, totals, items; the buttons the order's `allowed_actions` allow (send, accept offer, cancel with a reason, mark delivered, delete draft) | Accept as requested, **Write offer** (counter), decline, start preparing, dispatch, cancel | `POST /purchase-orders/{id}/{action}`, `DELETE /purchase-orders/{id}` |
| My stock / My catalogue | Per branch: quantity (any member), price, low-stock alert and listing (owners, managers), add a medicine, CSV import, confirm all, remove | Same, per depot | `GET /organizations/{id}/inventory`, `PUT .../stock/{product}`, `PUT/DELETE .../stock/{product}/offer`, `DELETE .../stock/{product}`, `POST .../stock/confirm`, `GET /catalogue/products` |
| Patient orders | "Patient ordering is coming soon" | — | None |
| Forecasting / Demand forecast | Example charts, labelled "Example data". Owners and managers only | Same | None |
| Branches and team / Depots and team | Profile; branches (add, edit, deactivate, reactivate); team (role, deactivate, remove); invitations (create link, New link/Resend, Revoke); documents (list, upload); **Registration details and review →** | Same | `GET/POST/PATCH /organizations/{id}/locations`, `GET/PATCH/DELETE /organizations/{id}/members`, `GET/POST /organizations/{id}/invitations`, `.../resend`, `.../revoke`, `GET/POST /organizations/{id}/documents` |

Owners manage everyone else; managers manage staff only; staff update quantities and prepare orders.

**Charts and analytics are for owners and managers only.** Staff do not see the overview charts (stock health, order pipeline, open order value, most requested medicines), Forecasting, or the Premium cards, and the layout closes up around them. The figures come from `GET /organizations/{id}/insights`, which refuses staff with 403, so hiding them in the page is not the only protection. Staff keep their stock, order and message screens. A quote request made by staff is saved as a **draft** and the dashboard says it was not sent (the backend lets only owners and managers submit). Buttons follow the role, and the backend enforces every rule.

**Not connected yet (no backend support), shown as such:**
- **Batch numbers and expiry dates.** The API has no stock batches. Their fields stay in the layout but are disabled and labelled "Not connected yet"; CSV import ignores those columns; the shelf-life panel and supplier expiry counts say tracking is not connected instead of showing zero.
- **Patient orders.** Patients can find listed stock but cannot order in the app.
- **Forecasting.** Example data only.
- **Plans and payments.** The card says "Not live yet. ApexRX takes no payments and has no paid plans yet."
- **In-app chat.** Conversations are built from orders; messages go through WhatsApp.

### Admin dashboard (`ops-console-7f3k9q.html`)

| Control | Endpoint |
|---|---|
| Sign in | `POST /auth/login`, then `GET /auth/me`. Refused unless `is_platform_admin` |
| Overview counts | `GET /admin/organizations/counts` (all seven numbers in one request) |
| Tabs | Overview, Organizations, Documents, Users, Catalogue, Search insights. The current tab is in the URL hash. `js/admin.js` (sign-in, tabs, organizations) and `js/admin-console.js` (the other sections) |
| **Overview** cards | The `total` of `GET /admin/organizations`, `/admin/documents?status=pending`, `/admin/users` (and `?is_platform_admin=true`), `/catalogue/drugs`, `/catalogue/products` (and `?include_inactive=true`), each with `limit=1`. Plus `GET /admin/insights/searches?days=30&limit=5` (and `&only_unmet=true`) |
| Organization counts | `GET /admin/organizations?limit=1` with each `type` / `status` filter, using its `total` |
| Organization table, filters, search, pages | `GET /admin/organizations?type=&status=&q=&limit=&offset=` |
| **Open** | `GET /admin/organizations/{id}`: profile, locations, members and documents |
| Detail: stock and orders (read only) | `GET /organizations/{id}/inventory`, `GET .../locations/{loc}/stock/{product}/adjustments` (**History**), `GET /purchase-orders?organization_id=` |
| **Approve** / **Reject** / **Suspend** | `POST /admin/organizations/{id}/review` (notes required to reject or suspend) |
| Document **Download** | `GET /admin/documents/{id}/download`: streamed by the backend from the private bucket |
| **Approve document** / **Reject document** | `POST /admin/documents/{id}/review` (a reason is required to reject) |
| **Documents** queue, status filter, pages | `GET /admin/documents?status=pending\|approved\|rejected`. Download and review as above. **Open organization** shows its detail |
| **Users** list, search, admin filter, pages | `GET /admin/users?q=&is_platform_admin=` |
| **Deactivate** / **Reactivate**, **Make admin** / **Remove admin** | `PATCH /admin/users/{id}` with `is_active` / `is_platform_admin`, after a confirmation. Not shown on your own row |
| **Drugs** list, search, pages | `GET /catalogue/drugs?q=` |
| **Add drug** / **Edit** | `POST /catalogue/drugs`, `PATCH /catalogue/drugs/{id}` (only the changed fields). A 409 duplicate is shown on the form |
| **View products** (of a drug) | `GET /catalogue/products?drug_id=` |
| **Products** list, search, include retired, pages | `GET /catalogue/products?q=&drug_id=&include_inactive=` |
| **Add product** / **Edit** | `POST /catalogue/products`, `PATCH /catalogue/products/{id}` (only the changed fields; a cleared field is sent as `null`). The drug is chosen from `GET /catalogue/drugs?q=`. A 409 duplicate or barcode is shown on the form |
| **Retire** / **Reactivate** | `PATCH /catalogue/products/{id}` with `is_active`, after a confirmation |
| **Search insights** | `GET /admin/insights/searches?days=&limit=&only_unmet=`. **Check catalogue** searches the products list for that text |
| **Sign out**, expired token | Clears the session and shows the sign-in screen |

## Not connected yet (no backend support in the v6 data model)

- **No plan or payment:** registration has no subscription or payment step. The dashboards' plan card says plans and payments are not live yet, with no price, and the top bar shows the real verification status.
- **Licence numbers (pharmacy license, NPC, TIN, Rwanda FDA):** there are no columns for them and the requirements are not confirmed, so the form does not ask for them (the old "License number" field, which was never saved, was removed). The uploaded documents are what ApexRX reviews.
- **Rwandan places:** `data/rwanda-locations.json` (5 provinces, 30 districts, 416 sectors, 2,149 cells, 14,837 villages) is from the MIT-licensed `rwanda-geo-data` package (see `data/README-rwanda-locations.txt`). Check it against official NISR/MINALOC data before a real launch. If it cannot load, the form falls back to typed names.
- **Account holder's name:** the account form has no name field, so registration uses the part of the email before `@`. It can be changed later with `PATCH /auth/me`.
- **Chat:** there is no in-app messaging. Dashboard conversations are built from purchase orders, and messages open WhatsApp (or the phone), as the roles document describes.
- **Stock batches and expiry dates:** the API stores one quantity per product and branch. The dashboards' batch and expiry fields are disabled and labelled "Not connected yet".
- **Homepage map pins and headline numbers:** illustrative content, unchanged. No public endpoint lists every pharmacy or returns platform totals.
- **Map services on search.html:** free OpenStreetMap community services, with usage policies and no guaranteed availability: tiles (light use, attribution required), FOSSGIS routing (fair use) and Nominatim (at most one request per second; the page searches only when the patient presses Find). Heavy traffic will need a hosted tile/routing provider, which may cost money.
- **Patient orders and forecasting:** not in the API. The pharmacy dashboard says patient ordering is coming soon; forecasting shows example data, labelled as such.
- **Supplier documents:** suppliers are asked for a business license and an owner ID, the generic types the admin console already knows. The project's roles document says the exact supplier document requirements are still to be confirmed. The backend accepts any document type, so adding types later is a frontend change only.
- **Translations:** the About and Legal page bodies are English only (their header and footer are translated). The Kinyarwanda strings on the registration pages (including the email verification ones) should be reviewed by a native speaker.
- **Translations:** the dashboards are in English, French and Kinyarwanda (`js/dashboard-i18n.js`); the Kinyarwanda strings should be reviewed by a native speaker.
