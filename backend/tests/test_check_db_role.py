"""The read-only database role check (app/scripts/check_db_role.py), against
the local test database with temporary roles (created and dropped here)."""

import pytest
from sqlalchemy import text

from app.core.database import engine
from app.scripts import check_db_role as check

ROLE = "apexrx_role_check_test"


@pytest.fixture
def role():
    """A NOLOGIN role with exactly the API's privileges; tests may add or remove some."""
    with engine.begin() as conn:
        conn.execute(text(
            f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE}') "
            f"THEN CREATE ROLE {ROLE} NOLOGIN NOSUPERUSER; END IF; END $$"
        ))
        conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {ROLE}"))
        conn.execute(text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {ROLE}"))
        conn.execute(text(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {ROLE}"))
    yield ROLE
    with engine.begin() as conn:
        conn.execute(text(f"DROP OWNED BY {ROLE}"))
        conn.execute(text(f"DROP ROLE {ROLE}"))


def assess_as(role_name=None, grant=None):
    with engine.connect() as conn:
        if grant:
            with engine.begin() as admin:
                admin.execute(text(grant))
        conn.execute(text("SET TRANSACTION READ ONLY"))
        if role_name:
            conn.execute(text(f"SET LOCAL ROLE {role_name}"))
        result = check.assess(conn)
        conn.rollback()
    return result


def test_the_local_superuser_is_reported_unsafe():
    a = assess_as()
    assert a.superuser and a.can_set_replication_role
    assert any("superuser" in r for r in a.unsafe)
    assert check.report(a) == 1


def test_a_role_with_only_the_api_privileges_is_safe_and_sufficient(role, capsys):
    a = assess_as(role)
    assert a.role == role and not a.superuser and not a.owned
    assert not a.truncate and not a.can_set_replication_role and not a.missing
    assert a.unsafe == []
    assert check.report(a) == 0
    assert "OK:" in capsys.readouterr().out


def test_truncate_is_reported_unsafe(role):
    a = assess_as(role, grant=f"GRANT TRUNCATE ON reservation, stock TO {role}")
    assert set(a.truncate) == {"reservation", "stock"}
    assert any("TRUNCATE" in r for r in a.unsafe)
    assert check.report(a) == 1


def test_setting_session_replication_role_is_reported_unsafe(role):
    a = assess_as(role, grant=f"GRANT SET ON PARAMETER session_replication_role TO {role}")
    assert a.can_set_replication_role and any("session_replication_role" in r for r in a.unsafe)


def test_missing_privileges_fail_even_when_safe(role, capsys):
    a = assess_as(role, grant=f"REVOKE DELETE ON notification FROM {role}")
    assert a.unsafe == [] and a.missing == ["notification: DELETE"]
    assert check.report(a) == 1
    assert "lacks privileges" in capsys.readouterr().out


def test_the_command_is_read_only_and_exits_1_for_the_superuser(capsys):
    before = engine.connect()
    try:
        roles = before.execute(text("SELECT count(*) FROM pg_roles")).scalar()
    finally:
        before.close()
    assert check.main() == 1
    out = capsys.readouterr().out
    assert "Database:" in out and "FAILED" in out and "password" not in out.lower()
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM pg_roles")).scalar() == roles
