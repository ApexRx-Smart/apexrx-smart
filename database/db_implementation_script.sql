-- =============================================================================
-- ApexRx: complete database schema
-- Alembic revision: d5f1b8c3a7e2 (the head of backend/alembic/versions)
-- PostgreSQL 13+
-- =============================================================================
--
-- What this is
--   The whole ApexRx schema in one standalone script: every table, constraint,
--   index, function, trigger and view that `alembic upgrade head` produces.
--   It was generated from a database built with `alembic upgrade head`
--   (pg_dump --schema-only) and checked by building a second database from
--   this file and comparing the two schemas: they are identical.
--
-- How to use it
--   * Run it on an EMPTY database:  psql -v ON_ERROR_STOP=1 -d <db> -f db_implementation_script.sql
--   * It ends by recording revision d5f1b8c3a7e2 in alembic_version, so Alembic treats
--     the database as up to date and later migrations apply normally.
--   * Real deployments are still built and upgraded with `alembic upgrade head`;
--     the migrations are the source of truth. When a migration is added,
--     regenerate this file the same way so the two never drift apart.
--   * Schema only: no users, organizations, products or other data.
--
-- What the schema covers (migration that introduced it)
--   Identity, organizations, members, locations, documents   (baseline, v6 a6f0c2d9e1b4)
--   Catalogue (drug, product), stock, supplier offers, audit (v6 a6f0c2d9e1b4)
--   Purchase orders, items, status history                    (v6 a6f0c2d9e1b4)
--   Phone verification codes                                  (c4d1e8f2a9b7, a6c3e9d1f4b2)
--   Email verification, user address                          (e7b2f4a1c9d3)
--   Sessions, organization invitations, password resets       (f3a9c1d7b2e5)
--   Messaging, procurement requests, quotations, notifications(b7c3e9d1f4a6)
--   Patient reservations, collections, reservation settings   (c8e5a1f7d2b9)
--   Minimum stock threshold for reservations                  (d4a7e2c9b1f8)
--   SMS one-time codes via eSMS Africa (challenge_ref, delivery status,
--   app_user.phone_verification_required)                    (a6c3e9d1f4b2)
--   Account type (patient / pharmacy / supplier) per account (b8d2f6a3c1e7)
--   Application submitted for review (organization.submitted_at) (c9e4a7b2d6f1)
--   Branch-scoped messaging: conversation branch, membership_branch (d5f1b8c3a7e2)
--
-- Audit actor
--   Every transaction that writes stock, product_offer, purchase orders or their
--   items MUST first run
--       SELECT set_config('app.user_id', '<authenticated user_id>', true);
--   The triggers read it (current_actor_id()), reject the write if it is
--   missing, and stamp it into the updated_by / created_by / status_changed_by
--   columns and the audit tables, so attribution cannot be spoofed or left stale.
--   Migrations, seed scripts and admin jobs must set it too.
--
-- Enforced in the database
--   * pharmacy/supplier organization types on purchase orders (composite FKs)
--   * order locations belong to the ordering/fulfilling organization
--   * a published offer always has a matching stock row; no duplicate products
--   * requested order lines are immutable after 'draft'; only drafts are deleted
--   * submitting an order requires both organizations to be 'approved'
--   * stock and offer writes/deletions require an actor and are audited
--   * one active phone-verification code per user and purpose
--
-- Enforced in the application (backend/app)
--   * only 'approved' organizations may publish stock or send/receive orders
--   * order and reservation status transitions, counteroffer approval, currency
--   * role-based permissions (owner / manager / staff) and platform admin rights
--   * one-time-code hashing, expiry, attempt and rate limits

BEGIN;

-- Function bodies refer to tables created further down.
SET LOCAL check_function_bodies = false;

-- FUNCTION: active_member_role(bigint, bigint)

CREATE FUNCTION public.active_member_role(p_user bigint, p_org bigint) RETURNS text
    LANGUAGE sql STABLE
    AS $$
    SELECT m.role FROM membership m JOIN app_user u ON u.user_id = m.user_id
    WHERE m.user_id = p_user AND m.organization_id = p_org AND m.is_active AND u.is_active;
$$;

-- FUNCTION: current_actor_id()

CREATE FUNCTION public.current_actor_id() RETURNS bigint
    LANGUAGE plpgsql STABLE
    AS $$
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
$$;

-- FUNCTION: message_guard()

CREATE FUNCTION public.message_guard() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            IF TG_OP <> 'INSERT' THEN
                RAISE EXCEPTION 'messages cannot be edited or deleted';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM conversation c
                WHERE c.conversation_id = NEW.conversation_id
                  AND NEW.sender_organization_id IN (c.pharmacy_organization_id, c.supplier_organization_id)
            ) THEN
                RAISE EXCEPTION 'the sender organization is not part of this conversation';
            END IF;
            UPDATE conversation SET last_message_at = NEW.created_at
            WHERE conversation_id = NEW.conversation_id;
            RETURN NEW;
        END;
        $$;

-- FUNCTION: offer_unit_acknowledgement_guard()

CREATE FUNCTION public.offer_unit_acknowledgement_guard() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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
$$;

-- FUNCTION: product_offer_before_delete()

CREATE FUNCTION public.product_offer_before_delete() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    PERFORM current_actor_id();
    RETURN OLD;
END;
$$;

-- FUNCTION: product_offer_before_write()

CREATE FUNCTION public.product_offer_before_write() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_by := current_actor_id();
    NEW.last_updated := CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$;

-- FUNCTION: product_reservation_guard()

CREATE FUNCTION public.product_reservation_guard() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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
$$;

-- FUNCTION: product_reservation_log()

CREATE FUNCTION public.product_reservation_log() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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
$$;

-- FUNCTION: purchase_order_before_write()

CREATE FUNCTION public.purchase_order_before_write() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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
$$;

-- FUNCTION: purchase_order_item_guard()

CREATE FUNCTION public.purchase_order_item_guard() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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
$$;

-- FUNCTION: purchase_order_log_status()

CREATE FUNCTION public.purchase_order_log_status() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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
$$;

-- FUNCTION: purchase_order_no_delete()

CREATE FUNCTION public.purchase_order_no_delete() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    PERFORM current_actor_id();

    IF OLD.status <> 'draft' THEN
        RAISE EXCEPTION
            'only draft orders can be deleted; cancel order % instead',
            OLD.purchase_order_id;
    END IF;

    RETURN OLD;
END;
$$;

-- FUNCTION: quotation_item_guard()

CREATE FUNCTION public.quotation_item_guard() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        DECLARE
            parent_status VARCHAR(20);
        BEGIN
            SELECT status INTO parent_status FROM quotation
            WHERE quotation_id = COALESCE(NEW.quotation_id, OLD.quotation_id);
            IF parent_status IS NOT NULL AND parent_status <> 'draft' THEN
                RAISE EXCEPTION 'quotation lines cannot change once the quotation is sent';
            END IF;
            RETURN COALESCE(NEW, OLD);
        END;
        $$;

-- FUNCTION: reject_change()

CREATE FUNCTION public.reject_change() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    RAISE EXCEPTION '% records cannot be changed or deleted', TG_TABLE_NAME;
END;
$$;

-- FUNCTION: reservation_allocated(bigint, bigint, bigint)

CREATE FUNCTION public.reservation_allocated(p_location bigint, p_product bigint, p_exclude bigint) RETURNS bigint
    LANGUAGE sql
    AS $$
    SELECT coalesce(sum(r.quantity), 0)::BIGINT FROM reservation r
    WHERE r.location_id = p_location AND r.product_id = p_product
      AND ((r.status = 'requested' AND r.respond_by > clock_timestamp())
        OR (r.status = 'confirmed' AND r.expires_at > clock_timestamp()))
      AND (p_exclude IS NULL OR r.reservation_id <> p_exclude);
$$;

-- FUNCTION: reservation_before_insert()

CREATE FUNCTION public.reservation_before_insert() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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
$$;

-- FUNCTION: reservation_before_update()

CREATE FUNCTION public.reservation_before_update() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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
$$;

-- FUNCTION: reservation_collection_before_insert()

CREATE FUNCTION public.reservation_collection_before_insert() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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
$$;

-- FUNCTION: reservation_collection_commit_check()

CREATE FUNCTION public.reservation_collection_commit_check() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    r RECORD;
BEGIN
    SELECT status, status_changed_by INTO r FROM reservation WHERE reservation_id = NEW.reservation_id;
    IF r.status IS DISTINCT FROM 'collected' OR r.status_changed_by IS DISTINCT FROM NEW.collected_by THEN
        RAISE EXCEPTION 'a collection record must be completed by marking the reservation collected in the same transaction';
    END IF;
    RETURN NULL;
END;
$$;

-- FUNCTION: reservation_ineligibility(bigint, bigint)

CREATE FUNCTION public.reservation_ineligibility(p_location bigint, p_product bigint) RETURNS text
    LANGUAGE plpgsql STABLE
    AS $$
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
$$;

-- FUNCTION: reservation_log_status()

CREATE FUNCTION public.reservation_log_status() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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
$$;

-- FUNCTION: reservation_open(text, timestamp with time zone, timestamp with time zone)

CREATE FUNCTION public.reservation_open(p_status text, p_respond_by timestamp with time zone, p_expires_at timestamp with time zone) RETURNS boolean
    LANGUAGE sql
    AS $$
    SELECT (p_status = 'requested' AND clock_timestamp() < p_respond_by)
        OR (p_status = 'confirmed' AND clock_timestamp() < p_expires_at);
$$;

-- FUNCTION: set_updated_at()

CREATE FUNCTION public.set_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at := CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$;

-- FUNCTION: stock_before_delete()

CREATE FUNCTION public.stock_before_delete() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    PERFORM current_actor_id();
    RETURN OLD;
END;
$$;

-- FUNCTION: stock_before_update()

CREATE FUNCTION public.stock_before_update() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_by := current_actor_id();
    NEW.last_updated := CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$;

-- FUNCTION: stock_log_adjustment()

CREATE FUNCTION public.stock_log_adjustment() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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
$$;

-- FUNCTION: stock_log_delete()

CREATE FUNCTION public.stock_log_delete() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    INSERT INTO stock_adjustment
        (location_id, product_id, old_quantity, new_quantity, changed_by, change_type)
    VALUES
        (OLD.location_id, OLD.product_id, OLD.quantity, 0,
         current_actor_id(), 'stock_deleted');
    RETURN OLD;
END;
$$;

SET default_tablespace = '';

SET default_table_access_method = heap;

-- TABLE: app_user

CREATE TABLE public.app_user (
    user_id bigint NOT NULL,
    name character varying(150) NOT NULL,
    email character varying(255) NOT NULL,
    phone character varying(30),
    password_hash text NOT NULL,
    is_platform_admin boolean DEFAULT false NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    verified_phone character varying(20),
    phone_verified_at timestamp with time zone,
    email_verified_at timestamp with time zone,
    phone_verification_required boolean DEFAULT false NOT NULL,
    account_type character varying(20) DEFAULT 'patient'::character varying NOT NULL,
    CONSTRAINT app_user_account_type_check CHECK (((account_type)::text = ANY ((ARRAY['patient'::character varying, 'pharmacy'::character varying, 'supplier'::character varying])::text[]))),
    CONSTRAINT app_user_verified_phone_check CHECK (((verified_phone IS NULL) = (phone_verified_at IS NULL))),
    CONSTRAINT app_user_verified_phone_e164_check CHECK (((verified_phone IS NULL) OR ((verified_phone)::text ~ '^\+[1-9][0-9]{6,14}$'::text)))
);

-- SEQUENCE: app_user_user_id_seq

ALTER TABLE public.app_user ALTER COLUMN user_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.app_user_user_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

-- TABLE: auth_session

CREATE TABLE public.auth_session (
    session_id bigint NOT NULL,
    user_id bigint NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    last_activity_at timestamp with time zone NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    revoked_at timestamp with time zone,
    revoked_reason character varying(30),
    CONSTRAINT auth_session_expiry_check CHECK ((expires_at > created_at)),
    CONSTRAINT auth_session_revoked_check CHECK (((revoked_at IS NULL) = (revoked_reason IS NULL)))
);

-- SEQUENCE: auth_session_session_id_seq

ALTER TABLE public.auth_session ALTER COLUMN session_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.auth_session_session_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

-- TABLE: conversation

CREATE TABLE public.conversation (
    conversation_id bigint NOT NULL,
    pharmacy_organization_id bigint NOT NULL,
    supplier_organization_id bigint NOT NULL,
    pharmacy_org_type character varying(20) DEFAULT 'pharmacy'::character varying NOT NULL,
    supplier_org_type character varying(20) DEFAULT 'supplier'::character varying NOT NULL,
    created_by bigint,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    last_message_at timestamp with time zone,
    pharmacy_location_id bigint NOT NULL,
    CONSTRAINT conversation_pharmacy_org_type_check CHECK (((pharmacy_org_type)::text = 'pharmacy'::text)),
    CONSTRAINT conversation_supplier_org_type_check CHECK (((supplier_org_type)::text = 'supplier'::text))
);

-- SEQUENCE: conversation_conversation_id_seq

ALTER TABLE public.conversation ALTER COLUMN conversation_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.conversation_conversation_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

-- TABLE: conversation_read

CREATE TABLE public.conversation_read (
    conversation_id bigint NOT NULL,
    user_id bigint NOT NULL,
    last_read_message_id bigint NOT NULL,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- TABLE: drug

CREATE TABLE public.drug (
    drug_id bigint NOT NULL,
    name character varying(255) NOT NULL,
    therapeutic_class character varying(255),
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- SEQUENCE: drug_drug_id_seq

ALTER TABLE public.drug ALTER COLUMN drug_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.drug_drug_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

-- TABLE: email_verification

CREATE TABLE public.email_verification (
    verification_id bigint NOT NULL,
    user_id bigint NOT NULL,
    email character varying(255) NOT NULL,
    token_hash character varying(64) NOT NULL,
    client_ip_hash character varying(64),
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    consumed_at timestamp with time zone,
    invalidated_at timestamp with time zone,
    delivery_failed_at timestamp with time zone,
    CONSTRAINT email_verification_expiry_check CHECK ((expires_at > created_at)),
    CONSTRAINT email_verification_failed_check CHECK (((delivery_failed_at IS NULL) OR (invalidated_at IS NOT NULL)))
);

-- SEQUENCE: email_verification_verification_id_seq

ALTER TABLE public.email_verification ALTER COLUMN verification_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.email_verification_verification_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

-- TABLE: location

CREATE TABLE public.location (
    location_id bigint NOT NULL,
    organization_id bigint NOT NULL,
    name character varying(255) NOT NULL,
    address text,
    city character varying(100),
    region character varying(100),
    latitude numeric(9,6),
    longitude numeric(9,6),
    phone character varying(30),
    whatsapp_phone character varying(30),
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    sector character varying(100),
    cell character varying(100),
    village character varying(100),
    reservation_min_stock integer DEFAULT 0 NOT NULL,
    CONSTRAINT location_latitude_check CHECK (((latitude IS NULL) OR ((latitude >= ('-90'::integer)::numeric) AND (latitude <= (90)::numeric)))),
    CONSTRAINT location_longitude_check CHECK (((longitude IS NULL) OR ((longitude >= ('-180'::integer)::numeric) AND (longitude <= (180)::numeric)))),
    CONSTRAINT location_reservation_min_stock_check CHECK (((reservation_min_stock >= 0) AND (reservation_min_stock <= 1000000)))
);

-- SEQUENCE: location_location_id_seq

ALTER TABLE public.location ALTER COLUMN location_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.location_location_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

-- TABLE: membership

CREATE TABLE public.membership (
    membership_id bigint NOT NULL,
    user_id bigint NOT NULL,
    organization_id bigint NOT NULL,
    role character varying(30) NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT membership_role_check CHECK (((role)::text = ANY ((ARRAY['owner'::character varying, 'manager'::character varying, 'staff'::character varying])::text[])))
);

-- TABLE: membership_branch

CREATE TABLE public.membership_branch (
    membership_id bigint NOT NULL,
    organization_id bigint NOT NULL,
    location_id bigint NOT NULL,
    assigned_by bigint,
    assigned_at timestamp with time zone DEFAULT now() NOT NULL
);

-- SEQUENCE: membership_membership_id_seq

ALTER TABLE public.membership ALTER COLUMN membership_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.membership_membership_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

-- TABLE: message

CREATE TABLE public.message (
    message_id bigint NOT NULL,
    conversation_id bigint NOT NULL,
    sender_organization_id bigint NOT NULL,
    sender_user_id bigint,
    body text NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT message_body_check CHECK (((char_length(btrim(body)) >= 1) AND (char_length(btrim(body)) <= 4000)))
);

-- SEQUENCE: message_message_id_seq

ALTER TABLE public.message ALTER COLUMN message_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.message_message_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

-- TABLE: notification

CREATE TABLE public.notification (
    notification_id bigint NOT NULL,
    organization_id bigint,
    kind character varying(30) NOT NULL,
    from_organization_id bigint,
    conversation_id bigint,
    procurement_request_id bigint,
    quotation_id bigint,
    purchase_order_id bigint,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    recipient_user_id bigint,
    reservation_id bigint,
    CONSTRAINT notification_kind_check CHECK (((kind)::text = ANY ((ARRAY['request_submitted'::character varying, 'request_cancelled'::character varying, 'request_declined'::character varying, 'quotation_submitted'::character varying, 'revision_requested'::character varying, 'quotation_accepted'::character varying, 'quotation_rejected'::character varying, 'order_created'::character varying, 'message'::character varying, 'reservation_requested'::character varying, 'reservation_cancelled_patient'::character varying, 'reservation_request_lapsed'::character varying, 'reservation_confirmed'::character varying, 'reservation_declined'::character varying, 'reservation_cancelled'::character varying, 'reservation_withdrawn'::character varying, 'reservation_expired'::character varying])::text[]))),
    CONSTRAINT notification_recipient_check CHECK ((num_nonnulls(organization_id, recipient_user_id) = 1))
);

-- SEQUENCE: notification_notification_id_seq

ALTER TABLE public.notification ALTER COLUMN notification_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.notification_notification_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

-- TABLE: notification_read

CREATE TABLE public.notification_read (
    notification_id bigint NOT NULL,
    user_id bigint NOT NULL,
    read_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- TABLE: offer_unit_acknowledgement

CREATE TABLE public.offer_unit_acknowledgement (
    location_id bigint NOT NULL,
    product_id bigint NOT NULL,
    unit_version integer NOT NULL,
    stock_unit character varying(10) NOT NULL,
    unit_label character varying(60) NOT NULL,
    pack_size character varying(100),
    acknowledged_by bigint NOT NULL,
    acknowledged_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT offer_unit_acknowledgement_stock_unit_check CHECK (((stock_unit)::text = ANY ((ARRAY['pack'::character varying, 'unit'::character varying])::text[]))),
    CONSTRAINT offer_unit_acknowledgement_unit_version_check CHECK ((unit_version > 0))
);

-- TABLE: organization

CREATE TABLE public.organization (
    organization_id bigint NOT NULL,
    name character varying(255) NOT NULL,
    type character varying(20) NOT NULL,
    status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    phone character varying(30),
    email character varying(255),
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    reviewed_at timestamp with time zone,
    reviewed_by bigint,
    review_notes text,
    submitted_at timestamp with time zone,
    CONSTRAINT organization_check CHECK ((((status)::text = 'pending'::text) OR (reviewed_at IS NOT NULL))),
    CONSTRAINT organization_status_check CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'approved'::character varying, 'rejected'::character varying, 'suspended'::character varying])::text[]))),
    CONSTRAINT organization_type_check CHECK (((type)::text = ANY ((ARRAY['pharmacy'::character varying, 'supplier'::character varying])::text[])))
);

-- TABLE: organization_document

CREATE TABLE public.organization_document (
    document_id bigint NOT NULL,
    organization_id bigint NOT NULL,
    document_type character varying(100) NOT NULL,
    file_name character varying(255) NOT NULL,
    storage_key text NOT NULL,
    mime_type character varying(100) NOT NULL,
    file_size_bytes bigint NOT NULL,
    verification_status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    uploaded_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    reviewed_at timestamp with time zone,
    reviewed_by bigint,
    rejection_reason text,
    CONSTRAINT organization_document_check CHECK (((((verification_status)::text = 'pending'::text) AND (reviewed_at IS NULL)) OR (((verification_status)::text <> 'pending'::text) AND (reviewed_at IS NOT NULL)))),
    CONSTRAINT organization_document_file_size_bytes_check CHECK ((file_size_bytes > 0)),
    CONSTRAINT organization_document_verification_status_check CHECK (((verification_status)::text = ANY ((ARRAY['pending'::character varying, 'approved'::character varying, 'rejected'::character varying])::text[])))
);

-- SEQUENCE: organization_document_document_id_seq

ALTER TABLE public.organization_document ALTER COLUMN document_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.organization_document_document_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

-- TABLE: organization_invitation

CREATE TABLE public.organization_invitation (
    invitation_id bigint NOT NULL,
    organization_id bigint NOT NULL,
    email character varying(255) NOT NULL,
    role character varying(30) NOT NULL,
    invited_by bigint,
    token_hash character varying(64) NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    sent_at timestamp with time zone,
    send_count integer DEFAULT 0 NOT NULL,
    send_failed_at timestamp with time zone,
    accepted_at timestamp with time zone,
    accepted_by bigint,
    account_created boolean,
    revoked_at timestamp with time zone,
    revoked_by bigint,
    CONSTRAINT organization_invitation_expiry_check CHECK ((expires_at > created_at)),
    CONSTRAINT organization_invitation_role_check CHECK (((role)::text = ANY ((ARRAY['owner'::character varying, 'manager'::character varying, 'staff'::character varying])::text[]))),
    CONSTRAINT organization_invitation_state_check CHECK ((NOT ((accepted_at IS NOT NULL) AND (revoked_at IS NOT NULL))))
);

-- SEQUENCE: organization_invitation_invitation_id_seq

ALTER TABLE public.organization_invitation ALTER COLUMN invitation_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.organization_invitation_invitation_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

-- SEQUENCE: organization_organization_id_seq

ALTER TABLE public.organization ALTER COLUMN organization_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.organization_organization_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

-- TABLE: password_reset

CREATE TABLE public.password_reset (
    reset_id bigint NOT NULL,
    user_id bigint NOT NULL,
    token_hash character varying(64) NOT NULL,
    client_ip_hash character varying(64),
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    used_at timestamp with time zone,
    invalidated_at timestamp with time zone,
    delivery_failed_at timestamp with time zone,
    CONSTRAINT password_reset_expiry_check CHECK ((expires_at > created_at))
);

-- SEQUENCE: password_reset_reset_id_seq

ALTER TABLE public.password_reset ALTER COLUMN reset_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.password_reset_reset_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

-- TABLE: product

CREATE TABLE public.product (
    product_id bigint NOT NULL,
    drug_id bigint NOT NULL,
    product_name character varying(255) NOT NULL,
    brand character varying(255),
    strength character varying(100),
    dosage_form character varying(100),
    pack_size character varying(100),
    barcode character varying(100),
    manufacturer character varying(255),
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    dispensing_class character varying(20) DEFAULT 'unclassified'::character varying NOT NULL,
    stock_unit character varying(10) DEFAULT 'unknown'::character varying NOT NULL,
    unit_label character varying(60),
    unit_version integer DEFAULT 1 NOT NULL,
    max_reservation_quantity integer,
    reservation_enabled boolean DEFAULT false NOT NULL,
    CONSTRAINT product_dispensing_class_check CHECK (((dispensing_class)::text = ANY ((ARRAY['unclassified'::character varying, 'non_prescription'::character varying, 'prescription_only'::character varying])::text[]))),
    CONSTRAINT product_max_reservation_quantity_check CHECK (((max_reservation_quantity IS NULL) OR (max_reservation_quantity > 0))),
    CONSTRAINT product_reservation_enabled_check CHECK (((NOT reservation_enabled) OR (((dispensing_class)::text = 'non_prescription'::text) AND ((stock_unit)::text <> 'unknown'::text) AND (max_reservation_quantity IS NOT NULL) AND (((stock_unit)::text = 'unit'::text) OR (btrim((COALESCE(pack_size, ''::character varying))::text) <> ''::text))))),
    CONSTRAINT product_stock_unit_check CHECK (((stock_unit)::text = ANY ((ARRAY['pack'::character varying, 'unit'::character varying, 'unknown'::character varying])::text[]))),
    CONSTRAINT product_unit_label_check CHECK (((((stock_unit)::text = 'unknown'::text) AND (unit_label IS NULL)) OR (((stock_unit)::text <> 'unknown'::text) AND (unit_label IS NOT NULL) AND ((unit_label)::text = btrim((unit_label)::text)) AND ((char_length((unit_label)::text) >= 2) AND (char_length((unit_label)::text) <= 60)) AND ((unit_label)::text ~ '[^[:space:][:punct:][:digit:]]'::text) AND (lower((unit_label)::text) <> ALL (ARRAY['n/a'::text, 'na'::text, 'none'::text, 'unknown'::text, 'tbd'::text, 'other'::text, 'x'::text]))))),
    CONSTRAINT product_unit_version_check CHECK ((unit_version > 0))
);

-- TABLE: product_offer

CREATE TABLE public.product_offer (
    offer_id bigint NOT NULL,
    location_id bigint NOT NULL,
    product_id bigint NOT NULL,
    unit_price numeric(14,2) NOT NULL,
    currency character(3) DEFAULT 'RWF'::bpchar NOT NULL,
    low_stock_threshold integer DEFAULT 5 NOT NULL,
    is_listed boolean DEFAULT true NOT NULL,
    last_updated timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_by bigint,
    CONSTRAINT product_offer_low_stock_threshold_check CHECK ((low_stock_threshold >= 0)),
    CONSTRAINT product_offer_unit_price_check CHECK ((unit_price >= (0)::numeric))
);

-- TABLE: reservation

CREATE TABLE public.reservation (
    reservation_id bigint NOT NULL,
    reference character varying(13) NOT NULL,
    patient_user_id bigint NOT NULL,
    pharmacy_organization_id bigint NOT NULL,
    pharmacy_org_type character varying(20) DEFAULT 'pharmacy'::character varying NOT NULL,
    location_id bigint NOT NULL,
    product_id bigint NOT NULL,
    quantity integer NOT NULL,
    unit_version integer NOT NULL,
    stock_unit character varying(10) NOT NULL,
    unit_label character varying(60) NOT NULL,
    pack_size character varying(100),
    unit_price numeric(14,2) NOT NULL,
    currency character(3) NOT NULL,
    contact_phone character varying(30) NOT NULL,
    patient_note text,
    client_request_id uuid NOT NULL,
    status character varying(20) DEFAULT 'requested'::character varying NOT NULL,
    status_source character varying(10) DEFAULT 'patient'::character varying NOT NULL,
    status_reason character varying(40),
    status_changed_by bigint,
    status_changed_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone NOT NULL,
    respond_by timestamp with time zone NOT NULL,
    responded_at timestamp with time zone,
    responded_by bigint,
    confirmed_at timestamp with time zone,
    expires_at timestamp with time zone,
    collected_at timestamp with time zone,
    collected_by bigint,
    cancelled_at timestamp with time zone,
    cancelled_by_role character varying(10),
    decline_reason text,
    cancel_reason text,
    CONSTRAINT reservation_cancel_reason_check CHECK (((cancel_reason IS NULL) OR (char_length(cancel_reason) <= 500))),
    CONSTRAINT reservation_cancelled_by_role_check CHECK (((cancelled_by_role)::text = ANY ((ARRAY['patient'::character varying, 'pharmacy'::character varying, 'system'::character varying])::text[]))),
    CONSTRAINT reservation_cancelled_check CHECK ((((status)::text <> 'cancelled'::text) OR ((cancelled_at IS NOT NULL) AND (cancelled_by_role IS NOT NULL) AND (((cancelled_by_role)::text = 'patient'::text) OR (btrim(COALESCE(cancel_reason, ''::text)) <> ''::text))))),
    CONSTRAINT reservation_collected_check CHECK ((((status)::text <> 'collected'::text) OR ((collected_at IS NOT NULL) AND (collected_by IS NOT NULL)))),
    CONSTRAINT reservation_confirmed_check CHECK ((((status)::text <> ALL ((ARRAY['confirmed'::character varying, 'collected'::character varying])::text[])) OR ((confirmed_at IS NOT NULL) AND (expires_at IS NOT NULL)))),
    CONSTRAINT reservation_contact_phone_check CHECK ((btrim((contact_phone)::text) <> ''::text)),
    CONSTRAINT reservation_decline_reason_check CHECK (((decline_reason IS NULL) OR (char_length(decline_reason) <= 500))),
    CONSTRAINT reservation_declined_check CHECK ((((status)::text <> 'declined'::text) OR (btrim(COALESCE(decline_reason, ''::text)) <> ''::text))),
    CONSTRAINT reservation_patient_note_check CHECK (((patient_note IS NULL) OR (char_length(patient_note) <= 500))),
    CONSTRAINT reservation_pharmacy_org_type_check CHECK (((pharmacy_org_type)::text = 'pharmacy'::text)),
    CONSTRAINT reservation_quantity_check CHECK ((quantity > 0)),
    CONSTRAINT reservation_reference_check CHECK (((reference)::text ~ '^RX-[ABCDEFGHJKMNPQRSTUVWXYZ23456789]{10}$'::text)),
    CONSTRAINT reservation_status_check CHECK (((status)::text = ANY ((ARRAY['requested'::character varying, 'confirmed'::character varying, 'declined'::character varying, 'cancelled'::character varying, 'collected'::character varying, 'expired'::character varying])::text[]))),
    CONSTRAINT reservation_status_reason_check CHECK (((status_reason)::text = ANY ((ARRAY['response_window_elapsed'::character varying, 'collection_window_elapsed'::character varying, 'pharmacy_suspended'::character varying])::text[]))),
    CONSTRAINT reservation_status_source_check CHECK (((status_source)::text = ANY ((ARRAY['patient'::character varying, 'pharmacy'::character varying, 'system'::character varying])::text[]))),
    CONSTRAINT reservation_system_actor_check CHECK ((((status_source)::text = 'system'::text) = (status_changed_by IS NULL))),
    CONSTRAINT reservation_system_reason_check CHECK ((((status_source)::text = 'system'::text) = (status_reason IS NOT NULL))),
    CONSTRAINT reservation_unit_price_check CHECK ((unit_price >= (0)::numeric))
);

-- TABLE: stock

CREATE TABLE public.stock (
    stock_id bigint NOT NULL,
    location_id bigint NOT NULL,
    product_id bigint NOT NULL,
    quantity integer DEFAULT 0 NOT NULL,
    last_updated timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_by bigint,
    CONSTRAINT stock_quantity_check CHECK ((quantity >= 0))
);

-- VIEW: patient_availability

CREATE VIEW public.patient_availability AS
 SELECT o.offer_id,
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
            WHEN ((s.quantity - COALESCE(a.allocated, (0)::bigint)) <= 0) THEN 'unavailable'::text
            WHEN ((s.quantity - COALESCE(a.allocated, (0)::bigint)) <= o.low_stock_threshold) THEN 'low_stock'::text
            ELSE 'in_stock'::text
        END AS availability_status,
    GREATEST(s.last_updated, o.last_updated) AS last_updated
   FROM (((((public.product_offer o
     JOIN public.stock s ON (((s.location_id = o.location_id) AND (s.product_id = o.product_id))))
     JOIN public.product p ON (((p.product_id = o.product_id) AND p.is_active)))
     JOIN public.location l ON (((l.location_id = o.location_id) AND l.is_active)))
     JOIN public.organization org ON (((org.organization_id = l.organization_id) AND ((org.type)::text = 'pharmacy'::text) AND ((org.status)::text = 'approved'::text))))
     LEFT JOIN LATERAL ( SELECT sum(r.quantity) AS allocated
           FROM public.reservation r
          WHERE ((r.location_id = o.location_id) AND (r.product_id = o.product_id) AND ((((r.status)::text = 'requested'::text) AND (r.respond_by > clock_timestamp())) OR (((r.status)::text = 'confirmed'::text) AND (r.expires_at > clock_timestamp()))))) a ON (true))
  WHERE o.is_listed;

-- TABLE: phone_verification

CREATE TABLE public.phone_verification (
    verification_id bigint NOT NULL,
    user_id bigint NOT NULL,
    phone_e164 character varying(20) NOT NULL,
    purpose character varying(40) NOT NULL,
    code_hash character varying(64) NOT NULL,
    client_ip_hash character varying(64),
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    attempts integer DEFAULT 0 NOT NULL,
    max_attempts integer NOT NULL,
    consumed_at timestamp with time zone,
    invalidated_at timestamp with time zone,
    delivery_failed_at timestamp with time zone,
    challenge_ref character varying(43),
    provider character varying(20),
    provider_message_id character varying(100),
    delivery_status character varying(30),
    delivery_status_at timestamp with time zone,
    CONSTRAINT phone_verification_attempts_check CHECK ((attempts >= 0)),
    CONSTRAINT phone_verification_challenge_ref_check CHECK (((challenge_ref IS NULL) OR ((challenge_ref)::text ~ '^[A-Za-z0-9_-]{16,43}$'::text))),
    CONSTRAINT phone_verification_expiry_check CHECK ((expires_at > created_at)),
    CONSTRAINT phone_verification_failed_check CHECK (((delivery_failed_at IS NULL) OR (invalidated_at IS NOT NULL))),
    CONSTRAINT phone_verification_max_attempts_check CHECK ((max_attempts > 0)),
    CONSTRAINT phone_verification_phone_e164_check CHECK (((phone_e164)::text ~ '^\+[1-9][0-9]{6,14}$'::text))
);

-- SEQUENCE: phone_verification_verification_id_seq

ALTER TABLE public.phone_verification ALTER COLUMN verification_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.phone_verification_verification_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

-- TABLE: procurement_request

CREATE TABLE public.procurement_request (
    procurement_request_id bigint NOT NULL,
    pharmacy_organization_id bigint NOT NULL,
    supplier_organization_id bigint NOT NULL,
    pharmacy_org_type character varying(20) DEFAULT 'pharmacy'::character varying NOT NULL,
    supplier_org_type character varying(20) DEFAULT 'supplier'::character varying NOT NULL,
    pharmacy_location_id bigint NOT NULL,
    conversation_id bigint NOT NULL,
    status character varying(20) DEFAULT 'submitted'::character varying NOT NULL,
    currency character(3) DEFAULT 'RWF'::bpchar NOT NULL,
    notes text,
    needed_by date,
    status_reason text,
    created_by bigint,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    viewed_at timestamp with time zone,
    CONSTRAINT procurement_request_pharmacy_org_type_check CHECK (((pharmacy_org_type)::text = 'pharmacy'::text)),
    CONSTRAINT procurement_request_status_check CHECK (((status)::text = ANY ((ARRAY['submitted'::character varying, 'viewed'::character varying, 'quoted'::character varying, 'negotiation'::character varying, 'accepted'::character varying, 'rejected'::character varying, 'cancelled'::character varying, 'converted'::character varying])::text[]))),
    CONSTRAINT procurement_request_supplier_org_type_check CHECK (((supplier_org_type)::text = 'supplier'::text))
);

-- TABLE: procurement_request_item

CREATE TABLE public.procurement_request_item (
    procurement_request_item_id bigint NOT NULL,
    procurement_request_id bigint NOT NULL,
    line_no integer NOT NULL,
    product_id bigint,
    medicine_name character varying(255) NOT NULL,
    strength character varying(100),
    dosage_form character varying(100),
    pack_size character varying(100),
    quantity integer NOT NULL,
    notes text,
    CONSTRAINT procurement_request_item_line_no_check CHECK ((line_no > 0)),
    CONSTRAINT procurement_request_item_medicine_name_check CHECK ((btrim((medicine_name)::text) <> ''::text)),
    CONSTRAINT procurement_request_item_quantity_check CHECK ((quantity > 0))
);

-- SEQUENCE: procurement_request_item_procurement_request_item_id_seq

ALTER TABLE public.procurement_request_item ALTER COLUMN procurement_request_item_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.procurement_request_item_procurement_request_item_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

-- SEQUENCE: procurement_request_procurement_request_id_seq

ALTER TABLE public.procurement_request ALTER COLUMN procurement_request_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.procurement_request_procurement_request_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

-- SEQUENCE: product_offer_offer_id_seq

ALTER TABLE public.product_offer ALTER COLUMN offer_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.product_offer_offer_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

-- SEQUENCE: product_product_id_seq

ALTER TABLE public.product ALTER COLUMN product_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.product_product_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

-- TABLE: product_reservation_history

CREATE TABLE public.product_reservation_history (
    history_id bigint NOT NULL,
    product_id bigint NOT NULL,
    dispensing_class character varying(20) NOT NULL,
    stock_unit character varying(10) NOT NULL,
    unit_label character varying(60),
    pack_size character varying(100),
    unit_version integer NOT NULL,
    max_reservation_quantity integer,
    reservation_enabled boolean NOT NULL,
    changed_by bigint NOT NULL,
    changed_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL
);

-- SEQUENCE: product_reservation_history_history_id_seq

ALTER TABLE public.product_reservation_history ALTER COLUMN history_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.product_reservation_history_history_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

-- TABLE: purchase_order

CREATE TABLE public.purchase_order (
    purchase_order_id bigint NOT NULL,
    pharmacy_organization_id bigint NOT NULL,
    supplier_organization_id bigint NOT NULL,
    pharmacy_org_type character varying(20) DEFAULT 'pharmacy'::character varying NOT NULL,
    supplier_org_type character varying(20) DEFAULT 'supplier'::character varying NOT NULL,
    pharmacy_location_id bigint NOT NULL,
    supplier_location_id bigint,
    status character varying(20) DEFAULT 'draft'::character varying NOT NULL,
    currency character(3) DEFAULT 'RWF'::bpchar NOT NULL,
    notes text,
    rejection_reason text,
    created_by bigint NOT NULL,
    responded_by bigint,
    status_changed_by bigint,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    submitted_at timestamp with time zone,
    responded_at timestamp with time zone,
    procurement_request_id bigint,
    quotation_id bigint,
    CONSTRAINT purchase_order_check CHECK ((pharmacy_organization_id <> supplier_organization_id)),
    CONSTRAINT purchase_order_check1 CHECK ((((status)::text = ANY ((ARRAY['draft'::character varying, 'cancelled'::character varying])::text[])) OR (submitted_at IS NOT NULL))),
    CONSTRAINT purchase_order_check2 CHECK ((((status)::text = ANY ((ARRAY['draft'::character varying, 'submitted'::character varying, 'cancelled'::character varying])::text[])) OR (responded_at IS NOT NULL))),
    CONSTRAINT purchase_order_pharmacy_org_type_check CHECK (((pharmacy_org_type)::text = 'pharmacy'::text)),
    CONSTRAINT purchase_order_quotation_check CHECK (((procurement_request_id IS NULL) = (quotation_id IS NULL))),
    CONSTRAINT purchase_order_status_check CHECK (((status)::text = ANY ((ARRAY['draft'::character varying, 'submitted'::character varying, 'countered'::character varying, 'accepted'::character varying, 'rejected'::character varying, 'processing'::character varying, 'dispatched'::character varying, 'delivered'::character varying, 'cancelled'::character varying])::text[]))),
    CONSTRAINT purchase_order_supplier_org_type_check CHECK (((supplier_org_type)::text = 'supplier'::text))
);

-- TABLE: purchase_order_item

CREATE TABLE public.purchase_order_item (
    purchase_order_item_id bigint NOT NULL,
    purchase_order_id bigint NOT NULL,
    product_id bigint,
    requested_quantity integer NOT NULL,
    requested_unit_price numeric(14,2) NOT NULL,
    confirmed_quantity integer,
    confirmed_unit_price numeric(14,2),
    item_description character varying(255),
    CONSTRAINT purchase_order_item_check CHECK (((confirmed_quantity IS NULL) OR (confirmed_quantity <= requested_quantity))),
    CONSTRAINT purchase_order_item_check1 CHECK (((confirmed_quantity IS NULL) = (confirmed_unit_price IS NULL))),
    CONSTRAINT purchase_order_item_confirmed_quantity_check CHECK ((confirmed_quantity > 0)),
    CONSTRAINT purchase_order_item_confirmed_unit_price_check CHECK ((confirmed_unit_price >= (0)::numeric)),
    CONSTRAINT purchase_order_item_description_check CHECK (((product_id IS NOT NULL) OR (btrim((COALESCE(item_description, ''::character varying))::text) <> ''::text))),
    CONSTRAINT purchase_order_item_requested_quantity_check CHECK ((requested_quantity > 0)),
    CONSTRAINT purchase_order_item_requested_unit_price_check CHECK ((requested_unit_price >= (0)::numeric))
);

-- SEQUENCE: purchase_order_item_purchase_order_item_id_seq

ALTER TABLE public.purchase_order_item ALTER COLUMN purchase_order_item_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.purchase_order_item_purchase_order_item_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

-- SEQUENCE: purchase_order_purchase_order_id_seq

ALTER TABLE public.purchase_order ALTER COLUMN purchase_order_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.purchase_order_purchase_order_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

-- TABLE: purchase_order_status_history

CREATE TABLE public.purchase_order_status_history (
    history_id bigint NOT NULL,
    purchase_order_id bigint NOT NULL,
    from_status character varying(20),
    to_status character varying(20) NOT NULL,
    changed_by bigint,
    changed_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    note text,
    CONSTRAINT purchase_order_status_history_from_status_check CHECK (((from_status IS NULL) OR ((from_status)::text = ANY ((ARRAY['draft'::character varying, 'submitted'::character varying, 'countered'::character varying, 'accepted'::character varying, 'rejected'::character varying, 'processing'::character varying, 'dispatched'::character varying, 'delivered'::character varying, 'cancelled'::character varying])::text[])))),
    CONSTRAINT purchase_order_status_history_to_status_check CHECK (((to_status)::text = ANY ((ARRAY['draft'::character varying, 'submitted'::character varying, 'countered'::character varying, 'accepted'::character varying, 'rejected'::character varying, 'processing'::character varying, 'dispatched'::character varying, 'delivered'::character varying, 'cancelled'::character varying])::text[])))
);

-- SEQUENCE: purchase_order_status_history_history_id_seq

ALTER TABLE public.purchase_order_status_history ALTER COLUMN history_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.purchase_order_status_history_history_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

-- TABLE: quotation

CREATE TABLE public.quotation (
    quotation_id bigint NOT NULL,
    procurement_request_id bigint NOT NULL,
    revision integer NOT NULL,
    status character varying(20) DEFAULT 'draft'::character varying NOT NULL,
    currency character(3) DEFAULT 'RWF'::bpchar NOT NULL,
    note text,
    estimated_days integer,
    created_by bigint,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    submitted_by bigint,
    submitted_at timestamp with time zone,
    responded_by bigint,
    responded_at timestamp with time zone,
    response_note text,
    CONSTRAINT quotation_check CHECK ((((status)::text = 'draft'::text) OR (submitted_at IS NOT NULL))),
    CONSTRAINT quotation_estimated_days_check CHECK (((estimated_days >= 0) AND (estimated_days <= 365))),
    CONSTRAINT quotation_revision_check CHECK ((revision > 0)),
    CONSTRAINT quotation_status_check CHECK (((status)::text = ANY ((ARRAY['draft'::character varying, 'submitted'::character varying, 'revision_requested'::character varying, 'accepted'::character varying, 'rejected'::character varying, 'superseded'::character varying])::text[])))
);

-- TABLE: quotation_item

CREATE TABLE public.quotation_item (
    quotation_item_id bigint NOT NULL,
    quotation_id bigint NOT NULL,
    procurement_request_item_id bigint NOT NULL,
    available boolean NOT NULL,
    quantity integer,
    unit_price numeric(14,2),
    note text,
    CONSTRAINT quotation_item_check CHECK ((available = ((quantity IS NOT NULL) AND (unit_price IS NOT NULL)))),
    CONSTRAINT quotation_item_check1 CHECK ((available OR ((quantity IS NULL) AND (unit_price IS NULL)))),
    CONSTRAINT quotation_item_quantity_check CHECK ((quantity > 0)),
    CONSTRAINT quotation_item_unit_price_check CHECK ((unit_price >= (0)::numeric))
);

-- SEQUENCE: quotation_item_quotation_item_id_seq

ALTER TABLE public.quotation_item ALTER COLUMN quotation_item_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.quotation_item_quotation_item_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

-- SEQUENCE: quotation_quotation_id_seq

ALTER TABLE public.quotation ALTER COLUMN quotation_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.quotation_quotation_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

-- TABLE: reservation_collection

CREATE TABLE public.reservation_collection (
    reservation_id bigint NOT NULL,
    collected_by bigint NOT NULL,
    collected_at timestamp with time zone NOT NULL,
    collected_xid xid8 NOT NULL,
    quantity integer NOT NULL,
    recorded_quantity_before integer NOT NULL,
    quantity_after integer NOT NULL,
    override boolean DEFAULT false NOT NULL,
    verified_on_hand integer,
    recorded_quantity_seen integer,
    override_reason text,
    override_by bigint,
    correction_adjustment_id bigint,
    deduction_adjustment_id bigint NOT NULL,
    CONSTRAINT reservation_collection_override_check CHECK (((override AND (verified_on_hand IS NOT NULL) AND (verified_on_hand >= quantity) AND (recorded_quantity_seen IS NOT NULL) AND (override_by IS NOT NULL) AND ((char_length(btrim(COALESCE(override_reason, ''::text))) >= 10) AND (char_length(btrim(COALESCE(override_reason, ''::text))) <= 500))) OR ((NOT override) AND (verified_on_hand IS NULL) AND (recorded_quantity_seen IS NULL) AND (override_reason IS NULL) AND (override_by IS NULL) AND (correction_adjustment_id IS NULL)))),
    CONSTRAINT reservation_collection_quantity_after_check CHECK ((quantity_after >= 0)),
    CONSTRAINT reservation_collection_quantity_check CHECK ((quantity > 0)),
    CONSTRAINT reservation_collection_recorded_quantity_before_check CHECK ((recorded_quantity_before >= 0))
);

-- SEQUENCE: reservation_reservation_id_seq

ALTER TABLE public.reservation ALTER COLUMN reservation_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.reservation_reservation_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

-- TABLE: reservation_status_history

CREATE TABLE public.reservation_status_history (
    history_id bigint NOT NULL,
    reservation_id bigint NOT NULL,
    from_status character varying(20),
    to_status character varying(20) NOT NULL,
    source character varying(10) NOT NULL,
    changed_by bigint,
    system_reason character varying(40),
    reason text,
    changed_at timestamp with time zone NOT NULL,
    CONSTRAINT reservation_status_history_check CHECK ((((source)::text = 'system'::text) = (changed_by IS NULL))),
    CONSTRAINT reservation_status_history_check1 CHECK ((((source)::text = 'system'::text) = (system_reason IS NOT NULL)))
);

-- SEQUENCE: reservation_status_history_history_id_seq

ALTER TABLE public.reservation_status_history ALTER COLUMN history_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.reservation_status_history_history_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

-- TABLE: search_event

CREATE TABLE public.search_event (
    search_event_id bigint NOT NULL,
    query_text character varying(255) NOT NULL,
    drug_id bigint,
    product_id bigint,
    approx_latitude numeric(6,3),
    approx_longitude numeric(6,3),
    results_count integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT search_event_approx_latitude_check CHECK (((approx_latitude IS NULL) OR ((approx_latitude >= ('-90'::integer)::numeric) AND (approx_latitude <= (90)::numeric)))),
    CONSTRAINT search_event_approx_longitude_check CHECK (((approx_longitude IS NULL) OR ((approx_longitude >= ('-180'::integer)::numeric) AND (approx_longitude <= (180)::numeric)))),
    CONSTRAINT search_event_results_count_check CHECK ((results_count >= 0))
);

-- SEQUENCE: search_event_search_event_id_seq

ALTER TABLE public.search_event ALTER COLUMN search_event_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.search_event_search_event_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

-- TABLE: stock_adjustment

CREATE TABLE public.stock_adjustment (
    adjustment_id bigint NOT NULL,
    location_id bigint NOT NULL,
    product_id bigint NOT NULL,
    old_quantity integer,
    new_quantity integer NOT NULL,
    changed_by bigint,
    changed_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    change_type character varying(20) DEFAULT 'quantity_update'::character varying NOT NULL,
    CONSTRAINT stock_adjustment_change_type_check CHECK (((change_type)::text = ANY ((ARRAY['initial_stock'::character varying, 'quantity_update'::character varying, 'stock_deleted'::character varying])::text[]))),
    CONSTRAINT stock_adjustment_new_quantity_check CHECK ((new_quantity >= 0)),
    CONSTRAINT stock_adjustment_old_quantity_check CHECK (((old_quantity IS NULL) OR (old_quantity >= 0)))
);

-- SEQUENCE: stock_adjustment_adjustment_id_seq

ALTER TABLE public.stock_adjustment ALTER COLUMN adjustment_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.stock_adjustment_adjustment_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

-- SEQUENCE: stock_stock_id_seq

ALTER TABLE public.stock ALTER COLUMN stock_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.stock_stock_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

-- VIEW: supplier_listing

CREATE VIEW public.supplier_listing AS
 SELECT o.offer_id,
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
   FROM ((((public.product_offer o
     JOIN public.stock s ON (((s.location_id = o.location_id) AND (s.product_id = o.product_id))))
     JOIN public.product p ON (((p.product_id = o.product_id) AND p.is_active)))
     JOIN public.location l ON (((l.location_id = o.location_id) AND l.is_active)))
     JOIN public.organization org ON (((org.organization_id = l.organization_id) AND ((org.type)::text = 'supplier'::text) AND ((org.status)::text = 'approved'::text))))
  WHERE o.is_listed;

-- CONSTRAINT: app_user app_user_pkey

ALTER TABLE ONLY public.app_user
    ADD CONSTRAINT app_user_pkey PRIMARY KEY (user_id);

-- CONSTRAINT: auth_session auth_session_pkey

ALTER TABLE ONLY public.auth_session
    ADD CONSTRAINT auth_session_pkey PRIMARY KEY (session_id);

-- CONSTRAINT: conversation conversation_pkey

ALTER TABLE ONLY public.conversation
    ADD CONSTRAINT conversation_pkey PRIMARY KEY (conversation_id);

-- CONSTRAINT: conversation_read conversation_read_pkey

ALTER TABLE ONLY public.conversation_read
    ADD CONSTRAINT conversation_read_pkey PRIMARY KEY (conversation_id, user_id);

-- CONSTRAINT: drug drug_pkey

ALTER TABLE ONLY public.drug
    ADD CONSTRAINT drug_pkey PRIMARY KEY (drug_id);

-- CONSTRAINT: email_verification email_verification_pkey

ALTER TABLE ONLY public.email_verification
    ADD CONSTRAINT email_verification_pkey PRIMARY KEY (verification_id);

-- CONSTRAINT: email_verification email_verification_token_hash_key

ALTER TABLE ONLY public.email_verification
    ADD CONSTRAINT email_verification_token_hash_key UNIQUE (token_hash);

-- CONSTRAINT: location location_location_id_organization_id_key

ALTER TABLE ONLY public.location
    ADD CONSTRAINT location_location_id_organization_id_key UNIQUE (location_id, organization_id);

-- CONSTRAINT: location location_pkey

ALTER TABLE ONLY public.location
    ADD CONSTRAINT location_pkey PRIMARY KEY (location_id);

-- CONSTRAINT: membership_branch membership_branch_pkey

ALTER TABLE ONLY public.membership_branch
    ADD CONSTRAINT membership_branch_pkey PRIMARY KEY (membership_id, location_id);

-- CONSTRAINT: membership membership_membership_id_organization_id_key

ALTER TABLE ONLY public.membership
    ADD CONSTRAINT membership_membership_id_organization_id_key UNIQUE (membership_id, organization_id);

-- CONSTRAINT: membership membership_pkey

ALTER TABLE ONLY public.membership
    ADD CONSTRAINT membership_pkey PRIMARY KEY (membership_id);

-- CONSTRAINT: membership membership_user_id_organization_id_key

ALTER TABLE ONLY public.membership
    ADD CONSTRAINT membership_user_id_organization_id_key UNIQUE (user_id, organization_id);

-- CONSTRAINT: message message_pkey

ALTER TABLE ONLY public.message
    ADD CONSTRAINT message_pkey PRIMARY KEY (message_id);

-- CONSTRAINT: notification notification_pkey

ALTER TABLE ONLY public.notification
    ADD CONSTRAINT notification_pkey PRIMARY KEY (notification_id);

-- CONSTRAINT: notification_read notification_read_pkey

ALTER TABLE ONLY public.notification_read
    ADD CONSTRAINT notification_read_pkey PRIMARY KEY (notification_id, user_id);

-- CONSTRAINT: offer_unit_acknowledgement offer_unit_acknowledgement_pkey

ALTER TABLE ONLY public.offer_unit_acknowledgement
    ADD CONSTRAINT offer_unit_acknowledgement_pkey PRIMARY KEY (location_id, product_id, unit_version);

-- CONSTRAINT: organization_document organization_document_pkey

ALTER TABLE ONLY public.organization_document
    ADD CONSTRAINT organization_document_pkey PRIMARY KEY (document_id);

-- CONSTRAINT: organization_document organization_document_storage_key_key

ALTER TABLE ONLY public.organization_document
    ADD CONSTRAINT organization_document_storage_key_key UNIQUE (storage_key);

-- CONSTRAINT: organization_invitation organization_invitation_pkey

ALTER TABLE ONLY public.organization_invitation
    ADD CONSTRAINT organization_invitation_pkey PRIMARY KEY (invitation_id);

-- CONSTRAINT: organization_invitation organization_invitation_token_hash_key

ALTER TABLE ONLY public.organization_invitation
    ADD CONSTRAINT organization_invitation_token_hash_key UNIQUE (token_hash);

-- CONSTRAINT: organization organization_organization_id_type_key

ALTER TABLE ONLY public.organization
    ADD CONSTRAINT organization_organization_id_type_key UNIQUE (organization_id, type);

-- CONSTRAINT: organization organization_pkey

ALTER TABLE ONLY public.organization
    ADD CONSTRAINT organization_pkey PRIMARY KEY (organization_id);

-- CONSTRAINT: password_reset password_reset_pkey

ALTER TABLE ONLY public.password_reset
    ADD CONSTRAINT password_reset_pkey PRIMARY KEY (reset_id);

-- CONSTRAINT: password_reset password_reset_token_hash_key

ALTER TABLE ONLY public.password_reset
    ADD CONSTRAINT password_reset_token_hash_key UNIQUE (token_hash);

-- CONSTRAINT: phone_verification phone_verification_pkey

ALTER TABLE ONLY public.phone_verification
    ADD CONSTRAINT phone_verification_pkey PRIMARY KEY (verification_id);

-- CONSTRAINT: procurement_request_item procurement_request_item_pkey

ALTER TABLE ONLY public.procurement_request_item
    ADD CONSTRAINT procurement_request_item_pkey PRIMARY KEY (procurement_request_item_id);

-- CONSTRAINT: procurement_request_item procurement_request_item_procurement_request_id_line_no_key

ALTER TABLE ONLY public.procurement_request_item
    ADD CONSTRAINT procurement_request_item_procurement_request_id_line_no_key UNIQUE (procurement_request_id, line_no);

-- CONSTRAINT: procurement_request_item procurement_request_item_procurement_request_id_product_id_key

ALTER TABLE ONLY public.procurement_request_item
    ADD CONSTRAINT procurement_request_item_procurement_request_id_product_id_key UNIQUE (procurement_request_id, product_id);

-- CONSTRAINT: procurement_request procurement_request_pkey

ALTER TABLE ONLY public.procurement_request
    ADD CONSTRAINT procurement_request_pkey PRIMARY KEY (procurement_request_id);

-- CONSTRAINT: product_offer product_offer_location_id_product_id_key

ALTER TABLE ONLY public.product_offer
    ADD CONSTRAINT product_offer_location_id_product_id_key UNIQUE (location_id, product_id);

-- CONSTRAINT: product_offer product_offer_pkey

ALTER TABLE ONLY public.product_offer
    ADD CONSTRAINT product_offer_pkey PRIMARY KEY (offer_id);

-- CONSTRAINT: product product_pkey

ALTER TABLE ONLY public.product
    ADD CONSTRAINT product_pkey PRIMARY KEY (product_id);

-- CONSTRAINT: product_reservation_history product_reservation_history_pkey

ALTER TABLE ONLY public.product_reservation_history
    ADD CONSTRAINT product_reservation_history_pkey PRIMARY KEY (history_id);

-- CONSTRAINT: purchase_order_item purchase_order_item_pkey

ALTER TABLE ONLY public.purchase_order_item
    ADD CONSTRAINT purchase_order_item_pkey PRIMARY KEY (purchase_order_item_id);

-- CONSTRAINT: purchase_order_item purchase_order_item_purchase_order_id_product_id_key

ALTER TABLE ONLY public.purchase_order_item
    ADD CONSTRAINT purchase_order_item_purchase_order_id_product_id_key UNIQUE (purchase_order_id, product_id);

-- CONSTRAINT: purchase_order purchase_order_pkey

ALTER TABLE ONLY public.purchase_order
    ADD CONSTRAINT purchase_order_pkey PRIMARY KEY (purchase_order_id);

-- CONSTRAINT: purchase_order purchase_order_procurement_request_id_key

ALTER TABLE ONLY public.purchase_order
    ADD CONSTRAINT purchase_order_procurement_request_id_key UNIQUE (procurement_request_id);

-- CONSTRAINT: purchase_order purchase_order_quotation_id_key

ALTER TABLE ONLY public.purchase_order
    ADD CONSTRAINT purchase_order_quotation_id_key UNIQUE (quotation_id);

-- CONSTRAINT: purchase_order_status_history purchase_order_status_history_pkey

ALTER TABLE ONLY public.purchase_order_status_history
    ADD CONSTRAINT purchase_order_status_history_pkey PRIMARY KEY (history_id);

-- CONSTRAINT: quotation_item quotation_item_pkey

ALTER TABLE ONLY public.quotation_item
    ADD CONSTRAINT quotation_item_pkey PRIMARY KEY (quotation_item_id);

-- CONSTRAINT: quotation_item quotation_item_quotation_id_procurement_request_item_id_key

ALTER TABLE ONLY public.quotation_item
    ADD CONSTRAINT quotation_item_quotation_id_procurement_request_item_id_key UNIQUE (quotation_id, procurement_request_item_id);

-- CONSTRAINT: quotation quotation_pkey

ALTER TABLE ONLY public.quotation
    ADD CONSTRAINT quotation_pkey PRIMARY KEY (quotation_id);

-- CONSTRAINT: quotation quotation_procurement_request_id_revision_key

ALTER TABLE ONLY public.quotation
    ADD CONSTRAINT quotation_procurement_request_id_revision_key UNIQUE (procurement_request_id, revision);

-- CONSTRAINT: reservation_collection reservation_collection_pkey

ALTER TABLE ONLY public.reservation_collection
    ADD CONSTRAINT reservation_collection_pkey PRIMARY KEY (reservation_id);

-- CONSTRAINT: reservation reservation_pkey

ALTER TABLE ONLY public.reservation
    ADD CONSTRAINT reservation_pkey PRIMARY KEY (reservation_id);

-- CONSTRAINT: reservation reservation_reference_key

ALTER TABLE ONLY public.reservation
    ADD CONSTRAINT reservation_reference_key UNIQUE (reference);

-- CONSTRAINT: reservation_status_history reservation_status_history_pkey

ALTER TABLE ONLY public.reservation_status_history
    ADD CONSTRAINT reservation_status_history_pkey PRIMARY KEY (history_id);

-- CONSTRAINT: search_event search_event_pkey

ALTER TABLE ONLY public.search_event
    ADD CONSTRAINT search_event_pkey PRIMARY KEY (search_event_id);

-- CONSTRAINT: stock_adjustment stock_adjustment_pkey

ALTER TABLE ONLY public.stock_adjustment
    ADD CONSTRAINT stock_adjustment_pkey PRIMARY KEY (adjustment_id);

-- CONSTRAINT: stock stock_location_id_product_id_key

ALTER TABLE ONLY public.stock
    ADD CONSTRAINT stock_location_id_product_id_key UNIQUE (location_id, product_id);

-- CONSTRAINT: stock stock_pkey

ALTER TABLE ONLY public.stock
    ADD CONSTRAINT stock_pkey PRIMARY KEY (stock_id);

-- CONSTRAINT: conversation uq_conversation_branch

ALTER TABLE ONLY public.conversation
    ADD CONSTRAINT uq_conversation_branch UNIQUE (pharmacy_location_id, supplier_organization_id);

-- CONSTRAINT: reservation uq_reservation_client_request

ALTER TABLE ONLY public.reservation
    ADD CONSTRAINT uq_reservation_client_request UNIQUE (patient_user_id, client_request_id);

-- INDEX: idx_conversation_supplier

CREATE INDEX idx_conversation_supplier ON public.conversation USING btree (supplier_organization_id, last_message_at DESC);

-- INDEX: idx_location_coords

CREATE INDEX idx_location_coords ON public.location USING btree (latitude, longitude) WHERE ((latitude IS NOT NULL) AND (longitude IS NOT NULL));

-- INDEX: idx_location_organization

CREATE INDEX idx_location_organization ON public.location USING btree (organization_id);

-- INDEX: idx_membership_organization

CREATE INDEX idx_membership_organization ON public.membership USING btree (organization_id);

-- INDEX: idx_membership_user

CREATE INDEX idx_membership_user ON public.membership USING btree (user_id);

-- INDEX: idx_message_conversation

CREATE INDEX idx_message_conversation ON public.message USING btree (conversation_id, message_id);

-- INDEX: idx_notification_org

CREATE INDEX idx_notification_org ON public.notification USING btree (organization_id, notification_id DESC);

-- INDEX: idx_notification_read_user

CREATE INDEX idx_notification_read_user ON public.notification_read USING btree (user_id);

-- INDEX: idx_notification_recipient

CREATE INDEX idx_notification_recipient ON public.notification USING btree (recipient_user_id, notification_id DESC) WHERE (recipient_user_id IS NOT NULL);

-- INDEX: idx_offer_product_listed

CREATE INDEX idx_offer_product_listed ON public.product_offer USING btree (product_id, is_listed);

-- INDEX: idx_org_document_org

CREATE INDEX idx_org_document_org ON public.organization_document USING btree (organization_id, verification_status);

-- INDEX: idx_organization_status

CREATE INDEX idx_organization_status ON public.organization USING btree (type, status);

-- INDEX: idx_po_status_history_po

CREATE INDEX idx_po_status_history_po ON public.purchase_order_status_history USING btree (purchase_order_id, changed_at);

-- INDEX: idx_procurement_request_pharmacy

CREATE INDEX idx_procurement_request_pharmacy ON public.procurement_request USING btree (pharmacy_organization_id, created_at DESC);

-- INDEX: idx_procurement_request_supplier

CREATE INDEX idx_procurement_request_supplier ON public.procurement_request USING btree (supplier_organization_id, status, created_at DESC);

-- INDEX: idx_product_drug

CREATE INDEX idx_product_drug ON public.product USING btree (drug_id);

-- INDEX: idx_product_reservation_history

CREATE INDEX idx_product_reservation_history ON public.product_reservation_history USING btree (product_id, history_id);

-- INDEX: idx_purchase_order_item_product

CREATE INDEX idx_purchase_order_item_product ON public.purchase_order_item USING btree (product_id);

-- INDEX: idx_purchase_order_pharmacy

CREATE INDEX idx_purchase_order_pharmacy ON public.purchase_order USING btree (pharmacy_organization_id, created_at);

-- INDEX: idx_purchase_order_supplier

CREATE INDEX idx_purchase_order_supplier ON public.purchase_order USING btree (supplier_organization_id, status, created_at);

-- INDEX: idx_reservation_allocation

CREATE INDEX idx_reservation_allocation ON public.reservation USING btree (location_id, product_id) INCLUDE (quantity, expires_at) WHERE ((status)::text = 'confirmed'::text);

-- INDEX: idx_reservation_expires_at

CREATE INDEX idx_reservation_expires_at ON public.reservation USING btree (expires_at) WHERE ((status)::text = 'confirmed'::text);

-- INDEX: idx_reservation_location_open

CREATE INDEX idx_reservation_location_open ON public.reservation USING btree (location_id) WHERE ((status)::text = ANY ((ARRAY['requested'::character varying, 'confirmed'::character varying])::text[]));

-- INDEX: idx_reservation_open_hold

CREATE INDEX idx_reservation_open_hold ON public.reservation USING btree (location_id, product_id) INCLUDE (quantity, respond_by, expires_at) WHERE ((status)::text = ANY ((ARRAY['requested'::character varying, 'confirmed'::character varying])::text[]));

-- INDEX: idx_reservation_patient

CREATE INDEX idx_reservation_patient ON public.reservation USING btree (patient_user_id, created_at DESC);

-- INDEX: idx_reservation_pharmacy

CREATE INDEX idx_reservation_pharmacy ON public.reservation USING btree (pharmacy_organization_id, status, created_at DESC);

-- INDEX: idx_reservation_product_open

CREATE INDEX idx_reservation_product_open ON public.reservation USING btree (product_id) WHERE ((status)::text = ANY ((ARRAY['requested'::character varying, 'confirmed'::character varying])::text[]));

-- INDEX: idx_reservation_respond_by

CREATE INDEX idx_reservation_respond_by ON public.reservation USING btree (respond_by) WHERE ((status)::text = 'requested'::text);

-- INDEX: idx_reservation_status_history

CREATE INDEX idx_reservation_status_history ON public.reservation_status_history USING btree (reservation_id, history_id);

-- INDEX: idx_search_event_created

CREATE INDEX idx_search_event_created ON public.search_event USING btree (created_at);

-- INDEX: idx_search_event_product

CREATE INDEX idx_search_event_product ON public.search_event USING btree (product_id) WHERE (product_id IS NOT NULL);

-- INDEX: idx_stock_adjustment_lookup

CREATE INDEX idx_stock_adjustment_lookup ON public.stock_adjustment USING btree (location_id, product_id, changed_at);

-- INDEX: idx_stock_product_location

CREATE INDEX idx_stock_product_location ON public.stock USING btree (product_id, location_id);

-- INDEX: ix_auth_session_user_active

CREATE INDEX ix_auth_session_user_active ON public.auth_session USING btree (user_id) WHERE (revoked_at IS NULL);

-- INDEX: ix_email_verification_ip_created

CREATE INDEX ix_email_verification_ip_created ON public.email_verification USING btree (client_ip_hash, created_at);

-- INDEX: ix_email_verification_user_created

CREATE INDEX ix_email_verification_user_created ON public.email_verification USING btree (user_id, created_at);

-- INDEX: ix_membership_branch_location

CREATE INDEX ix_membership_branch_location ON public.membership_branch USING btree (location_id);

-- INDEX: ix_organization_invitation_org

CREATE INDEX ix_organization_invitation_org ON public.organization_invitation USING btree (organization_id, created_at);

-- INDEX: ix_password_reset_ip_created

CREATE INDEX ix_password_reset_ip_created ON public.password_reset USING btree (client_ip_hash, created_at);

-- INDEX: ix_password_reset_user_created

CREATE INDEX ix_password_reset_user_created ON public.password_reset USING btree (user_id, created_at);

-- INDEX: ix_phone_verification_created

CREATE INDEX ix_phone_verification_created ON public.phone_verification USING btree (created_at);

-- INDEX: ix_phone_verification_ip_created

CREATE INDEX ix_phone_verification_ip_created ON public.phone_verification USING btree (client_ip_hash, created_at);

-- INDEX: ix_phone_verification_phone_created

CREATE INDEX ix_phone_verification_phone_created ON public.phone_verification USING btree (phone_e164, created_at);

-- INDEX: ix_phone_verification_provider_message

CREATE INDEX ix_phone_verification_provider_message ON public.phone_verification USING btree (provider, provider_message_id) WHERE (provider_message_id IS NOT NULL);

-- INDEX: ix_phone_verification_user_purpose

CREATE INDEX ix_phone_verification_user_purpose ON public.phone_verification USING btree (user_id, purpose, created_at);

-- INDEX: uq_app_user_email

CREATE UNIQUE INDEX uq_app_user_email ON public.app_user USING btree (lower(btrim((email)::text)));

-- INDEX: uq_drug_name

CREATE UNIQUE INDEX uq_drug_name ON public.drug USING btree (lower(btrim((name)::text)));

-- INDEX: uq_email_verification_one_active

CREATE UNIQUE INDEX uq_email_verification_one_active ON public.email_verification USING btree (user_id) WHERE ((consumed_at IS NULL) AND (invalidated_at IS NULL));

-- INDEX: uq_notification_reservation_event

CREATE UNIQUE INDEX uq_notification_reservation_event ON public.notification USING btree (reservation_id, kind, COALESCE(organization_id, (0)::bigint), COALESCE(recipient_user_id, (0)::bigint)) WHERE (reservation_id IS NOT NULL);

-- INDEX: uq_organization_invitation_open

CREATE UNIQUE INDEX uq_organization_invitation_open ON public.organization_invitation USING btree (organization_id, email) WHERE ((accepted_at IS NULL) AND (revoked_at IS NULL));

-- INDEX: uq_password_reset_one_active

CREATE UNIQUE INDEX uq_password_reset_one_active ON public.password_reset USING btree (user_id) WHERE ((used_at IS NULL) AND (invalidated_at IS NULL));

-- INDEX: uq_phone_verification_challenge_ref

CREATE UNIQUE INDEX uq_phone_verification_challenge_ref ON public.phone_verification USING btree (challenge_ref) WHERE (challenge_ref IS NOT NULL);

-- INDEX: uq_phone_verification_one_active

CREATE UNIQUE INDEX uq_phone_verification_one_active ON public.phone_verification USING btree (user_id, purpose) WHERE ((consumed_at IS NULL) AND (invalidated_at IS NULL));

-- INDEX: uq_product_barcode

CREATE UNIQUE INDEX uq_product_barcode ON public.product USING btree (lower(btrim((barcode)::text))) WHERE ((barcode IS NOT NULL) AND (btrim((barcode)::text) <> ''::text));

-- INDEX: uq_product_identity

CREATE UNIQUE INDEX uq_product_identity ON public.product USING btree (drug_id, lower(btrim((COALESCE(brand, ''::character varying))::text)), lower(btrim((COALESCE(strength, ''::character varying))::text)), lower(btrim((COALESCE(dosage_form, ''::character varying))::text)), lower(btrim((COALESCE(pack_size, ''::character varying))::text)), lower(btrim((COALESCE(manufacturer, ''::character varying))::text)));

-- INDEX: uq_quotation_accepted

CREATE UNIQUE INDEX uq_quotation_accepted ON public.quotation USING btree (procurement_request_id) WHERE ((status)::text = 'accepted'::text);

-- INDEX: uq_quotation_open

CREATE UNIQUE INDEX uq_quotation_open ON public.quotation USING btree (procurement_request_id) WHERE ((status)::text = ANY ((ARRAY['draft'::character varying, 'submitted'::character varying])::text[]));

-- INDEX: uq_reservation_open_pair

CREATE UNIQUE INDEX uq_reservation_open_pair ON public.reservation USING btree (patient_user_id, location_id, product_id) WHERE ((status)::text = ANY ((ARRAY['requested'::character varying, 'confirmed'::character varying])::text[]));

-- TRIGGER: app_user trg_app_user_updated_at

CREATE TRIGGER trg_app_user_updated_at BEFORE UPDATE ON public.app_user FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- TRIGGER: location trg_location_updated_at

CREATE TRIGGER trg_location_updated_at BEFORE UPDATE ON public.location FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- TRIGGER: message trg_message_guard

CREATE TRIGGER trg_message_guard BEFORE INSERT OR DELETE OR UPDATE ON public.message FOR EACH ROW EXECUTE FUNCTION public.message_guard();

-- TRIGGER: offer_unit_acknowledgement trg_offer_unit_acknowledgement_guard

CREATE TRIGGER trg_offer_unit_acknowledgement_guard BEFORE INSERT ON public.offer_unit_acknowledgement FOR EACH ROW EXECUTE FUNCTION public.offer_unit_acknowledgement_guard();

-- TRIGGER: offer_unit_acknowledgement trg_offer_unit_acknowledgement_immutable

CREATE TRIGGER trg_offer_unit_acknowledgement_immutable BEFORE DELETE OR UPDATE ON public.offer_unit_acknowledgement FOR EACH ROW EXECUTE FUNCTION public.reject_change();

-- TRIGGER: organization trg_organization_updated_at

CREATE TRIGGER trg_organization_updated_at BEFORE UPDATE ON public.organization FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- TRIGGER: product_offer trg_product_offer_before_delete

CREATE TRIGGER trg_product_offer_before_delete BEFORE DELETE ON public.product_offer FOR EACH ROW EXECUTE FUNCTION public.product_offer_before_delete();

-- TRIGGER: product_offer trg_product_offer_before_write

CREATE TRIGGER trg_product_offer_before_write BEFORE INSERT OR UPDATE ON public.product_offer FOR EACH ROW EXECUTE FUNCTION public.product_offer_before_write();

-- TRIGGER: product trg_product_reservation_guard

CREATE TRIGGER trg_product_reservation_guard BEFORE INSERT OR UPDATE ON public.product FOR EACH ROW EXECUTE FUNCTION public.product_reservation_guard();

-- TRIGGER: product_reservation_history trg_product_reservation_history_immutable

CREATE TRIGGER trg_product_reservation_history_immutable BEFORE DELETE OR UPDATE ON public.product_reservation_history FOR EACH ROW EXECUTE FUNCTION public.reject_change();

-- TRIGGER: product trg_product_reservation_log

CREATE TRIGGER trg_product_reservation_log AFTER INSERT OR UPDATE ON public.product FOR EACH ROW EXECUTE FUNCTION public.product_reservation_log();

-- TRIGGER: purchase_order trg_purchase_order_before_write

CREATE TRIGGER trg_purchase_order_before_write BEFORE INSERT OR UPDATE ON public.purchase_order FOR EACH ROW EXECUTE FUNCTION public.purchase_order_before_write();

-- TRIGGER: purchase_order_item trg_purchase_order_item_guard

CREATE TRIGGER trg_purchase_order_item_guard BEFORE INSERT OR DELETE OR UPDATE ON public.purchase_order_item FOR EACH ROW EXECUTE FUNCTION public.purchase_order_item_guard();

-- TRIGGER: purchase_order trg_purchase_order_log_status

CREATE TRIGGER trg_purchase_order_log_status AFTER INSERT OR UPDATE OF status ON public.purchase_order FOR EACH ROW EXECUTE FUNCTION public.purchase_order_log_status();

-- TRIGGER: purchase_order trg_purchase_order_no_delete

CREATE TRIGGER trg_purchase_order_no_delete BEFORE DELETE ON public.purchase_order FOR EACH ROW EXECUTE FUNCTION public.purchase_order_no_delete();

-- TRIGGER: purchase_order trg_purchase_order_updated_at

CREATE TRIGGER trg_purchase_order_updated_at BEFORE UPDATE ON public.purchase_order FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- TRIGGER: quotation_item trg_quotation_item_guard

CREATE TRIGGER trg_quotation_item_guard BEFORE INSERT OR DELETE OR UPDATE ON public.quotation_item FOR EACH ROW EXECUTE FUNCTION public.quotation_item_guard();

-- TRIGGER: reservation trg_reservation_before_insert

CREATE TRIGGER trg_reservation_before_insert BEFORE INSERT ON public.reservation FOR EACH ROW EXECUTE FUNCTION public.reservation_before_insert();

-- TRIGGER: reservation trg_reservation_before_update

CREATE TRIGGER trg_reservation_before_update BEFORE UPDATE ON public.reservation FOR EACH ROW EXECUTE FUNCTION public.reservation_before_update();

-- TRIGGER: reservation_collection trg_reservation_collection_before_insert

CREATE TRIGGER trg_reservation_collection_before_insert BEFORE INSERT ON public.reservation_collection FOR EACH ROW EXECUTE FUNCTION public.reservation_collection_before_insert();

-- TRIGGER: reservation_collection trg_reservation_collection_commit_check

CREATE CONSTRAINT TRIGGER trg_reservation_collection_commit_check AFTER INSERT ON public.reservation_collection DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.reservation_collection_commit_check();

-- TRIGGER: reservation_collection trg_reservation_collection_immutable

CREATE TRIGGER trg_reservation_collection_immutable BEFORE DELETE OR UPDATE ON public.reservation_collection FOR EACH ROW EXECUTE FUNCTION public.reject_change();

-- TRIGGER: reservation trg_reservation_log_status

CREATE TRIGGER trg_reservation_log_status AFTER INSERT OR UPDATE OF status ON public.reservation FOR EACH ROW EXECUTE FUNCTION public.reservation_log_status();

-- TRIGGER: reservation trg_reservation_no_delete

CREATE TRIGGER trg_reservation_no_delete BEFORE DELETE ON public.reservation FOR EACH ROW EXECUTE FUNCTION public.reject_change();

-- TRIGGER: reservation_status_history trg_reservation_status_history_immutable

CREATE TRIGGER trg_reservation_status_history_immutable BEFORE DELETE OR UPDATE ON public.reservation_status_history FOR EACH ROW EXECUTE FUNCTION public.reject_change();

-- TRIGGER: stock trg_stock_before_delete

CREATE TRIGGER trg_stock_before_delete BEFORE DELETE ON public.stock FOR EACH ROW EXECUTE FUNCTION public.stock_before_delete();

-- TRIGGER: stock trg_stock_before_update

CREATE TRIGGER trg_stock_before_update BEFORE INSERT OR UPDATE ON public.stock FOR EACH ROW EXECUTE FUNCTION public.stock_before_update();

-- TRIGGER: stock trg_stock_log_adjustment

CREATE TRIGGER trg_stock_log_adjustment AFTER INSERT OR UPDATE ON public.stock FOR EACH ROW EXECUTE FUNCTION public.stock_log_adjustment();

-- TRIGGER: stock trg_stock_log_delete

CREATE TRIGGER trg_stock_log_delete AFTER DELETE ON public.stock FOR EACH ROW EXECUTE FUNCTION public.stock_log_delete();

-- FK CONSTRAINT: auth_session auth_session_user_id_fkey

ALTER TABLE ONLY public.auth_session
    ADD CONSTRAINT auth_session_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(user_id) ON DELETE CASCADE;

-- FK CONSTRAINT: conversation conversation_created_by_fkey

ALTER TABLE ONLY public.conversation
    ADD CONSTRAINT conversation_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.app_user(user_id) ON DELETE SET NULL;

-- FK CONSTRAINT: conversation conversation_pharmacy_location_fkey

ALTER TABLE ONLY public.conversation
    ADD CONSTRAINT conversation_pharmacy_location_fkey FOREIGN KEY (pharmacy_location_id, pharmacy_organization_id) REFERENCES public.location(location_id, organization_id);

-- FK CONSTRAINT: conversation conversation_pharmacy_organization_id_pharmacy_org_type_fkey

ALTER TABLE ONLY public.conversation
    ADD CONSTRAINT conversation_pharmacy_organization_id_pharmacy_org_type_fkey FOREIGN KEY (pharmacy_organization_id, pharmacy_org_type) REFERENCES public.organization(organization_id, type);

-- FK CONSTRAINT: conversation_read conversation_read_conversation_id_fkey

ALTER TABLE ONLY public.conversation_read
    ADD CONSTRAINT conversation_read_conversation_id_fkey FOREIGN KEY (conversation_id) REFERENCES public.conversation(conversation_id) ON DELETE CASCADE;

-- FK CONSTRAINT: conversation_read conversation_read_user_id_fkey

ALTER TABLE ONLY public.conversation_read
    ADD CONSTRAINT conversation_read_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(user_id) ON DELETE CASCADE;

-- FK CONSTRAINT: conversation conversation_supplier_organization_id_supplier_org_type_fkey

ALTER TABLE ONLY public.conversation
    ADD CONSTRAINT conversation_supplier_organization_id_supplier_org_type_fkey FOREIGN KEY (supplier_organization_id, supplier_org_type) REFERENCES public.organization(organization_id, type);

-- FK CONSTRAINT: email_verification email_verification_user_id_fkey

ALTER TABLE ONLY public.email_verification
    ADD CONSTRAINT email_verification_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(user_id) ON DELETE CASCADE;

-- FK CONSTRAINT: location location_organization_id_fkey

ALTER TABLE ONLY public.location
    ADD CONSTRAINT location_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organization(organization_id) ON DELETE CASCADE;

-- FK CONSTRAINT: membership_branch membership_branch_assigned_by_fkey

ALTER TABLE ONLY public.membership_branch
    ADD CONSTRAINT membership_branch_assigned_by_fkey FOREIGN KEY (assigned_by) REFERENCES public.app_user(user_id);

-- FK CONSTRAINT: membership_branch membership_branch_location_fkey

ALTER TABLE ONLY public.membership_branch
    ADD CONSTRAINT membership_branch_location_fkey FOREIGN KEY (location_id, organization_id) REFERENCES public.location(location_id, organization_id);

-- FK CONSTRAINT: membership_branch membership_branch_membership_fkey

ALTER TABLE ONLY public.membership_branch
    ADD CONSTRAINT membership_branch_membership_fkey FOREIGN KEY (membership_id, organization_id) REFERENCES public.membership(membership_id, organization_id) ON DELETE CASCADE;

-- FK CONSTRAINT: membership membership_organization_id_fkey

ALTER TABLE ONLY public.membership
    ADD CONSTRAINT membership_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organization(organization_id) ON DELETE CASCADE;

-- FK CONSTRAINT: membership membership_user_id_fkey

ALTER TABLE ONLY public.membership
    ADD CONSTRAINT membership_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(user_id) ON DELETE CASCADE;

-- FK CONSTRAINT: message message_conversation_id_fkey

ALTER TABLE ONLY public.message
    ADD CONSTRAINT message_conversation_id_fkey FOREIGN KEY (conversation_id) REFERENCES public.conversation(conversation_id);

-- FK CONSTRAINT: message message_sender_organization_id_fkey

ALTER TABLE ONLY public.message
    ADD CONSTRAINT message_sender_organization_id_fkey FOREIGN KEY (sender_organization_id) REFERENCES public.organization(organization_id);

-- FK CONSTRAINT: message message_sender_user_id_fkey

ALTER TABLE ONLY public.message
    ADD CONSTRAINT message_sender_user_id_fkey FOREIGN KEY (sender_user_id) REFERENCES public.app_user(user_id) ON DELETE SET NULL;

-- FK CONSTRAINT: notification notification_conversation_id_fkey

ALTER TABLE ONLY public.notification
    ADD CONSTRAINT notification_conversation_id_fkey FOREIGN KEY (conversation_id) REFERENCES public.conversation(conversation_id) ON DELETE CASCADE;

-- FK CONSTRAINT: notification notification_from_organization_id_fkey

ALTER TABLE ONLY public.notification
    ADD CONSTRAINT notification_from_organization_id_fkey FOREIGN KEY (from_organization_id) REFERENCES public.organization(organization_id) ON DELETE SET NULL;

-- FK CONSTRAINT: notification notification_organization_id_fkey

ALTER TABLE ONLY public.notification
    ADD CONSTRAINT notification_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organization(organization_id) ON DELETE CASCADE;

-- FK CONSTRAINT: notification notification_procurement_request_id_fkey

ALTER TABLE ONLY public.notification
    ADD CONSTRAINT notification_procurement_request_id_fkey FOREIGN KEY (procurement_request_id) REFERENCES public.procurement_request(procurement_request_id) ON DELETE CASCADE;

-- FK CONSTRAINT: notification notification_purchase_order_id_fkey

ALTER TABLE ONLY public.notification
    ADD CONSTRAINT notification_purchase_order_id_fkey FOREIGN KEY (purchase_order_id) REFERENCES public.purchase_order(purchase_order_id) ON DELETE CASCADE;

-- FK CONSTRAINT: notification notification_quotation_id_fkey

ALTER TABLE ONLY public.notification
    ADD CONSTRAINT notification_quotation_id_fkey FOREIGN KEY (quotation_id) REFERENCES public.quotation(quotation_id) ON DELETE CASCADE;

-- FK CONSTRAINT: notification_read notification_read_notification_id_fkey

ALTER TABLE ONLY public.notification_read
    ADD CONSTRAINT notification_read_notification_id_fkey FOREIGN KEY (notification_id) REFERENCES public.notification(notification_id) ON DELETE CASCADE;

-- FK CONSTRAINT: notification_read notification_read_user_id_fkey

ALTER TABLE ONLY public.notification_read
    ADD CONSTRAINT notification_read_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(user_id) ON DELETE CASCADE;

-- FK CONSTRAINT: notification notification_recipient_user_id_fkey

ALTER TABLE ONLY public.notification
    ADD CONSTRAINT notification_recipient_user_id_fkey FOREIGN KEY (recipient_user_id) REFERENCES public.app_user(user_id) ON DELETE CASCADE;

-- FK CONSTRAINT: notification notification_reservation_id_fkey

ALTER TABLE ONLY public.notification
    ADD CONSTRAINT notification_reservation_id_fkey FOREIGN KEY (reservation_id) REFERENCES public.reservation(reservation_id) ON DELETE CASCADE;

-- FK CONSTRAINT: offer_unit_acknowledgement offer_unit_acknowledgement_acknowledged_by_fkey

ALTER TABLE ONLY public.offer_unit_acknowledgement
    ADD CONSTRAINT offer_unit_acknowledgement_acknowledged_by_fkey FOREIGN KEY (acknowledged_by) REFERENCES public.app_user(user_id);

-- FK CONSTRAINT: offer_unit_acknowledgement offer_unit_acknowledgement_location_id_fkey

ALTER TABLE ONLY public.offer_unit_acknowledgement
    ADD CONSTRAINT offer_unit_acknowledgement_location_id_fkey FOREIGN KEY (location_id) REFERENCES public.location(location_id);

-- FK CONSTRAINT: offer_unit_acknowledgement offer_unit_acknowledgement_product_id_fkey

ALTER TABLE ONLY public.offer_unit_acknowledgement
    ADD CONSTRAINT offer_unit_acknowledgement_product_id_fkey FOREIGN KEY (product_id) REFERENCES public.product(product_id);

-- FK CONSTRAINT: organization_document organization_document_organization_id_fkey

ALTER TABLE ONLY public.organization_document
    ADD CONSTRAINT organization_document_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organization(organization_id) ON DELETE CASCADE;

-- FK CONSTRAINT: organization_document organization_document_reviewed_by_fkey

ALTER TABLE ONLY public.organization_document
    ADD CONSTRAINT organization_document_reviewed_by_fkey FOREIGN KEY (reviewed_by) REFERENCES public.app_user(user_id);

-- FK CONSTRAINT: organization_invitation organization_invitation_accepted_by_fkey

ALTER TABLE ONLY public.organization_invitation
    ADD CONSTRAINT organization_invitation_accepted_by_fkey FOREIGN KEY (accepted_by) REFERENCES public.app_user(user_id) ON DELETE SET NULL;

-- FK CONSTRAINT: organization_invitation organization_invitation_invited_by_fkey

ALTER TABLE ONLY public.organization_invitation
    ADD CONSTRAINT organization_invitation_invited_by_fkey FOREIGN KEY (invited_by) REFERENCES public.app_user(user_id) ON DELETE SET NULL;

-- FK CONSTRAINT: organization_invitation organization_invitation_organization_id_fkey

ALTER TABLE ONLY public.organization_invitation
    ADD CONSTRAINT organization_invitation_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organization(organization_id) ON DELETE CASCADE;

-- FK CONSTRAINT: organization_invitation organization_invitation_revoked_by_fkey

ALTER TABLE ONLY public.organization_invitation
    ADD CONSTRAINT organization_invitation_revoked_by_fkey FOREIGN KEY (revoked_by) REFERENCES public.app_user(user_id) ON DELETE SET NULL;

-- FK CONSTRAINT: organization organization_reviewed_by_fkey

ALTER TABLE ONLY public.organization
    ADD CONSTRAINT organization_reviewed_by_fkey FOREIGN KEY (reviewed_by) REFERENCES public.app_user(user_id);

-- FK CONSTRAINT: password_reset password_reset_user_id_fkey

ALTER TABLE ONLY public.password_reset
    ADD CONSTRAINT password_reset_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(user_id) ON DELETE CASCADE;

-- FK CONSTRAINT: phone_verification phone_verification_user_id_fkey

ALTER TABLE ONLY public.phone_verification
    ADD CONSTRAINT phone_verification_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(user_id) ON DELETE CASCADE;

-- FK CONSTRAINT: procurement_request procurement_request_conversation_id_fkey

ALTER TABLE ONLY public.procurement_request
    ADD CONSTRAINT procurement_request_conversation_id_fkey FOREIGN KEY (conversation_id) REFERENCES public.conversation(conversation_id);

-- FK CONSTRAINT: procurement_request procurement_request_created_by_fkey

ALTER TABLE ONLY public.procurement_request
    ADD CONSTRAINT procurement_request_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.app_user(user_id) ON DELETE SET NULL;

-- FK CONSTRAINT: procurement_request_item procurement_request_item_procurement_request_id_fkey

ALTER TABLE ONLY public.procurement_request_item
    ADD CONSTRAINT procurement_request_item_procurement_request_id_fkey FOREIGN KEY (procurement_request_id) REFERENCES public.procurement_request(procurement_request_id) ON DELETE CASCADE;

-- FK CONSTRAINT: procurement_request_item procurement_request_item_product_id_fkey

ALTER TABLE ONLY public.procurement_request_item
    ADD CONSTRAINT procurement_request_item_product_id_fkey FOREIGN KEY (product_id) REFERENCES public.product(product_id);

-- FK CONSTRAINT: procurement_request procurement_request_pharmacy_location_id_pharmacy_organiza_fkey

ALTER TABLE ONLY public.procurement_request
    ADD CONSTRAINT procurement_request_pharmacy_location_id_pharmacy_organiza_fkey FOREIGN KEY (pharmacy_location_id, pharmacy_organization_id) REFERENCES public.location(location_id, organization_id);

-- FK CONSTRAINT: procurement_request procurement_request_pharmacy_organization_id_pharmacy_org__fkey

ALTER TABLE ONLY public.procurement_request
    ADD CONSTRAINT procurement_request_pharmacy_organization_id_pharmacy_org__fkey FOREIGN KEY (pharmacy_organization_id, pharmacy_org_type) REFERENCES public.organization(organization_id, type);

-- FK CONSTRAINT: procurement_request procurement_request_supplier_organization_id_supplier_org__fkey

ALTER TABLE ONLY public.procurement_request
    ADD CONSTRAINT procurement_request_supplier_organization_id_supplier_org__fkey FOREIGN KEY (supplier_organization_id, supplier_org_type) REFERENCES public.organization(organization_id, type);

-- FK CONSTRAINT: product product_drug_id_fkey

ALTER TABLE ONLY public.product
    ADD CONSTRAINT product_drug_id_fkey FOREIGN KEY (drug_id) REFERENCES public.drug(drug_id);

-- FK CONSTRAINT: product_offer product_offer_location_id_product_id_fkey

ALTER TABLE ONLY public.product_offer
    ADD CONSTRAINT product_offer_location_id_product_id_fkey FOREIGN KEY (location_id, product_id) REFERENCES public.stock(location_id, product_id) ON DELETE CASCADE;

-- FK CONSTRAINT: product_offer product_offer_updated_by_fkey

ALTER TABLE ONLY public.product_offer
    ADD CONSTRAINT product_offer_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES public.app_user(user_id);

-- FK CONSTRAINT: product_reservation_history product_reservation_history_changed_by_fkey

ALTER TABLE ONLY public.product_reservation_history
    ADD CONSTRAINT product_reservation_history_changed_by_fkey FOREIGN KEY (changed_by) REFERENCES public.app_user(user_id);

-- FK CONSTRAINT: product_reservation_history product_reservation_history_product_id_fkey

ALTER TABLE ONLY public.product_reservation_history
    ADD CONSTRAINT product_reservation_history_product_id_fkey FOREIGN KEY (product_id) REFERENCES public.product(product_id);

-- FK CONSTRAINT: purchase_order purchase_order_created_by_fkey

ALTER TABLE ONLY public.purchase_order
    ADD CONSTRAINT purchase_order_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.app_user(user_id);

-- FK CONSTRAINT: purchase_order_item purchase_order_item_product_id_fkey

ALTER TABLE ONLY public.purchase_order_item
    ADD CONSTRAINT purchase_order_item_product_id_fkey FOREIGN KEY (product_id) REFERENCES public.product(product_id);

-- FK CONSTRAINT: purchase_order_item purchase_order_item_purchase_order_id_fkey

ALTER TABLE ONLY public.purchase_order_item
    ADD CONSTRAINT purchase_order_item_purchase_order_id_fkey FOREIGN KEY (purchase_order_id) REFERENCES public.purchase_order(purchase_order_id) ON DELETE CASCADE;

-- FK CONSTRAINT: purchase_order purchase_order_pharmacy_location_id_pharmacy_organization__fkey

ALTER TABLE ONLY public.purchase_order
    ADD CONSTRAINT purchase_order_pharmacy_location_id_pharmacy_organization__fkey FOREIGN KEY (pharmacy_location_id, pharmacy_organization_id) REFERENCES public.location(location_id, organization_id);

-- FK CONSTRAINT: purchase_order purchase_order_pharmacy_organization_id_pharmacy_org_type_fkey

ALTER TABLE ONLY public.purchase_order
    ADD CONSTRAINT purchase_order_pharmacy_organization_id_pharmacy_org_type_fkey FOREIGN KEY (pharmacy_organization_id, pharmacy_org_type) REFERENCES public.organization(organization_id, type);

-- FK CONSTRAINT: purchase_order purchase_order_procurement_request_id_fkey

ALTER TABLE ONLY public.purchase_order
    ADD CONSTRAINT purchase_order_procurement_request_id_fkey FOREIGN KEY (procurement_request_id) REFERENCES public.procurement_request(procurement_request_id);

-- FK CONSTRAINT: purchase_order purchase_order_quotation_id_fkey

ALTER TABLE ONLY public.purchase_order
    ADD CONSTRAINT purchase_order_quotation_id_fkey FOREIGN KEY (quotation_id) REFERENCES public.quotation(quotation_id);

-- FK CONSTRAINT: purchase_order purchase_order_responded_by_fkey

ALTER TABLE ONLY public.purchase_order
    ADD CONSTRAINT purchase_order_responded_by_fkey FOREIGN KEY (responded_by) REFERENCES public.app_user(user_id);

-- FK CONSTRAINT: purchase_order purchase_order_status_changed_by_fkey

ALTER TABLE ONLY public.purchase_order
    ADD CONSTRAINT purchase_order_status_changed_by_fkey FOREIGN KEY (status_changed_by) REFERENCES public.app_user(user_id);

-- FK CONSTRAINT: purchase_order_status_history purchase_order_status_history_changed_by_fkey

ALTER TABLE ONLY public.purchase_order_status_history
    ADD CONSTRAINT purchase_order_status_history_changed_by_fkey FOREIGN KEY (changed_by) REFERENCES public.app_user(user_id);

-- FK CONSTRAINT: purchase_order_status_history purchase_order_status_history_purchase_order_id_fkey

ALTER TABLE ONLY public.purchase_order_status_history
    ADD CONSTRAINT purchase_order_status_history_purchase_order_id_fkey FOREIGN KEY (purchase_order_id) REFERENCES public.purchase_order(purchase_order_id) ON DELETE CASCADE;

-- FK CONSTRAINT: purchase_order purchase_order_supplier_location_id_supplier_organization__fkey

ALTER TABLE ONLY public.purchase_order
    ADD CONSTRAINT purchase_order_supplier_location_id_supplier_organization__fkey FOREIGN KEY (supplier_location_id, supplier_organization_id) REFERENCES public.location(location_id, organization_id);

-- FK CONSTRAINT: purchase_order purchase_order_supplier_organization_id_supplier_org_type_fkey

ALTER TABLE ONLY public.purchase_order
    ADD CONSTRAINT purchase_order_supplier_organization_id_supplier_org_type_fkey FOREIGN KEY (supplier_organization_id, supplier_org_type) REFERENCES public.organization(organization_id, type);

-- FK CONSTRAINT: quotation quotation_created_by_fkey

ALTER TABLE ONLY public.quotation
    ADD CONSTRAINT quotation_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.app_user(user_id) ON DELETE SET NULL;

-- FK CONSTRAINT: quotation_item quotation_item_procurement_request_item_id_fkey

ALTER TABLE ONLY public.quotation_item
    ADD CONSTRAINT quotation_item_procurement_request_item_id_fkey FOREIGN KEY (procurement_request_item_id) REFERENCES public.procurement_request_item(procurement_request_item_id);

-- FK CONSTRAINT: quotation_item quotation_item_quotation_id_fkey

ALTER TABLE ONLY public.quotation_item
    ADD CONSTRAINT quotation_item_quotation_id_fkey FOREIGN KEY (quotation_id) REFERENCES public.quotation(quotation_id) ON DELETE CASCADE;

-- FK CONSTRAINT: quotation quotation_procurement_request_id_fkey

ALTER TABLE ONLY public.quotation
    ADD CONSTRAINT quotation_procurement_request_id_fkey FOREIGN KEY (procurement_request_id) REFERENCES public.procurement_request(procurement_request_id) ON DELETE CASCADE;

-- FK CONSTRAINT: quotation quotation_responded_by_fkey

ALTER TABLE ONLY public.quotation
    ADD CONSTRAINT quotation_responded_by_fkey FOREIGN KEY (responded_by) REFERENCES public.app_user(user_id) ON DELETE SET NULL;

-- FK CONSTRAINT: quotation quotation_submitted_by_fkey

ALTER TABLE ONLY public.quotation
    ADD CONSTRAINT quotation_submitted_by_fkey FOREIGN KEY (submitted_by) REFERENCES public.app_user(user_id) ON DELETE SET NULL;

-- FK CONSTRAINT: reservation reservation_collected_by_fkey

ALTER TABLE ONLY public.reservation
    ADD CONSTRAINT reservation_collected_by_fkey FOREIGN KEY (collected_by) REFERENCES public.app_user(user_id);

-- FK CONSTRAINT: reservation_collection reservation_collection_collected_by_fkey

ALTER TABLE ONLY public.reservation_collection
    ADD CONSTRAINT reservation_collection_collected_by_fkey FOREIGN KEY (collected_by) REFERENCES public.app_user(user_id);

-- FK CONSTRAINT: reservation_collection reservation_collection_correction_adjustment_id_fkey

ALTER TABLE ONLY public.reservation_collection
    ADD CONSTRAINT reservation_collection_correction_adjustment_id_fkey FOREIGN KEY (correction_adjustment_id) REFERENCES public.stock_adjustment(adjustment_id);

-- FK CONSTRAINT: reservation_collection reservation_collection_deduction_adjustment_id_fkey

ALTER TABLE ONLY public.reservation_collection
    ADD CONSTRAINT reservation_collection_deduction_adjustment_id_fkey FOREIGN KEY (deduction_adjustment_id) REFERENCES public.stock_adjustment(adjustment_id);

-- FK CONSTRAINT: reservation_collection reservation_collection_override_by_fkey

ALTER TABLE ONLY public.reservation_collection
    ADD CONSTRAINT reservation_collection_override_by_fkey FOREIGN KEY (override_by) REFERENCES public.app_user(user_id);

-- FK CONSTRAINT: reservation_collection reservation_collection_reservation_id_fkey

ALTER TABLE ONLY public.reservation_collection
    ADD CONSTRAINT reservation_collection_reservation_id_fkey FOREIGN KEY (reservation_id) REFERENCES public.reservation(reservation_id);

-- FK CONSTRAINT: reservation reservation_location_id_pharmacy_organization_id_fkey

ALTER TABLE ONLY public.reservation
    ADD CONSTRAINT reservation_location_id_pharmacy_organization_id_fkey FOREIGN KEY (location_id, pharmacy_organization_id) REFERENCES public.location(location_id, organization_id);

-- FK CONSTRAINT: reservation reservation_patient_user_id_fkey

ALTER TABLE ONLY public.reservation
    ADD CONSTRAINT reservation_patient_user_id_fkey FOREIGN KEY (patient_user_id) REFERENCES public.app_user(user_id);

-- FK CONSTRAINT: reservation reservation_pharmacy_organization_id_pharmacy_org_type_fkey

ALTER TABLE ONLY public.reservation
    ADD CONSTRAINT reservation_pharmacy_organization_id_pharmacy_org_type_fkey FOREIGN KEY (pharmacy_organization_id, pharmacy_org_type) REFERENCES public.organization(organization_id, type);

-- FK CONSTRAINT: reservation reservation_product_id_fkey

ALTER TABLE ONLY public.reservation
    ADD CONSTRAINT reservation_product_id_fkey FOREIGN KEY (product_id) REFERENCES public.product(product_id);

-- FK CONSTRAINT: reservation reservation_responded_by_fkey

ALTER TABLE ONLY public.reservation
    ADD CONSTRAINT reservation_responded_by_fkey FOREIGN KEY (responded_by) REFERENCES public.app_user(user_id);

-- FK CONSTRAINT: reservation reservation_status_changed_by_fkey

ALTER TABLE ONLY public.reservation
    ADD CONSTRAINT reservation_status_changed_by_fkey FOREIGN KEY (status_changed_by) REFERENCES public.app_user(user_id);

-- FK CONSTRAINT: reservation_status_history reservation_status_history_changed_by_fkey

ALTER TABLE ONLY public.reservation_status_history
    ADD CONSTRAINT reservation_status_history_changed_by_fkey FOREIGN KEY (changed_by) REFERENCES public.app_user(user_id);

-- FK CONSTRAINT: reservation_status_history reservation_status_history_reservation_id_fkey

ALTER TABLE ONLY public.reservation_status_history
    ADD CONSTRAINT reservation_status_history_reservation_id_fkey FOREIGN KEY (reservation_id) REFERENCES public.reservation(reservation_id);

-- FK CONSTRAINT: search_event search_event_drug_id_fkey

ALTER TABLE ONLY public.search_event
    ADD CONSTRAINT search_event_drug_id_fkey FOREIGN KEY (drug_id) REFERENCES public.drug(drug_id) ON DELETE SET NULL;

-- FK CONSTRAINT: search_event search_event_product_id_fkey

ALTER TABLE ONLY public.search_event
    ADD CONSTRAINT search_event_product_id_fkey FOREIGN KEY (product_id) REFERENCES public.product(product_id) ON DELETE SET NULL;

-- FK CONSTRAINT: stock_adjustment stock_adjustment_changed_by_fkey

ALTER TABLE ONLY public.stock_adjustment
    ADD CONSTRAINT stock_adjustment_changed_by_fkey FOREIGN KEY (changed_by) REFERENCES public.app_user(user_id);

-- FK CONSTRAINT: stock_adjustment stock_adjustment_location_id_fkey

ALTER TABLE ONLY public.stock_adjustment
    ADD CONSTRAINT stock_adjustment_location_id_fkey FOREIGN KEY (location_id) REFERENCES public.location(location_id) ON DELETE CASCADE;

-- FK CONSTRAINT: stock_adjustment stock_adjustment_product_id_fkey

ALTER TABLE ONLY public.stock_adjustment
    ADD CONSTRAINT stock_adjustment_product_id_fkey FOREIGN KEY (product_id) REFERENCES public.product(product_id);

-- FK CONSTRAINT: stock stock_location_id_fkey

ALTER TABLE ONLY public.stock
    ADD CONSTRAINT stock_location_id_fkey FOREIGN KEY (location_id) REFERENCES public.location(location_id) ON DELETE CASCADE;

-- FK CONSTRAINT: stock stock_product_id_fkey

ALTER TABLE ONLY public.stock
    ADD CONSTRAINT stock_product_id_fkey FOREIGN KEY (product_id) REFERENCES public.product(product_id);

-- FK CONSTRAINT: stock stock_updated_by_fkey

ALTER TABLE ONLY public.stock
    ADD CONSTRAINT stock_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES public.app_user(user_id);

--
--

-- -----------------------------------------------------------------------------
-- Alembic bookkeeping: this database is at revision d5f1b8c3a7e2.
-- -----------------------------------------------------------------------------
CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL,
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);
INSERT INTO public.alembic_version (version_num) VALUES ('d5f1b8c3a7e2');

COMMIT;
