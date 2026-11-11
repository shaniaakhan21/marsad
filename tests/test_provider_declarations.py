"""
A firm says what it relies on, and a provider warns everyone once.

The claims: a provider's name never leaves a firm; firms that declared the provider are
told when it is hit; nobody can raise a false alarm about a provider they do not run; and
the register is built from what firms declared, with small groups held back.
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "packages" / "contracts"),
    str(ROOT / "packages" / "oprf"),
    str(ROOT / "services" / "connector"),
    str(ROOT / "services" / "core"),
]

from marsad_connector.agents.a3_redact import RedactionAgent, RedactionError
from marsad_connector.crypto.tokeniser import HmacTokeniser, canonical_provider
from marsad_contracts.boundary import DependencyDeclaration, IndicatorType

KEY = b"provider-declaration-key-16+"
TOKENISER = HmacTokeniser(KEY)
DOMAIN = "canary-kyc-vendor.example"
NAME = "CanaryKycVendorName"
TOKEN = TOKENISER.tokenise_provider(DOMAIN)
OWNER = "psd_vendor01"
A, B, C, D = "psd_firm00a", "psd_firm00b", "psd_firm00c", "psd_firm00d"
DIRECTORY = {TOKEN: {"name": "Demo KYC provider", "service": "Identity checks",
                     "market_activity_share": 0.2, "owner_ref": OWNER}}


def _dependencies(ref: str, sequence: int = 1, token: str = TOKEN, sub: str = "NO") -> dict:
    return {"kind": "DEPENDENCY", "declaration_id": f"declaration-{ref}-{sequence}",
            "institution_ref": ref, "sequence": sequence,
            "dependencies": [{"provider_token": token, "substitutability": sub}]}


def _incident(ref: str = OWNER, token: str = TOKEN, n: int = 1) -> dict:
    return {"kind": "PROVIDER_INCIDENT", "declaration_id": f"provider-incident-{n}",
            "institution_ref": ref, "provider_token": token, "severity_band": "HIGH",
            "ts_bucket": "2026-11-10T08:00:00+00:00"}


def _start(monkeypatch, tmp_path, backend) -> Iterator[TestClient]:
    from marsad_core.config import settings

    monkeypatch.setenv("MARSAD_CORE_STORE", backend)
    monkeypatch.setenv("MARSAD_CORE_DATABASE_URL", f"sqlite:///{tmp_path / 'core.db'}")
    monkeypatch.setenv("MARSAD_CORE_ANCHOR_INTERVAL_SECONDS", "0")
    monkeypatch.setenv("MARSAD_CORE_PROVIDER_DIRECTORY", json.dumps(DIRECTORY))
    settings.cache_clear()
    from marsad_core.main import STATE, app

    STATE.clear()
    with TestClient(app) as client:
        yield client
    STATE.clear()
    settings.cache_clear()


@pytest.fixture(params=["memory", "sql"])
def core(request, monkeypatch, tmp_path) -> Iterator[TestClient]:
    """Both backends: the fast one must not behave differently from the store of record."""
    yield from _start(monkeypatch, tmp_path, request.param)


def _declare(core, body: dict, **kw) -> httpx.Response:
    return core.post("/v1/declarations", json=body, **kw)


def _alerts(core, ref: str) -> list[dict]:
    return core.get("/v1/notices", params={"institution_ref": ref}).json()["provider_alerts"]


# ---------------------------------------------------------------- identity stays home


def test_a_provider_token_differs_from_the_same_domain_seen_in_an_attack():
    """Otherwise the core could link a firm's supplier list to its incidents."""
    assert TOKEN != TOKENISER.tokenise(DOMAIN, IndicatorType.DOMAIN)


def test_two_firms_writing_a_domain_differently_produce_one_token():
    variants = ("https://WWW.Canary-KYC-Vendor.example/", "canary-kyc-vendor[.]example")
    assert {TOKENISER.tokenise_provider(canonical_provider(v)) for v in variants} == {TOKEN}


@pytest.mark.parametrize("not_a_domain", ["Acme Payments LLC", "localhost", "acme"])
def test_a_provider_must_be_identified_by_its_domain(not_a_domain):
    """A free-form name would produce tokens that silently never match anyone's."""
    with pytest.raises(ValueError):
        canonical_provider(not_a_domain)


def test_a_declaration_cannot_carry_a_provider_name():
    """The shape cannot express it. An undeclared field is refused, not ignored."""
    with pytest.raises(ValueError):
        DependencyDeclaration.model_validate({**_dependencies(A), "provider_name": NAME})


def test_the_leak_guard_trips_if_a_name_ever_reaches_a_declaration():
    """Sabotage on purpose: a token that is really the name must stop the build."""
    entry = {"name": "abcdef0123456789abcdef0123456789", "domain": DOMAIN,
             "substitutability": "NO"}
    with pytest.raises(RedactionError, match="LEAK GUARD"):
        RedactionAgent.build_dependency_declaration(
            [entry], {DOMAIN: entry["name"]}, institution_ref=A, sequence=1,
        )


def test_a_dependency_without_a_token_fails_the_build():
    """A list quietly missing a provider would understate the firm's exposure."""
    with pytest.raises(RedactionError):
        RedactionAgent.build_dependency_declaration(
            [{"name": NAME, "domain": DOMAIN, "substitutability": "NO"}], {},
            institution_ref=A, sequence=1,
        )


def test_the_core_schema_has_no_column_for_a_provider_name():
    import marsad_core.db.models  # noqa: F401 - registers the tables
    from marsad_core.db.base import CoreBase

    columns = CoreBase.metadata.tables["core.declared_dependencies"].columns.keys()
    assert not {"name", "provider", "provider_name", "domain"} & set(columns)


# ---------------------------------------------------------------- the warning


def test_a_firm_that_declared_a_provider_is_warned_when_it_is_hit(core):
    """Declare once, warn everyone who relies on you. The brief's promise."""
    for ref in (A, B):
        assert _declare(core, _dependencies(ref)).status_code == 200
    reply = _declare(core, _incident())
    assert reply.status_code == 200
    assert reply.json()["dependents_notified"] == 2

    alerts = _alerts(core, A)
    assert len(alerts) == 1
    assert alerts[0]["provider_token"] == TOKEN
    assert alerts[0]["severity_band"] == "HIGH"


def test_a_firm_that_did_not_declare_the_provider_hears_nothing(core):
    _declare(core, _dependencies(A))
    _declare(core, _incident())
    assert _alerts(core, B) == []


def test_a_firm_declaring_just_after_the_incident_is_still_warned(core):
    """Timing of a spreadsheet update must not decide who learns their supplier was hit."""
    _declare(core, _incident())
    _declare(core, _dependencies(A))
    assert len(_alerts(core, A)) == 1


def test_the_provider_learns_how_many_firms_rely_on_it_and_never_which(core):
    _declare(core, _dependencies(A))
    text = _declare(core, _incident()).text
    assert A not in text and "institution" not in text


def test_a_retried_provider_incident_warns_once(core):
    _declare(core, _dependencies(A))
    _declare(core, _incident())
    _declare(core, _incident())
    assert len(_alerts(core, A)) == 1


def test_alert_ids_differ_per_firm(core):
    """A shared id would let two competitors discover they rely on the same provider."""
    for ref in (A, B):
        _declare(core, _dependencies(ref))
    _declare(core, _incident())
    assert _alerts(core, A)[0]["alert_id"] != _alerts(core, B)[0]["alert_id"]


# ---------------------------------------------------------------- false alarms


def test_nobody_can_declare_an_incident_at_a_provider_they_do_not_run(core):
    """The attack this route invites: one participant announcing a rival's outage."""
    _declare(core, _dependencies(A))
    assert _declare(core, _incident(ref=B)).status_code == 403
    assert _alerts(core, A) == []


def test_an_unenrolled_provider_cannot_raise_an_alert(core):
    other = TOKENISER.tokenise_provider("not-enrolled.example")
    _declare(core, _dependencies(A, token=other))
    assert _declare(core, _incident(ref=OWNER, token=other)).status_code == 403
    assert _alerts(core, A) == []


def test_a_certificate_may_only_declare_for_the_pseudonym_it_names(core, monkeypatch):
    from marsad_core.config import settings

    monkeypatch.setenv("MARSAD_CORE_REQUIRE_CLIENT_IDENTITY", "true")
    settings.cache_clear()
    subject = {"X-Client-Cert-Subject": f"CN={B},O=MARSAD"}
    assert _declare(core, _dependencies(A), headers=subject).status_code == 403
    assert _declare(core, _dependencies(B), headers=subject).status_code == 200
    assert _declare(core, _dependencies(C)).status_code == 401


def test_a_queued_older_list_cannot_overwrite_a_newer_one(core):
    """After an outage, retries may arrive out of order. The newest list must win."""
    other = TOKENISER.tokenise_provider("newer-vendor.example")
    assert _declare(core, _dependencies(A, 2, token=other)).json()["applied"] is True
    assert _declare(core, _dependencies(A, 1)).json()["applied"] is False
    _declare(core, _incident())
    assert _alerts(core, A) == []


def test_an_empty_list_withdraws_every_dependency(core):
    _declare(core, _dependencies(A))
    _declare(core, {**_dependencies(A, 2), "dependencies": []})
    _declare(core, _incident())
    assert _alerts(core, A) == []


# ---------------------------------------------------------------- the register


def _register(core) -> dict:
    return core.get("/v1/concentration").json()


def test_until_firms_declare_the_register_says_its_data_is_illustrative(core):
    """Seed data must never be mistaken for what firms told us."""
    assert _register(core)["data_basis"] == "ILLUSTRATIVE_SEED"


def test_the_register_is_built_from_declarations_once_k_firms_have_declared(core):
    for ref in (A, B, C):
        _declare(core, _dependencies(ref))
    report = _register(core)
    assert report["data_basis"] == "DECLARED"
    assert [p["provider"] for p in report["providers"]] == ["Demo KYC provider"]
    assert report["providers"][0]["dependents"] == 3
    assert report["providers"][0]["exposure"]["daily_traded_value_at_risk_aed_bn"] > 0


def test_a_provider_fewer_than_k_firms_declare_is_held_back(core):
    """Two firms and a named supplier identifies the pair to anyone who knows the market."""
    for ref in (A, B):
        _declare(core, _dependencies(ref))
    report = _register(core)
    assert report["data_basis"] == "ILLUSTRATIVE_SEED"
    assert report["declarations_held_back"]["withheld_below_k"] == 1


def test_a_token_nobody_enrolled_is_counted_and_never_named(core):
    other = TOKENISER.tokenise_provider("not-enrolled.example")
    for ref in (A, B, C):
        _declare(core, _dependencies(ref, token=other))
    report = _register(core)
    assert report["declarations_held_back"]["not_yet_enrolled"] == 1
    assert other not in json.dumps(report)


def test_the_register_names_no_firm(core):
    for ref in (A, B, C):
        _declare(core, _dependencies(ref))
    text = core.get("/v1/concentration").text
    for ref in (A, B, C):
        assert ref not in text


def test_disagreement_about_replaceability_takes_the_majority_and_ties_go_worse():
    from marsad_core.services.providers import _consensus

    assert _consensus(["YES", "YES", "NO"]).value == "YES"
    assert _consensus(["YES", "NO"]).value == "NO"


def test_a_directory_with_an_impossible_share_stops_the_core():
    from marsad_core.services.providers import parse_directory

    with pytest.raises(ValueError, match="out of range"):
        parse_directory(json.dumps({"t": {**DIRECTORY[TOKEN], "market_activity_share": 4}}))


# ---------------------------------------------------------------- the connector


@pytest.fixture
def connector(monkeypatch, tmp_path):
    """A connector wired to a real in-memory core, recording every request it makes."""
    from marsad_connector import main as connector_main
    from marsad_connector.config import settings
    from marsad_connector.store import InMemoryStore

    core_iter = _start(monkeypatch, tmp_path, "memory")
    core = next(core_iter)
    monkeypatch.setenv("MARSAD_TOKEN_KEY", KEY.decode())
    monkeypatch.setenv("MARSAD_INSTITUTION_REF", A)
    settings.cache_clear()
    monkeypatch.setattr(connector_main, "LOCAL", InMemoryStore())
    monkeypatch.setattr(connector_main, "OPRF_CONFIG", None)
    state = {"down": False, "requests": []}

    def handle(request: httpx.Request) -> httpx.Response:
        if state["down"]:
            raise httpx.ConnectError("core is down", request=request)
        state["requests"].append(request)
        if request.method == "POST":
            reply = core.post(request.url.path, json=json.loads(request.content))
        else:
            reply = core.get(request.url.path, params=dict(request.url.params))
        return httpx.Response(reply.status_code, content=reply.content,
                              headers={"content-type": "application/json"})

    monkeypatch.setattr(connector_main, "_core_client",
                        lambda cfg: httpx.AsyncClient(transport=httpx.MockTransport(handle)))
    yield TestClient(connector_main.app), core, state, connector_main
    settings.cache_clear()
    next(core_iter, None)


LIST = {"dependencies": [{"name": NAME, "domain": DOMAIN, "substitutability": "NO"}]}


def test_saving_a_list_sends_nothing(connector):
    """Sharing is a decision. Typing a supplier into a form is not that decision."""
    client, _, state, _ = connector
    assert client.post("/v1/dependencies", json=LIST).json() == {"saved": 1, "published": False}
    assert state["requests"] == []


def test_publishing_needs_a_named_person(connector):
    client, _, _, _ = connector
    client.post("/v1/dependencies", json=LIST)
    assert client.post("/v1/dependencies/publish", json={}).status_code == 422


def test_a_providers_name_and_domain_never_leave_the_firm(connector):
    """The canary for this feature, checked on the bytes the connector actually sent."""
    client, _, state, _ = connector
    client.post("/v1/dependencies", json=LIST)
    assert client.post("/v1/dependencies/publish", json={"declared_by": "a.analyst"}).status_code == 200
    client.post("/v1/notices/collect")

    assert state["requests"], "nothing was sent, so nothing was proven"
    for request in state["requests"]:
        sent = request.content.decode() + str(request.url)
        assert NAME not in sent and "canary-kyc" not in sent
    assert "a.analyst" not in state["requests"][0].content.decode()


def test_the_preview_is_exactly_what_would_be_sent(connector):
    client, _, state, _ = connector
    client.post("/v1/dependencies", json=LIST)
    preview = client.post("/v1/dependencies/preview").json()
    assert preview["dependencies"][0]["provider_token"] == TOKEN
    assert NAME not in json.dumps(preview)
    assert state["requests"] == [], "a preview must not send"


def test_every_declaration_is_recorded_before_it_leaves(connector):
    """There is no moment at which something crossed and no record of it exists."""
    client, _, _, connector_main = connector
    client.post("/v1/dependencies", json=LIST)
    seen = []
    real = connector_main.LOCAL.declarations
    original = connector_main._deliver_declaration

    async def spy(record):
        seen.append(len(real()))
        return await original(record)

    connector_main._deliver_declaration = spy
    try:
        client.post("/v1/dependencies/publish", json={"declared_by": "a.analyst"})
    finally:
        connector_main._deliver_declaration = original
    assert seen == [1]


def test_an_outage_queues_the_declaration_and_a_retry_resends_it_unchanged(connector):
    """A retry resends the recorded payload. It never rebuilds."""
    client, _, state, connector_main = connector
    client.post("/v1/dependencies", json=LIST)
    state["down"] = True
    assert client.post("/v1/dependencies/publish", json={"declared_by": "a.analyst"}).status_code == 503
    queued = connector_main.LOCAL.declarations(status="QUEUED")
    assert len(queued) == 1

    state["down"] = False
    assert client.post("/v1/declarations/retry").json()["results"][0]["status"] == "ACCEPTED"
    assert json.loads(state["requests"][-1].content)["declaration_id"] == queued[0]["declaration_id"]


def test_a_tampered_record_is_refused_rather_than_resent(connector):
    client, _, state, connector_main = connector
    client.post("/v1/dependencies", json=LIST)
    state["down"] = True
    client.post("/v1/dependencies/publish", json={"declared_by": "a.analyst"})
    connector_main.LOCAL.declarations()[0]["payload"]["sequence"] = 99
    state["down"] = False
    assert client.post("/v1/declarations/retry").json()["results"][0]["status"] == "REFUSED"


def test_the_firm_sees_the_alert_under_its_own_name_for_the_provider(connector):
    """The core only has a token. The name comes from the firm's own list."""
    client, core, _, _ = connector
    client.post("/v1/dependencies", json=LIST)
    client.post("/v1/dependencies/publish", json={"declared_by": "a.analyst"})
    core.post("/v1/declarations", json=_incident())
    assert client.post("/v1/notices/collect").json()["new_notices"] == 1

    alerts = client.get("/v1/provider-alerts").json()
    assert alerts[0]["provider"] == NAME
    assert alerts[0]["severity_band"] == "HIGH"


def test_a_connector_that_is_not_a_provider_cannot_declare_a_provider_incident(connector):
    client, _, state, _ = connector
    response = client.post("/v1/provider-incidents",
                           json={"severity": "HIGH", "declared_by": "a.analyst"})
    assert response.status_code == 409
    assert state["requests"] == []


def test_a_provider_declares_once_and_learns_only_a_count(connector, monkeypatch):
    client, core, _, _ = connector
    from marsad_connector.config import settings

    for ref in (B, C):
        core.post("/v1/declarations", json=_dependencies(ref))
    monkeypatch.setenv("MARSAD_INSTITUTION_REF", OWNER)
    monkeypatch.setenv("MARSAD_PROVIDER_DOMAIN", DOMAIN)
    settings.cache_clear()
    reply = client.post("/v1/provider-incidents",
                        json={"severity": "CRITICAL", "declared_by": "a.analyst"})
    assert reply.status_code == 200
    assert reply.json()["core_response"]["dependents_notified"] == 2


def test_extraction_does_not_declare_anything_by_itself():
    """A vendor named in a narrative is local context. Declaring is a separate, human act."""
    source = (ROOT / "services/connector/marsad_connector/agents/a2_extract.py").read_text()
    assert "build_dependency_declaration" not in source


def test_provider_tokens_work_under_the_split_key_too(tmp_path):
    """Same protocol as indicators, a separate input space, and agreement between firms."""
    sys.path.insert(0, str(ROOT / "services" / "evaluator"))
    from marsad_connector.crypto.oprf_client import OprfConfig, resolve_provider_tokens
    from marsad_evaluator.main import Settings, create_app
    from marsad_oprf.threshold import deal

    shares, public = deal(1, 2, 3)
    apps = {s.index: create_app(Settings(
        share_json=json.dumps(s.to_dict()), audit_log=str(tmp_path / f"a{s.index}.jsonl"),
    )) for s in shares}
    config = OprfConfig.parse(1, 2, public.group_key, json.dumps([
        {"index": i, "url": f"http://c{i}", "public_share": p}
        for i, p in public.public_shares.items()
    ]))

    def client(custodian):
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=apps[custodian.index]))

    first = asyncio.run(resolve_provider_tokens([DOMAIN], config, client))
    second = asyncio.run(resolve_provider_tokens([DOMAIN], config, client))
    assert first == second
    assert first[DOMAIN].startswith("00000001") and len(first[DOMAIN]) == 40
