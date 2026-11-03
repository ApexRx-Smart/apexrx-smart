"""Engine, session factory and the transaction-actor hook.

The v6 schema's triggers require every transaction that writes stock,
product_offer or purchase orders to identify the authenticated user via
``set_config('app.user_id', <user_id>, true)``. The setting is transaction
local, so it has to be re-applied at the start of *every* transaction.

``set_session_actor`` records the user on the session; the ``after_begin``
listener below then stamps it onto each new transaction automatically, so
route code never has to remember to do it (and a commit followed by more
writes on the same session stays attributed correctly).
"""

from collections.abc import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

ACTOR_KEY = "actor_user_id"

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)


def _apply_actor(session: Session, connection) -> None:
    actor_id = session.info.get(ACTOR_KEY)
    if actor_id is not None:
        connection.execute(
            text("SELECT set_config('app.user_id', :actor, true)"),
            {"actor": str(int(actor_id))},
        )


@event.listens_for(Session, "after_begin")
def _set_actor_on_begin(session: Session, transaction, connection) -> None:
    _apply_actor(session, connection)


def set_session_actor(session: Session, user_id: int) -> None:
    """Attribute all writes made through ``session`` to ``user_id``."""
    session.info[ACTOR_KEY] = int(user_id)
    # If a transaction is already open (e.g. the user lookup during
    # authentication), stamp it now as well.
    if session.in_transaction():
        _apply_actor(session, session.connection())


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as db:
        yield db
