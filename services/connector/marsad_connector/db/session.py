"""Engine and session construction for the edge database. Mirrors the core's, apart."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.orm import Session, sessionmaker

from marsad_connector.db.base import EDGE_SCHEMA

log = logging.getLogger("marsad.connector.db")


def attach_schema_for_sqlite(engine: sa.Engine, schema: str) -> None:
    """Give SQLite a namespace of the right name — see the core's session module."""
    if engine.dialect.name != "sqlite":
        return

    database = engine.url.database
    attached = (
        str(Path(database).with_suffix(f".{schema}.db"))
        if database and database != ":memory:" else ":memory:"
    )

    @event.listens_for(engine, "connect")
    def _attach(dbapi_connection, _record):  # pragma: no cover - driver callback
        dbapi_connection.execute(f"ATTACH DATABASE '{attached}' AS {schema}")


def build_engine(url: str, *, echo: bool = False) -> sa.Engine:
    engine = sa.create_engine(url, echo=echo, future=True, pool_pre_ping=True)
    attach_schema_for_sqlite(engine, EDGE_SCHEMA)

    # Cascades are the mechanism that stops quoted narrative outliving its incident,
    # and SQLite ignores foreign keys unless asked. Silently losing the cascade here
    # would leave provenance rows behind exactly where they matter most.
    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def _enforce_foreign_keys(dbapi_connection, _record):  # pragma: no cover
            dbapi_connection.execute("PRAGMA foreign_keys=ON")

    return engine


def build_sessionmaker(engine: sa.Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
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
    """Direct creation for tests and first local run. Alembic owns it otherwise."""
    from marsad_connector.db.base import EdgeBase

    if engine.dialect.name == "postgresql":
        with engine.begin() as connection:
            connection.execute(sa.schema.CreateSchema(EDGE_SCHEMA, if_not_exists=True))
    EdgeBase.metadata.create_all(engine)


__all__ = [
    "attach_schema_for_sqlite",
    "build_engine",
    "build_sessionmaker",
    "create_all",
    "session_scope",
]
