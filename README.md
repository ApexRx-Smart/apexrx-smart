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
│   │   ├── admin.js         # admin dashboard
│   │   ├── config.js        # backend address (API_BASE_URL)
│   │   ├── api.js           # API client used by every page (window.ApexAPI)
│   │   ├── script.js        # homepage, including medicine search
│   │   ├── pharmacies.js    # pharmacy onboarding and workspace
│   │   ├── pharmacies-i18n.js
│   │   └── pharmacies-motion.js
│   ├── tests/
│   │   └── e2e_admin.py     # Playwright check of the admin dashboard (local only)
│   ├── admin.html           # admin dashboard (ApexRX staff)
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
- Admin dashboard: http://localhost:5501/admin.html

Stop the server with `Ctrl+C`. VS Code Live Server works too, on port 5501.

### What is connected to the API

[frontend/README.md](frontend/README.md) maps every page and control to its endpoint. In short:

- **Homepage search** calls `GET /search/pharmacies`. It shows availability, price, location and how fresh the data is, never exact quantities.
- **Pharmacy registration** (`pharmacies.html`) creates the account (`POST /auth/register`), signs in, creates the pharmacy organization and its location, and uploads the verification documents. An existing email signs in instead.
- **Phone verification** (step 2): the user's mobile number is verified by SMS one-time code (`/auth/phone/*`). The backend only allows a pharmacy to be registered with that verified number. See [Phone verification (SMS)](#phone-verification-sms).
- **The pharmacy workspace** (`js/workspace.js`) runs the pharmacy day to day. All of it uses real backend data:
  - **Overview:** organization, status, branches, members and purchase-order counts.
  - **Branches:** list, add, edit, deactivate and reactivate.
  - **Employees:** add an existing account by email, change roles, deactivate, remove.
  - **Inventory:** per branch, set quantities, prices and listing.
  - **Purchase orders:** create a draft with a receiving branch, edit lines, submit, cancel with a reason, view history.
  - **Organization selector:** for users who belong to several pharmacies.
  - It also lists suppliers from the pharmacy's purchase orders and searches supplier stock with `GET /supplier-offers`, which works only for approved pharmacies. **Open chat** opens the supplier's WhatsApp or phone.
  - Buttons follow the user's role, but the backend enforces every rule.
- **Joining an existing pharmacy:** someone who registers to work at an existing pharmacy chooses "Joining an existing pharmacy instead?". They wait for the owner or a manager to add their email, instead of registering a new pharmacy.
- **Just exploring?** still opens the workspace with sample data and no account.

- **The admin dashboard** (`admin.html`) lets ApexRX staff review registrations. See [Admin dashboard](#admin-dashboard).

Still simulated in the browser, because the v6 data model has no support for them: the plan and payment step, and in-app supplier chat. Supplier organizations have no workspace screens yet; they use the API.

### Verify frontend changes

After making changes, check the following:

1. Open the home page and verify the Kigali map, logos, audience images, and animations.
2. Select English, French, and Kinyarwanda and verify that the language selection is applied.
3. Search for a medicine on the home page and check that results come back from the backend. An empty database returns no results: see [Test data](#test-data).
4. Open the pharmacy workflow and register with a new email and matching passwords (8 characters minimum). With the local backend in development mode (`APP_ENV=development`, `SMS_PROVIDER=mock`), enter a Rwandan mobile number and choose **Send code by SMS**. Read the code from `GET /dev/sms/latest` (see [Phone verification (SMS)](#phone-verification-sms)) and enter it. Then fill in the profile, upload the documents and continue through the simulated payment step.
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
| `JWT_SECRET_KEY` | yes | Token signing secret: **at least 32 random characters**. Placeholder/example values (including the one in `.env.example`) are rejected at startup, and the value is never echoed in errors. Generate one with `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | no | Default 30 |
| `CORS_ORIGINS` | no | Comma-separated. Default: `http://127.0.0.1:5501,http://localhost:5501` |
| `SUPABASE_URL` | production | Supabase project URL, e.g. `https://<project-ref>.supabase.co`. With the key, document files go to Supabase Storage |
| `SUPABASE_SECRET_KEY` | production | Supabase **secret** key (`sb_secret_...`, or the legacy `service_role` key). Backend only: never put it in the frontend |
| `SUPABASE_BUCKET_NAME` | no | Default `organization-documents`. The bucket must be **private** |
| `TRUSTED_CLIENT_IP_HEADER` | no (leave unset) | Header holding the real client IP. **Set it only after `tools/render-ip-check` shows that the proxy overwrites it.** Otherwise clients choose their own value. `X-Forwarded-For` is refused. See [Login rate limiting](#login-rate-limiting) |
| `DEVICE_TOKEN_MAX_AGE_DAYS` | no | Default 90. Lifetime of the "known browser" tokens |
| `LOGIN_MAX_FAILURES_PER_ACCOUNT` / `LOGIN_MAX_FAILURES_PER_IP` / `LOGIN_FAILURE_WINDOW_SECONDS` | no | Defaults 5 / 20 / 900 (15 minutes) |
| `RATE_LIMIT_STORAGE_URI` | no | Default `memory://` (per process). Use e.g. `redis://host:6379` with several instances |
| `DOCUMENT_STORAGE` | no | `auto` (default: Supabase when the two variables above are set, otherwise local disk), `supabase` or `local` |
| `UPLOAD_DIR` | no | Local document storage only (development). Default `backend/uploads/` |
| `MAX_UPLOAD_SIZE_BYTES` | no | Default 10 MB |
| `DEFAULT_CURRENCY` | no | Default `RWF` |
| `APP_ENV` | no | `production` (default), `development` or `test`. Only non-production allows the mock SMS provider and the `/dev` endpoints. On Render, any value other than `production` stops the service from starting |
| `PHONE_VERIFICATION_REQUIRED` | no | Default `true`: a pharmacy can only be registered with an SMS-verified number |
| `SMS_PROVIDER` | for SMS | Adapter name. `mock` works only outside production; real adapters are added as described in [Phone verification (SMS)](#phone-verification-sms). If it is unset, sending a code returns 503 |
| `SMS_SENDER_ID` | no | Sender name or number, for providers that support one |
| `OTP_TTL_SECONDS` / `OTP_MAX_ATTEMPTS` / `OTP_RESEND_COOLDOWN_SECONDS` | no | Defaults 300 / 5 / 60 |
| `OTP_MAX_SENDS_PER_PHONE_PER_HOUR` / `..._PER_USER_PER_HOUR` / `..._PER_IP_PER_HOUR` | no | Defaults 5 / 10 / 20. The IP limit applies only when the client IP is trustworthy |
| `PHONE_DEFAULT_REGION` / `PHONE_ALLOWED_REGIONS` | no | Defaults `RW` / `RW` (ISO country codes, comma-separated) |

**Security:** never commit `.env`, database credentials, JWT secrets or the Supabase secret key.

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

`create_admin` writes to the database in `DATABASE_URL` (environment first, otherwise `backend/.env`). Everything below is checked **before** anything is written:

- **Target:** it prints the target host and database name, never the credentials.
- **Non-local databases:** for a non-local or production-like database, you must **retype the exact host**, even with `--yes`.
- **New email:** a new platform admin is created. The password is prompted for twice, hidden (or read from `APEXRX_ADMIN_PASSWORD`). Then you type `yes` to confirm (`--yes` skips this prompt only).
- **Email that already has an account:** it shows the account (ID, name, active, admin, organizations) and changes nothing unless you pass the matching flag:
  - `--promote-existing` grants admin to that existing account.
  - `--reactivate` reactivates it if it was deactivated.
  - Passing either flag for an email with no account is refused, since that is usually a typo.
  - An existing account's password is never changed.

`seed_demo` only runs against a **local** database (a loopback host whose name does not look like production: not `neondb`, nothing containing `prod` or `live`). Any other target is refused before anything is written, unless you pass `--allow-remote-database` **and** retype the host. It creates a platform admin with a public password, so never use that flag on production.

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

The document tests use an in-memory fake of the Supabase Storage client, and the suite forces `DOCUMENT_STORAGE=local`, so tests never touch a real bucket. `tests/test_supabase_live.py` is an optional round trip against the real bucket (a dummy PDF under a random `test-.../` prefix, deleted afterwards). It runs only with `SUPABASE_LIVE_TESTS=1` and the `SUPABASE_*` variables set.

## Phone verification (SMS)

**Flow:** a pharmacy owner signs in, verifies their mobile number by SMS, and only then can register the pharmacy. All decisions are made on the backend.

| Endpoint | What it does |
|---|---|
| `GET /auth/phone/status` | `{required, verified, verified_phone, sms_available}`. The page uses it to decide whether to show the step |
| `POST /auth/phone/send-code` `{phone}` | Normalizes the number to E.164, applies the limits, stores a hashed code and sends the SMS. Returns the normalized and masked number, `expires_in` and `resend_after`, **never the code** |
| `POST /auth/phone/verify` `{phone, code}` | Single-use check. On success it sets `app_user.verified_phone` and `phone_verified_at` |
| `POST /organizations` (pharmacy) | **403** without a verified phone. **400** if the requested phone isn't the verified number. If no phone is given, the verified number is used. Changing a pharmacy's phone later also needs that new number to be verified |

**Codes:**
- Six random digits (`secrets`), valid for 5 minutes, single-use. The row is locked while it is checked, so two simultaneous requests can't both use a code.
- Only an HMAC of the code is stored. It is keyed with a secret derived from `JWT_SECRET_KEY` and bound to the user, number and purpose. A code for one number or account never verifies another.
- A new code invalidates the earlier ones. After 5 wrong attempts the code is dead.
- Sending is limited by a 60-second cooldown per number, and per hour per number (5), per user (10) and per trustworthy client IP (20).
  - **The limits live in PostgreSQL, not process memory.** They are counted from `phone_verification` rows inside one transaction.
  - That transaction first locks the user's row, then takes transaction-scoped advisory locks for the number and the IP, always in that order.
  - Checking and recording are therefore atomic, even with simultaneous requests or several app instances, and the limits survive restarts.
  - Only one code per user is issued at a time.
  - A partial unique index means the database itself refuses a second valid code for the same user and purpose.
  - The client IP is stored only as an HMAC.
- **The limits fail closed.** If the database can't check or record a limit, no SMS is sent and the client gets a generic 503 ("Verification codes cannot be sent right now"). Internal details are only logged.
- **The code is saved before it is sent.** The row is committed first and only then is the SMS sent, so a code can never be delivered without being stored.
  - If the provider refuses the message, the row is marked `delivery_failed_at` and invalidated. It still counts towards the hourly limits, so a failing provider can't be hammered, but not towards the cooldown, so the user can retry at once.
  - Trade-off: issuing a new code invalidates the previous one *before* sending. If that send fails, the user simply requests another code.
  - Remaining corner case: if recording a failed delivery also fails (the database is down at that moment), the undelivered code stays stored until it expires. Nobody knows it, but the user may have to wait out the cooldown.
- Codes and full phone numbers never appear in API responses or logs; logs show a masked number such as `+2507*****456`.

**Phone numbers:**
- Parsed with [`phonenumbers`](https://pypi.org/project/phonenumbers/) (libphonenumber).
- Rwandan formats such as `0788 123 456`, `788123456`, `250788123456` and `+250 788 123 456` become `+250788123456`.
- Only mobile numbers from `PHONE_ALLOWED_REGIONS` are accepted. Letters are refused, since libphonenumber would otherwise map them to keypad digits.
- To support another country, add it to `PHONE_ALLOWED_REGIONS`.

**Modes:**
- **Development and tests:** `APP_ENV=development` (or `test`) with `SMS_PROVIDER=mock`.
  - The mock sends nothing. It keeps messages in memory only.
  - `GET /dev/sms/latest`, signed in, returns **your own** latest test code.
  - The `/dev` routes aren't mounted in production, and the endpoint also answers 404 in production itself.
  - The tests use the mock automatically (`tests/conftest.py`).
- **Production:** `APP_ENV=production`, the default.
  - The mock is refused. With no real provider configured, `send-code` answers **503** "SMS verification is not available right now", a warning is logged at startup, and new pharmacies can't register.
  - A delivery failure answers **502**. Nothing falls back to the mock, and the stored code is marked as failed and invalidated.
- **Before a provider exists:** set `PHONE_VERIFICATION_REQUIRED=false`. The step is then skipped and pharmacies register without a verified number. There is never a fixed code.

**Adding a real provider (adapter):**
1. Create `backend/app/services/sms/<name>.py` with a class that has `name` and `send(to, message) -> SmsResult`. It calls the provider's HTTP API and raises `SmsDeliveryError` on any failure, never failing silently.
2. Read the provider's credentials inside the adapter from environment variables, for example `SMS_<NAME>_API_KEY` or a username and sender ID. Never commit them.
3. Register a factory in `PROVIDERS` in `backend/app/services/sms/__init__.py`.
4. Set `SMS_PROVIDER=<name>` and the credentials on Render. `GET /auth/phone/status` should then report `"sms_available": true`.

Typical providers need an API key or token, an account ID or username, and a registered sender ID or number. Get the exact names from the provider you choose. No provider has been chosen or tested yet, so **real SMS delivery has not been verified**.

**Testing locally:**
```bash
cd backend
python -m pytest tests/test_phone_otp.py tests/test_pharmacy_phone_binding.py tests/test_phone_numbers_and_sms.py
# Browser test: run the backend with APP_ENV=development SMS_PROVIDER=mock OTP_RESEND_COOLDOWN_SECONDS=5
python ../frontend/tests/e2e_phone_otp.py
```

## Login rate limiting

Failed sign-ins (`POST /auth/login`) are limited with the [`limits`](https://pypi.org/project/limits/) library, using a moving window. The limits are checked **before** the password is verified. A blocked attempt gets **429** with `Retry-After` and "Too many failed sign-in attempts. Please wait about N minutes and try again". The right password is refused too.

| Limit | Default | Counted for | Cleared by |
|---|---|---|---|
| Per account | 5 failures / 15 min | Browsers that haven't signed in to this account before. Keyed on a hash of the normalized email, **whether or not the account exists**, so no account is revealed | A successful sign-in from such a browser |
| Per known browser | 5 failures / 15 min | A browser that sends a valid device token for this account | A successful sign-in from that browser |
| Per client IP | 20 failures / 15 min | Only when the client IP is trustworthy (see below) | Expiry only |

**Known browsers (protection against lockout):**
- Every successful sign-in returns a signed `device_token`. It is tied to that user ID, expires after 90 days, and its signing key is derived from `JWT_SECRET_KEY`.
- `js/api.js` keeps it in `localStorage` for that email and sends it with the next sign-in.
- Someone who knows a user's email can still lock the account for **new** browsers with 5 wrong passwords. The owner's usual browser keeps working, because its attempts are counted separately.
- A device token is not a credential: the password is always required, and a token for one account is ignored for any other.
- Signing in from a new browser while an attack is under way still has to wait for the window to pass.

**Client IP:**
- `X-Forwarded-For` is never trusted: Render appends to it without clearing it.
- Leave `TRUSTED_CLIENT_IP_HEADER` **unset** unless `tools/render-ip-check` shows that a header (for example `CF-Connecting-IP` or `True-Client-IP`) always carries your real IP and can't be forged. Cloudflare's documentation says `True-Client-IP` is added only when it's enabled, and can otherwise be spoofed.
- Without the header, the TCP peer is used. On Render that's a private proxy address, so the per-IP limit is **skipped** rather than becoming one bucket shared by every user. The per-account and per-browser limits still apply, and a warning is logged at startup.

**Storage:** counters live in process memory (`RATE_LIMIT_STORAGE_URI=memory://`). That fits the single Render instance, and the counters reset on restart or deploy. With several instances, use a shared store such as Redis.

## Document storage

Verification documents are files in a **private Supabase Storage bucket**. Their metadata (type, file name, size, review status and the object key in `organization_document.storage_key`) stays in PostgreSQL on Neon.

- **Object keys** are generated by the backend: `org-<organization_id>/<32 random hex characters>.<pdf|png|jpg>`. The uploaded file name is stored only as metadata, so it cannot cause path traversal or overwrite another file. Uploads never overwrite (`upsert=false`).
- **Validation** happens before anything is stored. Only PDF, PNG and JPEG are accepted (415 otherwise), and the content must match the declared type. Empty files are refused (400), as are files over `MAX_UPLOAD_SIZE_BYTES` (413).
- **Downloads** are streamed through the API after the caller is checked:
  - `GET /admin/documents/{id}/download` needs a platform admin.
  - `GET /organizations/{id}/documents/{doc}/download` needs a member of that organization.
  - Anyone else gets 404, 403 or 401.
  - No Supabase URL, signed or public, is ever sent to the browser, and the secret key never leaves the backend.
- **Failures:** if Supabase is unreachable, uploads and downloads return 503 "Document storage is temporarily unavailable". No metadata row is written for a failed upload. A record whose file is not in the bucket returns 404 "missing from storage", and the record itself is kept.
- **Check the configuration** with `python -m app.scripts.check_storage`. It confirms the bucket is private and round-trips a dummy file. It prints no secrets.
- **Files from the old local storage** keep the same key format. `python -m app.scripts.migrate_documents_to_supabase` lists the files it would copy (a dry run). Add `--apply` to upload them under the same keys. No database change is needed.

## Admin dashboard

`frontend/admin.html` is for ApexRX staff. It is marked `noindex`; the only public link is the discreet "Admin Portal" link in the homepage footer, which sits on the left, next to the copyright, clear of the "Powered by Netlify" badge in the bottom-right corner. It uses only existing endpoints, and has one tab per area. The current tab is kept in the URL (`#users`, `#catalogue` and so on).

- **Sign in:** with the normal ApexRX login. Accounts that aren't platform admins are refused, and their token is cleared. The token is kept in `sessionStorage`, like the rest of the site. An expired or invalid token returns you to the sign-in screen. **Sign out** clears it.
- **Overview:**
  - What needs attention: organizations and documents awaiting review.
  - Platform numbers: organizations, user accounts, platform administrators, drugs, active products and retired products.
  - The five most searched medicines, and the five searches with no results, over the last 30 days.
  - Each number is the `total` of an existing list endpoint (`limit=1`). There is no summary endpoint. Each card opens the matching section.
- **Organizations:**
  - Seven counts at the top: total, pharmacies, suppliers, pending, approved, rejected and suspended. Clicking a count filters the list by it.
  - A table of name, type, registration date, status and contact details, with type and status filters, a name or email search, and pagination.
- **Organization detail:**
  - **Information:** profile, contacts, review history, locations, members and verification documents.
  - **Documents:** download any document, then approve it or reject it with a reason.
  - **Organization:** approve, reject with notes, or suspend with notes. Only the actions the backend allows from the current status are shown. **Approve** stays disabled while any document is pending.

- **Documents:** the review queue across all organizations (`GET /admin/documents`).
  - Filter by status: awaiting review, approved or rejected.
  - From each row: download the file, approve it, reject it with a reason, or open the organization.
- **Users:** every account, with a name or email search and a filter for platform administrators.
  - Each row shows the phone and whether it was verified by SMS, the registration date, active or inactive, and admin.
  - **Deactivate** / **Reactivate** and **Make admin** / **Remove admin** use `PATCH /admin/users/{id}`, after a confirmation.
  - Your own row has no buttons. The backend refuses deactivating yourself or removing your own admin access anyway.
  - A deactivated account loses access straight away: existing tokens stop working.
- **Catalogue:**
  - **Drugs:** search by name or therapeutic class, add, edit. **View products** lists the drug's products.
  - **Products:** search by product, brand, drug or exact barcode, with an option to include retired products.
  - Add or edit a product, choosing its drug from a searchable list. A field you clear is removed.
  - **Retire** / **Reactivate** use `is_active`, after a confirmation. Retired products are greyed out and labelled.
  - Duplicate names, products and barcodes are refused by the backend (409), and its message is shown on the form. Save buttons are disabled while saving, so a double click can't create a duplicate.
- **Search insights:** anonymous patient searches (`GET /admin/insights/searches`).
  - Choose the period (7, 30, 90 or 365 days) and how many to show, or show only searches that found nothing.
  - **Check catalogue** looks the search up in the products list, to spot catalogue gaps.
  - Only the search text and counts are shown. No patient details are recorded.

Every rule is enforced by the backend:
- `require_platform_admin` on every `/admin` route and every catalogue write;
- `ORG_TRANSITIONS`;
- the pending-documents check;
- the self-protection rule for user changes;
- the catalogue duplicate checks.

The page's buttons are only for usability. All values from the API are inserted as text, never as HTML.

To check the dashboard end to end against a **local** backend and a disposable database:
- `frontend/tests/e2e_admin.py`: organizations, document review, the session;
- `frontend/tests/e2e_admin_console.py`: overview, document queue, users, catalogue, search insights, loading, empty and error states, and access control.

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
| View orders, prepare and edit drafts | ✓ | ✓ | ✓ |
| Submit, cancel and accept counteroffers (pharmacy side) | ✓ | ✓ | — |
| Supplier side: accept, counter, reject, dispatch, cancel | ✓ | ✓ | ✓ |

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

### Database migrations: always before the code

The service doesn't run migrations by itself: Render only starts `uvicorn`. The ORM models always expect the latest schema. **If code is deployed before its migration has been applied, sign-in, registration, the workspace and admin fail with 503 "A database error occurred".**
- This happens even with `PHONE_VERIFICATION_REQUIRED=false`, because every query that loads a user selects the new columns. Public search keeps working.
- `/health` returns **503** with "Database schema is not up to date … run `alembic upgrade head`", and the startup log says the same.
- Optional safety net: if Render's **Health Check Path** is set to `/health`, Render won't switch traffic to a new deploy whose database hasn't been migrated.

These are three separate actions:

| Action | What it changes | How |
|---|---|---|
| **Apply a migration** | The database structure only | `alembic upgrade head`, run from your machine against the database |
| **Deploy application code** | What Render runs | Merging to `main` (Render deploys automatically) |
| **Turn mandatory phone verification on or off** | Whether a pharmacy needs an SMS-verified phone | The `PHONE_VERIFICATION_REQUIRED` environment variable on Render. It changes behaviour, not the schema, and needs no migration |

**Safe order for the testing environment** (for example, PR #24 and migration `c4d1e8f2a9b7`):
1. **Back up.** In Neon, open **Branches → Create branch** from the testing branch (for example `pre-c4d1e8f2a9b7`). That gives you an instant copy you can restore.
2. **Record the counts before** (read-only, Neon SQL Editor):
   ```sql
   SELECT version_num FROM alembic_version;  -- expect a6f0c2d9e1b4
   SELECT (SELECT count(*) FROM app_user) AS users, (SELECT count(*) FROM organization) AS orgs,
          (SELECT count(*) FROM location) AS locations, (SELECT count(*) FROM product_offer) AS offers;
   ```
3. **Apply the migration** from your machine, with a role that can change the schema (not the read-only role):
   ```bash
   cd backend
   DATABASE_URL="postgresql+psycopg://<owner role>:<password>@<host>/<db>?sslmode=require" alembic upgrade head
   DATABASE_URL="..." alembic current        # must print: c4d1e8f2a9b7 (head)
   ```
   The migration is additive: two nullable columns on `app_user`, plus the new `phone_verification` table. The code currently deployed keeps working on the new schema (verified locally), so this step causes no downtime.
4. **Verify** in the Neon SQL Editor:
   ```sql
   SELECT version_num FROM alembic_version;                -- c4d1e8f2a9b7
   SELECT count(*) FROM app_user WHERE verified_phone IS NOT NULL;   -- 0: existing rows untouched
   SELECT to_regclass('phone_verification');                -- phone_verification
   ```
   Re-run the counts from step 2. They must be identical.
5. **Choose the verification setting** on Render *before* deploying. Use `PHONE_VERIFICATION_REQUIRED=false` until a real SMS provider is configured; otherwise new pharmacies can't register.
6. **Deploy the code** by merging the PR. Then `GET /health` must return 200 with `"schema": "up to date"`. Check that sign-in and patient search work.

**Rolling back:**
- Revert or redeploy the previous code first. The previous code works on the new schema.
- Only if the schema itself must go, run `alembic downgrade a6f0c2d9e1b4`. That drops `phone_verification` and the two columns, so verification records are lost. Alternatively, restore the Neon branch from step 1.

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
| Environment | `DATABASE_URL` (Neon), `JWT_SECRET_KEY` (**at least 32 random characters**, or the service will not start), `APP_ENV=production` (also the default), `SMS_PROVIDER` and the provider's credentials (or `PHONE_VERIFICATION_REQUIRED=false` until there is a provider), `CORS_ORIGINS` (must include the Netlify URL, for example `https://your-site.netlify.app`), `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `SUPABASE_BUCKET_NAME=organization-documents`. Leave `TRUSTED_CLIENT_IP_HEADER` unset unless `tools/render-ip-check` has verified a header |

Limits of the free plan:

- The service sleeps after about 15 minutes without traffic. The first request after that can take up to a minute while it wakes, so it may time out in the browser: retry it.
- The disk is not persistent. That is why verification documents are stored in Supabase Storage. Without the `SUPABASE_*` variables, the backend falls back to local disk, and uploads are lost on the next restart. The first document upload or download logs which storage is in use (`Document storage: Supabase bucket ...`), and `python -m app.scripts.check_storage` checks it directly.

### Documents: Supabase Storage

1. In the Supabase dashboard, open **Storage** and create the bucket `organization-documents`. Leave **Public bucket off**. No storage policies are needed, because only the backend accesses the bucket, using the secret key.
2. Copy the **Project URL** and a **secret key** from **Project Settings → API Keys**, and set them on Render as `SUPABASE_URL` and `SUPABASE_SECRET_KEY`. Never put them in the frontend or in the repository.

### Frontend: Netlify

Deploy the repository with publish directory `frontend` and no build command. `frontend/js/config.js` already points to the Render backend; change it there if the backend URL changes.

### Test data

A new database has no medicines or pharmacies, so searches return nothing. Either:

- Run `python -m app.scripts.seed_demo` against a **local** database (fake data only; it refuses remote databases by default), or
- Add real data through the API: an admin creates catalogue drugs and products, then approved pharmacies record their stock and prices per branch.

Patient search shows only **approved** pharmacies, **active** locations and **listed** offers. By default it returns `in_stock` and `low_stock` results.

## Development Roadmap

- Supplier workspace screens (stock, prices and incoming orders). The pharmacy workspace exists; suppliers still use the API.
- A catalogue import script for loading real medicine data.
- A real SMS provider adapter (the infrastructure is ready; see [Phone verification (SMS)](#phone-verification-sms)).
- Password reset and email verification.
- Subscription plans and real payments (the plan step is simulated).
- PostGIS for distance search at scale (bounding-box and haversine search is used today).
- Notifications (email/WhatsApp) for order status changes.
