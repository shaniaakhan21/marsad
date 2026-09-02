"""
The core's tables.

Read this file as the answer to "what does the operator actually hold?". Every column
below is a field the boundary contract already permits to cross
(`packages/contracts/marsad_contracts/boundary.py`). There is deliberately no column
for narrative, analyst notes, plaintext indicator values, service names, vendor names
or extraction provenance — not because we remember not to write them, but because
there is nowhere to put them.

`tests/test_canary.py` sweeps every table, every column and every row of this schema
for strings planted inside an institution, so the claim is checked rather than
asserted.
"""

from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from marsad_core.db.base import CORE_SCHEMA, CoreBase


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Submission(CoreBase):
    """One boundary payload, exactly as the contract defines it."""

    __tablename__ = "submissions"

    submission_id: Mapped[str] = mapped_column(sa.String(64), primary_key=True)
    schema_version: Mapped[str] = mapped_column(sa.String(8), default="1.0")

    #: Rotating pseudonym. Not a name, not a stable identifier.
    institution_ref: Mapped[str] = mapped_column(sa.String(64), index=True)

    #: ATT&CK technique identifiers. A closed vocabulary of public IDs.
    technique_set: Mapped[list] = mapped_column(sa.JSON, default=list)

    # -- coarse metadata; deliberately low resolution -----------------------
    sector: Mapped[str] = mapped_column(sa.String(16))
    size_band: Mapped[str] = mapped_column(sa.String(16))
    severity_band: Mapped[str] = mapped_column(sa.String(16))
    ts_bucket: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))

    # -- proof a firm resolved its duties, without saying which or what -----
    obligation_receipt_hash: Mapped[str | None] = mapped_column(sa.String(64), default=None)
    obligation_authority: Mapped[str | None] = mapped_column(sa.String(32), default=None)
    obligation_filed_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), default=None
    )

    disclosure_rung: Mapped[int] = mapped_column(sa.Integer, default=0)
    received_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=_utcnow)

    tokens: Mapped[list[SubmissionToken]] = relationship(
        back_populates="submission", cascade="all, delete-orphan", lazy="selectin",
    )


class SubmissionToken(CoreBase):
    """
    A keyed, non-invertible reference to an indicator.

    The core can compare these for equality and nothing else. With an OPRF it cannot
    enumerate candidates either; with today's HMAC it could if it held the key, which
    is why the key is not the core's to hold. See crypto/tokeniser.py.
    """

    __tablename__ = "submission_tokens"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    submission_id: Mapped[str] = mapped_column(
        sa.ForeignKey(f"{CORE_SCHEMA}.submissions.submission_id", ondelete="CASCADE"),
        index=True,
    )
    indicator_type: Mapped[str] = mapped_column(sa.String(16))
    token: Mapped[str] = mapped_column(sa.String(64), index=True)

    submission: Mapped[Submission] = relationship(back_populates="tokens")

    __table_args__ = (sa.Index("ix_submission_tokens_token_type", "token", "indicator_type"),)


class Correlation(CoreBase):
    """A match the core found. Derived entirely from the columns above."""

    __tablename__ = "correlations"

    correlation_id: Mapped[str] = mapped_column(sa.String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(sa.String(32))
    campaign_id: Mapped[str | None] = mapped_column(sa.String(64), index=True, default=None)
    indicator_type: Mapped[str | None] = mapped_column(sa.String(16), default=None)
    token: Mapped[str | None] = mapped_column(sa.String(64), default=None)
    shared_techniques: Mapped[list] = mapped_column(sa.JSON, default=list)
    similarity: Mapped[float | None] = mapped_column(sa.Float, default=None)

    #: Propagates from the similarity engine so no alert is trusted more than the
    #: method that produced it. See engines/similarity.py.
    reduced_fidelity: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    detected_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=_utcnow)

    members: Mapped[list[CorrelationMember]] = relationship(
        back_populates="correlation", cascade="all, delete-orphan", lazy="selectin",
    )


class CorrelationMember(CoreBase):
    """
    Which pseudonyms are party to a correlation.

    Stored so the core can send each party its own rung-0 notice. A notice reveals
    peer *count*, never peer identity — the identities live here and are not served.
    """

    __tablename__ = "correlation_members"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    correlation_id: Mapped[str] = mapped_column(
        sa.ForeignKey(f"{CORE_SCHEMA}.correlations.correlation_id", ondelete="CASCADE"),
        index=True,
    )
    institution_ref: Mapped[str] = mapped_column(sa.String(64), index=True)
    submission_id: Mapped[str] = mapped_column(sa.String(64))

    correlation: Mapped[Correlation] = relationship(back_populates="members")


__all__ = ["Correlation", "CorrelationMember", "Submission", "SubmissionToken"]
