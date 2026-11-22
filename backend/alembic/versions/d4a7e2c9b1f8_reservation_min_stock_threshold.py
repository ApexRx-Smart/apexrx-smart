"""reservations: branch minimum stock, stock held from the request, no per-medicine enabling

* location.reservation_min_stock (default 0): the quantity of each medicine a
  pharmacy branch keeps back from public reservations. A medicine is
  reservable at a branch while stock - held - reservation_min_stock > 0.
* A reservation now holds (allocates) its quantity from the moment it is
  requested: open requests and confirmed reservations both count against the
  stock (reservation_allocated()). Declining, cancelling and expiry release it;
  collection deducts it. The insert trigger locks the stock row and requires
  the reservable quantity to cover the request, so concurrent requests cannot
  share the same stock. Confirmation keeps the held quantity; it only requires
  the stock to still cover it after the other open reservations (the minimum
  stock applies to new requests only, so raising it never invalidates a
  reservation that already exists).
* reservation_ineligibility() no longer requires product.reservation_enabled,
  a per-medicine maximum quantity, or a branch unit acknowledgement. It still
  requires an approved pharmacy, an active branch and product, a
  non-prescription classification, a known unit (with a pack size for packs)
  and a listed offer. product.reservation_enabled and
  offer_unit_acknowledgement are kept (existing rows stay; nothing reads them).
* patient_availability counts open requests too (same columns).

Downgrade restores the previous functions and view, drops the index, the
function and the column. It loses the branch thresholds; nothing else.

Revision ID: d4a7e2c9b1f8
Revises: c8e5a1f7d2b9
Create Date: 2026-11-22 12:00:00
"""

from typing import Sequence, Union

from alembic import op

revision: str = "d4a7e2c9b1f8"
down_revision: Union[str, Sequence[str], None] = "c8e5a1f7d2b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UPGRADE = r"""
ALTER TABLE location ADD COLUMN reservation_min_stock INTEGER NOT NULL DEFAULT 0
    CONSTRAINT location_reservation_min_stock_check CHECK (reservation_min_stock BETWEEN 0 AND 1000000);

-- Held by open reservations (requests and confirmed ones still inside their
-- deadline), optionally excluding one reservation.
CREATE FUNCTION reservation_allocated(p_location BIGINT, p_product BIGINT, p_exclude BIGINT)
RETURNS BIGINT AS $$
    SELECT coalesce(sum(r.quantity), 0)::BIGINT FROM reservation r
    WHERE r.location_id = p_location AND r.product_id = p_product
      AND ((r.status = 'requested' AND r.respond_by > clock_timestamp())
        OR (r.status = 'confirmed' AND r.expires_at > clock_timestamp()))
      AND (p_exclude IS NULL OR r.reservation_id <> p_exclude);
$$ LANGUAGE sql VOLATILE;

CREATE INDEX idx_reservation_open_hold ON reservation (location_id, product_id)
    INCLUDE (quantity, respond_by, expires_at) WHERE status IN ('requested', 'confirmed');

CREATE OR REPLACE FUNCTION reservation_ineligibility(p_location BIGINT, p_product BIGINT) RETURNS TEXT AS $$
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
    IF prod.stock_unit = 'pack' AND prod.pack_size IS NULL THEN
        RETURN 'pack_size_missing';
    END IF;
    SELECT * INTO off FROM product_offer WHERE location_id = p_location AND product_id = p_product;
    IF NOT FOUND OR NOT off.is_listed THEN
        RETURN 'offer_unlisted';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql STABLE;

CREATE OR REPLACE FUNCTION reservation_before_insert() RETURNS trigger AS $$
DECLARE
    actor BIGINT := current_actor_id();
    problem TEXT;
    prod RECORD;
    off RECORD;
    on_hand INTEGER;
    keep INTEGER;
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
    IF prod.max_reservation_quantity IS NOT NULL AND NEW.quantity > prod.max_reservation_quantity THEN
        RAISE EXCEPTION 'at most % can be reserved at once', prod.max_reservation_quantity;
    END IF;
    -- The request holds its quantity from now on. Lock the stock row so that
    -- concurrent requests are counted one after the other, then require the
    -- branch's reservable quantity (stock - held - kept back) to cover it.
    SELECT quantity INTO on_hand FROM stock
    WHERE location_id = NEW.location_id AND product_id = NEW.product_id FOR UPDATE;
    SELECT reservation_min_stock INTO keep FROM location WHERE location_id = NEW.location_id;
    IF on_hand IS NULL
       OR on_hand - reservation_allocated(NEW.location_id, NEW.product_id, NULL) - keep < NEW.quantity THEN
        RAISE EXCEPTION 'not enough stock available for reservation at this branch';
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

CREATE OR REPLACE FUNCTION reservation_before_update() RETURNS trigger AS $$
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
        -- The request already holds its quantity; confirming keeps it. It must
        -- still be covered by the recorded stock after every OTHER open
        -- reservation (a manual correction may have lowered the stock). The
        -- branch's minimum stock applies to new requests, not to this one.
        allocated := reservation_allocated(OLD.location_id, OLD.product_id, OLD.reservation_id);
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
      AND ((r.status = 'requested' AND r.respond_by > clock_timestamp())
        OR (r.status = 'confirmed' AND r.expires_at > clock_timestamp()))
) a ON true
WHERE o.is_listed;
"""

DOWNGRADE = r"""
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

CREATE OR REPLACE FUNCTION reservation_before_update() RETURNS trigger AS $$
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

CREATE OR REPLACE FUNCTION reservation_before_insert() RETURNS trigger AS $$
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

CREATE OR REPLACE FUNCTION reservation_ineligibility(p_location BIGINT, p_product BIGINT) RETURNS TEXT AS $$
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

DROP INDEX IF EXISTS idx_reservation_open_hold;
DROP FUNCTION reservation_allocated(BIGINT, BIGINT, BIGINT);
ALTER TABLE location DROP COLUMN reservation_min_stock;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
