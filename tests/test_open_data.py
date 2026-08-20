"""
Tests for the evidence layer.

These are not schema tests. Each one encodes a claim we make to a judge or a
regulator about our use of government data — that citations are complete, that
provenance is never overstated, that privacy parameters follow from real
population sizes, and that the AED figures reconcile against a second
independent source.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "packages" / "contracts"),
    str(ROOT / "services" / "core"),
]

from marsad_core.data import roadmap as rd  # noqa: E402
from marsad_core.data import uae_open_data as od  # noqa: E402


# ---------------------------------------------------------------- citations


def test_every_source_is_fully_citable():
    """A judge is told to check the exact dataset and its portal. No blanks."""
    for s in od.SOURCES:
        assert s.title.strip(), s.key
        assert s.publisher.strip(), s.key
        assert s.portal.strip(), s.key
        assert s.url.startswith("https://"), s.key
        assert s.access, s.key
        assert s.coverage.strip(), s.key
        assert s.used_for.strip(), f"{s.key} has no stated purpose"


def test_source_keys_are_unique():
    keys = [s.key for s in od.SOURCES]
    assert len(keys) == len(set(keys))


def test_weakly_verified_sources_must_carry_a_caveat():
    """
    Overstated provenance is the fastest way to lose a technically literate
    reviewer. Anything short of VERIFIED has to say what is missing.
    """
    for s in od.SOURCES:
        if s.verification is not od.Verification.VERIFIED:
            assert s.caveat, f"{s.key} is {s.verification.value} but carries no caveat"


def test_registry_counts_match_the_sources():
    r = od.registry()
    assert r["counts"]["total"] == len(od.SOURCES)
    assert r["counts"]["verified"] == sum(
        1 for s in od.SOURCES if s.verification is od.Verification.VERIFIED
    )
    assert r["counts"]["programmatic"] >= 1, "at least one machine-readable feed is required"


def test_registry_states_the_national_data_gap():
    """We rely on there being no sector-level cyber dataset. Say so, always."""
    gap = od.registry()["known_gap"].lower()
    assert "cyber" in gap and "no uae open dataset" in gap


def test_unreachable_portals_are_published_with_reasons():
    assert od.UNREACHABLE_PORTALS
    for p in od.UNREACHABLE_PORTALS:
        assert p["portal"] and p["reason"]


def test_challenge_owner_is_named_under_its_current_identity():
    """SCA now operates as the UAE Capital Market Authority; carry both."""
    blob = " ".join(s.publisher for s in od.SOURCES)
    assert "Capital Market Authority" in blob
    assert any("uaecma.gov.ae" in s.portal or "uaecma.gov.ae" in s.url for s in od.SOURCES)


# ---------------------------------------------------------------- market maths


def test_listed_market_cap_is_the_sum_of_both_exchanges():
    assert od.LISTED_MARKET_CAP_BN == pytest.approx(
        od.ADX_MARKET_CAP_BN + od.DFM_MARKET_CAP_BN
    )


def test_daily_traded_value_reconciles_with_the_exchanges_own_figures():
    """
    Two independent government sources must agree, or the headline number is
    decorative. CMA reports a daily average; the exchanges report full-year
    traded value. Divided by trading days they should land within a few percent.
    """
    cc = od.market_basis()["cross_check"]
    implied = cc["implied_daily_aed_bn"]
    reported = cc["cma_reported_daily_aed_bn"]
    assert abs(implied - reported) / reported < 0.05


def test_exposure_scales_with_share_and_is_clamped():
    low = od.exposure(0.10, 0.1)
    high = od.exposure(0.50, 0.1)
    assert high["daily_traded_value_at_risk_aed_bn"] > low["daily_traded_value_at_risk_aed_bn"]

    # A share above 1 or below 0 is a data error upstream, never an output error.
    assert od.exposure(4.0, 9.0)["market_activity_share"] == 1.0
    assert od.exposure(-1.0, -1.0)["market_activity_share"] == 0.0


def test_exposure_cannot_exceed_the_whole_market():
    full = od.exposure(1.0, 1.0)
    assert full["daily_traded_value_at_risk_aed_bn"] == pytest.approx(
        od.AVG_DAILY_TRADED_VALUE_BN
    )
    assert full["listed_market_cap_in_scope_aed_bn"] == pytest.approx(
        od.LISTED_MARKET_CAP_BN, rel=1e-3
    )


def test_weekly_exposure_is_five_trading_days():
    e = od.exposure(0.4, 0.2)
    assert e["weekly_traded_value_at_risk_aed_bn"] == pytest.approx(
        e["daily_traded_value_at_risk_aed_bn"] * 5
    )


# ---------------------------------------------------------------- k-anonymity


def test_small_cohorts_require_pooling_and_large_ones_do_not():
    """
    The whole point of calibrating against the real register: 3 of 61 banks is
    safe, 3 of 20 third-party administrators is not.
    """
    assert od.cohort_rule("BANK").pooling_required is False
    assert od.cohort_rule("TPA").pooling_required is True
    assert od.cohort_rule("FINANCE_CO").pooling_required is True


def test_pooling_decision_follows_from_the_population_not_a_constant():
    for r in od.cohort_rules():
        share_at_floor = od.K_FLOOR / r.population
        assert r.pooling_required == (share_at_floor > od.MAX_COHORT_SHARE), r.sector


def test_k_never_drops_below_the_absolute_floor():
    assert all(r.k_min >= od.K_FLOOR for r in od.cohort_rules())


def test_every_cohort_rule_explains_itself_with_its_numbers():
    """A privacy parameter a regulator cannot audit is not a control."""
    for r in od.cohort_rules():
        assert str(r.population) in r.rationale, r.sector
        assert r.label.lower() in r.rationale.lower(), r.sector


def test_cohorts_are_ordered_riskiest_first():
    pops = [r.population for r in od.cohort_rules()]
    assert pops == sorted(pops)


def test_unknown_cohort_is_refused_rather_than_guessed():
    with pytest.raises(KeyError):
        od.cohort_rule("NOT_A_SECTOR")


def test_concentration_denominator_comes_from_the_licensed_population():
    u = od.total_enrolled_universe()
    assert u["cma_licensed_companies"] == od.SECTOR_POPULATION["CMA_LICENSED"]["n"]
    assert u["cbuae_banks"] == od.SECTOR_POPULATION["BANK"]["n"]
    # The two registers are separate; the sum must be labelled, not passed off
    # as a deduplicated count of firms.
    assert "does not remove any firm that might appear on both" in u["note"]


def test_every_population_figure_names_its_source():
    for sector, meta in od.SECTOR_POPULATION.items():
        assert meta["source"] in od.SOURCES_BY_KEY, f"{sector} cites an unknown source"


# ---------------------------------------------------------------- the plan


def test_plan_covers_ninety_days_in_three_phases():
    p = rd.plan()
    assert p["horizon_days"] == 90
    assert len(p["phases"]) == 3
    last = p["phases"][-1]["milestones"][-1]["day"]
    assert last == 90, "the plan must actually reach day 90"


def test_milestones_are_in_chronological_order_and_within_the_horizon():
    days = [m["day"] for ph in rd.plan()["phases"] for m in ph["milestones"]]
    assert days == sorted(days)
    assert all(1 <= d <= 90 for d in days)


def test_every_milestone_has_an_owner_and_falsifiable_evidence():
    """'Done' has to mean something a third party can check."""
    for ph in rd.plan()["phases"]:
        for m in ph["milestones"]:
            assert m["owner"].strip(), m["title"]
            assert m["evidence"].strip(), m["title"]


def test_every_phase_has_a_gate_a_metric_and_a_named_risk():
    for ph in rd.plan()["phases"]:
        for field in ("exit_gate", "success_metric", "risk", "mitigation", "why_this_order"):
            assert ph[field].strip(), f"{ph['name']} is missing {field}"


def test_plan_has_kill_criteria():
    """A plan that cannot fail is a wish, and a judge will read it as one."""
    assert "day 45" in rd.plan()["kill_criteria"]


def test_legal_opinion_precedes_any_cross_firm_sharing():
    """
    The sequencing claim, enforced. Counsel is engaged in phase 1; the second
    institution — the first moment data is actually correlated between firms —
    must come later.
    """
    phases = rd.plan()["phases"]
    legal_day = next(
        m["day"] for m in phases[0]["milestones"] if "counsel" in m["detail"].lower()
    )
    second_firm_day = next(
        m["day"] for ph in phases for m in ph["milestones"]
        if "second institution" in m["title"].lower()
    )
    assert legal_day < second_firm_day


def test_oprf_lands_before_the_second_institution():
    """
    HMAC is not adequate for real institutional data. The production tokeniser
    must be in place before a second firm's data is correlated, not after.
    """
    milestones = [m for ph in rd.plan()["phases"] for m in ph["milestones"]]
    oprf = next(m["day"] for m in milestones if "OPRF" in m["title"])
    second = next(m["day"] for m in milestones if "second institution" in m["title"].lower())
    assert oprf < second


def test_plan_does_not_claim_government_integration():
    r = rd.plan()["resourcing"]["no_government_integration"].lower()
    assert "no verified access" in r
