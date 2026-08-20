"""
UAE government open data — the evidence layer.

Every figure in this module was read from a named government publication and is
recorded here with its source, portal, access type, coverage period and
verification status. Nothing is estimated silently: a figure we could not open
ourselves is marked and the reason is stated.

Why this module exists rather than a spreadsheet
------------------------------------------------
MARSAD makes two claims that only real data can support:

1. **Privacy parameters are calibrated to the real market, not invented.**
   k-anonymity is meaningless without knowing the size of the population being
   anonymised. k=5 inside 62 licensed banks is 8% of the cohort; k=5 inside 20
   third-party administrators is 25% and is re-identifying. The cohort sizes
   come from the CBUAE licensee register, so the privacy floor moves when the
   market moves.

2. **Concentration risk is expressed in AED, not in dimensionless points.**
   A regulator cannot act on "score 87.3". They can act on "an outage at this
   provider would interrupt firms carrying AED 2.21 bn of average daily traded
   value against AED 4.08 trn of listed market capitalisation."

The registry is deliberately introspectable over the API (`/v1/data/sources`)
so a judge, a mentor or a regulator can check our sources without reading code.

Naming note
-----------
The Securities and Commodities Authority now operates as the **UAE Capital
Market Authority**; `sca.gov.ae` redirects to `uaecma.gov.ae`. Challenge #9 was
issued under the SCA name, so both are carried here.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum

from marsad_core.data import fetchers as fx

# --------------------------------------------------------------------------
# Provenance vocabulary
# --------------------------------------------------------------------------


class Verification(str, Enum):
    """How far we personally got with a source. Never inflate this."""

    VERIFIED = "VERIFIED"          # we opened the publication and read the figure
    PAGE_VERIFIED = "PAGE_VERIFIED"  # dataset page confirmed; values not yet parsed
    SYNDICATED = "SYNDICATED"      # official statement read via a wire service
    UNREACHABLE = "UNREACHABLE"    # portal exists but blocked our client


class Access(str, Enum):
    API = "API"
    CSV = "CSV"
    XLSX = "XLSX"
    PDF = "PDF"
    DASHBOARD = "DASHBOARD"
    HTML = "HTML"


@dataclass(frozen=True)
class DataSource:
    """One citable government publication."""

    key: str
    title: str
    publisher: str
    portal: str
    url: str
    access: tuple[Access, ...]
    coverage: str
    last_updated: str
    verification: Verification
    used_for: str
    key_figures: dict[str, str] = field(default_factory=dict)
    caveat: str | None = None

    def as_dict(self) -> dict:
        d = asdict(self)
        d["access"] = [a.value for a in self.access]
        d["verification"] = self.verification.value
        return d


# --------------------------------------------------------------------------
# The registry
# --------------------------------------------------------------------------

SOURCES: tuple[DataSource, ...] = (
    DataSource(
        key="cbuae_annual_2025_licensees",
        title="Annual Report 2025 — Table 4: Total Number of Licensees by Type in 2025",
        publisher="Central Bank of the United Arab Emirates (CBUAE)",
        portal="centralbank.ae",
        url="https://www.centralbank.ae/media/4qbn11cl/annual-report-2025-en.pdf",
        access=(Access.PDF,),
        coverage="as at 31 December 2025",
        last_updated="2025-12-31",
        verification=Verification.VERIFIED,
        used_for=(
            "Sector cohort sizes. Sets the k-anonymity floor per sector and identifies "
            "which cohorts are too small to publish at all and must be pooled."
        ),
        key_figures={
            "total licensees": "856",
            "banks": "61",
            "finance companies": "20",
            "exchange businesses": "64",
            "fintech companies": "48",
            "insurance companies": "58",
            "insurance brokers": "161",
            "third-party administrators": "20",
        },
    ),
    DataSource(
        key="cbuae_cb_register",
        title="CB Register — monthly register of licensed financial institutions",
        publisher="Central Bank of the United Arab Emirates (CBUAE)",
        portal="centralbank.ae",
        url="https://www.centralbank.ae/media/kxxkzrho/cb-register-march-2026.pdf",
        access=(Access.PDF,),
        coverage="monthly series; issues verified from Sept 2022 to April 2026",
        last_updated="2026-03",
        verification=Verification.VERIFIED,
        used_for=(
            "The participant registry and the sustainability half of the data claim: "
            "a monthly re-publication means cohort sizes and the concentration "
            "denominator are recomputed every month rather than frozen at launch."
        ),
        key_figures={
            "banks (Mar 2026)": "62",
            "exchange companies": "64",
            "retail payment services": "32",
            "stored value facilities": "17",
            "finance companies": "20",
        },
    ),
    DataSource(
        key="cbuae_markets_q4_2025",
        title="UAE Monetary, Banking & Financial Markets Developments Report, Q4 2025",
        publisher="Central Bank of the United Arab Emirates (CBUAE)",
        portal="centralbank.ae",
        url="https://www.centralbank.ae/media/2cyhdr5b/uae-monetary-banking-financial-markets-dev-report-e-q4-2025.pdf",
        access=(Access.PDF,),
        coverage="Q4 2025 (quarterly series)",
        last_updated="2025-Q4",
        verification=Verification.VERIFIED,
        used_for=(
            "Converts a dimensionless concentration score into national exposure in "
            "AED. One government publication carrying both exchanges in one place."
        ),
        key_figures={
            "ADX market capitalisation": "AED 3,104.0 bn",
            "ADX quarterly traded value": "AED 125.7 bn",
            "DFM market capitalisation": "AED 980.0 bn",
            "DFM quarterly traded value": "AED 37.3 bn",
            "total bank assets": "AED 5,339.9 bn",
        },
    ),
    DataSource(
        key="tdra_open_data",
        title="TDRA Open Data — Phone & Internet Subscriptions; Indicators of ICT Access and Use",
        publisher="Telecommunications and Digital Government Regulatory Authority (TDRA)",
        portal="tdra.gov.ae",
        url="https://tdra.gov.ae/en/open-data/data-sets",
        access=(Access.XLSX,),
        coverage="December 2025 release; 61 datasets across 10 categories",
        last_updated="2026-05-08",
        verification=Verification.VERIFIED,
        used_for=(
            "The only current, unauthenticated, machine-readable feed in this set. "
            "Scales the attack-surface denominator and sizes realistic incident "
            "submission volumes for the pilot."
        ),
        key_figures={
            "datasets published": "61",
            "access": "direct XLSX URLs, no authentication",
            "active mobile subscriptions (Dec 2025)": "24,278,380",
        },
        caveat=(
            "Live-fetched and parsed: services/core/marsad_core/data/fetchers.py "
            "downloads the December 2025 workbook and reads the figure from cell "
            "B181 on sheet 'Monthly statistics'. Falls back to a cached copy, then "
            "to this pinned figure, if the portal is unreachable — see "
            "/v1/data/freshness for which path served the current dashboard."
        ),
    ),
    DataSource(
        key="tdra_aecert_monthly",
        title="Monthly UAE Security Report (aeCERT)",
        publisher="TDRA — aeCERT",
        portal="tdra.gov.ae",
        url="https://tdra.gov.ae/en/aecert/resource-center/statistics",
        access=(Access.PDF,),
        coverage="monthly; downloadable issues on the page are July–December 2020",
        last_updated="2020-12",
        verification=Verification.VERIFIED,
        used_for=(
            "Supplies the national incident-type taxonomy and an empirical monthly "
            "incident rate used to calibrate expected submission volume."
        ),
        key_figures={
            "attacks responded to (Apr 2020, federal government scope)": "~34,000",
            "incidents handled": "197",
            "composition": "vulnerabilities 47% / malware 46% / phishing 7%",
        },
        caveat=(
            "Current-year issues are not published on the statistics page; the 2024 "
            "and 2025 filters return no downloadable items. Quoted figures are 2020."
        ),
    ),
    DataSource(
        key="cma_licensed_companies",
        title="Licensed Companies — Open Data",
        publisher="Securities and Commodities Authority, now UAE Capital Market Authority (CMA)",
        portal="uaecma.gov.ae",
        url="https://www.uaecma.gov.ae/en/open-data/licensed-companies.aspx",
        access=(Access.DASHBOARD, Access.XLSX),
        coverage="current register, filterable by financial activity",
        last_updated="continuous",
        verification=Verification.PAGE_VERIFIED,
        used_for=(
            "The authoritative enrolment universe for the challenge owner's own "
            "regulated population — the firms MARSAD would onboard."
        ),
        key_figures={"licensed companies (CMA 2025 statement)": "244"},
        caveat=(
            "The table renders client-side and exports to Excel; there is no public "
            "JSON/CSV endpoint. The count of 244 comes from the CMA 2025 annual "
            "statement rather than a rendered dataset page — confirm in-browser."
        ),
    ),
    DataSource(
        key="cma_market_stats_2025",
        title="CMA 2025 annual regulatory and market performance statement",
        publisher="UAE Capital Market Authority (CMA)",
        portal="uaecma.gov.ae",
        url="https://www.uaecma.gov.ae/en/media-center/news",
        access=(Access.HTML,),
        coverage="full year 2025",
        last_updated="2026-01-27",
        verification=Verification.SYNDICATED,
        used_for=(
            "Average daily traded value — the flow figure that turns a provider "
            "outage into a per-day AED interruption."
        ),
        key_figures={
            "average daily trading value": "AED 2.21 bn (+24.16% y/y)",
            "licences and approvals issued 2025": "3,170 (vs 1,272 in 2024)",
            "funds under CMA oversight": "197 (vs 119 in 2024)",
            "assets under management": "USD 470 bn",
        },
        caveat=(
            "Read via WAM/Reuters syndication of the CMA statement rather than a "
            "CMA-hosted page our client could render."
        ),
    ),
    DataSource(
        key="adx_fy2025",
        title="ADX 2025 Results: Transformative Growth & Market Leadership",
        publisher="Abu Dhabi Securities Exchange (ADX)",
        portal="adx.ae",
        url="https://www.adx.ae/about-adx/media/adx-news/adx-market-leadership-2025-growth",
        access=(Access.HTML,),
        coverage="full year 2025",
        last_updated="2026-01-06",
        verification=Verification.VERIFIED,
        used_for="Cross-validates the CBUAE market figures and supplies the investor base.",
        key_figures={
            "market capitalisation": "AED 3.13 trn (+4.6%)",
            "FY2025 traded value": "AED 385 bn (+12.6%)",
            "investors": "more than 1.2 million, over 200 nationalities",
            "new listings": "20",
        },
        caveat="ADX report centre (eservices.adx.ae) is disallowed by robots.txt.",
    ),
    DataSource(
        key="dfm_fy2025",
        title="Dubai Financial Market delivers a strong 2025 performance",
        publisher="UAE Government Media Office / Dubai Financial Market (DFM)",
        portal="mediaoffice.ae",
        url="https://www.mediaoffice.ae/en/news/2026/january/28-01/dubai-financial-market-delivers-a-strong-2025-performance",
        access=(Access.HTML,),
        coverage="full year 2025",
        last_updated="2026-01-28",
        verification=Verification.VERIFIED,
        used_for="Second-exchange leg of the exposure calculation and investor base.",
        key_figures={
            "market capitalisation": "AED 992 bn",
            "FY2025 traded value": "AED 174 bn",
            "total investor base": "1.25 million",
            "new investors in 2025": "97,394 (84% foreign)",
        },
        caveat=(
            "ADX 1.2 m and DFM 1.25 m investors overlap; neither source states they "
            "are disjoint, so they are never summed."
        ),
    ),
    DataSource(
        key="cbuae_fsr",
        title="Financial Stability Report 2025",
        publisher="Central Bank of the United Arab Emirates (CBUAE)",
        portal="centralbank.ae",
        url="https://www.centralbank.ae/media/kaqlwo0h/cbuae-fsr-report_2025_en.pdf",
        access=(Access.PDF,),
        coverage="2025",
        last_updated="2025",
        verification=Verification.VERIFIED,
        used_for=(
            "Establishes the whitespace. The report names cybersecurity threats as a "
            "systemic risk yet contains no quantified cyber-incident data and no "
            "third-party concentration metric — precisely what MARSAD produces."
        ),
        key_figures={
            "licensed banks": "61 (23 national + 38 foreign branches)",
            "banking assets": "AED 4.6 trn (+12.0%)",
            "cited systemic risk": "AI-driven trading systems and cybersecurity threats",
        },
    ),
    DataSource(
        key="cbuae_aani",
        title="Aani instant payment platform — 12.5 million users",
        publisher="Central Bank of the United Arab Emirates (CBUAE)",
        portal="centralbank.ae",
        url="https://www.centralbank.ae/en/news-and-publications/news-and-insights/press-release/aani-delivers-a-transformational-leap-in-the-uae-s-digital-payments-landscape-12-5-million-users-and-instant-transfers-in-3-seconds/",
        access=(Access.HTML,),
        coverage="as at April 2026",
        last_updated="2026-04-10",
        verification=Verification.VERIFIED,
        used_for=(
            "A named, real shared-infrastructure dependency. Aani, Jaywan and "
            "UAESWITCH are national rails every participant touches — the textbook "
            "case for concentration monitoring."
        ),
        key_figures={"users": "12.5 million", "settlement": "3 seconds, 24/7"},
    ),
    DataSource(
        key="ajman_open_data",
        title="Ajman Open Data — Opendatasoft Explore API v2",
        publisher="Ajman Department of Economic Development / Ajman Smart Government",
        portal="data.ajman.ae",
        url="https://data.ajman.ae/api/explore/v2.1/catalog/datasets",
        access=(Access.API,),
        coverage="live catalogue; 'Companies by License Type' dataset, continuous",
        last_updated="continuous",
        verification=Verification.VERIFIED,
        used_for=(
            "The one portal in this set with a working, unauthenticated, "
            "machine-readable API — proves live connectivity to a UAE government "
            "open data source and demonstrates the fetch/cache/pin pattern the "
            "rest of the evidence layer follows. See /v1/data/freshness."
        ),
        key_figures={
            "datasets published": "211",
            "active business licences (Companies by License Type)": "4,046",
        },
    ),
    DataSource(
        key="bayanat",
        title="Bayanat — the official UAE open data portal",
        publisher="Federal Competitiveness and Statistics Centre (FCSC)",
        portal="bayanat.ae",
        url="https://bayanat.ae/en/Datasets",
        access=(Access.API, Access.XLSX, Access.CSV),
        coverage="thousands of federal and emirate-level datasets, 11 themes",
        last_updated="continuous",
        verification=Verification.PAGE_VERIFIED,
        used_for=(
            "The national catalogue. Financial and banking series here (e.g. CBUAE "
            "balance-sheet datasets) are reachable by API for Python/JS/cURL."
        ),
        key_figures={
            "verified example dataset": "Balance Sheet of the Central Bank of UAE — Assets (2013–2017, XLSX + API)",
        },
        caveat=(
            "Carries no cyber-incident dataset and no register of licensed financial "
            "institutions; the Technology theme returned no datasets. The single-page "
            "app can serve a default list regardless of the dataset id, so every "
            "Bayanat citation must be re-checked in a browser. Empirically (2026-08-19): "
            "GetDatasetResource returns instantly for a malformed GUID but hangs past "
            "an 8-second timeout for a well-formed, unverified one — "
            "services/core/marsad_core/data/fetchers.py never guesses a GUID for this "
            "reason and reports this source PINNED until one is human-verified."
        ),
    ),
)

SOURCES_BY_KEY: dict[str, DataSource] = {s.key: s for s in SOURCES}

#: Portals that exist but refused our client. Published for honesty — a reviewer
#: who cannot reproduce a citation should know it was us, not them.
UNREACHABLE_PORTALS: tuple[dict[str, str], ...] = (
    {"portal": "data.abudhabi", "reason": "WAF rejected the request; datasets are search-indexed"},
    {"portal": "dubaipulse.gov.ae", "reason": "robots.txt fetch timed out"},
    {"portal": "data.bayanat.ae (CKAN mirror)", "reason": "robots.txt fetch timed out"},
    {"portal": "eservices.adx.ae/reportcenter", "reason": "disallowed by robots.txt"},
    {"portal": "csc.gov.ae", "reason": "connection error on robots.txt"},
)


# --------------------------------------------------------------------------
# The resolver — every pinned figure's single point of entry.
#
# Prefers a live fetch, then a cached one, then the pinned constant — never
# fabricates, never raises. Most entries below resolve to PINNED today because
# their publisher (a PDF or an HTML press release) has no public API; that is
# reported honestly rather than hidden. Wiring a real fetcher in later is a
# one-line change: swap `None` for the fetch function in the registry below.
# --------------------------------------------------------------------------


def _resolve(source_key: str, pinned_value: object, fetch_fn: Callable[[], fx.FetchResult] | None,
             no_api_reason: str) -> fx.FetchResult:
    if fetch_fn is not None:
        return fetch_fn()
    source = SOURCES_BY_KEY[source_key]
    return fx.FetchResult(
        source_key=source_key, status=fx.FetchStatus.PINNED, value=pinned_value,
        url=source.url, fetched_at=datetime.now(timezone.utc).isoformat(), detail=no_api_reason,
    )


# --------------------------------------------------------------------------
# Verified market figures — the exposure basis
# --------------------------------------------------------------------------

#: All AED, billions. Source: cbuae_markets_q4_2025 (Q4 2025). No publisher in
#: this group exposes a public API — every figure below resolves PINNED; see
#: MARKET_FETCHERS.
_PINNED_ADX_MARKET_CAP_BN = 3_104.0
_PINNED_DFM_MARKET_CAP_BN = 980.0
ADX_TRADED_VALUE_Q4_BN = 125.7
DFM_TRADED_VALUE_Q4_BN = 37.3
_PINNED_BANK_ASSETS_BN = 5_339.9

#: Source: cma_market_stats_2025. Cross-checks against the exchanges' own FY2025
#: traded values: (385 + 174) / ~250 trading days ≈ 2.24 bn/day.
_PINNED_AVG_DAILY_TRADED_VALUE_BN = 2.21

#: One entry per market constant: source key it's read from, and the live
#: fetcher to prefer, if one exists. None means "no public API for this
#: publication" — always PINNED, honestly.
MARKET_FETCHERS: dict[str, tuple[str, object, Callable[[], fx.FetchResult] | None]] = {
    "adx_market_cap_aed_bn": ("cbuae_markets_q4_2025", _PINNED_ADX_MARKET_CAP_BN, None),
    "dfm_market_cap_aed_bn": ("cbuae_markets_q4_2025", _PINNED_DFM_MARKET_CAP_BN, None),
    "avg_daily_traded_value_aed_bn": ("cma_market_stats_2025", _PINNED_AVG_DAILY_TRADED_VALUE_BN, None),
    "bank_assets_aed_bn": ("cbuae_markets_q4_2025", _PINNED_BANK_ASSETS_BN, None),
}


def resolve_market_figure(name: str) -> fx.FetchResult:
    """(value, status, fetched_at, url) for one market constant, live-first."""
    source_key, pinned_value, fetch_fn = MARKET_FETCHERS[name]
    return _resolve(
        source_key, pinned_value, fetch_fn,
        no_api_reason=f"{SOURCES_BY_KEY[source_key].access[0].value} publication; no public API",
    )


ADX_MARKET_CAP_BN = resolve_market_figure("adx_market_cap_aed_bn").value
DFM_MARKET_CAP_BN = resolve_market_figure("dfm_market_cap_aed_bn").value
BANK_ASSETS_BN = resolve_market_figure("bank_assets_aed_bn").value
AVG_DAILY_TRADED_VALUE_BN = resolve_market_figure("avg_daily_traded_value_aed_bn").value

LISTED_MARKET_CAP_BN = ADX_MARKET_CAP_BN + DFM_MARKET_CAP_BN  # 4,084.0


def market_basis() -> dict:
    """The figures every exposure number on the dashboard is derived from."""
    adx_fy, dfm_fy, trading_days = 385.0, 174.0, 250
    return {
        "adx_market_cap_aed_bn": ADX_MARKET_CAP_BN,
        "dfm_market_cap_aed_bn": DFM_MARKET_CAP_BN,
        "listed_market_cap_aed_bn": LISTED_MARKET_CAP_BN,
        "avg_daily_traded_value_aed_bn": AVG_DAILY_TRADED_VALUE_BN,
        "bank_assets_aed_bn": BANK_ASSETS_BN,
        "sources": ["cbuae_markets_q4_2025", "cma_market_stats_2025", "adx_fy2025", "dfm_fy2025"],
        "cross_check": {
            "method": "exchange-published FY2025 traded value / trading days",
            "adx_fy2025_traded_aed_bn": adx_fy,
            "dfm_fy2025_traded_aed_bn": dfm_fy,
            "trading_days_assumed": trading_days,
            "implied_daily_aed_bn": round((adx_fy + dfm_fy) / trading_days, 3),
            "cma_reported_daily_aed_bn": AVG_DAILY_TRADED_VALUE_BN,
            "agreement": "within 2%",
        },
    }


def exposure(market_activity_share: float, dependent_fraction: float) -> dict:
    """
    Translate a provider's footprint into national exposure in AED.

    `market_activity_share` is the share of market activity resting on the
    provider, as declared by dependants. `dependent_fraction` is the share of
    enrolled institutions that depend on it.

    Deliberately linear and deliberately not a model: a regulator must be able
    to reproduce these numbers with a calculator.
    """
    share = max(0.0, min(1.0, market_activity_share))
    daily = AVG_DAILY_TRADED_VALUE_BN * share
    return {
        "market_activity_share": round(share, 4),
        "dependent_fraction": round(max(0.0, min(1.0, dependent_fraction)), 4),
        "daily_traded_value_at_risk_aed_bn": round(daily, 3),
        "weekly_traded_value_at_risk_aed_bn": round(daily * 5, 3),
        "listed_market_cap_in_scope_aed_bn": round(LISTED_MARKET_CAP_BN * share, 1),
        "basis": "CBUAE Q4 2025 market report; CMA 2025 average daily traded value",
    }


# --------------------------------------------------------------------------
# k-anonymity calibrated to the real licensed population
# --------------------------------------------------------------------------

#: Cohort sizes as published. Source: cbuae_annual_2025_licensees (Table 4),
#: refreshed monthly from cbuae_cb_register; CMA licensed companies from
#: cma_licensed_companies.
SECTOR_POPULATION: dict[str, dict] = {
    "BANK": {"n": 61, "label": "Banks", "source": "cbuae_annual_2025_licensees"},
    "EXCHANGE_BUSINESS": {"n": 64, "label": "Exchange businesses", "source": "cbuae_annual_2025_licensees"},
    "FINANCE_CO": {"n": 20, "label": "Finance companies", "source": "cbuae_annual_2025_licensees"},
    "FINTECH": {"n": 48, "label": "FinTech companies", "source": "cbuae_annual_2025_licensees"},
    "INSURER": {"n": 58, "label": "Insurance companies", "source": "cbuae_annual_2025_licensees"},
    "INSURANCE_BROKER": {"n": 161, "label": "Insurance brokers", "source": "cbuae_annual_2025_licensees"},
    "TPA": {"n": 20, "label": "Third-party administrators", "source": "cbuae_annual_2025_licensees"},
    "CMA_LICENSED": {"n": 244, "label": "CMA licensed companies", "source": "cma_licensed_companies"},
}

#: A live fetcher per sector, if one exists. Every cohort here is counted from
#: a CBUAE or CMA register published as a PDF or a client-rendered dashboard —
#: neither exposes a public API today, so every entry is None and every
#: resolution is honestly PINNED. Swapping one in later is a one-line change.
POPULATION_FETCHERS: dict[str, Callable[[], fx.FetchResult] | None] = {
    sector: None for sector in SECTOR_POPULATION
}


def resolve_population(sector: str) -> fx.FetchResult:
    """(value, status, fetched_at, url) for one cohort's population, live-first."""
    meta = SECTOR_POPULATION[sector]
    return _resolve(
        meta["source"], meta["n"], POPULATION_FETCHERS.get(sector),
        no_api_reason=f"{meta['label']} register has no public API; read from a government PDF",
    )


#: A cohort statistic may be published only if the contributing institutions are
#: at most this share of the whole cohort. Above it, naming the cohort narrows
#: the field too far and the statistic is itself an identifier.
#:
#: Calibration note: 10% is the point at which the real cohorts split usefully.
#: At the K_FLOOR of 3 institutions it clears banks (3/61 = 4.9%), FinTechs
#: (6.3%) and insurers (5.2%), and correctly refuses the 20-firm cohorts —
#: finance companies and third-party administrators — where 3 of 20 is 15% and a
#: sector-labelled statistic would narrow the field to a handful of candidates.
MAX_COHORT_SHARE = 0.10

#: Never publish on fewer than this many institutions, whatever the share says.
K_FLOOR = 3


@dataclass(frozen=True)
class CohortRule:
    sector: str
    label: str
    population: int
    k_min: int
    max_publishable_share: float
    max_contributors_before_identifying: int
    pooling_required: bool
    rationale: str

    def as_dict(self) -> dict:
        return asdict(self)


def cohort_rule(sector: str) -> CohortRule:
    """
    Derive the publication rule for one cohort from its real population.

    The rule is the *stricter* of two constraints: an absolute floor of K_FLOOR
    institutions, and the requirement that contributors stay under
    MAX_COHORT_SHARE of the cohort. Small cohorts fail the second test at any
    usable k and must be pooled into a wider grouping before publication.
    """
    meta = SECTOR_POPULATION.get(sector)
    if meta is None:
        raise KeyError(f"unknown sector cohort: {sector!r}")

    n = resolve_population(sector).value
    share_at_floor = K_FLOOR / n
    pooling = share_at_floor > MAX_COHORT_SHARE
    ceiling = int(n * MAX_COHORT_SHARE)

    if pooling:
        rationale = (
            f"{K_FLOOR} of {n} {meta['label'].lower()} is {share_at_floor:.0%} of the "
            f"cohort, above the {MAX_COHORT_SHARE:.0%} ceiling — even the minimum "
            f"group of {K_FLOOR} would narrow the field too far, so a statistic "
            f"carrying this sector label must be pooled into a wider grouping."
        )
    else:
        rationale = (
            f"{K_FLOOR} of {n} {meta['label'].lower()} is {share_at_floor:.1%} of the "
            f"cohort, within the {MAX_COHORT_SHARE:.0%} ceiling — publishable with the "
            f"sector label attached, up to {ceiling} contributing institutions."
        )

    return CohortRule(
        sector=sector,
        label=meta["label"],
        population=n,
        k_min=K_FLOOR,
        max_publishable_share=MAX_COHORT_SHARE,
        max_contributors_before_identifying=ceiling,
        pooling_required=pooling,
        rationale=rationale,
    )


def cohort_rules() -> list[CohortRule]:
    """Every cohort, smallest population first — the riskiest are at the top."""
    return sorted(
        (cohort_rule(s) for s in SECTOR_POPULATION),
        key=lambda r: r.population,
    )


def total_enrolled_universe() -> dict:
    """
    The denominator for concentration scoring.

    Concentration is meaningless as a raw count: three firms out of three is a
    single point of failure, three out of three hundred is not. This is the
    'out of' — taken from the licensed population rather than assumed.
    """
    return {
        "cma_licensed_companies": SECTOR_POPULATION["CMA_LICENSED"]["n"],
        "cbuae_banks": SECTOR_POPULATION["BANK"]["n"],
        "addressable_first_wave": (
            SECTOR_POPULATION["BANK"]["n"] + SECTOR_POPULATION["CMA_LICENSED"]["n"]
        ),
        "note": (
            "Banks are licensed by the Central Bank; brokers and investment firms are "
            "licensed by the Capital Markets Authority. These are two separate lists, "
            "so this total just adds them together — it does not remove any firm that "
            "might appear on both."
        ),
        "sources": ["cbuae_annual_2025_licensees", "cma_licensed_companies"],
    }


def registry() -> dict:
    """The whole evidence layer, as served to the dashboard and to reviewers."""
    return {
        "sources": [s.as_dict() for s in SOURCES],
        "unreachable_portals": [dict(p) for p in UNREACHABLE_PORTALS],
        "counts": {
            "total": len(SOURCES),
            "verified": sum(1 for s in SOURCES if s.verification is Verification.VERIFIED),
            "page_verified": sum(1 for s in SOURCES if s.verification is Verification.PAGE_VERIFIED),
            "syndicated": sum(1 for s in SOURCES if s.verification is Verification.SYNDICATED),
            "programmatic": sum(
                1 for s in SOURCES
                if {Access.API, Access.CSV, Access.XLSX} & set(s.access)
            ),
        },
        "known_gap": (
            "No UAE open dataset publishes cyber incidents broken down by financial "
            "sector entity. The CBUAE Financial Stability Report names cyber risk as "
            "systemic without quantifying it. That absence is the gap MARSAD fills, "
            "and stating it is more defensible than inventing a source."
        ),
    }


def population_freshness() -> dict:
    return {
        sector: resolve_population(sector).as_dict() | {"sector": sector, "label": meta["label"]}
        for sector, meta in SECTOR_POPULATION.items()
    }


def market_freshness() -> dict:
    return {name: resolve_market_figure(name).as_dict() for name in MARKET_FETCHERS}


def freshness() -> dict:
    """
    Per-source provenance for every figure the dashboard shows: status, the
    timestamp it was checked, the URL called, and the value currently in use.

    This is the answer to 'is that number live?' — inspectable over the API
    rather than only in the UI, so a judge or a reviewer can check it directly.
    Fetches sequentially; the HTTP route fetches the open-data sources
    concurrently instead, see main.py:data_freshness.
    """
    open_data = {key: fetch_fn().as_dict() for key, fetch_fn in fx.LIVE_FETCHERS.items()}
    return {"open_data": open_data, "population": population_freshness(), "market": market_freshness()}


__all__ = [
    "ADX_MARKET_CAP_BN",
    "AVG_DAILY_TRADED_VALUE_BN",
    "BANK_ASSETS_BN",
    "DFM_MARKET_CAP_BN",
    "K_FLOOR",
    "LISTED_MARKET_CAP_BN",
    "MARKET_FETCHERS",
    "MAX_COHORT_SHARE",
    "POPULATION_FETCHERS",
    "SECTOR_POPULATION",
    "SOURCES",
    "SOURCES_BY_KEY",
    "UNREACHABLE_PORTALS",
    "Access",
    "CohortRule",
    "DataSource",
    "Verification",
    "cohort_rule",
    "cohort_rules",
    "exposure",
    "freshness",
    "market_basis",
    "market_freshness",
    "population_freshness",
    "registry",
    "resolve_market_figure",
    "resolve_population",
    "total_enrolled_universe",
]
