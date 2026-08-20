"""
A4 — Obligation Resolver. EDGE agent. Runs inside the institution.

The adoption wedge. This agent delivers value to a single firm with **zero
sharing**, which is why the 90-day plan puts it at day 14 rather than waiting for
legal sign-off on the token boundary. A firm can install the connector, use this,
and never submit anything to the core.

The problem it solves
---------------------
A UAE financial institution can sit inside several regulatory perimeters at once.
The same incident can trigger notification duties on different clocks:

  * ADGM FSRA          — 24 hours
  * DIFC / DFSA        — 72 hours
  * TDRA               — on disruption of an essential service
  * CBUAE              — for licensed banks and finance companies
  * CMA (ex-SCA)       — for licensed capital-market firms and listed entities

Today a compliance officer reconciles these by hand, under time pressure, during
an incident. Deadlines are missed not through negligence but through arithmetic
performed at 3am.

Design rules, and why
---------------------
**Deterministic. No language model touches a deadline.** A missed regulatory
deadline is legal exposure. Every deadline here is `detected_at + timedelta`,
computed in code and reproducible by hand. The system design states this as a
hard rule: an LLM may explain a number, it may never produce one.

**Drafts, never files.** The agent produces notification drafts and a checklist.
The institution files. Nothing here has network capability.

**No materiality bright line exists, so the agent does not invent one.** UAE
rules do not give a numeric materiality threshold. Where applicability depends on
a judgement — is this an "essential service"? is this "material"? — the agent
presents the question with the rule text and marks the obligation
`REQUIRES_JUDGEMENT` rather than silently deciding. A tool that guesses here
would be worse than no tool, because it would look authoritative.

**Conservative on ambiguity.** If a jurisdiction is plausibly in scope, it is
included and flagged. Over-notifying is a nuisance; under-notifying is a breach.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum

from marsad_connector.agents.base import Agent, Autonomy


class Authority(str, Enum):
    ADGM_FSRA = "ADGM_FSRA"
    DFSA = "DFSA"
    TDRA = "TDRA"
    CBUAE = "CBUAE"
    CMA = "CMA"


class Applicability(str, Enum):
    REQUIRED = "REQUIRED"                    # in scope on the stated facts
    REQUIRES_JUDGEMENT = "REQUIRES_JUDGEMENT"  # in scope only on a human call
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True)
class AuthorityRule:
    """
    One notification duty.

    `citation` names the instrument rather than quoting it: rule text changes,
    and a stale quotation in a compliance tool is a liability. The corpus version
    is carried on the output so a reviewer knows what the resolver was reading.
    """

    authority: Authority
    label: str
    hours: int | None                      # None = trigger-based, not clock-based
    trigger: str
    citation: str
    applies_when: str
    judgement_required: bool = False


#: The regulatory corpus, versioned. In production this is RAG over the live
#: rulebooks with mandatory citations; here it is a pinned table, which is the
#: correct prototype choice — a wrong deadline is worse than a missing feature.
CORPUS_VERSION = "2026-08-19.1"

RULES: tuple[AuthorityRule, ...] = (
    AuthorityRule(
        authority=Authority.ADGM_FSRA,
        label="ADGM Financial Services Regulatory Authority",
        hours=24,
        trigger="detection of the incident",
        citation="ADGM FSRA rulebook — notification of material cyber/technology incidents",
        applies_when="the institution holds an ADGM licence or operates a branch in ADGM",
    ),
    AuthorityRule(
        authority=Authority.DFSA,
        label="Dubai Financial Services Authority (DIFC)",
        hours=72,
        trigger="detection of the incident",
        citation="DFSA rulebook — GEN notification obligations for technology incidents",
        applies_when="the institution holds a DFSA licence or operates in the DIFC",
    ),
    AuthorityRule(
        authority=Authority.TDRA,
        label="Telecommunications and Digital Government Regulatory Authority",
        hours=None,
        trigger="disruption of an essential service",
        citation="TDRA / UAE Information Assurance framework — essential-service incident notification",
        applies_when="the incident disrupts a service designated essential",
        judgement_required=True,
    ),
    AuthorityRule(
        authority=Authority.CBUAE,
        label="Central Bank of the UAE",
        hours=24,
        trigger="detection of the incident",
        citation="CBUAE supervisory expectations on cyber-risk incident notification",
        applies_when="the institution is CBUAE-licensed (bank, finance company, exchange house, payment provider)",
    ),
    AuthorityRule(
        authority=Authority.CMA,
        label="UAE Capital Market Authority (formerly SCA)",
        hours=48,
        trigger="detection of the incident",
        citation="SCA/CMA circulars on operational and cyber incident reporting by licensed persons",
        applies_when="the institution is CMA-licensed, or is a listed entity with a disclosure duty",
    ),
)

RULES_BY_AUTHORITY = {r.authority: r for r in RULES}

#: Below this severity band an incident is logged locally and no authority is
#: notified. Named and exposed so a compliance officer can see and change it,
#: rather than discovering it inside a function.
NOTIFY_AT_OR_ABOVE = ("MEDIUM", "HIGH", "CRITICAL")


@dataclass
class Obligation:
    authority: str
    label: str
    applicability: str
    deadline: str | None
    hours_allowed: int | None
    hours_remaining: float | None
    trigger: str
    citation: str
    reasoning: str
    draft_notification: str
    breached: bool = False

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class ObligationResult:
    incident_severity: str
    detected_at: str
    corpus_version: str
    notification_required: bool
    obligations: list[Obligation] = field(default_factory=list)
    earliest_deadline: str | None = None
    receipt_hash: str | None = None
    judgement_calls: list[str] = field(default_factory=list)
    note: str = ""

    def as_dict(self) -> dict:
        d = asdict(self)
        d["obligations"] = [o.as_dict() for o in self.obligations]
        return d


def _draft(rule: AuthorityRule, incident_ref: str, severity: str, detected: datetime,
           deadline: datetime | None) -> str:
    """
    A filing-ready notification skeleton.

    Deliberately factual and short. It carries no narrative detail the firm has
    not already chosen to include, and no speculation about attribution — an
    early notification that speculates is a document the firm has to retract.
    """
    when = (
        deadline.strftime("%Y-%m-%d %H:%M UTC") if deadline
        else "on determination of essential-service impact"
    )
    window = (
        f"Notification window: {rule.hours} hours from {rule.trigger}."
        if rule.hours else f"Trigger: {rule.trigger}."
    )
    return (
        f"To: {rule.label}\n"
        f"Subject: Notification of a cyber/technology incident — reference {incident_ref}\n\n"
        f"We notify you of a cyber security incident detected at "
        f"{detected.strftime('%Y-%m-%d %H:%M UTC')}, assessed at severity {severity}.\n\n"
        f"This notification is made under: {rule.citation}.\n"
        f"{window}\n"
        f"Filing due: {when}.\n\n"
        f"Incident classification, affected services and containment status are set out in the "
        f"attached structured report. Investigation is ongoing; this notification is made within "
        f"the required window and will be supplemented as facts are confirmed.\n\n"
        f"[Institution name] — [authorised signatory] — [contact]\n"
    )


def resolve(
    *,
    severity: str,
    detected_at: datetime,
    jurisdictions: list[str],
    essential_service_affected: bool | None = None,
    incident_ref: str = "PENDING",
    now: datetime | None = None,
) -> ObligationResult:
    """
    Resolve every notification duty for one incident.

    `essential_service_affected=None` means the institution has not yet made that
    call — the TDRA duty is then reported as REQUIRES_JUDGEMENT with the question
    stated, rather than resolved either way.

    `now` is injected rather than read from the clock so the result is testable
    and so a compliance officer can ask "where did I stand at 04:00?".
    """
    now = now or datetime.now(timezone.utc)
    if detected_at.tzinfo is None:
        detected_at = detected_at.replace(tzinfo=timezone.utc)

    severity = severity.upper()
    required = severity in NOTIFY_AT_OR_ABOVE
    held = {j.upper() for j in jurisdictions}

    obligations: list[Obligation] = []
    judgement_calls: list[str] = []

    for rule in RULES:
        applies = rule.authority.value in held

        # TDRA is trigger-based rather than licence-based: it can bind a firm
        # that holds no TDRA relationship, if the disrupted service is essential.
        if rule.authority is Authority.TDRA:
            if essential_service_affected is True:
                applicability = Applicability.REQUIRED
                reasoning = "The institution has determined an essential service was disrupted."
            elif essential_service_affected is False:
                applicability = Applicability.NOT_APPLICABLE
                reasoning = "The institution has determined no essential service was disrupted."
            else:
                applicability = Applicability.REQUIRES_JUDGEMENT
                reasoning = (
                    "Essential-service impact has not been determined. This is a judgement for "
                    "the institution, not for this system — no numeric threshold exists in the "
                    "rules to decide it automatically."
                )
                judgement_calls.append(
                    "Was a service designated essential disrupted? Determines the TDRA duty."
                )
        elif not applies:
            applicability = Applicability.NOT_APPLICABLE
            reasoning = f"Out of scope: {rule.applies_when}."
        elif not required:
            applicability = Applicability.NOT_APPLICABLE
            reasoning = (
                f"Severity {severity} is below the notification floor "
                f"({'/'.join(NOTIFY_AT_OR_ABOVE)}); logged locally only."
            )
        else:
            applicability = Applicability.REQUIRED
            reasoning = f"In scope: {rule.applies_when}."

        deadline = None
        hours_remaining = None
        breached = False
        if applicability in (Applicability.REQUIRED, Applicability.REQUIRES_JUDGEMENT) and rule.hours:
            deadline = detected_at + timedelta(hours=rule.hours)
            hours_remaining = round((deadline - now).total_seconds() / 3600, 2)
            breached = hours_remaining < 0

        obligations.append(
            Obligation(
                authority=rule.authority.value,
                label=rule.label,
                applicability=applicability.value,
                deadline=deadline.isoformat() if deadline else None,
                hours_allowed=rule.hours,
                hours_remaining=hours_remaining,
                trigger=rule.trigger,
                citation=rule.citation,
                reasoning=reasoning,
                draft_notification=(
                    _draft(rule, incident_ref, severity, detected_at, deadline)
                    if applicability is not Applicability.NOT_APPLICABLE else ""
                ),
                breached=breached,
            )
        )

    live = [o for o in obligations if o.applicability != Applicability.NOT_APPLICABLE.value]
    dated = [o for o in live if o.deadline]
    earliest = min((o.deadline for o in dated), default=None)

    # Sort so what is urgent is first: breached, then soonest, then judgement calls.
    obligations.sort(
        key=lambda o: (
            o.applicability == Applicability.NOT_APPLICABLE.value,
            o.hours_remaining if o.hours_remaining is not None else 1e6,
        )
    )

    result = ObligationResult(
        incident_severity=severity,
        detected_at=detected_at.isoformat(),
        corpus_version=CORPUS_VERSION,
        notification_required=bool(live) and required,
        obligations=obligations,
        earliest_deadline=earliest,
        judgement_calls=judgement_calls,
        note=(
            f"One report, checked against {len({o.authority for o in live})} regulator(s) at "
            f"once, with {len(live)} deadline(s) that apply."
        ),
    )
    result.receipt_hash = receipt_hash(result)
    return result


def receipt_hash(result: ObligationResult) -> str:
    """
    A hash of the resolved obligation set.

    This is the only artefact of A4 that may cross the privacy boundary — it goes
    into `IncidentSubmission.obligation_ref` so the core can prove a firm resolved
    its duties without learning which authorities bind it or what it filed. The
    hash covers the authorities, deadlines and corpus version, so a later
    recomputation either reproduces it or proves the inputs changed.
    """
    material = json.dumps(
        {
            "detected_at": result.detected_at,
            "severity": result.incident_severity,
            "corpus_version": result.corpus_version,
            "obligations": sorted(
                (o.authority, o.applicability, o.deadline) for o in result.obligations
            ),
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(material.encode()).hexdigest()


class ObligationAgent(Agent):
    """
    A4 as an addressable agent.

    DRAFT_ONLY and `may_cross_boundary = False`: it holds no network capability
    and cannot file with any authority. The institution files.
    """

    agent_id = "A4"
    autonomy = Autonomy.DRAFT_ONLY
    may_cross_boundary = False

    async def run(self, payload: dict) -> dict:
        detected = payload.get("detected_at") or datetime.now(timezone.utc)
        if isinstance(detected, str):
            detected = datetime.fromisoformat(detected)
        return resolve(
            severity=payload.get("severity", "MEDIUM"),
            detected_at=detected,
            jurisdictions=payload.get("jurisdictions", []),
            essential_service_affected=payload.get("essential_service_affected"),
            incident_ref=payload.get("incident_ref", "PENDING"),
        ).as_dict()


__all__ = [
    "Authority", "Applicability", "AuthorityRule", "RULES", "RULES_BY_AUTHORITY",
    "CORPUS_VERSION", "NOTIFY_AT_OR_ABOVE", "Obligation", "ObligationResult",
    "resolve", "receipt_hash", "ObligationAgent",
]
