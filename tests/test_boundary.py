"""
The tests that matter. If these pass, the central claims of the system hold.

Run:  pytest tests/ -v
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "packages" / "contracts"),
    str(ROOT / "services" / "connector"),
    str(ROOT / "services" / "core"),
]

from marsad_contracts.boundary import (  # noqa: E402
    CorrelationKind, IncidentSubmission, IndicatorType, Sector, SizeBand,
)
from marsad_connector.agents.a3_redact import RedactionAgent, RedactionError  # noqa: E402
from marsad_connector.crypto.tokeniser import HmacTokeniser, canonicalise  # noqa: E402
from marsad_core.engines.correlation import CorrelationEngine  # noqa: E402
from marsad_core.engines.similarity import JaccardEngine  # noqa: E402
from marsad_core.services.concentration import (  # noqa: E402
    ProviderDependency, Substitutability, rank, shared_by,
)

KEY = b"test-key-at-least-sixteen-bytes-long"


class FakeIncident:
    """Stands in for LocalIncident without needing a database."""

    def __init__(self, **kw):
        self.narrative = kw.get("narrative")
        self.analyst_notes = kw.get("analyst_notes")
        self.indicators = kw.get("indicators", [])
        self.techniques = kw.get("techniques", [])
        self.severity = kw.get("severity", "HIGH")
        self.evidence_paths = []
        self.obligation_receipt = kw.get("obligation_receipt")
        self.detected_at = kw.get("detected_at", datetime(2026, 8, 18, 13, 42, tzinfo=timezone.utc))


def agent() -> RedactionAgent:
    return RedactionAgent(HmacTokeniser(KEY))


def incident_a() -> FakeIncident:
    return FakeIncident(
        narrative="Finance staff received a credential-harvesting email impersonating the internal SSO portal.",
        analyst_notes="Confirmed two submissions by user ahmed.k before blocking.",
        indicators=[
            {"type": "DOMAIN", "value": "sso-almaha-verify.com"},
            {"type": "IP", "value": "185.220.101.44"},
            {"type": "IBAN", "value": "AE07 0331 2345 6789 0123 456"},
        ],
        techniques=["T1566.002", "T1078", "T1114", "T1567"],
    )


def incident_b() -> FakeIncident:
    """Different firm, SAME attacker IP — must produce an exact correlation."""
    return FakeIncident(
        narrative="Client services mailbox compromised; forwarding rule created.",
        indicators=[
            {"type": "DOMAIN", "value": "gulfsec-clientlogin.net"},
            {"type": "IP", "value": "185.220.101.44"},
        ],
        techniques=["T1566.002", "T1078", "T1114", "T1565"],
    )


def incident_c() -> FakeIncident:
    """Wholly different infrastructure, same tradecraft — similarity must catch it."""
    return FakeIncident(
        narrative="Portfolio team targeted by a lookalike login page.",
        indicators=[
            {"type": "DOMAIN", "value": "emcap-portal-secure.io"},
            {"type": "IP", "value": "91.219.238.12"},
        ],
        techniques=["T1566.002", "T1078", "T1114", "T1567"],
        severity="MEDIUM",
    )


def build(inc, ref: str) -> IncidentSubmission:
    return agent().build_submission(
        inc, institution_ref=ref, sector=Sector.BANK, size_band=SizeBand.LARGE
    )


# ---------------------------------------------------------------- privacy


def test_narrative_never_crosses_the_boundary():
    sub = build(incident_a(), "psd_a0001")
    blob = sub.model_dump_json().lower()
    for leaked in ("credential-harvesting", "sso portal", "ahmed", "finance staff"):
        assert leaked not in blob


def test_plaintext_indicators_never_cross():
    sub = build(incident_a(), "psd_a0001")
    blob = sub.model_dump_json()
    for plaintext in ("sso-almaha-verify.com", "185.220.101.44", "AE07"):
        assert plaintext not in blob


def test_leak_guard_trips_on_regression():
    """If a future refactor smuggles narrative through, this must fail loudly."""
    inc = incident_a()

    class Sabotaged(RedactionAgent):
        def build_submission(self, incident, **kw):
            sub = super().build_submission(incident, **kw)
            # simulate a developer 'helpfully' adding context to the pseudonym
            object.__setattr__(sub, "institution_ref", "credential-harvesting")
            self._assert_no_leakage(sub, incident)
            return sub

    with pytest.raises(RedactionError, match="LEAK GUARD"):
        Sabotaged(HmacTokeniser(KEY)).build_submission(
            inc, institution_ref="psd_a0001", sector=Sector.BANK, size_band=SizeBand.LARGE
        )


def test_contract_forbids_unknown_fields():
    """The schema itself is the defence — a typo cannot carry data across."""
    sub = build(incident_a(), "psd_a0001")
    payload = sub.model_dump(mode="json")
    payload["narrative"] = "this must be rejected"
    with pytest.raises(ValidationError):
        IncidentSubmission.model_validate(payload)


def test_timestamp_is_bucketed_to_the_hour():
    sub = build(incident_a(), "psd_a0001")
    assert sub.coarse.ts_bucket.minute == 0
    assert sub.coarse.ts_bucket.second == 0


def test_submission_with_no_indicators_is_refused():
    """Metadata-only submissions would leak posture while adding no value."""
    with pytest.raises(RedactionError):
        build(FakeIncident(indicators=[], techniques=["T1566.002"]), "psd_a0001")


# ---------------------------------------------------------------- tokenising


def test_same_indicator_tokenises_identically_across_institutions():
    """Without this, correlation silently never fires."""
    t = HmacTokeniser(KEY)
    assert t.tokenise("185.220.101.44", IndicatorType.IP) == \
           t.tokenise("185.220.101.44", IndicatorType.IP)


def test_canonicalisation_survives_analyst_formatting():
    """Analysts paste defanged and inconsistently spaced indicators."""
    t = HmacTokeniser(KEY)
    assert t.tokenise("Evil-Domain[.]com", IndicatorType.DOMAIN) == \
           t.tokenise("https://www.evil-domain.com/", IndicatorType.DOMAIN)
    assert t.tokenise("AE07 0331 2345", IndicatorType.IBAN) == \
           t.tokenise("ae0703312345", IndicatorType.IBAN)


def test_type_domain_separation_prevents_false_matches():
    t = HmacTokeniser(KEY)
    assert t.tokenise("12345", IndicatorType.ACCOUNT) != t.tokenise("12345", IndicatorType.IBAN)


def test_canonicalise_rejects_empty():
    with pytest.raises(ValueError):
        canonicalise("   ", IndicatorType.DOMAIN)


# ---------------------------------------------------------------- correlation


def engine(k: int = 3, threshold: float = 0.60) -> CorrelationEngine:
    return CorrelationEngine(JaccardEngine(), k_anonymity=k, similarity_threshold=threshold)


def test_exact_token_match_detected_without_plaintext():
    e = engine()
    assert e.ingest(build(incident_a(), "psd_a0001")) == []
    hits = e.ingest(build(incident_b(), "psd_b0002"))
    exact = [h for h in hits if h.kind == CorrelationKind.EXACT_TOKEN]
    assert len(exact) == 1
    assert exact[0].indicator_type == IndicatorType.IP
    assert set(exact[0].institution_refs) == {"psd_a0001", "psd_b0002"}


def test_technique_similarity_catches_rotated_infrastructure():
    """The differentiator: no shared indicator, same tradecraft."""
    e = engine()
    e.ingest(build(incident_a(), "psd_a0001"))
    hits = e.ingest(build(incident_c(), "psd_c0003"))
    sim = [h for h in hits if h.kind == CorrelationKind.TECHNIQUE_SIMILARITY]
    assert len(sim) == 1
    assert sim[0].similarity == 1.0          # identical technique sets
    assert sim[0].reduced_fidelity is True   # Jaccard must self-label
    assert not any(h.kind == CorrelationKind.EXACT_TOKEN for h in hits)


def test_similarity_not_reported_when_indicator_already_shared():
    """Avoid double-counting one campaign as two correlations."""
    e = engine()
    e.ingest(build(incident_a(), "psd_a0001"))
    hits = e.ingest(build(incident_b(), "psd_b0002"))
    assert not any(h.kind == CorrelationKind.TECHNIQUE_SIMILARITY for h in hits)


def test_same_institution_does_not_correlate_with_itself():
    e = engine()
    e.ingest(build(incident_a(), "psd_a0001"))
    assert e.ingest(build(incident_b(), "psd_a0001")) == []


def test_duplicate_submission_cannot_inflate_a_campaign():
    e = engine()
    sub = build(incident_a(), "psd_a0001")
    e.ingest(sub)
    assert e.ingest(sub) == []
    assert e.submission_count == 1


def test_k_anonymity_gates_aggregate_publication():
    e = engine(k=3)
    e.ingest(build(incident_a(), "psd_a0001"))
    hits = e.ingest(build(incident_b(), "psd_b0002"))
    hit = next(h for h in hits if h.kind == CorrelationKind.EXACT_TOKEN)
    assert e.may_publish_aggregate(hit) is False   # only two institutions
    # ...but both parties are still notified directly
    assert len(e.notices_for(hit)) == 2


def test_rung_zero_notice_reveals_count_not_identity():
    e = engine()
    e.ingest(build(incident_a(), "psd_a0001"))
    hits = e.ingest(build(incident_b(), "psd_b0002"))
    hit = next(h for h in hits if h.kind == CorrelationKind.EXACT_TOKEN)
    for ref, notice in e.notices_for(hit):
        blob = notice.model_dump_json()
        assert notice.peer_count == 1
        for other in ("psd_a0001", "psd_b0002"):
            if other != ref:
                assert other not in blob


def test_low_similarity_is_not_reported():
    e = engine(threshold=0.9)
    e.ingest(build(incident_a(), "psd_a0001"))
    hits = e.ingest(build(FakeIncident(
        indicators=[{"type": "DOMAIN", "value": "unrelated-site.example"}],
        techniques=["T1190", "T1505"],
    ), "psd_d0004"))
    assert hits == []


# ---------------------------------------------------------------- concentration


DEPS = [
    ProviderDependency("Nexa KYC", "Identity verification",
                       ("psd_a0001", "psd_b0002", "psd_c0003"), 0.41, Substitutability.NO),
    ProviderDependency("Meridian Cloud", "Core hosting",
                       ("psd_a0001", "psd_b0002"), 0.33, Substitutability.PARTIAL),
    ProviderDependency("TradeFeed", "Market data",
                       ("psd_b0002",), 0.12, Substitutability.YES),
]


def test_shared_provider_ranks_highest():
    ranked = rank(DEPS)
    assert ranked[0].provider == "Nexa KYC"
    assert ranked[0].band in ("HIGH", "CRITICAL")
    assert "no viable alternative" in ranked[0].rationale


def test_inferred_edges_are_discounted():
    declared = ProviderDependency("X", "svc", ("a", "b", "c"), 0.4, Substitutability.NO)
    inferred = ProviderDependency("X", "svc", ("a", "b", "c"), 0.4, Substitutability.NO,
                                  inferred=True)
    from marsad_core.services.concentration import score_provider
    assert score_provider(inferred).score < score_provider(declared).score
    assert "inferred" in score_provider(inferred).rationale


def test_escalation_finds_the_provider_all_victims_share():
    victims = {"psd_a0001", "psd_b0002", "psd_c0003"}
    shared = shared_by(DEPS, victims)
    assert [d.provider for d in shared] == ["Nexa KYC"]
