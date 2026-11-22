"""The reservation engine (app/services/reservations.py): lifecycle, rules,
idempotency, notifications, eligibility, stock allocation and the guards added
to existing endpoints. Concurrency: test_reservation_concurrency.py. Database
safeguards against direct SQL: test_reservation_db_guards.py."""

import uuid

import pytest
from sqlalchemy import text

from app.core.database import engine
from app.core.errors import AppError, Conflict, Forbidden, NotFound
from app.services import reservations
from app.services.reservations import CollectionOverride
from tests.reservation_support import PHONE, ResWorld, backdate, rows, run, scalar


def code(exc):
    return exc.extra.get("code")


def test_full_lifecycle_and_history(client):
    w = ResWorld(client)
    r = w.submit(quantity=3)
    assert r.status == "requested" and r.reference.startswith("RX-") and len(r.reference) == 13
    assert (r.unit_label, r.pack_size, str(r.unit_price), r.contact_phone) == ("box", "20 tablets", "500.00", "+250788123456")
    assert r.respond_by is not None and r.expires_at is None

    r = w.confirm(r.reservation_id)
    assert r.status == "confirmed" and r.responded_by == w.staff and r.expires_at is not None
    assert w.stock_quantity() == 10  # confirmation never changes physical stock
    position = run(None, reservations.stock_position, w.branch, w.product)
    assert (position.allocated, position.available_to_reserve, position.shortfall) == (3, 7, 0)

    done = w.collect(r)
    assert done.reservation.status == "collected" and done.reservation.collected_by == w.staff
    assert w.stock_quantity() == 7
    history = rows(
        "SELECT from_status, to_status, source, changed_by FROM reservation_status_history "
        "WHERE reservation_id = :r ORDER BY history_id", r=r.reservation_id,
    )
    assert history == [
        (None, "requested", "patient", w.patient),
        ("requested", "confirmed", "pharmacy", w.staff),
        ("confirmed", "collected", "pharmacy", w.staff),
    ]
    kinds = rows(
        "SELECT kind, organization_id, recipient_user_id FROM notification WHERE reservation_id = :r "
        "ORDER BY notification_id", r=r.reservation_id,
    )
    assert kinds == [("reservation_requested", w.org, None), ("reservation_confirmed", None, w.patient)]


def test_decline_and_cancellations(client):
    w = ResWorld(client)
    r = w.submit()
    with pytest.raises(AppError) as exc:
        run(w.staff, reservations.decline, w.org, r.reservation_id, "  ")
    assert code(exc.value) == "reason_required"
    out = run(w.staff, reservations.decline, w.org, r.reservation_id, "Out of this brand")
    assert out.reservation.status == "declined" and out.reservation.decline_reason == "Out of this brand"
    again = run(w.staff, reservations.decline, w.org, r.reservation_id, "Out of this brand")
    assert again.changed is False

    r2 = w.confirmed(patient=w.patient2)
    with pytest.raises(Forbidden):  # D4: staff cannot cancel a confirmed reservation
        run(w.staff, reservations.cancel_by_pharmacy, w.org, r2.reservation_id, "No longer available")
    out = run(w.manager, reservations.cancel_by_pharmacy, w.org, r2.reservation_id, "Batch recalled")
    assert out.reservation.status == "cancelled" and out.reservation.cancelled_by_role == "pharmacy"

    r3 = w.submit()
    with pytest.raises(Conflict) as exc:  # a pending request is declined, not cancelled
        run(w.manager, reservations.cancel_by_pharmacy, w.org, r3.reservation_id, "Not needed")
    assert code(exc.value) == "reservation_state_conflict"
    out = run(w.patient, reservations.cancel_by_patient, r3.reservation_id)
    assert out.reservation.status == "cancelled" and out.reservation.cancelled_by_role == "patient"
    assert run(w.patient, reservations.cancel_by_patient, r3.reservation_id).changed is False
    assert rows(
        "SELECT kind, organization_id FROM notification WHERE reservation_id = :r ORDER BY notification_id", r=r3.reservation_id
    )[-1] == ("reservation_cancelled_patient", w.org)


def test_patients_and_organizations_are_isolated(client):
    w = ResWorld(client)
    r = w.submit()
    with pytest.raises(NotFound):  # another patient
        run(w.patient2, reservations.cancel_by_patient, r.reservation_id)
    with pytest.raises(NotFound):  # not a member of the pharmacy
        run(w.outsider, reservations.confirm, w.org, r.reservation_id)
    with pytest.raises(NotFound):  # a patient is not a member of any organization
        run(w.patient, reservations.confirm, w.org, r.reservation_id)
    # The organization's own notification list never shows patient-addressed rows.
    run(w.staff, reservations.confirm, w.org, r.reservation_id)
    notes = client.get("/notifications", params={"organization_id": w.org}, headers=w.owner_headers).json()
    assert [n["kind"] for n in notes["items"]] == ["reservation_requested"]
    assert notes["items"][0]["reservation_reference"] == r.reference


def test_business_users_cannot_reserve_at_their_own_pharmacy(client):
    w = ResWorld(client)
    with pytest.raises(Conflict) as exc:
        w.submit(patient=w.staff)
    assert code(exc.value) == "own_pharmacy"


@pytest.mark.parametrize(
    "change, reason",
    [
        (dict(dispensing_class="prescription_only"), "prescription_only"),
        (dict(dispensing_class="unclassified"), "unclassified"),
        (dict(stock_unit="unknown", unit_label=None), "unit_unknown"),
        (dict(pack_size=None), "pack_size_missing"),
    ],
)
def test_ineligible_products_cannot_be_reserved(client, change, reason):
    w = ResWorld(client)
    w.configure(w.product, **change)
    with pytest.raises(Conflict) as exc:
        w.submit()
    assert code(exc.value) == "not_reservable" and exc.value.extra["reason"] == reason
    assert run(None, reservations.eligibility_problem, w.branch, w.product) == reason


def test_classified_listed_medicine_needs_nothing_else(client):
    """No per-medicine switch and no branch acknowledgement: a classified,
    listed medicine with stock is reservable as soon as it is classified."""
    w = ResWorld(client)
    product = w.medicine("Ibuprofen", "Brufen 200mg", classify=False)
    with pytest.raises(Conflict) as exc:
        w.submit(product=product)
    assert exc.value.extra["reason"] == "unclassified"
    w.configure(product)
    assert w.submit(product=product).status == "requested"
    assert scalar("SELECT count(*) FROM offer_unit_acknowledgement") == 0


def test_unlisted_offer_cannot_be_reserved(client):
    w = ResWorld(client)
    r = client.put(
        f"/organizations/{w.org}/locations/{w.branch}/stock/{w.product}/offer",
        json={"unit_price": "500.00", "is_listed": False}, headers=w.owner_headers,
    )
    assert r.status_code == 200
    with pytest.raises(Conflict) as exc:
        w.submit()
    assert exc.value.extra["reason"] == "offer_unlisted"


def test_unit_change_needs_no_branch_acknowledgement(client):
    w = ResWorld(client)
    product = w.medicine("Ibuprofen", "Brufen 200mg")
    version = scalar("SELECT unit_version FROM product WHERE product_id = :p", p=product)
    w.configure(product, unit_label="blister")
    assert scalar("SELECT unit_version FROM product WHERE product_id = :p", p=product) == version + 1
    r = w.submit(product=product)
    assert r.status == "requested" and r.unit_label == "blister"


def test_unit_changes_refused_while_reservations_are_open(client):
    w = ResWorld(client)
    w.submit()
    with pytest.raises(Conflict) as exc:
        w.configure(w.product, unit_label="carton")
    assert code(exc.value) == "open_reservations"
    r = client.patch(f"/catalogue/products/{w.product}", json={"pack_size": "30 tablets"}, headers=w.admin_headers)
    assert r.status_code == 409 and r.json()["code"] == "open_reservations"
    # Unrelated catalogue edits still work.
    r = client.patch(f"/catalogue/products/{w.product}", json={"brand": "Panadol"}, headers=w.admin_headers)
    assert r.status_code == 200


def test_product_settings_validation_and_audit(client, monkeypatch):
    w = ResWorld(client)
    product = w.medicine("Ibuprofen", "Brufen 200mg", classify=False)
    # No per-medicine limit: the default limit applies.
    monkeypatch.setattr(reservations.settings, "reservation_default_max_quantity", 3)
    w.configure(product, max_reservation_quantity=None)
    with pytest.raises(Conflict) as exc:
        w.submit(product=product, quantity=4)
    assert code(exc.value) == "quantity_above_limit" and exc.value.extra["max_quantity"] == 3
    for label in ("n/a", "--", "20"):
        with pytest.raises(AppError):
            w.configure(product, unit_label=label)
    for label in ("tablet", "vial", "bottle"):
        w.configure(product, stock_unit="unit", unit_label=label)
    with pytest.raises(Forbidden):
        run(w.owner, reservations.configure_product, product, dispensing_class="non_prescription")
    with pytest.raises(ValueError):  # the retired switch is no longer a setting
        run(w.admin, reservations.configure_product, product, reservation_enabled=True)
    history = rows("SELECT changed_by FROM product_reservation_history WHERE product_id = :p", p=product)
    assert history and all(row[0] == w.admin for row in history)


def test_quantity_limit_open_cap_and_one_open_per_pair(client, monkeypatch):
    w = ResWorld(client)
    with pytest.raises(Conflict) as exc:
        w.submit(quantity=6)
    assert code(exc.value) == "quantity_above_limit" and exc.value.extra["max_quantity"] == 5
    first = w.submit()
    with pytest.raises(Conflict) as exc:
        w.submit()
    assert code(exc.value) == "open_reservation_exists" and exc.value.extra["reference"] == first.reference
    monkeypatch.setattr(reservations.settings, "reservation_max_open_per_patient", 1)
    other = w.medicine("Ibuprofen", "Brufen 200mg")
    with pytest.raises(Conflict) as exc:
        w.submit(product=other)
    assert code(exc.value) == "too_many_open_reservations"


def test_idempotent_submission(client):
    w = ResWorld(client)
    key = uuid.uuid4()
    first = w.submit(client_request_id=key)
    again = run(w.patient, reservations.submit, location_id=w.branch, product_id=w.product, quantity=2,
                contact_phone=PHONE, client_request_id=key)
    assert again.changed is False and again.reservation.reservation_id == first.reservation_id
    with pytest.raises(Conflict) as exc:
        w.submit(client_request_id=key, quantity=3)
    assert code(exc.value) == "idempotency_key_reused"
    # A retry after the reservation moved on still returns it.
    w.confirm(first.reservation_id)
    again = run(w.patient, reservations.submit, location_id=w.branch, product_id=w.product, quantity=2,
                contact_phone=PHONE, client_request_id=key)
    assert again.changed is False and again.reservation.status == "confirmed"
    assert scalar("SELECT count(*) FROM reservation") == 1


def test_requests_hold_stock_from_submission(client):
    w = ResWorld(client, quantity=6)
    a = w.submit(quantity=4)  # held from the request, before any confirmation
    position = run(None, reservations.stock_position, w.branch, w.product)
    assert (position.quantity, position.allocated, position.available_to_reserve, position.reservable) == (6, 4, 2, 2)
    with pytest.raises(Conflict) as exc:
        w.submit(patient=w.patient2, quantity=3)
    assert code(exc.value) == "insufficient_stock" and exc.value.extra["reason"] == "no_reservable_stock"
    b = w.submit(patient=w.patient2, quantity=2)
    assert w.confirm(b.reservation_id).status == "confirmed"  # it already holds its stock
    run(w.patient, reservations.cancel_by_patient, a.reservation_id)  # releases the hold
    assert run(None, reservations.stock_position, w.branch, w.product).allocated == 2


def test_confirmation_refused_after_a_stock_correction(client):
    w = ResWorld(client)
    pending = w.submit(quantity=5)
    w.set_stock(w.product, 3)
    with pytest.raises(Conflict) as exc:
        w.confirm(pending.reservation_id)
    assert code(exc.value) == "insufficient_stock"
    assert w.status(pending.reservation_id) == "requested"


def test_shortfall_after_manual_correction(client):
    w = ResWorld(client)
    a = w.confirmed(quantity=5)
    w.set_stock(w.product, 3)  # D7: a deliberate correction below the held quantity is allowed
    position = run(None, reservations.stock_position, w.branch, w.product)
    assert (position.quantity, position.allocated, position.available_to_reserve, position.shortfall) == (3, 5, 0, 2)
    assert position.at_risk_reservation_ids == [a.reservation_id]
    assert w.status(a.reservation_id) == "confirmed"  # never cancelled silently
    with pytest.raises(Conflict) as exc:  # nothing new may deepen the shortfall
        w.submit(patient=w.patient2, quantity=1)
    assert exc.value.extra["reason"] == "no_reservable_stock"


def test_collection_with_insufficient_record_and_override(client):
    w = ResWorld(client)
    r = w.confirmed(quantity=5)
    w.set_stock(w.product, 2)
    with pytest.raises(Conflict) as exc:
        w.collect(r)
    assert code(exc.value) == "stock_record_insufficient"
    assert exc.value.extra == {"code": "stock_record_insufficient", "recorded_quantity": 2,
                               "reserved_quantity": 5, "can_override": False}
    assert w.status(r.reservation_id) == "confirmed" and w.stock_quantity() == 2  # nothing changed

    good = CollectionOverride(verified_on_hand=7, recorded_quantity_seen=2,
                              reason="Delivery of 5 boxes not yet entered", physically_verified=True)
    with pytest.raises(Forbidden):  # decision 1: owners and managers only
        w.collect(r, by=w.staff, override=good)
    with pytest.raises(AppError) as exc:
        w.collect(r, by=w.manager, override=CollectionOverride(4, 2, "Counted the shelf twice", True))
    assert code(exc.value) == "count_too_low"
    with pytest.raises(AppError) as exc:
        w.collect(r, by=w.manager, override=CollectionOverride(7, 2, "short", True))
    assert code(exc.value) == "reason_required"
    with pytest.raises(AppError) as exc:
        w.collect(r, by=w.manager, override=CollectionOverride(7, 2, "Counted the shelf twice", False))
    assert code(exc.value) == "not_verified"
    with pytest.raises(Conflict) as exc:
        w.collect(r, by=w.manager, override=CollectionOverride(7, 3, "Counted the shelf twice", True))
    assert code(exc.value) == "stock_changed"

    done = w.collect(r, by=w.manager, override=good)
    c = done.collection
    assert done.reservation.status == "collected" and w.stock_quantity() == 2
    assert (c.override, c.override_by, c.recorded_quantity_before, c.verified_on_hand, c.quantity_after) == (
        True, w.manager, 2, 7, 2)
    adjustments = dict(
        (row[0], row[1:]) for row in rows(
            "SELECT adjustment_id, old_quantity, new_quantity, changed_by FROM stock_adjustment "
            "WHERE adjustment_id IN (:a, :b)", a=c.correction_adjustment_id, b=c.deduction_adjustment_id)
    )
    assert adjustments[c.correction_adjustment_id] == (2, 7, w.manager)
    assert adjustments[c.deduction_adjustment_id] == (7, 2, w.manager)


def test_collection_checks_reference_and_is_idempotent(client):
    w = ResWorld(client)
    r = w.confirmed(quantity=2)
    with pytest.raises(AppError) as exc:
        run(w.staff, reservations.collect, w.org, r.reservation_id, reference="RX-AAAAAAAAAA")
    assert code(exc.value) == "reference_mismatch"
    first = w.collect(r)
    again = run(w.staff, reservations.collect, w.org, r.reservation_id, reference=r.reference.lower())
    assert again.changed is False and again.collection.deduction_adjustment_id == first.collection.deduction_adjustment_id
    assert w.stock_quantity() == 8


def test_expiry_by_time_and_recorded_once(client):
    w = ResWorld(client)
    pending = w.submit(quantity=1)
    confirmed = w.confirmed(quantity=3, patient=w.patient2)
    backdate(pending.reservation_id)
    backdate(confirmed.reservation_id)
    # Logically expired immediately: no allocation, collection refused.
    assert run(None, reservations.stock_position, w.branch, w.product).allocated == 0
    with pytest.raises(Conflict) as exc:
        w.collect(confirmed)
    assert code(exc.value) == "expired"
    assert w.status(confirmed.reservation_id) == "expired"  # recorded by the refused action
    assert sorted(run(None, reservations.expire_due)) == [pending.reservation_id]
    assert run(None, reservations.expire_due) == []
    reasons = rows("SELECT reservation_id, source, changed_by, system_reason FROM reservation_status_history "
                   "WHERE to_status = 'expired' ORDER BY reservation_id")
    assert reasons == [
        (pending.reservation_id, "system", None, "response_window_elapsed"),
        (confirmed.reservation_id, "system", None, "collection_window_elapsed"),
    ]
    kinds = sorted(rows("SELECT reservation_id, kind, organization_id IS NOT NULL FROM notification WHERE kind IN "
                        "('reservation_expired', 'reservation_request_lapsed')"))
    # (reservation, kind, addressed to the pharmacy?)
    assert kinds == sorted([(pending.reservation_id, "reservation_expired", False),
                            (pending.reservation_id, "reservation_request_lapsed", True),
                            (confirmed.reservation_id, "reservation_expired", False),
                            (confirmed.reservation_id, "reservation_expired", True)])


def test_lapsed_request_does_not_block_a_new_one(client):
    w = ResWorld(client)
    old = w.submit()
    backdate(old.reservation_id)
    new = w.submit()
    assert new.reservation_id != old.reservation_id and w.status(old.reservation_id) == "expired"
    with pytest.raises(Conflict) as exc:
        w.confirm(old.reservation_id)
    assert code(exc.value) == "reservation_state_conflict" and exc.value.extra["status"] == "expired"


def test_raising_the_minimum_keeps_existing_reservations(client):
    w = ResWorld(client)
    confirmed = w.confirmed(quantity=2)
    pending = w.submit(patient=w.patient2, quantity=3)
    w.set_min_stock(8)  # 10 recorded, 5 held: nothing left for new requests
    with pytest.raises(Conflict) as exc:
        w.submit(patient=w.outsider, quantity=1)
    assert exc.value.extra["reason"] == "no_reservable_stock"
    assert w.confirm(pending.reservation_id).status == "confirmed"  # the minimum applies to new requests only
    assert w.collect(confirmed).reservation.status == "collected"
    assert w.collect(pending).reservation.status == "collected"
    assert w.stock_quantity() == 5
    w.set_min_stock(4)  # 5 recorded, none held: 1 reservable
    assert w.submit(patient=w.outsider, quantity=1).status == "requested"


def test_suspension_closes_open_reservations(client):
    w = ResWorld(client)
    pending = w.submit()
    confirmed = w.confirmed(patient=w.patient2)
    r = client.post(f"/admin/organizations/{w.org}/review", json={"decision": "suspended", "notes": "Licence"},
                    headers=w.admin_headers)
    assert r.status_code == 200, r.text
    assert {w.status(pending.reservation_id), w.status(confirmed.reservation_id)} == {"cancelled"}
    assert rows("SELECT DISTINCT source, system_reason FROM reservation_status_history WHERE to_status = 'cancelled'") == [
        ("system", "pharmacy_suspended")]
    assert scalar("SELECT count(*) FROM notification WHERE kind = 'reservation_withdrawn'") == 2


def test_branch_close_and_stock_delete_refused_while_open(client):
    w = ResWorld(client)
    w.submit()
    r = client.patch(f"/organizations/{w.org}/locations/{w.branch}", json={"is_active": False}, headers=w.owner_headers)
    assert r.status_code == 409 and r.json()["code"] == "open_reservations"
    r = client.delete(f"/organizations/{w.org}/locations/{w.branch}/stock/{w.product}", headers=w.owner_headers)
    assert r.status_code == 409 and r.json()["code"] == "open_reservations"
    # The other branch has none: it can close.
    r = client.patch(f"/organizations/{w.org}/locations/{w.branch2}", json={"is_active": False}, headers=w.owner_headers)
    assert r.status_code == 200


def test_patient_availability_counts_reservations(client):
    w = ResWorld(client, quantity=6)

    def status():
        r = client.get(f"/search/pharmacies/{w.branch}").json()
        return [m["availability_status"] for m in r["medicines"] if m["product_id"] == w.product][0]

    assert status() == "in_stock"
    w.confirmed(quantity=4)  # 2 left, at or under the threshold of 5
    assert status() == "low_stock"
    inventory = client.get(f"/organizations/{w.org}/inventory", headers=w.owner_headers).json()["items"]
    assert [i["availability_status"] for i in inventory if i["product_id"] == w.product] == ["low_stock"]
    assert "quantity" not in client.get(f"/search/pharmacies/{w.branch}").json()["medicines"][0]


def test_notification_has_exactly_one_recipient():
    with engine.begin() as conn, pytest.raises(Exception, match="notification_recipient_check"):
        conn.execute(text("INSERT INTO notification (kind) VALUES ('message')"))


# ---------------------------------------------------------------------------
# Branch minimum stock: boundaries (stock 10 unless stated, limit 20 per reservation)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "stock, minimum, quantity, accepted",
    [
        (10, 0, 10, True),    # default minimum: all the stock can be reserved
        (10, 5, 5, True),     # exactly down to the minimum
        (10, 5, 6, False),    # one below the minimum
        (10, 10, 1, False),   # unallocated stock equals the minimum
        (10, 11, 1, False),   # minimum above the stock
        (0, 0, 1, False),     # no stock at all
        (1, 0, 1, True),      # the last unit
    ],
)
def test_reservable_stock_boundaries(client, stock, minimum, quantity, accepted):
    w = ResWorld(client)
    product = w.medicine("Ibuprofen", "Brufen 200mg", quantity=stock, max_quantity=20)
    w.set_min_stock(minimum)
    if accepted:
        assert w.submit(product=product, quantity=quantity).status == "requested"
        position = run(None, reservations.stock_position, w.branch, product)
        assert position.reservable == max(0, stock - quantity - minimum)
    else:
        with pytest.raises(Conflict) as exc:
            w.submit(product=product, quantity=quantity)
        assert code(exc.value) == "insufficient_stock" and exc.value.extra["reason"] == "no_reservable_stock"
        assert scalar("SELECT count(*) FROM reservation") == 0
    options_problem = run(None, reservations.stock_position, w.branch, product).reservable
    assert options_problem == max(0, stock - (quantity if accepted else 0) - minimum)


def test_several_requests_share_the_reservable_stock(client):
    w = ResWorld(client)  # 10 recorded
    w.set_min_stock(3)    # 7 reservable
    w.submit(quantity=3)
    w.submit(patient=w.patient2, quantity=4)  # exactly what was left
    with pytest.raises(Conflict) as exc:
        w.submit(patient=w.outsider, quantity=1)
    assert exc.value.extra["reason"] == "no_reservable_stock"
    position = run(None, reservations.stock_position, w.branch, w.product)
    assert (position.quantity, position.allocated, position.available_to_reserve, position.min_stock,
            position.reservable) == (10, 7, 3, 3, 0)


def test_each_branch_has_its_own_minimum(client):
    w = ResWorld(client)
    w.set_stock(w.product, 10, branch=w.branch2)
    client.put(f"/organizations/{w.org}/locations/{w.branch2}/stock/{w.product}/offer",
               json={"unit_price": "500.00"}, headers=w.owner_headers).raise_for_status()
    w.set_min_stock(10)  # branch 1 keeps everything back
    with pytest.raises(Conflict):
        w.submit(quantity=1)
    assert w.submit(quantity=2, branch=w.branch2).status == "requested"  # branch 2: minimum 0


def test_allocation_through_the_lifecycle(client):
    """Pending holds, confirmed keeps, declined / cancelled / expired release,
    collected consumes (and the stock drops by the quantity)."""
    w = ResWorld(client)

    def held():
        return run(None, reservations.stock_position, w.branch, w.product).allocated

    a = w.submit(quantity=2)
    assert held() == 2
    a = w.confirm(a.reservation_id)
    assert held() == 2
    b = w.submit(patient=w.patient2, quantity=3)
    assert held() == 5
    run(w.staff, reservations.decline, w.org, b.reservation_id, "Not today")
    assert held() == 2
    c = w.submit(patient=w.patient2, quantity=1)
    run(w.patient2, reservations.cancel_by_patient, c.reservation_id)
    assert held() == 2
    d = w.submit(patient=w.outsider, quantity=4)
    assert held() == 6
    backdate(d.reservation_id)
    assert held() == 2  # past its deadline: released at once, before any job runs
    w.collect(a)
    assert (held(), w.stock_quantity()) == (0, 8)
