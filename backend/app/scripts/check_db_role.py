"""Check that the application's database role cannot switch off the safeguards,
and that it has what the API and the expiry job need.

    python -m app.scripts.check_db_role

Read-only: one READ ONLY transaction, rolled back; nothing is created, granted
or changed. Uses DATABASE_URL like the API (environment first, otherwise
backend/.env). Prints only the target host and database name, the role name and
yes/no answers; never credentials.

The reservation, stock and order guarantees are enforced by triggers. A role
can get around them if it is a superuser, OWNS the tables (or belongs to the
owner role: ALTER TABLE ... DISABLE TRIGGER, DROP TRIGGER), may set
session_replication_role (which turns triggers off for its session), or has
TRUNCATE (which empties a table without firing its row triggers). The API and
the expiry job need only USAGE on the schema, SELECT/INSERT/UPDATE/DELETE on
the tables and USAGE/SELECT on the sequences. Migrations need the owner role;
run them separately with the owner's URL.

Exit status: 0 safe and sufficient, 1 unsafe (or insufficient for the API),
2 the check itself could not run.
"""

import sys
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.engine import Connection

GUARDED_TABLES = (
    "reservation",
    "reservation_collection",
    "reservation_status_history",
    "offer_unit_acknowledgement",
    "product_reservation_history",
    "product",
    "stock",
    "stock_adjustment",
    "product_offer",
    "purchase_order",
    "purchase_order_status_history",
    "notification",
)
# What the API and the expiry job need on every application table.
REQUIRED = ("SELECT", "INSERT", "UPDATE", "DELETE")


@dataclass
class Assessment:
    role: str
    server_version: int
    ssl: bool | None
    superuser: bool
    bypass_rls: bool
    create_role: bool
    create_db: bool
    replication: bool
    owned: list[str] = field(default_factory=list)
    truncate: list[str] = field(default_factory=list)
    trigger: list[str] = field(default_factory=list)
    can_set_replication_role: bool = False
    create_on_schema: bool = False
    missing: list[str] = field(default_factory=list)  # "table: PRIVILEGE" the API needs

    @property
    def unsafe(self) -> list[str]:
        reasons = []
        if self.superuser:
            reasons.append("is a superuser")
        if self.owned:
            reasons.append("owns (or is a member of the owner of) guarded tables: " + ", ".join(self.owned))
        if self.can_set_replication_role:
            reasons.append("may set session_replication_role (turns triggers off)")
        if self.truncate:
            reasons.append("has TRUNCATE (bypasses row triggers) on: " + ", ".join(self.truncate))
        if self.replication:
            reasons.append("has the REPLICATION attribute")
        return reasons

    @property
    def warnings(self) -> list[str]:
        notes = []
        if self.bypass_rls:
            notes.append("bypasses row security (not used by ApexRx today)")
        if self.create_role or self.create_db:
            notes.append("may create roles or databases")
        if self.create_on_schema:
            notes.append("may create objects in schema public")
        if self.trigger:
            notes.append("has TRIGGER (may add triggers, cannot remove ours) on: " + ", ".join(self.trigger))
        if self.ssl is False:
            notes.append("the connection is not encrypted (use sslmode=require)")
        return notes


def assess(conn: Connection) -> Assessment:
    """Read the current role's attributes and privileges (no changes)."""
    q = lambda sql, **p: conn.execute(text(sql), p)  # noqa: E731
    role = q("SELECT current_user").scalar()
    version = int(q("SHOW server_version_num").scalar())
    attrs = q(
        "SELECT rolsuper, rolbypassrls, rolcreaterole, rolcreatedb, rolreplication FROM pg_roles WHERE rolname = current_user"
    ).one()
    try:
        ssl = q("SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()").scalar()
    except Exception:  # noqa: BLE001 - not visible to every role
        ssl = None
    tables = list(GUARDED_TABLES)
    present = set(q("SELECT relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relname = ANY(:t)", t=tables).scalars())
    owned = list(q(
        "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'public' AND c.relname = ANY(:t) AND pg_has_role(current_user, c.relowner, 'USAGE') "
        "ORDER BY c.relname", t=tables).scalars())

    def having(privilege: str) -> list[str]:
        return [t for t in sorted(present) if q("SELECT has_table_privilege(current_user, :t, :p)",
                                                 t=f"public.{t}", p=privilege).scalar()]

    missing = [f"{t}: {p}" for t in sorted(present) for p in REQUIRED
               if not q("SELECT has_table_privilege(current_user, :t, :p)", t=f"public.{t}", p=p).scalar()]
    can_set = False
    if version >= 150000:  # GRANT SET ON PARAMETER exists from PostgreSQL 15
        can_set = bool(q("SELECT has_parameter_privilege(current_user, 'session_replication_role', 'SET')").scalar())
    return Assessment(
        role=role, server_version=version, ssl=ssl,
        superuser=attrs.rolsuper, bypass_rls=attrs.rolbypassrls, create_role=attrs.rolcreaterole,
        create_db=attrs.rolcreatedb, replication=attrs.rolreplication,
        owned=owned, truncate=having("TRUNCATE"), trigger=having("TRIGGER"),
        can_set_replication_role=can_set or attrs.rolsuper,
        create_on_schema=bool(q("SELECT has_schema_privilege(current_user, 'public', 'CREATE')").scalar()),
        missing=missing,
    )


def report(a: Assessment) -> int:
    yes = lambda v: "yes" if v else "no"  # noqa: E731
    print(f"Role: {a.role} (PostgreSQL {a.server_version // 10000})")
    print(f"  connection encrypted: {'unknown' if a.ssl is None else yes(a.ssl)}")
    print(f"  superuser: {yes(a.superuser)}")
    print(f"  owns guarded tables: {', '.join(a.owned) or 'none'}")
    print(f"  may set session_replication_role: {yes(a.can_set_replication_role)}")
    print(f"  TRUNCATE on guarded tables: {', '.join(a.truncate) or 'none'}")
    print(f"  missing privileges the API needs: {', '.join(a.missing) or 'none'}")
    for note in a.warnings:
        print(f"  warning: {note}")
    if a.unsafe:
        print("FAILED: this role can get around the database safeguards (" + "; ".join(a.unsafe) + "). "
              "Connect the API and the expiry job with a role that does not own the tables and has only "
              "SELECT, INSERT, UPDATE and DELETE on them; run migrations with the owner role.")
        return 1
    if a.missing:
        print("FAILED: this role is safe but lacks privileges the API needs. Grant them (see the runbook).")
        return 1
    print("OK: this role cannot disable the safeguards and has what the API and the expiry job need.")
    return 0


def main() -> int:
    from app.core.database import engine
    from app.scripts.safety import current_target

    print(f"Database: {current_target().label}")
    try:
        with engine.connect() as conn:
            conn.execute(text("SET TRANSACTION READ ONLY"))
            result = assess(conn)
            conn.rollback()
    except Exception as exc:  # noqa: BLE001 - reported, exit 2
        print(f"ERROR: the check could not run ({type(exc).__name__}).")
        return 2
    finally:
        engine.dispose()
    return report(result)


if __name__ == "__main__":
    sys.exit(main())
