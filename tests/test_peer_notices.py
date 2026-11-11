"""
A firm is told when peers report the same attacker, even if it reported first.

The core may not call into an institution, so a firm collects its own notices. These
tests hold the two halves of that bargain: the warning really arrives, and adding a route
inward did not open a route for anything else. The route accepts nothing.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "packages" / "contracts"),
    str(ROOT / "services" / "connector"),
    str(ROOT / "services" / "core"),
]

SHARED = "a" * 32
A, B, C = "psd_firm00a", "psd_firm00b", "psd_firm00c"


def _payload(n: int, ref: str, token: str = SHARED, techniques: tuple[str, ...] = ()) -> dict:
    return {
        "submission_id": f"00000000-0000-4000-8000-{n:012d}",
        "institution_ref": ref,
        "tokens": [{"type": "IP", "token": token}],
        "technique_set": list(techniques),
        "coarse": {"sector": "BANK", "size_band": "MID", "severity_band": "HIGH",
                   "ts_bucket": "2026-08-19T08:00:00+00:00"},
    }


def _start(monkeypatch, tmp_path, backend: str) -> Iterator[TestClient]:
    from marsad_core.config import settings

    monkeypatch.setenv("MARSAD_CORE_STORE", backend)
    monkeypatch.setenv("MARSAD_CORE_DATABASE_URL", f"sqlite:///{tmp_path / 'core.db'}")
    monkeypatch.setenv("MARSAD_CORE_ANCHOR_INTERVAL_SECONDS", "0")
    settings.cache_clear()
    from marsad_core.main import STATE, app

    STATE.clear()
    with TestClient(app) as client:
        yield client
    STATE.clear()
    settings.cache_clear()


@pytest.fixture
def core(monkeypatch, tmp_path) -> Iterator[TestClient]:
    yield from _start(monkeypatch, tmp_path, "memory")


@pytest.fixture
def sql_core(monkeypatch, tmp_path) -> Iterator[TestClient]:
    yield from _start(monkeypatch, tmp_path, "sql")


def _notices(core, ref: str, **params) -> list[dict]:
    response = core.get("/v1/notices", params={"institution_ref": ref, **params})
    assert response.status_code == 200
    return response.json()["notices"]


def _enforce(monkeypatch) -> None:
    from marsad_core.config import settings

    monkeypatch.setenv("MARSAD_CORE_REQUIRE_CLIENT_IDENTITY", "true")
    settings.cache_clear()


# ---------------------------------------------------------------- the warning arrives


def test_the_first_firm_to_report_is_told_when_a_second_firm_matches(core):
    """The whole reason this route exists. Before it, the first reporter was never told."""
    first = core.post("/v1/submissions", json=_payload(1, A)).json()
    assert first["correlations"] == [], "nothing to match yet, which is the premise"
    assert _notices(core, A) == []

    core.post("/v1/submissions", json=_payload(2, B))
    notices = _notices(core, A)
    assert len(notices) == 1
    assert notices[0]["peer_count"] == 1
    assert notices[0]["kind"] == "EXACT_TOKEN"
    assert notices[0]["indicator_type"] == "IP"


def test_an_earlier_firm_hears_about_each_later_firm_too(core):
    """Firm B was the newest at 11:00; it must still hear about Firm C at 14:00."""
    for n, ref in enumerate((A, B, C)):
        core.post("/v1/submissions", json=_payload(n, ref))
    assert sorted(x["peer_count"] for x in _notices(core, A)) == [1, 2]
    assert [x["peer_count"] for x in _notices(core, B)] == [1, 2]


def test_a_firm_with_no_match_receives_nothing(core):
    core.post("/v1/submissions", json=_payload(1, A))
    core.post("/v1/submissions", json=_payload(2, B, token="b" * 32))
    assert _notices(core, A) == []
    assert _notices(core, B) == []


def test_a_retried_submission_does_not_raise_a_second_warning(core):
    """A connector retrying after a timeout must not make a campaign look bigger."""
    core.post("/v1/submissions", json=_payload(1, A))
    core.post("/v1/submissions", json=_payload(2, B))
    core.post("/v1/submissions", json=_payload(2, B))
    assert len(_notices(core, A)) == 1


def test_notices_survive_a_core_restart_with_the_same_ids(sql_core):
    """A restarted core that re-issued ids would warn every firm a second time."""
    from marsad_core.main import STATE

    sql_core.post("/v1/submissions", json=_payload(1, A))
    sql_core.post("/v1/submissions", json=_payload(2, B))
    before = _notices(sql_core, A)

    STATE["hits"] = STATE["store"].all_correlations()  # what a restart loads
    assert [n["correlation_id"] for n in _notices(sql_core, A)] == \
           [n["correlation_id"] for n in before]


def test_since_returns_only_what_is_newer(core):
    core.post("/v1/submissions", json=_payload(1, A))
    core.post("/v1/submissions", json=_payload(2, B))
    newest = _notices(core, A)[-1]["detected_at"]
    assert _notices(core, A, since=newest) == []


# ---------------------------------------------------------------- nothing else opened


def test_a_notice_names_no_firm_token_or_submission(core):
    """Rung 0: how many others, never which. The route must not become a directory."""
    core.post("/v1/submissions", json=_payload(1, A))
    core.post("/v1/submissions", json=_payload(2, B))
    text = core.get("/v1/notices", params={"institution_ref": A}).text
    for private in (A, B, SHARED, "00000000-0000-4000-8000"):
        assert private not in text


def test_two_firms_in_one_match_hold_different_notice_ids(core):
    """A shared id would let competitors compare notes and identify each other."""
    core.post("/v1/submissions", json=_payload(1, A))
    core.post("/v1/submissions", json=_payload(2, B))
    assert _notices(core, A)[0]["correlation_id"] != _notices(core, B)[0]["correlation_id"]


def test_a_certificate_cannot_read_another_firms_notices(core, monkeypatch):
    """What a firm has been warned about is its own business, and competitors are peers."""
    core.post("/v1/submissions", json=_payload(1, A))
    core.post("/v1/submissions", json=_payload(2, B))
    _enforce(monkeypatch)
    subject = {"X-Client-Cert-Subject": f"CN={B},OU=Connector,O=MARSAD,C=AE"}

    response = core.get("/v1/notices", params={"institution_ref": A}, headers=subject)
    assert response.status_code == 403
    assert core.get("/v1/notices", params={"institution_ref": B}, headers=subject).status_code == 200


def test_notices_need_a_certificate_once_identity_is_required(core, monkeypatch):
    _enforce(monkeypatch)
    assert core.get("/v1/notices", params={"institution_ref": A}).status_code == 401


def test_the_route_accepts_no_data(core):
    """It is a read. If a POST worked here, this would be a second way out of a firm."""
    assert core.post("/v1/notices", json={"narrative": "x"}).status_code == 405


@pytest.mark.parametrize("config", ["boundary-gateway.conf", "boundary-gateway.mtls.conf"])
def test_the_gateway_forwards_exactly_three_routes_and_notices_accept_no_data(config):
    """
    The promise, restated: submissions and provider declarations carry typed payloads out,
    notices come in, and there are no others. A fourth location has to fail a build.
    """
    text = (ROOT / "infra" / config).read_text()
    routes = re.findall(r"location\s*=\s*(\S+)\s*\{\s*limit_except\s+(\w+)", text)
    assert routes == [("/v1/submissions", "POST"), ("/v1/declarations", "POST"),
                      ("/v1/notices", "GET")]
    assert len(re.findall(r"^\s*location\b", text, re.MULTILINE)) == 4, "three routes plus the refusal"


def test_the_public_site_does_not_serve_notices():
    """Only the certificate-authenticated port may. The open read list must not name it."""
    caddy = (ROOT / "deploy" / "caddy" / "Caddyfile").read_text()
    public = caddy[caddy.index("@reads {"):caddy.index("handle @reads")]
    assert "/v1/notices" not in public


# ---------------------------------------------------------------- the connector


class _Seen:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []


@pytest.fixture
def connector(monkeypatch, core):
    from marsad_connector import main as connector_main
    from marsad_connector.config import settings
    from marsad_connector.store import InMemoryStore

    monkeypatch.setenv("MARSAD_TOKEN_KEY", "peer-notices-key-16+")
    monkeypatch.setenv("MARSAD_INSTITUTION_REF", A)
    settings.cache_clear()
    monkeypatch.setattr(connector_main, "LOCAL", InMemoryStore())
    seen = _Seen()

    def handle(request: httpx.Request) -> httpx.Response:
        seen.requests.append(request)
        reply = core.get(request.url.path, params=dict(request.url.params))
        return httpx.Response(reply.status_code, content=reply.content,
                              headers={"content-type": "application/json"})

    monkeypatch.setattr(
        connector_main, "_core_client",
        lambda cfg: httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    )
    yield TestClient(connector_main.app), seen, connector_main
    settings.cache_clear()


def test_the_connector_collects_and_shows_the_warning(connector, core):
    client, _, _ = connector
    core.post("/v1/submissions", json=_payload(1, A))
    core.post("/v1/submissions", json=_payload(2, B))

    assert client.post("/v1/notices/collect").json() == {"collected": True, "new_notices": 1}
    held = client.get("/v1/notices").json()
    assert len(held) == 1 and held[0]["peer_count"] == 1


def test_collecting_twice_records_one_notice(connector, core):
    client, _, _ = connector
    core.post("/v1/submissions", json=_payload(1, A))
    core.post("/v1/submissions", json=_payload(2, B))
    client.post("/v1/notices/collect")
    assert client.post("/v1/notices/collect").json()["new_notices"] == 0
    assert len(client.get("/v1/notices").json()) == 1


def test_collecting_sends_a_pseudonym_and_a_timestamp_and_nothing_else(connector, core):
    """The whole privacy argument for this route, checked on the actual request."""
    client, seen, _ = connector
    client.post("/v1/incidents", json={
        "narrative": "CanaryNarrativeDoNotSend appeared in the mailbox",
        "indicators": [{"type": "IP", "value": "203.0.113.200"}], "severity": "HIGH",
    })
    core.post("/v1/submissions", json=_payload(1, A))
    core.post("/v1/submissions", json=_payload(2, B))
    client.post("/v1/notices/collect")
    client.post("/v1/notices/collect")

    assert len(seen.requests) == 2
    for request in seen.requests:
        assert request.method == "GET"
        assert request.content == b""
        assert set(request.url.params) <= {"institution_ref", "since"}
        assert "Canary" not in str(request.url) and "203.0.113.200" not in str(request.url)


def test_an_unreachable_core_costs_a_late_alert_and_nothing_else(connector, monkeypatch):
    """MARSAD is never on the critical path. A failed check reports itself and moves on."""
    client, _, connector_main = connector

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("core is down", request=request)

    monkeypatch.setattr(
        connector_main, "_core_client",
        lambda cfg: httpx.AsyncClient(transport=httpx.MockTransport(refuse)),
    )
    result = client.post("/v1/notices/collect")
    assert result.status_code == 200
    assert result.json() == {"collected": False, "new_notices": 0, "error": "ConnectError"}


def test_a_malformed_reply_stores_nothing(connector, monkeypatch):
    """Inbound data is still validated. A notice the contract refuses is not shown."""
    client, _, connector_main = connector

    def garbage(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"notices": [{"peer_count": "several"}]})

    monkeypatch.setattr(
        connector_main, "_core_client",
        lambda cfg: httpx.AsyncClient(transport=httpx.MockTransport(garbage)),
    )
    assert client.post("/v1/notices/collect").json()["collected"] is False
    assert client.get("/v1/notices").json() == []


def test_receiving_a_notice_changes_nothing_about_an_incident(connector, core):
    """It informs an analyst. It never files, escalates or submits anything by itself."""
    client, seen, connector_main = connector
    iid = client.post("/v1/incidents", json={
        "narrative": "Phishing reported by a user.", "severity": "LOW",
        "indicators": [{"type": "IP", "value": "203.0.113.9"}],
    }).json()["incident_id"]
    core.post("/v1/submissions", json=_payload(1, A))
    core.post("/v1/submissions", json=_payload(2, B))
    client.post("/v1/notices/collect")

    assert connector_main.LOCAL.get(iid).severity == "LOW"
    assert connector_main.OUTBOUND.for_incident(iid) == []
    assert {r.method for r in seen.requests} == {"GET"}


def test_notices_persist_in_the_institutions_database(tmp_path):
    from datetime import datetime, timezone

    from marsad_connector.db.session import build_engine, build_sessionmaker, create_all
    from marsad_connector.store import SqlStore

    engine = build_engine(f"sqlite:///{tmp_path / 'edge.db'}")
    create_all(engine)
    store = SqlStore(build_sessionmaker(engine))
    notice = {"correlation_id": "n" * 32, "kind": "EXACT_TOKEN", "peer_count": 2,
              "indicator_type": "IP", "shared_techniques": [], "similarity": None,
              "campaign_id": None, "detected_at": "2026-08-19T08:00:00Z"}

    assert store.save_notices([notice]) == 1
    assert store.save_notices([notice]) == 0
    assert store.notices()[0]["peer_count"] == 2
    assert store.last_notice_at() == datetime(2026, 8, 19, 8, tzinfo=timezone.utc)
