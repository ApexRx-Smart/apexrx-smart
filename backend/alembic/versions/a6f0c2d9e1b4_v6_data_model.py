"""v6 data model: verified organizations, stock and offers, purchase orders

Replaces the initial batch-based schema with the ApexRx v6 MVP schema.
database/db_implementation_script.sql is the same schema as a standalone script.

Data handling on upgrade
------------------------
* app_user, drug and product rows are carried over with their ids. Users
  without a password hash get an unusable one and must have it reset.
* Legacy organization, membership, location, batch and stock rows are
  DROPPED. They do not fit the v6 model (organization type and verification
  status, batch-level stock, audited stock writes). Back them up first if
  they matter.

Also works on an empty database, so a fresh setup only needs
``alembic upgrade head``.

Revision ID: a6f0c2d9e1b4
Revises: 211f0e646448
Create Date: 2026-11-03 23:45:00

"""
from typing import Sequence, Union

from alembic import op

revision: str = "a6f0c2d9e1b4"
down_revision: Union[str, Sequence[str], None] = "211f0e646448"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


LEGACY_TABLES = (
    "stock", "batch", "product", "drug", "location", "membership", "organization", "app_user",
)

V6_TABLES = (
    "search_event",
    "purchase_order_status_history",
    "purchase_order_item",
    "purchase_order",
    "stock_adjustment",
    "product_offer",
    "stock",
    "product",
    "drug",
    "organization_document",
    "location",
    "membership",
    "organization",
    "app_user",
)

V6_FUNCTIONS = (
    "purchase_order_no_delete()",
    "purchase_order_item_guard()",
    "purchase_order_before_write()",
    "purchase_order_log_status()",
    "product_offer_before_delete()",
    "product_offer_before_write()",
    "stock_log_delete()",
    "stock_before_delete()",
    "stock_log_adjustment()",
    "stock_before_update()",
    "current_actor_id()",
    "set_updated_at()",
)

CARRIED_IDENTITIES = (("app_user", "user_id"), ("drug", "drug_id"), ("product", "product_id"))

# Verbatim from database/db_implementation_script.sql, without BEGIN/COMMIT
# (Alembic runs the whole migration in one transaction).
V6_SCHEMA_SQL = r"""
-- ---------------------------------------------------------------------------
-- Helper: keep updated_at current
-- ---------------------------------------------------------------------------
CREATE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at := CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- The authenticated user for this transaction, set by the application with
-- set_config('app.user_id', ..., true). Raises if it is missing or not a number.
-- (After a transaction ends the setting reverts to an empty string, so a
-- forgotten set_config on the next transaction is rejected, not inherited.)
CREATE FUNCTION current_actor_id() RETURNS BIGINT AS $$
DECLARE
    raw TEXT := NULLIF(btrim(current_setting('app.user_id', true)), '');
BEGIN
    IF raw IS NULL THEN
        RAISE EXCEPTION 'app.user_id is not set for this transaction';
    END IF;
    RETURN raw::BIGINT;
EXCEPTION WHEN invalid_text_representation THEN
    RAISE EXCEPTION 'app.user_id must be a numeric user_id, got %', raw;
END;
$$ LANGUAGE plpgsql STABLE;

-- ---------------------------------------------------------------------------
-- Identity and organizations
-- ---------------------------------------------------------------------------
CREATE TABLE app_user (
    user_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name VARCHAR(150) NOT NULL,
    email VARCHAR(255) NOT NULL,
    phone VARCHAR(30),
    password_hash TEXT NOT NULL,
    -- Platform-level administrator (ApexRx staff). Separate from membership roles.
    is_platform_admin BOOLEAN NOT NULL DEFAULT FALSE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX uq_app_user_email ON app_user (lower(btrim(email)));

CREATE TABLE organization (
    organization_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    type VARCHAR(20) NOT NULL
        CHECK (type IN ('pharmacy', 'supplier')),
    status VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'rejected', 'suspended')),
    phone VARCHAR(30),
    email VARCHAR(255),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- Admin review of the registration (covers approve / reject / suspend).
    reviewed_at TIMESTAMPTZ,
    reviewed_by BIGINT REFERENCES app_user(user_id),
    review_notes TEXT,
    -- Lets child tables reference (organization_id, type) to enforce org type.
    UNIQUE (organization_id, type),
    CHECK (status = 'pending' OR reviewed_at IS NOT NULL)
);

CREATE TABLE membership (
    membership_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES app_user(user_id) ON DELETE CASCADE,
    organization_id BIGINT NOT NULL
        REFERENCES organization(organization_id) ON DELETE CASCADE,
    -- owner:   full control of the org, including managing members
    -- manager: manages stock, prices and orders; cannot manage owners
    -- staff:   day-to-day stock updates / order handling
    role VARCHAR(30) NOT NULL
        CHECK (role IN ('owner', 'manager', 'staff')),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, organization_id)
);

-- A pharmacy branch or a supplier warehouse (the org's type says which).
CREATE TABLE location (
    location_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id BIGINT NOT NULL
        REFERENCES organization(organization_id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    address TEXT,
    city VARCHAR(100),
    region VARCHAR(100),
    latitude NUMERIC(9,6),
    longitude NUMERIC(9,6),
    phone VARCHAR(30),
    whatsapp_phone VARCHAR(30),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- Lets other tables prove a location belongs to a given organization.
    UNIQUE (location_id, organization_id),
    CHECK (latitude IS NULL OR latitude BETWEEN -90 AND 90),
    CHECK (longitude IS NULL OR longitude BETWEEN -180 AND 180)
);

-- Document types are free text until verification requirements are confirmed.
CREATE TABLE organization_document (
    document_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id BIGINT NOT NULL
        REFERENCES organization(organization_id) ON DELETE CASCADE,
    document_type VARCHAR(100) NOT NULL,
    file_name VARCHAR(255) NOT NULL,
    storage_key TEXT NOT NULL UNIQUE,
    mime_type VARCHAR(100) NOT NULL,
    file_size_bytes BIGINT NOT NULL CHECK (file_size_bytes > 0),
    verification_status VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (verification_status IN ('pending', 'approved', 'rejected')),
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reviewed_at TIMESTAMPTZ,
    reviewed_by BIGINT REFERENCES app_user(user_id),
    rejection_reason TEXT,
    CHECK (
        (verification_status = 'pending' AND reviewed_at IS NULL)
        OR (verification_status <> 'pending' AND reviewed_at IS NOT NULL)
    )
);

-- ---------------------------------------------------------------------------
-- Shared medicine catalogue
-- ---------------------------------------------------------------------------
CREATE TABLE drug (
    drug_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    therapeutic_class VARCHAR(255),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX uq_drug_name ON drug (lower(btrim(name)));

CREATE TABLE product (
    product_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    drug_id BIGINT NOT NULL REFERENCES drug(drug_id),
    product_name VARCHAR(255) NOT NULL,
    brand VARCHAR(255),
    strength VARCHAR(100),
    dosage_form VARCHAR(100),
    pack_size VARCHAR(100),
    barcode VARCHAR(100),
    manufacturer VARCHAR(255),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
-- Prevent duplicate catalogue entries (NULL-safe).
CREATE UNIQUE INDEX uq_product_identity ON product (
    drug_id,
    lower(btrim(COALESCE(brand, ''))),
    lower(btrim(COALESCE(strength, ''))),
    lower(btrim(COALESCE(dosage_form, ''))),
    lower(btrim(COALESCE(pack_size, ''))),
    lower(btrim(COALESCE(manufacturer, '')))
);
CREATE UNIQUE INDEX uq_product_barcode ON product (lower(btrim(barcode)))
    WHERE barcode IS NOT NULL AND btrim(barcode) <> '';

-- ---------------------------------------------------------------------------
-- Stock and offers
-- ---------------------------------------------------------------------------
-- Stock: quantity of a catalogue product held at a location.
-- Quantity is expressed in the product's defined sellable unit/pack.
CREATE TABLE stock (
    stock_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    location_id BIGINT NOT NULL
        REFERENCES location(location_id) ON DELETE CASCADE,
    product_id BIGINT NOT NULL REFERENCES product(product_id),
    quantity INTEGER NOT NULL DEFAULT 0 CHECK (quantity >= 0),
    -- Freshness timestamp. Bumped on every update, including "still accurate" confirmations.
    last_updated TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_by BIGINT REFERENCES app_user(user_id),
    UNIQUE (location_id, product_id)
);

-- Offer: a location lists a product at a price. Availability is derived from
-- stock.quantity and never stored a second time.
-- The composite FK guarantees every offer has a matching stock row.
CREATE TABLE product_offer (
    offer_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    location_id BIGINT NOT NULL,
    product_id BIGINT NOT NULL,
    unit_price NUMERIC(14,2) NOT NULL CHECK (unit_price >= 0),
    currency CHAR(3) NOT NULL DEFAULT 'RWF',
    low_stock_threshold INTEGER NOT NULL DEFAULT 5
        CHECK (low_stock_threshold >= 0),
    is_listed BOOLEAN NOT NULL DEFAULT TRUE,
    last_updated TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_by BIGINT REFERENCES app_user(user_id),
    UNIQUE (location_id, product_id),
    FOREIGN KEY (location_id, product_id)
        REFERENCES stock (location_id, product_id) ON DELETE CASCADE
);

-- Audit trail of quantity changes (also lets you measure update frequency).
-- change_type separates the first stock row, normal quantity edits and row deletion.
CREATE TABLE stock_adjustment (
    adjustment_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    location_id BIGINT NOT NULL REFERENCES location(location_id) ON DELETE CASCADE,
    product_id BIGINT NOT NULL REFERENCES product(product_id),
    old_quantity INTEGER CHECK (old_quantity IS NULL OR old_quantity >= 0),
    new_quantity INTEGER NOT NULL CHECK (new_quantity >= 0),
    changed_by BIGINT REFERENCES app_user(user_id),
    changed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    change_type VARCHAR(20) NOT NULL DEFAULT 'quantity_update'
        CHECK (change_type IN ('initial_stock', 'quantity_update', 'stock_deleted'))
);

-- Rule: every stock write needs an actor and refreshes last_updated, even when the
-- quantity is unchanged (re-saving = "confirmed still accurate").
CREATE FUNCTION stock_before_update() RETURNS trigger AS $$
BEGIN
    NEW.updated_by := current_actor_id();
    NEW.last_updated := CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Classifies initial inserts and quantity changes. Deletion is handled by
-- stock_log_delete below.
CREATE FUNCTION stock_log_adjustment() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO stock_adjustment
            (location_id, product_id, old_quantity, new_quantity, changed_by, change_type)
        VALUES
            (NEW.location_id, NEW.product_id, NULL, NEW.quantity,
             current_actor_id(), 'initial_stock');
    ELSIF TG_OP = 'UPDATE' AND NEW.quantity IS DISTINCT FROM OLD.quantity THEN
        INSERT INTO stock_adjustment
            (location_id, product_id, old_quantity, new_quantity, changed_by, change_type)
        VALUES
            (NEW.location_id, NEW.product_id, OLD.quantity, NEW.quantity,
             current_actor_id(), 'quantity_update');
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Requires an actor before a direct or cascading stock deletion.
CREATE FUNCTION stock_before_delete() RETURNS trigger AS $$
BEGIN
    PERFORM current_actor_id();
    RETURN OLD;
END;
$$ LANGUAGE plpgsql;

-- Records stock deletion explicitly. A zero new_quantity is a terminal
-- representation for the deleted row; change_type disambiguates it.
CREATE FUNCTION stock_log_delete() RETURNS trigger AS $$
BEGIN
    INSERT INTO stock_adjustment
        (location_id, product_id, old_quantity, new_quantity, changed_by, change_type)
    VALUES
        (OLD.location_id, OLD.product_id, OLD.quantity, 0,
         current_actor_id(), 'stock_deleted');
    RETURN OLD;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_stock_before_update
    BEFORE INSERT OR UPDATE ON stock
    FOR EACH ROW EXECUTE FUNCTION stock_before_update();
CREATE TRIGGER trg_stock_log_adjustment
    AFTER INSERT OR UPDATE ON stock
    FOR EACH ROW EXECUTE FUNCTION stock_log_adjustment();
CREATE TRIGGER trg_stock_before_delete
    BEFORE DELETE ON stock
    FOR EACH ROW EXECUTE FUNCTION stock_before_delete();
CREATE TRIGGER trg_stock_log_delete
    AFTER DELETE ON stock
    FOR EACH ROW EXECUTE FUNCTION stock_log_delete();

-- Offer freshness and audit attribution.
CREATE FUNCTION product_offer_before_write() RETURNS trigger AS $$
BEGIN
    NEW.updated_by := current_actor_id();
    NEW.last_updated := CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Requires a transaction actor when an offer is directly deleted or deleted
-- through the stock(location_id, product_id) cascading foreign key.
CREATE FUNCTION product_offer_before_delete() RETURNS trigger AS $$
BEGIN
    PERFORM current_actor_id();
    RETURN OLD;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_product_offer_before_write
    BEFORE INSERT OR UPDATE ON product_offer
    FOR EACH ROW EXECUTE FUNCTION product_offer_before_write();
CREATE TRIGGER trg_product_offer_before_delete
    BEFORE DELETE ON product_offer
    FOR EACH ROW EXECUTE FUNCTION product_offer_before_delete();

-- ---------------------------------------------------------------------------
-- Purchase orders
-- ---------------------------------------------------------------------------
CREATE TABLE purchase_order (
    purchase_order_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    pharmacy_organization_id BIGINT NOT NULL,
    supplier_organization_id BIGINT NOT NULL,
    -- Constant columns that let the FKs below enforce each organization's type.
    pharmacy_org_type VARCHAR(20) NOT NULL DEFAULT 'pharmacy'
        CHECK (pharmacy_org_type = 'pharmacy'),
    supplier_org_type VARCHAR(20) NOT NULL DEFAULT 'supplier'
        CHECK (supplier_org_type = 'supplier'),
    pharmacy_location_id BIGINT NOT NULL,
    -- The supplier can choose/confirm the warehouse that fulfils the order.
    supplier_location_id BIGINT,
    status VARCHAR(20) NOT NULL DEFAULT 'draft'
        CHECK (status IN (
            'draft', 'submitted', 'countered', 'accepted', 'rejected',
            'processing', 'dispatched', 'delivered', 'cancelled'
        )),
    currency CHAR(3) NOT NULL DEFAULT 'RWF',
    notes TEXT,
    rejection_reason TEXT,
    created_by BIGINT NOT NULL REFERENCES app_user(user_id),
    responded_by BIGINT REFERENCES app_user(user_id),
    status_changed_by BIGINT REFERENCES app_user(user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    submitted_at TIMESTAMPTZ,
    responded_at TIMESTAMPTZ,
    CHECK (pharmacy_organization_id <> supplier_organization_id),
    CHECK (status IN ('draft', 'cancelled') OR submitted_at IS NOT NULL),
    CHECK (status IN ('draft', 'submitted', 'cancelled') OR responded_at IS NOT NULL),
    FOREIGN KEY (pharmacy_organization_id, pharmacy_org_type)
        REFERENCES organization (organization_id, type),
    FOREIGN KEY (supplier_organization_id, supplier_org_type)
        REFERENCES organization (organization_id, type),
    -- Locations must belong to the corresponding organization.
    FOREIGN KEY (pharmacy_location_id, pharmacy_organization_id)
        REFERENCES location (location_id, organization_id),
    FOREIGN KEY (supplier_location_id, supplier_organization_id)
        REFERENCES location (location_id, organization_id)
);

CREATE TABLE purchase_order_item (
    purchase_order_item_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    purchase_order_id BIGINT NOT NULL
        REFERENCES purchase_order(purchase_order_id) ON DELETE CASCADE,
    product_id BIGINT NOT NULL REFERENCES product(product_id),
    requested_quantity INTEGER NOT NULL CHECK (requested_quantity > 0),
    -- Supplier price the pharmacy saw when ordering (snapshot).
    requested_unit_price NUMERIC(14,2) NOT NULL CHECK (requested_unit_price >= 0),
    -- Supplier's accepted values, or proposed values while status = 'countered'.
    -- A counteroffer requires pharmacy approval before the order becomes accepted.
    -- Partial fulfilment after acceptance is out of MVP scope.
    confirmed_quantity INTEGER CHECK (confirmed_quantity > 0),
    confirmed_unit_price NUMERIC(14,2) CHECK (confirmed_unit_price >= 0),
    UNIQUE (purchase_order_id, product_id),
    CHECK (
        confirmed_quantity IS NULL
        OR confirmed_quantity <= requested_quantity
    ),
    CHECK ((confirmed_quantity IS NULL) = (confirmed_unit_price IS NULL))
);

CREATE TABLE purchase_order_status_history (
    history_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    purchase_order_id BIGINT NOT NULL
        REFERENCES purchase_order(purchase_order_id) ON DELETE CASCADE,
    from_status VARCHAR(20),
    to_status VARCHAR(20) NOT NULL
        CHECK (to_status IN (
            'draft', 'submitted', 'countered', 'accepted', 'rejected',
            'processing', 'dispatched', 'delivered', 'cancelled'
        )),
    changed_by BIGINT REFERENCES app_user(user_id),
    changed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    note TEXT,
    CHECK (
        from_status IS NULL OR from_status IN (
            'draft', 'submitted', 'countered', 'accepted', 'rejected',
            'processing', 'dispatched', 'delivered', 'cancelled'
        )
    )
);

-- Automatically record every order status transition in the same transaction.
-- The application must set status_changed_by for every status change.
CREATE FUNCTION purchase_order_log_status() RETURNS trigger AS $$
DECLARE
    actor_id BIGINT;
BEGIN
    IF TG_OP = 'INSERT' THEN
        actor_id := COALESCE(NEW.status_changed_by, NEW.created_by);
        INSERT INTO purchase_order_status_history
            (purchase_order_id, from_status, to_status, changed_by)
        VALUES
            (NEW.purchase_order_id, NULL, NEW.status, actor_id);
    ELSIF NEW.status IS DISTINCT FROM OLD.status THEN
        IF NEW.status_changed_by IS NULL THEN
            RAISE EXCEPTION 'status_changed_by is required when purchase-order status changes';
        END IF;
        actor_id := NEW.status_changed_by;
        INSERT INTO purchase_order_status_history
            (purchase_order_id, from_status, to_status, changed_by)
        VALUES
            (NEW.purchase_order_id, OLD.status, NEW.status, actor_id);
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_purchase_order_log_status
    AFTER INSERT OR UPDATE OF status ON purchase_order
    FOR EACH ROW EXECUTE FUNCTION purchase_order_log_status();

-- Order write rules:
--   * every INSERT/UPDATE requires the transaction actor
--   * new orders must start as draft
--   * response fields cannot be supplied by the caller on INSERT
--   * created_by and status_changed_by are transaction-derived
--   * response metadata is stamped only on the first supplier response
--   * submitted_at is set by the database on first submission
CREATE FUNCTION purchase_order_before_write() RETURNS trigger AS $$
DECLARE
    actor_id BIGINT := current_actor_id();
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'draft' THEN
            RAISE EXCEPTION 'new purchase orders must start in draft';
        END IF;

        NEW.created_by := actor_id;
        NEW.status_changed_by := actor_id;
        NEW.responded_by := NULL;
        NEW.responded_at := NULL;
        NEW.submitted_at := NULL;
    ELSE
        NEW.created_by := OLD.created_by;

        IF NEW.status IS DISTINCT FROM OLD.status THEN
            NEW.status_changed_by := actor_id;

            IF OLD.status = 'submitted'
               AND NEW.status IN ('countered', 'accepted', 'rejected') THEN
                -- Stamp only the first supplier response.
                IF OLD.responded_at IS NOT NULL OR OLD.responded_by IS NOT NULL THEN
                    RAISE EXCEPTION 'supplier response has already been recorded';
                END IF;
                NEW.responded_by := actor_id;
                NEW.responded_at := CURRENT_TIMESTAMP;
            ELSE
                NEW.responded_by := OLD.responded_by;
                NEW.responded_at := OLD.responded_at;
            END IF;
        ELSE
            NEW.status_changed_by := OLD.status_changed_by;
            NEW.responded_by := OLD.responded_by;
            NEW.responded_at := OLD.responded_at;
            NEW.submitted_at := OLD.submitted_at;
        END IF;
    END IF;

    -- Submission gate: both organizations must be approved.
    IF NEW.status = 'submitted'
       AND (TG_OP = 'INSERT' OR OLD.status IS DISTINCT FROM 'submitted') THEN
        IF EXISTS (
            SELECT 1
            FROM organization
            WHERE organization_id IN (
                NEW.pharmacy_organization_id,
                NEW.supplier_organization_id
            )
            AND status <> 'approved'
        ) THEN
            RAISE EXCEPTION 'both organizations must be approved to submit an order';
        END IF;
        NEW.submitted_at := CURRENT_TIMESTAMP;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_purchase_order_before_write
    BEFORE INSERT OR UPDATE ON purchase_order
    FOR EACH ROW EXECUTE FUNCTION purchase_order_before_write();

-- Order items:
--   * actor required for INSERT/UPDATE/DELETE
--   * parent purchase_order_id cannot be changed after insertion
--   * INSERT/DELETE and requested-line edits only allowed while parent is draft
--   * confirmed values may still be changed after submission; backend permissions
--     must restrict those changes to the appropriate supplier/pharmacy workflow.
CREATE FUNCTION purchase_order_item_guard() RETURNS trigger AS $$
DECLARE
    old_status VARCHAR(20);
    new_status VARCHAR(20);
BEGIN
    PERFORM current_actor_id();

    IF TG_OP = 'INSERT' THEN
        SELECT status INTO new_status
        FROM purchase_order
        WHERE purchase_order_id = NEW.purchase_order_id
        FOR UPDATE;

        IF new_status IS NULL THEN
            RAISE EXCEPTION 'purchase order % does not exist', NEW.purchase_order_id;
        END IF;

        IF new_status <> 'draft' THEN
            RAISE EXCEPTION 'order items can only be added while the order is draft';
        END IF;

        RETURN NEW;

    ELSIF TG_OP = 'DELETE' THEN
        SELECT status INTO old_status
        FROM purchase_order
        WHERE purchase_order_id = OLD.purchase_order_id
        FOR UPDATE;

        -- A missing parent means this delete is the cascade from deleting the
        -- order itself, which purchase_order_no_delete already limited to drafts.
        IF old_status IS NOT NULL AND old_status <> 'draft' THEN
            RAISE EXCEPTION 'order items can only be deleted while the order is draft';
        END IF;

        RETURN OLD;

    ELSE
        IF NEW.purchase_order_id IS DISTINCT FROM OLD.purchase_order_id THEN
            RAISE EXCEPTION 'an order item cannot be moved to another purchase order';
        END IF;

        SELECT status INTO old_status
        FROM purchase_order
        WHERE purchase_order_id = OLD.purchase_order_id
        FOR UPDATE;

        IF old_status IS NULL THEN
            RAISE EXCEPTION 'parent purchase order does not exist';
        END IF;

        IF old_status <> 'draft' AND (
            NEW.product_id IS DISTINCT FROM OLD.product_id
            OR NEW.requested_quantity IS DISTINCT FROM OLD.requested_quantity
            OR NEW.requested_unit_price IS DISTINCT FROM OLD.requested_unit_price
        ) THEN
            RAISE EXCEPTION
                'requested order lines cannot change once the order is %',
                old_status;
        END IF;

        RETURN NEW;
    END IF;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_purchase_order_item_guard
    BEFORE INSERT OR UPDATE OR DELETE ON purchase_order_item
    FOR EACH ROW EXECUTE FUNCTION purchase_order_item_guard();

-- Only draft orders may be deleted, and deleting needs an actor. Anything
-- submitted keeps its items and history; use status = 'cancelled' instead.
CREATE FUNCTION purchase_order_no_delete() RETURNS trigger AS $$
BEGIN
    PERFORM current_actor_id();

    IF OLD.status <> 'draft' THEN
        RAISE EXCEPTION
            'only draft orders can be deleted; cancel order % instead',
            OLD.purchase_order_id;
    END IF;

    RETURN OLD;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_purchase_order_no_delete
    BEFORE DELETE ON purchase_order
    FOR EACH ROW EXECUTE FUNCTION purchase_order_no_delete();

-- ---------------------------------------------------------------------------
-- Demand signal: patients search without accounts, so log searches here.
-- Store coarse location only (rounded coordinates).
-- ---------------------------------------------------------------------------
CREATE TABLE search_event (
    search_event_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    query_text VARCHAR(255) NOT NULL,
    drug_id BIGINT REFERENCES drug(drug_id) ON DELETE SET NULL,
    product_id BIGINT REFERENCES product(product_id) ON DELETE SET NULL,
    approx_latitude NUMERIC(6,3),
    approx_longitude NUMERIC(6,3),
    results_count INTEGER NOT NULL DEFAULT 0 CHECK (results_count >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (approx_latitude IS NULL OR approx_latitude BETWEEN -90 AND 90),
    CHECK (approx_longitude IS NULL OR approx_longitude BETWEEN -180 AND 180)
);

-- ---------------------------------------------------------------------------
-- Views: the visibility rules live here
-- ---------------------------------------------------------------------------
-- Patient-facing: derived status only, NEVER exact quantity.
CREATE VIEW patient_availability AS
SELECT
    o.offer_id,
    o.product_id,
    p.drug_id,
    l.location_id,
    org.organization_id AS pharmacy_organization_id,
    org.name AS pharmacy_name,
    l.name AS location_name,
    l.address,
    l.latitude,
    l.longitude,
    l.phone,
    o.unit_price,
    o.currency,
    CASE
        WHEN s.quantity <= 0 THEN 'unavailable'
        WHEN s.quantity <= o.low_stock_threshold THEN 'low_stock'
        ELSE 'in_stock'
    END AS availability_status,
    GREATEST(s.last_updated, o.last_updated) AS last_updated
FROM product_offer o
JOIN stock s ON s.location_id = o.location_id AND s.product_id = o.product_id
JOIN product p ON p.product_id = o.product_id AND p.is_active
JOIN location l ON l.location_id = o.location_id AND l.is_active
JOIN organization org
    ON org.organization_id = l.organization_id
   AND org.type = 'pharmacy'
   AND org.status = 'approved'
WHERE o.is_listed;

-- Pharmacy-facing: supplier listings WITH exact quantities.
CREATE VIEW supplier_listing AS
SELECT
    o.offer_id,
    o.product_id,
    p.drug_id,
    l.location_id AS supplier_location_id,
    org.organization_id AS supplier_organization_id,
    org.name AS supplier_name,
    l.name AS location_name,
    l.city,
    l.latitude,
    l.longitude,
    l.phone,
    l.whatsapp_phone,
    o.unit_price,
    o.currency,
    s.quantity,
    GREATEST(s.last_updated, o.last_updated) AS last_updated
FROM product_offer o
JOIN stock s ON s.location_id = o.location_id AND s.product_id = o.product_id
JOIN product p ON p.product_id = o.product_id AND p.is_active
JOIN location l ON l.location_id = o.location_id AND l.is_active
JOIN organization org
    ON org.organization_id = l.organization_id
   AND org.type = 'supplier'
   AND org.status = 'approved'
WHERE o.is_listed;

-- ---------------------------------------------------------------------------
-- updated_at triggers
-- ---------------------------------------------------------------------------
CREATE TRIGGER trg_app_user_updated_at BEFORE UPDATE ON app_user
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_organization_updated_at BEFORE UPDATE ON organization
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_location_updated_at BEFORE UPDATE ON location
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_purchase_order_updated_at BEFORE UPDATE ON purchase_order
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- Indexes
-- ---------------------------------------------------------------------------
CREATE INDEX idx_membership_user ON membership(user_id);
CREATE INDEX idx_membership_organization ON membership(organization_id);
CREATE INDEX idx_location_organization ON location(organization_id);
-- Simple bounding-box lookups. If distance search matters, move to PostGIS
-- (geography column + GiST index) instead.
CREATE INDEX idx_location_coords ON location(latitude, longitude)
    WHERE latitude IS NOT NULL AND longitude IS NOT NULL;
CREATE INDEX idx_organization_status ON organization(type, status);
CREATE INDEX idx_org_document_org ON organization_document(organization_id, verification_status);
CREATE INDEX idx_product_drug ON product(drug_id);
CREATE INDEX idx_stock_product_location ON stock(product_id, location_id);
CREATE INDEX idx_offer_product_listed ON product_offer(product_id, is_listed);
CREATE INDEX idx_stock_adjustment_lookup ON stock_adjustment(location_id, product_id, changed_at);
CREATE INDEX idx_purchase_order_pharmacy ON purchase_order(pharmacy_organization_id, created_at);
CREATE INDEX idx_purchase_order_supplier ON purchase_order(supplier_organization_id, status, created_at);
CREATE INDEX idx_purchase_order_item_product ON purchase_order_item(product_id);
CREATE INDEX idx_po_status_history_po ON purchase_order_status_history(purchase_order_id, changed_at);
CREATE INDEX idx_search_event_created ON search_event(created_at);
CREATE INDEX idx_search_event_product ON search_event(product_id) WHERE product_id IS NOT NULL;
"""

# The initial schema (baseline 5c11125c47b6 + 211f0e646448 password_hash).
LEGACY_SCHEMA_SQL = r"""
CREATE TABLE app_user (
    user_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name VARCHAR(150) NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE,
    phone VARCHAR(30),
    password_hash VARCHAR(255)
);
CREATE TABLE organization (
    organization_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    type VARCHAR(50) NOT NULL
);
CREATE TABLE membership (
    membership_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id BIGINT NOT NULL,
    organization_id BIGINT NOT NULL,
    role VARCHAR(50) NOT NULL,
    CONSTRAINT fk_membership_user FOREIGN KEY (user_id) REFERENCES app_user(user_id),
    CONSTRAINT fk_membership_organization FOREIGN KEY (organization_id)
        REFERENCES organization(organization_id),
    CONSTRAINT uq_membership UNIQUE (user_id, organization_id)
);
CREATE TABLE location (
    location_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id BIGINT NOT NULL,
    name VARCHAR(255) NOT NULL,
    address TEXT,
    city VARCHAR(100),
    latitude NUMERIC(9,6),
    longitude NUMERIC(9,6),
    CONSTRAINT fk_location_organization FOREIGN KEY (organization_id)
        REFERENCES organization(organization_id)
);
CREATE TABLE drug (
    drug_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    therapeutic_class VARCHAR(255)
);
CREATE TABLE product (
    product_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    drug_id BIGINT NOT NULL,
    product_name VARCHAR(255) NOT NULL,
    brand VARCHAR(255),
    strength VARCHAR(100),
    dosage_form VARCHAR(100),
    pack_size VARCHAR(100),
    barcode VARCHAR(100),
    manufacturer VARCHAR(255),
    CONSTRAINT fk_product_drug FOREIGN KEY (drug_id) REFERENCES drug(drug_id)
);
CREATE TABLE batch (
    batch_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_id BIGINT NOT NULL,
    batch_number VARCHAR(100) NOT NULL,
    expiry_date DATE NOT NULL,
    CONSTRAINT fk_batch_product FOREIGN KEY (product_id) REFERENCES product(product_id),
    CONSTRAINT uq_batch_product UNIQUE (product_id, batch_number)
);
CREATE TABLE stock (
    stock_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    location_id BIGINT NOT NULL,
    batch_id BIGINT NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 0,
    availability VARCHAR(50),
    last_updated TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_stock_location FOREIGN KEY (location_id) REFERENCES location(location_id),
    CONSTRAINT fk_stock_batch FOREIGN KEY (batch_id) REFERENCES batch(batch_id),
    CONSTRAINT uq_stock_location_batch UNIQUE (location_id, batch_id),
    CONSTRAINT chk_stock_quantity CHECK (quantity >= 0)
);
"""


def _run_script(sql: str) -> None:
    # Use the raw DBAPI cursor so '%' in RAISE messages and '::' casts reach
    # PostgreSQL untouched (no bind-parameter parsing). Same transaction.
    cursor = op.get_bind().connection.dbapi_connection.cursor()
    try:
        cursor.execute(sql)
    finally:
        cursor.close()


def _scalar(sql: str, params: dict):
    return op.get_bind().exec_driver_sql(sql, params).scalar()


def _table_exists(name: str) -> bool:
    return _scalar("SELECT to_regclass('public.' || %(name)s) IS NOT NULL", {"name": name})


def _column_exists(table: str, column: str) -> bool:
    return _scalar(
        "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = %(t)s AND column_name = %(c)s)",
        {"t": table, "c": column},
    )


def _reset_identities() -> None:
    for table, column in CARRIED_IDENTITIES:
        op.execute(
            f"SELECT setval(pg_get_serial_sequence('{table}', '{column}'), "
            f"COALESCE((SELECT max({column}) FROM {table}), 0) + 1, false)"
        )


def upgrade() -> None:
    has_users = _table_exists("app_user")
    has_drugs = _table_exists("drug")
    has_products = _table_exists("product")

    # 1. Keep the compatible legacy rows in temporary tables.
    if has_users:
        password = "password_hash" if _column_exists("app_user", "password_hash") else "NULL"
        op.execute(
            "CREATE TEMP TABLE _v6_users ON COMMIT DROP AS "
            "SELECT DISTINCT ON (lower(btrim(email))) user_id, name, "
            f"lower(btrim(email)) AS email, phone, {password}::text AS password_hash "
            "FROM app_user ORDER BY lower(btrim(email)), user_id"
        )
    if has_drugs:
        op.execute(
            "CREATE TEMP TABLE _v6_drugs ON COMMIT DROP AS "
            "SELECT DISTINCT ON (lower(btrim(name))) drug_id, name, therapeutic_class "
            "FROM drug ORDER BY lower(btrim(name)), drug_id"
        )
    if has_products:
        op.execute(
            "CREATE TEMP TABLE _v6_products ON COMMIT DROP AS "
            "SELECT product_id, drug_id, product_name, brand, strength, dosage_form, "
            "pack_size, barcode, manufacturer FROM product"
        )

    # 2. Drop the legacy schema.
    for table in LEGACY_TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")

    # 3. Create the v6 schema.
    _run_script(V6_SCHEMA_SQL)

    # 4. Restore the carried-over rows, preserving ids.
    if has_users:
        op.execute(
            "INSERT INTO app_user (user_id, name, email, phone, password_hash) "
            "OVERRIDING SYSTEM VALUE "
            "SELECT user_id, name, email, phone, "
            "COALESCE(NULLIF(password_hash, ''), '!unusable') FROM _v6_users"
        )
    if has_drugs:
        op.execute(
            "INSERT INTO drug (drug_id, name, therapeutic_class) OVERRIDING SYSTEM VALUE "
            "SELECT drug_id, name, therapeutic_class FROM _v6_drugs"
        )
    if has_products:
        # Products whose drug was a case-duplicate, or that duplicate another
        # product's identity, are skipped.
        op.execute(
            "INSERT INTO product (product_id, drug_id, product_name, brand, strength, "
            "dosage_form, pack_size, barcode, manufacturer) OVERRIDING SYSTEM VALUE "
            "SELECT p.product_id, p.drug_id, p.product_name, p.brand, p.strength, "
            "p.dosage_form, p.pack_size, p.barcode, p.manufacturer "
            "FROM _v6_products p JOIN drug d ON d.drug_id = p.drug_id "
            "ON CONFLICT DO NOTHING"
        )

    # 5. Move the identity sequences past the restored ids.
    _reset_identities()


def downgrade() -> None:
    """Restore the initial (pre-v6) schema.

    app_user, drug and product rows are carried back. Everything that only
    exists in v6 (organizations, locations, stock, offers, orders, documents,
    audit history, search events) is lost.
    """
    op.execute(
        "CREATE TEMP TABLE _legacy_users ON COMMIT DROP AS "
        "SELECT user_id, name, email, phone, password_hash FROM app_user"
    )
    op.execute(
        "CREATE TEMP TABLE _legacy_drugs ON COMMIT DROP AS "
        "SELECT drug_id, name, therapeutic_class FROM drug"
    )
    op.execute(
        "CREATE TEMP TABLE _legacy_products ON COMMIT DROP AS "
        "SELECT product_id, drug_id, product_name, brand, strength, dosage_form, "
        "pack_size, barcode, manufacturer FROM product"
    )

    op.execute("DROP VIEW IF EXISTS supplier_listing")
    op.execute("DROP VIEW IF EXISTS patient_availability")
    for table in V6_TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    for function in V6_FUNCTIONS:
        op.execute(f"DROP FUNCTION IF EXISTS {function}")

    _run_script(LEGACY_SCHEMA_SQL)

    op.execute(
        "INSERT INTO app_user (user_id, name, email, phone, password_hash) "
        "OVERRIDING SYSTEM VALUE SELECT user_id, name, email, phone, "
        "NULLIF(password_hash, '!unusable') FROM _legacy_users"
    )
    op.execute(
        "INSERT INTO drug (drug_id, name, therapeutic_class) OVERRIDING SYSTEM VALUE "
        "SELECT drug_id, name, therapeutic_class FROM _legacy_drugs"
    )
    op.execute(
        "INSERT INTO product (product_id, drug_id, product_name, brand, strength, "
        "dosage_form, pack_size, barcode, manufacturer) OVERRIDING SYSTEM VALUE "
        "SELECT product_id, drug_id, product_name, brand, strength, dosage_form, "
        "pack_size, barcode, manufacturer FROM _legacy_products"
    )
    _reset_identities()
