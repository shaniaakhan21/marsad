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
from datetime import datetime, timezone
from enum import Enum
from typing import Protocol

import sqlalchemy as sa
from marsad_contracts.boundary import (
    CorrelationKind,
    DependencyDeclaration,
    IncidentSubmission,
    IndicatorType,
    ProviderIncidentDeclaration,
)
from marsad_contracts.digest import payload_digest
from sqlalchemy.orm import Session, sessionmaker

from marsad_core.db.models import (
    Correlation,
    CorrelationMember,
    DeclarationSequence,
    DeclaredDependency,
    ProviderIncident,
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
    def replace_dependencies(self, declaration: DependencyDeclaration) -> bool: ...
    def dependency_rows(self) -> list[tuple[str, str, str]]: ...
    def tokens_declared_by(self, institution_ref: str) -> set[str]: ...
    def dependents_of(self, provider_token: str) -> int: ...
    def save_provider_incident(self, declaration: ProviderIncidentDeclaration) -> None: ...
    def provider_incidents_for(self, tokens: set[str],
                               since: datetime) -> list[ProviderIncidentDeclaration]: ...


class InMemoryStore:
    """The fast path. Same surface, dict behind it."""

    name = "memory"

    def __init__(self) -> None:
        self._submissions: dict[str, IncidentSubmission] = {}
        self._digests: dict[str, str] = {}
        self._hits: list[CorrelationHit] = []
        self._dependencies: dict[str, DependencyDeclaration] = {}
        self._provider_incidents: dict[str, tuple[ProviderIncidentDeclaration, datetime]] = {}

    def replace_dependencies(self, declaration: DependencyDeclaration) -> bool:
        held = self._dependencies.get(declaration.institution_ref)
        if held is not None and held.sequence >= declaration.sequence:
            return False
        self._dependencies[declaration.institution_ref] = declaration
        return True

    def dependency_rows(self) -> list[tuple[str, str, str]]:
        return [(ref, d.provider_token, str(d.substitutability))
                for ref, held in self._dependencies.items() for d in held.dependencies]

    def tokens_declared_by(self, institution_ref: str) -> set[str]:
        held = self._dependencies.get(institution_ref)
        return {d.provider_token for d in held.dependencies} if held else set()

    def dependents_of(self, provider_token: str) -> int:
        return sum(token == provider_token for _, token, _ in self.dependency_rows())

    def save_provider_incident(self, declaration: ProviderIncidentDeclaration) -> None:
        self._provider_incidents.setdefault(
            declaration.declaration_id, (declaration, datetime.now(timezone.utc)))

    def provider_incidents_for(self, tokens, since) -> list[ProviderIncidentDeclaration]:
        return [d for d, at in self._provider_incidents.values()
                if d.provider_token in tokens and at >= since]

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

    def replace_dependencies(self, declaration: DependencyDeclaration) -> bool:
        """The firm's whole list, atomically. False if a newer list is already held."""
        ref = declaration.institution_ref
        with session_scope(self._factory) as session:
            held = session.get(DeclarationSequence, ref)
            if held is not None and held.sequence >= declaration.sequence:
                return False
            session.execute(sa.delete(DeclaredDependency).where(
                DeclaredDependency.institution_ref == ref))
            session.merge(DeclarationSequence(institution_ref=ref, sequence=declaration.sequence))
            session.add_all(
                DeclaredDependency(institution_ref=ref, provider_token=d.provider_token,
                                   substitutability=_enum_value(d.substitutability),
                                   sequence=declaration.sequence)
                for d in declaration.dependencies
            )
        return True

    def dependency_rows(self) -> list[tuple[str, str, str]]:
        with session_scope(self._factory) as session:
            return [(r.institution_ref, r.provider_token, r.substitutability)
                    for r in session.scalars(sa.select(DeclaredDependency))]

    def tokens_declared_by(self, institution_ref: str) -> set[str]:
        with session_scope(self._factory) as session:
            return set(session.scalars(sa.select(DeclaredDependency.provider_token).where(
                DeclaredDependency.institution_ref == institution_ref)))

    def dependents_of(self, provider_token: str) -> int:
        with session_scope(self._factory) as session:
            return int(session.scalar(sa.select(sa.func.count()).select_from(DeclaredDependency)
                       .where(DeclaredDependency.provider_token == provider_token)) or 0)

    def save_provider_incident(self, declaration: ProviderIncidentDeclaration) -> None:
        with session_scope(self._factory) as session:
            if session.get(ProviderIncident, declaration.declaration_id) is None:
                session.add(ProviderIncident(
                    declaration_id=declaration.declaration_id,
                    institution_ref=declaration.institution_ref,
                    provider_token=declaration.provider_token,
                    severity_band=_enum_value(declaration.severity_band),
                    ts_bucket=declaration.ts_bucket,
                ))

    def provider_incidents_for(self, tokens, since) -> list[ProviderIncidentDeclaration]:
        if not tokens:
            return []
        with session_scope(self._factory) as session:
            rows = session.scalars(sa.select(ProviderIncident).where(
                ProviderIncident.provider_token.in_(tokens),
                ProviderIncident.received_at >= since,
            )).all()
            return [ProviderIncidentDeclaration(
                declaration_id=r.declaration_id, institution_ref=r.institution_ref,
                provider_token=r.provider_token, severity_band=r.severity_band,
                ts_bucket=r.ts_bucket,
            ) for r in rows]

    def save_correlations(self, hits: list[CorrelationHit]) -> None:
        if not hits:
            return
        with session_scope(self._factory) as session:
            for hit in hits:
                session.add(Correlation(
                    correlation_id=hit.correlation_id,
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
                    correlation_id=row.correlation_id,
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
