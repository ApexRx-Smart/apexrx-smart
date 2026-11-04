from sqlalchemy import BigInteger, DateTime, FetchedValue, Identity, text
from sqlalchemy.orm import DeclarativeBase, mapped_column


class Base(DeclarativeBase):
    # Several columns are written by database triggers (updated_by,
    # last_updated, created_by, responded_at, ...). eager_defaults makes the
    # ORM read them back with RETURNING on INSERT *and* UPDATE.
    __mapper_args__ = {"eager_defaults": True}


def identity_pk():
    """BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY"""
    return mapped_column(BigInteger, Identity(always=True), primary_key=True)


def created_at_column():
    return mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )


def server_timestamp_column():
    """A timestamp a trigger refreshes on UPDATE (updated_at / last_updated)."""
    return mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        server_onupdate=FetchedValue(),
    )
