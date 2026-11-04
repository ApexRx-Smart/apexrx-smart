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

The API address comes from `js/config.js`. It is empty in the repository, so local development uses `http://127.0.0.1:8000`.

## Deploy on Netlify

`netlify.toml` at the repository root has the settings. There is no build: the deploy step only writes `js/config.js`.

1. In Netlify, choose **Add new site → Import an existing project** and pick this repository and the `main` branch. Leave the build settings at their defaults, because `netlify.toml` provides them.
2. Under **Site configuration → Environment variables**, set `APEXRX_API_BASE` to the backend URL, for example `https://apexrx-api.onrender.com`. If it is missing or not an `https` URL, the deploy fails on purpose.
3. Deploy. Then, in the Render backend's environment, set `CORS_ORIGINS` to the Netlify site URL, for example `https://apexrx-smart.netlify.app`, and redeploy the backend.

A free Render instance sleeps when idle and takes about 50 seconds to wake. The first request after a quiet period is slow; the client waits up to 70 seconds.

## How the pages use the API

All requests go through `js/api.js` (`window.ApexAPI`). It covers every backend endpoint, including inventory, purchase orders and admin, which have no screens yet. It turns error responses into `ApiError` objects with a readable `message`. It keeps the access token in `sessionStorage`, so the token is cleared when the tab closes.

| Page / control | Endpoint |
|---|---|
| Homepage medicine search | `GET /search/pharmacies?q=`: availability status, price, location and freshness. Never exact quantities. |
| Homepage **Sign in** / **Get started** | Open `pharmacies.html` |
| Pharmacies step 1, Account | `POST /auth/register`, then `POST /auth/login`. If the email already has an account, the same form signs in. |
| Pharmacies step 3, Profile | `POST /organizations` (type `pharmacy`), `POST /organizations/{id}/locations`, `POST /organizations/{id}/documents` for each selected file. Coming back to this step updates the same records with `PATCH`. |
| Workspace name, avatar and profile | `GET /auth/me`, `GET /organizations/{id}`, `GET /organizations/{id}/locations` |
| Workspace profile: documents | `GET /organizations/{id}/documents`: each document's review status |
| Overview card count, **Overview** and **Supplier chat** lists | `GET /purchase-orders?organization_id=`: one row per supplier you have ordered from, with the latest order's number, status, total and item count. Typing filters by supplier name, then adds matching supplier stock. |
| **Find a source** and supplier search | `GET /supplier-offers`: approved pharmacies only, with exact supplier stock. A medicine name is required. |
| **Open chat** on any supplier row | Opens the supplier's WhatsApp with a prefilled message, or calls their phone |
| "Sample data" badge and workspace note | Switch to "Live data" and a live note when signed in |
| Page refresh | Resumes the signed-in session from `sessionStorage` |
| **Restart demo** | Signs out |

**Just exploring?** still opens the workspace with sample data and no account.

## Not connected yet (no backend support in the v6 data model)

- **Email verification (step 2):** the demo code `472916` is still checked in the browser.
- **Plan and payment (step 4):** still simulated. There is no subscription data.
- **License number:** there is no column for it. It is shown on the workspace profile for this session only. The uploaded license documents are what ApexRX reviews.
- **Account holder's name:** the account form has no name field, so registration uses the part of the email before `@`. It can be changed later with `PATCH /auth/me`.
- **Supplier chat:** messages in the sample chat dialog stay in the browser. Live suppliers are contacted on WhatsApp or by phone, as the roles document describes.
- **Homepage map pins and headline numbers:** illustrative content, unchanged. No public endpoint lists every pharmacy or returns platform totals.
- **Supplier search by supplier name:** `/supplier-offers` searches by medicine. Supplier names are matched only among suppliers you have already ordered from.
- **Inventory, purchase order screens and admin review:** `js/api.js` has the calls, but these pages have no screens for them yet.
