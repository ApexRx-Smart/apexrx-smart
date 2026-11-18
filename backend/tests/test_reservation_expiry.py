"""The scheduled reservation-expiry job (app/scripts/expire_reservations.py) over
the engine's expire_due_batch: what it records, the notifications, idempotency,
concurrency, failure and retry, stock after expiry, exit codes and its log.

Local *_test database only. Deadlines are moved into the past with the existing
``backdate`` fixture (deadlines are stamped by triggers and cannot be set by the
application); everything else goes through the engine and the API.
"""

import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy.exc import OperationalError

from app.scripts import expire_reservations as job
from app.services import reservations
from tests.reservation_support import PHONE, HeldSQL, ResWorld, backdate, rows, scalar


@pytest.fixture
def w(client):
    return ResWorld(client)


def run_job(capsys, *args):
    code = job.main(list(args))
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    return code, events


def finish(events):
    return next(e for e in events if e["event"] in ("reservation_expiry.finish", "reservation_expiry.failed"))


def notes(reservation_id):
    return rows(
        "SELECT kind, organization_id IS NOT NULL AS to_pharmacy FROM notification "
        "WHERE reservation_id = :r ORDER BY notification_id", r=reservation_id,
    )


def status(reservation_id):
    return rows("SELECT status, status_reason FROM reservation WHERE reservation_id = :r", r=reservation_id)[0]


def due_requests(w, n):
    """``n`` requests past their response deadline (distinct patient/medicine pairs)."""
    patients = [w.patient, w.patient2, w.outsider]
    products = [w.product] + [w.medicine(f"Drug{i}", f"Medicine {i}") for i in range(1, (n + 2) // 3 + 1)]
    made = []
    for i in range(n):
        r = w.submit(patient=patients[i % 3], product=products[i // 3], quantity=1)
        backdate(r.reservation_id)
        made.append(r.reservation_id)
    return made


def test_nothing_due_is_a_successful_run(w, capsys):
    fresh = w.submit()
    code, events = run_job(capsys)
    end = finish(events)
    assert code == 0 and events[0]["event"] == "reservation_expiry.start"
    assert (end["outcome"], end["expired"], end["notifications"], end["due_before"]) == ("success", 0, 0, 0)
    assert status(fresh.reservation_id) == ("requested", None)


def test_unanswered_request_expires_with_patient_and_pharmacy_notifications(w, capsys):
    r = w.submit(quantity=2)
    backdate(r.reservation_id)
    code, events = run_job(capsys)
    end = finish(events)
    assert code == 0 and (end["unanswered"], end["uncollected"], end["notifications"]) == (1, 0, 2)
    assert status(r.reservation_id) == ("expired", "response_window_elapsed")
    assert notes(r.reservation_id) == [
        ("reservation_requested", True), ("reservation_expired", False), ("reservation_request_lapsed", True)
    ]
    history = rows("SELECT to_status, source, system_reason FROM reservation_status_history "
                   "WHERE reservation_id = :r ORDER BY history_id", r=r.reservation_id)
    assert history[-1] == ("expired", "system", "response_window_elapsed")


def test_uncollected_confirmed_reservation_expires_and_frees_its_stock(w, capsys, client):
    r = w.confirmed(quantity=4)
    assert w.stock_quantity() == 10
    backdate(r.reservation_id)
    code, events = run_job(capsys)
    end = finish(events)
    assert code == 0 and (end["unanswered"], end["uncollected"], end["notifications"]) == (0, 1, 2)
    assert status(r.reservation_id) == ("expired", "collection_window_elapsed")
    assert notes(r.reservation_id)[-2:] == [("reservation_expired", False), ("reservation_expired", True)]
    # Nothing was deducted, nothing stays held: the full stock is available again.
    item = next(i for i in client.get(f"/organizations/{w.org}/inventory", headers=w.owner_headers).json()["items"]
                if i["product_id"] == w.product)
    assert (item["quantity"], item["allocated_quantity"], item["available_to_reserve"]) == (10, 0, 10)
    assert item["availability_status"] == "in_stock"
    # The pharmacy reads the new notice in its list, with the reference.
    pharmacy = client.get("/notifications", params={"organization_id": w.org}, headers=w.owner_headers).json()
    assert ("reservation_expired", r.reference) in {(n["kind"], n["reservation_reference"]) for n in pharmacy["items"]}
    patient = client.get("/notifications", headers=w.headers[w.patient]).json()
    assert ("reservation_expired", r.reference) in {(n["kind"], n["reservation_reference"]) for n in patient["items"]}


def test_many_due_in_small_batches_and_reservations_not_yet_due_are_untouched(w, capsys):
    due = due_requests(w, 5)
    confirmed = w.confirmed(quantity=1, patient=w.patient, product=w.medicine("Later", "Not due yet"))
    pending = w.submit(patient=w.patient2, product=w.medicine("Fresh", "Fresh request"))
    code, events = run_job(capsys, "--batch-size", "2")
    end = finish(events)
    batches = [e for e in events if e["event"] == "reservation_expiry.batch"]
    assert code == 0 and [b["expired"] for b in batches] == [2, 2, 1]
    assert (end["expired"], end["unanswered"], end["notifications"], end["remaining_due"]) == (5, 5, 10, 0)
    assert all(status(i)[0] == "expired" for i in due)
    assert status(confirmed.reservation_id) == ("confirmed", None)
    assert status(pending.reservation_id) == ("requested", None)
    assert notes(pending.reservation_id) == [("reservation_requested", True)]


def test_repeated_runs_never_notify_twice(w, capsys):
    due = due_requests(w, 3)
    first = run_job(capsys)
    total = scalar("SELECT count(*) FROM notification")
    second = run_job(capsys)
    end = finish(second[1])
    assert first[0] == second[0] == 0
    assert (end["expired"], end["notifications"], end["due_before"]) == (0, 0, 0)
    assert scalar("SELECT count(*) FROM notification") == total
    assert all(len(notes(i)) == 3 for i in due)


def test_concurrent_runs_record_each_reservation_once(w):
    due = due_requests(w, 9)
    stop = threading.Event()
    with ThreadPoolExecutor(max_workers=3) as pool:
        codes = list(pool.map(lambda _: job.run(2, 50, stop), range(3)))
    assert codes == [0, 0, 0]
    assert all(status(i)[0] == "expired" for i in due)
    per = rows("SELECT reservation_id, count(*) FROM notification WHERE kind <> 'reservation_requested' "
               "GROUP BY reservation_id")
    assert sorted(per) == sorted((i, 2) for i in due)
    assert scalar("SELECT count(*) FROM reservation_status_history WHERE to_status = 'expired'") == 9


def test_a_reservation_held_by_another_transaction_is_skipped_then_taken_later(w, capsys):
    held_id, free_id = due_requests(w, 2)
    other = HeldSQL()
    other.execute("SELECT 1 FROM reservation WHERE reservation_id = :r FOR UPDATE", r=held_id)
    try:
        code, events = run_job(capsys)
        end = finish(events)
        assert code == 0 and (end["expired"], end["remaining_due"]) == (1, 1)
        assert status(free_id)[0] == "expired" and status(held_id)[0] == "requested"
    finally:
        other.rollback()
    code, events = run_job(capsys)
    assert code == 0 and finish(events)["expired"] == 1 and status(held_id)[0] == "expired"


def test_a_failure_rolls_the_whole_batch_back_and_the_next_run_completes_it(w, capsys, monkeypatch):
    due = due_requests(w, 3)
    real = reservations.notify_reservation
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 3:  # the connection drops halfway through the batch
            raise OperationalError("INSERT INTO notification", {}, Exception("server closed the connection"))
        return real(*args, **kwargs)

    monkeypatch.setattr(reservations, "notify_reservation", flaky)
    code, events = run_job(capsys)
    failed = finish(events)
    assert code == 1 and failed["event"] == "reservation_expiry.failed" and failed["error"] == "OperationalError"
    # Nothing half-done: no status changed, no notification was kept.
    assert all(status(i) == ("requested", None) for i in due)
    assert all(notes(i) == [("reservation_requested", True)] for i in due)

    monkeypatch.setattr(reservations, "notify_reservation", real)
    code, events = run_job(capsys)
    assert code == 0 and finish(events)["expired"] == 3
    assert all(len(notes(i)) == 3 for i in due)


def test_check_mode_changes_nothing_and_refuses_an_old_schema(w, capsys, monkeypatch):
    r = w.submit()
    backdate(r.reservation_id)
    c = w.confirmed(quantity=1, patient=w.patient2)
    backdate(c.reservation_id)
    code, events = run_job(capsys, "--check")
    end = finish(events)
    assert code == 0 and end["outcome"] == "checked" and end["due"] == {"unanswered": 1, "uncollected": 1}
    assert status(r.reservation_id)[0] == "requested" and status(c.reservation_id)[0] == "confirmed"

    monkeypatch.setattr(job.schema, "schema_problem", lambda _c: "Database schema is not up to date")
    code, events = run_job(capsys)
    assert code == 1 and events[-1]["event"] == "reservation_expiry.refused"
    assert status(r.reservation_id)[0] == "requested"


def test_interrupted_run_exits_2_and_leaves_the_rest_for_later(w, capsys):
    due = due_requests(w, 2)
    stop = threading.Event()
    stop.set()  # a SIGTERM arrived before the first batch
    assert job.run(200, 50, stop) == 2
    end = finish([json.loads(x) for x in capsys.readouterr().out.splitlines()])
    assert end["outcome"] == "interrupted" and end["expired"] == 0 and end["remaining_due"] == 2
    assert all(status(i)[0] == "requested" for i in due)


def test_the_log_holds_counts_only_never_personal_data(w, capsys):
    due_requests(w, 2)
    code, events = run_job(capsys)
    text = json.dumps(events)
    assert code == 0
    assert {e["event"] for e in events} >= {"reservation_expiry.start", "reservation_expiry.batch", "reservation_expiry.finish"}
    for secret in (PHONE, "+250788123456", "Patient One", "patient@example.com", "RX-"):
        assert secret not in text
    end = finish(events)
    assert {"duration_ms", "due_before", "remaining_due", "already_processed", "unanswered", "uncollected",
            "notifications"} <= set(end)


@pytest.mark.parametrize("args", [["--batch-size", "0"], ["--max-batches", "5000"]])
def test_invalid_options_are_refused(args, capsys):
    with pytest.raises(SystemExit) as exc:
        job.main(args)
    assert exc.value.code == 2
