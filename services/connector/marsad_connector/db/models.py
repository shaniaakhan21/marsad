"""
The institution's own store. Everything here is plaintext and none of it crosses.

A3 is the only bridge out of this data, and it builds from an allow-list rather than
reading these rows. See a3_redact.py.

Retention
---------
Two kinds of plaintext live here and they have different lifetimes on purpose:

* **Structural fields** — severity, techniques, indicator types, the obligation
  receipt — are what makes an incident useful to the institution months later, and
  they are what A3 derives a submission from. They are kept.
* **Narrative, analyst notes, the attacker's email body, the normalised copy, and
  every extraction provenance row** are free text. They are the reason this database
  is sensitive, and they expire.

The rule that matters: **provenance expires with the narrative, never after it.**
An `ExtractionProvenance.evidence` value is a verbatim slice of the narrative — it is
the narrative, in a different table. Expiring the narrative while leaving spans and
quoted evidence behind would delete the appearance of the data and keep the data.
`purge_expired` does both in one transaction, the foreign key cascades, and
`test_provenance_cannot_outlive_the_narrative_it_quotes` holds the line.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from marsad_connector.db.base import EDGE_SCHEMA, EdgeBase


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class LocalIncident(EdgeBase):
    """
    The full incident as the institution holds it. Never serialised outward.

    `indicators` is a list of {"type": IndicatorType value, "value": plaintext}.
    """

    __tablename__ = "local_incidents"

    id: Mapped[str] = mapped_column(sa.String(64), primary_key=True)

    # -- free text: expires ------------------------------------------------
    narrative: Mapped[str | None] = mapped_column(sa.Text, default=None)
    #: Arabic-normalised copy. Stored beside the raw text, never instead of it —
    #: the analyst is shown what they typed, matching runs on this. Expires together
    #: with the raw narrative, being the same words.
    narrative_normalised: Mapped[str | None] = mapped_column(sa.Text, default=None)
    analyst_notes: Mapped[str | None] = mapped_column(sa.Text, default=None)
    #: Attacker-authored. The hostile channel A14 inspects as data, never instruction.
    raw_email: Mapped[str | None] = mapped_column(sa.Text, default=None)

    # -- structural: kept --------------------------------------------------
    indicators: Mapped[list[dict[str, Any]]] = mapped_column(sa.JSON, default=list)
    techniques: Mapped[list[str]] = mapped_column(sa.JSON, default=list)
    severity: Mapped[str] = mapped_column(sa.String(16), default="MEDIUM")
    evidence_paths: Mapped[list[str]] = mapped_column(sa.JSON, default=list)
    obligation_receipt: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, default=None)
    detected_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=_utcnow)
    submitted_submission_id: Mapped[str | None] = mapped_column(sa.String(64), default=None)

    # -- provenance of the incident itself ---------------------------------
    #: "ANALYST_STRUCTURED" or "EXTRACTION_CONFIRMED". There is deliberately no third
    #: value: unconfirmed extraction output never becomes an incident.
    source: Mapped[str] = mapped_column(sa.String(32), default="ANALYST_STRUCTURED")
    confirmed_by: Mapped[str | None] = mapped_column(sa.String(128), default=None)
    language: Mapped[str | None] = mapped_column(sa.String(16), default=None)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=_utcnow)

    #: When the free text above must be gone. Null means the policy was never applied,
    #: which `purge_expired` treats as "expire on the default window from creation"
    #: rather than "keep forever" — the safe direction for text nobody chose to keep.
    expires_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), index=True, default=None
    )
    #: Set when the free text has been purged, so a reader can tell "no narrative was
    #: written" from "the narrative expired". Silent nulls would look like a bug.
    redacted_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), default=None
    )

    provenance: Mapped[list[ExtractionProvenance]] = relationship(
        back_populates="incident", cascade="all, delete-orphan", lazy="selectin",
    )


class ExtractionProvenance(EdgeBase):
    """
    What A2 proposed for one field, and the words it read to propose it.

    This table is narrative in a different shape. `evidence` is a verbatim slice of
    the incident's narrative and `span_start`/`span_end` index into it. Treat every
    row as being exactly as sensitive as the narrative itself, because it is.

    The `ondelete="CASCADE"` is load-bearing: deleting an incident must not be able to
    leave quoted narrative behind in a table nobody remembered to clear.
    """

    __tablename__ = "extraction_provenance"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    incident_id: Mapped[str] = mapped_column(
        sa.ForeignKey(f"{EDGE_SCHEMA}.local_incidents.id", ondelete="CASCADE"), index=True,
    )

    field_name: Mapped[str] = mapped_column(sa.String(64))
    value_json: Mapped[Any | None] = mapped_column(sa.JSON, default=None)
    confidence: Mapped[float] = mapped_column(sa.Float, default=0.0)

    #: Verbatim narrative. The whole reason this table expires.
    evidence: Mapped[str | None] = mapped_column(sa.Text, default=None)
    span_start: Mapped[int | None] = mapped_column(sa.Integer, default=None)
    span_end: Mapped[int | None] = mapped_column(sa.Integer, default=None)

    needs_attention: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    edited: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=_utcnow)

    incident: Mapped[LocalIncident] = relationship(back_populates="provenance")


def expiry_for(created_at: datetime, retention_days: int) -> datetime:
    """The one place a retention deadline is computed. Arithmetic, not judgement."""
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return created_at + timedelta(days=retention_days)


__all__ = ["ExtractionProvenance", "LocalIncident", "expiry_for"]
