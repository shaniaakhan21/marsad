"""
The institution's record of everything that left it.

Why this exists. Counsel's first question about MARSAD is "what exactly would we be
disclosing?", and `/preview` answers it before the fact. This module answers it after
the fact, for every submission ever made: the payload exactly as it crossed, when,
under which tokeniser, on whose confirmation, and what the core said it received.
The 90-day plan's day-30 evidence is "an auditor can reconstruct any submission";
this is where the auditor reads.

It is also the outbound queue, and the two are one mechanism on purpose. A payload is
recorded BEFORE it is sent, so:

* there is no moment at which something has crossed and no record of it exists;
* a core that is down leaves the payload QUEUED here rather than lost, and it
  survives a restart because it is in the institution's database, not in a process;
* a retry resends the RECORDED payload, never a rebuilt one. A3 mints a fresh
  `submission_id` on every build, so rebuilding to retry would hand the core a second
  submission for one incident — and a timeout does not tell us whether the first one
  arrived. Resending the same id is a no-op at the core if it did.

Kept apart from `store.py` because it holds a different class of data. The incident
store is plaintext and expires; this holds only boundary-contract payloads, which
contain nothing the core does not also hold, and it is kept. Append-only: rows are
added, never updated or deleted.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol

import sqlalchemy as sa
from marsad_contracts.boundary import IncidentSubmission
from marsad_contracts.digest import payload_digest
from sqlalchemy.orm import Session, sessionmaker

from marsad_connector.db.models import OutboundSubmission, SubmissionAttempt
from marsad_connector.db.session import session_scope

log = logging.getLogger("marsad.connector.outbound")

#: Longest error text kept on an attempt. Enough to diagnose; not a log archive.
MAX_ERROR_CHARS = 500


class Outcome(str, Enum):
    ACCEPTED = "ACCEPTED"   # the core stored it and said so
    QUEUED = "QUEUED"       # not known to have arrived; resent unchanged on retry
    REJECTED = "REJECTED"   # the core refused it, so it holds nothing; never resent
    REFUSED = "REFUSED"     # stopped here before sending — see RedactionAgent.restore


@dataclass(frozen=True)
class Attempt:
    attempted_at: datetime
    outcome: str
    http_status: int | None = None
    core_digest: str | None = None
    core_response: dict[str, Any] | None = None
    error: str | None = None


@dataclass(frozen=True)
class OutboundRecord:
    submission_id: str
    incident_id: str
    payload: dict[str, Any]
    payload_digest: str
    tokeniser_scheme: str
    incident_source: str
    confirmed_by: str | None
    built_at: datetime
    attempts: tuple[Attempt, ...] = field(default_factory=tuple)

    @property
    def status(self) -> str:
        """
        The last attempt's outcome, or QUEUED if there has been none.

        No attempt means the payload was recorded and the process stopped before or
        while sending it. It may or may not have arrived, which is exactly the case
        resending the same `submission_id` is safe for — so it is queued, not lost.
        """
        return self.attempts[-1].outcome if self.attempts else Outcome.QUEUED.value

    @property
    def digest_confirmed(self) -> bool:
        """True once the core has reported holding exactly this payload."""
        return any(a.outcome == Outcome.ACCEPTED.value and a.core_digest == self.payload_digest
                   for a in self.attempts)

    def last_accepted(self) -> Attempt | None:
        return next((a for a in reversed(self.attempts)
                     if a.outcome == Outcome.ACCEPTED.value), None)

    def as_dict(self) -> dict[str, Any]:
        return {
            "submission_id": self.submission_id,
            "incident_id": self.incident_id,
            "status": self.status,
            "payload": self.payload,
            "payload_digest": self.payload_digest,
            "digest_confirmed": self.digest_confirmed,
            "tokeniser_scheme": self.tokeniser_scheme,
            "incident_source": self.incident_source,
            "confirmed_by": self.confirmed_by,
            "built_at": self.built_at.isoformat(),
            "attempts": [
                {
                    "attempted_at": a.attempted_at.isoformat(),
                    "outcome": a.outcome,
                    "http_status": a.http_status,
                    "core_digest": a.core_digest,
                    "error": a.error,
                }
                for a in self.attempts
            ],
        }


class OutboundLog(Protocol):
    name: str

    def record(self, submission: IncidentSubmission, *, incident_id: str,
               tokeniser_scheme: str, incident_source: str,
               confirmed_by: str | None) -> OutboundRecord: ...
    def attempt(self, submission_id: str, *, outcome: Outcome, http_status: int | None = None,
                core_digest: str | None = None, core_response: dict[str, Any] | None = None,
                error: str | None = None) -> OutboundRecord: ...
    def get(self, submission_id: str) -> OutboundRecord | None: ...
    def for_incident(self, incident_id: str) -> list[OutboundRecord]: ...
    def queued(self) -> list[OutboundRecord]: ...
    def all(self) -> list[OutboundRecord]: ...


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clip(error: str | None) -> str | None:
    return error[:MAX_ERROR_CHARS] if error else None


class InMemoryOutboundLog:
    """The fast path. Same surface and the same append-only discipline."""

    name = "memory"

    def __init__(self) -> None:
        self._records: dict[str, OutboundRecord] = {}

    def record(self, submission, *, incident_id, tokeniser_scheme, incident_source,
               confirmed_by) -> OutboundRecord:
        rec = OutboundRecord(
            submission_id=submission.submission_id, incident_id=incident_id,
            payload=submission.model_dump(mode="json"),
            payload_digest=payload_digest(submission), tokeniser_scheme=tokeniser_scheme,
            incident_source=incident_source, confirmed_by=confirmed_by, built_at=_now(),
        )
        self._records[rec.submission_id] = rec
        return rec

    def attempt(self, submission_id, *, outcome, http_status=None, core_digest=None,
                core_response=None, error=None) -> OutboundRecord:
        rec = self._records[submission_id]
        rec = replace(rec, attempts=(*rec.attempts, Attempt(
            attempted_at=_now(), outcome=Outcome(outcome).value, http_status=http_status,
            core_digest=core_digest, core_response=core_response, error=_clip(error),
        )))
        self._records[submission_id] = rec
        return rec

    def get(self, submission_id):
        return self._records.get(submission_id)

    def for_incident(self, incident_id):
        return [r for r in self._records.values() if r.incident_id == incident_id]

    def queued(self):
        return [r for r in self._records.values() if r.status == Outcome.QUEUED.value]

    def all(self):
        return list(self._records.values())


class SqlOutboundLog:
    """The record of what left, in the institution's own database."""

    name = "sql"

    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory

    def record(self, submission, *, incident_id, tokeniser_scheme, incident_source,
               confirmed_by) -> OutboundRecord:
        with session_scope(self._factory) as session:
            row = OutboundSubmission(
                submission_id=submission.submission_id, incident_id=incident_id,
                payload=submission.model_dump(mode="json"),
                payload_digest=payload_digest(submission), tokeniser_scheme=tokeniser_scheme,
                incident_source=incident_source, confirmed_by=confirmed_by, built_at=_now(),
            )
            session.add(row)
            session.flush()
            return self._to_record(row)

    def attempt(self, submission_id, *, outcome, http_status=None, core_digest=None,
                core_response=None, error=None) -> OutboundRecord:
        with session_scope(self._factory) as session:
            session.add(SubmissionAttempt(
                submission_id=submission_id, attempted_at=_now(),
                outcome=Outcome(outcome).value, http_status=http_status,
                core_digest=core_digest, core_response=core_response, error=_clip(error),
            ))
        record = self.get(submission_id)
        if record is None:  # pragma: no cover - the foreign key makes this unreachable
            raise KeyError(submission_id)
        return record

    def get(self, submission_id):
        with session_scope(self._factory) as session:
            row = session.get(OutboundSubmission, submission_id)
            return self._to_record(row) if row is not None else None

    def for_incident(self, incident_id):
        return self._select(OutboundSubmission.incident_id == incident_id)

    def queued(self):
        latest = (
            sa.select(SubmissionAttempt.submission_id,
                      sa.func.max(SubmissionAttempt.id).label("last_id"))
            .group_by(SubmissionAttempt.submission_id)
            .subquery()
        )
        with session_scope(self._factory) as session:
            rows = session.scalars(
                sa.select(OutboundSubmission)
                .outerjoin(latest, latest.c.submission_id == OutboundSubmission.submission_id)
                .outerjoin(SubmissionAttempt, SubmissionAttempt.id == latest.c.last_id)
                .where(sa.or_(SubmissionAttempt.id.is_(None),
                              SubmissionAttempt.outcome == Outcome.QUEUED.value))
                .order_by(OutboundSubmission.built_at)
            ).all()
            return [self._to_record(row) for row in rows]

    def all(self):
        return self._select(sa.true())

    def _select(self, condition) -> list[OutboundRecord]:
        with session_scope(self._factory) as session:
            rows = session.scalars(
                sa.select(OutboundSubmission).where(condition)
                .order_by(OutboundSubmission.built_at)
            ).all()
            return [self._to_record(row) for row in rows]

    @staticmethod
    def _to_record(row: OutboundSubmission) -> OutboundRecord:
        return OutboundRecord(
            submission_id=row.submission_id, incident_id=row.incident_id,
            payload=dict(row.payload), payload_digest=row.payload_digest,
            tokeniser_scheme=row.tokeniser_scheme, incident_source=row.incident_source,
            confirmed_by=row.confirmed_by, built_at=row.built_at,
            attempts=tuple(
                Attempt(attempted_at=a.attempted_at, outcome=a.outcome,
                        http_status=a.http_status, core_digest=a.core_digest,
                        core_response=a.core_response, error=a.error)
                for a in row.attempts
            ),
        )


__all__ = [
    "Attempt", "InMemoryOutboundLog", "OutboundLog", "OutboundRecord", "Outcome",
    "SqlOutboundLog",
]
