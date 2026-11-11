"""MARSAD core — receives boundary payloads, never plaintext."""
from __future__ import annotations

import asyncio
import hashlib
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from marsad_contracts.boundary import (
    Declaration,
    DependencyDeclaration,
    IncidentSubmission,
    ProviderAlert,
    ProviderIncidentDeclaration,
)
from marsad_contracts.digest import payload_digest

from marsad_core.config import settings
from marsad_core.data import fetchers as fx
from marsad_core.data import roadmap as roadmap_data
from marsad_core.data import uae_open_data as od
from marsad_core.db.session import build_engine, build_sessionmaker, create_all
from marsad_core.engines.correlation import CorrelationEngine
from marsad_core.engines.similarity import build_similarity_engine
from marsad_core.ledger.anchoring import Anchorer
from marsad_core.ledger.backends import BesuLedger, LedgerBackend, LocalChainLedger
from marsad_core.security import (
    assert_bound_to,
    connector_identity,
    console_role,
    parse_origins,
)
from marsad_core.services import providers as provider_service
from marsad_core.services import regulator as regulator_view
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


def _build_ledger(cfg, factory) -> LedgerBackend:
    if cfg.ledger_backend == "besu":
        return BesuLedger(cfg.besu_rpc_url, cfg.besu_contract_address, cfg.besu_private_key,
                          cfg.besu_artifact_path)
    return LocalChainLedger(factory)


async def _anchor_loop(anchorer: Anchorer, interval_seconds: int) -> None:
    """Anchor on a timer. A failed round is logged and retried; submissions never wait."""
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            await asyncio.to_thread(anchorer.run_once)
        except Exception:  # the audit trail may lag, but it must not stop for good
            log.exception("core.anchor_run_failed")


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
    STATE["directory"] = provider_service.parse_directory(cfg.provider_directory)

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
        factory = build_sessionmaker(db_engine)
        STATE["store"] = SqlStore(factory)
        STATE["anchorer"] = Anchorer(factory, _build_ledger(cfg, factory), STATE["store"])
        rehydrate(STATE["engine"], STATE["store"])
        # Rehydration re-finds old matches and discards them, correctly — they were
        # stored when first found. The list the dashboard reads comes from the store.
        STATE["hits"] = STATE["store"].all_correlations()

    log.info(
        "core.ready similarity=%s k=%d store=%s",
        cfg.similarity_engine, cfg.k_anonymity, STATE["store"].name,
    )
    anchor_task = None
    if STATE.get("anchorer") is not None and cfg.anchor_interval_seconds > 0:
        anchor_task = asyncio.create_task(
            _anchor_loop(STATE["anchorer"], cfg.anchor_interval_seconds))
    yield
    if anchor_task is not None:
        anchor_task.cancel()


app = FastAPI(title="MARSAD Core", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=parse_origins(settings().cors_origins),
    allow_methods=["GET", "POST"],
    allow_headers=["authorization", "content-type"],
)


@app.get("/health")
async def health():
    cfg = settings()
    return {
        "ok": True,
        "submissions": STATE["store"].submission_count(),
        "store": STATE["store"].name,
        # Reported so a core without enforcement cannot be mistaken for one with it.
        "client_identity_required": cfg.require_client_identity,
        "console_auth_required": bool(cfg.console_tokens),
    }


@app.post("/v1/submissions")
async def submit(
    sub: IncidentSubmission,
    certified: Annotated[str | None, Depends(connector_identity)],
):
    """
    The only ingress for incident data. FastAPI validates against the boundary
    contract before this function body runs, so a payload carrying a forbidden
    field is rejected at the edge of the process with a 422.
    """
    assert_bound_to(certified, sub.institution_ref)

    engine: CorrelationEngine = STATE["engine"]
    hits = engine.ingest(sub)
    STATE["hits"].extend(hits)

    # Persist after matching, never before: the engine is idempotent on
    # submission_id, and writing first would let a retry be counted twice by one side
    # and once by the other.
    store = STATE["store"]
    digest = store.save_submission(sub)
    store.save_correlations(hits)

    return {
        "accepted": True,
        "submission_id": sub.submission_id,
        # What the core now holds under this id, so the sender can check it against
        # its own record of what it sent. See marsad_contracts/digest.py.
        "payload_digest": digest,
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


#: Notices returned per request. A firm further behind than this catches up over polls.
MAX_NOTICES_PER_POLL = 500


@app.get("/v1/notices")
async def notices(
    institution_ref: str,
    certified: Annotated[str | None, Depends(connector_identity)],
    since: datetime | None = None,
):
    """
    A firm collecting its own rung-0 notices: read-only, and the only way one reaches it.

    The core may not call into an institution, so a firm that reported before its peers
    has no other way to learn it was matched. `POST /v1/submissions` remains the only
    route that accepts anything from a firm. This one takes a pseudonym and a timestamp.

    Bound to the caller's certificate, because a notice is what one firm knows about
    itself. How many peers matched and on which technique is not another firm's to read.
    """
    assert_bound_to(certified, institution_ref)
    if since is not None and since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)

    engine: CorrelationEngine = STATE["engine"]
    out = [
        notice
        for hit in sorted(STATE["hits"], key=lambda h: h.detected_at)
        if institution_ref in hit.institution_refs and (since is None or hit.detected_at > since)
        for ref, notice in engine.notices_for(hit)
        if ref == institution_ref
    ]
    return {
        "notices": [n.model_dump(mode="json") for n in out[:MAX_NOTICES_PER_POLL]],
        "provider_alerts": _provider_alerts_for(institution_ref),
    }


def _provider_alerts_for(institution_ref: str) -> list[dict]:
    """Recent incidents at providers this firm declared. Ids differ per firm, as for notices."""
    store = STATE["store"]
    cutoff = datetime.now(timezone.utc) - timedelta(
        days=provider_service.PROVIDER_ALERT_WINDOW_DAYS)
    return [
        ProviderAlert(
            alert_id=hashlib.sha256(
                f"{d.declaration_id}:{institution_ref}".encode()).hexdigest()[:32],
            provider_token=d.provider_token, severity_band=d.severity_band,
            ts_bucket=d.ts_bucket,
        ).model_dump(mode="json")
        for d in store.provider_incidents_for(store.tokens_declared_by(institution_ref), cutoff)
    ]


@app.post("/v1/declarations")
async def declare(
    declaration: Declaration,
    certified: Annotated[str | None, Depends(connector_identity)],
):
    """
    A firm's provider list, or an enrolled provider's incident. Tokens and bands only.

    A provider incident is accepted only from the pseudonym the directory names as that
    provider. Otherwise any participant could warn the market of an outage that never
    happened, at a provider it has nothing to do with.
    """
    assert_bound_to(certified, declaration.institution_ref)
    store = STATE["store"]
    digest = payload_digest(declaration)

    if isinstance(declaration, DependencyDeclaration):
        applied = store.replace_dependencies(declaration)
        return {"accepted": True, "applied": applied, "payload_digest": digest}

    assert isinstance(declaration, ProviderIncidentDeclaration)
    entry = STATE["directory"].get(declaration.provider_token)
    if entry is None or entry.owner_ref != declaration.institution_ref:
        log.warning("core.provider_incident_refused claimed_by=%s", declaration.institution_ref)
        raise HTTPException(403, "this pseudonym is not enrolled as that provider")
    store.save_provider_incident(declaration)
    # The one thing a provider learns: how many firms rely on it, never which.
    return {"accepted": True, "payload_digest": digest,
            "dependents_notified": store.dependents_of(declaration.provider_token)}


@app.get("/v1/correlations", dependencies=[Depends(console_role)])
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


@app.get("/v1/concentration", dependencies=[Depends(console_role)])
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
    # What firms declared replaces the illustrative seed as soon as any of it is
    # publishable. Until then the seed is shown, and the response says that it is.
    declared, held_back = provider_service.declared_dependencies(
        STATE["store"].dependency_rows(), STATE["directory"], settings().k_anonymity,
    )
    deps = declared or STATE["deps"]
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
        "data_basis": "DECLARED" if declared else "ILLUSTRATIVE_SEED",
        "declarations_held_back": held_back,
        "basis": od.market_basis(),
    }


@app.get("/v1/regulator/overview", dependencies=[Depends(console_role)])
async def regulator_overview():
    """Campaigns, sectors, trends and shared-provider risk. Aggregates only; see the module."""
    engine: CorrelationEngine = STATE["engine"]
    return regulator_view.overview(
        STATE["store"].all_submissions(), STATE["hits"], k=settings().k_anonymity,
        may_publish=engine.may_publish_aggregate,
        concentration=await concentration(),
    )


# --------------------------------------------------------------------------
# Audit ledger — open to anyone holding a receipt. Hashes only, nothing about who.
# --------------------------------------------------------------------------


def _anchorer() -> Anchorer:
    anchorer = STATE.get("anchorer")
    if anchorer is None:
        raise HTTPException(503, "the audit ledger needs the sql store")
    return anchorer


@app.get("/v1/ledger")
async def ledger_status():
    return _anchorer().status()


@app.get("/v1/receipts/{receipt}/proof")
async def receipt_proof(receipt: str):
    """Whether this receipt is anchored, and whether its record is still what was anchored."""
    if len(receipt) != 64 or any(c not in "0123456789abcdef" for c in receipt):
        raise HTTPException(422, "a receipt is 64 lowercase hex characters")
    result = await asyncio.to_thread(_anchorer().proof, receipt)
    if result is None:
        raise HTTPException(404, "unknown receipt")
    return result


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
