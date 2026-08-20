"""
Tests for the live open-data fetcher layer.

The demo has to survive a dead venue network, so the contract under test is:
never raise, always fall back honestly (LIVE -> CACHED -> PINNED), and never
touch the network when a fetcher is meant to skip. None of these tests need
network access — the handful that verify a *real* portal live are marked
@pytest.mark.network and excluded from the default run (see pytest.ini).
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "packages" / "contracts"),
    str(ROOT / "services" / "core"),
]

from marsad_core.data import fetchers as fx  # noqa: E402
from marsad_core.data import uae_open_data as od  # noqa: E402


# --------------------------------------------------------------------------
# test doubles for httpx.Client — no real socket ever opens in these tests
# --------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, json_data=None, content: bytes = b""):
        self._json = json_data
        self.content = content

    def raise_for_status(self):
        pass

    def json(self):
        if self._json is None:
            raise ValueError("response has no JSON body")
        return self._json


def _client_returning(outcome):
    """A stand-in for httpx.Client whose .get() either raises or returns `outcome`."""

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, **kw):
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

    return _FakeClient


def _never_called_client():
    class _FakeClient:
        def __init__(self, *a, **kw):
            raise AssertionError("a skipped fetcher must never touch the network")

    return _FakeClient


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    """Every test gets its own empty cache directory."""
    monkeypatch.setattr(fx, "CACHE_DIR", tmp_path / "opendata_cache")


# --------------------------------------------------------------------------
# the fallback contract
# --------------------------------------------------------------------------


def test_fetch_never_raises_and_returns_pinned_when_the_network_fails(monkeypatch):
    monkeypatch.setattr(fx.httpx, "Client", _client_returning(httpx.ConnectError("simulated outage")))
    result = fx.fetch_ajman_catalogue()
    assert result.status is fx.FetchStatus.PINNED
    assert result.value == fx.PINNED_AJMAN_CATALOGUE_COUNT
    assert result.detail and "ConnectError" in result.detail


def test_fetch_never_raises_on_a_timeout_either(monkeypatch):
    monkeypatch.setattr(fx.httpx, "Client", _client_returning(httpx.TimeoutException("simulated timeout")))
    result = fx.fetch_tdra_mobile_subscriptions()
    assert result.status is fx.FetchStatus.PINNED
    assert result.value == fx.PINNED_TDRA_DEC_2025_MOBILE_SUBSCRIPTIONS


def test_malformed_payload_falls_back_rather_than_propagating(monkeypatch):
    bad = _FakeResponse(json_data={"total_count": "not-an-int"})
    monkeypatch.setattr(fx.httpx, "Client", _client_returning(bad))
    result = fx.fetch_ajman_catalogue()
    assert result.status is fx.FetchStatus.PINNED
    assert result.value == fx.PINNED_AJMAN_CATALOGUE_COUNT


def test_missing_json_body_falls_back_rather_than_propagating(monkeypatch):
    empty = _FakeResponse(json_data=None)
    monkeypatch.setattr(fx.httpx, "Client", _client_returning(empty))
    result = fx.fetch_ajman_business_licenses()
    assert result.status is fx.FetchStatus.PINNED
    assert result.value == fx.PINNED_AJMAN_ACTIVE_BUSINESS_LICENSES


def test_a_successful_fetch_is_reported_live_and_written_to_cache(monkeypatch):
    ok = _FakeResponse(json_data={"total_count": 250})
    monkeypatch.setattr(fx.httpx, "Client", _client_returning(ok))
    result = fx.fetch_ajman_catalogue()
    assert result.status is fx.FetchStatus.LIVE
    assert result.value == 250
    assert (fx.CACHE_DIR / "ajman_catalogue.json").exists()


def test_a_stale_cache_is_still_used_and_reports_its_age(monkeypatch):
    fx.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    old_timestamp = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
    (fx.CACHE_DIR / "ajman_catalogue.json").write_text(json.dumps({
        "value": 999, "url": "https://data.ajman.ae/api/explore/v2.1/catalog/datasets",
        "fetched_at": old_timestamp, "detail": "previously live",
    }))
    monkeypatch.setattr(fx.httpx, "Client", _client_returning(httpx.ConnectError("simulated outage")))

    result = fx.fetch_ajman_catalogue()

    assert result.status is fx.FetchStatus.CACHED
    assert result.value == 999
    assert result.cache_age_days >= 30


def test_a_fresh_cache_is_used_on_network_failure_too(monkeypatch):
    fx.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    (fx.CACHE_DIR / "ajman_catalogue.json").write_text(json.dumps({
        "value": 500, "url": "https://data.ajman.ae/api/explore/v2.1/catalog/datasets",
        "fetched_at": now, "detail": "previously live",
    }))
    monkeypatch.setattr(fx.httpx, "Client", _client_returning(httpx.ConnectError("simulated outage")))

    result = fx.fetch_ajman_catalogue()

    assert result.status is fx.FetchStatus.CACHED
    assert result.value == 500
    assert result.cache_age_days < 1


def test_corrupt_cache_file_is_ignored_rather_than_raised(monkeypatch):
    fx.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (fx.CACHE_DIR / "ajman_catalogue.json").write_text("{not valid json")
    monkeypatch.setattr(fx.httpx, "Client", _client_returning(httpx.ConnectError("simulated outage")))

    result = fx.fetch_ajman_catalogue()

    assert result.status is fx.FetchStatus.PINNED
    assert result.value == fx.PINNED_AJMAN_CATALOGUE_COUNT


# --------------------------------------------------------------------------
# Bayanat and Dubai Pulse — the honest non-integrations
# --------------------------------------------------------------------------


def test_bayanat_never_claims_live_without_a_verified_guid(monkeypatch):
    """No network call at all — see fetch_bayanat_cbuae_series's docstring."""
    monkeypatch.setattr(fx.httpx, "Client", _never_called_client())
    result = fx.fetch_bayanat_cbuae_series()
    assert result.status is fx.FetchStatus.PINNED
    assert result.value is None
    assert "GUID" in result.detail


def test_dubai_pulse_skips_cleanly_with_no_key_and_no_network_call(monkeypatch):
    monkeypatch.delenv("MARSAD_DUBAI_PULSE_KEY", raising=False)
    monkeypatch.setattr(fx.httpx, "Client", _never_called_client())
    result = fx.fetch_dubai_pulse()
    assert result.status is fx.FetchStatus.PINNED
    assert result.value is None
    assert "MARSAD_DUBAI_PULSE_KEY" in result.detail


def test_dubai_pulse_attempts_the_network_once_a_key_is_configured(monkeypatch):
    monkeypatch.setenv("MARSAD_DUBAI_PULSE_KEY", "test-key")
    monkeypatch.setattr(fx.httpx, "Client", _client_returning(httpx.ConnectError("blocked")))
    result = fx.fetch_dubai_pulse()
    assert result.status is fx.FetchStatus.PINNED  # portal has always blocked us — see UNREACHABLE_PORTALS
    assert result.value is None


# --------------------------------------------------------------------------
# the resolver — proving the live path drives the same logic as the pinned one
# --------------------------------------------------------------------------


def test_cohort_rule_flips_from_publish_to_pool_on_a_live_population_figure(monkeypatch):
    """
    cohort_rule() itself is unchanged — only resolve_population() feeds it. A
    live figure that shrinks the bank cohort below the 10% ceiling must flip
    the same publication decision the pinned constant currently avoids.
    """
    assert od.cohort_rule("BANK").pooling_required is False  # pinned: 3/61 = 4.9%

    def live_bank_population() -> fx.FetchResult:
        return fx.FetchResult(
            source_key="cbuae_annual_2025_licensees", status=fx.FetchStatus.LIVE,
            value=15, url="https://example.test/cb-register", fetched_at="2026-08-19T00:00:00+00:00",
        )

    monkeypatch.setitem(od.POPULATION_FETCHERS, "BANK", live_bank_population)

    rule = od.cohort_rule("BANK")
    assert rule.population == 15
    assert rule.pooling_required is True  # 3/15 = 20% > the 10% ceiling
    assert "15" in rule.rationale


def test_resolve_population_is_pinned_by_default_and_names_its_source():
    result = od.resolve_population("BANK")
    assert result.status is fx.FetchStatus.PINNED
    assert result.value == od.SECTOR_POPULATION["BANK"]["n"]
    assert result.url == od.SOURCES_BY_KEY["cbuae_annual_2025_licensees"].url


def test_resolve_market_figure_is_pinned_by_default_and_matches_the_module_constant():
    result = od.resolve_market_figure("avg_daily_traded_value_aed_bn")
    assert result.status is fx.FetchStatus.PINNED
    assert result.value == od.AVG_DAILY_TRADED_VALUE_BN


def test_exposure_and_market_basis_are_unaffected_by_the_resolver_refactor():
    """cohort_rule() and exposure() are frozen; only their inputs changed."""
    basis = od.market_basis()
    assert basis["avg_daily_traded_value_aed_bn"] == od.AVG_DAILY_TRADED_VALUE_BN
    e = od.exposure(0.5, 0.2)
    assert e["daily_traded_value_at_risk_aed_bn"] == pytest.approx(od.AVG_DAILY_TRADED_VALUE_BN * 0.5, rel=1e-3)


def test_freshness_reports_every_figure_with_a_status_and_a_url(monkeypatch):
    """Shape test for /v1/data/freshness — the open-data fetchers are faked out."""
    def fake_fetch() -> fx.FetchResult:
        return fx.FetchResult("fake_source", fx.FetchStatus.LIVE, 1, "https://example.test", "2026-08-19T00:00:00+00:00")

    monkeypatch.setattr(fx, "LIVE_FETCHERS", {"fake_source": fake_fetch})

    report = od.freshness()

    assert report["open_data"]["fake_source"]["status"] == "LIVE"
    for sector_report in report["population"].values():
        assert sector_report["status"] in ("LIVE", "CACHED", "PINNED")
        assert sector_report["url"].startswith("https://")
    for market_report in report["market"].values():
        assert market_report["status"] in ("LIVE", "CACHED", "PINNED")
        assert market_report["url"].startswith("https://")


def test_freshness_route_returns_the_same_shape(monkeypatch):
    def fake_fetch() -> fx.FetchResult:
        return fx.FetchResult("fake_source", fx.FetchStatus.LIVE, 1, "https://example.test", "2026-08-19T00:00:00+00:00")

    monkeypatch.setattr(fx, "LIVE_FETCHERS", {"fake_source": fake_fetch})

    from fastapi.testclient import TestClient
    from marsad_core.main import app

    with TestClient(app) as client:
        resp = client.get("/v1/data/freshness")

    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"open_data", "population", "market"}
    assert body["open_data"]["fake_source"]["status"] == "LIVE"


# --------------------------------------------------------------------------
# real-network integration — excluded from the default run
# --------------------------------------------------------------------------


@pytest.mark.network
def test_ajman_catalogue_is_genuinely_reachable_live():
    result = fx.fetch_ajman_catalogue()
    assert result.status is fx.FetchStatus.LIVE
    assert result.value > 0


@pytest.mark.network
def test_tdra_workbook_is_genuinely_parsed_live():
    result = fx.fetch_tdra_mobile_subscriptions()
    assert result.status is fx.FetchStatus.LIVE
    assert result.value > 0
    assert "B" in result.detail  # cell reference, e.g. "cell B181 on sheet ..."
