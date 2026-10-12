"""
The edge's database identity — separate from the core's, structurally.

This database holds plaintext: narrative, analyst notes, attacker-authored email
bodies, plaintext indicator values, and extraction provenance that quotes the
narrative verbatim. It is the single most sensitive store in the system and it must
never be reachable from the core.

The separation is the same three layers described in the core's `db/base.py`, read
from this side:

1. **Separate instance** — each institution's database runs on that institution's
   own edge network, unreachable from `core_net`.
2. **Separate schema** — `edge`, never `core`.
3. **Separate MetaData** — `EdgeBase.metadata` and `CoreBase.metadata` share no table.

If you ever find yourself adding an edge table to `CoreBase`, or pointing both sides
at one database "just for local development", stop: that configuration makes every
guarantee in this repository false at once, and nothing downstream would notice.
"""

from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase

#: Every edge table is qualified with this. Deliberately not the core's.
EDGE_SCHEMA = "edge"


class UtcDateTime(sa.TypeDecorator):
    """
    A timestamp that comes back as the instant that went in, on every backend.

    Mirrors the core's type rather than importing it — the two sides share the
    contracts package and nothing else. The failure it prevents is sharper here than
    at the core: `detected_at` starts every regulatory clock. SQLite dropped the offset
    and kept the wall-clock digits, so an incident detected at 08:30 UAE time came back
    as a zoneless 08:30, A4 read it as UTC, and the CBUAE deadline it computed was four
    hours LATE. Postgres was never affected, which is why only the fast path hid it.
    """

    impl = sa.DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class EdgeBase(DeclarativeBase):
    """Declarative base for the institution's own store. Never crosses anything."""

    metadata = sa.MetaData(
        schema=EDGE_SCHEMA,
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s",
            "pk": "pk_%(table_name)s",
        },
    )


__all__ = ["EDGE_SCHEMA", "EdgeBase", "UtcDateTime"]
