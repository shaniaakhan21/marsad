"""
Where the core keeps what it has been sent.

Two backends behind one protocol:

* `SqlStore` — Postgres in deployment, SQLite for the fast test path. The store of
  record: submissions and correlations survive a restart, and the canary sweep reads
  it directly.
* `InMemoryStore` — the same surface with a dict behind it. Kept deliberately, so the
  default test suite stays fast and so nothing in the correlation algorithm can start
  depending on a database being present.

An honest note on what "replace in-memory state with Postgres" means here. The
`CorrelationEngine` still holds an in-memory index of tokens for matching, because
matching is a set intersection and doing it in SQL per submission would be slower and
no more correct. That index is a **cache**: it is rebuilt from the database at
startup by `rehydrate`, and the database is the only thing that persists. Losing the
process loses nothing; losing the database loses everything.
"""

from __future__ import annotations

import logging
import uuid
from enum import Enum
from typing import Protocol

import sqlalchemy as sa
from marsad_contracts.boundary import CorrelationKind, IncidentSubmission, IndicatorType
from marsad_contracts.digest import payload_digest
from sqlalchemy.orm import Session, sessionmaker

from marsad_core.db.models import (
    Correlation,
    CorrelationMember,
    Submission,
    SubmissionToken,
)
from marsad_core.db.session import session_scope
from marsad_core.engines.correlation import CorrelationHit

log = logging.getLogger("marsad.core.store")


def _enum_value(value) -> str | None:
    """
    The plain value of an enum member, never its repr.

    `str()` on a `str`-mixin Enum returns "CorrelationKind.EXACT_TOKEN" on Python
    3.11+, not "EXACT_TOKEN". Writing that to the database stores a Python type name
    where a vocabulary term belongs, and it overflows the column. SQLite does not
    enforce VARCHAR length, so this failed only against Postgres — which is why
    `test_enum_columns_store_plain_values_not_python_reprs` asserts the value rather
    than the length, and catches it on either backend.
    """
    if value is None:
        return None
    return value.value if isinstance(value, Enum) else str(value)


class SubmissionStore(Protocol):
    """What the core needs of a store, and nothing more."""

    name: str

    def save_submission(self, submission: IncidentSubmission) -> str: ...
    def save_correlations(self, hits: list[CorrelationHit]) -> None: ...
    def all_submissions(self) -> list[IncidentSubmission]: ...
    def all_correlations(self) -> list[CorrelationHit]: ...
    def submission_count(self) -> int: ...
    def correlation_count(self) -> int: ...


class InMemoryStore:
    """The fast path. Same surface, dict behind it."""

    name = "memory"

    def __init__(self) -> None:
        self._submissions: dict[str, IncidentSubmission] = {}
        self._digests: dict[str, str] = {}
        self._hits: list[CorrelationHit] = []

    def save_submission(self, submission: IncidentSubmission) -> str:
        self._submissions.setdefault(submission.submission_id, submission)
        return self._digests.setdefault(submission.submission_id, payload_digest(submission))

    def save_correlations(self, hits: list[CorrelationHit]) -> None:
        self._hits.extend(hits)

    def all_submissions(self) -> list[IncidentSubmission]:
        return list(self._submissions.values())

    def all_correlations(self) -> list[CorrelationHit]:
        return list(self._hits)

    def submission_count(self) -> int:
        return len(self._submissions)

    def correlation_count(self) -> int:
        return len(self._hits)


class SqlStore:
    """
    The store of record.

    Writes are idempotent on `submission_id`, matching the correlation engine's own
    idempotence: a connector retrying after a network failure must not inflate a
    campaign's apparent size, and that must be true of the database as well as of the
    in-memory index.
    """

    name = "sql"

    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory

    def save_submission(self, submission: IncidentSubmission) -> str:
        """
        Store the payload and return the digest of what is now held under its id.

        On a duplicate that is the digest of the FIRST payload, not of the one that just
        arrived. A connector retrying the same payload gets back the digest it expects;
        one that reused an id for different content gets back a digest that does not
        match its own, which is the only honest answer — the core kept the original.
        """
        digest = payload_digest(submission)
        with session_scope(self._factory) as session:
            exists = session.get(Submission, submission.submission_id)
            if exists is not None:
                if exists.payload_digest and exists.payload_digest != digest:
                    log.warning("store.duplicate submission=%s differs from the stored "
                                "payload; the stored one is kept", submission.submission_id)
                else:
                    log.info("store.duplicate submission=%s ignored", submission.submission_id)
                return exists.payload_digest or digest

            obligation = submission.obligation_ref
            session.add(Submission(
                submission_id=submission.submission_id,
                schema_version=submission.schema_version,
                institution_ref=submission.institution_ref,
                technique_set=list(submission.technique_set),
                sector=_enum_value(submission.coarse.sector),
                size_band=_enum_value(submission.coarse.size_band),
                severity_band=_enum_value(submission.coarse.severity_band),
                ts_bucket=submission.coarse.ts_bucket,
                obligation_receipt_hash=obligation.receipt_hash if obligation else None,
                obligation_authority=obligation.authority if obligation else None,
                obligation_filed_at=obligation.filed_at if obligation else None,
                disclosure_rung=int(submission.disclosure_rung),
                payload_digest=digest,
                tokens=[
                    SubmissionToken(indicator_type=_enum_value(kt.type), token=kt.token)
                    for kt in submission.tokens
                ],
            ))
        return digest

    def save_correlations(self, hits: list[CorrelationHit]) -> None:
        if not hits:
            return
        with session_scope(self._factory) as session:
            for hit in hits:
                correlation_id = str(uuid.uuid4())
                session.add(Correlation(
                    correlation_id=correlation_id,
                    kind=_enum_value(hit.kind),
                    campaign_id=hit.campaign_id,
                    indicator_type=_enum_value(hit.indicator_type),
                    token=hit.token,
                    shared_techniques=list(hit.shared_techniques),
                    similarity=hit.similarity,
                    reduced_fidelity=hit.reduced_fidelity,
                    detected_at=hit.detected_at,
                    members=[
                        CorrelationMember(institution_ref=ref, submission_id=sid)
                        for ref, sid in hit.members
                    ],
                ))

    def all_submissions(self) -> list[IncidentSubmission]:
        """
        Rebuild boundary payloads from stored rows.

        Reconstructed through `IncidentSubmission` rather than handed back as ORM
        objects, so anything that fails the contract on the way out fails loudly here
        rather than reaching a caller that assumes it is valid.
        """
        with session_scope(self._factory) as session:
            rows = session.scalars(sa.select(Submission)).all()
            return [self._to_contract(row) for row in rows]

    def reconstruct(self, submission_id: str) -> tuple[IncidentSubmission, str | None] | None:
        """
        An auditor's view of one submission: the payload rebuilt from its rows, and the
        digest recorded when it arrived.

        If the rows still say what arrived, `payload_digest(rebuilt)` equals the
        recorded digest — and equals the digest in the institution's own record of
        what it sent. Any of the three disagreeing is a finding.
        """
        with session_scope(self._factory) as session:
            row = session.get(Submission, submission_id)
            if row is None:
                return None
            return self._to_contract(row), row.payload_digest

    def all_correlations(self) -> list[CorrelationHit]:
        """
        Every correlation found, oldest first, rebuilt from the store of record.

        The engine rebuilds its token index from submissions at startup, but that
        rebuild deliberately discards the hits it re-finds — they were already found and
        stored once. Without this, a restarted core would still match new submissions
        correctly and yet report that it had never found anything.
        """
        with session_scope(self._factory) as session:
            rows = session.scalars(
                sa.select(Correlation).order_by(Correlation.detected_at)
            ).all()
            return [
                CorrelationHit(
                    kind=CorrelationKind(row.kind),
                    institution_refs=tuple(sorted({m.institution_ref for m in row.members})),
                    submission_ids=tuple(sorted(m.submission_id for m in row.members)),
                    indicator_type=IndicatorType(row.indicator_type) if row.indicator_type else None,
                    token=row.token,
                    shared_techniques=tuple(row.shared_techniques or ()),
                    similarity=row.similarity,
                    reduced_fidelity=row.reduced_fidelity,
                    campaign_id=row.campaign_id,
                    detected_at=row.detected_at,
                    members=tuple(sorted((m.institution_ref, m.submission_id)
                                         for m in row.members)),
                )
                for row in rows
            ]

    @staticmethod
    def _to_contract(row: Submission) -> IncidentSubmission:
        payload = {
            "schema_version": row.schema_version,
            "submission_id": row.submission_id,
            "institution_ref": row.institution_ref,
            "tokens": [{"type": t.indicator_type, "token": t.token} for t in row.tokens],
            "technique_set": list(row.technique_set or []),
            "coarse": {
                "sector": row.sector,
                "size_band": row.size_band,
                "severity_band": row.severity_band,
                "ts_bucket": row.ts_bucket,
            },
            "disclosure_rung": row.disclosure_rung,
        }
        if row.obligation_receipt_hash:
            payload["obligation_ref"] = {
                "receipt_hash": row.obligation_receipt_hash,
                "authority": row.obligation_authority,
                "filed_at": row.obligation_filed_at,
            }
        return IncidentSubmission.model_validate(payload)

    def submission_count(self) -> int:
        with session_scope(self._factory) as session:
            return int(session.scalar(sa.select(sa.func.count()).select_from(Submission)) or 0)

    def correlation_count(self) -> int:
        with session_scope(self._factory) as session:
            return int(session.scalar(sa.select(sa.func.count()).select_from(Correlation)) or 0)


def rehydrate(engine, store: SubmissionStore) -> int:
    """
    Rebuild the correlation engine's in-memory index from the store of record.

    Called at startup. Without it a restarted core would find no matches against
    anything submitted before the restart, and would report that as "no correlation"
    — a silent false negative, which is the worst failure this system has.
    """
    submissions = store.all_submissions()
    for submission in submissions:
        engine.ingest(submission)
    log.info("store.rehydrated submissions=%d backend=%s", len(submissions), store.name)
    return len(submissions)


__all__ = ["InMemoryStore", "SqlStore", "SubmissionStore", "rehydrate"]
