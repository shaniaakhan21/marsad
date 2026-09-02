"""
Where the institution keeps its own incidents. Plaintext, and it stays here.

Same two-backend shape as the core's store, for the same reasons: `SqlStore` is the
store of record, `InMemoryStore` keeps the test suite fast and stops anything in the
agent layer quietly assuming a database.

The one thing this module does that the core's does not is write **extraction
provenance** — the per-field confidence, the quoted evidence and the span offsets A2
produced. That data quotes the narrative verbatim, so it is written with the incident
and expires with it. See `db/retention.py`.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Protocol

import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from marsad_connector.db.models import ExtractionProvenance, LocalIncident, expiry_for
from marsad_connector.db.session import session_scope

log = logging.getLogger("marsad.connector.store")


class EdgeStore(Protocol):
    name: str

    def save(self, incident_id: str, incident: Any,
             provenance: list[dict[str, Any]] | None = None) -> None: ...
    def get(self, incident_id: str) -> Any | None: ...
    def __contains__(self, incident_id: str) -> bool: ...
    def count(self) -> int: ...


class InMemoryStore:
    """The fast path. Provenance is held alongside, not discarded, so tests see it."""

    name = "memory"

    def __init__(self) -> None:
        self._incidents: dict[str, Any] = {}
        self._provenance: dict[str, list[dict[str, Any]]] = {}

    def save(self, incident_id, incident, provenance=None) -> None:
        self._incidents[incident_id] = incident
        self._provenance[incident_id] = list(provenance or [])

    def get(self, incident_id):
        return self._incidents.get(incident_id)

    def provenance_for(self, incident_id) -> list[dict[str, Any]]:
        return self._provenance.get(incident_id, [])

    def __contains__(self, incident_id) -> bool:
        return incident_id in self._incidents

    def count(self) -> int:
        return len(self._incidents)


class SqlStore:
    """
    The store of record for one institution.

    `retention_days` is applied at write time rather than only at purge time, so every
    row carries the deadline it was created under. Changing the policy later does not
    silently re-date text an institution already agreed to hold for a fixed window.
    """

    name = "sql"

    def __init__(self, factory: sessionmaker[Session], *, retention_days: int = 90,
                 model: type | None = None) -> None:
        self._factory = factory
        self._retention_days = retention_days
        #: The Pydantic type incidents are rebuilt into on read. Injected so this
        #: module does not import the FastAPI app and create a cycle.
        self._model = model

    def save(self, incident_id, incident, provenance=None) -> None:
        now = datetime.now(timezone.utc)
        with session_scope(self._factory) as session:
            row = LocalIncident(
                id=incident_id,
                narrative=getattr(incident, "narrative", None),
                narrative_normalised=getattr(incident, "narrative_normalised", None),
                analyst_notes=getattr(incident, "analyst_notes", None),
                raw_email=getattr(incident, "raw_email", None),
                indicators=list(getattr(incident, "indicators", []) or []),
                techniques=list(getattr(incident, "techniques", []) or []),
                severity=getattr(incident, "severity", "MEDIUM"),
                obligation_receipt=getattr(incident, "obligation_receipt", None),
                detected_at=getattr(incident, "detected_at", None) or now,
                source=getattr(incident, "source", "ANALYST_STRUCTURED"),
                confirmed_by=getattr(incident, "confirmed_by", None),
                language=getattr(incident, "language", None),
                created_at=now,
                expires_at=expiry_for(now, self._retention_days),
            )
            for entry in provenance or []:
                span = entry.get("span") or (None, None)
                row.provenance.append(ExtractionProvenance(
                    field_name=entry["name"],
                    value_json=entry.get("value"),
                    confidence=float(entry.get("confidence") or 0.0),
                    evidence=entry.get("evidence"),
                    span_start=span[0] if span else None,
                    span_end=span[1] if span else None,
                    needs_attention=bool(entry.get("needs_attention")),
                    edited=bool(entry.get("edited")),
                ))
            session.merge(row)

    def get(self, incident_id):
        with session_scope(self._factory) as session:
            row = session.get(LocalIncident, incident_id)
            if row is None:
                return None
            return self._model(
                narrative=row.narrative,
                analyst_notes=row.analyst_notes,
                indicators=list(row.indicators or []),
                techniques=list(row.techniques or []),
                severity=row.severity,
                obligation_receipt=row.obligation_receipt,
                detected_at=row.detected_at,
                raw_email=row.raw_email,
                source=row.source,
                confirmed_by=row.confirmed_by,
            ) if self._model else row

    def provenance_for(self, incident_id) -> list[dict[str, Any]]:
        with session_scope(self._factory) as session:
            rows = session.scalars(
                sa.select(ExtractionProvenance).where(
                    ExtractionProvenance.incident_id == incident_id)
            ).all()
            return [
                {"name": r.field_name, "value": r.value_json, "confidence": r.confidence,
                 "evidence": r.evidence, "span": (r.span_start, r.span_end)}
                for r in rows
            ]

    def __contains__(self, incident_id) -> bool:
        with session_scope(self._factory) as session:
            return session.get(LocalIncident, incident_id) is not None

    def count(self) -> int:
        with session_scope(self._factory) as session:
            return int(session.scalar(
                sa.select(sa.func.count()).select_from(LocalIncident)) or 0)


def provenance_from_draft(draft) -> list[dict[str, Any]]:
    """
    Flatten an ExtractionDraft's tracked fields into rows.

    Every one of these carries `evidence`, a verbatim slice of the narrative. That is
    why the provenance table is on the same retention clock as the narrative itself.
    """
    return [
        {"name": name, "value": field.value, "confidence": field.confidence,
         "evidence": field.evidence, "span": field.span,
         "needs_attention": field.needs_attention, "edited": field.edited}
        for name, field in draft.fields.items()
    ]


__all__ = ["EdgeStore", "InMemoryStore", "SqlStore", "provenance_from_draft"]
