"""
Who may reach what — the gaps a pilot may not start with.

Each test is a line from the "known gaps, closed before any real data" table, stated as
the property that closes it. Mutual TLS proves a caller is *some* member of the
federation; these tests are about the step after that, which is the one that stops a
member speaking as another member.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "packages" / "contracts"),
    str(ROOT / "services" / "connector"),
    str(ROOT / "services" / "core"),
]

SUBJECT = "CN=psd_emcap03,OU=Connector,O=MARSAD,C=AE"
READ_TOKEN = "regulator:a-regulator-token-long-enough,operator:an-operator-token-long-enough"


def _payload(institution_ref: str = "psd_emcap03") -> dict:
    return {
        "submission_id": "11111111-1111-4111-8111-111111111111",
        "institution_ref": institution_ref,
        "tokens": [{"type": "IP", "token": "a" * 32}],
        "technique_set": ["T1566"],
        "coarse": {"sector": "BANK", "size_band": "MID", "severity_band": "HIGH",
                   "ts_bucket": "2026-08-19T08:00:00+00:00"},
    }


@pytest.fixture
def core(monkeypatch) -> Iterator[TestClient]:
    """A core in memory, with whatever enforcement the test sets before starting it."""
    from marsad_core.config import settings

    monkeypatch.setenv("MARSAD_CORE_STORE", "memory")
    settings.cache_clear()
    from marsad_core.main import STATE, app

    STATE.clear()
    with TestClient(app) as client:
        yield client
    settings.cache_clear()


def _enforce(monkeypatch, **env: str) -> None:
    from marsad_core.config import settings

    for key, value in env.items():
        monkeypatch.setenv(f"MARSAD_CORE_{key}", value)
    settings.cache_clear()


def test_a_certificate_may_only_submit_for_the_pseudonym_it_names(core, monkeypatch):
    """
    Without this, an enrolled firm could submit under a competitor's pseudonym and
    fabricate a correlation that implicates them. A valid certificate is not a licence
    to speak for anyone else.
    """
    _enforce(monkeypatch, REQUIRE_CLIENT_IDENTITY="true")

    refused = core.post("/v1/submissions", json=_payload("psd_almaha01"),
                        headers={"X-Client-Cert-Subject": SUBJECT})
    assert refused.status_code == 403
    assert core.get("/health").json()["submissions"] == 0, "a refused payload was stored"

    admitted = core.post("/v1/submissions", json=_payload("psd_emcap03"),
                         headers={"X-Client-Cert-Subject": SUBJECT})
    assert admitted.status_code == 200


def test_a_submission_with_no_certificate_is_refused_once_identity_is_required(core, monkeypatch):
    """Refused before the body is read: a stranger learns nothing from validation errors."""
    _enforce(monkeypatch, REQUIRE_CLIENT_IDENTITY="true")
    response = core.post("/v1/submissions", json={"not": "a valid payload"})
    assert response.status_code == 401


def test_a_certificate_outside_the_registered_list_is_refused(core, monkeypatch):
    """The CA signing a certificate says who it is; the register says who may submit."""
    _enforce(monkeypatch, REQUIRE_CLIENT_IDENTITY="true",
             REGISTERED_INSTITUTIONS_RAW="psd_almaha01,psd_gulfsec02")
    response = core.post("/v1/submissions", json=_payload(),
                         headers={"X-Client-Cert-Subject": SUBJECT})
    assert response.status_code == 403


@pytest.mark.parametrize("subject", ["", "O=MARSAD", "CN=Emirates Capital,O=MARSAD", "CN=X"])
def test_a_subject_that_is_not_a_pseudonym_is_refused(core, monkeypatch, subject):
    """A firm name in a certificate would undo pseudonymity, so it does not authenticate."""
    _enforce(monkeypatch, REQUIRE_CLIENT_IDENTITY="true")
    response = core.post("/v1/submissions", json=_payload(),
                         headers={"X-Client-Cert-Subject": subject})
    assert response.status_code in (401, 403)


def test_the_core_reports_when_it_is_running_without_enforcement(core):
    """Nothing degrades silently: the demo posture is visible, not assumed away."""
    health = core.get("/health").json()
    assert health["client_identity_required"] is False
    assert health["console_auth_required"] is False


def test_console_reads_need_a_token_once_tokens_are_configured(core, monkeypatch):
    """The correlations list is the operator's view; it is not public by default."""
    _enforce(monkeypatch, CONSOLE_TOKENS=READ_TOKEN)

    assert core.get("/v1/correlations").status_code == 401
    assert core.get("/v1/correlations",
                    headers={"Authorization": "Bearer wrong-token-of-enough-length"}
                    ).status_code == 401
    assert core.get("/v1/correlations",
                    headers={"Authorization": "Bearer an-operator-token-long-enough"}
                    ).status_code == 200


def test_a_wildcard_cors_origin_is_refused_at_startup():
    """A wildcard lets any page an analyst visits read the API with their browser."""
    from marsad_core.security import parse_origins

    with pytest.raises(RuntimeError, match="not permitted"):
        parse_origins("https://console.example, *")
    assert parse_origins("https://console.example/") == ["https://console.example"]


def test_an_unapproved_origin_receives_no_cors_grant(core):
    approved = core.get("/health", headers={"Origin": "http://localhost:3000"})
    assert approved.headers.get("access-control-allow-origin") == "http://localhost:3000"
    stranger = core.get("/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in stranger.headers


def test_every_proxy_in_front_of_the_core_overwrites_the_identity_header():
    """
    The core believes X-Client-Cert-Subject only because no client can set it. That
    rests on these lines, so their absence has to fail a build.
    """
    plain = (ROOT / "infra" / "boundary-gateway.conf").read_text()
    assert 'proxy_set_header X-Client-Cert-Subject "";' in plain

    mtls = (ROOT / "infra" / "boundary-gateway.mtls.conf").read_text()
    assert "ssl_verify_client on;" in mtls
    assert "proxy_set_header X-Client-Cert-Subject $ssl_client_s_dn;" in mtls

    caddy = (ROOT / "deploy" / "caddy" / "Caddyfile").read_text()
    assert "header_up X-Client-Cert-Subject {http.request.tls.client.subject}" in caddy


# ---------------------------------------------------------------- the connector


@pytest.fixture
def connector(monkeypatch) -> Iterator[TestClient]:
    from marsad_connector.config import settings

    monkeypatch.setenv("MARSAD_TOKEN_KEY", "access-control-key-16+")
    settings.cache_clear()
    from marsad_connector.main import app

    yield TestClient(app)
    settings.cache_clear()


def test_the_connector_serves_no_plaintext_route_without_the_console_token(connector, monkeypatch):
    """
    This process holds narrative. Protection is applied to every route by default, so
    one added later is protected without anyone having to remember.
    """
    from marsad_connector.config import settings

    monkeypatch.setenv("MARSAD_CONSOLE_TOKEN", "a-console-token-long-enough")
    settings.cache_clear()

    assert connector.get("/v1/incidents/anything").status_code == 401
    assert connector.get("/v1/outbound").status_code == 401
    assert connector.get("/health").status_code == 200, "the liveness probe stays open"
    assert connector.get("/v1/incidents/anything",
                         headers={"Authorization": "Bearer a-console-token-long-enough"}
                         ).status_code == 404, "a valid token reaches the route"


# ---------------------------------------------------------------- scheduled retention


@pytest.fixture
def sql_store(tmp_path):
    from marsad_connector.db.session import build_engine, build_sessionmaker, create_all
    from marsad_connector.store import SqlStore

    engine = build_engine(f"sqlite:///{tmp_path / 'edge.db'}")
    create_all(engine)
    return SqlStore(build_sessionmaker(engine), retention_days=1)


class _Incident:
    narrative = "secret-narrative-text about the outage"
    analyst_notes = "secret-analyst-note"
    indicators = ()
    techniques = ()
    severity = "HIGH"


def test_a_scheduled_purge_clears_expired_text_and_leaves_an_audit_row(sql_store):
    """The gap was "exists but is not scheduled": a run must act, and be provable."""
    sql_store.save("inc-1", _Incident())
    result = sql_store.purge_expired(now=datetime.now(timezone.utc) + timedelta(days=2))
    assert result["incidents_redacted"] == 1

    runs = sql_store.retention_runs()
    assert len(runs) == 1
    assert runs[0]["status"] == "COMPLETED"
    assert runs[0]["incidents_redacted"] == 1


def test_the_retention_audit_quotes_nothing_it_deleted(sql_store):
    """A log of deletions that repeated the deleted text would be the text, kept."""
    sql_store.save("inc-1", _Incident())
    sql_store.purge_expired(now=datetime.now(timezone.utc) + timedelta(days=2))
    assert "secret" not in repr(sql_store.retention_runs())


def test_a_failed_purge_is_recorded_rather_than_invisible(sql_store, monkeypatch):
    """A gap in the audit trail must read as a failure, not as nothing having been due."""
    import marsad_connector.store as store_module

    def explode(*_, **__):
        raise RuntimeError("disk full")

    monkeypatch.setattr(store_module, "purge_expired", explode)
    with pytest.raises(RuntimeError):
        sql_store.purge_expired()
    assert sql_store.retention_runs()[0]["status"] == "FAILED"


def test_the_purge_loop_survives_a_failed_run(monkeypatch):
    """One bad night must not end retention for the life of the process."""
    import asyncio

    import marsad_connector.main as connector_main

    calls = {"n": 0}

    class FlakyStore:
        name = "sql"

        def purge_expired(self):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("database restarting")
            return {"incidents_redacted": 0}

    monkeypatch.setattr(connector_main, "LOCAL", FlakyStore())

    async def run():
        task = asyncio.create_task(connector_main._retention_loop(0))
        while calls["n"] < 2:
            await asyncio.sleep(0)
        task.cancel()

    asyncio.run(run())
    assert calls["n"] >= 2
