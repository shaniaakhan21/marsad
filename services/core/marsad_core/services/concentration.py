"""
Third-party concentration risk — the capability that exists nowhere today.

Deliberately deterministic. A regulator will be asked to act on these numbers,
so they must be reproducible and explainable line by line, never model output.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Substitutability(str, Enum):
    YES = "YES"        # a comparable provider could be switched to in weeks
    PARTIAL = "PARTIAL"
    NO = "NO"          # no viable alternative in the market


@dataclass(frozen=True)
class ProviderDependency:
    provider: str
    service: str
    dependent_refs: tuple[str, ...]
    market_activity_share: float          # 0..1 of trade value resting on it
    substitutability: Substitutability
    inferred: bool = False                # True if derived, not declared


@dataclass(frozen=True)
class ConcentrationScore:
    provider: str
    score: float                          # 0..100
    band: str                             # LOW | MEDIUM | HIGH | CRITICAL
    dependents: int
    market_activity_share: float
    rationale: str


#: Weights are policy, not maths. Kept here, named, so the SCA can tune them
#: and see exactly what changed.
#:
#: Calibration note: the dominant term is the *fraction of participating
#: institutions* that depend on a provider, not the raw count. A provider three
#: of three firms rely on is a systemic single point of failure; a provider three
#: of three hundred rely on is not. Absolute counts cannot express that, and an
#: early version of this scorer under-rated a non-substitutable provider the
#: whole sample depended on — the test suite caught it.
W_DEPENDENT_FRACTION = 45.0
W_MARKET_SHARE = 40.0
W_NO_SUBSTITUTE = 25.0
W_PARTIAL_SUBSTITUTE = 10.0
W_INFERRED_PENALTY = 0.85  # discount unconfirmed edges rather than trusting them


def score_provider(
    dep: ProviderDependency, *, total_participants: int | None = None
) -> ConcentrationScore:
    """
    Score a provider's systemic concentration.

    `total_participants` is the number of institutions enrolled in MARSAD. When
    omitted we fall back to the dependent count itself, which yields the most
    conservative (highest) reading — appropriate for a regulator's default view,
    but pass the real figure in production.
    """
    n = len(dep.dependent_refs)
    total = total_participants or n or 1
    fraction = min(1.0, n / total)

    raw = fraction * W_DEPENDENT_FRACTION + dep.market_activity_share * W_MARKET_SHARE

    if dep.substitutability is Substitutability.NO:
        raw += W_NO_SUBSTITUTE
    elif dep.substitutability is Substitutability.PARTIAL:
        raw += W_PARTIAL_SUBSTITUTE

    if dep.inferred:
        raw *= W_INFERRED_PENALTY

    score = max(0.0, min(100.0, raw))
    band = (
        "CRITICAL" if score >= 85 else
        "HIGH" if score >= 62 else
        "MEDIUM" if score >= 38 else
        "LOW"
    )

    parts = [
        f"{n} of {total} participating institution(s) dependent ({fraction:.0%})",
        f"{dep.market_activity_share:.0%} of market activity",
    ]
    if dep.substitutability is Substitutability.NO:
        parts.append("no viable alternative provider")
    elif dep.substitutability is Substitutability.PARTIAL:
        parts.append("only partially substitutable")
    if dep.inferred:
        parts.append("edge inferred, not declared — discounted pending confirmation")

    return ConcentrationScore(
        provider=dep.provider,
        score=round(score, 1),
        band=band,
        dependents=n,
        market_activity_share=dep.market_activity_share,
        rationale="; ".join(parts),
    )


def rank(
    deps: list[ProviderDependency], *, total_participants: int | None = None
) -> list[ConcentrationScore]:
    """Market-wide single points of failure, worst first."""
    return sorted(
        (score_provider(d, total_participants=total_participants) for d in deps),
        key=lambda s: s.score,
        reverse=True,
    )


def shared_by(deps: list[ProviderDependency], refs: set[str]) -> list[ProviderDependency]:
    """Providers every one of `refs` depends on — the escalation trigger."""
    return [d for d in deps if refs.issubset(set(d.dependent_refs))]
