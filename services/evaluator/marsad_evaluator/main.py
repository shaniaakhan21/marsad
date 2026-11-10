"""
One key custodian's evaluator.

Three parties each run one of these (proposed: CMA, the UAE Cybersecurity Council and a
rotating participating firm). It holds one Shamir share of the token key and does one
thing: multiply a blinded element by that share and prove it did.

What it can and cannot learn. The elements it receives are uniformly random group
elements, different on every request even for the same indicator, so it cannot tell
what was tokenised or whether it has seen it before. It does learn which firm asked and
how many elements were in the batch, because metering needs both.

Why the meter is the control that matters. An OPRF stops anyone computing tokens
offline, but a firm with evaluator access can still ask for tokens online, one candidate
at a time, and enumerating IPv4 that way is the remaining attack. It requires billions
of evaluations, so a per-client daily budget turns it from silent into refused, and the
audit log turns any attempt into a record each custodian holds independently.

Nothing here is on the critical path of an incident. If a quorum is unreachable the
connector cannot build a submission and says so; the firm's own work continues.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from marsad_contracts.boundary import OprfEvaluationRequest, OprfEvaluationResponse
from marsad_oprf import group, voprf
from marsad_oprf.threshold import KeyShare
from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger("marsad.evaluator")

_CN = re.compile(r"(?:^|,)\s*CN=([a-z0-9_\-]{6,64})(?:,|$)")

#: Elements one client may have evaluated per UTC day. An incident carries at most 512;
#: this allows about ten maximal incidents, and is about a millionth of what walking
#: IPv4 would need. A reviewer may tune it. It should stay nowhere near 2^32.
DEFAULT_DAILY_ELEMENT_BUDGET = 5000


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MARSAD_EVALUATOR_", extra="ignore")

    #: This custodian's share as JSON, or `share_file` naming a file that holds it.
    share_json: str = ""
    share_file: str = ""
    daily_element_budget: int = DEFAULT_DAILY_ELEMENT_BUDGET
    audit_log: str = "./evaluator-audit.jsonl"

    #: Require a verified certificate subject from the gateway. Off only on one laptop.
    require_client_identity: bool = False


@lru_cache
def settings() -> Settings:
    return Settings()


def load_share(cfg: Settings) -> KeyShare:
    raw = cfg.share_json or (Path(cfg.share_file).read_text() if cfg.share_file else "")
    if not raw:
        raise RuntimeError(
            "no key share configured. Set MARSAD_EVALUATOR_SHARE_JSON or _SHARE_FILE; "
            "see scripts/oprf_keygen.py."
        )
    share = KeyShare(**json.loads(raw))
    group.validate_scalar(share.scalar)
    return share


@dataclass
class Meter:
    """
    Per-client daily counts, backed by an append-only audit log.

    The log is replayed on start, because a limit that a restart resets is a limit an
    attacker waits out. It records who, when, how many and the decision; never the
    elements, since a custodian keeping them could later correlate repeat requests.
    """

    path: Path
    budget: int

    def __post_init__(self) -> None:
        self._lock = threading.Lock()
        self._used: dict[tuple[str, date], int] = defaultdict(int)
        if self.path.exists():
            for line in self.path.read_text().splitlines():
                entry = json.loads(line)
                if entry["decision"] == "EVALUATED":
                    day = datetime.fromisoformat(entry["at"]).date()
                    self._used[(entry["client"], day)] += entry["elements"]

    def _append(self, entry: dict) -> None:
        with self.path.open("a") as handle:
            handle.write(json.dumps(entry) + "\n")

    def charge(self, client: str, epoch: int, elements: int) -> bool:
        """Spend budget and record the decision. False means refuse the request."""
        now = datetime.now(timezone.utc)
        with self._lock:
            key = (client, now.date())
            allowed = self._used[key] + elements <= self.budget
            if allowed:
                self._used[key] += elements
            self._append({
                "at": now.isoformat(), "client": client, "epoch": epoch, "elements": elements,
                "decision": "EVALUATED" if allowed else "REFUSED_OVER_BUDGET",
            })
        return allowed

    def usage(self) -> dict[str, int]:
        today = datetime.now(timezone.utc).date()
        with self._lock:
            return {c: n for (c, d), n in self._used.items() if d == today}


def caller(
    request: Request,
    x_client_cert_subject: Annotated[str | None, Header()] = None,
    x_marsad_client: Annotated[str | None, Header()] = None,
) -> str:
    """Who is spending budget. Certified when enforced; a self-reported label if not."""
    if request.app.state.cfg.require_client_identity:
        match = _CN.search(x_client_cert_subject or "")
        if match is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "a client certificate is required")
        return match.group(1)
    return (x_marsad_client or "unauthenticated")[:64]


def create_app(cfg: Settings | None = None) -> FastAPI:
    """A factory, so three custodians are three instances rather than three modules."""
    cfg = cfg or settings()
    share = load_share(cfg)
    public = share.public
    meter = Meter(Path(cfg.audit_log), cfg.daily_element_budget)

    app = FastAPI(title="MARSAD key custodian", version="0.1.0",
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.state.meter = meter
    app.state.cfg = cfg

    @app.get("/health")
    def health() -> dict:
        return {"ok": True, "index": share.index, "epoch": share.epoch,
                "threshold": share.threshold, "parties": share.parties,
                "client_identity_required": cfg.require_client_identity}

    @app.get("/v1/oprf/metering")
    def metering() -> dict:
        """Today's evaluations per client. Not forwarded by the gateway: custodian-only."""
        return {"budget_per_client": cfg.daily_element_budget, "used_today": meter.usage()}

    @app.post("/v1/oprf/evaluate")
    def evaluate(
        body: OprfEvaluationRequest, client: Annotated[str, Depends(caller)],
    ) -> OprfEvaluationResponse:
        if body.epoch != share.epoch:
            # Never answer for another epoch: a token from the wrong key does not fail,
            # it just never matches, which reads as "no correlation".
            raise HTTPException(status.HTTP_409_CONFLICT,
                                f"this custodian serves epoch {share.epoch}")

        try:
            blinded = [group.validate_element(bytes.fromhex(e)) for e in body.blinded_elements]
        except group.InvalidElement as exc:
            raise HTTPException(422, str(exc)) from exc

        if not meter.charge(client, body.epoch, len(blinded)):
            log.warning("evaluator.over_budget client=%s elements=%d", client, len(blinded))
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "daily evaluation budget spent")

        evaluated = [voprf.blind_evaluate(share.scalar, b) for b in blinded]
        proof = voprf.generate_proof(share.scalar, public, blinded, evaluated)
        log.info("evaluator.evaluated client=%s epoch=%d elements=%d",
                 client, body.epoch, len(blinded))
        return OprfEvaluationResponse(
            epoch=share.epoch, index=share.index,
            evaluated_elements=[e.hex() for e in evaluated],
            proof=proof.to_bytes().hex(),
        )

    return app
