"""
Engine and session construction for the core database.

One thing here is worth reading closely: `attach_schema_for_sqlite`. Postgres has
schemas natively; SQLite does not, and without help a schema-qualified model simply
fails to create. Attaching a database under the schema's name makes SQLite behave the
same way, which means the fast test path exercises the SAME schema-qualified SQL as
production instead of a schema-less variant that would hide a whole class of bug.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.orm import Session, sessionmaker

from marsad_core.db.base import CORE_SCHEMA

log = logging.getLogger("marsad.core.db")


def attach_schema_for_sqlite(engine: sa.Engine, schema: str) -> None:
    """
    Give SQLite a namespace of the right name, so `core.submissions` resolves.

    A file-backed engine attaches a sibling file; an in-memory one attaches another
    in-memory database. Either way the schema qualification is real, and a query that
    would fail against Postgres fails here too.
    """
    if engine.dialect.name != "sqlite":
        return

    database = engine.url.database
    if database and database != ":memory:":
        attached = str(Path(database).with_suffix(f".{schema}.db"))
    else:
        attached = ":memory:"

    @event.listens_for(engine, "connect")
    def _attach(dbapi_connection, _record):  # pragma: no cover - driver callback
        dbapi_connection.execute(f"ATTACH DATABASE '{attached}' AS {schema}")


def build_engine(url: str, *, echo: bool = False) -> sa.Engine:
    """
    Construct the core engine.

    `pool_pre_ping` because a connector retrying a submission against a core whose
    database connection has gone stale should get a working request, not a 500 — the
    core is additive, and a flaky core must never look like a failure of the
    institution's own incident response.
    """
    engine = sa.create_engine(url, echo=echo, future=True, pool_pre_ping=True)
    attach_schema_for_sqlite(engine, CORE_SCHEMA)
    return engine


def build_sessionmaker(engine: sa.Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Commit on success, roll back on failure. No half-written correlations."""
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def create_all(engine: sa.Engine) -> None:
    """
    Create the schema directly, for tests and for a first local run.

    Alembic owns the schema in every other context — `make migrate`. This exists so
    the fast test path does not need a migration run per test.
    """
    from marsad_core.db.base import CoreBase

    if engine.dialect.name == "postgresql":
        with engine.begin() as connection:
            connection.execute(sa.schema.CreateSchema(CORE_SCHEMA, if_not_exists=True))
    CoreBase.metadata.create_all(engine)


__all__ = [
    "attach_schema_for_sqlite",
    "build_engine",
    "build_sessionmaker",
    "create_all",
    "session_scope",
]
