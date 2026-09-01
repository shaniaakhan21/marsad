"""
Connector-local persistence. Everything in this module is plaintext and MUST
NOT be referenced by any module that talks to the core. A3 is the only bridge.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, DateTime, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class LocalIncident(Base):
    """
    The full incident as the institution holds it. Never serialised outward.

    `indicators` is a list of {"type": IndicatorType value, "value": plaintext}.
    """

    __tablename__ = "local_incidents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    narrative: Mapped[str | None] = mapped_column(Text, default=None)
    #: Arabic-normalised copy of the narrative. Stored beside the raw text, never
    #: instead of it — the analyst is shown what they typed, matching runs on this.
    #: Both are plaintext and both stay inside the institution.
    narrative_normalised: Mapped[str | None] = mapped_column(Text, default=None)
    analyst_notes: Mapped[str | None] = mapped_column(Text, default=None)
    indicators: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    techniques: Mapped[list[str]] = mapped_column(JSON, default=list)
    severity: Mapped[str] = mapped_column(String(16), default="MEDIUM")
    evidence_paths: Mapped[list[str]] = mapped_column(JSON, default=list)
    obligation_receipt: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    submitted_submission_id: Mapped[str | None] = mapped_column(String(64), default=None)
