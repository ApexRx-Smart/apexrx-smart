"""Shared setup for the reservation tests (local *_test database only).

* ``ResWorld``: an approved pharmacy with two branches, an owner, a manager, a
  staff member, two patients, and medicines configured for reservations.
* ``run``: one engine call in its own session (its own transaction), acting
  as a user, the way the API will call it.
* ``hold``: an engine call WITHOUT its commit (``fn.__wrapped__``), so a test
  can keep its locks while another session tries to proceed, then commit.
* ``wait_blocked``: waits until another session is waiting for a row lock,
  read from pg_stat_activity; this makes concurrency tests deterministic.
* ``backdate``: moves a reservation's deadlines into the past. Deadlines are
  stamped by triggers and cannot be changed by the application, so this uses
  session_replication_role = replica, which needs the superuser test role.
"""

import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import text

from app.core.database import SessionLocal, engine, set_session_actor
from app.models import User
from app.services import reservations
from tests.helpers import admin, approve, catalogue_product, location, organization, stock, user

PHONE = "+250 788 123 456"
LOCK_TIMEOUT = "20s"


def user_id(client, headers) -> int:
    return client.get("/auth/me", headers=headers).json()["user_id"]


def add_member(user_id_: int, organization_id: int, role: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO membership (user_id, organization_id, role) VALUES (:u, :o, :r)"),
            {"u": user_id_, "o": organization_id, "r": role},
        )


def session(user_id_: int | None):
    db = SessionLocal()
    db.execute(text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'"))
    if user_id_ is not None:
        set_session_actor(db, user_id_)
    return db


def run(user_id_: int | None, fn, *args, **kwargs):
    """Call an engine function as ``user_id_`` (None: the system) in a new session."""
    db = session(user_id_)
    try:
        if user_id_ is None:
            return fn(db, *args, **kwargs)
        return fn(db, db.get(User, user_id_), *args, **kwargs)
    finally:
        db.close()


def outcome(user_id_: int | None, fn, *args, **kwargs):
    """Like ``run`` but returns ("ok", value) or ("error", exception)."""
    try:
        return "ok", run(user_id_, fn, *args, **kwargs)
    except Exception as exc:  # noqa: BLE001 - the test inspects it
        return "error", exc


class Held:
    """An engine call done but not committed: its locks are still held."""

    def __init__(self, user_id_: int | None, fn, *args, **kwargs):
        self.db = session(user_id_)
        target = fn.__wrapped__ if hasattr(fn, "__wrapped__") else fn
        try:
            if user_id_ is None:
                self.result = target(self.db, *args, **kwargs)
            else:
                self.result = target(self.db, self.db.get(User, user_id_), *args, **kwargs)
        except BaseException:
            self.rollback()
            raise

    def commit(self):
        self.db.commit()
        self.db.close()

    def rollback(self):
        self.db.rollback()
        self.db.close()


class HeldSQL:
    """A raw transaction (optionally acting as a user) kept open."""

    def __init__(self, user_id_: int | None = None):
        self.conn = engine.connect()
        self.tx = self.conn.begin()
        self.conn.execute(text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'"))
        if user_id_ is not None:
            self.conn.execute(text("SELECT set_config('app.user_id', :u, true)"), {"u": str(user_id_)})

    def execute(self, sql: str, **params):
        return self.conn.execute(text(sql), params)

    def commit(self):
        try:
            self.tx.commit()
        finally:
            self.conn.close()

    def rollback(self):
        try:
            self.tx.rollback()
        finally:
            self.conn.close()


def waiting_for_locks() -> int:
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                "AND wait_event_type = 'Lock' AND pid <> pg_backend_pid()"
            )
        ).scalar()


def wait_blocked(timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if waiting_for_locks():
            return
        time.sleep(0.02)
    raise AssertionError("the second session never waited for a lock")


def in_background(fn, *args, **kwargs):
    pool = ThreadPoolExecutor(max_workers=1)
    future = pool.submit(fn, *args, **kwargs)
    pool.shutdown(wait=False)
    return future


def backdate(reservation_id: int, hours: int = 25) -> None:
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL session_replication_role = replica"))
        conn.execute(
            text(
                "UPDATE reservation SET respond_by = respond_by - make_interval(hours => :h), "
                "expires_at = expires_at - make_interval(hours => :h) WHERE reservation_id = :r"
            ),
            {"h": hours, "r": reservation_id},
        )


def scalar(sql: str, **params):
    with engine.connect() as conn:
        return conn.execute(text(sql), params).scalar()


def rows(sql: str, **params):
    with engine.connect() as conn:
        return conn.execute(text(sql), params).all()


class ResWorld:
    def __init__(self, client, *, quantity: int = 10, max_quantity: int = 5):
        self.client = client
        self.admin_headers = admin(client)
        self.admin = user_id(client, self.admin_headers)
        owner = user(client, "owner@pharmacy.example.com", "Pharmacy Owner")
        self.owner = user_id(client, owner)
        self.owner_headers = owner
        self.org = organization(client, owner, "pharmacy", "Kigali Pharmacy")
        approve(client, self.admin_headers, self.org)
        self.branch = location(client, owner, self.org, "Downtown", -1.9441, 30.0619)
        self.branch2 = location(client, owner, self.org, "Remera", -1.95, 30.1)
        self.headers = {self.owner: owner, self.admin: self.admin_headers}

        def person(email, name):
            headers = user(client, email, name)
            uid = user_id(client, headers)
            self.headers[uid] = headers
            return uid

        self.manager = person("manager@pharmacy.example.com", "Manager")
        self.staff = person("staff@pharmacy.example.com", "Staff")
        add_member(self.manager, self.org, "manager")
        add_member(self.staff, self.org, "staff")
        self.patient = person("patient@example.com", "Patient One")
        self.patient2 = person("patient2@example.com", "Patient Two")
        self.outsider = person("outsider@example.com", "Other Pharmacist")
        self.product = self.medicine("Paracetamol", "Panadol 500mg", quantity=quantity, max_quantity=max_quantity)

    def medicine(self, drug, name, *, quantity=10, max_quantity=5, branch=None, enable=True, ack=True):
        branch = branch or self.branch
        product = catalogue_product(self.client, self.admin_headers, drug, name, pack_size="20 tablets")
        stock(self.client, self.owner_headers, self.org, branch, product, quantity, "500.00")
        if enable:
            self.configure(product)
        if ack:
            self.acknowledge(product, branch)
        return product

    def configure(self, product, **changes):
        settings = dict(
            dispensing_class="non_prescription",
            stock_unit="pack",
            unit_label="box",
            max_reservation_quantity=5,
            reservation_enabled=True,
        )
        settings.update(changes)
        return run(self.admin, reservations.configure_product, product, **settings)

    def acknowledge(self, product, branch=None, by=None):
        info = rows(
            "SELECT unit_version, stock_unit, unit_label, pack_size FROM product WHERE product_id = :p", p=product
        )[0]
        return run(
            by or self.owner,
            reservations.acknowledge_unit,
            self.org,
            branch or self.branch,
            product,
            unit_version=info[0],
            stock_unit=info[1],
            unit_label=info[2],
            pack_size=info[3],
        )

    def submit(self, patient=None, product=None, quantity=2, branch=None, client_request_id=None):
        return run(
            patient or self.patient,
            reservations.submit,
            location_id=branch or self.branch,
            product_id=product or self.product,
            quantity=quantity,
            contact_phone=PHONE,
            client_request_id=client_request_id or uuid.uuid4(),
        ).reservation

    def confirm(self, reservation_id, by=None):
        return run(by or self.staff, reservations.confirm, self.org, reservation_id).reservation

    def confirmed(self, quantity=2, patient=None, product=None):
        r = self.submit(patient=patient, quantity=quantity, product=product)
        return self.confirm(r.reservation_id)

    def collect(self, reservation, by=None, override=None):
        return run(
            by or self.staff,
            reservations.collect,
            self.org,
            reservation.reservation_id,
            reference=reservation.reference,
            override=override,
        )

    def set_stock(self, product, quantity, branch=None):
        stock(self.client, self.owner_headers, self.org, branch or self.branch, product, quantity)

    def stock_quantity(self, product=None, branch=None):
        return scalar(
            "SELECT quantity FROM stock WHERE location_id = :l AND product_id = :p",
            l=branch or self.branch,
            p=product or self.product,
        )

    def status(self, reservation_id):
        return scalar("SELECT status FROM reservation WHERE reservation_id = :r", r=reservation_id)
