"""MARSAD core — receives boundary payloads, never plaintext."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from marsad_contracts.boundary import IncidentSubmission

from marsad_core.config import settings
from marsad_core.data import fetchers as fx
from marsad_core.data import roadmap as roadmap_data
from marsad_core.data import uae_open_data as od
from marsad_core.db.session import build_engine, build_sessionmaker, create_all
from marsad_core.engines.correlation import CorrelationEngine
from marsad_core.engines.similarity import build_similarity_engine
from marsad_core.services.concentration import (
    ProviderDependency,
    Substitutability,
    rank,
)
from marsad_core.store import InMemoryStore, SqlStore, rehydrate

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("marsad.core")

STATE: dict = {}


# --------------------------------------------------------------------------
# Seed dependencies
#
# The providers below are real, named UAE shared infrastructure — Aani, Jaywan
# and UAESWITCH are national rails documented in CBUAE publications, which is
# what makes them the textbook concentration case. The *dependency edges* are
# illustrative for the prototype: which firm depends on which provider can only
# come from the firms themselves, and no firm has declared to us yet.
# --------------------------------------------------------------------------

SEED_DEPENDENCIES: list[ProviderDependency] = [
    ProviderDependency(
        provider="UAESWITCH / Jaywan (domestic card routing)",
        service="Domestic POS and ATM transaction routing",
        dependent_refs=("psd_almaha01", "psd_gulfsec02", "psd_emcap03"),
        market_activity_share=0.46,
        substitutability=Substitutability.NO,
    ),
    ProviderDependency(
        provider="Aani (instant payment platform)",
        service="24/7 instant retail transfers, 12.5 m users",
        dependent_refs=("psd_almaha01", "psd_gulfsec02"),
        market_activity_share=0.31,
        substitutability=Substitutability.PARTIAL,
    ),
    ProviderDependency(
        provider="Shared KYC / identity verification vendor",
        service="Onboarding identity verification",
        dependent_refs=("psd_almaha01", "psd_gulfsec02", "psd_emcap03"),
        market_activity_share=0.22,
        substitutability=Substitutability.NO,
    ),
    ProviderDependency(
        provider="Single-region cloud hosting",
        service="Core application hosting",
        dependent_refs=("psd_gulfsec02", "psd_emcap03"),
        market_activity_share=0.18,
        substitutability=Substitutability.PARTIAL,
        inferred=True,
    ),
    ProviderDependency(
        provider="Market data feed vendor",
        service="Price and reference data",
        dependent_refs=("psd_emcap03",),
        market_activity_share=0.07,
        substitutability=Substitutability.YES,
    ),
]


@asynccontextmanager
async def lifespan(_: FastAPI):
    cfg = settings()
    STATE["engine"] = CorrelationEngine(
        build_similarity_engine(cfg.similarity_engine),
        k_anonymity=cfg.k_anonymity,
        similarity_threshold=cfg.similarity_threshold,
    )
    STATE["hits"] = []
    STATE["deps"] = list(SEED_DEPENDENCIES)

    # The store of record. The engine's token index is a cache rebuilt from it — see
    # store.py. A core that restarted without rehydrating would find no matches
    # against anything submitted before the restart and report that as "no
    # correlation", which is a silent false negative and the worst failure mode here.
    if cfg.store == "memory":
        STATE["store"] = InMemoryStore()
    else:
        db_engine = build_engine(cfg.database_url)
        if cfg.auto_create_schema:
            create_all(db_engine)
        STATE["db_engine"] = db_engine
        STATE["store"] = SqlStore(build_sessionmaker(db_engine))
        rehydrate(STATE["engine"], STATE["store"])

    log.info(
        "core.ready similarity=%s k=%d store=%s",
        cfg.similarity_engine, cfg.k_anonymity, STATE["store"].name,
    )
    yield


app = FastAPI(title="MARSAD Core", version="0.2.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
async def health():
    return {
        "ok": True,
        "submissions": STATE["store"].submission_count(),
        "store": STATE["store"].name,
    }


@app.post("/v1/submissions")
async def submit(sub: IncidentSubmission):
    """
    The only ingress for incident data. FastAPI validates against the boundary
    contract before this function body runs, so a payload carrying a forbidden
    field is rejected at the edge of the process with a 422.
    """
    engine: CorrelationEngine = STATE["engine"]
    hits = engine.ingest(sub)
    STATE["hits"].extend(hits)

    # Persist after matching, never before: the engine is idempotent on
    # submission_id, and writing first would let a retry be counted twice by one side
    # and once by the other.
    store = STATE["store"]
    store.save_submission(sub)
    store.save_correlations(hits)

    return {
        "accepted": True,
        "submission_id": sub.submission_id,
        "correlations": [
            {
                "kind": h.kind,
                "peer_count": len(h.institution_refs) - 1,
                "indicator_type": h.indicator_type,
                "shared_techniques": list(h.shared_techniques),
                "similarity": h.similarity,
                "reduced_fidelity": h.reduced_fidelity,
                "campaign_id": h.campaign_id,
                "publishable_as_aggregate": engine.may_publish_aggregate(h),
            }
            for h in hits
        ],
    }


@app.get("/v1/correlations")
async def correlations():
    engine: CorrelationEngine = STATE["engine"]
    return [
        {
            "kind": h.kind,
            "institutions": len(h.institution_refs),
            "indicator_type": h.indicator_type,
            "shared_techniques": list(h.shared_techniques),
            "similarity": h.similarity,
            "reduced_fidelity": h.reduced_fidelity,
            "campaign_id": h.campaign_id,
            "detected_at": h.detected_at,
            "publishable_as_aggregate": engine.may_publish_aggregate(h),
        }
        for h in STATE["hits"]
    ]


@app.get("/v1/concentration")
async def concentration(total_participants: int | None = None):
    """
    Ranked single points of failure, each carrying its exposure in AED.

    On the choice of denominator
    ---------------------------
    Concentration is a *fraction*, so the denominator decides the answer, and
    there are two defensible ones. Scoring against the whole licensed market
    (244 CMA-licensed companies) makes every provider look harmless while
    coverage is low — 3 of 244 is 1%, and the score would say LOW about a
    provider all three enrolled firms cannot operate without. Scoring against
    the enrolled participants answers the question MARSAD can actually observe:
    of the firms reporting to us, how many rest on this provider?

    So we score against the enrolled sample and publish the market coverage
    alongside it, rather than quietly choosing whichever denominator flatters
    the number. A score of CRITICAL at 1.2% coverage is a finding about three
    firms, not about the market, and the response says so.
    """
    deps = STATE["deps"]
    enrolled = {ref for d in deps for ref in d.dependent_refs}
    total = total_participants or len(enrolled) or 1
    licensed = od.SECTOR_POPULATION["CMA_LICENSED"]["n"]

    by_provider = {d.provider: d for d in deps}
    ranked = rank(deps, total_participants=total)

    out = []
    for s in ranked:
        dep = by_provider[s.provider]
        row = s.__dict__ | {
            "service": dep.service,
            "substitutability": dep.substitutability.value,
            "inferred": dep.inferred,
            "exposure": od.exposure(
                dep.market_activity_share, len(dep.dependent_refs) / total
            ),
        }
        out.append(row)

    return {
        "total_participants": total,
        "licensed_population": licensed,
        "market_coverage": round(total / licensed, 4),
        "coverage_caveat": (
            f"These scores cover the {total} firm(s) in this demo — "
            f"{total / licensed:.1%} of the {licensed} licensed firms in the UAE. "
            f"It becomes a market-wide picture as more firms join."
        ),
        "providers": out,
        "basis": od.market_basis(),
    }


# --------------------------------------------------------------------------
# Evidence layer — open data, privacy calibration, execution plan
# --------------------------------------------------------------------------


@app.get("/v1/data/sources")
async def data_sources():
    """Every government publication this system relies on, with its provenance."""
    return od.registry()


@app.get("/v1/data/market")
async def data_market():
    """The verified market figures that every AED number is derived from."""
    return od.market_basis()


@app.get("/v1/data/cohorts")
async def data_cohorts():
    """
    Publication rules derived from the real licensed population.

    This is the answer to 'why k=3?' — it is not a constant we picked, it is a
    constraint that falls out of how many institutions actually exist in each
    licensed cohort.
    """
    return {
        "k_floor": od.K_FLOOR,
        "max_cohort_share": od.MAX_COHORT_SHARE,
        "universe": od.total_enrolled_universe(),
        "cohorts": [r.as_dict() for r in od.cohort_rules()],
    }


@app.get("/v1/roadmap")
async def roadmap():
    """The 90-day execution plan with gates, owners and evidence per milestone."""
    return roadmap_data.plan()


@app.get("/v1/data/freshness")
async def data_freshness():
    """
    Per source: LIVE / CACHED / PINNED, the timestamp checked, the URL called,
    and the value currently in use — provenance a judge can inspect directly.

    The live/cached/pinned sources are fetched concurrently so an offline venue
    network costs one timeout window, not one per source.
    """
    open_data_keys = list(fx.LIVE_FETCHERS)
    open_data_values = await asyncio.gather(
        *(asyncio.to_thread(fx.LIVE_FETCHERS[k]) for k in open_data_keys)
    )
    open_data = {k: r.as_dict() for k, r in zip(open_data_keys, open_data_values)}

    return {
        "open_data": open_data,
        "population": od.population_freshness(),
        "market": od.market_freshness(),
    }
