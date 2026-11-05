# ApexRx-Smart

ApexRx-Smart is a medicine availability platform designed to help patients, healthcare professionals, pharmacies, and suppliers access information about medicine availability.

The project includes a static frontend, a FastAPI backend, and a PostgreSQL database schema. The backend implements the v6 data model and API for patients, pharmacies, suppliers and administrators. The frontend is connected to it: the homepage medicine search, pharmacy registration and sign-in, organization profile and document upload, supplier search and the pharmacy workspace all use the live API.

| Part | Hosted on (test deployment) |
|---|---|
| Frontend | Netlify (static, publish directory `frontend/`) |
| Backend | Render: https://apexrx-smart.onrender.com |
| Database | Neon (PostgreSQL) |

## Project Structure

```text
apexrx-smart/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── core/
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── scripts/
│   │   └── services/
│   ├── alembic/
│   ├── tests/
│   ├── requirements.txt
│   ├── requirements-dev.txt
│   └── alembic.ini
├── database/
│   └── db_implementation_script.sql
├── frontend/
│   ├── assets/
│   │   ├── images/
│   │   └── logos/
│   ├── css/
│   ├── js/
│   │   ├── config.js        # backend address (API_BASE_URL)
│   │   ├── api.js           # API client used by every page (window.ApexAPI)
│   │   ├── script.js        # homepage, including medicine search
│   │   ├── pharmacies.js    # pharmacy onboarding and workspace
│   │   ├── pharmacies-i18n.js
│   │   └── pharmacies-motion.js
│   ├── index.html
│   ├── pharmacies.html
│   └── README.md            # how each page and control maps to the API
├── apexrx_customer_bases_roles_and_functions.md   # business rules for the v6 model
├── PHARMACY-WORKFLOW.md
└── README.md
```

## Frontend

The frontend is a static website (HTML, CSS and vanilla JavaScript). No build step is required. It supports English, French and Kinyarwanda.

### Backend address

Every page loads `js/config.js` before `js/api.js`:

```js
window.APEX_CONFIG = {
    API_BASE_URL: "https://apexrx-smart.onrender.com"
};
```

`api.js` uses `window.APEX_CONFIG.API_BASE_URL`, and falls back to `http://127.0.0.1:8000` when it is not set. To work against a local backend, change the URL in `config.js` to `http://127.0.0.1:8000` and don't commit that change.

Whichever backend you use must list the frontend's address in its `CORS_ORIGINS` (see [Configure](#1-configure)).

### Run locally

From the repository root, run:

```bash
python -m http.server 5501 --directory frontend
```

Open the following pages in your browser:

- Home page: http://localhost:5501/
- Pharmacy workflow: http://localhost:5501/pharmacies.html

Stop the server with `Ctrl+C`. VS Code Live Server works too, on port 5501.

### What is connected to the API

[frontend/README.md](frontend/README.md) maps every page and control to its endpoint. In short:

- **Homepage search** calls `GET /search/pharmacies`. It shows availability, price, location and how fresh the data is, never exact quantities.
- **Pharmacy registration** (`pharmacies.html`) creates the account (`POST /auth/register`), signs in, creates the pharmacy organization and its location, and uploads the verification documents. An existing email signs in instead.
- **The pharmacy workspace** shows the signed-in pharmacy's profile and document review status. It lists suppliers from the pharmacy's purchase orders and searches supplier stock with `GET /supplier-offers`, which works only for approved pharmacies. **Open chat** opens the supplier's WhatsApp or phone.
- **Just exploring?** still opens the workspace with sample data and no account.

Still simulated in the browser, because the v6 data model has no support for them: the email verification code (`472916`), the plan and payment step, and in-app supplier chat. Inventory, purchase order and admin screens don't exist yet, but `js/api.js` already has the calls for them.

### Verify frontend changes

After making changes, check the following:

1. Open the home page and verify the Kigali map, logos, audience images, and animations.
2. Select English, French, and Kinyarwanda and verify that the language selection is applied.
3. Search for a medicine on the home page and check that results come back from the backend. An empty database returns no results: see [Test data](#test-data).
4. Open the pharmacy workflow and register with a new email and matching passwords (8 characters minimum). Enter the demonstration code `472916`, fill in the profile and upload the documents, then continue through the simulated payment step.
5. In the workspace, check the profile and document statuses. Sign in as an **approved** pharmacy to try supplier search.
6. Check narrow and wide layouts, navigation, return navigation, and social links.

External Google Fonts and the YouTube background need network access and are subject to browser and provider restrictions.

See [PHARMACY-WORKFLOW.md](PHARMACY-WORKFLOW.md) for more details about the workflow.

## Backend

The backend is a FastAPI + SQLAlchemy 2 + PostgreSQL API, with Alembic migrations. It implements the v6 data model described in `apexrx_customer_bases_roles_and_functions.md`:

- **Patients** search for medicines and pharmacies without an account. They see the availability status (`in_stock` / `low_stock` / `unavailable`), the price, the location and how fresh the information is. They never see exact quantities.
- **Pharmacies** register, get verified, add staff with their own accounts, record stock and selling prices per branch, search supplier stock (exact quantities), and place purchase orders.
- **Suppliers** register, get verified, record warehouse stock and prices, and receive, accept, counter, reject and fulfil orders.
- **Admins** (ApexRx staff) review organizations and their documents, maintain the shared catalogue, and manage accounts.

### Prerequisites

- Python 3.12+ (developed on 3.13)
- PostgreSQL 13+

### 1. Configure

```bash
cd backend
cp .env.example .env    # then edit DATABASE_URL and JWT_SECRET_KEY
```

| Variable | Required | Purpose |
|---|---|---|
| `DATABASE_URL` | yes | `postgresql+psycopg://USER:PASSWORD@HOST:PORT/DB` |
| `JWT_SECRET_KEY` | yes | At least 16 characters, random |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | no | Default 30 |
| `CORS_ORIGINS` | no | Comma-separated. Default: `http://127.0.0.1:5501,http://localhost:5501` |
| `UPLOAD_DIR` | no | Where verification documents are stored. Default `backend/uploads/` |
| `MAX_UPLOAD_SIZE_BYTES` | no | Default 10 MB |
| `DEFAULT_CURRENCY` | no | Default `RWF` |

**Security:** never commit `.env`, database credentials or JWT secrets.

### 2. Install

```bash
python -m venv .venv
source .venv/Scripts/activate      # Git Bash on Windows; use .venv/bin/activate on Linux/macOS
python -m pip install -r requirements-dev.txt   # or requirements.txt for production
```

### 3. Create the schema

```bash
alembic upgrade head
```

This works on an **empty database** and on a database still on the **old (batch-based) schema**:

- On an old-schema database, migration `a6f0c2d9e1b4` keeps the `app_user`, `drug` and `product` rows (ids preserved) and **drops the old organization, membership, location, batch and stock rows**, which do not fit the v6 model. Back up first if those rows matter. Carried-over users without a password must have one set again (use `create_admin` or re-register).
- `alembic downgrade 211f0e646448` restores the old schema (keeping users, drugs and products).

`database/db_implementation_script.sql` contains the same v6 schema as a standalone script, for review or for building a scratch database by hand. If you build a database with it, run `alembic stamp head` afterwards.

### 4. Create an admin and (optionally) demo data

```bash
python -m app.scripts.create_admin --email you@example.com --name "Your Name"
python -m app.scripts.seed_demo     # local development only
```

`seed_demo` creates an approved pharmacy with two Kigali branches, an approved supplier, five catalogue products, and stock and prices. Its accounts all use the password `demo-password`:

| Email | Role |
|---|---|
| `admin@apexrx.example.com` | Platform admin |
| `pharmacist@apexrx.example.com` | Owner of Kigali Central Pharmacy |
| `supplier@apexrx.example.com` | Owner of Rwanda Medical Supplies |

### 5. Run

```bash
uvicorn app.main:app --reload --port 8000
```

- Interactive docs: http://127.0.0.1:8000/docs (use **Authorize** to paste a token from `POST /auth/login`)
- Health check: http://127.0.0.1:8000/health

### 6. Test

The tests are integration tests against a real PostgreSQL database, because the schema's triggers are part of the behaviour. Point `TEST_DATABASE_URL` at a **disposable** database whose name ends in `_test`. The suite drops and rebuilds its schema.

```bash
export TEST_DATABASE_URL=postgresql+psycopg://USER:PASSWORD@localhost:5432/apexrx_v6_test
python -m pytest
ruff check app tests alembic
```

## API Overview

Authenticated endpoints need `Authorization: Bearer <token>`. List endpoints return `{items, total, limit, offset}` and accept `limit` (max 100) and `offset`. Errors return `{"detail": "..."}`.

| Area | Endpoints |
|---|---|
| Auth | `POST /auth/register`, `POST /auth/login`, `GET/PATCH /auth/me`, `POST /auth/me/password` |
| Patient search (public) | `GET /search/medicines?q=`, `GET /search/pharmacies?q=\|product_id=\|drug_id=&lat=&lng=&radius_km=&availability=&max_price=&sort=distance\|price\|freshness`, `GET /search/pharmacies/{location_id}` |
| Catalogue | `GET /catalogue/drugs`, `GET /catalogue/products` (public); `POST/PATCH` (admin only) |
| Organizations | `POST/GET /organizations`, `GET/PATCH /organizations/{id}`, `POST /organizations/{id}/resubmit` |
| Members | `GET/POST /organizations/{id}/members`, `PATCH/DELETE /organizations/{id}/members/{membership_id}` |
| Locations | `GET/POST /organizations/{id}/locations`, `GET/PATCH .../locations/{location_id}` (deactivate with `is_active: false`) |
| Documents | `GET/POST /organizations/{id}/documents` (multipart: `document_type`, `file`), `GET .../{doc_id}/download`, `DELETE .../{doc_id}` (pending only) |
| Inventory | `GET /organizations/{id}/inventory`; per location: `PUT/GET/DELETE .../locations/{loc}/stock/{product_id}`, `PUT/DELETE .../stock/{product_id}/offer`, `GET .../stock/{product_id}/adjustments`, `POST .../locations/{loc}/stock/confirm` |
| Supplier discovery | `GET /supplier-offers?pharmacy_organization_id=&q=&lat=&lng=&min_quantity=&sort=price\|distance\|quantity\|freshness` |
| Purchase orders | `POST/GET /purchase-orders`, `GET/PATCH/DELETE /purchase-orders/{id}`, items `POST/PATCH/DELETE .../items[/{item_id}]`, `POST .../reprice`, transitions `POST .../submit\|accept\|counter\|reject\|accept-counter\|start-processing\|dispatch\|mark-delivered\|cancel` |
| Admin | `GET /admin/organizations`, `GET /admin/organizations/{id}`, `POST .../review`, `GET /admin/documents`, `GET .../download`, `POST .../review`, `GET/PATCH /admin/users`, `GET /admin/insights/searches` |
| Legacy (deprecated) | `GET /medicines/availability`: no longer used by the frontend. Kept for older clients, without quantities |

Each purchase order includes `allowed_actions`, the actions the current user may take next, so the UI can show only the valid buttons.

### Roles and rules

| | Owner | Manager | Staff |
|---|---|---|---|
| Manage members | everyone | staff only | — (can leave) |
| Organization profile, locations, documents | ✓ | ✓ | — |
| Update stock quantities | ✓ | ✓ | ✓ |
| Set prices and listings, delete stock | ✓ | ✓ | — |
| Handle purchase orders | ✓ | ✓ | ✓ |

- Only **approved** organizations can write stock and offers, search suppliers, and create or act on orders. Cancelling is always possible.
- An organization cannot be approved while it has pending documents. It must always keep at least one active owner.
- Order line prices are always the supplier's current listed price, taken on the server. If prices change before submission, `submit` returns `409` with `price_changes`; call `reprice`, then submit again.
- A counteroffer can lower quantities and change prices, and must cover every line. The pharmacy accepts it (`accept-counter`) or cancels the order. Partial fulfilment after acceptance is out of MVP scope.
- Suppliers never see draft orders. Only drafts can be deleted; anything submitted is cancelled instead.
- Locations are deactivated, never deleted, so their stock audit trail and orders stay intact.

### How the database enforces attribution

Every authenticated request sets the database transaction actor (`set_config('app.user_id', ...)`) automatically through a SQLAlchemy session hook (`app/core/database.py`). Database triggers then stamp `updated_by`, `created_by`, `status_changed_by` and `responded_by`, and write the `stock_adjustment` and `purchase_order_status_history` audit rows. The application cannot fake or forget these values. Any script that writes stock, offers or orders must call `set_session_actor(session, user_id)` first (see `app/scripts/seed_demo.py`).

## Frontend and Backend Integration

Run the frontend and backend in separate terminals during local development. CORS allows `http://127.0.0.1:5501` and `http://localhost:5501` by default; change it with `CORS_ORIGINS`.

All frontend requests go through `frontend/js/api.js` (`window.ApexAPI`):

- It reads the backend address from `js/config.js`.
- It turns error responses into `ApiError` objects that carry a readable message.
- It keeps the access token in `sessionStorage`, so the token is cleared when the tab closes.
- Requests time out after 15 seconds.

See `/docs` on the backend for the full request and response schemas.

## Deployment (test environment)

The test deployment uses free tiers only.

### Database: Neon

1. Create a Neon project and copy its connection string. Change the scheme to `postgresql+psycopg://` and keep `?sslmode=require`.
2. From your machine, run the migrations against it once, then create an admin:

   ```bash
   cd backend
   DATABASE_URL="postgresql+psycopg://...neon.tech/...?sslmode=require" alembic upgrade head
   DATABASE_URL="..." python -m app.scripts.create_admin --email you@example.com --name "Your Name"
   ```

### Backend: Render

Create a web service with root directory `backend`.

| Setting | Value |
|---|---|
| Build command | `pip install -r requirements.txt` |
| Start command | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| Environment | `DATABASE_URL` (Neon), `JWT_SECRET_KEY`, `CORS_ORIGINS` (must include the Netlify URL, for example `https://your-site.netlify.app`) |

Limits of the free plan:

- The service sleeps after about 15 minutes without traffic. The first request after that can take up to a minute while it wakes, so it may time out in the browser: retry it.
- The disk is not persistent, so uploaded verification documents are lost when the service restarts or redeploys. Use object storage before relying on uploads.

### Frontend: Netlify

Deploy the repository with publish directory `frontend` and no build command. `frontend/js/config.js` already points to the Render backend; change it there if the backend URL changes.

### Test data

A new database has no medicines or pharmacies, so searches return nothing. Either:

- Run `python -m app.scripts.seed_demo` against the database (fake data only), or
- Add real data through the API: an admin creates catalogue drugs and products, then approved pharmacies record their stock and prices per branch.

Patient search shows only **approved** pharmacies, **active** locations and **listed** offers. By default it returns `in_stock` and `low_stock` results.

## Development Roadmap

- Screens for inventory (stock and prices), purchase orders and admin review. `frontend/js/api.js` already has these calls.
- A catalogue import script for loading real medicine data.
- Password reset and email verification.
- Subscription plans and real payments (the plan step is simulated).
- Object storage (S3 or similar) for verification documents in multi-server deployments.
- PostGIS for distance search at scale (bounding-box and haversine search is used today).
- Notifications (email/WhatsApp) for order status changes.
