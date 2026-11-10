"""
The regulator's market-wide view: read-only, aggregate, and with no firm in it.

The view is built only from what the core already holds, and everything published
passes one rule: a figure describes at least k distinct institutions, or it is not
published. A statistic over two firms identifies them to each other by elimination, even
with no name attached.

Sector counts go further. A cohort too small to satisfy the publication rule derived
from the licensed register is pooled, and if the pool itself would be small enough to
single a firm out, all sectors are merged, because publishing the others would reveal
the remainder by subtraction.

What is deliberately absent: pseudonyms, tokens, submission ids, and financial impact.
Impact stays inside each firm's own report. Showing it here would need new fields on the
boundary contract, which is a security decision that has not been taken.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable

from marsad_contracts.boundary import IncidentSubmission

from marsad_core.data import uae_open_data as od
from marsad_core.engines.correlation import CorrelationHit

#: Boundary sector -> licensed cohort whose population decides the publication rule.
#: A sector with no entry has no verified population, so it is always pooled.
SECTOR_COHORT = {"BANK": "BANK", "BROKER": "CMA_LICENSED", "INVEST": "CMA_LICENSED",
                 "INSURER": "INSURER"}

IMPACT_UNAVAILABLE = (
    "Financial impact is reported by each firm in its own filing and does not cross the "
    "boundary, so it cannot be aggregated here without a reviewed contract change."
)


def _sector_view(submissions: list[IncidentSubmission], k: int) -> dict:
    firms: dict[str, set[str]] = defaultdict(set)
    incidents: Counter[str] = Counter()
    for sub in submissions:
        firms[str(sub.coarse.sector)].add(sub.institution_ref)
        incidents[str(sub.coarse.sector)] += 1

    published: list[dict] = []
    pooled_firms: set[str] = set()
    pooled_incidents = 0
    for sector, members in sorted(firms.items()):
        cohort = SECTOR_COHORT.get(sector)
        if cohort and len(members) >= k and not od.cohort_rule(cohort).pooling_required:
            published.append({"group": sector, "institutions": len(members),
                              "incidents": incidents[sector]})
        else:
            pooled_firms |= members
            pooled_incidents += incidents[sector]

    if 0 < len(pooled_firms) < k:
        # Too small to publish, and subtraction would reveal it if the rest were shown.
        everyone = set().union(*firms.values())
        return {"groups": [{"group": "ALL_SECTORS", "institutions": len(everyone),
                            "incidents": sum(incidents.values())}], "pooling_applied": True}
    if pooled_firms:
        published.append({"group": "POOLED_OTHER_SECTORS", "institutions": len(pooled_firms),
                          "incidents": pooled_incidents})
    return {"groups": published, "pooling_applied": bool(pooled_firms)}


def _campaign_view(hits: list[CorrelationHit], k: int,
                   may_publish: Callable[[CorrelationHit], bool]) -> dict:
    grouped: dict[str, list[CorrelationHit]] = defaultdict(list)
    for hit in hits:
        grouped[hit.campaign_id or "unassigned"].append(hit)

    published: list[dict] = []
    withheld = 0
    for campaign_id, members in grouped.items():
        firms = {ref for h in members for ref in h.institution_refs}
        if len(firms) < k or not any(may_publish(h) for h in members):
            withheld += 1
            continue
        published.append({
            "campaign_id": campaign_id,
            "institutions": len(firms),
            "kinds": sorted({str(getattr(h.kind, "value", h.kind)) for h in members}),
            "techniques": sorted({t for h in members for t in h.shared_techniques}),
            "first_seen": min(h.detected_at for h in members).isoformat(),
            "reduced_fidelity": any(h.reduced_fidelity for h in members),
        })
    published.sort(key=lambda c: c["institutions"], reverse=True)
    return {"published": published, "withheld_below_k": withheld}


def _weekly_trend(submissions: list[IncidentSubmission], k: int) -> dict:
    weeks: dict[str, list[IncidentSubmission]] = defaultdict(list)
    for sub in submissions:
        year, week, _ = sub.coarse.ts_bucket.isocalendar()
        weeks[f"{year}-W{week:02d}"].append(sub)

    published: list[dict] = []
    withheld = 0
    for week, members in sorted(weeks.items()):
        if len({s.institution_ref for s in members}) < k:
            withheld += 1
            continue
        published.append({
            "week": week,
            "incidents": len(members),
            "by_severity": dict(Counter(str(s.coarse.severity_band) for s in members)),
        })
    return {"weeks": published, "weeks_withheld_below_k": withheld}


def _technique_view(submissions: list[IncidentSubmission], k: int) -> list[dict]:
    firms: dict[str, set[str]] = defaultdict(set)
    for sub in submissions:
        for technique in sub.technique_set:
            firms[technique].add(sub.institution_ref)
    rows = [{"technique": t, "institutions": len(m)} for t, m in firms.items() if len(m) >= k]
    return sorted(rows, key=lambda r: (-r["institutions"], r["technique"]))


def overview(submissions: list[IncidentSubmission], hits: list[CorrelationHit], *, k: int,
             may_publish: Callable[[CorrelationHit], bool], concentration: dict) -> dict:
    """The whole view. If fewer than k firms have reported, nothing about them is shown."""
    participants = {s.institution_ref for s in submissions}
    gate = {"k": k, "satisfied": len(participants) >= k}
    if not gate["satisfied"]:
        return {"gate": gate, "withheld": "fewer institutions have reported than k",
                "concentration": concentration, "impact": {"available": False,
                                                           "reason": IMPACT_UNAVAILABLE}}
    return {
        "gate": gate,
        "participants": len(participants),
        "market_coverage": concentration.get("market_coverage"),
        "campaigns": _campaign_view(hits, k, may_publish),
        "sectors": _sector_view(submissions, k),
        "trend": _weekly_trend(submissions, k),
        "techniques": _technique_view(submissions, k),
        "concentration": concentration,
        "impact": {"available": False, "reason": IMPACT_UNAVAILABLE},
    }


__all__ = ["IMPACT_UNAVAILABLE", "overview"]
