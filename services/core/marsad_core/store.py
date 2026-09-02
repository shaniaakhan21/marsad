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
from marsad_contracts.boundary import IncidentSubmission
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

    def save_submission(self, submission: IncidentSubmission) -> None: ...
    def save_correlations(self, hits: list[CorrelationHit]) -> None: ...
    def all_submissions(self) -> list[IncidentSubmission]: ...
    def submission_count(self) -> int: ...
    def correlation_count(self) -> int: ...


class InMemoryStore:
    """The fast path. Same surface, dict behind it."""

    name = "memory"

    def __init__(self) -> None:
        self._submissions: dict[str, IncidentSubmission] = {}
        self._hits: list[CorrelationHit] = []

    def save_submission(self, submission: IncidentSubmission) -> None:
        self._submissions.setdefault(submission.submission_id, submission)

    def save_correlations(self, hits: list[CorrelationHit]) -> None:
        self._hits.extend(hits)

    def all_submissions(self) -> list[IncidentSubmission]:
        return list(self._submissions.values())

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

    def save_submission(self, submission: IncidentSubmission) -> None:
        with session_scope(self._factory) as session:
            exists = session.get(Submission, submission.submission_id)
            if exists is not None:
                log.info("store.duplicate submission=%s ignored", submission.submission_id)
                return

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
                tokens=[
                    SubmissionToken(indicator_type=_enum_value(kt.type), token=kt.token)
                    for kt in submission.tokens
                ],
            ))

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
                        for ref, sid in zip(hit.institution_refs, hit.submission_ids,
                                            strict=False)
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
