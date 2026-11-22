"""Concurrency of the reservation engine, with genuinely separate database
sessions and transactions.

Most races are made deterministic: the first operation runs without its commit
(so it keeps its locks), the second starts in another thread, the test waits
until PostgreSQL shows it waiting for a lock (pg_stat_activity), then the first
commits. Both orders are tested where the outcome differs. The deadlock
scenarios (12-15) reproduce the exact interleaving that deadlocks with the
wrong lock modes; PostgreSQL would abort one side (SQLSTATE 40P01) and the
test would fail.

Numbering follows the Phase 0.6/0.7 concurrency matrix (21: trigger
enforcement, in test_reservation_db_guards.py).
"""

import threading
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.api import admin as admin_api
from app.api import inventory as inventory_api
from app.api import organizations as organizations_api
from app.core.errors import AppError
from app.models import Organization, Reservation, User
from app.models.enums import OrganizationStatus
from app.schemas.admin import OrganizationDecision, OrganizationReview
from app.schemas.inventory import StockUpsert
from app.schemas.organizations import LocationUpdate
from app.services import reservations
from app.services.reservations import CollectionOverride
from tests.helpers import stock as put_stock
from tests.reservation_support import (
    PHONE,
    Held,
    HeldSQL,
    ResWorld,
    backdate,
    in_background,
    outcome,
    rows,
    run,
    scalar,
    session,
    wait_blocked,
)


def api_call(user_id_, fn, *args):
    """Call an API route function directly, in its own session, as the user."""
    db = session(user_id_)
    try:
        return "ok", fn(*args, db.get(User, user_id_), db)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        return "error", exc
    finally:
        db.close()


def result_of(future):
    return future.result(timeout=60)


def error_code(result):
    kind, value = result
    assert kind == "error", f"expected an error, got {value!r}"
    assert isinstance(value, AppError), repr(value)
    return value.extra.get("code"), value.extra.get("reason")


def ok(result):
    kind, value = result
    assert kind == "ok", f"expected success, got {value!r}"
    return value


def submit_args(w, patient=None, quantity=2, product=None, key=None):
    return dict(location_id=w.branch, product_id=product or w.product, quantity=quantity,
                contact_phone=PHONE, client_request_id=key or uuid.uuid4())


def suspend_uncommitted(admin_id, org_id):
    """What the admin review does for a suspension, left uncommitted."""
    db = session(admin_id)
    org = db.scalar(select(Organization).where(Organization.organization_id == org_id)
                    .with_for_update(key_share=True).execution_options(populate_existing=True))
    org.status = OrganizationStatus.SUSPENDED.value
    org.reviewed_at = datetime.now(timezone.utc)
    org.reviewed_by = admin_id
    db.flush()
    reservations.cancel_for_suspension(db, org_id)
    return db


def suspend_via_api(w):
    return api_call(w.admin, admin_api.review_organization, w.org,
                    OrganizationReview(decision=OrganizationDecision.SUSPENDED, notes="Licence review"))


# 1 -------------------------------------------------------------------------
def test_01_two_requests_for_the_last_units(client):
    """Requests hold stock from submission: the second waits for the first's
    stock lock, then finds nothing left to reserve."""
    w = ResWorld(client, quantity=8)
    first = Held(w.patient, reservations.submit, **submit_args(w, quantity=5))
    second = in_background(outcome, w.patient2, reservations.submit, **submit_args(w, quantity=5))
    wait_blocked()
    first.commit()
    assert error_code(result_of(second)) == ("insufficient_stock", "no_reservable_stock")
    assert scalar("SELECT coalesce(sum(quantity), 0) FROM reservation WHERE status = 'requested'") == 5


def test_01b_simultaneous_requests_never_overallocate(client):
    w = ResWorld(client, quantity=8)
    w.set_min_stock(1)  # 7 reservable
    barrier = threading.Barrier(3)

    def go(patient, quantity):
        barrier.wait()
        return outcome(patient, reservations.submit, **submit_args(w, quantity=quantity))

    futures = [in_background(go, p, q) for p, q in ((w.patient, 5), (w.patient2, 5), (w.outsider, 4))]
    results = [result_of(f) for f in futures]
    held = scalar("SELECT coalesce(sum(quantity), 0) FROM reservation WHERE status = 'requested'")
    assert held <= 7 and sum(r[0] == "ok" for r in results) == 1
    assert all(r[0] == "ok" or error_code(r) == ("insufficient_stock", "no_reservable_stock") for r in results)
    assert scalar("SELECT reservation_allocated(:l, :p, NULL)", l=w.branch, p=w.product) == held


def test_01c_two_confirmations_keep_what_their_requests_hold(client):
    w = ResWorld(client, quantity=8)
    a = w.submit(quantity=5)
    b = w.submit(patient=w.patient2, quantity=3)
    first = Held(w.staff, reservations.confirm, w.org, a.reservation_id)
    second = in_background(outcome, w.manager, reservations.confirm, w.org, b.reservation_id)
    wait_blocked()
    first.commit()
    ok(result_of(second))
    assert (w.status(a.reservation_id), w.status(b.reservation_id)) == ("confirmed", "confirmed")
    assert scalar("SELECT sum(quantity) FROM reservation WHERE status = 'confirmed'") == 8


def test_01d_minimum_raised_then_request(client):
    w = ResWorld(client)
    tx = HeldSQL(w.owner)
    tx.execute("UPDATE location SET reservation_min_stock = 9 WHERE location_id = :l", l=w.branch)
    submit = in_background(outcome, w.patient, reservations.submit, **submit_args(w, quantity=2))
    wait_blocked()
    tx.commit()
    assert error_code(result_of(submit)) == ("insufficient_stock", "no_reservable_stock")


def test_01e_request_then_minimum_raised(client):
    w = ResWorld(client)
    submit = Held(w.patient, reservations.submit, **submit_args(w, quantity=2))
    change = in_background(api_call, w.owner, organizations_api.update_location, w.org, w.branch,
                           LocationUpdate(reservation_min_stock=9))
    wait_blocked()
    submit.commit()
    assert ok(result_of(change)).reservation_min_stock == 9
    # The request made before the change stays valid and can be confirmed.
    assert w.confirm(submit.result.reservation.reservation_id).status == "confirmed"
    with pytest.raises(AppError):
        w.submit(patient=w.patient2, quantity=1)


# 2 -------------------------------------------------------------------------
def test_02a_stock_reduction_first_then_confirmation(client):
    w = ResWorld(client)
    r = w.submit(quantity=5)
    reduce = HeldSQL(w.owner)
    reduce.execute("UPDATE stock SET quantity = 3 WHERE location_id = :l AND product_id = :p", l=w.branch, p=w.product)
    confirm = in_background(outcome, w.staff, reservations.confirm, w.org, r.reservation_id)
    wait_blocked()
    reduce.commit()
    assert error_code(result_of(confirm))[0] == "insufficient_stock"
    assert w.status(r.reservation_id) == "requested"


def test_02c_request_first_then_unconfirmed_stock_reduction(client):
    """A stock edit below what open reservations hold waits for the request,
    then is refused unless the pharmacy confirms the count is right."""
    w = ResWorld(client)
    submit = Held(w.patient, reservations.submit, **submit_args(w, quantity=5))
    reduce = in_background(api_call, w.owner, inventory_api.upsert_stock, w.org, w.branch, w.product,
                           StockUpsert(quantity=4))
    wait_blocked()
    submit.commit()
    kind, exc = result_of(reduce)
    assert kind == "error" and exc.extra["code"] == "below_reserved" and exc.extra["held_quantity"] == 5
    assert w.stock_quantity() == 10


def test_02b_confirmation_first_then_stock_reduction(client):
    w = ResWorld(client)
    r = w.submit(quantity=5)
    confirm = Held(w.staff, reservations.confirm, w.org, r.reservation_id)
    reduce = in_background(api_call, w.owner, inventory_api.upsert_stock, w.org, w.branch, w.product,
                           StockUpsert(quantity=2, allow_below_reserved=True))
    wait_blocked()
    confirm.commit()
    ok(result_of(reduce))
    position = run(None, reservations.stock_position, w.branch, w.product)
    assert (position.quantity, position.allocated, position.shortfall) == (2, 5, 3)
    assert position.at_risk_reservation_ids == [r.reservation_id] and w.status(r.reservation_id) == "confirmed"


# 3 and 24 ------------------------------------------------------------------
def test_03_collection_and_expiry_job(client):
    w = ResWorld(client)
    r = w.confirmed(quantity=2)
    collecting = Held(w.staff, reservations.collect, w.org, r.reservation_id, reference=r.reference)
    assert run(None, reservations.expire_due) == []  # skips the locked row, does not wait
    collecting.commit()
    assert w.status(r.reservation_id) == "collected" and w.stock_quantity() == 8


def test_24_deadline_passes_while_collection_waits(client):
    w = ResWorld(client)
    r = w.confirmed(quantity=2)
    holder = HeldSQL(w.admin)
    holder.execute("SELECT 1 FROM organization WHERE organization_id = :o FOR NO KEY UPDATE", o=w.org)
    collecting = in_background(outcome, w.staff, reservations.collect, w.org, r.reservation_id, reference=r.reference)
    wait_blocked()
    backdate(r.reservation_id)  # the deadline passes during the wait
    holder.rollback()
    assert error_code(result_of(collecting))[0] == "expired"
    assert w.status(r.reservation_id) == "expired" and w.stock_quantity() == 10
    assert scalar("SELECT count(*) FROM reservation_collection") == 0


# 4 -------------------------------------------------------------------------
def test_04a_confirmation_then_patient_cancellation(client):
    w = ResWorld(client)
    r = w.submit()
    confirm = Held(w.staff, reservations.confirm, w.org, r.reservation_id)
    cancel = in_background(outcome, w.patient, reservations.cancel_by_patient, r.reservation_id)
    wait_blocked()
    confirm.commit()
    assert ok(result_of(cancel)).reservation.status == "cancelled"
    assert [h[0] for h in rows("SELECT to_status FROM reservation_status_history WHERE reservation_id = :r "
                                "ORDER BY history_id", r=r.reservation_id)] == ["requested", "confirmed", "cancelled"]


def test_04b_patient_cancellation_then_confirmation(client):
    w = ResWorld(client)
    r = w.submit()
    cancel = Held(w.patient, reservations.cancel_by_patient, r.reservation_id)
    confirm = in_background(outcome, w.staff, reservations.confirm, w.org, r.reservation_id)
    wait_blocked()
    cancel.commit()
    assert error_code(result_of(confirm))[0] == "reservation_state_conflict"
    assert w.status(r.reservation_id) == "cancelled"


# 5 -------------------------------------------------------------------------
def test_05_unlisting_and_confirmation(client):
    w = ResWorld(client)
    r = w.submit()
    unlist = HeldSQL(w.owner)
    unlist.execute("UPDATE product_offer SET is_listed = false WHERE location_id = :l AND product_id = :p",
                   l=w.branch, p=w.product)
    # Confirmation reads the committed listing; it does not wait for the unlisting.
    assert ok(outcome(w.staff, reservations.confirm, w.org, r.reservation_id)).reservation.status == "confirmed"
    unlist.commit()
    assert w.collect(run(None, lambda db: db.get(Reservation, r.reservation_id))).reservation.status == "collected"
    # Unlisted first: a new request cannot be confirmed.
    put_stock(client, w.owner_headers, w.org, w.branch, w.product, 10, "500.00")
    r2 = w.submit(patient=w.patient2)
    unlist = HeldSQL(w.owner)
    unlist.execute("UPDATE product_offer SET is_listed = false WHERE location_id = :l AND product_id = :p",
                   l=w.branch, p=w.product)
    unlist.commit()
    assert error_code(outcome(w.staff, reservations.confirm, w.org, r2.reservation_id))[1] == "offer_unlisted"


# 6 and 22 ------------------------------------------------------------------
def test_06a_reclassification_then_submission(client):
    w = ResWorld(client)
    reclassify = Held(w.admin, reservations.configure_product, w.product, dispensing_class="prescription_only")
    submit = in_background(outcome, w.patient, reservations.submit, **submit_args(w))
    wait_blocked()
    reclassify.commit()
    assert error_code(result_of(submit)) == ("not_reservable", "prescription_only")


def test_06b_submission_then_unit_change(client):
    w = ResWorld(client)
    submit = Held(w.patient, reservations.submit, **submit_args(w))
    change = in_background(outcome, w.admin, reservations.configure_product, w.product, unit_label="carton")
    wait_blocked()
    submit.commit()
    assert error_code(result_of(change))[0] == "open_reservations"


def test_22a_reclassification_then_confirmation(client):
    w = ResWorld(client)
    r = w.submit()
    reclassify = Held(w.admin, reservations.configure_product, w.product, dispensing_class="prescription_only")
    confirm = in_background(outcome, w.staff, reservations.confirm, w.org, r.reservation_id)
    wait_blocked()
    reclassify.commit()
    assert error_code(result_of(confirm)) == ("not_reservable", "prescription_only")


def test_22b_confirmation_then_reclassification(client):
    w = ResWorld(client)
    r = w.submit()
    confirm = Held(w.staff, reservations.confirm, w.org, r.reservation_id)
    reclassify = in_background(outcome, w.admin, reservations.configure_product, w.product,
                               dispensing_class="prescription_only")
    wait_blocked()
    confirm.commit()
    ok(result_of(reclassify))
    assert w.collect(confirm.result.reservation).reservation.status == "collected"


# 7 -------------------------------------------------------------------------
def test_07a_suspension_then_submission(client):
    w = ResWorld(client)
    suspension = suspend_uncommitted(w.admin, w.org)
    submit = in_background(outcome, w.patient, reservations.submit, **submit_args(w))
    wait_blocked()
    suspension.commit()
    suspension.close()
    assert error_code(result_of(submit)) == ("not_reservable", "pharmacy_unavailable")
    assert scalar("SELECT count(*) FROM reservation") == 0


def test_07b_submission_then_suspension(client):
    w = ResWorld(client)
    submit = Held(w.patient, reservations.submit, **submit_args(w))
    suspension = in_background(suspend_via_api, w)
    wait_blocked()
    submit.commit()
    ok(result_of(suspension))
    rid = submit.result.reservation.reservation_id
    assert rows("SELECT status, status_reason FROM reservation WHERE reservation_id = :r", r=rid) == [
        ("cancelled", "pharmacy_suspended")]
    assert scalar("SELECT count(*) FROM notification WHERE reservation_id = :r AND kind = 'reservation_withdrawn'",
                  r=rid) == 1


# 8, 9, 25 ------------------------------------------------------------------
def test_08_two_collections_of_one_reservation(client):
    w = ResWorld(client)
    r = w.confirmed(quantity=2)
    first = Held(w.staff, reservations.collect, w.org, r.reservation_id, reference=r.reference)
    second = in_background(outcome, w.manager, reservations.collect, w.org, r.reservation_id, reference=r.reference)
    wait_blocked()
    first.commit()
    assert ok(result_of(second)).changed is False
    assert (w.stock_quantity(), scalar("SELECT count(*) FROM reservation_collection")) == (8, 1)


def test_09_duplicate_confirmations_and_cancellations(client):
    w = ResWorld(client)
    r = w.submit()
    first = Held(w.staff, reservations.confirm, w.org, r.reservation_id)
    second = in_background(outcome, w.manager, reservations.confirm, w.org, r.reservation_id)
    wait_blocked()
    first.commit()
    assert ok(result_of(second)).changed is False
    first = Held(w.patient, reservations.cancel_by_patient, r.reservation_id)
    second = in_background(outcome, w.patient, reservations.cancel_by_patient, r.reservation_id)
    wait_blocked()
    first.commit()
    assert ok(result_of(second)).changed is False
    assert [h[0] for h in rows("SELECT to_status FROM reservation_status_history WHERE reservation_id = :r "
                                "ORDER BY history_id", r=r.reservation_id)] == ["requested", "confirmed", "cancelled"]


def test_25_normal_and_override_collection_together(client):
    w = ResWorld(client)
    r = w.confirmed(quantity=2)
    normal = Held(w.staff, reservations.collect, w.org, r.reservation_id, reference=r.reference)
    override = in_background(
        outcome, w.manager, reservations.collect, w.org, r.reservation_id, reference=r.reference,
        override=CollectionOverride(12, 10, "Counted the shelf twice", True),
    )
    wait_blocked()
    normal.commit()
    assert ok(result_of(override)).changed is False
    assert rows("SELECT override, quantity_after FROM reservation_collection") == [(False, 8)]


# 10, 11 --------------------------------------------------------------------
def test_10a_branch_closed_then_submission(client):
    w = ResWorld(client)
    db = session(w.owner)
    branch = reservations.lock_location(db, w.branch)
    branch.is_active = False
    db.flush()
    submit = in_background(outcome, w.patient, reservations.submit, **submit_args(w))
    wait_blocked()
    db.commit()
    db.close()
    assert error_code(result_of(submit)) == ("not_reservable", "branch_inactive")


def test_10b_submission_then_branch_close(client):
    w = ResWorld(client)
    submit = Held(w.patient, reservations.submit, **submit_args(w))
    close = in_background(api_call, w.owner, organizations_api.update_location, w.org, w.branch,
                          LocationUpdate(is_active=False))
    wait_blocked()
    submit.commit()
    assert error_code(result_of(close))[0] == "open_reservations"
    assert scalar("SELECT is_active FROM location WHERE location_id = :l", l=w.branch) is True


def test_11a_stock_deleted_then_submission(client):
    w = ResWorld(client)
    db = session(w.owner)
    db.delete(reservations.lock_stock(db, w.branch, w.product))
    db.flush()
    submit = in_background(outcome, w.patient, reservations.submit, **submit_args(w))
    wait_blocked()
    db.commit()
    db.close()
    assert error_code(result_of(submit))[0] == "not_reservable"
    assert scalar("SELECT count(*) FROM reservation") == 0


def test_11b_submission_then_stock_delete(client):
    w = ResWorld(client)
    submit = Held(w.patient, reservations.submit, **submit_args(w))
    delete = in_background(api_call, w.owner, inventory_api.delete_stock, w.org, w.branch, w.product)
    wait_blocked()
    submit.commit()
    assert error_code(result_of(delete))[0] == "open_reservations"
    assert w.stock_quantity() == 10


# 12-15: interleavings that deadlock with the wrong lock modes ---------------
def test_12_suspension_and_patient_cancellation(client):
    w = ResWorld(client)
    r = w.confirmed(quantity=2)
    db = session(w.patient)
    reservations._lock(db, Reservation, Reservation.reservation_id == r.reservation_id, mode="update")
    suspension = in_background(suspend_via_api, w)
    wait_blocked()  # the suspension holds the organization and waits for the reservation
    # The cancellation now notifies the organization (a foreign-key check on it).
    reservations.cancel_by_patient.__wrapped__(db, db.get(User, w.patient), r.reservation_id)
    db.commit()
    db.close()
    ok(result_of(suspension))
    assert rows("SELECT status, cancelled_by_role FROM reservation") == [("cancelled", "patient")]


def test_13_suspension_and_expiry_job(client):
    w = ResWorld(client)
    r = w.confirmed(quantity=2)
    backdate(r.reservation_id)
    db = session(None)
    ids = list(db.scalars(select(Reservation.reservation_id).where(reservations.lapsed_clause())
                          .with_for_update(skip_locked=True)))
    suspension = in_background(suspend_via_api, w)
    wait_blocked()
    reservations._expire_locked(db, ids)
    db.commit()
    db.close()
    ok(result_of(suspension))
    assert rows("SELECT status, status_reason FROM reservation") == [("expired", "collection_window_elapsed")]
    # Once each: the patient, and (Phase 5A) the pharmacy, told the confirmed reservation was not collected.
    assert rows("SELECT recipient_user_id IS NOT NULL, organization_id IS NOT NULL FROM notification "
                "WHERE kind = 'reservation_expired' ORDER BY notification_id") == [(True, False), (False, True)]


def test_14_suspension_and_decline(client):
    w = ResWorld(client)
    r = w.submit()
    db = session(w.staff)
    reservations._lock(db, Reservation, Reservation.reservation_id == r.reservation_id, mode="update")
    suspension = in_background(suspend_via_api, w)
    wait_blocked()
    reservations.decline.__wrapped__(db, db.get(User, w.staff), w.org, r.reservation_id, "Not in stock today")
    db.commit()
    db.close()
    ok(result_of(suspension))
    assert w.status(r.reservation_id) == "declined"


def test_15_submission_and_expiry_job_notifying_the_same_patient(client):
    w = ResWorld(client)
    old = w.submit()
    backdate(old.reservation_id)
    db = session(None)
    ids = list(db.scalars(select(Reservation.reservation_id).where(reservations.lapsed_clause())
                          .with_for_update(skip_locked=True)))
    submit = in_background(outcome, w.patient, reservations.submit, **submit_args(w))
    wait_blocked()  # the submission holds the patient's row and waits for the lapsed reservation
    reservations._expire_locked(db, ids)  # notifies the patient (a foreign-key check on that row)
    db.commit()
    db.close()
    new = ok(result_of(submit)).reservation
    assert new.status == "requested" and w.status(old.reservation_id) == "expired"


# 16, 17 --------------------------------------------------------------------
def test_16_override_and_concurrent_stock_correction(client):
    w = ResWorld(client)
    r = w.confirmed(quantity=5)
    w.set_stock(w.product, 2)
    correction = HeldSQL(w.owner)
    correction.execute("UPDATE stock SET quantity = 4 WHERE location_id = :l AND product_id = :p",
                       l=w.branch, p=w.product)
    override = in_background(
        outcome, w.manager, reservations.collect, w.org, r.reservation_id, reference=r.reference,
        override=CollectionOverride(7, 2, "Counted the shelf twice", True),
    )
    wait_blocked()
    correction.commit()
    assert error_code(result_of(override))[0] == "stock_changed"
    assert w.stock_quantity() == 4 and w.status(r.reservation_id) == "confirmed"
    assert rows("SELECT old_quantity, new_quantity FROM stock_adjustment WHERE location_id = :l AND product_id = :p "
                "ORDER BY adjustment_id DESC LIMIT 1", l=w.branch, p=w.product) == [(2, 4)]


def test_17_override_and_confirmation_on_the_same_stock(client):
    w = ResWorld(client)
    r1 = w.confirmed(quantity=5)
    r2 = w.submit(patient=w.patient2, quantity=2)  # requested before the correction: it holds 2
    w.set_stock(w.product, 3)
    override = Held(w.manager, reservations.collect, w.org, r1.reservation_id, reference=r1.reference,
                    override=CollectionOverride(8, 3, "Delivery not entered yet", True))
    confirm = in_background(outcome, w.staff, reservations.confirm, w.org, r2.reservation_id)
    wait_blocked()
    override.commit()
    assert ok(result_of(confirm)).reservation.status == "confirmed"
    position = run(None, reservations.stock_position, w.branch, w.product)
    assert (position.quantity, position.allocated, position.available_to_reserve, position.shortfall) == (3, 2, 1, 0)


# 18, 19, 20 ----------------------------------------------------------------
def test_18_same_request_id_twice_at_once(client):
    w = ResWorld(client)
    args = submit_args(w)
    first = Held(w.patient, reservations.submit, **args)
    second = in_background(outcome, w.patient, reservations.submit, **args)
    wait_blocked()
    first.commit()
    again = ok(result_of(second))
    assert again.changed is False and again.reservation.reservation_id == first.result.reservation.reservation_id
    assert scalar("SELECT count(*) FROM reservation") == 1


def test_19_open_cap_with_concurrent_submissions(client, monkeypatch):
    w = ResWorld(client)
    other = w.medicine("Ibuprofen", "Brufen 200mg")
    monkeypatch.setattr(reservations.settings, "reservation_max_open_per_patient", 1)
    first = Held(w.patient, reservations.submit, **submit_args(w))
    second = in_background(outcome, w.patient, reservations.submit, **submit_args(w, product=other))
    wait_blocked()
    first.commit()
    assert error_code(result_of(second))[0] == "too_many_open_reservations"


def test_20_expiry_job_in_parallel(client):
    w = ResWorld(client)
    lapsed = [w.submit(quantity=1).reservation_id, w.confirmed(quantity=1, patient=w.patient2).reservation_id,
              w.submit(patient=w.outsider, quantity=1).reservation_id]
    for rid in lapsed:
        backdate(rid)
    first = Held(None, reservations.expire_due)
    assert sorted(first.result) == sorted(lapsed)
    assert run(None, reservations.expire_due) == []  # skips the rows the first run holds
    first.commit()
    assert run(None, reservations.expire_due) == []
    assert scalar("SELECT count(*) FROM reservation_status_history WHERE to_status = 'expired'") == 3
    assert scalar("SELECT count(*) FROM notification WHERE kind = 'reservation_expired' AND recipient_user_id IS NOT NULL") == 3
    # Phase 5A: the pharmacy is told about the confirmed reservation that was not collected (one).
    assert scalar("SELECT count(*) FROM notification WHERE kind = 'reservation_expired' AND organization_id IS NOT NULL") == 1
    assert scalar("SELECT count(*) FROM notification WHERE kind = 'reservation_request_lapsed'") == 2


# Exact stock-adjustment association under concurrent stock activity ---------
@pytest.mark.parametrize("round_", range(3))
def test_collections_reference_their_own_adjustments(client, round_):
    w = ResWorld(client, quantity=20)
    other = w.medicine("Ibuprofen", "Brufen 200mg", quantity=20)
    put_stock(client, w.owner_headers, w.org, w.branch2, w.product, 20, "500.00")
    r1 = w.confirmed(quantity=3)  # branch 1, product 1
    r2 = run(w.patient2, reservations.submit, location_id=w.branch2, product_id=w.product, quantity=4,
             contact_phone=PHONE, client_request_id=uuid.uuid4()).reservation
    r2 = w.confirm(r2.reservation_id)
    r3 = w.confirmed(quantity=2, patient=w.outsider, product=other)
    w.set_stock(other, 1)  # r3 needs an override at branch 1
    barrier = threading.Barrier(6)

    def collect(reservation, actor, override=None):
        barrier.wait()
        return outcome(actor, reservations.collect, w.org, reservation.reservation_id,
                       reference=reservation.reference, override=override)

    def churn(location_id, product_id):
        barrier.wait()
        for quantity in range(30, 40):
            tx = HeldSQL(w.owner)
            tx.execute("INSERT INTO stock (location_id, product_id, quantity) VALUES (:l, :p, :q) "
                       "ON CONFLICT (location_id, product_id) DO UPDATE SET quantity = EXCLUDED.quantity",
                       l=location_id, p=product_id, q=quantity)
            tx.commit()

    churn_products = [w.medicine("Cetirizine", f"Zyrtec {round_}", classify=False),
                      w.medicine("Loratadine", f"Clarityn {round_}", classify=False, branch=w.branch2)]
    futures = [
        in_background(collect, r1, w.staff),
        in_background(collect, r2, w.manager),
        in_background(collect, r3, w.owner, CollectionOverride(6, 1, "Counted after delivery", True)),
        in_background(churn, w.branch, churn_products[0]),
        in_background(churn, w.branch2, churn_products[1]),
        in_background(churn, w.branch2, churn_products[0]),
    ]
    results = [result_of(f) for f in futures[:3]]
    for f in futures[3:]:
        result_of(f)
    collected = {ok(res).reservation.reservation_id for res in results}
    assert collected == {r1.reservation_id, r2.reservation_id, r3.reservation_id}

    for reservation, actor in ((r1, w.staff), (r2, w.manager), (r3, w.owner)):
        c = rows("SELECT recorded_quantity_before, verified_on_hand, quantity_after, correction_adjustment_id, "
                 "deduction_adjustment_id, collected_by FROM reservation_collection WHERE reservation_id = :r",
                 r=reservation.reservation_id)[0]
        before, verified, after, correction_id, deduction_id, by = c
        assert by == actor
        deduction = rows("SELECT location_id, product_id, old_quantity, new_quantity, changed_by FROM stock_adjustment "
                         "WHERE adjustment_id = :a", a=deduction_id)[0]
        assert deduction == (reservation.location_id, reservation.product_id, verified or before, after, actor)
        if verified is not None:
            correction = rows("SELECT location_id, product_id, old_quantity, new_quantity, changed_by "
                              "FROM stock_adjustment WHERE adjustment_id = :a", a=correction_id)[0]
            assert correction == (reservation.location_id, reservation.product_id, before, verified, actor)
        else:
            assert correction_id is None
