"""Safety checks shared by the maintenance scripts (seed_demo, create_admin).

The target is read from the engine the script will really write through
(``app.core.database.engine``), not re-parsed from the environment, so the
check and the writes cannot disagree. Only the host and the database name are
ever shown; never the user, password or full URL.
"""

from dataclasses import dataclass

from sqlalchemy.engine import URL, make_url

# Loopback hosts. An empty host means a local Unix socket.
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", ""})
# Database names that look like a shared or production database.
PRODUCTION_NAMES = frozenset({"neondb"})
PRODUCTION_NAME_MARKERS = ("prod", "live")


@dataclass(frozen=True)
class DatabaseTarget:
    host: str
    database: str

    @property
    def label(self) -> str:
        return f"{self.host or 'localhost (socket)'}/{self.database}"

    @property
    def is_local_host(self) -> bool:
        return self.host.lower() in LOCAL_HOSTS

    @property
    def production_like(self) -> bool:
        name = self.database.lower()
        return name in PRODUCTION_NAMES or any(marker in name for marker in PRODUCTION_NAME_MARKERS)

    @property
    def is_safe_local(self) -> bool:
        """A loopback host with a database name that does not look like production."""
        return self.is_local_host and not self.production_like

    def reasons(self) -> list[str]:
        problems = []
        if not self.is_local_host:
            problems.append(f"host '{self.host}' is not a local (loopback) host")
        if self.production_like:
            problems.append(f"database name '{self.database}' looks like a production database")
        return problems


def inspect_target(url: str | URL) -> DatabaseTarget:
    parsed = url if isinstance(url, URL) else make_url(url)
    return DatabaseTarget(host=(parsed.host or ""), database=(parsed.database or ""))


def current_target() -> DatabaseTarget:
    """The database the scripts' SessionLocal writes to."""
    from app.core.database import engine

    return inspect_target(engine.url)


def confirm_host(target: DatabaseTarget, input_fn=input) -> bool:
    """Make the operator retype the exact host before touching a non-local database."""
    typed = input_fn(f"This is NOT a local database. Type the host exactly ({target.host}) to continue: ")
    return typed.strip() == target.host and bool(target.host)
