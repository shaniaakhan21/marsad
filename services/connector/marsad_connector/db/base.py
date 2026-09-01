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

import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase

#: Every edge table is qualified with this. Deliberately not the core's.
EDGE_SCHEMA = "edge"


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


__all__ = ["EDGE_SCHEMA", "EdgeBase"]
