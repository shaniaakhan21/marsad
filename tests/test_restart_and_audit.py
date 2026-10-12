"""
Restart survival and the audit trail — the day-30 claims of the 90-day plan.

The plan names two pieces of evidence for "Postgres and audit persistence replace
in-memory state": a restart-survival test, and "an auditor can reconstruct any
submission". Both are made executable here, against real databases and the real
services, with "restart" meaning a new process on the same database.

What an institution is promised, in the order these tests prove it:

* **It always knows what it disclosed.** Every payload is recorded in the institution's
  own database before it leaves, exactly as it crossed, with who confirmed the incident
  and what the core said it received. The record outlives the narrative; it holds
  nothing the boundary forbids.
* **A core outage loses nothing and counts nothing twice.** A payload the core did not
  confirm stays queued across restarts and is resent unchanged — same `submission_id`
  — so a submission that did arrive before the failure is not counted again.
* **A record changed at rest is refused, not sent.**
* **What the analyst filed is what the store gives back.** Jurisdictions, the
  essential-service determination and the true instant of detection all survive a
  restart — and with them, every regulatory deadline A4 computes.
* **A restarted core forgets nothing.** It still matches against what it received
  before, still reports the correlations it found, names the right institution for each
  submission in a match, and rebuilds any submission to the digest recorded on receipt.
"""

from __future__ import annotations

import importlib
import json
import sys
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "packages" / "contracts"),
    str(ROOT / "services" / "connector"),
    str(ROOT / "services" / "core"),
]

from marsad_connector.config import settings as edge_settings
from marsad_connector.db.models import OutboundSubmission
from marsad_connector.db.retention import purge_expired
from marsad_connector.db.session import build_engine as build_edge_engine
from marsad_connector.db.session import build_sessionmaker as build_edge_sessionmaker
from marsad_connector.db.session import create_all as create_edge
from marsad_connector.db.session import session_scope as edge_session
from marsad_contracts.boundary import IncidentSubmission
from marsad_contracts.digest import payload_digest
from marsad_core.config import settings as core_settings
from marsad_core.db.models import CorrelationMember
from marsad_core.db.session import build_engine as build_core_engine
from marsad_core.db.session import build_sessionmaker as build_core_sessionmaker
from marsad_core.db.session import create_all as create_core
from marsad_core.db.session import session_scope as core_session
from marsad_core.engines.correlation import CorrelationEngine
from marsad_core.engines.similarity import JaccardEngine
from marsad_core.store import SqlStore

TOKEN_KEY = "audit-trail-test-key-sixteen-plus"
UAE = timezone(timedelta(hours=4))

#: Words long enough for A3's leak guard to check, so the incident exercises it.
NARRATIVE = (
    "Treasury analysts received credential-harvesting messages impersonating the "
    "settlement portal. AuditCanaryProse7f3a was the affected workflow."
)


# ---------------------------------------------------------------- the core


class CoreHarness:
    """
    A real core on a real database. `restart()` is a new process on the same database.

    `transport()` is how a connector reaches it — in-process, with switches for the
    failures the connector has to survive: unreachable, refusing, and the ambiguous
    one, where the core stores the payload and the reply is lost.
    """

    def __init__(self) -> None:
        self.client: TestClient | None = None
        self.received: list[dict[str, Any]] = []
        self.down = False
        self.reject = False
        self.lose_reply_after_storing = False
        self.on_arrival: Callable[[dict[str, Any]], None] | None = None

    def start(self) -> None:
        core_settings.cache_clear()
        from marsad_core.main import STATE, app

        STATE.clear()
        self._context = TestClient(app)
        self.client = self._context.__enter__()

    def stop(self) -> None:
        self._context.__exit__(None, None, None)

    def restart(self) -> None:
        self.stop()
        self.start()

    def post(self, submission: IncidentSubmission) -> dict[str, Any]:
        response = self.client.post("/v1/submissions", json=submission.model_dump(mode="json"))
        response.raise_for_status()
        return response.json()

    def submission_count(self) -> int:
        return self.client.get("/health").json()["submissions"]

    def transport(self) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            if self.down:
                raise httpx.ConnectError("connection refused", request=request)
            if self.reject:
                return httpx.Response(422, json={"detail": "refused by the test core"})
            body = json.loads(request.content)
            if self.on_arrival is not None:
                self.on_arrival(body)
            self.received.append(body)
            reply = self.client.post(request.url.path, json=body)
            if self.lose_reply_after_storing:
                raise httpx.ReadTimeout("reply lost after the core stored it", request=request)
            return httpx.Response(reply.status_code, content=reply.content,
                                  headers={"content-type": "application/json"})

        return httpx.MockTransport(handle)


@pytest.fixture
def core(monkeypatch, tmp_path) -> Iterator[CoreHarness]:
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        monkeypatch.setenv(var, "http://127.0.0.1:9")
    monkeypatch.setenv("MARSAD_CORE_STORE", "sql")
    monkeypatch.setenv("MARSAD_CORE_DATABASE_URL", f"sqlite:///{tmp_path / 'core.db'}")
    harness = CoreHarness()
    harness.start()
    try:
        yield harness
    finally:
        harness.stop()
        core_settings.cache_clear()


# ---------------------------------------------------------------- the connector


class ConnectorHarness:
    """
    A real connector process on its own database, wired to `core` in-process.

    `restart()` re-imports the service module, so the stores, the drafts, the LLM
    provider and the app are all rebuilt from configuration exactly as at boot. Only
    the database carries anything across.
    """

    def __init__(self, monkeypatch, core: CoreHarness, database_url: str) -> None:
        self._monkeypatch = monkeypatch
        self._core = core
        self.database_url = database_url

    def start(self) -> None:
        edge_settings.cache_clear()
        name = "marsad_connector.main"
        module = (importlib.reload(sys.modules[name]) if name in sys.modules
                  else importlib.import_module(name))
        self._monkeypatch.setattr(
            module, "_core_client",
            lambda _cfg: httpx.AsyncClient(transport=self._core.transport(), timeout=10),
        )
        self.main = module
        self.client = TestClient(module.app)

    def restart(self) -> None:
        self.start()

    def file(self, **overrides: Any) -> str:
        body = {
            "narrative": NARRATIVE,
            "analyst_notes": "Two analysts confirmed the sender infrastructure.",
            "indicators": [{"type": "IP", "value": "198.51.100.23"},
                           {"type": "DOMAIN", "value": "settle-portal[.]example"}],
            "techniques": ["T1566.002", "T1078"],
            "severity": "HIGH",
            "confirmed_by": "a.analyst",
            **overrides,
        }
        response = self.client.post("/v1/incidents", json=body)
        response.raise_for_status()
        return response.json()["incident_id"]

    def submit(self, incident_id: str) -> httpx.Response:
        return self.client.post(f"/v1/incidents/{incident_id}/submit")

    def records(self, incident_id: str | None = None) -> list[dict[str, Any]]:
        params = {"incident_id": incident_id} if incident_id else {}
        return self.client.get("/v1/outbound", params=params).json()

    def retry(self) -> dict[str, Any]:
        response = self.client.post("/v1/outbound/retry")
        response.raise_for_status()
        return response.json()

    def database(self):
        """A second, independent handle on the connector's database — an auditor's."""
        engine = build_edge_engine(self.database_url)
        return build_edge_sessionmaker(engine)


@pytest.fixture
def connector(monkeypatch, tmp_path, core) -> Iterator[ConnectorHarness]:
    database_url = f"sqlite:///{tmp_path / 'edge.db'}"
    for name, value in {
        "MARSAD_STORE": "sql",
        "MARSAD_DATABASE_URL": database_url,
        "MARSAD_TOKEN_KEY": TOKEN_KEY,
        "MARSAD_TOKENISER": "hmac",
        "MARSAD_INSTITUTION_REF": "psd_audit01",
        "MARSAD_SECTOR": "BANK",
        "MARSAD_SIZE_BAND": "LARGE",
        "MARSAD_CORE_URL": "http://core.test",
        "MARSAD_LLM_PROVIDER": "stub",
        "MARSAD_CORE_CLIENT_CERT": "",
    }.items():
        monkeypatch.setenv(name, value)
    harness = ConnectorHarness(monkeypatch, core, database_url)
    harness.start()
    try:
        yield harness
    finally:
        edge_settings.cache_clear()


def _submission(submission_id: str, institution_ref: str, token: str, *,
                techniques: tuple[str, ...] = ("T1566.002", "T1078"),
                ts_bucket: datetime | None = None, **extra: Any) -> IncidentSubmission:
    return IncidentSubmission(
        submission_id=submission_id, institution_ref=institution_ref,
        tokens=[{"type": "IP", "token": token}], technique_set=list(techniques),
        coarse={"sector": "BANK", "size_band": "LARGE", "severity_band": "HIGH",
                "ts_bucket": ts_bucket or datetime(2026, 8, 19, 8, tzinfo=timezone.utc)},
        **extra,
    )


# ================================================================= what left


def test_every_payload_is_recorded_before_it_leaves(connector, core):
    """
    There is no moment at which something has crossed and the institution holds no
    record of it. Checked at the instant the payload reaches the core, not afterwards.
    """
    recorded_on_arrival: list[bool] = []
    core.on_arrival = lambda body: recorded_on_arrival.append(
        connector.main.OUTBOUND.get(body["submission_id"]) is not None)

    response = connector.submit(connector.file())

    assert response.status_code == 200, response.text
    assert recorded_on_arrival == [True]


def test_the_record_holds_exactly_what_the_core_received(connector, core):
    """
    The institution's record and the core's receipt describe one payload. Both sides
    hold the same digest, and the connector says so only because the core told it.
    """
    incident_id = connector.file()
    sent = connector.submit(incident_id).json()

    [record] = connector.records(incident_id)
    assert record["payload"] == core.received[0], "the record differs from what crossed"
    assert record["payload_digest"] == payload_digest(
        IncidentSubmission.model_validate(core.received[0]))
    assert record["digest_confirmed"] is True
    assert record["attempts"][-1]["core_digest"] == record["payload_digest"]
    assert sent["payload_digest"] == record["payload_digest"]

    # The auditor's view names who stood behind it and how the tokens were made.
    assert record["confirmed_by"] == "a.analyst"
    assert record["tokeniser_scheme"] == "hmac-sha256-v1-PROTOTYPE"
    assert record["status"] == "ACCEPTED"


def test_an_unreachable_core_leaves_the_submission_queued_not_lost(connector, core):
    """
    MARSAD is additive: a core outage never blocks the institution, and never costs
    it the submission either. It answers 503 and keeps the payload.
    """
    core.down = True
    response = connector.submit(connector.file())

    assert response.status_code == 503
    [record] = connector.records()
    assert record["status"] == "QUEUED"
    assert record["payload"]["tokens"], "a queued record must hold the payload to resend"
    assert connector.client.get("/health").json()["queued_submissions"] == 1


def test_a_queued_submission_survives_a_restart_and_is_resent_unchanged(connector, core):
    """
    The queue is in the institution's database, not in the process. After a restart the
    same payload — same submission_id, same digest — is what reaches the core.
    """
    core.down = True
    incident_id = connector.file()
    connector.submit(incident_id)
    [queued] = connector.records(incident_id)

    connector.restart()
    core.down = False
    result = connector.retry()

    assert result == {"attempted": 1, "results": [
        {"submission_id": queued["submission_id"], "status": "ACCEPTED"}], "still_queued": 0}
    assert [b["submission_id"] for b in core.received] == [queued["submission_id"]]
    assert core.received[0] == queued["payload"]
    [done] = connector.records(incident_id)
    assert [a["outcome"] for a in done["attempts"]] == ["QUEUED", "ACCEPTED"]
    assert done["digest_confirmed"] is True


def test_a_resend_after_an_ambiguous_failure_is_not_counted_twice(connector, core):
    """
    Why a retry resends and never rebuilds. The core stored the payload and the reply
    was lost, so the connector cannot know it arrived. A rebuilt payload would carry a
    new submission_id and inflate the campaign; the recorded one is a no-op.
    """
    core.lose_reply_after_storing = True
    incident_id = connector.file()
    assert connector.submit(incident_id).status_code == 503
    assert core.submission_count() == 1, "the core must have stored it for this test to mean anything"

    core.lose_reply_after_storing = False
    assert connector.submit(incident_id).status_code == 200

    assert len({b["submission_id"] for b in core.received}) == 1
    assert len(core.received) == 2
    assert core.submission_count() == 1


def test_submitting_an_incident_twice_sends_one_submission(connector, core):
    """A second submit answers from the record. Nothing is sent, nothing is counted."""
    incident_id = connector.file()
    first = connector.submit(incident_id).json()
    second = connector.submit(incident_id).json()

    assert second["already_submitted"] is True
    assert second["submission_id"] == first["submission_id"]
    assert second["core_response"] == first["core_response"]
    assert len(core.received) == 1
    assert core.submission_count() == 1


def test_a_rejected_submission_is_recorded_and_never_resent(connector, core):
    """
    A refusal from the core means it holds nothing. Resending the same payload would be
    refused forever, so it leaves the queue — and the refusal stays on the record.
    """
    core.reject = True
    incident_id = connector.file()
    response = connector.submit(incident_id)

    assert response.status_code == 502
    [record] = connector.records(incident_id)
    assert record["status"] == "REJECTED"
    assert record["attempts"][-1]["http_status"] == 422
    assert connector.retry() == {"attempted": 0, "results": [], "still_queued": 0}


def test_a_record_altered_at_rest_is_refused_not_sent(connector, core):
    """
    The record is what the institution approved. A queued payload edited in the
    database after it was built no longer matches its digest, and A3 refuses it.
    """
    core.down = True
    incident_id = connector.file()
    connector.submit(incident_id)
    [queued] = connector.records(incident_id)

    with edge_session(connector.database()) as session:
        row = session.get(OutboundSubmission, queued["submission_id"])
        altered = json.loads(json.dumps(row.payload))
        altered["tokens"][0]["token"] = "0" * 32
        row.payload = altered

    core.down = False
    result = connector.retry()

    assert result["results"] == [{"submission_id": queued["submission_id"], "status": "REFUSED"}]
    assert core.received == [], "an altered record reached the core"
    [record] = connector.records(incident_id)
    assert "digest" in record["attempts"][-1]["error"]


def test_the_record_of_what_crossed_outlives_the_narrative(connector, core):
    """
    "What did we disclose?" is asked after the narrative has expired. The record
    survives the retention purge — and it can, because it holds none of the free text.
    """
    incident_id = connector.file()
    connector.submit(incident_id)

    with edge_session(connector.database()) as session:
        purged = purge_expired(session, now=datetime.now(timezone.utc) + timedelta(days=3650))
    assert purged.incidents_redacted == 1
    assert connector.client.get(f"/v1/incidents/{incident_id}").json()["narrative"] is None

    [record] = connector.records(incident_id)
    assert record["status"] == "ACCEPTED" and record["digest_confirmed"] is True
    dumped = json.dumps(record)
    for word in ("AuditCanaryProse7f3a", "credential-harvesting", "198.51.100.23",
                 "settle-portal", "confirmed the sender"):
        assert word not in dumped, f"{word!r} is in the outbound record"


# ================================================================= what was filed


def test_filed_jurisdictions_survive_a_restart_and_drive_the_obligations(connector):
    """
    A4 resolves an incident against the perimeters the analyst filed it under, not the
    institution's configured defaults. The SQL store used to drop both fields on write,
    so this incident — filed under ADGM with an essential service hit — came back as
    CBUAE/CMA with the TDRA question unanswered.
    """
    incident_id = connector.file(jurisdictions=["ADGM_FSRA"], essential_service_affected=True)
    connector.restart()

    result = connector.client.post(f"/v1/incidents/{incident_id}/obligations").json()
    by_authority = {o["authority"]: o["applicability"] for o in result["obligations"]}

    assert by_authority["ADGM_FSRA"] == "REQUIRED"
    assert by_authority["CMA"] == "NOT_APPLICABLE"
    assert by_authority["TDRA"] == "REQUIRED"


def test_cbuae_deadline_is_24_hours_from_the_true_detection_instant_after_a_restart(connector):
    """
    Detected at 08:30 UAE time is 04:30 UTC, so the CBUAE deadline is 04:30 UTC the next
    day. SQLite dropped the offset, A4 read 08:30 as UTC, and the deadline came out four
    hours late — the direction that becomes a breach.
    """
    incident_id = connector.file(jurisdictions=["CBUAE"],
                                 detected_at="2026-08-19T08:30:00+04:00")
    connector.restart()

    result = connector.client.post(f"/v1/incidents/{incident_id}/obligations").json()
    [cbuae] = [o for o in result["obligations"] if o["authority"] == "CBUAE"]
    assert datetime.fromisoformat(cbuae["deadline"]) == datetime(
        2026, 8, 20, 4, 30, tzinfo=timezone.utc)


# ================================================================= the core


def test_a_restarted_core_still_matches_against_what_it_received_before(core):
    """
    The token index is a cache rebuilt from the database. If it were not, a restarted
    core would answer "no correlation" — a silent false negative.
    """
    core.post(_submission("sub-before", "psd_bank0001", "ab" * 16))
    core.restart()
    reply = core.post(_submission("sub-after", "psd_brok0002", "ab" * 16))

    assert [c["kind"] for c in reply["correlations"]] == ["EXACT_TOKEN"]
    assert reply["correlations"][0]["peer_count"] == 1


def test_a_restarted_core_still_reports_the_correlations_it_found(core):
    """The dashboard's list of correlations is read from the store, not from memory."""
    core.post(_submission("sub-1", "psd_bank0001", "cd" * 16))
    core.post(_submission("sub-2", "psd_brok0002", "cd" * 16))
    before = core.client.get("/v1/correlations").json()
    assert before, "nothing correlated, so the restart proves nothing"

    core.restart()
    after = core.client.get("/v1/correlations").json()

    def shape(rows):
        return [(r["kind"], r["institutions"], r["campaign_id"]) for r in rows]

    assert shape(after) == shape(before)


def test_correlation_members_name_the_institution_that_sent_each_submission(tmp_path):
    """
    Each submission in a stored match is attributed to the firm that sent it. The store
    used to zip two independently sorted lists, which pairs these the wrong way round —
    and drops a member whenever one firm contributes two submissions.
    """
    engine = build_core_engine(f"sqlite:///{tmp_path / 'core.db'}")
    create_core(engine)
    factory = build_core_sessionmaker(engine)
    store = SqlStore(factory)
    correlation = CorrelationEngine(JaccardEngine())

    token = "ef" * 16
    for submission in (_submission("sub-zz", "psd_aaaa0001", token),
                       _submission("sub-mm", "psd_aaaa0001", token, techniques=("T1190",)),
                       _submission("sub-aa", "psd_bbbb0002", token)):
        store.save_submission(submission)
        store.save_correlations(correlation.ingest(submission))

    with core_session(factory) as session:
        members = {(m.institution_ref, m.submission_id)
                   for m in session.scalars(sa.select(CorrelationMember))}
    assert members == {("psd_aaaa0001", "sub-zz"), ("psd_aaaa0001", "sub-mm"),
                       ("psd_bbbb0002", "sub-aa")}


def test_the_core_can_reconstruct_any_submission_exactly_as_received(core):
    """
    The auditor's check at the core: rebuild the payload from its rows and it has the
    digest recorded when it arrived — the digest the institution also holds. Sent in UAE
    time on purpose; SQLite used to return it zoneless and four hours adrift.
    """
    submission = _submission(
        "sub-audit", "psd_bank0001", "12" * 16,
        ts_bucket=datetime(2026, 8, 19, 8, tzinfo=UAE),
        obligation_ref={"receipt_hash": "a" * 64, "authority": "CBUAE",
                        "filed_at": datetime(2026, 8, 19, 9, 13, tzinfo=UAE)},
    )
    reply = core.post(submission)
    core.restart()

    from marsad_core.main import STATE

    rebuilt, recorded = STATE["store"].reconstruct("sub-audit")
    assert recorded == reply["payload_digest"] == payload_digest(submission)
    assert payload_digest(rebuilt) == recorded
    assert rebuilt.coarse.ts_bucket == submission.coarse.ts_bucket


def test_a_reused_submission_id_is_answered_with_what_the_core_holds(core):
    """
    The core keeps the first payload under an id. A sender that reuses the id for
    different content is told the digest of what the core actually holds, so the
    disagreement is visible to it rather than silently accepted.
    """
    original = _submission("sub-reused", "psd_bank0001", "34" * 16)
    different = _submission("sub-reused", "psd_bank0001", "56" * 16)

    core.post(original)
    reply = core.post(different)

    assert reply["payload_digest"] == payload_digest(original)
    assert reply["payload_digest"] != payload_digest(different)


def test_a_database_older_than_the_code_is_refused_at_boot(tmp_path):
    """
    Auto-create never alters an existing table, so an old local database used to boot
    cleanly and fail at the first query as "no such column". It is refused at boot now,
    with the missing columns and the fix named.
    """
    engine = build_edge_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE edge.local_incidents (id VARCHAR(64) PRIMARY KEY, narrative TEXT)")

    with pytest.raises(RuntimeError, match="jurisdictions") as refused:
        create_edge(engine)
    assert "make migrate" in str(refused.value)
