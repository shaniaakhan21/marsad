"""
The ledger claims, against three real QBFT validators and the deployed contract.

Needs `make ledger`. The in-process suite (`test_audit_ledger.py`) covers the logic; this
covers what only a real network can show: that a root reaches consensus, that the
contract refuses to rewrite one, and that the core's proof reads it back.
"""

from __future__ import annotations

import json
import secrets
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "packages" / "contracts"), str(ROOT / "services" / "core")]

pytestmark = pytest.mark.ledger

RPC = "http://127.0.0.1:8545"
CORE = "http://localhost:8000"
COMPOSE = ["docker", "compose", "-f", "docker-compose.yml", "-f", "docker-compose.ledger.yml"]


def _address() -> str:
    text = (ROOT / "docker-compose.ledger.yml").read_text()
    return text.split('MARSAD_CORE_BESU_CONTRACT_ADDRESS: "')[1].split('"')[0]


def _key() -> str:
    text = (ROOT / "docker-compose.ledger.yml").read_text()
    return text.split('MARSAD_CORE_BESU_PRIVATE_KEY: "')[1].split('"')[0]


@pytest.fixture(scope="module")
def ledger():
    from marsad_core.ledger.backends import BesuLedger

    try:
        httpx.post(RPC, json={"jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber"}, timeout=3)
    except httpx.HTTPError:
        pytest.skip("the test ledger is not running; start it with: make ledger")
    return BesuLedger(RPC, _address(), _key(), str(ROOT / "contracts" / "ReceiptAnchor.json"))


def _rpc(method: str, params: list) -> dict:
    return httpx.post(RPC, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                      timeout=10).json()


def test_three_independent_validators_produce_the_chain(ledger):
    """The operators named in the plan, as separate signing keys."""
    validators = _rpc("qbft_getValidatorsByBlockNumber", ["latest"])["result"]
    assert len(validators) == 3
    assert int(_rpc("net_peerCount", [])["result"], 16) == 2


def test_a_root_reaches_the_chain_and_reads_back(ledger):
    root = secrets.token_hex(32)
    assert ledger.lookup(root) is None
    written = ledger.anchor(root, 7)
    assert written.block > 0
    found = ledger.lookup(root)
    assert found is not None
    assert found.block == written.block


def test_anchoring_a_root_twice_keeps_the_first_timestamp(ledger):
    """A retry after a lost response must not move the moment a report was recorded."""
    root = secrets.token_hex(32)
    first = ledger.anchor(root, 1)
    time.sleep(3)
    assert ledger.anchor(root, 1).anchored_at == first.anchored_at


def test_the_contract_itself_refuses_to_overwrite_a_root(ledger):
    """Not client politeness: a direct second write is rejected by the chain."""
    root = secrets.token_hex(32)
    ledger.anchor(root, 1)
    with pytest.raises(Exception, match="already anchored"):
        ledger._contract.functions.anchor(bytes.fromhex(root), 2).call(
            {"from": ledger._account.address})


def test_only_the_operator_may_anchor(ledger):
    root = secrets.token_hex(32)
    with pytest.raises(Exception, match="not operator"):
        ledger._contract.functions.anchor(bytes.fromhex(root), 1).call(
            {"from": "0x000000000000000000000000000000000000dEaD"})


def _submission() -> dict:
    n = secrets.randbelow(10**12)
    return {
        "submission_id": f"00000000-0000-4000-8000-{n:012d}",
        "institution_ref": "psd_ledgertest",
        "tokens": [{"type": "IP", "token": secrets.token_hex(16)}],
        "technique_set": ["T1566"],
        "coarse": {"sector": "BANK", "size_band": "MID", "severity_band": "HIGH",
                   "ts_bucket": "2026-11-10T08:00:00+00:00"},
    }


def _anchored_proof(digest: str, timeout: int = 60) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        proof = httpx.get(f"{CORE}/v1/receipts/{digest}/proof", timeout=10).json()
        if proof.get("status") == "ANCHORED":
            return proof
        time.sleep(2)
    pytest.fail(f"receipt was not anchored within {timeout}s: {proof}")


@pytest.fixture
def anchored_receipt(ledger):
    response = httpx.post(f"{CORE}/v1/submissions", json=_submission(), timeout=10)
    response.raise_for_status()
    return response.json()["payload_digest"]


def test_a_receipt_verifies_end_to_end_on_the_real_ledger(anchored_receipt):
    proof = _anchored_proof(anchored_receipt)
    assert proof["verified"] is True
    assert proof["ledger"]["backend"] == "hyperledger-besu-qbft"
    assert proof["ledger"]["reduced_fidelity"] is False


def test_an_edited_row_in_the_real_database_fails_its_proof_on_the_real_ledger(anchored_receipt):
    """The promised test, on the deployment: edit Postgres directly, the proof must fail."""
    assert _anchored_proof(anchored_receipt)["verified"] is True
    edit = (f"UPDATE core.submissions SET severity_band='LOW' "
            f"WHERE payload_digest='{anchored_receipt}'")
    subprocess.run([*COMPOSE, "exec", "-T", "core-db", "psql", "-U", "marsad", "-d", "marsad_core",
                    "-c", edit], cwd=ROOT, check=True, capture_output=True)
    proof = httpx.get(f"{CORE}/v1/receipts/{anchored_receipt}/proof", timeout=10).json()
    assert proof["verified"] is False
    assert proof["checks"]["record_unchanged"] is False
    assert proof["checks"]["root_on_ledger"] is True
    json.dumps(proof)
