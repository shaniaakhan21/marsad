"""
The core's database identity — separate from the edge's, structurally.

Three independent separations, each stated because each fails differently:

1. **Separate instances.** Core's database runs on `core_net`; each institution's
   runs on that institution's edge network. A core process has no route to an edge
   database at all — the same isolation `tests/test_network_boundary.py` proves for
   the services themselves.
2. **Separate schemas.** Core objects live in the `core` schema, edge objects in
   `edge`. Pointing core at an edge database would still not make an edge table
   addressable by a core session.
3. **Separate MetaData.** `CoreBase.metadata` does not contain an edge table, so the
   core ORM cannot name one even by accident.

Sharing one database between the two sides would quietly destroy the thesis: the edge
stores plaintext narrative and the core must have no path to reach it. That is why
this file exists at all rather than a single shared `Base`.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase

#: Every core table is qualified with this. Never parameterised away — a schema that
#: can be configured to match the edge's is not a separation.
CORE_SCHEMA = "core"


class CoreBase(DeclarativeBase):
    """
    Declarative base for everything the core stores.

    Nothing in this metadata can hold narrative, analyst notes, plaintext indicators
    or PII, because no such column is declared. That is the first line of defence and
    it is a property of the schema rather than of any code path: the store cannot
    express what must not cross.
    """

    metadata = sa.MetaData(
        schema=CORE_SCHEMA,
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s",
            "pk": "pk_%(table_name)s",
        },
    )


__all__ = ["CORE_SCHEMA", "CoreBase"]
