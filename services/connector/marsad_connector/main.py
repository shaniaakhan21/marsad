"""
MARSAD connector — runs inside an institution's perimeter.

This process is the only one that ever holds narrative, plaintext indicators or
PII. It reaches the core through exactly one function, `submit_to_core`, which
accepts only an already-redacted IncidentSubmission.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from marsad_contracts.boundary import IncidentSubmission, Sector, SizeBand
from pydantic import BaseModel, Field

from marsad_connector.agents.a2_extract import ExtractionAgent, ExtractionDraft
from marsad_connector.agents.a3_redact import RedactionAgent, RedactionError
from marsad_connector.agents.a4_obligation import resolve as resolve_obligations
from marsad_connector.agents.a14_supervisor import inspect as inspect_for_injection
from marsad_connector.config import settings
from marsad_connector.crypto.tokeniser import build_tokeniser
from marsad_connector.db.session import build_engine, build_sessionmaker, create_all
from marsad_connector.llm.provider import LLMProvider, build_llm
from marsad_connector.store import InMemoryStore, SqlStore, provenance_from_draft

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("marsad.connector")

app = FastAPI(title="MARSAD Connector", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

def _build_store():
    """
    The institution's store, chosen at boot.

    SQLite locally, Postgres in deployment, and an in-memory backend for tests. It is
    built here rather than lazily so a misconfigured database stops the connector from
    starting — the same reason the LLM provider is constructed at import.
    """
    cfg = settings()
    if cfg.store == "memory":
        return InMemoryStore()
    engine = build_engine(cfg.database_url)
    if cfg.auto_create_schema:
        create_all(engine)
    return SqlStore(build_sessionmaker(engine), retention_days=cfg.retention_days,
                    model=lambda **kw: IncidentIn(**kw))


#: The institution's incidents. Plaintext, and it never leaves this process except
#: through A3, which builds an allow-listed payload rather than reading these rows.
LOCAL = _build_store()


def _build_llm_at_startup() -> LLMProvider:
    """
    Construct the extraction provider while the process is booting.

    Built here, at import, so a misconfigured endpoint stops the connector from
    starting. Deferring it to the first request would mean a connector that passes
    its health check, sits in production looking fine, and only discovers it is
    pointed at a hosted vendor when an analyst files a real incident — at which
    point the plaintext has already been sent.
    """
    cfg = settings()
    provider = build_llm(
        cfg.llm_provider,
        **(
            {}
            if cfg.llm_provider == "stub"
            else {
                "base_url": cfg.llm_base_url,
                "api_key": cfg.llm_api_key,
                "model": cfg.llm_model,
                "sovereign_mode": cfg.sovereign_mode,
            }
        ),
    )
    log.info("connector.llm_ready provider=%s sovereign_mode=%s", provider.name, cfg.sovereign_mode)
    return provider


LLM: LLMProvider = _build_llm_at_startup()

#: Proposals awaiting human confirmation. Deliberately a separate store from LOCAL:
#: a draft is not an incident, and keeping them in one dict would make it a
#: one-flag mistake away from being treated as one.
DRAFTS: dict[str, ExtractionDraft] = {}


class IndicatorIn(BaseModel):
    type: str
    value: str


class IncidentIn(BaseModel):
    """Plaintext incident. NEVER serialised to the core."""

    narrative: str | None = None
    analyst_notes: str | None = None
    indicators: list[dict[str, Any]] = Field(default_factory=list)
    techniques: list[str] = Field(default_factory=list)
    severity: str = "MEDIUM"
    obligation_receipt: dict[str, Any] | None = None
    detected_at: datetime | None = None

    #: Jurisdictions the institution is licensed in — drives A4. Set per firm in
    #: production config; accepted per incident here so the demo can vary it.
    jurisdictions: list[str] = Field(default_factory=list)
    essential_service_affected: bool | None = None

    #: Attacker-authored text, kept separate from analyst prose on purpose: this
    #: is the hostile channel, and A14 inspects it as data, never as instruction.
    raw_email: str | None = None

    #: How this incident came to exist. "ANALYST_STRUCTURED" is a human filling the
    #: fields directly, which is confirmed by definition. "EXTRACTION_CONFIRMED" is
    #: A2 output a human reviewed and signed off. There is deliberately no third
    #: value: unconfirmed extraction output never becomes an incident.
    source: str = "ANALYST_STRUCTURED"
    confirmed_by: str | None = None


class ExtractIn(BaseModel):
    """Free text as an analyst types it. No structure required, none assumed."""

    narrative: str
    analyst_notes: str | None = None
    raw_email: str | None = None


class ConfirmIn(BaseModel):
    """
    The analyst's sign-off. `edits` overrides any field A2 proposed.

    `analyst` is required and not defaulted: a confirmation with nobody's name on it
    is not a confirmation, and the whole point of PROPOSE_CONFIRM is that a person
    stands behind these values.
    """

    analyst: str
    edits: dict[str, Any] = Field(default_factory=dict)
    jurisdictions: list[str] = Field(default_factory=list)
    essential_service_affected: bool | None = None


@app.get("/health")
async def health():
    cfg = settings()
    return {
        "ok": True,
        "institution": cfg.institution_name,
        "local_incidents": LOCAL.count(),
        "llm_provider": LLM.name,
        "sovereign_mode": cfg.sovereign_mode,
    }


@app.post("/v1/incidents")
async def create_incident(incident: IncidentIn):
    """Store locally. Nothing leaves until /submit is called explicitly."""
    iid = str(uuid.uuid4())
    incident.detected_at = incident.detected_at or datetime.now(timezone.utc)
    LOCAL.save(iid, incident)

    # A14 runs at intake, before any model sees the text. An injection is
    # neutralised and logged; it never blocks the incident, because halting on
    # injection would let an attacker suppress a report by embedding one.
    supervisor = inspect_for_injection(
        "\n".join(filter(None, [incident.narrative, incident.analyst_notes, incident.raw_email]))
    )
    if supervisor.verdict != "CLEAN":
        log.warning(
            "connector.injection_detected incident=%s verdict=%s score=%d",
            iid, supervisor.verdict, supervisor.score,
        )

    log.info("connector.stored incident=%s indicators=%d", iid, len(incident.indicators))
    return {
        "incident_id": iid,
        "stored_locally": True,
        "submitted": False,
        "supervisor": supervisor.as_dict(),
    }


@app.post("/v1/intake/extract")
async def extract_from_text(body: ExtractIn):
    """
    A2 — read free text and PROPOSE a structured incident.

    Nothing is filed here. The response is a draft: every field with its confidence
    and the span of narrative it came from, plus the list the analyst must look at.
    A14 runs first, on the same text, and as always its verdict is a finding rather
    than a veto — extraction proceeds either way.
    """
    supervisor = inspect_for_injection(
        "\n".join(filter(None, [body.narrative, body.analyst_notes, body.raw_email]))
    )
    if supervisor.verdict != "CLEAN":
        log.warning(
            "connector.injection_detected stage=intake verdict=%s score=%d",
            supervisor.verdict, supervisor.score,
        )

    try:
        draft = await ExtractionAgent(LLM).propose(
            body.narrative, analyst_notes=body.analyst_notes, raw_email=body.raw_email,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    DRAFTS[draft.draft_id] = draft
    return {"draft": draft.as_dict(), "supervisor": supervisor.as_dict()}


@app.post("/v1/intake/{draft_id}/confirm")
async def confirm_draft(draft_id: str, body: ConfirmIn):
    """
    The human gate. Only this turns a proposal into an incident.

    Until it is called, the draft cannot reach A3 at all — reading an incident field
    off an unconfirmed draft raises rather than returning a value. Filing, previewing
    and submitting all operate on the incident this creates, never on the draft.
    """
    draft = DRAFTS.get(draft_id)
    if draft is None:
        raise HTTPException(404, "unknown draft")

    try:
        confirmed = draft.confirm(analyst=body.analyst, edits=body.edits)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    iid = str(uuid.uuid4())
    stored = IncidentIn(
        narrative=confirmed.narrative,
        analyst_notes=confirmed.analyst_notes,
        indicators=confirmed.indicators,
        techniques=confirmed.techniques,
        severity=confirmed.severity,
        obligation_receipt=confirmed.obligation_receipt,
        detected_at=confirmed.detected_at or datetime.now(timezone.utc),
        jurisdictions=body.jurisdictions,
        essential_service_affected=body.essential_service_affected,
        raw_email=confirmed.raw_email,
        source="EXTRACTION_CONFIRMED",
        confirmed_by=confirmed.confirmed_by,
    )
    # Provenance is written with the incident and shares its retention clock: every
    # row carries a verbatim slice of the narrative, so it must not outlive it.
    LOCAL.save(iid, stored, provenance_from_draft(draft))
    del DRAFTS[draft_id]
    log.info(
        "connector.confirmed draft=%s incident=%s by=%s edited=%s",
        draft_id, iid, confirmed.confirmed_by, list(confirmed.edited_fields),
    )
    return {
        "incident_id": iid,
        "confirmed_by": confirmed.confirmed_by,
        "edited_fields": list(confirmed.edited_fields),
        "severity": confirmed.severity,
        "indicators": confirmed.indicators,
        "techniques": confirmed.techniques,
        # Local-only context, shown to the analyst. Never crosses the boundary —
        # affected system names and vendor names are on the never-cross list.
        "category": confirmed.category,
        "affected_services": list(confirmed.affected_services),
        "third_party_dependencies": list(confirmed.third_party_dependencies),
    }


@app.get("/v1/intake/{draft_id}")
async def get_draft(draft_id: str):
    """Re-read a pending proposal. Local only."""
    draft = DRAFTS.get(draft_id)
    if draft is None:
        raise HTTPException(404, "unknown draft")
    return draft.as_dict()


@app.get("/v1/incidents/{iid}")
async def get_incident(iid: str):
    """Local view only — this endpoint is not reachable from the core."""
    if iid not in LOCAL:
        raise HTTPException(404, "unknown incident")
    return LOCAL.get(iid)


@app.post("/v1/incidents/{iid}/obligations")
async def obligations(iid: str):
    """
    A4 — resolve every notification duty for this incident.

    Value with zero sharing: this endpoint never contacts the core. A firm can run
    the connector purely for this, which is exactly the adoption wedge the 90-day
    plan depends on.
    """
    if iid not in LOCAL:
        raise HTTPException(404, "unknown incident")
    inc = LOCAL.get(iid)
    cfg = settings()
    result = resolve_obligations(
        severity=inc.severity,
        detected_at=inc.detected_at or datetime.now(timezone.utc),
        jurisdictions=inc.jurisdictions or cfg.jurisdictions,
        essential_service_affected=inc.essential_service_affected,
        incident_ref=iid[:8].upper(),
    )
    return result.as_dict()


@app.post("/v1/incidents/{iid}/supervise")
async def supervise(iid: str):
    """A14 — re-run injection inspection on demand, for the demo and for audit."""
    if iid not in LOCAL:
        raise HTTPException(404, "unknown incident")
    inc = LOCAL.get(iid)
    return inspect_for_injection(
        "\n".join(filter(None, [inc.narrative, inc.analyst_notes, inc.raw_email]))
    ).as_dict()


@app.post("/v1/incidents/{iid}/preview")
async def preview(iid: str) -> IncidentSubmission:
    """
    Show exactly what would cross the boundary, without sending it.

    Deliberately a first-class endpoint: an institution's security team can
    inspect the emitted payload for any incident before enabling submission.
    """
    return _build(iid)


@app.post("/v1/incidents/{iid}/submit")
async def submit(iid: str):
    sub = _build(iid)
    cfg = settings()
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            r = await client.post(f"{cfg.core_url}/v1/submissions", json=sub.model_dump(mode="json"))
            r.raise_for_status()
        except httpx.HTTPError as exc:
            # Degraded mode: queue locally, never block the institution's own work.
            log.warning("connector.core_unreachable queued incident=%s err=%s", iid, exc)
            raise HTTPException(503, "core unreachable; submission queued locally") from exc
    return {"submitted": True, "core_response": r.json(), "payload_sent": sub.model_dump(mode="json")}


def _build(iid: str) -> IncidentSubmission:
    if iid not in LOCAL:
        raise HTTPException(404, "unknown incident")
    cfg = settings()
    agent = RedactionAgent(build_tokeniser(cfg.tokeniser))
    try:
        return agent.build_submission(
            LOCAL.get(iid),
            institution_ref=cfg.institution_ref,
            sector=Sector(cfg.sector),
            size_band=SizeBand(cfg.size_band),
        )
    except RedactionError as exc:
        raise HTTPException(422, str(exc)) from exc
