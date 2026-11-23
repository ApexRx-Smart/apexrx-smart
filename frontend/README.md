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
| `search.html` | Expanded patient search, from the homepage's **See more**: price range, location (current position, a typed place or a tap on the map), distance, sorting, then the selected pharmacy beside a map with the route and directions (`js/patient-search.js`). The searched medicine shows **Reserve this medicine** when it can be reserved at that branch, otherwise the reason |
| `reservations.html` | Patient reservations (`js/reservations.js`, `css/reservations.css`): sign in or create an account, reserve one medicine at one branch, follow updates, see each reservation's details and history, cancel. Linked from the footer (**My reservations**). `noindex` |
| `how-it-works.html` | "Built for everyone in the medicine chain" and "How it works", moved from the landing page |
| `about.html` | About ApexRX_Smart, Our Mission, Our Vision, Our Team and Our Organization. Placeholder copy (Lorem ipsum, "Team member name") to replace; see the comment at the top of the file |
| `legal.html#privacy`, `#terms`, `#cookies` | One layout for the legal pages (`js/legal.js` shows the one in the address). Clearly marked placeholders, not approved policies |
| `pharmacies.html` | Pharmacy registration and sign-in (`js/registration.js`), then `pharmacy-dashboard.html` |
| `suppliers.html` | Supplier registration and sign-in (`js/registration.js`, the same journey with `<body data-role="supplier">`), then `supplier-dashboard.html` |
| `pharmacy-dashboard.html`, `supplier-dashboard.html` | The dashboards (`js/dashboard.js`); see below. `?preview=1` shows sample data |
| `verify-email.html` | Opened from the verification email; sends the link's token to `POST /auth/email/verify` (`js/verify-email.js`) |
| `verify-phone.html` | Mobile number verification by SMS code (`js/verify-phone.js`): `GET /auth/phone`, `POST /auth/phone/send`, `POST /auth/phone/verify {challenge_id, code}`, **Change number** (`PATCH /auth/me`), resend countdown, then back to `?next=` (a page of this site only). `js/api.js` opens it whenever the server answers 403 `phone_verification_required`; the server, not the page, enforces it. The account menu offers it to unverified accounts when SMS works |
| `accept-invitation.html` | Opened from a staff invitation: set up your own account, or sign in, and join (`js/accept-invitation.js`) |
| `reset-password.html` | "Forgot password?": says it is temporarily unavailable while email is disabled (`GET /auth/capabilities`); the reset form works again once email returns (`js/reset-password.js`) |
| `ops-console-7f3k9q.html` | Admin console (staff only). Not linked from any public page; open the URL directly |

- **Shared header and footer:** `js/site-layout.js` provides them for `index.html`, `how-it-works.html`, `about.html` and `legal.html`, so the navigation is defined once.
  - Each page includes it twice: `data-part="header"` and `data-part="footer"`. It renders in place, before `js/script.js`.
  - `<body data-page="…">` marks the current page.
  - `js/script.js` adds the translations and the mobile menu on every one of these pages (no Sign in / Get started: see "Entry points per group").
- **Main navigation:** For Pharmacies, For Suppliers, How it works, About. **For Patients** is not in the main navigation: patients use the search on the landing page.
- **Footer links:**
  - Product: For Patients goes to `index.html#hero-search` (`#hero-search` on the landing page itself). The others go to the registration pages and How it works.
  - Company: all four links go to `about.html` for now.
  - Legal: the three legal pages.
  - There is no admin link: the admin console is never linked from the public site.
- **Show/hide password:** `js/password-toggle.js` adds an eye button to every password field on `pharmacies.html`, `pharmacy-sign-in.html`, `suppliers.html` and `ops-console-7f3k9q.html`.
  - It has a "Show password" / "Hide password" label (English, French, Kinyarwanda) and `aria-pressed`, and works from the keyboard.
  - Fields go back to hidden when their form is submitted.
- **Entry points per group:** the public header has **For Patients** (`patient-register.html`), **For Pharmacies** (`pharmacies.html`) and **For Suppliers** (`suppliers.html`): each group's registration page, whose "Already have an account? Sign in" leads to that group's sign-in. There is no Sign in / Get started on the public site, and the public header never shows who is signed in (the same for every visitor). The footer has no "My reservations".
- **Pharmacy sign-in and registration are separate pages:** `pharmacy-sign-in.html` (`data-auth="signin"`) and `pharmacies.html` (`data-auth="create"`), both rendered by `js/registration.js`. Each links only to the other ("Sign in to your pharmacy →" / "Register your pharmacy →") and the sign-in page to **Forgot password?** (`reset-password.html?next=pharmacy`). Old links to `pharmacies.html#signin`, `#staff` and `#review` are redirected to the sign-in page. After sign-in an unfinished registration continues on the same page. Suppliers keep one page with an "Already have an account? Sign in" switch (`#signin`).
  - Sign-in asks only for email and password, and calls `POST /auth/login`.
  - **No cross-group links:** no auth page links to another group's sign-in or registration. An account of the other group signing in is told so ("registered as a medicine supplier, not a pharmacy", and the other way round) and offered the home page or sign-out. An ApexRX administrator is told to sign out instead.
  - Patients: `patient-register.html` ("Already have an account? Sign in") and `patient-sign-in.html` ("Don't have an account? Sign up", **Forgot password?** → `reset-password.html?next=patient`, whose "Back to sign in" returns to it), both on `js/patient-auth.js`. Registration asks for a mobile number (stored as +250…; it will be verified by SMS once a provider is chosen), signs the patient in and opens the reservations dashboard with a welcome message. The reserve form then shows that number ("Use another number" for a different one), so the patient does not type it again; sign-in opens the dashboard, or `?next=` when it is a `reservations.html` view on this site (only `location`, `product`, `ref` are kept; anything else, another site included, falls back to the dashboard). Already signed in as a patient: straight to the dashboard; a pharmacy, supplier or admin account is told it is not a patient account.
- **Same layout for every group's sign-in and registration:** the minimal header (brand, Back to website, language) and the story card, no floating public header (`css/pharmacies.css`). The show/hide password button (`js/password-toggle.js`) is on every password field: patients, pharmacies, suppliers, password reset, invitations and the admin console.
- **Account menu (`js/account-menu.js`):** every signed-in workspace (patient dashboard, pharmacy and supplier dashboards, admin console) has an initials avatar that opens a menu with the account's name and email (and organization and role for business accounts) and **Sign out**. It closes on Escape or a click outside and works from the keyboard. Signing out from anywhere ends the session on the server and opens `index.html`; an ended session (inactivity, another tab, expiry) goes to that group's sign-in with the reason instead.
  - A session already in the tab (a refresh, another ApexRX page, the admin portal) is continued, and the page always says which account it is: "Signed in as … · Sign out".

## How the pages use the API

All requests go through `js/api.js` (`window.ApexAPI`). It covers every backend endpoint. It turns error responses into `ApiError` objects with a readable `message`. It keeps the access token in `sessionStorage`, so the token is cleared when the tab closes.

| Page / control | Endpoint |
|---|---|
| Homepage medicine search | `GET /search/pharmacies?q=`: availability status, price, location and freshness. Never exact quantities. Each result is one link to that branch's page for that medicine (`search.html?q=&pharmacy=&product=`); the query is kept in the homepage address so Back shows the results again. **See more** opens `search.html?q=` |
| `search.html` results and filters | `GET /search/pharmacies?q=&min_price=&max_price=&lat=&lng=&radius_km=&sort=price\|price_desc\|distance\|freshness&record=false`. Filtering and sorting run on the server, so they combine and work on any number of results; pages of 30 with **Show more pharmacies**. `record=false` keeps refinements out of search insights (the homepage already counted the search). Branches without coordinates have no distance: they are listed last when sorting by distance and left out by a distance limit |
| `search.html` selected pharmacy | `GET /search/pharmacies/{location_id}`: details and every medicine it lists; `product=` selects the exact medicine that was clicked. One back arrow: back to the results it came from (history), or the results for the same search when opened directly. Two contact actions: **Call pharmacy** (`tel:`) and **Get directions** to the branch's coordinates (else its address): a `geo:` link on Android (the system opens the patient's maps app, with an OpenStreetMap page if nothing opens), Apple Maps on iPhone, iPad and Mac, OpenStreetMap in the browser elsewhere. The in-page map uses OpenStreetMap tiles; the route comes from FOSSGIS OSRM (car or foot); a typed place from Nominatim. Leaflet 1.9.4 is in `vendor/leaflet/`. If routing fails the map shows a labelled straight line |
| `search.html` **Reserve this medicine** | `GET /reservations/options?location_id=&product_id=` (public, no stock figures). Shown only when `reservable`; otherwise the reason (turned off, prescription-only, not set up at this pharmacy...). Opens `reservations.html?location=&product=` |
| `patient-sign-in.html` / `patient-register.html` | **Sign in:** `POST /auth/login`. **Create an account:** `POST /auth/register`, then `POST /auth/login`. No organization, no email-verification step: a patient account is a plain account. Signed out, every view shows this panel first and then continues where the patient was (only the public branch, product or reference ids are in the address) |
| `reservations.html?location=&product=` reserve form | `GET /reservations/options` + `GET /search/pharmacies/{location_id}` for the medicine, branch, unit, maximum and price; `GET /auth/me` pre-fills the phone. `POST /reservations` with the shown `unit_version` and a `client_request_id` kept (with the draft: quantity, phone, note) in `sessionStorage` until it succeeds, so a retry, a double click or a sign-in in the middle never creates a second reservation. Errors: `unit_changed` reloads the unit and asks the patient to review it; `not_reservable`, `quantity_above_limit`, `too_many_open_reservations`, `open_reservation_exists` (links the existing one), `idempotency_key_reused`, `phone_required`, `invalid_phone`, `rate_limited`, network failures |
| `reservations.html` list and updates | `GET /reservations?status=&limit=10&offset=` (status filter, pages); `GET /notifications` without an organization (the patient's own updates, linked by `reservation_reference`), `POST /notifications/read`. Opening a reservation marks its own updates read. The list or the open reservation refreshes quietly every 45 s (not while the tab is hidden, a request is running, a field has focus or the cancel form is open). Prices are labelled as the pharmacy's listed price at the time of the request, indicative and paid at the pharmacy |
| `reservations.html?ref=RX-…` | `GET /reservations/{reference}`: status in words and a symbol, what happens next, both deadlines, chronological history, the reasons given. **Cancel reservation** (when the API says `can_cancel`) asks first, then `POST /reservations/{reference}/cancel`; a 409 (collected or expired meanwhile) is explained and the reservation reloaded |
| `reservations.html` (patient dashboard) | Signed out: `patient-sign-in.html?next=<this view>`. Reservations list with the status filter, updates, details, cancellation; the reserve form for `?location=&product=` |
| `pharmacy-sign-in.html` (owners, managers and staff) | Sign-in is `POST /auth/login` with the person's own account, then `GET /auth/me`. Several pharmacies: a chooser, then the dashboard. **Forgot password?** opens `reset-password.html` |
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
- **Not signed in:** the page goes to `pharmacy-sign-in.html` / `suppliers.html#signin`. Sign-out, inactivity and other-tab sign-out return there too, with the reason.
- **Preview:** `?preview=1` (**Just exploring?** on both registration pages) shows sample data from `DashData.preview()`, held in the browser only. A strip says "Preview with sample data. Nothing you do here is saved or sent to anyone", and every confirmation adds "(Preview: nothing was saved or sent.)". The preview never creates invitation links.

| Section | Pharmacy | Supplier | Endpoints |
|---|---|---|---|
| Top bar | Organization, branch selector, verification status, user and role, language, theme, Sign out | Same, with depots | `GET /auth/me`, `GET /organizations/{id}`, `GET /organizations/{id}/locations?include_inactive=true` |
| Overview | Greeting, counts (offers waiting, running low, listed), what needs attention, recent supplier conversations. Owners and managers also: stock health per branch | What needs attention, recent pharmacy conversations. Owners and managers also: order pipeline (new, offers sent, to prepare, dispatched, delivered), open order value, most requested medicines | `GET /purchase-orders?organization_id=`, `GET /organizations/{id}/inventory?location_id=`; charts: `GET /organizations/{id}/insights?location_id=` (owners and managers) |
| Compare prices | Supplier offers by medicine or category, best price, distance from the branch, **Send order** (a purchase order at the listed price; quotations go through Procurement requests), **Message** | — | `GET /catalogue/drugs`, `GET /supplier-offers` (approved pharmacies only), `POST /purchase-orders`, `POST /purchase-orders/{id}/submit` |
| Messages | One conversation per supplier, stored in ApexRX: name, Supplier label, last message, time, unread count. Messages with the sender and time, plus the orders and procurement requests with that supplier. **Send** (Enter), **New conversation** (approved suppliers), **New request**, **Write an order list**. New messages arrive by polling (every 5 s while open) | Same with pharmacies; started from **New conversation**, an order's **Open chat** or a request's **Message** | `GET/POST /conversations`, `GET /conversations/contacts`, `GET/POST /conversations/{id}/messages`, `POST /conversations/{id}/read`, orders as above |
| Procurement requests | **New request**: supplier, branch, medicines from the catalogue or described in words, quantities, notes, needed-by date, review, send. Request detail: status, every quotation revision, **Ask for a revision**, **Accept quotation**, **Reject quotation**, **Create supplier order**, **Cancel request** (as `allowed_actions` allow) | Incoming requests; opening one marks it seen. Quotation form: can supply or not, boxes, price per box, line totals, note, ready in (days); **Save draft**, **Send quotation**, **Decline request**. Earlier revisions stay visible | `GET/POST /procurement-requests`, `GET /procurement-requests/{id}`, the action routes |
| Notifications (bell, top bar) | New requests, quotations, revision requests, answers, orders created from a quotation, new messages, reservation requests (and patient cancellations, unanswered requests) by reference; **Mark all as read**; a click opens the request, conversation or reservation | Same, without reservations | `GET /notifications`, `POST /notifications/read` |
| Supplier orders / Orders | Status, totals, items; the buttons the order's `allowed_actions` allow (send, accept offer, cancel with a reason, mark delivered, delete draft) | Accept as requested, **Write offer** (counter), decline, start preparing, dispatch, cancel | `POST /purchase-orders/{id}/{action}`, `DELETE /purchase-orders/{id}` |
| My stock / My catalogue | Per branch: quantity (any member), price, low-stock alert and listing (owners, managers), add a medicine, CSV import, confirm all, remove. Pharmacies: under each quantity, **Held · unallocated · reservable** and any shortfall, from the inventory API (re-read when the screen opens); a quantity edit or CSV row below what open reservations hold asks first and then sends `allow_below_reserved` (if reservations arrived meanwhile, the API's 409 `below_reserved` asks with its figure), and **Confirm all** says which items are short | Same, per depot | `GET /organizations/{id}/inventory`, `PUT .../stock/{product}`, `PUT/DELETE .../stock/{product}/offer`, `DELETE .../stock/{product}`, `POST .../stock/confirm`, `GET /catalogue/products` |
| Reservations (`js/dashboard-reservations.js`) | Patient reservations, every branch (memberships are organization-wide). Groups with counts: New requests, Awaiting collection, Collected, Declined, Cancelled, Expired; filters for branch, submitted dates and reference, sort by urgency or newest, pages of 20 (all on the server). Detail: request / confirmed commitment / closed, patient name and phone (phone only while open), medicine, quantity and unit, branch, the deadline that applies, history, the branch's stock against reservations, the collection record, and a **shortfall** warning that links to My stock. Actions as the API's `actions` allow: **Confirm** (any role; shows stock and warns when too little is free), **Decline** (reason), **Collect** (full quantity only; staff type the reference the patient shows, and a mismatch is refused by the API), **Cancel** (owners and managers, reason), **Physical-count override** (owners and managers, an exception: count, reason, the recorded quantity seen; refused if the record changed). **Reservation settings**: per branch, the minimum stock kept for walk-in customers (owners and managers edit it; staff see it) and each stocked medicine's recorded, held, unallocated, kept-back and reservable quantities, whether it is reservable there now and why not; catalogue settings read only. Suspended or not approved: read only. Opening or handling a reservation marks its notifications read; the list or open reservation refreshes quietly at most every 40 s through the dashboard's existing 20-second background poll (not while a dialog is open or a field has focus) | — | `GET /organizations/{id}/reservations` (also the counts, `limit=1`), `GET .../reservations/{reference}`, `POST .../{reference}/confirm\|decline\|cancel\|collect`, `GET .../locations/{loc}/reservation-medicines`, `PATCH .../locations/{loc}` (`reservation_min_stock`), `GET /catalogue/products/{id}/reservation-settings` |
| Forecasting / Demand forecast | Example charts, labelled "Example data". Owners and managers only | Same | None |
| Branches and team / Depots and team | Profile; branches (add, edit, deactivate, reactivate); team (role, deactivate, remove); invitations (create link, New link/Resend, Revoke); documents (list, upload); **Registration details and review →** | Same | `GET/POST/PATCH /organizations/{id}/locations`, `GET/PATCH/DELETE /organizations/{id}/members`, `GET/POST /organizations/{id}/invitations`, `.../resend`, `.../revoke`, `GET/POST /organizations/{id}/documents` |

Owners manage everyone else; managers manage staff only; staff update quantities and prepare orders.

**Charts and analytics are for owners and managers only.** Staff do not see the overview charts (stock health, order pipeline, open order value, most requested medicines), Forecasting, or the Premium cards, and the layout closes up around them. The figures come from `GET /organizations/{id}/insights`, which refuses staff with 403, so hiding them in the page is not the only protection. Staff keep their stock, order and message screens. A quote request made by staff is saved as a **draft** and the dashboard says it was not sent (the backend lets only owners and managers submit). Buttons follow the role, and the backend enforces every rule.

**Not connected yet (no backend support), shown as such:**
- **Batch numbers and expiry dates.** The API has no stock batches. Their fields stay in the layout but are disabled and labelled "Not connected yet"; CSV import ignores those columns; the shelf-life panel and supplier expiry counts say tracking is not connected instead of showing zero.
- **Forecasting.** Example data only.
- **Plans and payments.** The card says "Not live yet. ApexRX takes no payments and has no paid plans yet."

### Admin dashboard (`ops-console-7f3k9q.html`)

| Control | Endpoint |
|---|---|
| Sign in | `POST /auth/login`, then `GET /auth/me`. Refused unless `is_platform_admin` |
| Overview counts | `GET /admin/organizations/counts` (all seven numbers in one request) |
| Tabs | Overview, Organizations, Documents, Users, Catalogue, Medicines, Search insights. The current tab is in the URL hash. `js/admin.js` (sign-in, tabs, organizations) and `js/admin-console.js` (the other sections) |
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
| **Medicines** counts, list, filters, pages | `GET /catalogue/reservation-settings?q=&dispensing_class=&include_inactive=` (counts use `limit=1` and `total`; the Overview's "Medicines not classified for reservations" card opens this tab filtered) |
| **Classify** / **Edit** (medicine) | `PATCH /catalogue/products/{id}/reservation-settings` with only the changed fields (classification, stock unit, unit name, pack size, most per reservation). Non-prescription asks for a confirmation; the row then says whether patients can reserve it and why not |
| **Search insights** | `GET /admin/insights/searches?days=&limit=&only_unmet=`. **Check catalogue** searches the products list for that text |
| **Sign out**, expired token | Clears the session and shows the sign-in screen |

## Not connected yet (no backend support in the v6 data model)

- **No plan or payment:** registration has no subscription or payment step. The dashboards' plan card says plans and payments are not live yet, with no price, and the top bar shows the real verification status.
- **Licence numbers (pharmacy license, NPC, TIN, Rwanda FDA):** there are no columns for them and the requirements are not confirmed, so the form does not ask for them (the old "License number" field, which was never saved, was removed). The uploaded documents are what ApexRX reviews.
- **Rwandan places:** `data/rwanda-locations.json` (5 provinces, 30 districts, 416 sectors, 2,149 cells, 14,837 villages) is from the MIT-licensed `rwanda-geo-data` package (see `data/README-rwanda-locations.txt`). Check it against official NISR/MINALOC data before a real launch. If it cannot load, the form falls back to typed names.
- **Account holder's name:** the account form has no name field, so registration uses the part of the email before `@`. It can be changed later with `PATCH /auth/me`.
- **Chat:** messages are stored in ApexRX and delivered by polling (the open conversation every 5 seconds, lists and notifications every 20), so a new message can take a few seconds to appear. WhatsApp is no longer used for pharmacy-supplier messages; the branch WhatsApp number is still collected as a contact detail.
- **Stock batches and expiry dates:** the API stores one quantity per product and branch. The dashboards' batch and expiry fields are disabled and labelled "Not connected yet".
- **Homepage map:** the interactive Kigali map is restored (pins on the pharmacies drawn in the image, an animated network canvas, cards on hover, click and by themselves). Its cards name the area only: no pharmacy names or stock claims, because no data is behind the drawing. No public endpoint lists every pharmacy or returns platform totals.
- **Map services on search.html:** free OpenStreetMap community services, with usage policies and no guaranteed availability: tiles (light use, attribution required), FOSSGIS routing (fair use) and Nominatim (at most one request per second; the page searches only when the patient presses Find). Heavy traffic will need a hosted tile/routing provider, which may cost money.
- **Forecasting:** not in the API; it shows example data, labelled as such. (Patient orders were replaced by patient reservations.)
- **Supplier documents:** suppliers are asked for a business license and an owner ID, the generic types the admin console already knows. The project's roles document says the exact supplier document requirements are still to be confirmed. The backend accepts any document type, so adding types later is a frontend change only.
- **Translations:** the About and Legal page bodies are English only (their header and footer are translated). The Kinyarwanda strings on the registration pages (including the email verification ones) should be reviewed by a native speaker.
- **Translations:** the dashboards are in English, French and Kinyarwanda (`js/dashboard-i18n.js`); the Kinyarwanda strings should be reviewed by a native speaker.
- **Translations:** the reservation strings (`js/reservations-i18n.js`, merged into `js/script.js`'s tables) are in English, French and Kinyarwanda; the Kinyarwanda should be reviewed by a native speaker. Unit labels ("box", "tablet") come from the catalogue and are not translated.
- **Reservations:** only the searched medicine on `search.html` gets a Reserve button (one eligibility check per opened pharmacy, not one per listed medicine). Pharmacies work in the dashboard's **Reservations** screen. Its strings are in `js/dashboard-reservations-i18n.js` (the reservation "Expired" has its own key, because the dashboard's "Expired" means an expired medicine batch). Patients receive updates on `reservations.html` only (no SMS or email).
