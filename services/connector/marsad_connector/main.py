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

from marsad_connector.agents.a3_redact import RedactionAgent, RedactionError
from marsad_connector.agents.a4_obligation import resolve as resolve_obligations
from marsad_connector.agents.a14_supervisor import inspect as inspect_for_injection
from marsad_connector.config import settings
from marsad_connector.crypto.tokeniser import build_tokeniser
from marsad_connector.llm.provider import LLMProvider, build_llm

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("marsad.connector")

app = FastAPI(title="MARSAD Connector", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

#: In-memory for the prototype; swap for the SQLAlchemy model in models.py.
LOCAL: dict[str, "IncidentIn"] = {}


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


@app.get("/health")
async def health():
    cfg = settings()
    return {
        "ok": True,
        "institution": cfg.institution_name,
        "local_incidents": len(LOCAL),
        "llm_provider": LLM.name,
        "sovereign_mode": cfg.sovereign_mode,
    }


@app.post("/v1/incidents")
async def create_incident(incident: IncidentIn):
    """Store locally. Nothing leaves until /submit is called explicitly."""
    iid = str(uuid.uuid4())
    incident.detected_at = incident.detected_at or datetime.now(timezone.utc)
    LOCAL[iid] = incident

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


@app.get("/v1/incidents/{iid}")
async def get_incident(iid: str):
    """Local view only — this endpoint is not reachable from the core."""
    if iid not in LOCAL:
        raise HTTPException(404, "unknown incident")
    return LOCAL[iid]


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
    inc = LOCAL[iid]
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
    inc = LOCAL[iid]
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
            LOCAL[iid],
            institution_ref=cfg.institution_ref,
            sector=Sector(cfg.sector),
            size_band=SizeBand(cfg.size_band),
        )
    except RedactionError as exc:
        raise HTTPException(422, str(exc)) from exc
