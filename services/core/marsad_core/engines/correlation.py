"""
Correlation engine — matches submissions without ever seeing plaintext.

Two mechanisms, deliberately separated because they fail differently:

  * exact token match  — high precision, blind to infrastructure rotation
  * technique similarity — catches rotation, lower precision, needs a threshold

Both are gated by k-anonymity before anything is published, because a match that
identifies a firm by elimination is a disclosure even when no field was shared.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone

from marsad_contracts.boundary import (
    CorrelationKind,
    CorrelationNotice,
    IncidentSubmission,
    IndicatorType,
)

from marsad_core.engines.similarity import SimilarityEngine, stable_campaign_id

log = logging.getLogger("marsad.correlation")

#: Minimum distinct institutions before an aggregate signal may be published.
#: A pairwise notice to the two parties involved is exempt — they already know
#: their own side, so telling each "someone matched you" reveals nothing further.
DEFAULT_K_ANONYMITY = 3

#: Technique overlap below this is noise. Phishing plus valid-accounts is the
#: shape of half the incidents in the sector.
DEFAULT_SIMILARITY_THRESHOLD = 0.60


@dataclass
class CorrelationHit:
    kind: CorrelationKind
    institution_refs: tuple[str, ...]
    submission_ids: tuple[str, ...]
    indicator_type: IndicatorType | None = None
    token: str | None = None
    shared_techniques: tuple[str, ...] = ()
    similarity: float | None = None
    reduced_fidelity: bool = False
    campaign_id: str | None = None
    detected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class CorrelationEngine:
    """
    Stateless with respect to plaintext; stateful only over submitted payloads.

    In production the index lives in Postgres plus a graph store. The in-memory
    index here is intentionally behind the same method surface so swapping the
    backing store does not change the algorithm.
    """

    def __init__(
        self,
        similarity: SimilarityEngine,
        *,
        k_anonymity: int = DEFAULT_K_ANONYMITY,
        similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    ) -> None:
        self._sim = similarity
        self._k = k_anonymity
        self._threshold = similarity_threshold

        self._submissions: dict[str, IncidentSubmission] = {}
        # token -> set of submission_id
        self._token_index: dict[str, set[str]] = defaultdict(set)

    # -- ingest -------------------------------------------------------------

    def ingest(self, sub: IncidentSubmission) -> list[CorrelationHit]:
        """
        Register a submission and return any correlations it creates.

        Idempotent on submission_id so a connector retrying after a network
        failure cannot inflate a campaign's apparent size.
        """
        if sub.submission_id in self._submissions:
            log.info("correlation.duplicate submission=%s ignored", sub.submission_id)
            return []

        hits: list[CorrelationHit] = []
        hits += self._match_exact(sub)
        hits += self._match_techniques(sub)

        self._submissions[sub.submission_id] = sub
        for kt in sub.tokens:
            self._token_index[kt.token].add(sub.submission_id)

        for h in hits:
            h.campaign_id = self._assign_campaign(h)
        return hits

    # -- mechanisms ---------------------------------------------------------

    def _match_exact(self, sub: IncidentSubmission) -> list[CorrelationHit]:
        out: list[CorrelationHit] = []
        for kt in sub.tokens:
            peers = {
                sid for sid in self._token_index.get(kt.token, set())
                if self._submissions[sid].institution_ref != sub.institution_ref
            }
            if not peers:
                continue
            refs = tuple(sorted(
                {self._submissions[s].institution_ref for s in peers} | {sub.institution_ref}
            ))
            out.append(CorrelationHit(
                kind=CorrelationKind.EXACT_TOKEN,
                institution_refs=refs,
                submission_ids=tuple(sorted(peers | {sub.submission_id})),
                indicator_type=IndicatorType(kt.type),
                token=kt.token,
            ))
            log.info(
                "correlation.exact token=%s… institutions=%d",
                kt.token[:10], len(refs),
            )
        return out

    def _match_techniques(self, sub: IncidentSubmission) -> list[CorrelationHit]:
        if not sub.technique_set:
            return []
        out: list[CorrelationHit] = []
        own_tokens = {kt.token for kt in sub.tokens}

        for sid, other in self._submissions.items():
            if other.institution_ref == sub.institution_ref or not other.technique_set:
                continue
            # If they already share an indicator, the exact match is the stronger
            # signal and a second notice would double-count the same campaign.
            if own_tokens & {kt.token for kt in other.tokens}:
                continue

            res = self._sim.compare(sub.technique_set, other.technique_set)
            if res.score < self._threshold:
                continue

            out.append(CorrelationHit(
                kind=CorrelationKind.TECHNIQUE_SIMILARITY,
                institution_refs=tuple(sorted({sub.institution_ref, other.institution_ref})),
                submission_ids=tuple(sorted({sub.submission_id, sid})),
                shared_techniques=res.shared,
                similarity=round(res.score, 4),
                reduced_fidelity=res.reduced_fidelity,
            ))
            log.info(
                "correlation.similarity score=%.2f method=%s reduced_fidelity=%s",
                res.score, res.method, res.reduced_fidelity,
            )
        return out

    # -- campaigns ----------------------------------------------------------

    def _assign_campaign(self, hit: CorrelationHit) -> str:
        toks = [hit.token] if hit.token else []
        return stable_campaign_id(toks, list(hit.shared_techniques))

    # -- publication --------------------------------------------------------

    def notices_for(self, hit: CorrelationHit) -> list[tuple[str, CorrelationNotice]]:
        """
        Convert a hit into the per-institution notices that may actually be sent.

        Each recipient learns *how many* other institutions are involved, never
        which. That is disclosure rung 0 — the institution decides whether to go
        further.
        """
        notices: list[tuple[str, CorrelationNotice]] = []
        for ref in hit.institution_refs:
            notices.append((ref, CorrelationNotice(
                correlation_id=str(uuid.uuid4()),
                kind=hit.kind,
                peer_count=len(hit.institution_refs) - 1,
                indicator_type=hit.indicator_type,
                shared_techniques=list(hit.shared_techniques),
                similarity=hit.similarity,
                detected_at=hit.detected_at,
                campaign_id=hit.campaign_id,
            )))
        return notices

    def may_publish_aggregate(self, hit: CorrelationHit) -> bool:
        """
        k-anonymity gate for *sector-wide* signals, dashboards and advisories —
        anything visible beyond the parties to the match itself.
        """
        distinct = len(set(hit.institution_refs))
        ok = distinct >= self._k
        if not ok:
            log.info(
                "correlation.gated distinct=%d k=%d — pairwise notice only",
                distinct, self._k,
            )
        return ok

    # -- introspection ------------------------------------------------------

    @property
    def submission_count(self) -> int:
        return len(self._submissions)

    def campaign_members(self, campaign_id: str) -> set[str]:
        return {
            s.institution_ref for s in self._submissions.values()
            if stable_campaign_id([kt.token for kt in s.tokens], s.technique_set) == campaign_id
        }
