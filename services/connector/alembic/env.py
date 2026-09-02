"""
Alembic environment for the EDGE database.

Mirror of the core's, pointed the other way and kept separate on purpose. The same
two details are load-bearing: `alembic_version` lives inside the `edge` schema so the
two histories can never collide, and `include_object` refuses to touch anything
outside it, so an edge migration run against the wrong URL cannot alter core tables.
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

from marsad_connector.db import models  # noqa: F401  (registers the tables)
from marsad_connector.db.base import EDGE_SCHEMA, EdgeBase

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option(
    "sqlalchemy.url",
    os.environ.get("MARSAD_DATABASE_URL", "sqlite:///./connector.db"),
)

target_metadata = EdgeBase.metadata


def include_object(obj, name, type_, reflected, compare_to):
    """Edge migrations touch edge objects. Nothing else, ever."""
    if type_ == "table":
        return (obj.schema or EDGE_SCHEMA) == EDGE_SCHEMA
    return True


def _configure(**kwargs) -> None:
    context.configure(
        target_metadata=target_metadata,
        include_schemas=True,
        include_object=include_object,
        version_table_schema=EDGE_SCHEMA,
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
    from marsad_connector.db.session import attach_schema_for_sqlite
    attach_schema_for_sqlite(connectable, EDGE_SCHEMA)

    with connectable.connect() as connection:
        if connection.dialect.name == "postgresql":
            from sqlalchemy.schema import CreateSchema
            connection.execute(CreateSchema(EDGE_SCHEMA, if_not_exists=True))
            connection.commit()
        _configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
