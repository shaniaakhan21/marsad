"""
Live open-data fetchers — the ingestion layer behind uae_open_data.py.

Every function here follows the same contract, because the demo has to survive
a dead venue network without anyone noticing:

1. Try the live portal: an 8-second timeout, one retry.
2. On any failure, fall back to the last cached response on disk
   (var/opendata_cache/<source_key>.json), however old it is.
3. If there is no cache either, fall back to a pinned constant — a real figure
   we read by hand and recorded in this file, never invented.

A fetcher never raises. It always returns a FetchResult carrying which of the
three paths was taken, so the UI can say so honestly (LIVE / CACHED / PINNED)
instead of presenting every number as equally fresh.
"""
from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger("marsad.core.fetchers")

TIMEOUT_SECONDS = 8.0
RETRIES = 1  # one retry beyond the first attempt, per the fetcher contract

#: Relative to the process working directory, which is services/core both in
#: local dev (README's `cd services/core && uvicorn ...`) and in the container
#: (Dockerfile WORKDIR). Never committed — see .gitignore.
CACHE_DIR = Path("var/opendata_cache")


class FetchStatus(str, Enum):
    LIVE = "LIVE"      # read from the portal on this call
    CACHED = "CACHED"  # portal unreachable; served from a prior successful fetch
    PINNED = "PINNED"  # no live path and no cache; a hand-verified constant


@dataclass(frozen=True)
class FetchResult:
    source_key: str
    status: FetchStatus
    value: Any
    url: str
    fetched_at: str  # ISO-8601 UTC
    cache_age_days: float | None = None
    detail: str | None = None  # cell reference, failure reason, or context

    def as_dict(self) -> dict:
        return {
            "source_key": self.source_key,
            "status": self.status.value,
            "value": self.value,
            "url": self.url,
            "fetched_at": self.fetched_at,
            "cache_age_days": self.cache_age_days,
            "detail": self.detail,
        }


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _cache_path(source_key: str) -> Path:
    return CACHE_DIR / f"{source_key}.json"


def _read_cache(source_key: str) -> dict | None:
    path = _cache_path(source_key)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        log.warning("fetchers.cache_corrupt key=%s", source_key)
        return None


def _write_cache(source_key: str, value: Any, url: str, fetched_at: str, detail: str | None) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cache_path(source_key).write_text(
            json.dumps({"value": value, "url": url, "fetched_at": fetched_at, "detail": detail})
        )
    except OSError:
        log.warning("fetchers.cache_write_failed key=%s", source_key)


def _from_cache_or_pin(source_key: str, url: str, pinned_value: Any, reason: str) -> FetchResult:
    cached = _read_cache(source_key)
    if cached is not None:
        fetched_at = cached["fetched_at"]
        age_days = max(0.0, (_now() - datetime.fromisoformat(fetched_at)).total_seconds() / 86400)
        log.info(
            "fetchers.cached key=%s status=CACHED age_days=%.1f reason=%s",
            source_key, age_days, reason,
        )
        return FetchResult(
            source_key, FetchStatus.CACHED, cached["value"], cached.get("url", url),
            fetched_at, cache_age_days=round(age_days, 2), detail=cached.get("detail") or reason,
        )
    log.info("fetchers.pinned key=%s status=PINNED reason=%s", source_key, reason)
    return FetchResult(source_key, FetchStatus.PINNED, pinned_value, url, _now_iso(), detail=reason)


def _attempt(url: str, **client_kwargs: Any) -> httpx.Response:
    """One GET, retried once, under the shared timeout. Raises on final failure."""
    last_exc: Exception | None = None
    for _ in range(RETRIES + 1):
        try:
            with httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=True) as client:
                resp = client.get(url, **client_kwargs)
                resp.raise_for_status()
                return resp
        except Exception as exc:  # noqa: BLE001 — any failure just triggers the retry/fallback
            last_exc = exc
    assert last_exc is not None
    raise last_exc


def _live_or_fallback(
    source_key: str,
    url: str,
    pinned_value: Any,
    parse: Callable[[httpx.Response], tuple[Any, str | None]],
) -> FetchResult:
    """The shared shape of every fetcher below: attempt live, else cache, else pin."""
    try:
        resp = _attempt(url)
        value, detail = parse(resp)
        now = _now_iso()
        _write_cache(source_key, value, url, now, detail)
        log.info("fetchers.live key=%s status=LIVE url=%s", source_key, url)
        return FetchResult(source_key, FetchStatus.LIVE, value, url, now, detail=detail)
    except Exception as exc:  # noqa: BLE001 — a fetcher never raises to its caller
        log.info("fetchers.failed key=%s url=%s error=%s: %s", source_key, url, type(exc).__name__, exc)
        return _from_cache_or_pin(source_key, url, pinned_value, f"fetch failed — {type(exc).__name__}: {exc}")


# --------------------------------------------------------------------------
# A. Ajman Data — Opendatasoft Explore API v2. No authentication, most
# reliable portal we found; verified reachable while building this.
# --------------------------------------------------------------------------

AJMAN_BASE = "https://data.ajman.ae/api/explore/v2.1/catalog/datasets"

#: Pinned fallback — the dataset count observed on 2026-08-19.
PINNED_AJMAN_CATALOGUE_COUNT = 211

#: Pinned fallback — active licences in "Companies by License Type"
#: (dataset_id: companies-by-license-type), observed on 2026-08-19.
PINNED_AJMAN_ACTIVE_BUSINESS_LICENSES = 4046


def fetch_ajman_catalogue() -> FetchResult:
    """Live dataset count from the Ajman open data catalogue — proves connectivity."""
    def parse(resp: httpx.Response) -> tuple[int, str]:
        data = resp.json()
        total = data["total_count"]
        if not isinstance(total, int):
            raise ValueError("total_count is not an int")
        return total, "datasets currently published on data.ajman.ae"

    return _live_or_fallback(
        "ajman_catalogue", f"{AJMAN_BASE}?limit=1", PINNED_AJMAN_CATALOGUE_COUNT, parse,
    )


def fetch_ajman_business_licenses() -> FetchResult:
    """
    Active business licences from Ajman's "Companies by License Type" dataset —
    the business/economic-activity dataset the brief asks for.
    """
    url = f"{AJMAN_BASE}/companies-by-license-type/records?limit=1&where=company_status%3D%22Active%22"

    def parse(resp: httpx.Response) -> tuple[int, str]:
        data = resp.json()
        total = data["total_count"]
        if not isinstance(total, int):
            raise ValueError("total_count is not an int")
        return total, "active licences, Ajman 'Companies by License Type' dataset"

    return _live_or_fallback(
        "ajman_business_licenses", url, PINNED_AJMAN_ACTIVE_BUSINESS_LICENSES, parse,
    )


# --------------------------------------------------------------------------
# B. Bayanat — the federal portal. Documented pattern:
# https://bayanat.ae/api/DatasetResources/GetDatasetResource?resourceID={GUID}
#
# Empirically, during this build: a malformed resourceID returns 400 in under
# a second; a well-formed but unconfirmed GUID does not error — it hangs past
# the 8-second timeout with no response. The portal's static HTML carries no
# discoverable public search endpoint either (it is a single-page app). We
# could not verify a GUID for the CBUAE financial/banking series, so per the
# source rule — verify before relying on it — this fetcher never claims LIVE.
# --------------------------------------------------------------------------

BAYANAT_SEARCH_URL = "https://bayanat.ae/api/DatasetSearch/Search"
BAYANAT_RESOURCE_URL = "https://bayanat.ae/api/DatasetResources/GetDatasetResource"


def bayanat_search(query: str) -> httpx.Response:
    """Low-level: one real attempt at the documented (unconfirmed) search pattern."""
    return _attempt(BAYANAT_SEARCH_URL, params={"keyword": query})


def bayanat_fetch_resource(resource_id: str) -> httpx.Response:
    """Low-level: one real attempt to fetch a dataset resource by GUID."""
    return _attempt(BAYANAT_RESOURCE_URL, params={"resourceID": resource_id})


def fetch_bayanat_cbuae_series() -> FetchResult:
    """
    Target: CBUAE financial/banking series on the federal Bayanat portal.

    Always PINNED (value None — we have no verified figure to fall back on)
    until a human confirms a resourceID in-browser and records it above. See
    the module docstring for why we do not guess one.
    """
    reason = (
        "no human-verified dataset GUID on file for the CBUAE series — "
        "GetDatasetResource hangs on unconfirmed GUIDs (empirically observed "
        "2026-08-19) and the portal exposes no public search API in its "
        "static HTML; guessing a GUID risks silently citing the wrong dataset"
    )
    log.info("fetchers.pinned key=bayanat_cbuae_series status=PINNED reason=%s", reason)
    return _from_cache_or_pin("bayanat_cbuae_series", "https://bayanat.ae/en/Datasets", None, reason)


# --------------------------------------------------------------------------
# C. TDRA Open Data — direct XLSX, no authentication.
# --------------------------------------------------------------------------

TDRA_MOBILE_SUBSCRIPTIONS_URL = (
    "https://tdra.gov.ae/-/media/Open-Data/Phone-and-internet-subscriptions/"
    "Phone-and-Internet-Subscriptions-2025/Active-Mobile-Subscriptions-Dec-2025.ashx"
)

#: Pinned fallback — read from cell B181, sheet "Monthly statistics", on
#: 2026-08-19. Real figure, not estimated; see fetch_tdra_mobile_subscriptions.
PINNED_TDRA_DEC_2025_MOBILE_SUBSCRIPTIONS = 24_278_380


def fetch_tdra_mobile_subscriptions() -> FetchResult:
    """
    Download and parse the TDRA workbook; extract the December 2025 row.

    The internal layout of this workbook was not inspected in advance, so the
    parser is defensive: it scans for a date cell in column A matching
    2025-12 rather than assuming a fixed row, and falls back if the sheet
    name, the column shape, or the expected month is missing.
    """
    def parse(resp: httpx.Response) -> tuple[int, str]:
        import openpyxl  # deferred: only needed on this path

        wb = openpyxl.load_workbook(BytesIO(resp.content), data_only=True)
        sheet_name = "Monthly statistics"
        if sheet_name not in wb.sheetnames:
            raise ValueError(f"expected sheet {sheet_name!r} not found; got {wb.sheetnames}")
        ws = wb[sheet_name]
        for row in ws.iter_rows(min_row=2, max_row=ws.max_row, max_col=2):
            date_cell, value_cell = row[0], row[1]
            d = date_cell.value
            if (
                isinstance(d, datetime)
                and d.year == 2025 and d.month == 12
                and isinstance(value_cell.value, (int, float))
            ):
                return int(value_cell.value), f"cell {value_cell.coordinate} on sheet '{sheet_name}'"
        raise ValueError("no December 2025 row found in the expected shape")

    return _live_or_fallback(
        "tdra_mobile_subscriptions",
        TDRA_MOBILE_SUBSCRIPTIONS_URL,
        PINNED_TDRA_DEC_2025_MOBILE_SUBSCRIPTIONS,
        parse,
    )


# --------------------------------------------------------------------------
# D. Dubai Pulse — optional, requires an OAuth key. Skips cleanly, with no
# network call at all, when MARSAD_DUBAI_PULSE_KEY is unset. Every manual
# check against this portal during this build was blocked at the network
# level (see UNREACHABLE_PORTALS in uae_open_data.py), so even with a key
# this path is best-effort and unverified.
# --------------------------------------------------------------------------

DUBAI_PULSE_DATASET_URL = "https://www.dubaipulse.gov.ae/api/opendata"


def fetch_dubai_pulse() -> FetchResult:
    source_key = "dubai_pulse_pilot_volume"
    key = os.environ.get("MARSAD_DUBAI_PULSE_KEY")
    if not key:
        reason = "MARSAD_DUBAI_PULSE_KEY not set — skipped, no network call made"
        log.info("fetchers.skipped key=%s reason=%s", source_key, reason)
        return _from_cache_or_pin(source_key, DUBAI_PULSE_DATASET_URL, None, reason)

    def parse(resp: httpx.Response) -> tuple[Any, str]:
        data = resp.json()
        return data, "Dubai Pulse authenticated response (unverified endpoint shape)"

    try:
        resp = _attempt(DUBAI_PULSE_DATASET_URL, headers={"Authorization": f"Bearer {key}"})
        value, detail = parse(resp)
        now = _now_iso()
        _write_cache(source_key, value, DUBAI_PULSE_DATASET_URL, now, detail)
        log.info("fetchers.live key=%s status=LIVE url=%s", source_key, DUBAI_PULSE_DATASET_URL)
        return FetchResult(source_key, FetchStatus.LIVE, value, DUBAI_PULSE_DATASET_URL, now, detail=detail)
    except Exception as exc:  # noqa: BLE001 — never raise to the caller
        log.info("fetchers.failed key=%s error=%s: %s", source_key, type(exc).__name__, exc)
        return _from_cache_or_pin(
            source_key, DUBAI_PULSE_DATASET_URL, None,
            f"fetch failed — {type(exc).__name__}: {exc}",
        )


# --------------------------------------------------------------------------
# Registry — every source the /v1/data/freshness endpoint reports on.
# --------------------------------------------------------------------------

LIVE_FETCHERS: dict[str, Callable[[], FetchResult]] = {
    "ajman_catalogue": fetch_ajman_catalogue,
    "ajman_business_licenses": fetch_ajman_business_licenses,
    "tdra_mobile_subscriptions": fetch_tdra_mobile_subscriptions,
    "bayanat_cbuae_series": fetch_bayanat_cbuae_series,
    "dubai_pulse_pilot_volume": fetch_dubai_pulse,
}


__all__ = [
    "LIVE_FETCHERS",
    "PINNED_AJMAN_ACTIVE_BUSINESS_LICENSES",
    "PINNED_AJMAN_CATALOGUE_COUNT",
    "PINNED_TDRA_DEC_2025_MOBILE_SUBSCRIPTIONS",
    "FetchResult",
    "FetchStatus",
    "bayanat_fetch_resource",
    "bayanat_search",
    "fetch_ajman_business_licenses",
    "fetch_ajman_catalogue",
    "fetch_bayanat_cbuae_series",
    "fetch_dubai_pulse",
    "fetch_tdra_mobile_subscriptions",
]
