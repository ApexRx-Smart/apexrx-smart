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

## How the pages use the API

All requests go through `js/api.js` (`window.ApexAPI`). It covers every backend endpoint, including inventory and purchase orders, which have no screens yet. It turns error responses into `ApiError` objects with a readable `message`. It keeps the access token in `sessionStorage`, so the token is cleared when the tab closes.

| Page / control | Endpoint |
|---|---|
| Homepage medicine search | `GET /search/pharmacies?q=`: availability status, price, location and freshness. Never exact quantities. |
| Homepage **Sign in** / **Get started** | Open `pharmacies.html` |
| Pharmacies step 1, Account | `POST /auth/register`, then `POST /auth/login`. If the email already has an account, the same form signs in. |
| Pharmacies step 2, Verify | `GET /auth/phone/status`, then `POST /auth/phone/send-code` and `POST /auth/phone/verify`. The step is skipped when the number is already verified or the backend doesn't require it. **Resend code** counts down `resend_after` |
| Pharmacies step 3, Profile | `POST /organizations` (type `pharmacy`). The phone field is filled with the verified number, read-only, and the backend enforces it, `POST /organizations/{id}/locations`, `POST /organizations/{id}/documents` for each selected file. Coming back to this step updates the same records with `PATCH`. |
| Workspace name, avatar and profile | `GET /auth/me`, `GET /organizations/{id}`, `GET /organizations/{id}/locations` |
| Workspace profile: documents | `GET /organizations/{id}/documents`: each document's review status |
| Overview card count, **Overview** and **Supplier chat** lists | `GET /purchase-orders?organization_id=`: one row per supplier you have ordered from, with the latest order's number, status, total and item count. Typing filters by supplier name, then adds matching supplier stock. |
| **Find a source** and supplier search | `GET /supplier-offers`: approved pharmacies only, with exact supplier stock. A medicine name is required. |
| **Open chat** on any supplier row | Opens the supplier's WhatsApp with a prefilled message, or calls their phone |
| "Sample data" badge and workspace note | Switch to "Live data" and a live note when signed in |
| Page refresh | Resumes the signed-in session from `sessionStorage` |
| **Restart demo** | Signs out |

**Just exploring?** still opens the workspace with sample data and no account.

### Admin dashboard (`admin.html`)

| Control | Endpoint |
|---|---|
| Sign in | `POST /auth/login`, then `GET /auth/me`. Refused unless `is_platform_admin` |
| Overview counts | `GET /admin/organizations?limit=1` with each `type` / `status` filter, using its `total` |
| Organization table, filters, search, pages | `GET /admin/organizations?type=&status=&q=&limit=&offset=` |
| **Open** | `GET /admin/organizations/{id}`: profile, locations, members and documents |
| **Approve** / **Reject** / **Suspend** | `POST /admin/organizations/{id}/review` (notes required to reject or suspend) |
| Document **Download** | `GET /admin/documents/{id}/download`: streamed by the backend from the private bucket |
| **Approve document** / **Reject document** | `POST /admin/documents/{id}/review` (a reason is required to reject) |
| **Sign out**, expired token | Clears the session and shows the sign-in screen |

## Not connected yet (no backend support in the v6 data model)

- **Plan and payment (step 4):** still simulated. There is no subscription data.
- **License number:** there is no column for it. It is shown on the workspace profile for this session only. The uploaded license documents are what ApexRX reviews.
- **Account holder's name:** the account form has no name field, so registration uses the part of the email before `@`. It can be changed later with `PATCH /auth/me`.
- **Supplier chat:** messages in the sample chat dialog stay in the browser. Live suppliers are contacted on WhatsApp or by phone, as the roles document describes.
- **Homepage map pins and headline numbers:** illustrative content, unchanged. No public endpoint lists every pharmacy or returns platform totals.
- **Supplier search by supplier name:** `/supplier-offers` searches by medicine. Supplier names are matched only among suppliers you have already ordered from.
- **Inventory and purchase order screens:** `js/api.js` has the calls, but there are no screens for them yet.
