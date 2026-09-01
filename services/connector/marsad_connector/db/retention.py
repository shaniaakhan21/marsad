"""
Retention for the edge plaintext store.

The policy, in one sentence: free text expires after a configurable window, and
extraction provenance expires with it rather than after it.

Why provenance is the interesting half
--------------------------------------
`ExtractionProvenance.evidence` holds a verbatim slice of the narrative and
`span_start`/`span_end` point into it. A policy that cleared `local_incidents.narrative`
and stopped there would produce a database that looks purged and still holds the
analyst's words, scattered across a table whose name does not say "narrative". That is
worse than not purging at all, because someone would believe it was done.

So the purge does both, in one transaction, and the foreign key cascades. Two
independent mechanisms, because this is the kind of thing that must not depend on
remembering.

What is deliberately kept
-------------------------
Severity, techniques, indicator types, detection time and the obligation receipt.
These are what an institution needs to answer a regulator months later, and what A3
derives a submission from. They are structured, bounded, and none of them is free
text an analyst wrote.

Configuring it
--------------
`MARSAD_RETENTION_DAYS` (default 90). Set it to the shortest window the institution's
own policy allows; nothing in MARSAD needs the narrative after the incident is closed.
A row whose `expires_at` was never set is treated as expiring on the default window
from creation — the safe direction for text nobody made a decision about.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from sqlalchemy.orm import Session

from marsad_connector.db.models import ExtractionProvenance, LocalIncident

log = logging.getLogger("marsad.connector.retention")

#: Columns cleared when an incident's free text expires. Listed explicitly rather
#: than derived, so adding a new free-text column is a decision someone makes about
#: retention rather than an omission nobody notices.
FREE_TEXT_COLUMNS = ("narrative", "narrative_normalised", "analyst_notes", "raw_email")


@dataclass(frozen=True)
class PurgeResult:
    incidents_redacted: int
    provenance_rows_deleted: int
    cutoff: datetime

    def as_dict(self) -> dict:
        return {
            "incidents_redacted": self.incidents_redacted,
            "provenance_rows_deleted": self.provenance_rows_deleted,
            "cutoff": self.cutoff.isoformat(),
        }


def due_for_purge(session: Session, *, now: datetime, retention_days: int) -> list[LocalIncident]:
    """
    Incidents whose free text has expired.

    A null `expires_at` is not "keep forever": it is treated as the default window
    from creation. Free text that nobody made a retention decision about is exactly
    the text most likely to be forgotten.
    """
    fallback_cutoff = now - timedelta(days=retention_days)
    statement = sa.select(LocalIncident).where(
        sa.and_(
            sa.or_(
                LocalIncident.expires_at <= now,
                sa.and_(LocalIncident.expires_at.is_(None),
                        LocalIncident.created_at <= fallback_cutoff),
            ),
            LocalIncident.redacted_at.is_(None),
        )
    )
    return list(session.scalars(statement))


def purge_expired(session: Session, *, now: datetime | None = None,
                  retention_days: int = 90) -> PurgeResult:
    """
    Clear expired free text and every provenance row that quotes it.

    One transaction. Provenance is deleted BEFORE the narrative is cleared, so an
    interrupted purge can only ever leave the narrative without its provenance — never
    provenance without its narrative, which is the direction that would leave quoted
    text behind after the thing it quotes was declared gone.
    """
    now = now or datetime.now(timezone.utc)
    expired = due_for_purge(session, now=now, retention_days=retention_days)
    if not expired:
        return PurgeResult(0, 0, now)

    incident_ids = [incident.id for incident in expired]

    deleted = session.execute(
        sa.delete(ExtractionProvenance).where(
            ExtractionProvenance.incident_id.in_(incident_ids)
        )
    ).rowcount or 0

    for incident in expired:
        for column in FREE_TEXT_COLUMNS:
            setattr(incident, column, None)
        incident.redacted_at = now

    session.flush()
    log.info(
        "retention.purged incidents=%d provenance_rows=%d retention_days=%d",
        len(expired), deleted, retention_days,
    )
    return PurgeResult(len(expired), deleted, now)


def surviving_free_text(session: Session) -> list[tuple[str, str, str]]:
    """
    Every free-text value still stored, as (table, column, value).

    Used by the retention tests and available to an operator who wants to answer
    "what plaintext do we still hold?" without reading the schema. Provenance is
    included precisely because it is the half that gets forgotten.
    """
    found: list[tuple[str, str, str]] = []
    for incident in session.scalars(sa.select(LocalIncident)):
        for column in FREE_TEXT_COLUMNS:
            value = getattr(incident, column)
            if value:
                found.append(("local_incidents", column, value))
    for row in session.scalars(sa.select(ExtractionProvenance)):
        if row.evidence:
            found.append(("extraction_provenance", "evidence", row.evidence))
    return found


__all__ = [
    "FREE_TEXT_COLUMNS", "PurgeResult", "due_for_purge", "purge_expired",
    "surviving_free_text",
]
