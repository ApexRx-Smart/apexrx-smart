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
- **Registration** (`pharmacies.html` and `suppliers.html`, both driven by `js/registration.js`): Account -> Verify email -> Details -> Documents -> Review.
  - **Account:** `POST /auth/register` then sign in (an existing email signs in instead), or "Already have an account? Sign in".
  - **Verify email:** a single-use link is emailed to the account address (`/auth/email/*`, opened on `verify-email.html`). The backend refuses to create a pharmacy or supplier until the email is verified. See [Email verification](#email-verification).
  - **Details:** business name and phone, branch or warehouse name, WhatsApp (optional), a structured Rwandan address (province, district, sector, cell, village from `frontend/data/rwanda-locations.json`, plus street or landmark) and optional coordinates ("Use my current location"). Stored on the organization and its first location.
  - **Documents:** pharmacy license, business license and owner ID for pharmacies; business license and owner ID for suppliers.
  - **Review:** the real status, ApexRX's review note, the stored details and documents, uploads, and "Resubmit for review" after a rejection. Pharmacies then open their workspace.
  - **Resuming:** progress is read back from the backend, so signing in again continues an incomplete registration where it stopped.
  - The page always shows which account is signed in ("Signed in as … · Sign out"). There is no payment or subscription step, and phone numbers are contact details only.
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
- **Supplier registration (`suppliers.html`):** the same journey with `type: "supplier"` and a warehouse; same API and admin review as pharmacies.
- **Public pages:**
  - `how-it-works.html`, `about.html` (placeholder content to replace) and `legal.html` (placeholder privacy, terms and cookie pages, not approved policies).
  - They share one header and footer, from `js/site-layout.js`.
  - Both registration pages have an "Already have an account? Sign in" switch, and every password field has a show/hide button.
  - See `frontend/README.md`.
- **Just exploring?** still opens the workspace with sample data and no account.

- **The admin dashboard** (`admin.html`) lets ApexRX staff review registrations. See [Admin dashboard](#admin-dashboard).

Still simulated in the browser: in-app supplier chat (the sample conversations in the preview). There is no subscription or payment anywhere in registration. Supplier organizations have no workspace screens yet; they use the API.

### Verify frontend changes

After making changes, check the following:

1. Open the home page and verify the Kigali map, logos, audience images, and animations.
2. Select English, French, and Kinyarwanda and verify that the language selection is applied.
3. Search for a medicine on the home page and check that results come back from the backend. An empty database returns no results: see [Test data](#test-data).
4. Open the pharmacy workflow and register with a new email and matching passwords (8 characters minimum). With the local backend in development mode (`APP_ENV=development`, `EMAIL_PROVIDER=mock`, `FRONTEND_BASE_URL=http://127.0.0.1:5501`), the verification email is kept in memory: open the `link` from `GET /dev/email/latest` (see [Email verification](#email-verification)). The registration tab continues by itself. Then fill in the details, upload the documents and check the review.
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
| `APP_ENV` | no | `production` (default), `development` or `test`. Only non-production allows the mock email provider and the `/dev` endpoints. On Render, any value other than `production` stops the service from starting |
| `EMAIL_VERIFICATION_REQUIRED` | no | Default `true`: registering a pharmacy or supplier needs a verified account email |
| `EMAIL_PROVIDER` | for email | `resend` or `brevo` (HTTPS APIs). `mock` works only outside production. If it is unset, sending a verification email returns 503. See [Email verification](#email-verification) |
| `RESEND_API_KEY` / `BREVO_API_KEY` | for that provider | The provider's API key. Server-side only |
| `EMAIL_FROM_ADDRESS` / `EMAIL_FROM_NAME` | address: for email | Sender, e.g. `no-reply@your-domain`; it must be allowed by the provider (usually a verified domain). Name default `ApexRX Smart` |
| `FRONTEND_BASE_URL` | for email | Where the frontend is served (the link opens `<FRONTEND_BASE_URL>/verify-email.html`). Must be `https://` in production. Default `http://127.0.0.1:5501` |
| `EMAIL_VERIFICATION_TTL_MINUTES` / `EMAIL_VERIFICATION_RESEND_COOLDOWN_SECONDS` | no | Defaults 1440 (24 hours) / 60 |
| `EMAIL_VERIFICATION_MAX_SENDS_PER_USER_PER_HOUR` / `..._PER_IP_PER_HOUR` | no | Defaults 5 / 20. The IP limit applies only when the client IP is trustworthy |
| `PHONE_DEFAULT_REGION` / `PHONE_ALLOWED_REGIONS` | no | Defaults `RW` / `RW`. Business phone numbers are normalized with these (contact only, not verification) |

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

## Email verification

**Flow:** a pharmacy or supplier owner creates an account and signs in, ApexRX emails a link to that address, and opening the link verifies it. Only then can the organization be registered. All decisions are made on the backend.

| Endpoint | What it does |
|---|---|
| `GET /auth/email/status` (signed in) | `{email, verified, verified_at, required, delivery_available, pending, expires_at, resend_after}`. The registration page uses it to show the step and to resume |
| `POST /auth/email/send` `{next}` (signed in) | Applies the limits, stores a hashed token and emails a link to the **account's** address. `next` (`pharmacy` or `supplier`) only chooses where the link leads afterwards. Returns the masked address, `expires_in` and `resend_after`, **never the token**. 409 if already verified |
| `POST /auth/email/verify` `{token}` (no session) | Opened from the link by `verify-email.html`. Single use. Sets `app_user.email_verified_at`. Errors are 400 with a `reason`: `invalid`, `expired`, `used` or `superseded` (a newer email was sent). Reopening a link after verification answers 200 with `already_verified: true` and changes nothing |
| `POST /organizations` | **403** (`reason: email_unverified`) until the caller's email is verified, for pharmacies and suppliers |

**Links and tokens:**
- `<FRONTEND_BASE_URL>/verify-email.html?next=pharmacy#token=...`. The token (32 random bytes) is in the URL **fragment**, so it is never sent to a server in a request line or Referer. The page removes it from the address bar before calling the API, and the page sets `referrer: no-referrer`.
- Only a SHA-256 hash of the token is stored (`email_verification`), bound to the user and to the address it was sent to. If the account's address changes, or the account is deactivated, the link stops working.
- Valid for 24 hours (configurable), single-use. Sending a new email invalidates the earlier links; a partial unique index lets the database itself refuse a second usable link for the same user.
- Opening the link needs no session, because opening it proves access to the mailbox, which is what is being verified. It can be opened on another device. In the same browser, the registration tab is notified (BroadcastChannel) and also re-checks when it regains focus, so it continues by itself.

**Limits** (as for the former SMS codes, in PostgreSQL so they hold across restarts and instances): a 60-second resend cooldown, at most 5 emails per user per hour and 20 per trustworthy client IP per hour. The user's row and an advisory lock for the IP are locked while checking and recording, so the check is atomic. The limits fail closed: if the database cannot check them, no email is sent (generic 503). The link is stored before the email is sent; a provider failure answers 502, marks the row failed and lets the user retry immediately. Tokens and full addresses never appear in responses or logs (logs show `a***a@example.com`).

**Providers** (`backend/app/services/email/`): Render's free plan blocks outbound SMTP (ports 25, 465 and 587), so email goes through an HTTPS API:
- **Resend** (`EMAIL_PROVIDER=resend`): create an API key, verify a domain you control under Domains (DNS records), and use a sender on it (`EMAIL_FROM_ADDRESS=no-reply@your-domain`). Without a verified domain, Resend only delivers to your own account address.
- **Brevo** (`EMAIL_PROVIDER=brevo`): create an API key under SMTP & API, and authenticate your domain (or at least verify a sender). Free addresses such as Gmail cannot be authenticated and may be rewritten or filtered.
- Set the key (`RESEND_API_KEY` or `BREVO_API_KEY`), `EMAIL_FROM_ADDRESS` and `FRONTEND_BASE_URL` (the Netlify URL) on Render, never in the repository or the frontend. `GET /auth/email/status` then reports `"delivery_available": true`; the startup log warns while email is not configured.
- Real delivery has not been tested from this repository (no provider account or domain was available); the adapters are tested against the providers' documented request formats.

**Modes:**
- **Development and tests:** `APP_ENV=development` (or `test`) with `EMAIL_PROVIDER=mock`. The mock sends nothing and keeps messages in memory; `GET /dev/email/latest`, signed in, returns **your own** latest message with its link. The `/dev` routes are not mounted in production and also answer 404 there.
- **Production** (`APP_ENV=production`, the default, and the only value Render accepts): the mock is refused. With no provider configured, sending answers **503** and new organizations cannot register (unless `EMAIL_VERIFICATION_REQUIRED=false`, which skips the requirement; there is never a fake verification).

**Phone numbers** are business contact details (and later Mobile Money). They are normalized to E.164 with [`phonenumbers`](https://pypi.org/project/phonenumbers/) (`0788 123 456` -> `+250788123456`, numbers from `PHONE_ALLOWED_REGIONS` only), and are never used to verify anyone. The former SMS verification was removed; its old table `phone_verification` and the columns `app_user.verified_phone` / `phone_verified_at` are left in the database untouched (nothing writes them any more) and can be dropped by a later migration.

**Testing locally:**
```bash
cd backend
python -m pytest tests/test_email_verification.py tests/test_registration_profile.py
# Browser test: run the backend with APP_ENV=development EMAIL_PROVIDER=mock FRONTEND_BASE_URL=http://127.0.0.1:5501
python ../frontend/tests/e2e_registration.py
```

## Password hashing

Passwords are hashed with Argon2id through pwdlib's recommended configuration, `PasswordHash.recommended()` (argon2-cffi defaults: 64 MiB of memory, 3 passes, 4 lanes; `backend/app/core/security.py`). In November 2026 cheaper parameters (19 MiB, 2 passes, 1 lane) were briefly used; that change was reverted. Any hash made with other parameters still verifies and is re-hashed with the recommended ones the next time that user signs in successfully, so no migration is needed.

## Responsiveness

- **Activity indicator:** `js/api.js` shows a thin progress bar at the top of the page while any request is in flight. After 4 seconds it adds a note that the server may be starting up: a free Render instance sleeps when idle, and its first request can take 30 seconds or more.
- **Warm-up:** each page that loads `js/api.js` sends `GET /health` straight away, without waiting for it. A sleeping server and database start waking while the user reads or types.
- **Timeout:** requests time out after 45 seconds, long enough for that wake-up.
- **Fewer, parallel requests:**
  - The admin overview uses one counts request instead of seven.
  - The pharmacy workspace loads the organization, branches, documents and orders at the same time.
  - Registration saves the location and uploads documents at the same time.
- **No flashing:** a workspace section repainting after a save stays visible, dimmed, instead of flashing "Loading…".
- **Busy buttons:** admin buttons show "Opening…", "Approving…" and similar while they wait.

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
  - Seven counts: total, pharmacies, suppliers, pending, approved, rejected and suspended.
  - They come from `GET /admin/organizations/counts`: one request and one grouped query for all seven numbers.
  - Clicking a count filters the list by it.
- **Organizations:** a table of name, type, registration date, status and contact details. It has type and status filters, a name or email search, and pagination.
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
  - **Stock and purchase orders (read only):**
    - The organization's stock, prices and listing per branch, with each item's change history.
    - Its 20 most recent purchase orders.
    - Admins may read these but not change them. They cannot open a single order: the backend gives order details only to the organizations involved.

- **Documents:** the review queue across all organizations (`GET /admin/documents`).
  - Filter by status: awaiting review, approved or rejected.
  - From each row: download the file, approve it, reject it with a reason, or open the organization.
- **Users:** every account, with a name or email search and a filter for platform administrators.
  - Each row shows the phone (with "Verified by SMS" for accounts verified before SMS verification was removed), the registration date, active or inactive, and admin.
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
| Admin | `GET /admin/organizations`, `GET /admin/organizations/counts`, `GET /admin/organizations/{id}`, `POST .../review`, `GET /admin/documents`, `GET .../download`, `POST .../review`, `GET/PATCH /admin/users`, `GET /admin/insights/searches` |
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
| **Turn mandatory email verification on or off** | Whether registering an organization needs a verified email | The `EMAIL_VERIFICATION_REQUIRED` environment variable on Render. It changes behaviour, not the schema, and needs no migration |

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
5. **Configure email** on Render *before* deploying code that requires it (`EMAIL_PROVIDER`, the provider key, `EMAIL_FROM_ADDRESS`, `FRONTEND_BASE_URL`; see [Email verification](#email-verification)). Until a provider is configured, new pharmacies and suppliers cannot register, or set `EMAIL_VERIFICATION_REQUIRED=false` deliberately.
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
| Environment | `DATABASE_URL` (Neon), `JWT_SECRET_KEY` (**at least 32 random characters**, or the service will not start), `APP_ENV=production` (also the default), `EMAIL_PROVIDER`, `RESEND_API_KEY` or `BREVO_API_KEY`, `EMAIL_FROM_ADDRESS` and `FRONTEND_BASE_URL` (the Netlify URL; see [Email verification](#email-verification)), `CORS_ORIGINS` (must include the Netlify URL, for example `https://your-site.netlify.app`), `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `SUPABASE_BUCKET_NAME=organization-documents`. Leave `TRUSTED_CLIENT_IP_HEADER` unset unless `tools/render-ip-check` has verified a header |

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
- Configure a real email provider and domain for verification emails (see [Email verification](#email-verification)).
- Password reset (by emailed link, reusing the email provider).
- Subscription plans and Mobile Money payments (not part of registration today).
- PostGIS for distance search at scale (bounding-box and haversine search is used today).
- Notifications (email/WhatsApp) for order status changes.
