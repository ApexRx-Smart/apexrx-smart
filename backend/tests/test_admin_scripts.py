"""Safety of the maintenance scripts: seed_demo and create_admin.

The real target in tests is the local *_test database. "Remote" targets are
simulated by replacing safety.current_target; any write would still go to the
test database, and the tests assert that nothing is written at all.
"""

import pytest
from sqlalchemy import text

from app.core.database import engine
from app.core.security import verify_password
from app.scripts import create_admin, safety, seed_demo
from app.scripts.safety import DatabaseTarget, inspect_target
from tests.helpers import organization, user

NEON = DatabaseTarget(host="ep-example-123456-pooler.us-east-2.aws.neon.tech", database="neondb")
PASSWORD = "Str0ng-admin-password"


def _user_row(email):
    with engine.connect() as c:
        return c.execute(
            text(
                "SELECT user_id, is_platform_admin, is_active, password_hash FROM app_user WHERE email = :e"
            ),
            {"e": email},
        ).one_or_none()


def no_input(prompt=""):
    raise AssertionError(f"unexpected prompt: {prompt}")


def answers(*values):
    it = iter(values)
    return lambda prompt="": next(it)


@pytest.fixture(autouse=True)
def _no_env_password(monkeypatch):
    monkeypatch.delenv("APEXRX_ADMIN_PASSWORD", raising=False)


# ---------------------------------------------------------------------------
# Target classification
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("url", "safe"),
    [
        ("postgresql+psycopg://u:pw@localhost:5432/apexrx", True),
        ("postgresql+psycopg://u:pw@127.0.0.1/apexrx_v6_test", True),
        ("postgresql+psycopg://u:pw@[::1]/apexrx_dev", True),
        ("postgresql+psycopg://u:pw@/apexrx", True),  # local socket
        ("postgresql+psycopg://u:pw@ep-x.neon.tech/neondb?sslmode=require", False),
        ("postgresql+psycopg://u:pw@ep-x.neon.tech/apexrx_test", False),  # remote, even if *_test
        ("postgresql+psycopg://u:pw@db.internal/apexrx", False),
        ("postgresql+psycopg://u:pw@localhost/neondb", False),  # e.g. a tunnel to production
        ("postgresql+psycopg://u:pw@localhost/apexrx_prod", False),
        ("postgresql+psycopg://u:pw@localhost/live_db", False),
    ],
)
def test_target_classification(url, safe):
    target = inspect_target(url)
    assert target.is_safe_local is safe
    assert "pw" not in target.label and "u:" not in target.label


def test_tests_run_against_a_safe_local_target():
    assert safety.current_target().is_safe_local
    assert safety.current_target().database.endswith("_test")


# ---------------------------------------------------------------------------
# seed_demo
# ---------------------------------------------------------------------------
def test_seed_demo_runs_on_local_test_database(client, capsys):
    assert seed_demo.main([], input_fn=no_input) == 0
    row = _user_row("admin@apexrx.example.com")
    assert row is not None and row.is_platform_admin
    out = capsys.readouterr().out
    assert "Target database: localhost/" in out and "postgresql" not in out


@pytest.mark.parametrize(
    "target",
    [
        NEON,
        DatabaseTarget("localhost", "neondb"),
        DatabaseTarget("localhost", "apexrx_prod"),
        DatabaseTarget("10.0.0.12", "apexrx"),
    ],
)
def test_seed_demo_refuses_remote_or_production_by_default(monkeypatch, capsys, target):
    monkeypatch.setattr(safety, "current_target", lambda: target)
    monkeypatch.setattr(seed_demo, "_seed", lambda: pytest.fail("seed ran"))
    assert seed_demo.main([], input_fn=no_input) == 1
    out = capsys.readouterr().out
    assert f"Target database: {target.label}" in out and "Refusing by default" in out
    assert _user_row("admin@apexrx.example.com") is None


def test_seed_demo_override_requires_exact_host(monkeypatch, capsys):
    monkeypatch.setattr(safety, "current_target", lambda: NEON)
    monkeypatch.setattr(seed_demo, "_seed", lambda: pytest.fail("seed ran"))
    for typed in ["", "neondb", "ep-example", NEON.host.upper(), "yes"]:
        assert seed_demo.main(["--allow-remote-database"], input_fn=answers(typed)) == 1
    assert "Host did not match" in capsys.readouterr().out


def test_seed_demo_override_with_exact_host_proceeds(monkeypatch, capsys):
    monkeypatch.setattr(safety, "current_target", lambda: NEON)
    ran = []
    monkeypatch.setattr(seed_demo, "_seed", lambda: ran.append(True))
    assert seed_demo.main(["--allow-remote-database"], input_fn=answers(NEON.host)) == 0
    assert ran == [True]
    assert "PLATFORM ADMIN with the public password" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# create_admin: new accounts
# ---------------------------------------------------------------------------
def test_create_new_admin(client, capsys):
    rc = create_admin.main(
        ["--email", "New.Admin@Example.com", "--name", "New Admin"],
        input_fn=answers("yes"),
        getpass_fn=answers(PASSWORD, PASSWORD),
    )
    assert rc == 0
    row = _user_row("new.admin@example.com")
    assert row.is_platform_admin and row.is_active and verify_password(PASSWORD, row.password_hash)
    out = capsys.readouterr().out
    assert "No account exists" in out and PASSWORD not in out


def test_create_new_admin_with_yes_and_env_password(client, monkeypatch):
    monkeypatch.setenv("APEXRX_ADMIN_PASSWORD", PASSWORD)
    assert (
        create_admin.main(["--email", "env@example.com", "--yes"], input_fn=no_input, getpass_fn=no_input)
        == 0
    )
    assert _user_row("env@example.com").is_platform_admin


@pytest.mark.parametrize(
    ("passwords", "answer"),
    [((PASSWORD, "different-password"), "yes"), (("short", "short"), "yes"), ((PASSWORD, PASSWORD), "no")],
)
def test_create_new_admin_refusals_write_nothing(client, passwords, answer):
    rc = create_admin.main(
        ["--email", "nope@example.com"], input_fn=answers(answer), getpass_fn=answers(*passwords)
    )
    assert rc == 1
    assert _user_row("nope@example.com") is None


@pytest.mark.parametrize("flag", ["--promote-existing", "--reactivate"])
def test_flags_for_a_missing_account_are_refused(client, capsys, flag):
    rc = create_admin.main(["--email", "typo@example.com", flag], input_fn=no_input, getpass_fn=no_input)
    assert rc == 1 and _user_row("typo@example.com") is None
    assert "Check the email" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# create_admin: existing accounts
# ---------------------------------------------------------------------------
def test_existing_non_admin_needs_promote_flag(client, capsys):
    h = user(client, "owner@example.com", "Owner Person")
    organization(client, h, "pharmacy", "Kigali Health")
    before = _user_row("owner@example.com")

    assert (
        create_admin.main(["--email", "owner@example.com", "--yes"], input_fn=no_input, getpass_fn=no_input)
        == 1
    )
    out = capsys.readouterr().out
    assert "ALREADY EXISTS" in out and f"user_id:         {before.user_id}" in out
    assert "Owner Person" in out and "Kigali Health (pharmacy), owner" in out
    assert "--promote-existing" in out
    assert _user_row("owner@example.com") == before


def test_promote_existing_after_confirmation_keeps_password(client):
    user(client, "staff@example.com", "Staff Person")
    before = _user_row("staff@example.com")
    # Declined: unchanged.
    assert (
        create_admin.main(
            ["--email", "staff@example.com", "--promote-existing"],
            input_fn=answers("no"),
            getpass_fn=no_input,
        )
        == 1
    )
    assert _user_row("staff@example.com") == before
    # Confirmed: promoted; password untouched; no password prompt at all.
    assert (
        create_admin.main(
            ["--email", "staff@example.com", "--promote-existing"],
            input_fn=answers("yes"),
            getpass_fn=no_input,
        )
        == 0
    )
    after = _user_row("staff@example.com")
    assert after.is_platform_admin and after.password_hash == before.password_hash


def _deactivate(email):
    with engine.begin() as c:
        c.execute(text("UPDATE app_user SET is_active = false WHERE email = :e"), {"e": email})


def test_inactive_account_needs_reactivate_flag(client, capsys):
    user(client, "gone@example.com")
    _deactivate("gone@example.com")
    rc = create_admin.main(
        ["--email", "gone@example.com", "--promote-existing", "--yes"], input_fn=no_input, getpass_fn=no_input
    )
    assert rc == 1
    assert "--reactivate" in capsys.readouterr().out
    row = _user_row("gone@example.com")
    assert not row.is_platform_admin and not row.is_active

    rc = create_admin.main(
        ["--email", "gone@example.com", "--promote-existing", "--reactivate", "--yes"],
        input_fn=no_input,
        getpass_fn=no_input,
    )
    assert rc == 0
    row = _user_row("gone@example.com")
    assert row.is_platform_admin and row.is_active


def test_existing_active_admin_is_left_alone(client, capsys):
    user(client, "boss@example.com")
    with engine.begin() as c:
        c.execute(text("UPDATE app_user SET is_platform_admin = true WHERE email = 'boss@example.com'"))
    before = _user_row("boss@example.com")
    assert create_admin.main(["--email", "boss@example.com"], input_fn=no_input, getpass_fn=no_input) == 0
    assert "already an active platform admin" in capsys.readouterr().out
    assert _user_row("boss@example.com") == before


def test_inactive_admin_needs_reactivate(client):
    user(client, "old-admin@example.com")
    with engine.begin() as c:
        c.execute(
            text(
                "UPDATE app_user SET is_platform_admin = true, is_active = false "
                "WHERE email = 'old-admin@example.com'"
            )
        )
    assert (
        create_admin.main(
            ["--email", "old-admin@example.com", "--yes"], input_fn=no_input, getpass_fn=no_input
        )
        == 1
    )
    assert not _user_row("old-admin@example.com").is_active
    assert (
        create_admin.main(
            ["--email", "old-admin@example.com", "--reactivate", "--yes"],
            input_fn=no_input,
            getpass_fn=no_input,
        )
        == 0
    )
    assert _user_row("old-admin@example.com").is_active


# ---------------------------------------------------------------------------
# create_admin: non-local targets
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("typed", ["", "yes", "neondb", "ep-example", NEON.host + " x"])
def test_non_local_target_needs_exact_host_even_with_yes(client, monkeypatch, typed):
    monkeypatch.setattr(safety, "current_target", lambda: NEON)
    monkeypatch.setenv("APEXRX_ADMIN_PASSWORD", PASSWORD)
    rc = create_admin.main(
        ["--email", "remote@example.com", "--yes"], input_fn=answers(typed), getpass_fn=no_input
    )
    assert rc == 1
    assert _user_row("remote@example.com") is None


def test_non_local_target_with_exact_host_proceeds(client, monkeypatch, capsys):
    monkeypatch.setattr(safety, "current_target", lambda: NEON)
    rc = create_admin.main(
        ["--email", "remote@example.com"],
        input_fn=answers(NEON.host, "yes"),
        getpass_fn=answers(PASSWORD, PASSWORD),
    )
    assert rc == 0
    assert _user_row("remote@example.com").is_platform_admin
    out = capsys.readouterr().out
    assert f"Target database: {NEON.label}" in out and "postgresql" not in out


def test_invalid_email_is_refused(client):
    assert create_admin.main(["--email", "not-an-email"], input_fn=no_input, getpass_fn=no_input) == 1
