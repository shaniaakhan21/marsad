"""
Split-key tokenisation — the claims the prototype's shared HMAC key could not make.

No single party can create or reverse a token; the party evaluating never sees the
indicator; a custodian cannot lie undetected; and the redaction agent still holds no
network capability. The first tests pin the primitive to RFC 9497's published vectors,
so everything above them is built on the standard rather than on our reading of it.
"""

from __future__ import annotations

import ast
import asyncio
import json
import sys
from itertools import combinations
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "packages" / "contracts"),
    str(ROOT / "packages" / "oprf"),
    str(ROOT / "services" / "connector"),
    str(ROOT / "services" / "evaluator"),
]

from marsad_connector.agents.a3_redact import RedactionAgent
from marsad_connector.crypto.oprf_client import (
    OprfConfig,
    indicator_input,
    resolve_tokens,
)
from marsad_connector.crypto.tokeniser import OprfUnavailable, TokenNotEvaluated
from marsad_contracts.boundary import (
    IncidentSubmission,
    IndicatorType,
    Sector,
    SizeBand,
)
from marsad_evaluator.main import Settings, create_app
from marsad_oprf import group, voprf
from marsad_oprf.threshold import (
    PublicKeySet,
    QuorumError,
    assert_consistent,
    combine,
    deal,
)

SK = "e6f73f344b79b379f1a0dd37e07ff62e38d9f71345ce62ae3a9bc60b04ccd909"
PK = "c803e2cc6b05fc15064549b5920659ca4a77b2cca6f04f6b357009335476ad4e"
BLIND_1 = "64d37aed22a27f5191de1c1d69fadb899d8862b58eb4220029e036ec4c1f6706"
BLIND_2 = "222a5e897cf59db8145db8d16e597e8facb80ae7d4e26d9881aa6f61d645fc0e"
OUT_1 = ("b58cfbe118e0cb94d79b5fd6a6dafb98764dff49c14e1770b566e42402da1a7d"
         "a4d8527693914139caee5bd03903af43a491351d23b430948dd50cde10d32b3c")
OUT_2 = ("8a9a2f3c7f085b65933594309041fc1898d42d0858e59f90814ae90571a6df60"
         "356f4610bf816f27afdd84f47719e480906d27ecd994985890e5f539e7ea74b6")

VECTORS = [
    # RFC 9497 Appendix A.1.2.1, A.1.2.2, A.1.2.3
    (["00"], [BLIND_1],
     ["863f330cc1a1259ed5a5998a23acfd37fb4351a793a5b3c090b642ddc439b945"],
     ["aa8fa048764d5623868679402ff6108d2521884fa138cd7f9c7669a9a014267e"],
     ("ddef93772692e535d1a53903db24367355cc2cc78de93b3be5a8ffcc6985dd06"
      "6d4346421d17bf5117a2a1ff0fcb2a759f58a539dfbe857a40bce4cf49ec600d"),
     BLIND_2, [OUT_1]),
    (["5a" * 17], [BLIND_1],
     ["cc0b2a350101881d8a4cba4c80241d74fb7dcbfde4a61fde2f91443c2bf9ef0c"],
     ["60a59a57208d48aca71e9e850d22674b611f752bed48b36f7a91b372bd7ad468"],
     ("401a0da6264f8cf45bb2f5264bc31e109155600babb3cd4e5af7d181a2c9dc0a"
      "67154fabf031fd936051dec80b0b6ae29c9503493dde7393b722eafdf5a50b02"),
     BLIND_2, [OUT_2]),
    (["00", "5a" * 17], [BLIND_1, BLIND_2],
     ["863f330cc1a1259ed5a5998a23acfd37fb4351a793a5b3c090b642ddc439b945",
      "90a0145ea9da29254c3a56be4fe185465ebb3bf2a1801f7124bbbadac751e654"],
     ["aa8fa048764d5623868679402ff6108d2521884fa138cd7f9c7669a9a014267e",
      "cc5ac221950a49ceaa73c8db41b82c20372a4c8d63e5dded2db920b7eee36a2a"],
     ("cc203910175d786927eeb44ea847328047892ddf8590e723c37205cb74600b0a"
      "5ab5337c8eb4ceae0494c2cf89529dcf94572ed267473d567aeed6ab873dee08"),
     "419c4f4f5052c53c45f3da494d2b67b220d02118e0857cdbcf037f9ea84bbe0c",
     [OUT_1, OUT_2]),
]


@pytest.mark.parametrize("vector", VECTORS, ids=["batch1a", "batch1b", "batch2"])
def test_the_primitive_reproduces_the_rfc_9497_vectors_byte_for_byte(vector):
    """A home-grown reading of a standard is not the standard. These bytes are."""
    inputs, blinds, blinded, evaluated, proof, r, outputs = vector
    h = bytes.fromhex
    sk, pk = h(SK), h(PK)
    assert group.base_mult(sk) == pk

    made = [voprf.blind(h(i), blind_scalar=h(b))[1] for i, b in zip(inputs, blinds, strict=True)]
    assert [m.hex() for m in made] == blinded
    answers = [voprf.blind_evaluate(sk, m) for m in made]
    assert [a.hex() for a in answers] == evaluated

    produced = voprf.generate_proof(sk, pk, made, answers, r=h(r))
    assert produced.to_bytes().hex() == proof
    voprf.verify_proof(pk, made, answers, produced)

    finals = [voprf.finalize(h(i), h(b), a)
              for i, b, a in zip(inputs, blinds, answers, strict=True)]
    assert [f.hex() for f in finals] == outputs


# ---------------------------------------------------------------- a working federation


class Federation:
    """Three real custodian apps, reached over an in-process HTTP transport."""

    def __init__(self, tmp_path, epoch=1, budget=5000, threshold=2, parties=3):
        self.shares, self.public = deal(epoch, threshold, parties)
        self.epoch, self.threshold = epoch, threshold
        self.tmp_path, self.budget = tmp_path, budget
        self.apps = {}
        self.down: set[int] = set()
        self.bodies: list[str] = []
        self.tamper: dict[int, object] = {}
        for share in self.shares:
            self.apps[share.index] = self.build_app(share)

    def build_app(self, share):
        return create_app(Settings(
            share_json=json.dumps(share.to_dict()), daily_element_budget=self.budget,
            audit_log=str(self.tmp_path / f"audit-e{self.epoch}-{share.index}.jsonl"),
        ))

    def config(self, *, indices=None) -> OprfConfig:
        return OprfConfig.parse(
            self.epoch, self.threshold, self.public.group_key,
            json.dumps([
                {"index": i, "url": f"http://custodian{i}", "public_share": p}
                for i, p in self.public.public_shares.items()
                if indices is None or i in indices
            ]),
        )

    def client(self, custodian) -> httpx.AsyncClient:
        federation = self

        class Observed(httpx.AsyncBaseTransport):
            async def handle_async_request(self, request):
                if custodian.index in federation.down:
                    raise httpx.ConnectError("custodian is down")
                federation.bodies.append(request.content.decode())
                inner = httpx.ASGITransport(app=federation.apps[custodian.index])
                response = await inner.handle_async_request(request)
                tamper = federation.tamper.get(custodian.index)
                if tamper is None:
                    return response
                body = json.loads(await response.aread())
                tamper(body)
                return httpx.Response(response.status_code, json=body)

        return httpx.AsyncClient(transport=Observed(), base_url="http://custodian")

    def resolve(self, indicators, config=None, label="psd_test0001"):
        return asyncio.run(resolve_tokens(
            indicators, config or self.config(), self.client, client_label=label,
        ))


@pytest.fixture
def federation(tmp_path) -> Federation:
    return Federation(tmp_path)


IP = {"type": "IP", "value": "203.0.113.77"}
DOMAIN = {"type": "DOMAIN", "value": "canary-oprf-domain.example"}


def token_of(tokeniser, indicator) -> str:
    return tokeniser.tokenise(indicator["value"], IndicatorType(indicator["type"]))


def test_two_connectors_holding_one_indicator_produce_one_token(federation):
    """Interoperability: correlation is impossible without this, whichever quorum answers."""
    first = federation.resolve([IP], label="psd_firm00a")
    federation.down = {1}
    second = federation.resolve([IP], label="psd_firm00b")
    federation.down = {3}
    third = federation.resolve([IP], label="psd_firm00c")
    assert token_of(first, IP) == token_of(second, IP) == token_of(third, IP)


def test_different_indicators_produce_different_tokens(federation):
    table = federation.resolve([IP, DOMAIN])
    assert token_of(table, IP) != token_of(table, DOMAIN)


def test_a_token_is_valid_on_the_unchanged_boundary_contract(federation):
    token = token_of(federation.resolve([IP]), IP)
    IncidentSubmission.model_validate({
        "submission_id": "x", "institution_ref": "psd_firm00a",
        "tokens": [{"type": "IP", "token": token}],
        "coarse": {"sector": "BANK", "size_band": "MID", "severity_band": "HIGH",
                   "ts_bucket": "2026-08-19T08:00:00+00:00"},
    })


def test_the_incident_submission_gained_no_field_for_the_oprf():
    """Replacing the tokeniser must not widen what crosses to the core. Not by one field."""
    assert set(IncidentSubmission.model_fields) == {
        "schema_version", "submission_id", "institution_ref", "tokens", "technique_set",
        "coarse", "obligation_ref", "disclosure_rung",
    }


def test_a_single_share_cannot_evaluate_alone(federation):
    """The promise to CMA: no single party, including Vertech, can make a token."""
    federation.down = {2, 3}
    with pytest.raises(OprfUnavailable):
        federation.resolve([IP])


def test_one_shares_output_is_not_the_token_even_if_someone_finalises_it(federation):
    """The refusal is not just client politeness: one share's maths gives a wrong value."""
    data = indicator_input(IndicatorType.IP, "203.0.113.77")
    blind_scalar, blinded = voprf.blind(data)
    partials = {s.index: voprf.blind_evaluate(s.scalar, blinded) for s in federation.shares}

    real = voprf.finalize(data, blind_scalar, combine(partials, 2))
    for partial in partials.values():
        assert voprf.finalize(data, blind_scalar, partial) != real
    with pytest.raises(QuorumError):
        combine({1: partials[1]}, 2)


def test_every_quorum_computes_the_same_prf_as_the_unsplit_key():
    """Splitting the key must be invisible in the output, for any pair of custodians."""
    shares, public = deal(1, 2, 3)
    data = b"IP\x1f198.51.100.9"
    blind_scalar, blinded = voprf.blind(data)
    partials = {s.index: voprf.blind_evaluate(s.scalar, blinded) for s in shares}
    outputs = {
        voprf.finalize(data, blind_scalar, combine({i: partials[i] for i in pair}, 2))
        for pair in combinations(partials, 2)
    }
    assert len(outputs) == 1

    # Reconstruct k here, as only a test may, and compare with direct evaluation.
    from marsad_oprf.threshold import lagrange_at_zero

    key = group.scalar_add(
        group.scalar_mul(lagrange_at_zero(1, [1, 2]), shares[0].scalar),
        group.scalar_mul(lagrange_at_zero(2, [1, 2]), shares[1].scalar),
    )
    assert group.base_mult(key).hex() == public.group_key
    assert outputs == {voprf.evaluate(key, data)}


def test_a_custodian_never_sees_the_indicator(federation):
    """The defining property of the protocol, checked on the actual bytes on the wire."""
    federation.resolve([IP, DOMAIN])
    wire = "".join(federation.bodies)
    assert federation.bodies, "nothing was sent, so nothing was proven"
    for secret in ("203.0.113.77", "canary-oprf-domain", b"canary".hex(), "IP\\u001f"):
        assert secret not in wire


def test_the_same_indicator_looks_different_to_a_custodian_every_time(federation):
    """Otherwise a custodian could tell that two firms, or two days, shared an indicator."""
    federation.resolve([IP])
    first = {tuple(json.loads(b)["blinded_elements"]) for b in federation.bodies}
    federation.bodies.clear()
    federation.resolve([IP])
    second = {tuple(json.loads(b)["blinded_elements"]) for b in federation.bodies}
    assert not first & second


def test_a_custodian_that_cheats_is_ignored_and_the_honest_quorum_still_works(
    federation, caplog,
):
    """A wrong answer must not become a token that silently never matches anyone's."""
    honest = token_of(federation.resolve([IP]), IP)

    def swap_in_another_element(body):
        body["evaluated_elements"][0] = voprf.hash_to_group(b"forged").hex()

    federation.tamper[1] = swap_in_another_element
    assert token_of(federation.resolve([IP]), IP) == honest
    assert "oprf.proof_failed custodian=1" in caplog.text


def test_too_many_cheating_custodians_fail_closed_rather_than_downgrading(federation):
    """There is no weaker fallback. No quorum means no token, and the caller is told."""

    def forge(body):
        body["evaluated_elements"][0] = voprf.hash_to_group(b"forged").hex()

    federation.tamper = {1: forge, 2: forge}
    with pytest.raises(OprfUnavailable):
        federation.resolve([IP])


def test_tokens_from_different_key_epochs_never_compare_equal(tmp_path):
    """After rotation an old token must not look like a current one, or match by chance."""
    old = Federation(tmp_path, epoch=1).resolve([IP])
    new = Federation(tmp_path, epoch=2).resolve([IP])
    assert token_of(old, IP)[:8] == "00000001"
    assert token_of(new, IP)[:8] == "00000002"
    assert token_of(old, IP) != token_of(new, IP)


def test_a_custodian_refuses_an_epoch_it_does_not_hold(federation):
    from fastapi.testclient import TestClient

    client = TestClient(federation.apps[1])
    _, element = voprf.blind(b"x")
    response = client.post("/v1/oprf/evaluate", json={"epoch": 99, "blinded_elements": [element.hex()]})
    assert response.status_code == 409


def test_a_custodian_refuses_an_invalid_group_element(federation):
    """Input from the network is validated before a secret share is multiplied by it."""
    from fastapi.testclient import TestClient

    client = TestClient(federation.apps[1])
    response = client.post("/v1/oprf/evaluate",
                           json={"epoch": 1, "blinded_elements": ["ff" * 32]})
    assert response.status_code == 422


def test_bulk_enumeration_is_refused_by_the_daily_budget(tmp_path):
    """The attack that remains: asking online. It takes billions of queries; this stops it."""
    federation = Federation(tmp_path, budget=3)
    federation.resolve([IP, DOMAIN], label="psd_scraper1")
    with pytest.raises(OprfUnavailable):
        federation.resolve([{"type": "IP", "value": "203.0.113.78"},
                            {"type": "IP", "value": "203.0.113.79"}], label="psd_scraper1")
    federation.resolve([{"type": "IP", "value": "203.0.113.80"}], label="psd_otherfirm")


def test_restarting_a_custodian_does_not_reset_the_budget(tmp_path):
    """A limit a restart clears is a limit an attacker waits out."""
    federation = Federation(tmp_path, budget=2)
    federation.resolve([IP, DOMAIN], label="psd_scraper1")
    federation.apps = {s.index: federation.build_app(s) for s in federation.shares}
    with pytest.raises(OprfUnavailable):
        federation.resolve([IP], label="psd_scraper1")


def test_the_audit_log_records_every_evaluation_and_no_element(federation, tmp_path):
    """Enumeration must be visible, and the log must not itself allow linking requests."""
    federation.resolve([IP, DOMAIN], label="psd_firm00a")
    audit = (tmp_path / "audit-e1-1.jsonl").read_text()
    entry = json.loads(audit.splitlines()[0])
    assert (entry["client"], entry["elements"], entry["decision"]) == ("psd_firm00a", 2, "EVALUATED")
    for body in federation.bodies:
        for element in json.loads(body)["blinded_elements"]:
            assert element not in audit


def test_a_custodian_requires_a_certificate_when_identity_is_enforced(federation):
    from fastapi.testclient import TestClient

    share = federation.shares[0]
    app = create_app(Settings(
        share_json=json.dumps(share.to_dict()), require_client_identity=True,
        audit_log=str(federation.tmp_path / "strict.jsonl"),
    ))
    client = TestClient(app)
    _, element = voprf.blind(b"x")
    body = {"epoch": 1, "blinded_elements": [element.hex()]}
    assert client.post("/v1/oprf/evaluate", json=body).status_code == 401
    assert client.post("/v1/oprf/evaluate", json=body,
                       headers={"X-Client-Cert-Subject": "CN=psd_firm00a,O=MARSAD"}
                       ).status_code == 200


def test_a_key_set_from_two_ceremonies_is_refused_at_startup():
    """Mixed shares pass every proof and yield tokens that never match. Stop at boot."""
    _, first = deal(1, 2, 3)
    _, second = deal(1, 2, 3)
    mixed = PublicKeySet(1, 2, first.group_key,
                         {1: first.public_shares[1], 2: second.public_shares[2],
                          3: first.public_shares[3]})
    with pytest.raises(QuorumError):
        assert_consistent(mixed)


def test_a_one_of_n_split_cannot_be_dealt():
    """A threshold of one is a shared key under another name."""
    with pytest.raises(ValueError, match="one share"):
        deal(1, 1, 3)


# ---------------------------------------------------------------- A3 stays offline


class _Incident:
    narrative = "Credentials were sent to a harvesting page during the outage window."
    analyst_notes = None
    techniques = ("T1566",)
    severity = "HIGH"
    obligation_receipt = None
    detected_at = None
    indicators = (IP, DOMAIN)


def test_the_redaction_agent_still_holds_no_network_capability():
    """A reviewer reads one file and knows it cannot talk to anything. The OPRF kept that."""
    source = (ROOT / "services/connector/marsad_connector/agents/a3_redact.py").read_text()
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert not imported & {"httpx", "requests", "urllib", "socket", "aiohttp", "http"}


def test_a3_builds_a_valid_submission_from_prefetched_tokens(federation):
    tokeniser = federation.resolve(list(_Incident.indicators))
    submission = RedactionAgent(tokeniser).build_submission(
        _Incident(), institution_ref="psd_firm00a", sector=Sector.BANK, size_band=SizeBand.MID,
    )
    assert {kt.token for kt in submission.tokens} == {
        token_of(tokeniser, IP), token_of(tokeniser, DOMAIN),
    }
    assert "203.0.113.77" not in submission.model_dump_json()


def test_an_indicator_the_custodians_never_saw_fails_the_build_rather_than_vanishing(federation):
    """A3 drops untokenisable values and continues; a skipped one must not be dropped."""
    tokeniser = federation.resolve([IP])
    with pytest.raises(TokenNotEvaluated):
        RedactionAgent(tokeniser).build_submission(
            _Incident(), institution_ref="psd_firm00a",
            sector=Sector.BANK, size_band=SizeBand.MID,
        )


def test_the_tokeniser_scheme_records_the_custody_it_was_built_under(federation):
    """Nothing degrades silently: every outbound record says software custody, 2-of-3."""
    scheme = federation.resolve([IP]).scheme
    assert scheme == "oprf-ristretto255-sha512-e1-2of3-software"
    assert len(scheme) <= 64, "tokeniser_scheme is a VARCHAR(64) column"


# ---------------------------------------------------------------- through the real connector


@pytest.fixture
def connector(federation, monkeypatch):
    from fastapi.testclient import TestClient
    from marsad_connector import main as connector_main
    from marsad_connector.config import settings

    monkeypatch.setenv("MARSAD_TOKENISER", "oprf")
    settings.cache_clear()
    monkeypatch.setattr(connector_main, "OPRF_CONFIG", federation.config())
    monkeypatch.setattr(connector_main, "_custodian_client", federation.client)
    yield TestClient(connector_main.app), connector_main
    settings.cache_clear()


INCIDENT = {"narrative": "Phishing page observed during the morning shift.",
            "indicators": [IP], "techniques": ["T1566"], "severity": "HIGH"}


def test_the_preview_shows_oprf_tokens_through_the_real_connector(connector):
    client, _ = connector
    iid = client.post("/v1/incidents", json=INCIDENT).json()["incident_id"]
    preview = client.post(f"/v1/incidents/{iid}/preview")
    assert preview.status_code == 200
    token = preview.json()["tokens"][0]["token"]
    assert len(token) == 40 and token.startswith("00000001")


def test_a_custodian_outage_returns_503_and_records_nothing(federation, connector):
    """Additive by design: the incident stays, nothing half-built leaves, retry works."""
    client, connector_main = connector
    iid = client.post("/v1/incidents", json=INCIDENT).json()["incident_id"]

    federation.down = {1, 2, 3}
    response = client.post(f"/v1/incidents/{iid}/submit")
    assert response.status_code == 503
    assert connector_main.OUTBOUND.for_incident(iid) == []
    assert client.get(f"/v1/incidents/{iid}").status_code == 200
