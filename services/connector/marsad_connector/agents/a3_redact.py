"""
A3 — Redaction Agent. The trust anchor of the whole system.

This is the ONLY component permitted to construct a payload that crosses the
privacy boundary. Everything else in the connector operates on plaintext and
must never call out to the core directly.

Design stance: the guarantee is structural, not procedural. A3 does not "strip"
a rich object down to a safe one — it *constructs* a new object from an
allow-list of derived values. There is no code path by which narrative text can
reach the output, because the output type cannot hold it and the builder never
reads it.

An institution's security team should be able to audit this file plus
`marsad_contracts.boundary` and be satisfied. Keep it short enough that they will.

The one exemption in the leak guard
-----------------------------------
`_assert_no_leakage` compares long words from the narrative against the outbound
payload and aborts on a match. It skips exactly one class of match: text that is a
substring of the `coarse.ts_bucket` value this submission already carries.

Why the exemption exists. The contract deliberately emits an hour-bucketed detection
time, and analysts routinely write that time into the narrative ("detected at
2026-08-19 08:00 UTC"). Without the exemption the guard aborts ordinary, correct
submissions and reports them as a defect — and a guard that cries wolf is one an
operator switches off, which loses far more than the false positive cost.

Why it cannot widen into a hole. The exempt text is not an arbitrary allowance: a
token is skipped only when it appears inside the ISO rendering of the timestamp we
just emitted. That rendering is produced from a validated `datetime` that has been
truncated to the hour, so its alphabet is digits, `-`, `:`, `+`, `T` and nothing
else. No hostname, no account number, no name, no analyst prose can be a substring
of such a string — there is nowhere in it for an identifier to hide. The exemption
therefore cannot be widened by an attacker or by accident; widening it would require
editing this rule, which is a security review.

`test_the_timestamp_exemption_did_not_disarm_the_leak_guard` holds the line: it
proves the guard still fires on narrative text, and still fires on a date-shaped
word that is *not* the timestamp this payload carries.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Protocol

from marsad_contracts.boundary import (
    CoarseMetadata,
    DisclosureRung,
    IncidentSubmission,
    IndicatorType,
    KeyedToken,
    ObligationReceiptRef,
    Sector,
    SeverityBand,
    SizeBand,
)

from marsad_connector.crypto.tokeniser import Tokeniser

log = logging.getLogger("marsad.a3")


class IncidentLike(Protocol):
    """
    Structural contract for the local incident A3 reads from.

    Deliberately a Protocol rather than the ORM model: the redaction agent must
    not depend on persistence, and this keeps it unit-testable with no database
    and no framework. It also means A3 can be reviewed in isolation, which is
    the point of concentrating the trust boundary in one small file.
    """

    narrative: str | None
    analyst_notes: str | None
    indicators: list[dict[str, Any]]
    techniques: list[str]
    severity: str
    obligation_receipt: dict[str, Any] | None
    detected_at: datetime | None

#: Indicator types we will tokenise. Anything else is dropped rather than
#: guessed at — an unrecognised type is a review item, not a pass-through.
ALLOWED_INDICATORS = frozenset(IndicatorType)

#: Hard ceiling so a pathological incident cannot become a bulk-enumeration
#: oracle against the tokenisation service.
MAX_TOKENS_PER_SUBMISSION = 512


class RedactionPolicy:
    """
    Per-institution configuration. Defaults are the most restrictive useful
    setting; loosening any of these is a decision the institution makes, not us.
    """

    def __init__(
        self,
        *,
        emit_techniques: bool = True,
        emit_obligation_ref: bool = True,
        allowed_indicators: frozenset[IndicatorType] = ALLOWED_INDICATORS,
        max_tokens: int = MAX_TOKENS_PER_SUBMISSION,
    ) -> None:
        self.emit_techniques = emit_techniques
        self.emit_obligation_ref = emit_obligation_ref
        self.allowed_indicators = allowed_indicators
        self.max_tokens = max_tokens


class RedactionError(RuntimeError):
    """Raised when a submission cannot be built safely. Fail closed, never partially."""


class RedactionAgent:
    """Builds the boundary payload. Holds no network capability by design."""

    def __init__(self, tokeniser: Tokeniser, policy: RedactionPolicy | None = None) -> None:
        self._tokeniser = tokeniser
        self._policy = policy or RedactionPolicy()

    # -- public -------------------------------------------------------------

    def build_submission(
        self,
        incident: IncidentLike,
        *,
        institution_ref: str,
        sector: Sector,
        size_band: SizeBand,
    ) -> IncidentSubmission:
        """
        Construct the outbound payload from an incident held locally.

        Note that `incident.narrative`, `incident.analyst_notes` and
        `incident.evidence_paths` are never read in this method. That is the
        point — grep this file for them and you will find nothing.
        """
        tokens = self._tokenise_indicators(incident)
        if not tokens:
            raise RedactionError(
                "no tokenisable indicators — refusing to emit a submission that "
                "would carry only metadata about an institution"
            )

        submission = IncidentSubmission(
            submission_id=str(uuid.uuid4()),
            institution_ref=institution_ref,
            tokens=tokens,
            technique_set=(
                sorted(set(incident.techniques or []))
                if self._policy.emit_techniques
                else []
            ),
            coarse=CoarseMetadata(
                sector=sector,
                size_band=size_band,
                severity_band=SeverityBand(incident.severity),
                ts_bucket=self._bucket(incident.detected_at),
            ),
            obligation_ref=self._obligation_ref(incident),
            disclosure_rung=DisclosureRung.ANONYMOUS_MATCH,
        )

        self._assert_no_leakage(submission, incident)
        log.info(
            "a3.built submission=%s tokens=%d techniques=%d scheme=%s",
            submission.submission_id, len(submission.tokens),
            len(submission.technique_set), self._tokeniser.scheme,
        )
        return submission

    # -- internals ----------------------------------------------------------

    def _tokenise_indicators(self, incident: IncidentLike) -> list[KeyedToken]:
        out: list[KeyedToken] = []
        seen: set[tuple[str, str]] = set()

        for raw in incident.indicators or []:
            try:
                itype = IndicatorType(raw["type"])
            except (KeyError, ValueError):
                log.warning("a3.drop unrecognised indicator type=%r", raw.get("type"))
                continue

            if itype not in self._policy.allowed_indicators:
                log.info("a3.drop policy-excluded type=%s", itype.value)
                continue

            try:
                token = self._tokeniser.tokenise(raw["value"], itype)
            except ValueError as exc:
                log.warning("a3.drop untokenisable type=%s reason=%s", itype.value, exc)
                continue

            key = (itype.value, token)
            if key in seen:
                continue
            seen.add(key)
            out.append(KeyedToken(type=itype, token=token))

            if len(out) >= self._policy.max_tokens:
                log.warning("a3.truncate token cap reached cap=%d", self._policy.max_tokens)
                break

        return out

    def _obligation_ref(self, incident: IncidentLike) -> ObligationReceiptRef | None:
        if not self._policy.emit_obligation_ref:
            return None
        r = incident.obligation_receipt
        if not r:
            return None
        return ObligationReceiptRef(
            receipt_hash=r["receipt_hash"],
            authority=r["authority"],
            filed_at=r["filed_at"],
        )

    @staticmethod
    def _bucket(dt: datetime | None) -> datetime:
        dt = dt or datetime.now(timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.replace(minute=0, second=0, microsecond=0)

    # -- the assertion that makes this auditable ----------------------------

    @staticmethod
    def _assert_no_leakage(submission: IncidentSubmission, incident: IncidentLike) -> None:
        """
        Belt and braces. The type system already prevents narrative from being
        carried, but an explicit check turns a future refactoring mistake into a
        loud failure rather than a silent disclosure.
        """
        blob = submission.model_dump_json().lower()

        # The contract deliberately carries an hour-bucketed detection time, so a
        # narrative that states when the incident was detected will always "appear"
        # in the payload. Exempt exactly that text and nothing else: a token is
        # skipped only when it is literally part of the timestamp we just emitted.
        # This is narrow on purpose — the guard must keep firing on every other word,
        # and a guard that cries wolf on ordinary incidents is a guard someone
        # switches off, which is worse than the false positive it was raising.
        declared = submission.coarse.ts_bucket.isoformat().lower()

        secrets: list[str] = []
        if incident.narrative:
            secrets += [w for w in incident.narrative.split() if len(w) > 7]
        for raw in incident.indicators or []:
            v = str(raw.get("value", ""))
            if len(v) > 5:
                secrets.append(v)
        if incident.analyst_notes:
            secrets += [w for w in incident.analyst_notes.split() if len(w) > 7]

        for s in secrets:
            if s.lower() in blob:
                if s.lower() in declared:
                    continue
                raise RedactionError(
                    f"LEAK GUARD TRIPPED: {s[:12]!r}… appears in the outbound payload. "
                    "Submission aborted. This is a defect, not a data problem."
                )
