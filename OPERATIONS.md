# ApexRx operations runbook

How to deploy, check, back up, recover and watch ApexRx, with the patient
reservation system. It describes procedures; it creates nothing.

Every fact here is marked one of two ways:
- **Verified in the repository**: true of this code and its documentation.
- **To confirm on the account**: depends on the Render, Neon, Netlify or Supabase plan or settings, which were not inspected.

Never paste credentials into this file, a ticket or a chat.

**Contents**
1. [Architecture](#1-architecture)
2. [Database roles](#2-database-roles)
3. [Backups and recovery](#3-backups-and-recovery)
4. [Deploying the reservation release](#4-deploying-the-reservation-release)
5. [Health checks and monitoring](#5-health-checks-and-monitoring)
6. [Infrastructure facts and limits](#6-infrastructure-facts-and-limits)
7. [Security configuration checklist](#7-security-configuration-checklist)

---

## 1. Architecture

| Part | Service | Verified in the repository | To confirm on the account |
|---|---|---|---|
| Frontend | Netlify (static, publish directory `frontend`, no build) | `frontend/js/config.js` holds the backend URL. Every request goes through `js/api.js`, with a 45-second timeout. | Plan, bandwidth and the deploy trigger |
| Backend | Render web service, root `backend` | Started with `uvicorn app.main:app --host 0.0.0.0 --port $PORT`, with no `--workers` flag, so **one process**. The README says the free plan sleeps after about 15 minutes idle and takes up to a minute to wake. | Plan, whether it sleeps, instance size, Health Check Path, auto-deploy on `main` |
| Database | Neon PostgreSQL (production server reported PostgreSQL 18.7 earlier) | One SQLAlchemy engine per process with library defaults: a pool of 5 connections plus up to 10 overflow, and `pool_pre_ping`. TLS comes from `?sslmode=require` in the URL. | Plan, compute auto-suspend delay, compute-hour allowance, connection limit, point-in-time restore window, pooled or direct endpoint |
| Documents | Supabase Storage, private bucket | Files are streamed by the backend and never served from a public URL. `python -m app.scripts.check_storage` verifies the bucket is private. | Storage quota and plan |
| Reservation expiry | Scheduled command (not created yet) | `python -m app.scripts.expire_reservations`; see the README section "Reservation expiry job" | Whether Render Cron Jobs are available on the plan, and their cost |

**Failure modes:**

| Failure | What users see | What still works |
|---|---|---|
| Neon down | Everything signed in fails with 503 "A database error occurred". | The landing page renders, but search returns errors. |
| Render down or asleep | Every API call waits or fails. The frontend shows "Still working… the server may be starting up" after 4 seconds, and the request times out after 45. | Nothing that needs the API. |
| Supabase down | Document uploads and downloads return 503. | Everything else. |
| The expiry job not running | Reservations still count as expired at their deadline, but nobody gets the expiry notification and the stored status lags. | Everything else. |

## 2. Database roles

### What each process needs (verified in the repository)

| Process | Needs | Must not have |
|---|---|---|
| **API** (`uvicorn`) | `USAGE` on schema `public`; `SELECT, INSERT, UPDATE, DELETE` on all tables; `USAGE, SELECT` on all sequences; `EXECUTE` on functions (granted to `PUBLIC` by default) | Ownership of the tables, superuser, `TRUNCATE`, permission to set `session_replication_role`, `REPLICATION` |
| **Expiry job** | The same as the API: it selects, updates `reservation` and inserts into `notification` | The same |
| **Migrations** (`alembic upgrade head`) | Ownership of the schema objects: CREATE, ALTER and DROP for tables, functions, triggers and views | It's only used by an operator, during a deployment |

**Why the safeguards depend on this.**
- The reservation, stock and order rules are enforced by triggers. A role can get around them if it:
  - **owns the tables**: `ALTER TABLE … DISABLE TRIGGER`, `DROP TRIGGER`;
  - **is a superuser**, or **may set `session_replication_role`**: either can turn triggers off for its session;
  - **has `TRUNCATE`**: it empties a table without firing its row-level delete protection.
- The table owner can also drop tables. So **if the API connects as the owner, a bug or an injected statement in the API could disable the safeguards or destroy data.**
- What's known about production: earlier migrations ran as `neondb_owner`, and the API probably uses the same URL. **Unverified.**

**Separating the roles is possible without changing any code.**
- Alembic reads the same `DATABASE_URL` setting. The operator runs migrations with the owner's URL in their own shell, while Render keeps a restricted role's URL.
- Importing the settings also requires a valid `JWT_SECRET_KEY` in that shell. Any 32-character random value works for running migrations.

### Production verification (to run with your account; read-only)

1. On your machine, from `backend/`, set `DATABASE_URL` to **the URL the Render API service uses**. Copy it from the Render dashboard into your shell only, never into a file in the repository. Set `JWT_SECRET_KEY` to any 32-character value.
2. Run `python -m app.scripts.check_db_role`. It opens one `READ ONLY` transaction, reads role attributes and privileges, rolls back, and prints the host, database, role name and yes/no answers. It never prints credentials.
3. **Expected result for a safe role:** exit 0, with "OK: this role cannot disable the safeguards and has what the API and the expiry job need". That means:
   - `superuser: no`;
   - `owns guarded tables: none`;
   - `may set session_replication_role: no`;
   - `TRUNCATE on guarded tables: none`;
   - `missing privileges the API needs: none`;
   - `connection encrypted: yes`.
4. **Failure conditions:**
   - **Exit 1, "can get around the database safeguards":** the role owns the tables, is a superuser, may set `session_replication_role`, has `TRUNCATE`, or has `REPLICATION`. Blocks launch.
   - **Exit 1, "lacks privileges":** the API would fail on some operation. Fix the grants first.
   - **Exit 2:** the check couldn't connect. Nothing was learnt.
   - **Warnings** (role or database creation, `CREATE` on the schema, `TRIGGER`, an unencrypted connection) don't fail the check but should be removed.

### If it fails: a restricted application role (requires your approval; not done)

Plan this only after confirming who owns the schema: `SELECT tableowner, count(*) FROM pg_tables WHERE schemaname = 'public' GROUP BY 1;`. Then, as the owner, in the Neon SQL editor on a **branch first**:

```sql
CREATE ROLE apexrx_app LOGIN PASSWORD '<generated in Neon, never written down here>';
GRANT USAGE ON SCHEMA public TO apexrx_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO apexrx_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO apexrx_app;
-- Objects created by later migrations (run as the owner) get the same grants:
ALTER DEFAULT PRIVILEGES FOR ROLE <owner> IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO apexrx_app;
ALTER DEFAULT PRIVILEGES FOR ROLE <owner> IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO apexrx_app;
```

Neon may manage roles through its console or API; use whichever it requires.

Then:
1. Run `check_db_role` with the new role's URL. It must exit 0.
2. Run the test suite against the branch.
3. Switch the Render API's `DATABASE_URL` and the expiry job to the new role.
4. Keep the owner URL for migrations only.

## 3. Backups and recovery

### Terms

| Term | What it is | Restores to |
|---|---|---|
| **Backup** | Any copy you can restore from. Below it means one of the three mechanisms. | — |
| **Neon branch** | An instant copy-on-write copy of a branch at one moment. It costs nothing until it diverges, and can be queried and promoted. | The moment it was created |
| **Point-in-time restore** | Rebuilding a branch at an earlier time from Neon's history. The available window depends on the plan. | Any moment inside the history window |
| **Logical export** | `pg_dump` to a file you keep outside Neon; restored with `pg_restore` or `psql`. | The moment of the dump |

**Status:**
- **Nothing is verified as configured.** The README's earlier migrations used a Neon branch before each migration (for example `pre-c4d1e8f2a9b7`); whether those branches still exist is unknown.
- **Neon's point-in-time history window on this account is to be confirmed in the Neon console.** Don't assume one exists or how long it is.
- **No logical export is produced anywhere today.**

### Before every migration or risky change

1. **Neon branch** from production, named `pre-<revision>-<date>` (for example `pre-c8e5a1f7d2b9-2026-11-20`). This needs your account and approval.
2. **Logical export** (recommended for this release, because the reservation migration can't be downgraded once data exists):
   - `pg_dump --format=custom --no-owner --file apexrx-<date>.dump "<owner URL>"`;
   - use a `pg_dump` at least as new as the server (18);
   - keep the file outside the repository, encrypted.
3. **Record counts** (read-only, SQL editor):
   ```sql
   SELECT (SELECT version_num FROM alembic_version) AS revision,
          (SELECT count(*) FROM app_user) AS users, (SELECT count(*) FROM organization) AS orgs,
          (SELECT count(*) FROM stock) AS stock_rows, (SELECT count(*) FROM stock_adjustment) AS adjustments,
          (SELECT count(*) FROM purchase_order) AS orders, (SELECT count(*) FROM notification) AS notifications;
   ```

### Recovery options, and what each loses

| Situation | Recover by | Data lost |
|---|---|---|
| A migration failed | Nothing to restore. Each migration runs in one transaction, so a failure rolls back completely; check `alembic_version` is unchanged. | None |
| A migration succeeded, but the release must be withdrawn before real use | Fix forward (section 4). Or restore the pre-migration branch, if no reservation data matters yet. | Everything written after the branch was created |
| Data was corrupted or deleted | Point-in-time restore just before the incident, if the plan allows. Otherwise the most recent branch, or the logical export. | Everything after the restore point |
| Neon project lost | The logical export, into a new project | Everything after the export |

**Restoring a branch.** Make it the database the API uses (Neon's branch-restore feature, or point `DATABASE_URL` at it). Then confirm `/health` shows the schema matching the deployed code. An older branch can be at an older migration revision.

### Checking restored data is consistent (read-only)

1. The counts above match what you expect for the restore point.
2. `alembic_version` matches the code that will run against it.
3. These invariant queries each return **0**:

```sql
-- Every collected reservation has its collection record, and vice versa.
SELECT count(*) FROM reservation r LEFT JOIN reservation_collection c USING (reservation_id)
 WHERE (r.status = 'collected') <> (c.reservation_id IS NOT NULL);
-- Every collection's deduction is a real stock adjustment.
SELECT count(*) FROM reservation_collection c LEFT JOIN stock_adjustment a ON a.adjustment_id = c.deduction_adjustment_id
 WHERE a.adjustment_id IS NULL;
-- No stock row is negative.
SELECT count(*) FROM stock WHERE quantity < 0;
-- Every reservation's last history row is its current status.
SELECT count(*) FROM reservation r JOIN LATERAL (
  SELECT to_status FROM reservation_status_history h WHERE h.reservation_id = r.reservation_id
  ORDER BY changed_at DESC, history_id DESC LIMIT 1) last ON true WHERE last.to_status <> r.status;
```

4. Run `python -m app.scripts.check_storage` against the restored setup. Document files live in Supabase and aren't part of a database restore, so check that the rows' storage keys still resolve.

### Recovery rehearsal (on a disposable branch; requires your approval)

1. Create a branch `rehearsal-<date>` from production.
2. On your machine, with `DATABASE_URL` set to the **branch's** owner URL:
   - `alembic current`;
   - `alembic upgrade head`;
   - the queries above;
   - `python -m app.scripts.expire_reservations --check`.
3. Run `pg_dump` of the branch, then restore it into another empty branch, and repeat the queries.
4. Delete both branches.

This exercises the migration, the export and the restore without touching production.

## 4. Deploying the reservation release

**What changes.**
- The working tree adds migration `c8e5a1f7d2b9` on top of `b7c3e9d1f4a6`. It's verified as the single head; remote `main` is `46ff706`, the branch's base.
- The migration adds tables, triggers and indexes, alters `product` and `notification`, redefines the `stock_log_adjustment` function, and replaces the `patient_availability` view.

**Downgrades.** The migration refuses to downgrade once any reservation, unit acknowledgement or product-settings history exists, and the first time an admin classifies a medicine creates history. **Treat the migration as one-way.**

**Compatibility of mixed versions:**

| Database | Backend | Frontend | Result |
|---|---|---|---|
| new | old | old | The old code's `/health` returns 503: it expects `b7c3e9d1f4a6`, and the check requires an exact match, so a Render health check would block deploys. Requests are **expected** to keep working, because the migration keeps the old columns and adds only nullable or defaulted ones, but this is **not tested**. Rehearse it on a branch if you rely on it. |
| new | new | old | Works. The old frontend calls no reservation endpoint. |
| old | new | any | **Broken.** The models expect the new columns, so signed-in features return 503 and `/health` returns 503. Never deploy the backend before the migration. |
| new | new | new | The target state |
| new | old | new | Reservation screens show errors (404s); the Reserve block hides itself. |

### Order (each step needs your approval; nothing has been run)

1. **Freeze.** Pause merges to `main` while deploying, because Render auto-deploys `main` (to confirm in the Render settings).
2. **Back up** (section 3): a Neon branch and a logical export, and record the counts.
3. **Verify the migration on a branch.** Run the rehearsal from section 3 with this release's code. `alembic upgrade head` must succeed, and `alembic current` must show `c8e5a1f7d2b9`.
4. **Migrate production.** From your machine, with the **owner** URL, run `alembic upgrade head`, then `alembic current`. The old backend keeps serving: its `/health` reports outdated, but its requests work.
5. **Deploy the backend.** Merge to `main` or trigger a deploy. Check that `/health` returns 200 with `"schema": "up to date"`.
6. **Deploy the frontend** to Netlify.
7. **Create the expiry job** (README, "Reservation expiry job"). It refuses to run against an outdated schema, so doing this before step 4 would be harmless but useless.
8. **Check the role:** `check_db_role` with the API's URL (section 2).
9. **End-to-end check,** with a test pharmacy and a test patient that you create through the app:
   - search for a classified medicine, reserve it, and see the request in the pharmacy dashboard;
   - confirm it, see the patient's update, collect it with the reference, and check the stock dropped by the quantity;
   - cancel a second reservation.
   - Do **not** use `database/seed_test_data.sql`: it's for local test databases only and must never be applied to a deployed database.
10. **Watch for 24 hours** (section 5): `/health`, the Render logs, and the first expiry runs.

### When something goes wrong

- **The migration fails.** It rolled back. Read the error, fix it on a branch and repeat step 3. Production is unchanged.
- **The migration succeeded but the backend deploy failed.** The old backend still serves (its `/health` reports outdated). Fix and redeploy the new backend. Don't roll the database back.
- **The new backend has a bug.**
  - **Fix forward:** ship a corrected build on the same schema.
  - **Short term:** stop new reservations of a medicine by classifying it as not reservable in the admin console (for example prescription-only): confirmed reservations stay collectable, and no new request or confirmation is possible. (Since `d4a7e2c9b1f8` the per-medicine `reservation_enabled` switch is retired.) A pharmacy can also stop new requests at one branch by raising its minimum stock.
  - **Avoid** rolling application code back to a version older than the schema. If it's unavoidable, expect `/health` to report 503 and turn off the Render health-check gate while it runs.
- **Data damage.** Restore (section 3). Know what's lost first.

### Migration `d4a7e2c9b1f8`: branch minimum stock, stock held from the request

**What changes** (on top of `c8e5a1f7d2b9`; single head):
- `location.reservation_min_stock INTEGER NOT NULL DEFAULT 0` with a CHECK (0 to 1,000,000). Every existing branch gets 0, so nothing is kept back until a pharmacy sets it.
- New function `reservation_allocated()` and partial index `idx_reservation_open_hold`.
- Replaced (same signatures): `reservation_ineligibility()` (no per-medicine switch, no branch acknowledgement; a pack needs a pack size), the reservation insert and update triggers (a request needs reservable stock and locks the stock row; confirmation needs the stock to cover it after the other holds), and the `patient_availability` view (requests hold stock too; same columns).
- No table or column is dropped. `product.reservation_enabled` and `offer_unit_acknowledgement` stay with their rows; nothing reads them.

**Downgrade:** `alembic downgrade c8e5a1f7d2b9` restores the previous functions, triggers and view and drops the index, the function and the column (losing only the branch minimums). It was run on local test databases only. Don't run it on a shared database to "test" it.

**Mixed versions (tested locally, 2026-11-22):** the deployed `main` backend code was run against a local database migrated to `d4a7e2c9b1f8`, and 26 checks of its flows passed: sign-in, catalogue and settings, registration, branches, approval, stock, offers, unit acknowledgement, options, reservations, confirmation, collection, decline, cancellation, inventory, public search and lists.

| Database | Backend | Result |
|---|---|---|
| `d4a7e2c9b1f8` | `main` (old) | Requests work. `/health` returns **503** "schema outdated", because the check requires an exact match. A request beyond the reservable stock gets main's generic 409 with the database's message. If Render's Health Check Path is `/health`, a deploy, restart or wake-up of the old code may not be marked healthy. |
| `d4a7e2c9b1f8` | this branch | The target. `/health` 200. |
| `c8e5a1f7d2b9` | this branch | **Broken**: the model expects `location.reservation_min_stock`. Never deploy the branch before the migration. |

**Order for a shared or production database** (each step needs approval): back up (section 3), then `alembic upgrade head` with the owner URL, then deploy the backend, then the frontend. Keep the gap between the migration and the backend deploy short, because the old backend's `/health` reports 503 in between.

## 5. Health checks and monitoring

### `/health` (verified in the repository)

| Response | Meaning |
|---|---|
| `200 {"status":"healthy","database":"connected","schema":"up to date"}` | The process is running, and a `SELECT 1` and the migration check both pass. |
| `503 "Database unavailable."` | The database can't be reached. |
| `503 "Database schema is not up to date (database: X, code expects: Y)…"` | The migration and the code don't match. |

It doesn't check Supabase Storage (use `python -m app.scripts.check_storage`), email (disabled), or the expiry job. Startup also logs the schema problem at CRITICAL.

**Recommendation:** set Render's Health Check Path to `/health`, to confirm on the account. Render then doesn't switch traffic to a deploy whose database isn't migrated. During a deliberate code rollback (section 4), turn it off.

### Client IP and login rate limiting (verified in the repository)

- **Leave `TRUSTED_CLIENT_IP_HEADER` unset.** Without it, the per-IP login limit is **not active** on Render: every request comes from a private proxy address, and the code skips the per-IP limit rather than lumping everyone into one bucket. The per-account and per-browser limits still apply, and startup logs a warning.
- **Never use `X-Forwarded-For`.** Render appends to it without clearing it, so it can be forged; the settings refuse it.
- **To enable per-IP limiting:** follow `tools/render-ip-check` on a temporary Render service. Only a header that shows your real IP from two networks and ignores forged values may be set.
- **Counters are in process memory** (`memory://`). That fits one process; they reset on restart.

### What to watch, and what to do

| Problem | How it shows | What to do |
|---|---|---|
| API outage | `/health` doesn't answer; Render shows the service down; the frontend shows "Cannot reach the ApexRx server". | Check Render's events and logs. If it's asleep (free plan), the first request wakes it. |
| Database connectivity | `/health` returns 503 "Database unavailable"; the logs show `Database error` with a SQLSTATE. | Check Neon's status and whether the compute is suspended or out of compute hours. |
| Schema mismatch | `/health` returns 503 "schema is not up to date"; there's a CRITICAL log at startup. | Run the missing migration (section 4) or deploy matching code. |
| Expiry job failed | A non-zero exit in the cron job's history; the last log line is `reservation_expiry.failed` (with the error class and SQLSTATE) or `.refused`. | Read the line. `refused` means the schema doesn't match; `failed` is usually connectivity. Nothing is half-done, and the next run retries. |
| Expiry backlog | `remaining_due` above 0 run after run, or `--check` showing `due` growing. | Look for long transactions holding rows. Raise `--max-batches` or run the job by hand. |
| Expiry job not running at all | No new runs in the history; patients get no expiry updates. | Check the cron service. Reservations still behave correctly by time. |

**Free options only.**
- Render's own logs, events and failure emails, if enabled on the account.
- Neon's console.
- An external uptime pinger hitting `/health` would add a new service and needs your approval. On a sleeping free plan it would also keep the instance awake.

## 6. Infrastructure facts and limits

**Verified in the repository:**
- **One uvicorn process,** with a database pool of 5 plus up to 10 overflow connections. The expiry job opens its own short-lived connection per batch and closes its pool at exit.
- **Browser request timeout:** 45 seconds.
- **Uploads:** 10 MB by default (`MAX_UPLOAD_SIZE_BYTES`), PDF, PNG or JPEG.
- **Sessions:** 30 minutes idle, 12 hours maximum. Tokens live in `sessionStorage`.
- **Expiry job:** proposed every 15 minutes. An empty run is one indexed query.

**To confirm on the accounts (not assumed here):**
- **Render:**
  - plan, and whether the web service sleeps;
  - **whether Cron Jobs are available, and their cost** (a separate service type);
  - minimum cron interval, maximum run time, instance memory.
- **Neon:**
  - plan, compute-hour allowance, auto-suspend delay;
  - **point-in-time restore window**;
  - maximum connections, and whether to use the pooled or direct endpoint (migrations should use the direct one).
  - A job every 15 minutes wakes a suspended compute up to 96 times a day. Check this against the allowance before choosing a shorter interval.
- **Netlify:** plan and bandwidth.
- **Supabase:** storage quota and plan.

**Effect of a sleeping Render backend.** A patient's first search or reservation after an idle period waits for the wake-up, up to about a minute per the README. The page explains the wait, and retries are safe: submissions are idempotent.

## 7. Security configuration checklist

| Setting | Required | Verified in code |
|---|---|---|
| `JWT_SECRET_KEY` | 32+ random characters, not a placeholder | The service refuses to start otherwise. |
| `APP_ENV` | `production` on Render | Any other value on Render stops start-up; the mock email and `/dev` routes are off in production. |
| `DATABASE_URL` | The **restricted** role (section 2), `sslmode=require` | `check_db_role` reports encryption and role safety. |
| `CORS_ORIGINS` | Exactly the Netlify origin(s) | The defaults are localhost only; credentials are not allowed. |
| `TRUSTED_CLIENT_IP_HEADER` | Unset, unless `tools/render-ip-check` verified one | `X-Forwarded-For` is refused. |
| `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `SUPABASE_BUCKET_NAME` | Set on Render only, never in the frontend | `check_storage` verifies the bucket is private. |
| Error responses | Validation errors never echo submitted values; database errors return a generic 503 | `app/core/errors.py` |
| Logs | The expiry job logs counts only. API database errors log the SQLSTATE and stack trace, but the engine runs with `hide_parameters=True`, so statement parameters (phones, notes, names, tokens) never reach the logs. Request bodies are not logged. | `app/core/database.py`, `tests/test_config_security.py` |
| Sessions | Bearer tokens in `sessionStorage`, server-side sessions, `Cache-Control: no-store` on signed-in responses. No cookies, so no cookie flags to set. | |
