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
| `index.html` | Landing page: medicine search (`#hero-search`), the numbers and the call to action |
| `how-it-works.html` | "Built for everyone in the medicine chain" and "How it works", moved from the landing page |
| `about.html` | About ApexRX_Smart, Our Mission, Our Vision, Our Team and Our Organization. Placeholder copy (Lorem ipsum, "Team member name") to replace; see the comment at the top of the file |
| `legal.html#privacy`, `#terms`, `#cookies` | One layout for the legal pages (`js/legal.js` shows the one in the address). Clearly marked placeholders, not approved policies |
| `pharmacies.html` | Pharmacy registration and sign-in (`js/registration.js`), then the pharmacy workspace (`js/pharmacies.js`, `js/workspace.js`) |
| `suppliers.html` | Supplier registration and sign-in (`js/registration.js`, the same journey with `<body data-role="supplier">`) |
| `verify-email.html` | Opened from the verification email; sends the link's token to `POST /auth/email/verify` (`js/verify-email.js`) |
| `accept-invitation.html` | Opened from a staff invitation: set up your own account, or sign in, and join (`js/accept-invitation.js`) |
| `reset-password.html` | "Forgot password?": says it is temporarily unavailable while email is disabled (`GET /auth/capabilities`); the reset form works again once email returns (`js/reset-password.js`) |
| `admin.html` | Admin console (staff only) |

- **Shared header and footer:** `js/site-layout.js` provides them for `index.html`, `how-it-works.html`, `about.html` and `legal.html`, so the navigation is defined once.
  - Each page includes it twice: `data-part="header"` and `data-part="footer"`. It renders in place, before `js/script.js`.
  - `<body data-page="…">` marks the current page.
  - `js/script.js` adds the translations, the mobile menu, and the **Sign in** / **Get started** buttons on every one of these pages.
- **Main navigation:** For Pharmacies, For Suppliers, How it works, About. **For Patients** is not in the main navigation: patients use the search on the landing page.
- **Footer links:**
  - Product: For Patients goes to `index.html#hero-search` (`#hero-search` on the landing page itself). The others go to the registration pages and How it works.
  - Company: all four links go to `about.html` for now.
  - Legal: the three legal pages.
  - Admin Portal: bottom left, next to the copyright.
- **Show/hide password:** `js/password-toggle.js` adds an eye button to every password field on `pharmacies.html`, `suppliers.html` and `admin.html`.
  - It has a "Show password" / "Hide password" label (English, French, Kinyarwanda) and `aria-pressed`, and works from the keyboard.
  - Fields go back to hidden when their form is submitted.
- **Sign in or create account:** both registration pages have an "Already have an account? Sign in" switch on their first step, and `#signin` opens it directly; the homepage **Sign in** button uses `pharmacies.html#signin`.
  - Sign-in mode asks only for email and password, and calls `POST /auth/login`.
  - A supplier-only account signing in on the pharmacy page is pointed to `suppliers.html`, instead of being asked to register a pharmacy (and the other way round). An ApexRX administrator is told to sign out instead.
  - A session already in the tab (a refresh, another ApexRX page, the admin portal) is continued, and the page always says which account it is: "Signed in as … · Sign out".

## How the pages use the API

All requests go through `js/api.js` (`window.ApexAPI`). It covers every backend endpoint. The pharmacy workspace sections live in `js/workspace.js`. It turns error responses into `ApiError` objects with a readable `message`. It keeps the access token in `sessionStorage`, so the token is cleared when the tab closes.

| Page / control | Endpoint |
|---|---|
| Homepage medicine search | `GET /search/pharmacies?q=`: availability status, price, location and freshness. Never exact quantities. |
| Homepage **Sign in** / **Get started** | Open `pharmacies.html#signin` / `pharmacies.html` |
| Pharmacy page: *Register a pharmacy* / *Staff sign-in* tabs (`#staff`, `#signin`) | Staff sign-in is `POST /auth/login` with the person's own account, then `GET /auth/me`. Several pharmacies: a chooser, then the workspace. **Forgot password?** opens `reset-password.html` |
| Workspace **Sign out** (top bar and sidebar), public header **Sign out** | `POST /auth/logout`: ends this session only |
| Session activity, inactivity warning, other tabs | `js/api.js`: `POST /auth/session/activity` on real user activity; see the root README, "Sessions" |
| Employees → Invite an employee (email disabled: **Create invitation link** shows the link once, with **Copy link**), invitation list (New link / Resend, Revoke) | `POST/GET /organizations/{id}/invitations`, `.../{inv}/resend`, `.../{inv}/revoke` (owners and managers) |
| Registration step 1, Account (both pages) | **Create account:** `POST /auth/register`, then `POST /auth/login` (an email that already has an account signs in). **Sign in:** `POST /auth/login` only. Then everything below is decided from `GET /auth/me`, `GET /auth/email/status` and the organization's records, so an incomplete registration resumes where it stopped |
| Step 2, Verify email | `GET /auth/email/status`; `POST /auth/email/send {next}` sends the link (automatically the first time). **I've verified my email** re-checks the status; the page also re-checks when it regains focus and when `verify-email.html` reports success in the same browser. **Resend** counts down `resend_after` |
| `verify-email.html` | `POST /auth/email/verify {token}` (no session). Messages for verified, already verified, invalid, expired, used and superseded links |
| Step 3, Details | `POST /organizations` (`type` from the page's `data-role`; 403 `email_unverified` brings the user back to step 2), then `POST /organizations/{id}/locations` with `name`, `region` (province), `city` (district), `sector`, `cell`, `village`, `address` (street or landmark), `phone`, `whatsapp_phone`, `latitude`/`longitude` (optional; "Use my current location", checked against Rwanda's bounds). Coming back updates the same records with `PATCH`. Province to village come from `data/rwanda-locations.json` |
| Step 4, Documents | `POST /organizations/{id}/documents` per selected file. Pharmacies: pharmacy license, business license, owner ID. Suppliers: business license, owner ID |
| Step 5, Review | `GET /organizations/{id}`, `/locations`, `/documents`: status, review note, stored details, document statuses and reasons. Owners and managers can **Edit details** and **Add a document**; owners can **Resubmit for review** after a rejection (`POST /organizations/{id}/resubmit`). Pharmacies: **Open your workspace** |
| Workspace name, avatar and profile | `GET /auth/me`, `GET /organizations/{id}`, `GET /organizations/{id}/locations` |
| Workspace profile: documents | `GET /organizations/{id}/documents`: each document's review status |
| Overview card count, **Overview** and **Supplier chat** lists | `GET /purchase-orders?organization_id=`: one row per supplier you have ordered from, with the latest order's number, status, total and item count. Typing filters by supplier name, then adds matching supplier stock. |
| **Find a source** and supplier search | `GET /supplier-offers`: approved pharmacies only, with exact supplier stock. A medicine name is required. |
| **Open chat** on any supplier row | Opens the supplier's WhatsApp with a prefilled message, or calls their phone |
| "Sample data" badge and workspace note | Switch to "Live data" and a live note when signed in |
| Page refresh | Resumes the signed-in session from `sessionStorage` (shown as "Signed in as …") |
| **Restart demo** | Signs out |
| Status card, **Registration and documents** (profile) | The organization's status; opens the registration review |

**Just exploring?** still opens the workspace with sample data and no account.

The supplier page uses the same steps and endpoints, with `type: "supplier"`, a warehouse instead of a branch, and no workspace yet (suppliers stay on the review).

### Pharmacy workspace sections (`js/workspace.js`)

| Section / control | Endpoint | Who |
|---|---|---|
| Organization selector (users in several pharmacies) | `GET /auth/me` memberships. The choice is kept for the tab | Everyone |
| Overview | `GET /organizations/{id}`, `/locations`, `/members`, `GET /purchase-orders?organization_id=` | Everyone |
| Branches: list | `GET /organizations/{id}/locations?include_inactive=true` | Everyone |
| Branches: add, edit, deactivate/reactivate | `POST` / `PATCH /organizations/{id}/locations[/{loc}]` (`is_active`) | Owners, managers |
| Employees: list | `GET /organizations/{id}/members` | Everyone |
| Employees: invite (email + role, no account needed), resend, revoke | `POST /organizations/{id}/invitations`, `.../{inv}/resend`, `.../{inv}/revoke`, `GET .../invitations` | Owners (any role); managers (staff only) |
| Employees: change role, deactivate, remove | `PATCH` / `DELETE /organizations/{id}/members[/{m}]` | Owners (everyone); managers (staff only) |
| Inventory: branch selector, list | `GET /organizations/{id}/inventory?location_id=` | Everyone |
| Inventory: set quantity, add a catalogue medicine | `PUT .../locations/{loc}/stock/{product}`, `GET /catalogue/products` | Everyone (approved pharmacies) |
| Inventory: price and listing | `PUT .../stock/{product}/offer` | Owners, managers |
| Orders: list, open, history | `GET /purchase-orders?organization_id=`, `GET /purchase-orders/{id}` | Everyone |
| Orders: new draft (receiving branch, supplier stock search, lines, optional warehouse) | `GET /supplier-offers`, `POST /purchase-orders` | Everyone (approved pharmacies) |
| Orders: edit draft lines, delete draft | `PATCH` / `DELETE /purchase-orders/{id}/items/{item}`, `DELETE /purchase-orders/{id}` | Everyone |
| Orders: submit, cancel (with a reason), accept counteroffer, mark delivered | `POST /purchase-orders/{id}/{action}`. Buttons come from the order's `allowed_actions` | Submit, cancel and accept counteroffer: owners and managers only (enforced by the backend) |
| Joining an existing pharmacy | `GET /auth/me` ("Check again") | A registered user with no pharmacy |

### Admin dashboard (`admin.html`)

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

- **No plan or payment:** registration has no subscription or payment step, and the workspace shows the real verification status instead of a plan.
- **Licence numbers (pharmacy license, NPC, TIN, Rwanda FDA):** there are no columns for them and the requirements are not confirmed, so the form does not ask for them (the old "License number" field, which was never saved, was removed). The uploaded documents are what ApexRX reviews.
- **Rwandan places:** `data/rwanda-locations.json` (5 provinces, 30 districts, 416 sectors, 2,149 cells, 14,837 villages) is from the MIT-licensed `rwanda-geo-data` package (see `data/README-rwanda-locations.txt`). Check it against official NISR/MINALOC data before a real launch. If it cannot load, the form falls back to typed names.
- **Account holder's name:** the account form has no name field, so registration uses the part of the email before `@`. It can be changed later with `PATCH /auth/me`.
- **Supplier chat:** messages in the sample chat dialog stay in the browser. Live suppliers are contacted on WhatsApp or by phone, as the roles document describes.
- **Homepage map pins and headline numbers:** illustrative content, unchanged. No public endpoint lists every pharmacy or returns platform totals.
- **Supplier search by supplier name:** `/supplier-offers` searches by medicine. Supplier names are matched only among suppliers you have already ordered from.
- **Supplier workspace:** suppliers can register and follow their verification on `suppliers.html`. There are no screens for stock, prices or incoming orders yet; suppliers use the API for those.
- **Supplier documents:** suppliers are asked for a business license and an owner ID, the generic types the admin console already knows. The project's roles document says the exact supplier document requirements are still to be confirmed. The backend accepts any document type, so adding types later is a frontend change only.
- **Translations:** the About and Legal page bodies are English only (their header and footer are translated). The Kinyarwanda strings on the registration pages (including the email verification ones) should be reviewed by a native speaker.
- **Translations:** the new workspace sections are in English only (French and Kinyarwanda fall back to English).
