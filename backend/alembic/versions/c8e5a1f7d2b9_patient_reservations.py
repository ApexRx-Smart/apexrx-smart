"""patient medicine reservations (engine and safeguards)

* product: reservation settings. dispensing_class (unclassified by default:
  never reservable until classified), stock_unit / unit_label (what one stock
  count means), unit_version (bumped whenever that meaning changes),
  max_reservation_quantity and reservation_enabled (a CHECK allows enabling
  only a classified, non-prescription product with a known unit and a cap).
  Changes are audited in product_reservation_history.
* offer_unit_acknowledgement: insert-only; an owner or manager confirms that a
  branch counts a product in the catalogue's current unit (one row per
  unit_version). Reservations need a current acknowledgement.
* reservation: a patient's request for one medicine at one branch. Request
  details are fixed at insert; afterwards only status transitions are allowed,
  enforced by triggers: who may make which transition, deadlines (24 hours to
  respond, 24 hours to collect, measured with clock_timestamp()), stock
  availability on confirmation, and "system" transitions (expiry after the
  deadline, cancellation when the pharmacy is suspended) that ordinary code
  cannot forge. reservation_status_history records every transition.
* reservation_collection: insert-only record of a collection. Its trigger
  deducts the stock (optionally after an audited owner/manager override that
  records a physical count) and stores the exact stock_adjustment ids, taken
  from stock_log_adjustment, which now publishes the id it creates in the
  transaction-local setting app.last_stock_adjustment_id. A deferred
  constraint trigger requires the reservation to be marked collected, by the
  same person, in the same transaction (pg_current_xact_id()).
* notification: may address one user (recipient_user_id) instead of an
  organization (exactly one of the two), and may refer to a reservation.
* patient_availability: availability now counts confirmed, unexpired
  reservations against stock. Same columns as before.

Revision ID: c8e5a1f7d2b9
Revises: b7c3e9d1f4a6
Create Date: 2026-11-17 12:00:00
"""

from typing import Sequence, Union

from alembic import op

revision: str = "c8e5a1f7d2b9"
down_revision: Union[str, Sequence[str], None] = "b7c3e9d1f4a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_KINDS = (
    "'request_submitted', 'request_cancelled', 'request_declined', 'quotation_submitted', "
    "'revision_requested', 'quotation_accepted', 'quotation_rejected', 'order_created', 'message'"
)
RESERVATION_KINDS = (
    "'reservation_requested', 'reservation_cancelled_patient', 'reservation_request_lapsed', "
    "'reservation_confirmed', 'reservation_declined', 'reservation_cancelled', "
    "'reservation_withdrawn', 'reservation_expired'"
)

UPGRADE = """
-- ---------------------------------------------------------------------------
-- Stock adjustments: publish the id of each adjustment row this transaction
-- creates, so a caller in the same transaction can reference it exactly.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION stock_log_adjustment() RETURNS trigger AS $$
DECLARE
    new_id BIGINT;
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO stock_adjustment
            (location_id, product_id, old_quantity, new_quantity, changed_by, change_type)
        VALUES
            (NEW.location_id, NEW.product_id, NULL, NEW.quantity,
             current_actor_id(), 'initial_stock')
        RETURNING adjustment_id INTO new_id;
    ELSIF TG_OP = 'UPDATE' AND NEW.quantity IS DISTINCT FROM OLD.quantity THEN
        INSERT INTO stock_adjustment
            (location_id, product_id, old_quantity, new_quantity, changed_by, change_type)
        VALUES
            (NEW.location_id, NEW.product_id, OLD.quantity, NEW.quantity,
             current_actor_id(), 'quantity_update')
        RETURNING adjustment_id INTO new_id;
    END IF;
    IF new_id IS NOT NULL THEN
        PERFORM set_config('app.last_stock_adjustment_id', new_id::text, true);
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ---------------------------------------------------------------------------
-- Product reservation settings
-- ---------------------------------------------------------------------------
ALTER TABLE product
    ADD COLUMN dispensing_class VARCHAR(20) NOT NULL DEFAULT 'unclassified'
        CONSTRAINT product_dispensing_class_check
        CHECK (dispensing_class IN ('unclassified', 'non_prescription', 'prescription_only')),
    ADD COLUMN stock_unit VARCHAR(10) NOT NULL DEFAULT 'unknown'
        CONSTRAINT product_stock_unit_check CHECK (stock_unit IN ('pack', 'unit', 'unknown')),
    ADD COLUMN unit_label VARCHAR(60),
    ADD COLUMN unit_version INTEGER NOT NULL DEFAULT 1
        CONSTRAINT product_unit_version_check CHECK (unit_version > 0),
    ADD COLUMN max_reservation_quantity INTEGER
        CONSTRAINT product_max_reservation_quantity_check
        CHECK (max_reservation_quantity IS NULL OR max_reservation_quantity > 0),
    ADD COLUMN reservation_enabled BOOLEAN NOT NULL DEFAULT false,
    -- unknown: no label. pack/unit: a trimmed, meaningful name for ONE counted
    -- item (e.g. "box", "tablet", "vial"); the contents stay in pack_size.
    ADD CONSTRAINT product_unit_label_check CHECK (
        (stock_unit = 'unknown' AND unit_label IS NULL)
        OR (stock_unit <> 'unknown'
            AND unit_label IS NOT NULL
            AND unit_label = btrim(unit_label)
            AND char_length(unit_label) BETWEEN 2 AND 60
            AND unit_label ~ '[^[:space:][:punct:][:digit:]]'
            AND lower(unit_label) NOT IN ('n/a', 'na', 'none', 'unknown', 'tbd', 'other', 'x'))
    ),
    ADD CONSTRAINT product_reservation_enabled_check CHECK (
        NOT reservation_enabled
        OR (dispensing_class = 'non_prescription'
            AND stock_unit <> 'unknown'
            AND max_reservation_quantity IS NOT NULL
            AND (stock_unit = 'unit' OR btrim(coalesce(pack_size, '')) <> ''))
    );

CREATE TABLE product_reservation_history (
    history_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_id BIGINT NOT NULL REFERENCES product(product_id),
    dispensing_class VARCHAR(20) NOT NULL,
    stock_unit VARCHAR(10) NOT NULL,
    unit_label VARCHAR(60),
    pack_size VARCHAR(100),
    unit_version INTEGER NOT NULL,
    max_reservation_quantity INTEGER,
    reservation_enabled BOOLEAN NOT NULL,
    changed_by BIGINT NOT NULL REFERENCES app_user(user_id),
    changed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX idx_product_reservation_history ON product_reservation_history (product_id, history_id);

-- ---------------------------------------------------------------------------
-- Shared helpers
-- ---------------------------------------------------------------------------
-- Open = still pending or still collectable at this instant (deadlines are
-- checked with clock_timestamp(), not the transaction start time).
CREATE FUNCTION reservation_open(p_status TEXT, p_respond_by TIMESTAMPTZ, p_expires_at TIMESTAMPTZ)
RETURNS BOOLEAN AS $$
    SELECT (p_status = 'requested' AND clock_timestamp() < p_respond_by)
        OR (p_status = 'confirmed' AND clock_timestamp() < p_expires_at);
$$ LANGUAGE sql VOLATILE;

-- The role of an active user's active membership, or NULL.
CREATE FUNCTION active_member_role(p_user BIGINT, p_org BIGINT) RETURNS TEXT AS $$
    SELECT m.role FROM membership m JOIN app_user u ON u.user_id = m.user_id
    WHERE m.user_id = p_user AND m.organization_id = p_org AND m.is_active AND u.is_active;
$$ LANGUAGE sql STABLE;

-- Why a product cannot be reserved at a branch right now, or NULL if it can.
-- The single definition used by the triggers and by the application.
CREATE FUNCTION reservation_ineligibility(p_location BIGINT, p_product BIGINT) RETURNS TEXT AS $$
DECLARE
    loc RECORD;
    org RECORD;
    prod RECORD;
    off RECORD;
BEGIN
    SELECT * INTO loc FROM location WHERE location_id = p_location;
    IF NOT FOUND THEN
        RETURN 'branch_not_found';
    END IF;
    SELECT * INTO org FROM organization WHERE organization_id = loc.organization_id;
    IF org.type <> 'pharmacy' THEN
        RETURN 'not_a_pharmacy';
    END IF;
    IF org.status <> 'approved' THEN
        RETURN 'pharmacy_unavailable';
    END IF;
    IF NOT loc.is_active THEN
        RETURN 'branch_inactive';
    END IF;
    SELECT * INTO prod FROM product WHERE product_id = p_product;
    IF NOT FOUND OR NOT prod.is_active THEN
        RETURN 'product_inactive';
    END IF;
    IF prod.dispensing_class = 'prescription_only' THEN
        RETURN 'prescription_only';
    END IF;
    IF prod.dispensing_class <> 'non_prescription' THEN
        RETURN 'unclassified';
    END IF;
    IF prod.stock_unit = 'unknown' THEN
        RETURN 'unit_unknown';
    END IF;
    IF prod.max_reservation_quantity IS NULL THEN
        RETURN 'no_quantity_limit';
    END IF;
    IF NOT prod.reservation_enabled THEN
        RETURN 'disabled';
    END IF;
    SELECT * INTO off FROM product_offer WHERE location_id = p_location AND product_id = p_product;
    IF NOT FOUND OR NOT off.is_listed THEN
        RETURN 'offer_unlisted';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM offer_unit_acknowledgement a
        WHERE a.location_id = p_location
          AND a.product_id = p_product
          AND a.unit_version = prod.unit_version
          AND a.stock_unit = prod.stock_unit
          AND a.unit_label = prod.unit_label
          AND (prod.stock_unit <> 'pack' OR a.pack_size IS NOT DISTINCT FROM prod.pack_size)
    ) THEN
        RETURN 'unit_not_acknowledged';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql STABLE;

CREATE FUNCTION reject_change() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION '% records cannot be changed or deleted', TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;

-- ---------------------------------------------------------------------------
-- Branch unit acknowledgements (insert-only, one row per unit version)
-- ---------------------------------------------------------------------------
CREATE TABLE offer_unit_acknowledgement (
    location_id BIGINT NOT NULL REFERENCES location(location_id),
    product_id BIGINT NOT NULL REFERENCES product(product_id),
    unit_version INTEGER NOT NULL CHECK (unit_version > 0),
    stock_unit VARCHAR(10) NOT NULL CHECK (stock_unit IN ('pack', 'unit')),
    unit_label VARCHAR(60) NOT NULL,
    pack_size VARCHAR(100),
    acknowledged_by BIGINT NOT NULL REFERENCES app_user(user_id),
    acknowledged_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (location_id, product_id, unit_version)
);

CREATE FUNCTION offer_unit_acknowledgement_guard() RETURNS trigger AS $$
DECLARE
    actor BIGINT := current_actor_id();
    org RECORD;
    prod RECORD;
    member_role TEXT;
BEGIN
    SELECT o.* INTO org FROM organization o JOIN location l ON l.organization_id = o.organization_id
    WHERE l.location_id = NEW.location_id;
    IF org.type IS DISTINCT FROM 'pharmacy' THEN
        RAISE EXCEPTION 'stock units are acknowledged by pharmacy branches';
    END IF;
    member_role := active_member_role(actor, org.organization_id);
    IF member_role IS NULL OR member_role NOT IN ('owner', 'manager') THEN
        RAISE EXCEPTION 'only owners and managers of this pharmacy can acknowledge stock units';
    END IF;
    SELECT * INTO prod FROM product WHERE product_id = NEW.product_id;
    IF prod.stock_unit = 'unknown' THEN
        RAISE EXCEPTION 'this product has no stock unit to acknowledge';
    END IF;
    IF NEW.unit_version <> prod.unit_version
       OR NEW.stock_unit <> prod.stock_unit
       OR NEW.unit_label <> prod.unit_label
       OR (prod.stock_unit = 'pack' AND NEW.pack_size IS DISTINCT FROM prod.pack_size) THEN
        RAISE EXCEPTION 'the stock unit of this product has changed; review it and acknowledge again';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM product_offer WHERE location_id = NEW.location_id AND product_id = NEW.product_id
    ) THEN
        RAISE EXCEPTION 'add this product to the branch stock before acknowledging its unit';
    END IF;
    NEW.pack_size := prod.pack_size;
    NEW.acknowledged_by := actor;
    NEW.acknowledged_at := clock_timestamp();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER trg_offer_unit_acknowledgement_guard
    BEFORE INSERT ON offer_unit_acknowledgement
    FOR EACH ROW EXECUTE FUNCTION offer_unit_acknowledgement_guard();
CREATE TRIGGER trg_offer_unit_acknowledgement_immutable
    BEFORE UPDATE OR DELETE ON offer_unit_acknowledgement
    FOR EACH ROW EXECUTE FUNCTION reject_change();

-- ---------------------------------------------------------------------------
-- Reservations
-- ---------------------------------------------------------------------------
CREATE TABLE reservation (
    reservation_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    reference VARCHAR(13) NOT NULL UNIQUE
        CHECK (reference ~ '^RX-[ABCDEFGHJKMNPQRSTUVWXYZ23456789]{10}$'),
    patient_user_id BIGINT NOT NULL REFERENCES app_user(user_id),
    pharmacy_organization_id BIGINT NOT NULL,
    pharmacy_org_type VARCHAR(20) NOT NULL DEFAULT 'pharmacy' CHECK (pharmacy_org_type = 'pharmacy'),
    location_id BIGINT NOT NULL,
    product_id BIGINT NOT NULL REFERENCES product(product_id),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    -- Fixed at request time from the catalogue and the offer.
    unit_version INTEGER NOT NULL,
    stock_unit VARCHAR(10) NOT NULL,
    unit_label VARCHAR(60) NOT NULL,
    pack_size VARCHAR(100),
    unit_price NUMERIC(14, 2) NOT NULL CHECK (unit_price >= 0),
    currency CHAR(3) NOT NULL,
    contact_phone VARCHAR(30) NOT NULL CHECK (btrim(contact_phone) <> ''),
    patient_note TEXT CHECK (patient_note IS NULL OR char_length(patient_note) <= 500),
    client_request_id UUID NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'requested'
        CHECK (status IN ('requested', 'confirmed', 'declined', 'cancelled', 'collected', 'expired')),
    status_source VARCHAR(10) NOT NULL DEFAULT 'patient'
        CHECK (status_source IN ('patient', 'pharmacy', 'system')),
    status_reason VARCHAR(40)
        CHECK (status_reason IN ('response_window_elapsed', 'collection_window_elapsed', 'pharmacy_suspended')),
    status_changed_by BIGINT REFERENCES app_user(user_id),
    status_changed_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    respond_by TIMESTAMPTZ NOT NULL,
    responded_at TIMESTAMPTZ,
    responded_by BIGINT REFERENCES app_user(user_id),
    confirmed_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    collected_at TIMESTAMPTZ,
    collected_by BIGINT REFERENCES app_user(user_id),
    cancelled_at TIMESTAMPTZ,
    cancelled_by_role VARCHAR(10) CHECK (cancelled_by_role IN ('patient', 'pharmacy', 'system')),
    decline_reason TEXT CHECK (decline_reason IS NULL OR char_length(decline_reason) <= 500),
    cancel_reason TEXT CHECK (cancel_reason IS NULL OR char_length(cancel_reason) <= 500),
    FOREIGN KEY (pharmacy_organization_id, pharmacy_org_type)
        REFERENCES organization(organization_id, type),
    FOREIGN KEY (location_id, pharmacy_organization_id)
        REFERENCES location(location_id, organization_id),
    CONSTRAINT uq_reservation_client_request UNIQUE (patient_user_id, client_request_id),
    CONSTRAINT reservation_system_actor_check
        CHECK ((status_source = 'system') = (status_changed_by IS NULL)),
    CONSTRAINT reservation_system_reason_check
        CHECK ((status_source = 'system') = (status_reason IS NOT NULL)),
    CONSTRAINT reservation_confirmed_check
        CHECK (status NOT IN ('confirmed', 'collected') OR (confirmed_at IS NOT NULL AND expires_at IS NOT NULL)),
    CONSTRAINT reservation_collected_check
        CHECK (status <> 'collected' OR (collected_at IS NOT NULL AND collected_by IS NOT NULL)),
    CONSTRAINT reservation_declined_check
        CHECK (status <> 'declined' OR btrim(coalesce(decline_reason, '')) <> ''),
    CONSTRAINT reservation_cancelled_check
        CHECK (status <> 'cancelled' OR (
            cancelled_at IS NOT NULL AND cancelled_by_role IS NOT NULL
            AND (cancelled_by_role = 'patient' OR btrim(coalesce(cancel_reason, '')) <> '')))
);
-- One open reservation per patient, branch and product.
CREATE UNIQUE INDEX uq_reservation_open_pair ON reservation (patient_user_id, location_id, product_id)
    WHERE status IN ('requested', 'confirmed');
-- Allocation: confirmed reservations per branch and product.
CREATE INDEX idx_reservation_allocation ON reservation (location_id, product_id)
    INCLUDE (quantity, expires_at) WHERE status = 'confirmed';
CREATE INDEX idx_reservation_location_open ON reservation (location_id)
    WHERE status IN ('requested', 'confirmed');
CREATE INDEX idx_reservation_product_open ON reservation (product_id)
    WHERE status IN ('requested', 'confirmed');
CREATE INDEX idx_reservation_patient ON reservation (patient_user_id, created_at DESC);
CREATE INDEX idx_reservation_pharmacy ON reservation (pharmacy_organization_id, status, created_at DESC);
CREATE INDEX idx_reservation_respond_by ON reservation (respond_by) WHERE status = 'requested';
CREATE INDEX idx_reservation_expires_at ON reservation (expires_at) WHERE status = 'confirmed';

CREATE TABLE reservation_status_history (
    history_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    reservation_id BIGINT NOT NULL REFERENCES reservation(reservation_id),
    from_status VARCHAR(20),
    to_status VARCHAR(20) NOT NULL,
    source VARCHAR(10) NOT NULL,
    changed_by BIGINT REFERENCES app_user(user_id),
    system_reason VARCHAR(40),
    reason TEXT,
    changed_at TIMESTAMPTZ NOT NULL,
    CHECK ((source = 'system') = (changed_by IS NULL)),
    CHECK ((source = 'system') = (system_reason IS NOT NULL))
);
CREATE INDEX idx_reservation_status_history ON reservation_status_history (reservation_id, history_id);

-- A new reservation: always a request by the signed-in patient for an
-- eligible product at an eligible branch. Snapshot and deadlines are set here.
CREATE FUNCTION reservation_before_insert() RETURNS trigger AS $$
DECLARE
    actor BIGINT := current_actor_id();
    problem TEXT;
    prod RECORD;
    off RECORD;
BEGIN
    IF NEW.status IS DISTINCT FROM 'requested' OR NEW.status_source IS DISTINCT FROM 'patient' THEN
        RAISE EXCEPTION 'a reservation starts as a request by the patient';
    END IF;
    IF NEW.patient_user_id IS DISTINCT FROM actor THEN
        RAISE EXCEPTION 'a reservation can only be requested by the patient themselves';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM app_user WHERE user_id = actor AND is_active) THEN
        RAISE EXCEPTION 'this account is not active';
    END IF;
    IF active_member_role(actor, NEW.pharmacy_organization_id) IS NOT NULL THEN
        RAISE EXCEPTION 'members of a pharmacy cannot reserve medicines at that pharmacy';
    END IF;
    problem := reservation_ineligibility(NEW.location_id, NEW.product_id);
    IF problem IS NOT NULL THEN
        RAISE EXCEPTION 'this medicine cannot be reserved at this branch (%)', problem;
    END IF;
    SELECT * INTO prod FROM product WHERE product_id = NEW.product_id;
    IF NEW.quantity > prod.max_reservation_quantity THEN
        RAISE EXCEPTION 'at most % can be reserved at once', prod.max_reservation_quantity;
    END IF;
    SELECT * INTO off FROM product_offer WHERE location_id = NEW.location_id AND product_id = NEW.product_id;

    NEW.unit_version := prod.unit_version;
    NEW.stock_unit := prod.stock_unit;
    NEW.unit_label := prod.unit_label;
    NEW.pack_size := prod.pack_size;
    NEW.unit_price := off.unit_price;
    NEW.currency := off.currency;
    NEW.created_at := clock_timestamp();
    NEW.respond_by := NEW.created_at + interval '24 hours';
    NEW.status_changed_by := actor;
    NEW.status_changed_at := NEW.created_at;
    NEW.status_reason := NULL;
    NEW.responded_at := NULL;
    NEW.responded_by := NULL;
    NEW.confirmed_at := NULL;
    NEW.expires_at := NULL;
    NEW.collected_at := NULL;
    NEW.collected_by := NULL;
    NEW.cancelled_at := NULL;
    NEW.cancelled_by_role := NULL;
    NEW.decline_reason := NULL;
    NEW.cancel_reason := NULL;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- After insert: request details never change; only these transitions exist:
--   requested -> confirmed | declined | cancelled | expired
--   confirmed -> collected | cancelled | expired
-- The actor is stamped from app.user_id. status_source = 'system' is accepted
-- only when the condition is true in the database: the deadline has passed
-- (expiry) or the pharmacy is suspended (cancellation).
CREATE FUNCTION reservation_before_update() RETURNS trigger AS $$
DECLARE
    actor BIGINT;
    member_role TEXT;
    org_status TEXT;
    problem TEXT;
    on_hand INTEGER;
    allocated BIGINT;
    now_ts TIMESTAMPTZ := clock_timestamp();
BEGIN
    IF (NEW.reservation_id, NEW.reference, NEW.patient_user_id, NEW.pharmacy_organization_id,
        NEW.pharmacy_org_type, NEW.location_id, NEW.product_id, NEW.quantity, NEW.unit_version,
        NEW.stock_unit, NEW.unit_label, NEW.pack_size, NEW.unit_price, NEW.currency,
        NEW.contact_phone, NEW.patient_note, NEW.client_request_id, NEW.created_at, NEW.respond_by)
       IS DISTINCT FROM
       (OLD.reservation_id, OLD.reference, OLD.patient_user_id, OLD.pharmacy_organization_id,
        OLD.pharmacy_org_type, OLD.location_id, OLD.product_id, OLD.quantity, OLD.unit_version,
        OLD.stock_unit, OLD.unit_label, OLD.pack_size, OLD.unit_price, OLD.currency,
        OLD.contact_phone, OLD.patient_note, OLD.client_request_id, OLD.created_at, OLD.respond_by) THEN
        RAISE EXCEPTION 'the details of a reservation request cannot change';
    END IF;
    IF NEW.status = OLD.status THEN
        RAISE EXCEPTION 'a reservation only changes through a status transition';
    END IF;
    IF NOT ((OLD.status = 'requested' AND NEW.status IN ('confirmed', 'declined', 'cancelled', 'expired'))
         OR (OLD.status = 'confirmed' AND NEW.status IN ('collected', 'cancelled', 'expired'))) THEN
        RAISE EXCEPTION 'a reservation cannot go from % to %', OLD.status, NEW.status;
    END IF;

    -- Lifecycle columns are stamped here; values from the application are ignored.
    NEW.responded_at := OLD.responded_at;
    NEW.responded_by := OLD.responded_by;
    NEW.confirmed_at := OLD.confirmed_at;
    NEW.expires_at := OLD.expires_at;
    NEW.collected_at := OLD.collected_at;
    NEW.collected_by := OLD.collected_by;
    NEW.cancelled_at := OLD.cancelled_at;
    NEW.cancelled_by_role := OLD.cancelled_by_role;
    NEW.status_changed_at := now_ts;
    IF NEW.status <> 'declined' THEN
        NEW.decline_reason := OLD.decline_reason;
    END IF;
    IF NEW.status <> 'cancelled' THEN
        NEW.cancel_reason := OLD.cancel_reason;
    END IF;

    IF NEW.status_source = 'system' THEN
        NEW.status_changed_by := NULL;
        IF NEW.status = 'expired' AND OLD.status = 'requested' AND now_ts >= OLD.respond_by THEN
            NEW.status_reason := 'response_window_elapsed';
        ELSIF NEW.status = 'expired' AND OLD.status = 'confirmed' AND now_ts >= OLD.expires_at THEN
            NEW.status_reason := 'collection_window_elapsed';
        ELSIF NEW.status = 'cancelled' THEN
            SELECT status INTO org_status FROM organization
            WHERE organization_id = OLD.pharmacy_organization_id;
            IF org_status IS DISTINCT FROM 'suspended' THEN
                RAISE EXCEPTION 'a system cancellation is only possible when the pharmacy is suspended';
            END IF;
            NEW.status_reason := 'pharmacy_suspended';
            NEW.cancelled_at := now_ts;
            NEW.cancelled_by_role := 'system';
            NEW.cancel_reason := 'pharmacy_suspended';
        ELSE
            RAISE EXCEPTION 'this change cannot be made as a system action';
        END IF;
        RETURN NEW;
    END IF;

    IF NEW.status = 'expired' THEN
        RAISE EXCEPTION 'only the system can expire a reservation, after its deadline';
    END IF;
    actor := current_actor_id();
    NEW.status_changed_by := actor;
    NEW.status_reason := NULL;
    IF NOT reservation_open(OLD.status, OLD.respond_by, OLD.expires_at) THEN
        RAISE EXCEPTION 'this reservation has expired';
    END IF;

    IF NEW.status_source = 'patient' THEN
        IF actor IS DISTINCT FROM OLD.patient_user_id THEN
            RAISE EXCEPTION 'only the patient can act as the patient';
        END IF;
        IF NEW.status <> 'cancelled' THEN
            RAISE EXCEPTION 'a patient can only cancel a reservation';
        END IF;
        NEW.cancelled_at := now_ts;
        NEW.cancelled_by_role := 'patient';
        RETURN NEW;
    END IF;

    IF NEW.status_source <> 'pharmacy' THEN
        RAISE EXCEPTION 'unknown status source %', NEW.status_source;
    END IF;
    member_role := active_member_role(actor, OLD.pharmacy_organization_id);
    IF member_role IS NULL THEN
        RAISE EXCEPTION 'only members of this pharmacy can act on its reservations';
    END IF;
    IF actor = OLD.patient_user_id THEN
        RAISE EXCEPTION 'you cannot handle your own reservation';
    END IF;
    SELECT status INTO org_status FROM organization WHERE organization_id = OLD.pharmacy_organization_id;
    IF org_status IS DISTINCT FROM 'approved' THEN
        RAISE EXCEPTION 'the pharmacy must be approved by ApexRx to handle reservations';
    END IF;

    IF NEW.status = 'confirmed' THEN
        problem := reservation_ineligibility(OLD.location_id, OLD.product_id);
        IF problem IS NOT NULL THEN
            RAISE EXCEPTION 'this reservation cannot be confirmed (%)', problem;
        END IF;
        IF (SELECT unit_version FROM product WHERE product_id = OLD.product_id) <> OLD.unit_version THEN
            RAISE EXCEPTION 'the stock unit of this product changed after the request';
        END IF;
        SELECT quantity INTO on_hand FROM stock
        WHERE location_id = OLD.location_id AND product_id = OLD.product_id FOR UPDATE;
        SELECT coalesce(sum(r.quantity), 0) INTO allocated FROM reservation r
        WHERE r.location_id = OLD.location_id AND r.product_id = OLD.product_id
          AND r.status = 'confirmed' AND r.expires_at > now_ts
          AND r.reservation_id <> OLD.reservation_id;
        IF on_hand IS NULL OR on_hand - allocated < OLD.quantity THEN
            RAISE EXCEPTION 'not enough unreserved stock to confirm this reservation';
        END IF;
        NEW.responded_at := now_ts;
        NEW.responded_by := actor;
        NEW.confirmed_at := now_ts;
        NEW.expires_at := now_ts + interval '24 hours';
    ELSIF NEW.status = 'declined' THEN
        IF btrim(coalesce(NEW.decline_reason, '')) = '' THEN
            RAISE EXCEPTION 'a reason is required to decline';
        END IF;
        NEW.responded_at := now_ts;
        NEW.responded_by := actor;
    ELSIF NEW.status = 'cancelled' THEN
        IF OLD.status <> 'confirmed' THEN
            RAISE EXCEPTION 'a pending request is declined, not cancelled';
        END IF;
        IF member_role NOT IN ('owner', 'manager') THEN
            RAISE EXCEPTION 'only owners and managers can cancel a confirmed reservation';
        END IF;
        IF btrim(coalesce(NEW.cancel_reason, '')) = '' THEN
            RAISE EXCEPTION 'a reason is required to cancel';
        END IF;
        NEW.cancelled_at := now_ts;
        NEW.cancelled_by_role := 'pharmacy';
    ELSIF NEW.status = 'collected' THEN
        IF NOT EXISTS (
            SELECT 1 FROM reservation_collection c
            WHERE c.reservation_id = OLD.reservation_id
              AND c.collected_xid = pg_current_xact_id()
              AND c.collected_by = actor
        ) THEN
            RAISE EXCEPTION 'a collection must be recorded in the same transaction by the same person';
        END IF;
        NEW.collected_at := now_ts;
        NEW.collected_by := actor;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE FUNCTION reservation_log_status() RETURNS trigger AS $$
BEGIN
    INSERT INTO reservation_status_history
        (reservation_id, from_status, to_status, source, changed_by, system_reason, reason, changed_at)
    VALUES
        (NEW.reservation_id,
         CASE WHEN TG_OP = 'INSERT' THEN NULL ELSE OLD.status END,
         NEW.status, NEW.status_source, NEW.status_changed_by, NEW.status_reason,
         CASE NEW.status WHEN 'declined' THEN NEW.decline_reason
                         WHEN 'cancelled' THEN NEW.cancel_reason END,
         NEW.status_changed_at);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_reservation_before_insert
    BEFORE INSERT ON reservation
    FOR EACH ROW EXECUTE FUNCTION reservation_before_insert();
CREATE TRIGGER trg_reservation_before_update
    BEFORE UPDATE ON reservation
    FOR EACH ROW EXECUTE FUNCTION reservation_before_update();
CREATE TRIGGER trg_reservation_no_delete
    BEFORE DELETE ON reservation
    FOR EACH ROW EXECUTE FUNCTION reject_change();
CREATE TRIGGER trg_reservation_log_status
    AFTER INSERT OR UPDATE OF status ON reservation
    FOR EACH ROW EXECUTE FUNCTION reservation_log_status();
CREATE TRIGGER trg_reservation_status_history_immutable
    BEFORE UPDATE OR DELETE ON reservation_status_history
    FOR EACH ROW EXECUTE FUNCTION reject_change();

-- ---------------------------------------------------------------------------
-- Product: unit changes are refused while reservations are open, and bump
-- unit_version (which invalidates every branch acknowledgement). Audited.
-- ---------------------------------------------------------------------------
CREATE FUNCTION product_reservation_guard() RETURNS trigger AS $$
DECLARE
    unit_changed BOOLEAN;
BEGIN
    IF TG_OP = 'INSERT' THEN
        NEW.unit_version := 1;
        RETURN NEW;
    END IF;
    unit_changed := NEW.stock_unit IS DISTINCT FROM OLD.stock_unit
        OR NEW.unit_label IS DISTINCT FROM OLD.unit_label
        OR ((OLD.stock_unit = 'pack' OR NEW.stock_unit = 'pack')
            AND NEW.pack_size IS DISTINCT FROM OLD.pack_size);
    IF unit_changed THEN
        IF EXISTS (
            SELECT 1 FROM reservation r
            WHERE r.product_id = NEW.product_id AND reservation_open(r.status, r.respond_by, r.expires_at)
        ) THEN
            RAISE EXCEPTION 'this product has open reservations; its stock unit cannot change until they are resolved';
        END IF;
        NEW.unit_version := OLD.unit_version + 1;
    ELSE
        NEW.unit_version := OLD.unit_version;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE FUNCTION product_reservation_log() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.dispensing_class = 'unclassified' AND NEW.stock_unit = 'unknown'
           AND NEW.max_reservation_quantity IS NULL AND NOT NEW.reservation_enabled THEN
            RETURN NEW;
        END IF;
    ELSIF (NEW.dispensing_class, NEW.stock_unit, NEW.unit_label, NEW.unit_version,
           NEW.max_reservation_quantity, NEW.reservation_enabled)
          IS NOT DISTINCT FROM
          (OLD.dispensing_class, OLD.stock_unit, OLD.unit_label, OLD.unit_version,
           OLD.max_reservation_quantity, OLD.reservation_enabled) THEN
        RETURN NEW;
    END IF;
    INSERT INTO product_reservation_history
        (product_id, dispensing_class, stock_unit, unit_label, pack_size, unit_version,
         max_reservation_quantity, reservation_enabled, changed_by)
    VALUES
        (NEW.product_id, NEW.dispensing_class, NEW.stock_unit, NEW.unit_label, NEW.pack_size,
         NEW.unit_version, NEW.max_reservation_quantity, NEW.reservation_enabled, current_actor_id());
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_product_reservation_guard
    BEFORE INSERT OR UPDATE ON product
    FOR EACH ROW EXECUTE FUNCTION product_reservation_guard();
CREATE TRIGGER trg_product_reservation_log
    AFTER INSERT OR UPDATE ON product
    FOR EACH ROW EXECUTE FUNCTION product_reservation_log();
CREATE TRIGGER trg_product_reservation_history_immutable
    BEFORE UPDATE OR DELETE ON product_reservation_history
    FOR EACH ROW EXECUTE FUNCTION reject_change();

-- ---------------------------------------------------------------------------
-- Collection records
-- ---------------------------------------------------------------------------
CREATE TABLE reservation_collection (
    reservation_id BIGINT PRIMARY KEY REFERENCES reservation(reservation_id),
    collected_by BIGINT NOT NULL REFERENCES app_user(user_id),
    collected_at TIMESTAMPTZ NOT NULL,
    collected_xid xid8 NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    recorded_quantity_before INTEGER NOT NULL CHECK (recorded_quantity_before >= 0),
    quantity_after INTEGER NOT NULL CHECK (quantity_after >= 0),
    override BOOLEAN NOT NULL DEFAULT false,
    verified_on_hand INTEGER,
    recorded_quantity_seen INTEGER,
    override_reason TEXT,
    override_by BIGINT REFERENCES app_user(user_id),
    correction_adjustment_id BIGINT REFERENCES stock_adjustment(adjustment_id),
    deduction_adjustment_id BIGINT NOT NULL REFERENCES stock_adjustment(adjustment_id),
    CONSTRAINT reservation_collection_override_check CHECK (
        (override
         AND verified_on_hand IS NOT NULL AND verified_on_hand >= quantity
         AND recorded_quantity_seen IS NOT NULL
         AND override_by IS NOT NULL
         AND char_length(btrim(coalesce(override_reason, ''))) BETWEEN 10 AND 500)
        OR (NOT override
            AND verified_on_hand IS NULL AND recorded_quantity_seen IS NULL
            AND override_reason IS NULL AND override_by IS NULL
            AND correction_adjustment_id IS NULL)
    )
);

-- Validates the collection and performs the stock deduction (after the
-- override correction, if any), recording the exact adjustment ids.
CREATE FUNCTION reservation_collection_before_insert() RETURNS trigger AS $$
DECLARE
    actor BIGINT := current_actor_id();
    r RECORD;
    member_role TEXT;
    on_hand INTEGER;
    available INTEGER;
BEGIN
    SELECT * INTO r FROM reservation WHERE reservation_id = NEW.reservation_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'reservation not found';
    END IF;
    IF r.status <> 'confirmed' THEN
        RAISE EXCEPTION 'only a confirmed reservation can be collected';
    END IF;
    IF clock_timestamp() >= r.expires_at THEN
        RAISE EXCEPTION 'this reservation has expired';
    END IF;
    member_role := active_member_role(actor, r.pharmacy_organization_id);
    IF member_role IS NULL THEN
        RAISE EXCEPTION 'only members of this pharmacy can record a collection';
    END IF;
    IF actor = r.patient_user_id THEN
        RAISE EXCEPTION 'you cannot handle your own reservation';
    END IF;
    SELECT quantity INTO on_hand FROM stock
    WHERE location_id = r.location_id AND product_id = r.product_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'this branch no longer has a stock record for this product';
    END IF;

    NEW.quantity := r.quantity;
    NEW.recorded_quantity_before := on_hand;
    NEW.collected_by := actor;
    NEW.collected_at := clock_timestamp();
    NEW.collected_xid := pg_current_xact_id();
    NEW.correction_adjustment_id := NULL;

    IF NEW.override THEN
        IF member_role NOT IN ('owner', 'manager') THEN
            RAISE EXCEPTION 'only owners and managers can override the recorded stock';
        END IF;
        IF NEW.recorded_quantity_seen IS DISTINCT FROM on_hand THEN
            RAISE EXCEPTION 'the recorded stock changed; count again before overriding';
        END IF;
        IF NEW.verified_on_hand IS NULL OR NEW.verified_on_hand < r.quantity THEN
            RAISE EXCEPTION 'the physically counted stock must cover the full reserved quantity';
        END IF;
        NEW.override_by := actor;
        IF NEW.verified_on_hand <> on_hand THEN
            PERFORM set_config('app.last_stock_adjustment_id', '', true);
            UPDATE stock SET quantity = NEW.verified_on_hand
            WHERE location_id = r.location_id AND product_id = r.product_id;
            NEW.correction_adjustment_id :=
                nullif(current_setting('app.last_stock_adjustment_id', true), '')::BIGINT;
            IF NEW.correction_adjustment_id IS NULL THEN
                RAISE EXCEPTION 'the stock correction was not recorded';
            END IF;
        END IF;
        available := NEW.verified_on_hand;
    ELSE
        IF on_hand < r.quantity THEN
            RAISE EXCEPTION 'the recorded stock is lower than the reserved quantity';
        END IF;
        NEW.verified_on_hand := NULL;
        NEW.recorded_quantity_seen := NULL;
        NEW.override_reason := NULL;
        NEW.override_by := NULL;
        available := on_hand;
    END IF;

    PERFORM set_config('app.last_stock_adjustment_id', '', true);
    UPDATE stock SET quantity = available - r.quantity
    WHERE location_id = r.location_id AND product_id = r.product_id;
    NEW.deduction_adjustment_id :=
        nullif(current_setting('app.last_stock_adjustment_id', true), '')::BIGINT;
    IF NEW.deduction_adjustment_id IS NULL THEN
        RAISE EXCEPTION 'the stock deduction was not recorded';
    END IF;
    NEW.quantity_after := available - r.quantity;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- At commit: the reservation must have been marked collected by the same
-- person (otherwise the whole transaction, stock changes included, rolls back).
CREATE FUNCTION reservation_collection_commit_check() RETURNS trigger AS $$
DECLARE
    r RECORD;
BEGIN
    SELECT status, status_changed_by INTO r FROM reservation WHERE reservation_id = NEW.reservation_id;
    IF r.status IS DISTINCT FROM 'collected' OR r.status_changed_by IS DISTINCT FROM NEW.collected_by THEN
        RAISE EXCEPTION 'a collection record must be completed by marking the reservation collected in the same transaction';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_reservation_collection_before_insert
    BEFORE INSERT ON reservation_collection
    FOR EACH ROW EXECUTE FUNCTION reservation_collection_before_insert();
CREATE CONSTRAINT TRIGGER trg_reservation_collection_commit_check
    AFTER INSERT ON reservation_collection
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION reservation_collection_commit_check();
CREATE TRIGGER trg_reservation_collection_immutable
    BEFORE UPDATE OR DELETE ON reservation_collection
    FOR EACH ROW EXECUTE FUNCTION reject_change();

-- ---------------------------------------------------------------------------
-- Notifications: one organization OR one user; may refer to a reservation.
-- ---------------------------------------------------------------------------
ALTER TABLE notification
    ALTER COLUMN organization_id DROP NOT NULL,
    ADD COLUMN recipient_user_id BIGINT REFERENCES app_user(user_id) ON DELETE CASCADE,
    ADD COLUMN reservation_id BIGINT REFERENCES reservation(reservation_id) ON DELETE CASCADE,
    ADD CONSTRAINT notification_recipient_check
        CHECK (num_nonnulls(organization_id, recipient_user_id) = 1);
ALTER TABLE notification DROP CONSTRAINT notification_kind_check;
ALTER TABLE notification ADD CONSTRAINT notification_kind_check CHECK (kind IN ({kinds}));
CREATE INDEX idx_notification_recipient ON notification (recipient_user_id, notification_id DESC)
    WHERE recipient_user_id IS NOT NULL;
-- Each reservation event is notified once per recipient.
CREATE UNIQUE INDEX uq_notification_reservation_event ON notification
    (reservation_id, kind, coalesce(organization_id, 0), coalesce(recipient_user_id, 0))
    WHERE reservation_id IS NOT NULL;

-- ---------------------------------------------------------------------------
-- Patient availability: stock minus confirmed, unexpired reservations.
-- Same columns as before; never an exact quantity.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW patient_availability AS
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
        WHEN s.quantity - coalesce(a.allocated, 0) <= 0 THEN 'unavailable'
        WHEN s.quantity - coalesce(a.allocated, 0) <= o.low_stock_threshold THEN 'low_stock'
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
LEFT JOIN LATERAL (
    SELECT sum(r.quantity) AS allocated FROM reservation r
    WHERE r.location_id = o.location_id AND r.product_id = o.product_id
      AND r.status = 'confirmed' AND r.expires_at > now()
) a ON true
WHERE o.is_listed;
"""

DOWNGRADE = """
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM reservation) OR EXISTS (SELECT 1 FROM offer_unit_acknowledgement)
       OR EXISTS (SELECT 1 FROM product_reservation_history) THEN
        RAISE EXCEPTION 'reservation data exists; downgrade would delete it';
    END IF;
END $$;

CREATE OR REPLACE VIEW patient_availability AS
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

DELETE FROM notification WHERE recipient_user_id IS NOT NULL OR reservation_id IS NOT NULL;
DROP INDEX IF EXISTS uq_notification_reservation_event;
DROP INDEX IF EXISTS idx_notification_recipient;
ALTER TABLE notification DROP CONSTRAINT notification_kind_check;
ALTER TABLE notification ADD CONSTRAINT notification_kind_check CHECK (kind IN ({old_kinds}));
ALTER TABLE notification
    DROP CONSTRAINT notification_recipient_check,
    DROP COLUMN reservation_id,
    DROP COLUMN recipient_user_id,
    ALTER COLUMN organization_id SET NOT NULL;

DROP TABLE reservation_collection;
DROP FUNCTION reservation_collection_before_insert();
DROP FUNCTION reservation_collection_commit_check();
DROP TRIGGER trg_product_reservation_guard ON product;
DROP TRIGGER trg_product_reservation_log ON product;
DROP FUNCTION product_reservation_guard();
DROP FUNCTION product_reservation_log();
DROP TABLE reservation_status_history;
DROP TABLE reservation;
DROP FUNCTION reservation_before_insert();
DROP FUNCTION reservation_before_update();
DROP FUNCTION reservation_log_status();
DROP TABLE offer_unit_acknowledgement;
DROP FUNCTION offer_unit_acknowledgement_guard();
DROP TABLE product_reservation_history;
DROP FUNCTION reject_change();
DROP FUNCTION reservation_ineligibility(BIGINT, BIGINT);
DROP FUNCTION active_member_role(BIGINT, BIGINT);
DROP FUNCTION reservation_open(TEXT, TIMESTAMPTZ, TIMESTAMPTZ);
ALTER TABLE product
    DROP CONSTRAINT product_reservation_enabled_check,
    DROP CONSTRAINT product_unit_label_check,
    DROP COLUMN reservation_enabled,
    DROP COLUMN max_reservation_quantity,
    DROP COLUMN unit_version,
    DROP COLUMN unit_label,
    DROP COLUMN stock_unit,
    DROP COLUMN dispensing_class;

CREATE OR REPLACE FUNCTION stock_log_adjustment() RETURNS trigger AS $$
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
"""


def upgrade() -> None:
    op.execute(UPGRADE.replace("{kinds}", f"{OLD_KINDS}, {RESERVATION_KINDS}"))


def downgrade() -> None:
    op.execute(DOWNGRADE.replace("{old_kinds}", OLD_KINDS))
