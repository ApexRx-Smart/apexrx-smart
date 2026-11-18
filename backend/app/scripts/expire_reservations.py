"""Record patient-reservation expiry: the scheduled job.

    python -m app.scripts.expire_reservations              # record what is due
    python -m app.scripts.expire_reservations --check      # read only: what is due
    python -m app.scripts.expire_reservations --batch-size 200 --max-batches 50

Reservations already behave as expired the moment a deadline passes (every
query and trigger compares deadlines with the current time). This job RECORDS
it - status ``expired``, the reason, the history row - and sends the
notifications, through the reservation engine's ``expire_due_batch`` (no second
expiry logic here):

* a request past its 24-hour response deadline: the patient is told it expired,
  the pharmacy that the request lapsed;
* a confirmed reservation past its 24-hour collection deadline: the patient is
  told it expired, the pharmacy that it was not collected (its stock is free).

Safe to run repeatedly and concurrently. Each batch is ONE transaction: rows
are locked with FOR UPDATE SKIP LOCKED (a row held by a user's action or
another run is skipped, not waited for), their expiry and notifications are
committed together, and notifications are unique per reservation, kind and
recipient. A crash or lost connection rolls the batch back completely; the
next run takes the same rows again. Nothing is half-done.

Environment: the same as the API (``DATABASE_URL``, ``JWT_SECRET_KEY`` - the
settings validate it - and optionally ``RESERVATION_EXPIRY_BATCH_SIZE``).
The database must be at the code's migration head; otherwise the job refuses.

Output: one JSON object per line on stdout (start, each batch, finish or
failure) with counts and durations only - never names, phone numbers or other
personal data. Exit status: 0 success (including "nothing due"), 1 failure,
2 interrupted (SIGTERM/SIGINT: the current batch finishes, the rest waits for
the next run).
"""

import argparse
import json
import signal
import sys
import threading
import time

from sqlalchemy import text

from app.core import schema
from app.core.config import settings
from app.core.database import SessionLocal, engine
from app.services import reservations

EXIT_OK, EXIT_FAILED, EXIT_INTERRUPTED = 0, 1, 2
# Per transaction: a batch never waits long for a lock or runs away.
LOCK_TIMEOUT = "10s"
STATEMENT_TIMEOUT = "60s"

def emit(event: str, **fields) -> None:
    """One JSON line on stdout (what a scheduler such as a Render Cron Job keeps as the run's log)."""
    print(json.dumps({"event": f"reservation_expiry.{event}", **fields}, sort_keys=True, default=str), flush=True)


def _error_fields(exc: BaseException) -> dict:
    """The kind of error, never its message (which may quote data)."""
    orig = getattr(exc, "orig", None)
    return {"error": type(exc).__name__, "sqlstate": getattr(orig, "sqlstate", None)}


def check_schema() -> str | None:
    with engine.connect() as connection:
        return schema.schema_problem(connection)


def due() -> dict[str, int]:
    with SessionLocal() as db:
        counts = reservations.count_due(db)
        db.rollback()
        return counts


def one_batch(batch_size: int) -> reservations.ExpiryResult:
    """One transaction, in its own short-lived session (no connection is kept)."""
    with SessionLocal() as db:
        db.execute(text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'"))
        db.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'"))
        return reservations.expire_due_batch(db, limit=batch_size)


def run(batch_size: int, max_batches: int, stop: threading.Event, check_only: bool = False) -> int:
    started = time.monotonic()
    totals = {"batches": 0, "expired": 0, "unanswered": 0, "uncollected": 0, "notifications": 0}
    emit("start", batch_size=batch_size, max_batches=max_batches, check_only=check_only)
    outcome, code = "success", EXIT_OK
    try:
        problem = check_schema()
        if problem:
            emit("refused", reason="schema_not_current", detail=problem)
            return EXIT_FAILED
        before = due()
        if check_only:
            emit("finish", outcome="checked", due=before, duration_ms=round((time.monotonic() - started) * 1000))
            return EXIT_OK
        for _ in range(max_batches):
            if stop.is_set():
                outcome, code = "interrupted", EXIT_INTERRUPTED
                break
            batch_started = time.monotonic()
            result = one_batch(batch_size)
            totals["batches"] += 1
            totals["expired"] += len(result.expired)
            totals["unanswered"] += result.unanswered
            totals["uncollected"] += result.uncollected
            totals["notifications"] += result.notifications
            emit("batch", number=totals["batches"], expired=len(result.expired), unanswered=result.unanswered,
                 uncollected=result.uncollected, notifications=result.notifications,
                 duration_ms=round((time.monotonic() - batch_started) * 1000))
            if len(result.expired) < batch_size:
                break  # nothing more this run could take
        after = due()
        due_before = before["unanswered"] + before["uncollected"]
        remaining = after["unanswered"] + after["uncollected"]
        emit(
            "finish",
            outcome=outcome,
            duration_ms=round((time.monotonic() - started) * 1000),
            due_before=due_before,
            remaining_due=remaining,  # held by other transactions, over max-batches, or newly due
            # Due at the start but recorded by someone else meanwhile (an action
            # on the reservation, or another run): already processed, skipped here.
            already_processed=max(0, due_before - totals["expired"] - remaining),
            **totals,
        )
        return code
    except Exception as exc:  # noqa: BLE001 - reported as a failed run, exit 1
        emit("failed", duration_ms=round((time.monotonic() - started) * 1000), **totals, **_error_fields(exc))
        return EXIT_FAILED
    finally:
        engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record reservation expiry and send its notifications.")
    parser.add_argument("--batch-size", type=int, default=settings.reservation_expiry_batch_size,
                        help="reservations per transaction (default: RESERVATION_EXPIRY_BATCH_SIZE, 200)")
    parser.add_argument("--max-batches", type=int, default=50, help="batches per run (default 50)")
    parser.add_argument("--check", action="store_true", help="read only: report what is due, change nothing")
    args = parser.parse_args(argv)
    if not 1 <= args.batch_size <= 1000 or not 1 <= args.max_batches <= 1000:
        parser.error("--batch-size and --max-batches must be between 1 and 1000")

    stop = threading.Event()

    def interrupted(signum, _frame):
        emit("signal", signal=signal.Signals(signum).name, action="finishing the current batch")
        stop.set()

    previous = {s: signal.signal(s, interrupted) for s in (signal.SIGINT, signal.SIGTERM)}
    try:
        return run(args.batch_size, args.max_batches, stop, check_only=args.check)
    finally:
        for s, handler in previous.items():
            signal.signal(s, handler)


if __name__ == "__main__":
    sys.exit(main())
