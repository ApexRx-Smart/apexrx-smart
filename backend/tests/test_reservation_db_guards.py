"""Database safeguards of migrations c8e5a1f7d2b9 and d4a7e2c9b1f8, exercised
with direct SQL (an application-level bypass): collection records (T1-T11),
product unit rules (T12-T15), the branch minimum stock and stock held from the
request, forged system actions, and a restricted application role that cannot
switch the safeguards off."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.database import engine
from tests.reservation_support import HeldSQL, ResWorld, backdate, rows, scalar

RESTRICTED_ROLE = "apexrx_app_restricted_test"


def collect_sql(tx, reservation_id, **override):
    if override:
        tx.execute(
            "INSERT INTO reservation_collection (reservation_id, override, verified_on_hand, "
            "recorded_quantity_seen, override_reason) VALUES (:r, true, :v, :s, :why)",
            r=reservation_id, **override,
        )
    else:
        tx.execute("INSERT INTO reservation_collection (reservation_id) VALUES (:r)", r=reservation_id)


def mark_collected(tx, reservation_id):
    tx.execute(
        "UPDATE reservation SET status = 'collected', status_source = 'pharmacy' WHERE reservation_id = :r",
        r=reservation_id,
    )


def adjustment_count():
    return scalar("SELECT count(*) FROM stock_adjustment")


def insert_reservation_sql(tx, w, *, patient=None, product=None, quantity=1, status="requested", source="patient"):
    return tx.execute(
        "INSERT INTO reservation (reference, patient_user_id, pharmacy_organization_id, location_id, product_id, "
        "quantity, contact_phone, client_request_id, status, status_source) VALUES "
        "('RX-' || substr(translate(upper(md5(random()::text)), '01IOL', '23456'), 1, 10), :p, :o, :l, :pr, :q, "
        "'+250788123456', gen_random_uuid(), :st, :src) RETURNING reservation_id",
        p=patient or w.patient, o=w.org, l=w.branch, pr=product or w.product, q=quantity, st=status, src=source,
    ).scalar()


def expect_db_error(match, fn, *args, **kwargs):
    with pytest.raises(DBAPIError, match=match):
        fn(*args, **kwargs)


# ---------------------------------------------------------------------------
# Collection records
# ---------------------------------------------------------------------------
def test_t1_valid_collection_in_one_transaction(client):
    w = ResWorld(client)
    r = w.confirmed(quantity=2)
    tx = HeldSQL(w.staff)
    collect_sql(tx, r.reservation_id)
    xid = tx.execute("SELECT pg_current_xact_id()::text").scalar()
    mark_collected(tx, r.reservation_id)
    tx.commit()
    record = rows(
        "SELECT collected_xid::text, collected_by, quantity, recorded_quantity_before, quantity_after, "
        "deduction_adjustment_id FROM reservation_collection WHERE reservation_id = :r", r=r.reservation_id,
    )[0]
    assert record[:5] == (xid, w.staff, 2, 10, 8)
    adj = rows("SELECT location_id, product_id, old_quantity, new_quantity, changed_by FROM stock_adjustment "
               "WHERE adjustment_id = :a", a=record[5])[0]
    assert adj == (w.branch, w.product, 10, 8, w.staff)
    assert w.status(r.reservation_id) == "collected" and w.stock_quantity() == 8
    assert scalar("SELECT count(*) FROM reservation_status_history WHERE reservation_id = :r AND to_status = 'collected' "
                  "AND changed_by = :s", r=r.reservation_id, s=w.staff) == 1


def test_t2_record_without_status_change_is_rolled_back_at_commit(client):
    w = ResWorld(client)
    r = w.confirmed(quantity=2)
    before = adjustment_count()
    tx = HeldSQL(w.staff)
    collect_sql(tx, r.reservation_id)
    expect_db_error("must be completed by marking the reservation collected", tx.commit)
    assert scalar("SELECT count(*) FROM reservation_collection") == 0
    assert (w.stock_quantity(), adjustment_count(), w.status(r.reservation_id)) == (10, before, "confirmed")


def test_t3_a_record_from_an_earlier_transaction_cannot_authorise_collection(client):
    w = ResWorld(client)
    r = w.confirmed(quantity=2)
    # Create the impossible state (a committed record for a confirmed
    # reservation) by switching off the commit-time check: only the owner of
    # the table can do that (see test_restricted_role_cannot_disable_safeguards).
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE reservation_collection DISABLE TRIGGER trg_reservation_collection_commit_check"))
    try:
        tx = HeldSQL(w.staff)
        collect_sql(tx, r.reservation_id)
        tx.commit()
    finally:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE reservation_collection ENABLE TRIGGER trg_reservation_collection_commit_check"))
    tx = HeldSQL(w.staff)
    expect_db_error("same transaction by the same person", mark_collected, tx, r.reservation_id)
    tx.rollback()
    assert w.status(r.reservation_id) == "confirmed"


def test_t4_unauthorised_actors_cannot_record_a_collection(client):
    w = ResWorld(client)
    r = w.confirmed(quantity=2)
    for actor, message in ((w.outsider, "only members of this pharmacy"), (w.patient, "only members of this pharmacy")):
        tx = HeldSQL(actor)
        expect_db_error(message, collect_sql, tx, r.reservation_id)
        tx.rollback()
    tx = HeldSQL(w.staff)
    expect_db_error("only owners and managers can override", collect_sql, tx, r.reservation_id,
                    v=12, s=10, why="Counted the shelf twice")
    tx.rollback()
    tx = HeldSQL(None)
    expect_db_error("app.user_id is not set", collect_sql, tx, r.reservation_id)
    tx.rollback()


def test_t5_records_and_histories_are_immutable(client):
    w = ResWorld(client)
    r = w.confirmed(quantity=2)
    w.collect(r)
    for sql in (
        "UPDATE reservation_collection SET quantity_after = 99",
        "DELETE FROM reservation_collection",
        "DELETE FROM reservation",
        "UPDATE reservation_status_history SET reason = 'x'",
        "DELETE FROM reservation_status_history",
        "UPDATE product_reservation_history SET unit_label = 'tablet'",
    ):
        tx = HeldSQL(w.owner)
        expect_db_error("cannot be changed or deleted", tx.execute, sql)
        tx.rollback()


def test_t6_rollback_before_the_status_change_leaves_nothing(client):
    w = ResWorld(client)
    r = w.confirmed(quantity=2)
    before = adjustment_count()
    tx = HeldSQL(w.staff)
    collect_sql(tx, r.reservation_id)
    tx.rollback()
    assert (w.stock_quantity(), adjustment_count(), w.status(r.reservation_id)) == (10, before, "confirmed")
    assert scalar("SELECT count(*) FROM reservation_collection") == 0
    assert w.collect(r).reservation.status == "collected"


def test_t7_the_status_change_must_be_by_the_same_person(client):
    w = ResWorld(client)
    r = w.confirmed(quantity=2)
    tx = HeldSQL(w.staff)
    collect_sql(tx, r.reservation_id)
    tx.execute("SELECT set_config('app.user_id', :u, true)", u=str(w.manager))
    expect_db_error("same transaction by the same person", mark_collected, tx, r.reservation_id)
    tx.rollback()


def test_t8_client_supplied_transaction_id_is_ignored(client):
    w = ResWorld(client)
    r = w.confirmed(quantity=2)
    tx = HeldSQL(w.staff)
    tx.execute("INSERT INTO reservation_collection (reservation_id, collected_xid, collected_by, quantity, "
               "recorded_quantity_before, quantity_after, deduction_adjustment_id) "
               "VALUES (:r, '1', :o, 99, 99, 99, 1)", r=r.reservation_id, o=w.owner)
    xid = tx.execute("SELECT pg_current_xact_id()::text").scalar()
    mark_collected(tx, r.reservation_id)
    tx.commit()
    assert rows("SELECT collected_xid::text, collected_by, quantity, quantity_after FROM reservation_collection") == [
        (xid, w.staff, 2, 8)]


def test_t9_immediate_constraint_mode_fails_closed(client):
    w = ResWorld(client)
    r = w.confirmed(quantity=2)
    tx = HeldSQL(w.staff)
    tx.execute("SET CONSTRAINTS ALL IMMEDIATE")
    expect_db_error("must be completed", collect_sql, tx, r.reservation_id)
    tx.rollback()
    assert w.stock_quantity() == 10


def test_t10_savepoints_keep_the_top_level_transaction(client):
    w = ResWorld(client)
    r = w.confirmed(quantity=2)
    tx = HeldSQL(w.staff)
    tx.execute("SAVEPOINT s1")
    collect_sql(tx, r.reservation_id)
    tx.execute("RELEASE SAVEPOINT s1")
    mark_collected(tx, r.reservation_id)
    tx.commit()
    assert w.status(r.reservation_id) == "collected" and w.stock_quantity() == 8


def test_t11_one_record_per_reservation(client):
    w = ResWorld(client)
    r = w.confirmed(quantity=2)
    tx = HeldSQL(w.staff)
    collect_sql(tx, r.reservation_id)
    expect_db_error("reservation_collection_pkey", collect_sql, tx, r.reservation_id)
    tx.rollback()
    assert w.stock_quantity() == 10
    w.collect(r)
    tx = HeldSQL(w.staff)
    expect_db_error("only a confirmed reservation", collect_sql, tx, r.reservation_id)
    tx.rollback()
    assert w.stock_quantity() == 8


# ---------------------------------------------------------------------------
# Product units and reservability
# ---------------------------------------------------------------------------
def product_update(w, product, sql, **params):
    tx = HeldSQL(w.admin)
    tx.execute(f"UPDATE product SET {sql} WHERE product_id = :p", p=product, **params)
    tx.commit()


def test_t12_unit_label_rules(client):
    w = ResWorld(client)
    product = w.medicine("Ibuprofen", "Brufen 200mg", classify=False)
    for label in ("", " tablet", "tablet ", "n/a", "NA", "---", "20", "x"):
        expect_db_error("product_unit_label_check", product_update, w, product,
                        "stock_unit = 'unit', unit_label = :l", l=label)
    for label in ("tablet", "vial", "bottle", "box of 20"):
        product_update(w, product, "stock_unit = 'unit', unit_label = :l", l=label)
    expect_db_error("product_unit_label_check", product_update, w, product, "stock_unit = 'pack', unit_label = NULL")
    # A pack must describe its contents before it can be reserved.
    product_update(w, product, "pack_size = NULL, stock_unit = 'pack', unit_label = 'box', "
                               "dispensing_class = 'non_prescription'")
    tx = HeldSQL(w.patient)
    expect_db_error(r"\(pack_size_missing\)", insert_reservation_sql, tx, w, product=product)
    tx.rollback()
    product_update(w, product, "pack_size = '20 tablets'")
    tx = HeldSQL(w.patient)
    insert_reservation_sql(tx, w, product=product)
    tx.commit()


def test_t13_reclassified_products(client):
    w = ResWorld(client)
    confirmed = w.confirmed(quantity=2)
    to_cancel = w.confirmed(quantity=1, patient=w.patient2)
    pending = w.submit(patient=w.outsider, quantity=1)
    product_update(w, w.product, "dispensing_class = 'prescription_only'")
    tx = HeldSQL(w.patient2)
    expect_db_error(r"\(prescription_only\)", insert_reservation_sql, tx, w, patient=w.patient2, quantity=1)
    tx.rollback()
    tx = HeldSQL(w.staff)
    expect_db_error(r"cannot be confirmed \(prescription_only\)", tx.execute,
                    "UPDATE reservation SET status = 'confirmed', status_source = 'pharmacy' WHERE reservation_id = :r",
                    r=pending.reservation_id)
    tx.rollback()
    # Confirmed reservations stay collectable, cancellable and expirable.
    tx = HeldSQL(w.staff)
    collect_sql(tx, confirmed.reservation_id)
    mark_collected(tx, confirmed.reservation_id)
    tx.commit()
    tx = HeldSQL(w.manager)
    tx.execute("UPDATE reservation SET status = 'cancelled', status_source = 'pharmacy', cancel_reason = 'Recall' "
               "WHERE reservation_id = :r", r=to_cancel.reservation_id)
    tx.commit()
    backdate(pending.reservation_id)
    tx = HeldSQL(None)
    tx.execute("UPDATE reservation SET status = 'expired', status_source = 'system' WHERE reservation_id = :r",
               r=pending.reservation_id)
    tx.commit()
    assert [w.status(r.reservation_id) for r in (confirmed, to_cancel, pending)] == ["collected", "cancelled", "expired"]


def test_t14_the_retired_switch_and_acknowledgements_are_not_required(client):
    w = ResWorld(client)
    product_update(w, w.product, "reservation_enabled = false")
    assert scalar("SELECT count(*) FROM offer_unit_acknowledgement") == 0
    assert scalar("SELECT reservation_ineligibility(:l, :p)", l=w.branch, p=w.product) is None
    tx = HeldSQL(w.patient)
    insert_reservation_sql(tx, w)
    tx.commit()
    # The old CHECK on the retired column still refuses an inconsistent "true".
    expect_db_error("product_reservation_enabled_check", product_update, w, w.product,
                    "dispensing_class = 'unclassified', reservation_enabled = true")


def test_t15_unit_changes(client):
    w = ResWorld(client)
    version = scalar("SELECT unit_version FROM product WHERE product_id = :p", p=w.product)
    # A unit change with an open reservation is refused by the product trigger.
    r = w.submit()
    expect_db_error("open reservations", product_update, w, w.product, "unit_label = 'carton'")
    expect_db_error("open reservations", product_update, w, w.product, "pack_size = '30 tablets'")
    w.collect(w.confirm(r.reservation_id))
    # Without open reservations the change is accepted and bumps the version;
    # new requests quote the new unit, with nothing to acknowledge.
    product_update(w, w.product, "pack_size = '30 tablets'")
    assert scalar("SELECT unit_version FROM product WHERE product_id = :p", p=w.product) == version + 1
    tx = HeldSQL(w.patient2)
    reservation_id = insert_reservation_sql(tx, w, patient=w.patient2)
    tx.commit()
    assert rows("SELECT pack_size, unit_version FROM reservation WHERE reservation_id = :r", r=reservation_id) == [
        ("30 tablets", version + 1)]


def test_direct_confirmation_rechecks_the_unit(client):
    w = ResWorld(client)
    r = w.submit()
    # Force an inconsistent catalogue state that the application cannot
    # produce (the unit changed under an open request).
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL session_replication_role = replica"))
        conn.execute(text("UPDATE product SET unit_version = unit_version + 1 WHERE product_id = :p"), {"p": w.product})
    tx = HeldSQL(w.staff)
    expect_db_error("the stock unit of this product changed after the request", tx.execute,
                    "UPDATE reservation SET status = 'confirmed', status_source = 'pharmacy' WHERE reservation_id = :r",
                    r=r.reservation_id)
    tx.rollback()


# ---------------------------------------------------------------------------
# Branch minimum stock and stock held from the request (d4a7e2c9b1f8)
# ---------------------------------------------------------------------------
def test_direct_inserts_respect_the_branch_minimum_and_what_is_held(client):
    w = ResWorld(client)  # 10 recorded
    w.set_min_stock(6)  # 4 reservable
    tx = HeldSQL(w.patient)
    expect_db_error("not enough stock available for reservation", insert_reservation_sql, tx, w, quantity=5)
    tx.rollback()
    tx = HeldSQL(w.patient)
    insert_reservation_sql(tx, w, quantity=4)  # exactly what is reservable
    tx.commit()
    tx = HeldSQL(w.patient2)
    expect_db_error("not enough stock available for reservation", insert_reservation_sql, tx, w,
                    patient=w.patient2, quantity=1)
    tx.rollback()
    assert scalar("SELECT reservation_allocated(:l, :p, NULL)", l=w.branch, p=w.product) == 4
    # The other branch has its own minimum (0) and no stock record here.
    assert scalar("SELECT reservation_min_stock FROM location WHERE location_id = :l", l=w.branch2) == 0


def test_branch_minimum_is_checked_by_the_database(client):
    w = ResWorld(client)
    for bad in (-1, 1_000_001):
        tx = HeldSQL(w.owner)
        expect_db_error("location_reservation_min_stock_check", tx.execute,
                        "UPDATE location SET reservation_min_stock = :v WHERE location_id = :l", v=bad, l=w.branch)
        tx.rollback()
    with engine.begin() as conn:
        assert conn.execute(text(
            "SELECT column_default, is_nullable FROM information_schema.columns "
            "WHERE table_name = 'location' AND column_name = 'reservation_min_stock'")).one() == ("0", "NO")


def test_direct_confirmation_cannot_exceed_the_stock_after_other_holds(client):
    w = ResWorld(client)
    a = w.submit(quantity=5)
    b = w.submit(patient=w.patient2, quantity=5)
    w.set_stock(w.product, 8)
    tx = HeldSQL(w.staff)
    expect_db_error("not enough unreserved stock to confirm", tx.execute,
                    "UPDATE reservation SET status = 'confirmed', status_source = 'pharmacy' WHERE reservation_id = :r",
                    r=a.reservation_id)
    tx.rollback()
    w.set_min_stock(5)  # the minimum applies to new requests only, never to confirmation
    run_decline = HeldSQL(w.staff)
    run_decline.execute("UPDATE reservation SET status = 'declined', status_source = 'pharmacy', "
                        "decline_reason = 'Short' WHERE reservation_id = :r", r=b.reservation_id)
    run_decline.commit()
    tx = HeldSQL(w.staff)
    tx.execute("UPDATE reservation SET status = 'confirmed', status_source = 'pharmacy' WHERE reservation_id = :r",
               r=a.reservation_id)
    tx.commit()
    assert w.status(a.reservation_id) == "confirmed"


# ---------------------------------------------------------------------------
# Transitions, actors and system actions cannot be forged
# ---------------------------------------------------------------------------
def update_sql(actor, reservation_id, sql):
    tx = HeldSQL(actor)
    try:
        tx.execute(f"UPDATE reservation SET {sql} WHERE reservation_id = :r", r=reservation_id)
    except BaseException:
        tx.rollback()
        raise
    tx.commit()


def test_forged_and_invalid_transitions_are_refused(client):
    w = ResWorld(client)
    r = w.submit()
    rid = r.reservation_id
    cases = [
        (w.staff, "status = 'cancelled', status_source = 'system'", "only possible when the pharmacy is suspended"),
        (w.staff, "status = 'expired', status_source = 'system'", "cannot be made as a system action"),
        (None, "status = 'expired', status_source = 'system'", "cannot be made as a system action"),
        (w.staff, "status = 'expired', status_source = 'pharmacy'", "only the system can expire"),
        (w.outsider, "status = 'confirmed', status_source = 'pharmacy'", "only members of this pharmacy"),
        (w.staff, "status = 'cancelled', status_source = 'patient'", "only the patient can act as the patient"),
        (w.patient, "status = 'confirmed', status_source = 'patient'", "a patient can only cancel"),
        (w.patient, "status = 'confirmed', status_source = 'pharmacy'", "only members of this pharmacy"),
        (w.staff, "quantity = 1", "cannot change"),
        (w.staff, "status_changed_by = status_changed_by", "only changes through a status transition"),
        (w.staff, "status = 'collected', status_source = 'pharmacy'", "cannot go from requested to collected"),
        (w.staff, "status = 'declined', status_source = 'pharmacy'", "a reason is required"),
        (None, "status = 'confirmed', status_source = 'pharmacy'", "app.user_id is not set"),
    ]
    for actor, sql, message in cases:
        expect_db_error(message, update_sql, actor, rid, sql)
    assert w.status(rid) == "requested"
    # The actor is stamped by the database, not taken from the statement.
    update_sql(w.staff, rid, f"status = 'confirmed', status_source = 'pharmacy', status_changed_by = {w.owner}, "
                             "expires_at = now() + interval '30 days', responded_by = 1")
    row = rows("SELECT status_changed_by, responded_by, expires_at - confirmed_at FROM reservation "
               "WHERE reservation_id = :r", r=rid)[0]
    assert (row[0], row[1], str(row[2])) == (w.staff, w.staff, "1 day, 0:00:00")
    expect_db_error("only owners and managers can cancel", update_sql, w.staff, rid,
                    "status = 'cancelled', status_source = 'pharmacy', cancel_reason = 'x'")


def test_direct_inserts_are_checked(client):
    w = ResWorld(client)
    for actor, kwargs, message in (
        (w.patient, dict(status="confirmed"), "starts as a request by the patient"),
        (w.patient, dict(source="system"), "starts as a request by the patient"),
        (w.patient2, dict(patient=w.patient), "only be requested by the patient themselves"),
        (w.staff, dict(patient=w.staff), "members of a pharmacy cannot reserve"),
        (w.patient, dict(quantity=6), "at most 5 can be reserved"),
        (None, dict(), "app.user_id is not set"),
    ):
        tx = HeldSQL(actor)
        expect_db_error(message, insert_reservation_sql, tx, w, **kwargs)
        tx.rollback()


def test_system_cancellation_needs_a_real_suspension(client):
    w = ResWorld(client)
    r = w.confirmed(quantity=1)
    expect_db_error("only possible when the pharmacy is suspended", update_sql, None, r.reservation_id,
                    "status = 'cancelled', status_source = 'system'")
    tx = HeldSQL(w.admin)
    tx.execute("UPDATE organization SET status = 'suspended', reviewed_at = now() WHERE organization_id = :o", o=w.org)
    tx.execute("UPDATE reservation SET status = 'cancelled', status_source = 'system' WHERE reservation_id = :r",
               r=r.reservation_id)
    tx.commit()
    assert rows("SELECT status_reason, cancelled_by_role, status_changed_by FROM reservation WHERE reservation_id = :r",
                r=r.reservation_id) == [("pharmacy_suspended", "system", None)]


# ---------------------------------------------------------------------------
# The application role cannot switch the safeguards off
# ---------------------------------------------------------------------------
@pytest.fixture
def restricted_role():
    with engine.begin() as conn:
        conn.execute(text(
            f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{RESTRICTED_ROLE}') "
            f"THEN CREATE ROLE {RESTRICTED_ROLE} NOLOGIN NOSUPERUSER; END IF; END $$"
        ))
        conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {RESTRICTED_ROLE}"))
        conn.execute(text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {RESTRICTED_ROLE}"))
        conn.execute(text(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {RESTRICTED_ROLE}"))
    yield RESTRICTED_ROLE
    with engine.begin() as conn:
        conn.execute(text(f"DROP OWNED BY {RESTRICTED_ROLE}"))
        conn.execute(text(f"DROP ROLE {RESTRICTED_ROLE}"))


def test_restricted_role_cannot_disable_safeguards(client, restricted_role):
    w = ResWorld(client)
    r = w.confirmed(quantity=2)
    for sql, message in (
        ("ALTER TABLE reservation_collection DISABLE TRIGGER trg_reservation_collection_commit_check", "must be owner"),
        ("ALTER TABLE reservation DISABLE TRIGGER ALL", "must be owner"),
        ("SET session_replication_role = replica", "permission denied"),
        ("TRUNCATE reservation_collection", "permission denied"),
        ("DROP TRIGGER trg_reservation_before_update ON reservation", "must be owner"),
    ):
        tx = HeldSQL(w.staff)
        tx.execute(f"SET LOCAL ROLE {restricted_role}")
        expect_db_error(message, tx.execute, sql)
        tx.rollback()
    # Under that role the triggers still apply and a proper collection works.
    tx = HeldSQL(w.staff)
    tx.execute(f"SET LOCAL ROLE {restricted_role}")
    collect_sql(tx, r.reservation_id)
    expect_db_error("must be completed", tx.commit)
    tx = HeldSQL(w.staff)
    tx.execute(f"SET LOCAL ROLE {restricted_role}")
    collect_sql(tx, r.reservation_id)
    mark_collected(tx, r.reservation_id)
    tx.commit()
    assert w.status(r.reservation_id) == "collected"
