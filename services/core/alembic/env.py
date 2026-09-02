"""
Alembic environment for the CORE database.

Two details are load-bearing rather than boilerplate:

* `version_table_schema=CORE_SCHEMA` puts `alembic_version` inside the core schema.
  If the two sides were ever pointed at one database, their migration histories would
  otherwise collide in `public` and each would try to run the other's migrations.
  Keeping the bookkeeping table inside the schema it describes makes that impossible
  to do quietly.
* `include_schemas=True` with a filter, so autogenerate never proposes a migration
  that would create, drop or alter an EDGE table. Core's migrations must not be able
  to touch the institution's store even if the URL is wrong.
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

SERVICE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVICE_ROOT.parents[1]
sys.path[:0] = [str(SERVICE_ROOT), str(REPO_ROOT / "packages" / "contracts")]

from marsad_core.db import models  # noqa: F401  (import registers the tables)
from marsad_core.db.base import CORE_SCHEMA, CoreBase

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option(
    "sqlalchemy.url",
    os.environ.get("MARSAD_CORE_DATABASE_URL", "sqlite:///./core.db"),
)

target_metadata = CoreBase.metadata


def include_object(obj, name, type_, reflected, compare_to):
    """Core migrations touch core objects. Nothing else, ever."""
    if type_ == "table":
        return (obj.schema or CORE_SCHEMA) == CORE_SCHEMA
    return True


def _configure(**kwargs) -> None:
    context.configure(
        target_metadata=target_metadata,
        include_schemas=True,
        include_object=include_object,
        version_table_schema=CORE_SCHEMA,
        compare_type=True,
        **kwargs,
    )


def run_migrations_offline() -> None:
    _configure(url=config.get_main_option("sqlalchemy.url"), literal_binds=True,
               dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.", poolclass=pool.NullPool,
    )
    # SQLite has no schemas; attach one of the right name so the same
    # schema-qualified DDL runs on both backends. See db/session.py.
    from marsad_core.db.session import attach_schema_for_sqlite
    attach_schema_for_sqlite(connectable, CORE_SCHEMA)

    with connectable.connect() as connection:
        if connection.dialect.name == "postgresql":
            from sqlalchemy.schema import CreateSchema
            connection.execute(CreateSchema(CORE_SCHEMA, if_not_exists=True))
            connection.commit()
        _configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
