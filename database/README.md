# ApexRx Smart database

PostgreSQL + PostGIS. The schema implements the platform's core rule:
**only verified pharmacies (NPC number) can see supplier stock and prices,
and a supplier never sees another supplier.**

## Contents

| File | Purpose |
|---|---|
| `01_schema.sql` | Types, tables, indexes, row-level security (RLS) rules, views, search function |

Demo data and a `reset.sh` script will be added in a later commit.

## Requirements

- PostgreSQL **15 or newer** (tested on 16 and 18, recommended: 18)
- PostGIS (distance between pharmacies and patients)
- Extensions `pg_trgm` (typo-tolerant search) and `pgcrypto`, both included in `postgresql-contrib`

Installation on Ubuntu 24.04 (version 18 comes from the official PostgreSQL repository):

```bash
sudo apt install -y postgresql-common
sudo /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh
sudo apt install -y postgresql-18 postgresql-18-postgis-3
```

## Create the database

From the project root:

```bash
sudo -u postgres dropdb --if-exists apexrx
sudo -u postgres createdb apexrx
sudo -u postgres psql -d apexrx -v ON_ERROR_STOP=1 -q < database/01_schema.sql
```

Check it worked:

```bash
sudo -u postgres psql -d apexrx -c "SELECT postgis_version();" -c "\dt"
```

## Schema overview

- **Identity**: `app_user`, `organization` (pharmacy or supplier, with NPC / licence number and verification status), `membership`, `location`, `verification_document`
- **Normalised catalogue**: `drug` → `product` → `batch`
- **Stock and prices**: `stock` (pharmacies and suppliers), `negotiated_price`
- **Chat and negotiation**: `conversation`, `message`, `quote` (structured price offers), `rfq`
- **Orders**: `purchase_order`, `purchase_order_item`, `delivery` (delivery: table planned, not functional yet)
- **Premium**: `insurer`, `insurance_plan`, `subscription`, `payment`, `forecast`
- **Other**: `stock_alert`, `audit_log`, `refresh_token`

Two views for the API: `v_pharmacy_availability` (public) and `v_supplier_offers`
(verified pharmacies only). The function `search_pharmacy_availability(...)` powers
patient search, sorted by price or distance.

## Rules for the backend

1. The API connects with the **`apexrx_api`** role, never as `postgres` or the
   database owner: both bypass row-level security.
   Create the login account (choose a real password, never commit it):

```sql
   CREATE ROLE apexrx_api_login LOGIN PASSWORD '...' IN ROLE apexrx_api;
```

2. On every request, inside the transaction, the API says who is calling:

```sql
   SELECT set_config('app.org_id',   '<organization id, or empty>', true);
   SELECT set_config('app.is_admin', 'false', true);
```

3. Negotiated prices are per pharmacy: a price accepted in the chat is saved
   automatically in `negotiated_price` and is visible only to the two parties.

## Team conventions

- Every schema change goes through `01_schema.sql`, in a pull request.
- After a `git pull` that changes the schema, rebuild your local database with the commands above.
- Never commit a password or a `.env` file.
- Insurance rates, prices and NPC numbers in the demo data are **fictitious**.
  Real rates must come from the insurers.