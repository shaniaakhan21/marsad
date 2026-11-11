"""
Shared-provider risk from what firms declared, and warnings when a provider is hit.

Firms declare dependencies as keyed tokens, because provider names are on the
never-cross list. So the core can count how many firms rest on one token without
knowing who the provider is. A name appears only through the directory below.

The directory is published by the operator when a provider enrols. It maps a token to
that provider's own public name and to the pseudonym allowed to speak for it. That
second field is the important one: without it, any participant could declare an incident
against a provider it does not run, and warn the whole market of an outage that never
happened.

Register output is gated like every other aggregate. A provider fewer than k firms
declare is withheld, and a token nobody has enrolled is counted but never named.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass

from marsad_core.services.concentration import ProviderDependency, Substitutability

#: How far back a firm is warned about provider incidents. Long enough to cover a firm
#: that declares a dependency just after its provider was hit.
PROVIDER_ALERT_WINDOW_DAYS = 30

#: Breaks ties when firms disagree about how replaceable a provider is. The worse
#: reading wins, because understating a single point of failure is the costlier error.
_SEVERITY_ORDER = (Substitutability.NO, Substitutability.PARTIAL, Substitutability.YES)


@dataclass(frozen=True)
class DirectoryEntry:
    name: str
    service: str
    market_activity_share: float
    owner_ref: str


def parse_directory(raw: str) -> dict[str, DirectoryEntry]:
    """Parsed at startup, so a malformed directory stops the core rather than a warning."""
    entries = {token: DirectoryEntry(**fields) for token, fields in json.loads(raw).items()}
    for token, entry in entries.items():
        if not 0 <= entry.market_activity_share <= 1:
            raise ValueError(f"market_activity_share out of range for {token[:12]}")
    return entries


def _consensus(votes: list[str]) -> Substitutability:
    counts = Counter(votes)
    top = max(counts.values())
    return next(s for s in _SEVERITY_ORDER if counts.get(s.value) == top)


def declared_dependencies(
    rows: list[tuple[str, str, str]], directory: dict[str, DirectoryEntry], k: int,
) -> tuple[list[ProviderDependency], dict[str, int]]:
    """
    Register entries from (institution_ref, provider_token, substitutability) rows.

    Returns the publishable providers and the counts of what was held back.
    """
    firms: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for ref, token, substitutability in rows:
        firms[token].append((ref, substitutability))

    published: list[ProviderDependency] = []
    withheld = unenrolled = 0
    for token, declared in firms.items():
        if len(declared) < k:
            withheld += 1
            continue
        entry = directory.get(token)
        if entry is None:
            unenrolled += 1
            continue
        published.append(ProviderDependency(
            provider=entry.name,
            service=entry.service,
            dependent_refs=tuple(sorted(ref for ref, _ in declared)),
            market_activity_share=entry.market_activity_share,
            substitutability=_consensus([s for _, s in declared]),
        ))
    return published, {"withheld_below_k": withheld, "not_yet_enrolled": unenrolled}


__all__ = ["PROVIDER_ALERT_WINDOW_DAYS", "DirectoryEntry", "declared_dependencies",
           "parse_directory"]
