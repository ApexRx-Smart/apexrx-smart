# Plan: Admin dashboard and Supabase document storage

Branch: `feature/admin-dashboard-supabase-storage`, from the latest `main` (4f8d787, includes #19). A copy of this plan goes in `ai/plans/` per the org rules.

## Context

ApexRx needs a working admin console to verify pharmacies and suppliers. It also needs durable storage for verification documents: Render's free disk is wiped on every restart or deploy, so uploaded files are lost today.

The inspection found that the backend already does nearly all of the admin work:
- `backend/app/api/admin.py` has list, filter, detail, review and transition endpoints.
- It enforces the `ORG_TRANSITIONS` rules and blocks approval while documents are pending.
- It reviews documents and handles admin downloads.
- Every endpoint uses `AdminUser` (`deps.require_platform_admin`, which checks `is_platform_admin`).
- `frontend/js/api.js` already wraps all of these endpoints.

So the work is:
1. Swap the storage module.
2. Add one static admin page.
3. Add tests.
4. Make two small hardening tweaks.

The existing endpoints, models, schemas, JWT auth and patient search are not changed.

## 1. Supabase storage (backend)

**Dependency decision.**
- The official `supabase==2.34.0` package does not install alongside the pinned `PyJWT==2.10.1`; the dry-run fails with ResolutionImpossible.
- It would also add auth, realtime, websockets and postgrest, which we don't need.
- Instead, use **`storage3==2.34.0`**. It is Supabase's official Storage client, the same module that `supabase` exposes as `client.storage`, and it installs with no conflicts.
- Its new packages are: `storage3`, `deprecation`, `h2`/`hpack`/`hyperframe`, `multidict`, `yarl` and `propcache`. `httpx` is already present and moves from requirements-dev into requirements.txt.
- If the full client is ever needed, it is a one-line swap of the constructor.

**`backend/app/core/config.py`.** Add:
- `supabase_url: str | None`
- `supabase_secret_key: SecretStr | None` (masked in reprs and logs)
- `supabase_bucket_name: str = "organization-documents"`
- `document_storage: Literal["auto","supabase","local"] = "auto"`. With `auto`, Supabase is used when `SUPABASE_URL` and the key are set; otherwise local disk is used (local development and tests).

**`backend/app/services/storage.py`.** Keep the public functions, so callers barely change.
- **`save_document(org_id, upload)`:**
  - Read at most `max_upload_size_bytes + 1` bytes; anything larger returns 413.
  - Keep the existing checks: allowed MIME type (415), empty file (400), magic-number check (415).
  - Then write through the backend.
  - The key format is unchanged: `org-<id>/<32 hex chars>.<ext>`. It is generated on the server and never uses the client's file name, so there is no path traversal and no collisions. Uploads use `upsert=false`, so nothing is ever overwritten.
- **`read_document(key) -> bytes`:** new. Raises `NotFound` if the object is missing.
- **`delete_document(key)`:** failures are logged and swallowed, because the database row is already gone.
- **Backends:**
  - `LocalBackend`: today's code.
  - `SupabaseBackend`: `SyncStorageClient(f"{url}/storage/v1", {apikey, Authorization: Bearer})` with a timeout.
  - The backend is chosen once, and tests can override it.
- **Errors:**
  - Supabase or network failures become `AppError(503, "Document storage is temporarily unavailable.")`.
  - Logs include the key and the error class only. Credentials are never logged.

**`backend/app/api/organizations.py`.**
- `document_file_response` returns a `Response(content=bytes)`. It sets `Content-Type` from the stored `mime_type`, `Content-Disposition: attachment; filename*=…`, `Cache-Control: no-store` and `X-Content-Type-Options: nosniff`.
- That makes downloads **authenticated backend streaming**: no signed or public URL ever reaches the browser, and the bucket stays private.
- Upload and delete keep their current order: upload first, then the database commit, then cleanup on failure.

**Authorization is unchanged and covered by tests.**
- Organization downloads go through `get_org_access`, which returns 404 for anyone who isn't a member.
- Admin downloads go through `AdminUser`.

**Existing documents.**
- Keys stay in the same format and the `storage_key` column is reused, so **no database migration is needed**.
- Files that only ever lived on Render's ephemeral disk are almost certainly gone already. Their download returns a clear 404: "file missing from storage, ask the organization to re-upload". Metadata and review history stay intact. Nothing is silently deleted.
- Add `backend/app/scripts/migrate_documents_to_supabase.py`. It runs a dry run by default and uploads local `UPLOAD_DIR` files under the same key with `--apply`. It is not run against production without your approval.
- You run a read-only check in the Neon SQL editor: `SELECT count(*), min(uploaded_at), max(uploaded_at) FROM organization_document;`

**`backend/app/scripts/check_storage.py`** (new). It confirms the configured bucket exists and is **private**, then does a round trip with a dummy object (`healthcheck/<random>.txt`): upload, download, then delete. It prints no secrets.

## 2. Admin account (`create_admin.py`)

How it works today:
- It uses `SessionLocal` from `app.core.database`, which runs on `settings.database_url`.
- That value comes from the `DATABASE_URL` environment variable, otherwise from `backend/.env`.
- If the email exists, it **promotes** the user (admin plus active, password unchanged). Otherwise it **creates** the user, with the password from `APEXRX_ADMIN_PASSWORD` or a hidden prompt.

Small safety change:
- Print the target `host/database` (never the password).
- Require typing `yes` before writing, unless `--yes` is passed.

It is not run against production. The final report gives the exact command.

## 3. Admin dashboard (frontend, no framework)

New files:
- `frontend/admin.html`: `noindex`, not linked from public pages. It loads `config.js`, then `api.js`, then `admin.js`.
- `frontend/js/admin.js`
- `frontend/css/admin.css`: reuses the palette variables from `pharmacies.css`.

English only, consistent with the existing pages' look.

**A. Login, logout and session.**
- Sign in with `ApexAPI.auth.login`, then `auth.me`.
- If `is_platform_admin` is false, show "This account is not an ApexRx administrator" and clear the session. The backend still enforces this on every call; the page's check is only for user experience.
- The token stays in `sessionStorage` through `api.js`, as it does today.
- When `apexrx:signed-out` fires (any 401), return to login with "Session expired".
- A **Sign out** button is included.

**B. Overview.** Seven counts: total, pharmacies, suppliers, pending, approved, rejected and suspended. Each comes from the `total` of `GET /admin/organizations?limit=1&…`, run in parallel, so **no new endpoint** is needed.

**C. Organizations table.**
- Columns: name, type, registered date (`created_at`), status, email and phone.
- Filters: type and status dropdowns, plus a name/email search (`q`).
- Previous/next pagination.

**D. Detail panel** (`GET /admin/organizations/{id}`):
- Profile, contacts, review notes and dates.
- Locations, with address, phone, coordinates and active state.
- Members, with name, email and role.
- Documents.

Action buttons appear only when the backend's transition table allows them. The backend remains the authority, and 409 messages are shown as returned.
- **Approve:** disabled while documents are pending, with the reason shown.
- **Reject:** asks for a reason.
- **Suspend:** shown for approved organizations only, and asks for a reason.

**E. Documents.**
- Each document shows type, file name, size, upload date, status and rejection reason.
- **Download** uses `ApexAPI.admin.downloadDocument`, which returns a blob through an object URL.
- **Approve** and **Reject** (with a reason) are available on pending documents.

**`api.js` tweak.** `download()` will also clear the session and emit `apexrx:signed-out` on 401, matching `request()`. Patient search is untouched.

## 4. Tests (existing pytest structure, local Postgres `apexrx_v6_test`)

**Test setup.**
- `conftest.py` gets a fixture that installs a **fake Supabase client**: an in-memory dict with the storage3 `from_(bucket).upload/download/remove` interface.
- It goes through the real `SupabaseBackend`, plus a "fail" switch to simulate outages.

**`tests/test_admin.py`.**
- Admin login works, and the admin endpoints return 200.
- An ordinary user gets 403 on every admin endpoint. Unauthenticated requests get 401. Tampered or expired JWTs (built with PyJWT, past `exp`) get 401.
- Listing works, and the type, status and `q` filters work. Detail includes locations, members and documents.
- Approving, rejecting and suspending persist in the database, checked with SQL.
- Invalid transitions get 409. Approval with pending documents gets 409. Rejecting or suspending without notes gets 422.

**`tests/test_documents.py`.**
- An upload goes to the fake bucket at `org-<id>/<hex>.pdf`, and its metadata row matches.
- An admin download returns the exact bytes and headers. The organization's own member can download it.
- A member of another organization gets 404. An ordinary user on the admin download gets 403. Unauthenticated gets 401.
- Wrong type, spoofed magic number, oversize (via a monkeypatched limit) and empty file are all rejected, with nothing stored.
- During a Supabase outage, upload returns 503 with no database row, and download returns 503. A missing object returns 404.
- Deleting a pending document removes the object.

**Live Supabase test (opt-in).**
- `tests/test_supabase_live.py` is skipped unless `SUPABASE_LIVE_TESTS=1`.
- It does a real round trip under the `test-<random>/` prefix with a dummy PDF, then cleans up.
- To run it, you would put `SUPABASE_URL`, `SUPABASE_SECRET_KEY` and `SUPABASE_BUCKET_NAME` in `backend/.env`, which is git-ignored. Never paste them in chat.

**Regression.** The full existing suite (search, registration, orders) still has to pass, and `ruff check` must be clean.

**UI (org rule).** `frontend/tests/e2e_admin.py` (Playwright) runs against the local backend and server:
- A non-admin is refused.
- An admin signs in and the counts render.
- The filters work.
- Opening a pending organization works; the documents download and are approved.
- The organization is approved, and its status changes.
- A rejection with a reason works.
- Sign out returns to login.

## 5. Docs and deployment notes

Update the root README and `backend/.env.example` with placeholders only:
- The new environment variables: `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `SUPABASE_BUCKET_NAME`, and optionally `DOCUMENT_STORAGE`.
- The new dependency.
- That no Alembic migration is needed.
- The bucket must stay private.
- The admin dashboard URL (`/admin.html`).
- How to create the admin.
- Step-by-step steps to deploy and verify on Render, Netlify and Supabase.

Nothing is pushed, deployed, migrated or written to production. You review first.

## Org-process notes
- The plan is saved under `ai/plans/`.
- A GitLab ticket can't be created: there's no GitLab access and the repo is on GitHub.
- Committing the conversation log with the host IP would publish network details, so it stays held, as raised before.
- The Playwright script is included.

## Verification (what I will run locally)
1. `pytest` (new and existing tests) and `ruff check app tests alembic`.
2. Start uvicorn against the local test database and serve `frontend/` on port 5501. Run `e2e_admin.py`, and re-run the existing patient-search check.
3. Only if you add the Supabase variables to `backend/.env`: run `python -m app.scripts.check_storage` and the live test.
