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

The record of what left
-----------------------
A third kind of data, with the opposite lifetime. `OutboundSubmission` and
`SubmissionAttempt` are the institution's own record of every payload it sent to the
core and what happened each time. Nothing in them is plaintext — the payload is the
boundary contract exactly as it crossed — and they are **kept**, because "what did we
disclose, when, and on whose confirmation?" is the question an auditor or regulator
asks after the narrative has long expired. Both tables are append-only: nothing in
this codebase updates or deletes a row in either.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from marsad_connector.db.base import EDGE_SCHEMA, EdgeBase, UtcDateTime


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
    detected_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)

    #: Which perimeters this incident was filed under, and whether an essential service
    #: was hit. A4 reads both. Before these columns existed the SQL store dropped them
    #: on write, so A4 silently fell back to the institution's configured defaults — a
    #: firm that said "ADGM" was resolved as though it had not.
    jurisdictions: Mapped[list[str]] = mapped_column(sa.JSON, default=list)
    essential_service_affected: Mapped[bool | None] = mapped_column(sa.Boolean, default=None)
    submitted_submission_id: Mapped[str | None] = mapped_column(sa.String(64), default=None)

    # -- provenance of the incident itself ---------------------------------
    #: "ANALYST_STRUCTURED" or "EXTRACTION_CONFIRMED". There is deliberately no third
    #: value: unconfirmed extraction output never becomes an incident.
    source: Mapped[str] = mapped_column(sa.String(32), default="ANALYST_STRUCTURED")
    confirmed_by: Mapped[str | None] = mapped_column(sa.String(128), default=None)
    language: Mapped[str | None] = mapped_column(sa.String(16), default=None)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)

    #: When the free text above must be gone. Null means the policy was never applied,
    #: which `purge_expired` treats as "expire on the default window from creation"
    #: rather than "keep forever" — the safe direction for text nobody chose to keep.
    expires_at: Mapped[datetime | None] = mapped_column(
        UtcDateTime, index=True, default=None
    )
    #: Set when the free text has been purged, so a reader can tell "no narrative was
    #: written" from "the narrative expired". Silent nulls would look like a bug.
    redacted_at: Mapped[datetime | None] = mapped_column(
        UtcDateTime, default=None
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
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)

    incident: Mapped[LocalIncident] = relationship(back_populates="provenance")


class OutboundSubmission(EdgeBase):
    """
    One payload this institution sent, or is about to send, to the core.

    Written BEFORE the request leaves, so there is no moment at which something has
    crossed and no record of it exists. `payload` is the `IncidentSubmission` exactly
    as serialised on the wire; `payload_digest` is its canonical digest, the same one
    the core computes on receipt and returns (`marsad_contracts.digest`).

    `incident_id` is deliberately not a foreign key. An incident's free text expires
    and the incident itself may be deleted; the fact that the institution disclosed
    something about it must not be deletable along with it.
    """

    __tablename__ = "outbound_submissions"

    submission_id: Mapped[str] = mapped_column(sa.String(64), primary_key=True)
    incident_id: Mapped[str] = mapped_column(sa.String(64), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(sa.JSON)
    payload_digest: Mapped[str] = mapped_column(sa.String(64))

    #: Which tokeniser produced the tokens. Not in the payload, and exactly what an
    #: auditor needs once HMAC is replaced: which disclosures were made under the
    #: prototype scheme.
    tokeniser_scheme: Mapped[str] = mapped_column(sa.String(64))

    #: Who stood behind the incident when it was sent, copied rather than joined so the
    #: record does not change if the incident row does.
    incident_source: Mapped[str] = mapped_column(sa.String(32))
    confirmed_by: Mapped[str | None] = mapped_column(sa.String(128), default=None)
    built_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow, index=True)

    attempts: Mapped[list[SubmissionAttempt]] = relationship(
        back_populates="submission", lazy="selectin", order_by="SubmissionAttempt.id",
    )


class SubmissionAttempt(EdgeBase):
    """
    One attempt to deliver an `OutboundSubmission`, and what came back.

    `outcome` is ACCEPTED, QUEUED (the core could not be reached, or failed in a way
    that may have been after it stored the payload — resending the same payload is
    safe because the core is idempotent on `submission_id`) or REJECTED (the core
    refused it; nothing was stored, so it is never resent).
    """

    __tablename__ = "submission_attempts"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    submission_id: Mapped[str] = mapped_column(
        sa.ForeignKey(f"{EDGE_SCHEMA}.outbound_submissions.submission_id"), index=True,
    )
    attempted_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)
    outcome: Mapped[str] = mapped_column(sa.String(16))
    http_status: Mapped[int | None] = mapped_column(sa.Integer, default=None)

    #: The digest the core says it holds under this id. Equal to `payload_digest` on
    #: the submission, or the two sides disagree about what crossed.
    core_digest: Mapped[str | None] = mapped_column(sa.String(64), default=None)
    #: The core's reply — this institution's own rung-0 notices, nothing about peers
    #: beyond their count. Kept so a repeated submit can answer without resending.
    core_response: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, default=None)
    error: Mapped[str | None] = mapped_column(sa.String(500), default=None)

    submission: Mapped[OutboundSubmission] = relationship(back_populates="attempts")


def expiry_for(created_at: datetime, retention_days: int) -> datetime:
    """The one place a retention deadline is computed. Arithmetic, not judgement."""
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return created_at + timedelta(days=retention_days)


__all__ = [
    "ExtractionProvenance", "LocalIncident", "OutboundSubmission", "SubmissionAttempt",
    "expiry_for",
]
