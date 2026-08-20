"""
The 90-day execution plan, as data.

Held in code rather than in a slide so the dashboard, the written submission and
the pitch cannot drift apart. Each phase carries an explicit exit gate: the plan
is designed to be stopped at a gate, not to run on optimism.

The sequencing rests on one judgement. MARSAD's binding constraint is not
engineering — it is whether an institution's legal counsel accepts that a keyed
token is not a disclosure of incident data. So the first 30 days deliver value
that requires *zero* sharing, and the sharing capability is only switched on
once counsel has signed. A plan that builds correlation first and asks
permission later would stall at day 60 with nothing deployable.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Milestone:
    day: int
    title: str
    detail: str
    owner: str
    evidence: str          # what must physically exist for this to count as done


@dataclass(frozen=True)
class Phase:
    window: str
    name: str
    objective: str
    why_this_order: str
    milestones: tuple[Milestone, ...]
    exit_gate: str
    success_metric: str
    risk: str
    mitigation: str


PHASES: tuple[Phase, ...] = (
    Phase(
        window="Days 1–30",
        name="Obligation resolver in production at one institution",
        objective=(
            "Deliver a capability that is useful to a single firm on its own, before "
            "asking any firm to share anything with anyone."
        ),
        why_this_order=(
            "Multi-authority incident reporting is pure benefit and requires no "
            "sharing, so it can be deployed while the legal question on tokens is "
            "still open. It also puts a connector inside a real perimeter, which is "
            "the hard part of every later phase."
        ),
        milestones=(
            Milestone(
                day=7,
                title="Legal boundary contract before a DPO",
                detail=(
                    "Put the boundary contract and the redaction agent in front of one "
                    "institution's Data Protection Officer and general counsel for a "
                    "written opinion on whether keyed tokens constitute disclosure."
                ),
                owner="Founder / legal counsel",
                evidence="Written legal opinion, or a written list of conditions to satisfy",
            ),
            Milestone(
                day=14,
                title="Obligation resolver covering the divergent UAE clocks",
                detail=(
                    "One submission satisfies ADGM's 24-hour duty, DIFC's 72-hour duty "
                    "and TDRA's essential-service notification, with a receipt hash per "
                    "authority. No materiality bright line exists, so the resolver "
                    "presents the decision rather than making it."
                ),
                owner="Engineering",
                evidence="Passing test suite per authority + a filed receipt in staging",
            ),
            Milestone(
                day=21,
                title="Connector deployed inside one institution's perimeter",
                detail=(
                    "Docker deployment behind the firm's firewall, egress restricted to "
                    "the core endpoint, reviewed by the firm's own security team."
                ),
                owner="Engineering / partner SOC",
                evidence="Signed-off deployment review; connector health green for 7 days",
            ),
            Milestone(
                day=30,
                title="Postgres and audit persistence replace in-memory state",
                detail="Alembic migrations, retention policy, per-submission audit trail.",
                owner="Engineering",
                evidence="Restart-survival test; auditor can reconstruct any submission",
            ),
        ),
        exit_gate=(
            "A written legal opinion exists AND one connector has run inside a real "
            "perimeter for 7 consecutive days. If counsel refuses, the product "
            "continues as a single-firm obligation resolver and correlation is dropped "
            "— we do not proceed on hope."
        ),
        success_metric="1 institution live; ≥3 real filings resolved across ≥2 authorities",
        risk="Counsel declines on principle, regardless of cryptographic rigour.",
        mitigation=(
            "The 30-day deliverable has standalone commercial value without sharing, so "
            "a refusal costs the correlation roadmap, not the company."
        ),
    ),
    Phase(
        window="Days 31–60",
        name="Production cryptography and the second institution",
        objective="Make correlation safe enough to switch on, then switch it on between two firms.",
        why_this_order=(
            "Correlation between two institutions is the first moment the privacy "
            "guarantee is load-bearing. The HMAC prototype is not adequate for real "
            "data — indicators are low-entropy, so a key holder could enumerate them. "
            "The OPRF must land before the second institution, not after."
        ),
        milestones=(
            Milestone(
                day=40,
                title="OPRF tokenisation replacing HMAC",
                detail=(
                    "RFC 9497 VOPRF over Ristretto255: the institution learns PRF(k, x) "
                    "without learning k, the evaluator never sees x. Key epochs recorded "
                    "in the token scheme so tokens are never compared across epochs."
                ),
                owner="Engineering (cryptography)",
                evidence="Interop test across two connectors; independent code review",
            ),
            Milestone(
                day=48,
                title="Threshold key custody across independent parties",
                detail=(
                    "Key shares split so no single party — including us — can evaluate "
                    "alone. HSM-backed, with evaluation metered and audited so bulk "
                    "enumeration is visible."
                ),
                owner="Engineering / infrastructure",
                evidence="Custody agreement signed; single-share evaluation demonstrably fails",
            ),
            Milestone(
                day=55,
                title="Second institution live; first real cross-firm correlation",
                detail=(
                    "Two firms in different sectors submit under the production "
                    "tokeniser. Correlation notices at disclosure rung 0 only."
                ),
                owner="Founder / engineering",
                evidence="A correlation notice delivered to two SOCs from real submissions",
            ),
            Milestone(
                day=60,
                title="Concentration register seeded from declared dependencies",
                detail=(
                    "Both firms declare third-party dependencies; scoring runs against "
                    "the real licensed population as the denominator, with exposure "
                    "expressed in AED of daily traded value."
                ),
                owner="Engineering / risk",
                evidence="Ranked register reviewed by both firms' third-party risk leads",
            ),
        ),
        exit_gate=(
            "OPRF in production with threshold custody, and at least one correlation "
            "notice generated from two institutions' real submissions."
        ),
        success_metric="2 institutions live; ≥1 genuine cross-firm correlation; 0 privacy incidents",
        risk="OPRF round trips add latency, or HSM procurement slips.",
        mitigation=(
            "Batch blinding gives one round trip per incident rather than per indicator; "
            "software threshold custody ships first with HSM migration as a follow-on, "
            "and the reduced-fidelity flag makes the weaker path visible to operators."
        ),
    ),
    Phase(
        window="Days 61–90",
        name="Regulator view, telemetry, and the commercial decision",
        objective=(
            "Give the challenge owner a market-wide picture, prove the predictive claim, "
            "and reach a fundable go/no-go."
        ),
        why_this_order=(
            "The regulator-facing value only becomes real with more than two "
            "participants, and the predictive claim — detecting a campaign forming "
            "before anyone files — needs a telemetry baseline that takes weeks to "
            "accumulate. Both depend on phases 1 and 2 having held."
        ),
        milestones=(
            Milestone(
                day=70,
                title="Five institutions enrolled; k-anonymity gate active",
                detail=(
                    "Cohort publication rules derived from the CBUAE licensee register: "
                    "small cohorts are pooled rather than published, because a labelled "
                    "statistic over a 20-firm cohort is itself an identifier."
                ),
                owner="Founder",
                evidence="5 signed participation agreements; gate blocking a real aggregate",
            ),
            Milestone(
                day=78,
                title="Continuous coarse telemetry ingest",
                detail=(
                    "Sub-threshold signals — authentication failure rates, mail rejects, "
                    "scan volume — pooled as deviations from each firm's local baseline. "
                    "Rates and counts only; never events, never logs."
                ),
                owner="Engineering",
                evidence="14 days of baseline per firm; one precursor alert reviewed by a SOC",
            ),
            Milestone(
                day=84,
                title="Regulator console for the challenge owner",
                detail=(
                    "Market-wide risk picture, ranked concentration with AED exposure, "
                    "campaign view. Read-only, no new powers over any firm, no ability "
                    "to see an individual firm's incident detail."
                ),
                owner="Engineering / design",
                evidence="Walkthrough completed with the CMA challenge mentor",
            ),
            Milestone(
                day=90,
                title="Pilot report and go/no-go",
                detail=(
                    "Measured outcomes against the pilot hypotheses, a costed operating "
                    "model, and a written recommendation to continue, pivot or stop."
                ),
                owner="Founder",
                evidence="Pilot report delivered to participants and the challenge owner",
            ),
        ),
        exit_gate=(
            "Five institutions live, one precursor alert acknowledged by a SOC, and a "
            "written pilot report with a costed operating model."
        ),
        success_metric=(
            "5 institutions; ≥1 correlation that changed a SOC's action; concentration "
            "register naming at least one shared provider no single firm could see"
        ),
        risk=(
            "A zero-disclosure alert may not actually change SOC behaviour — the "
            "assumption that a bare 'you are not alone' signal is actionable is "
            "unvalidated."
        ),
        mitigation=(
            "Day-78 telemetry and the rung-2.5 Response Room let firms coordinate "
            "action without disclosing; if rung 0 proves inert, the product's centre "
            "of gravity moves to the concentration register, which needs no alerting."
        ),
    ),
)


def plan() -> dict:
    """Served at /v1/roadmap and rendered by the dashboard."""
    return {
        "horizon_days": 90,
        "sequencing_principle": (
            "Deliver value that requires zero sharing first; switch on sharing only "
            "after counsel has signed and production cryptography is in place."
        ),
        "phases": [
            {
                **{k: v for k, v in asdict(p).items() if k != "milestones"},
                "milestones": [asdict(m) for m in p.milestones],
            }
            for p in PHASES
        ],
        "resourcing": {
            "team": "2 engineers, 1 founder on partnerships and legal, fractional cryptography review",
            "critical_dependency": "One institution willing to host a connector in month 1",
            "no_government_integration": (
                "No verified access to the challenge owner's systems, taxonomies or data "
                "is in place. Every entity named is a notional counterparty requiring a "
                "formal agreement."
            ),
        },
        "kill_criteria": (
            "Legal counsel refuses the token boundary and no alternative institution "
            "accepts it by day 45; or five institutions cannot be enrolled by day 90."
        ),
    }


__all__ = ["Milestone", "Phase", "PHASES", "plan"]
