"""
Technique similarity — the second swap point.

Exact token matching catches an attacker reusing infrastructure. It misses the
same actor rotating domains and addresses, which is cheap and routine. Technique
similarity is what closes that gap, and it is the capability that distinguishes
MARSAD from indicator-sharing platforms.

The difficulty: you cannot run private set intersection on a similarity
comparison. Three strategies of increasing rigour are modelled here behind one
interface, so the trust assumption can be upgraded without touching callers.
"""

from __future__ import annotations

import hashlib
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

log = logging.getLogger("marsad.similarity")


@dataclass(frozen=True)
class SimilarityResult:
    score: float
    shared: tuple[str, ...]
    #: Set when the guarantee is weaker than the deployment target, so any
    #: downstream alert can be labelled rather than silently trusted.
    reduced_fidelity: bool = False
    method: str = ""


class SimilarityEngine(ABC):
    """Compares two technique sets and returns a bounded score in [0, 1]."""

    name: str
    reduced_fidelity: bool = False

    @abstractmethod
    def compare(self, a: list[str], b: list[str]) -> SimilarityResult: ...

    @staticmethod
    def _validate(a: list[str], b: list[str]) -> None:
        if not a or not b:
            raise ValueError("technique sets must be non-empty")


class JaccardEngine(SimilarityEngine):
    """
    PROTOTYPE. Plain Jaccard overlap on ATT&CK technique identifiers.

    Honest about its limits: it treats techniques as unordered and unweighted,
    so it cannot distinguish a common technique (T1566 phishing, present in
    almost everything) from a rare one that genuinely fingerprints an actor. It
    also requires the technique sets themselves in the clear at the core, which
    is a weaker privacy position than the enclave path.
    """

    name = "jaccard-v1"
    reduced_fidelity = True

    def compare(self, a: list[str], b: list[str]) -> SimilarityResult:
        self._validate(a, b)
        sa, sb = set(a), set(b)
        inter = sa & sb
        union = sa | sb
        score = len(inter) / len(union) if union else 0.0
        return SimilarityResult(
            score=score,
            shared=tuple(sorted(inter)),
            reduced_fidelity=True,
            method=self.name,
        )


class WeightedJaccardEngine(JaccardEngine):
    """
    Improvement available without new infrastructure: weight each technique by
    inverse document frequency across observed campaigns, so a rare technique
    contributes more evidence of a shared actor than a ubiquitous one.

    Populate `idf` from the core's own campaign history; until then it degrades
    gracefully to unweighted Jaccard.
    """

    name = "weighted-jaccard-v1"

    def __init__(self, idf: dict[str, float] | None = None) -> None:
        self.idf = idf or {}

    def compare(self, a: list[str], b: list[str]) -> SimilarityResult:
        self._validate(a, b)
        sa, sb = set(a), set(b)
        inter, union = sa & sb, sa | sb
        if not union:
            return SimilarityResult(0.0, (), True, self.name)

        w = lambda t: self.idf.get(t, 1.0)  # noqa: E731
        num = sum(w(t) for t in inter)
        den = sum(w(t) for t in union)
        return SimilarityResult(
            score=(num / den) if den else 0.0,
            shared=tuple(sorted(inter)),
            reduced_fidelity=True,
            method=self.name,
        )


class EnclaveEngine(SimilarityEngine):
    """
    DEPLOYMENT TARGET — not yet implemented.

    Comparison runs inside a confidential-computing enclave (AMD SEV-SNP or
    Intel TDX). Institutions submit encrypted technique embeddings, verify the
    enclave's remote attestation before submitting, and only the resulting score
    leaves the enclave. The operator cannot read the inputs.

    Implementation notes:
      * Attestation must be verified by the *institution*, not by us, or the
        guarantee is theatre. Publish the expected measurement.
      * Embeddings beat set overlap here: encode the technique *sequence* so
        ordering and progression carry signal.
      * Budget a hard cap on comparisons per epoch — an unbounded oracle inside
        an enclave is still an oracle.
    """

    name = "enclave-embedding-v1"
    reduced_fidelity = False

    def __init__(self, *_, **__) -> None:
        raise NotImplementedError(
            "EnclaveEngine is the deployment target. Requires an attested TEE and "
            "published enclave measurements before real data is processed."
        )

    def compare(self, a: list[str], b: list[str]) -> SimilarityResult:  # pragma: no cover
        raise NotImplementedError


class SmpcEngine(SimilarityEngine):
    """
    HARDENED TARGET — not yet implemented. Secure multiparty computation of
    cosine similarity between two institutions' embeddings, with no trusted
    hardware assumption and no third party learning either input. Materially
    heavier than the enclave path; the right answer once volume justifies it.
    """

    name = "smpc-cosine-v1"
    reduced_fidelity = False

    def __init__(self, *_, **__) -> None:
        raise NotImplementedError("SMPC path not implemented.")

    def compare(self, a: list[str], b: list[str]) -> SimilarityResult:  # pragma: no cover
        raise NotImplementedError


def build_similarity_engine(kind: str = "jaccard", **kw) -> SimilarityEngine:
    match kind.lower():
        case "jaccard":
            return JaccardEngine()
        case "weighted":
            return WeightedJaccardEngine(**kw)
        case "enclave":
            return EnclaveEngine(**kw)
        case "smpc":
            return SmpcEngine(**kw)
        case _:
            raise ValueError(f"unknown similarity engine: {kind!r}")


def stable_campaign_id(tokens: list[str], techniques: list[str]) -> str:
    """Deterministic campaign identifier so restarts do not fragment a campaign."""
    h = hashlib.sha256()
    for t in sorted(set(tokens)):
        h.update(t.encode())
    for t in sorted(set(techniques)):
        h.update(t.encode())
    return "cmp_" + h.hexdigest()[:16]
