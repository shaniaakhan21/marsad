"""
A report cannot be secretly changed.

Each receipt's digest is batched into a Merkle root and anchored. These tests are about
what that buys: editing a stored record is detected, editing the audit tables as well is
detected, and a ledger outage costs nothing but delay.
"""

from __future__ import annotations

import hashlib
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "packages" / "contracts"), str(ROOT / "services" / "core")]

from marsad_core.ledger.merkle import inclusion_path, root_from_path, root_of

OBLIGATION = "b" * 64


def _payload(n: int, ref: str = "psd_firm00a") -> dict:
    return {
        "submission_id": f"00000000-0000-4000-8000-{n:012d}",
        "institution_ref": ref,
        "tokens": [{"type": "IP", "token": f"{n:032x}"}],
        "technique_set": ["T1566"],
        "coarse": {"sector": "BANK", "size_band": "MID", "severity_band": "HIGH",
                   "ts_bucket": "2026-08-19T08:00:00+00:00"},
        "obligation_ref": {"receipt_hash": OBLIGATION, "authority": "CMA",
                           "filed_at": "2026-08-19T09:00:00+00:00"},
    }


@pytest.fixture
def core(monkeypatch, tmp_path) -> Iterator[TestClient]:
    from marsad_core.config import settings

    monkeypatch.setenv("MARSAD_CORE_STORE", "sql")
    monkeypatch.setenv("MARSAD_CORE_DATABASE_URL", f"sqlite:///{tmp_path / 'core.db'}")
    monkeypatch.setenv("MARSAD_CORE_ANCHOR_INTERVAL_SECONDS", "0")
    settings.cache_clear()
    from marsad_core.main import STATE, app

    STATE.clear()
    with TestClient(app) as client:
        yield client
    STATE.clear()
    settings.cache_clear()


def _submit(core, n: int) -> str:
    response = core.post("/v1/submissions", json=_payload(n))
    assert response.status_code == 200
    return response.json()["payload_digest"]


def _anchorer():
    from marsad_core.main import STATE

    return STATE["anchorer"]


def _edit(statement) -> None:
    from marsad_core.main import STATE

    with STATE["db_engine"].begin() as connection:
        connection.execute(statement)


# ---------------------------------------------------------------- Merkle


@pytest.mark.parametrize("size", [1, 2, 3, 4, 5, 7, 8, 33])
def test_every_leaf_of_any_tree_has_a_proof_that_reaches_the_root(size):
    digests = [hashlib.sha256(str(i).encode()).hexdigest() for i in range(size)]
    root = root_of(digests)
    for i, digest in enumerate(digests):
        assert root_from_path(digest, inclusion_path(digests, i)) == root


def test_a_proof_does_not_verify_for_a_different_digest():
    digests = [hashlib.sha256(str(i).encode()).hexdigest() for i in range(4)]
    assert root_from_path("f" * 64, inclusion_path(digests, 0)) != root_of(digests)


def test_duplicating_the_last_leaf_cannot_produce_the_same_root():
    """The classic Merkle flaw: two different batches sharing one root."""
    a, b, c = ("a" * 64, "b" * 64, "c" * 64)
    assert root_of([a, b, c]) != root_of([a, b, c, c])


def test_an_interior_node_cannot_be_presented_as_a_leaf():
    """Without separate prefixes, a proof could be forged for something never submitted."""
    a, b, c, d = ("a" * 64, "b" * 64, "c" * 64, "d" * 64)
    path = inclusion_path([a, b, c, d], 0)
    interior = root_from_path(a, path[:1])
    assert root_from_path(interior, path[1:]) != root_of([a, b, c, d])


# ---------------------------------------------------------------- the claim


def test_an_anchored_receipt_verifies(core):
    digest = _submit(core, 1)
    run = _anchorer().run_once()
    assert (run.batches_anchored, run.receipts_anchored) == (1, 1)

    proof = core.get(f"/v1/receipts/{digest}/proof").json()
    assert proof["status"] == "ANCHORED"
    assert proof["verified"] is True
    assert all(proof["checks"].values())
    assert proof["ledger"]["block"] == 1


def test_a_firm_can_prove_a_filing_by_its_obligation_receipt(core):
    """The firm's own evidence that it filed on time, without showing what it filed."""
    _submit(core, 1)
    _anchorer().run_once()
    proof = core.get(f"/v1/receipts/{OBLIGATION}/proof").json()
    assert proof["verified"] is True
    assert proof["ledger"]["anchored_at"]


def test_editing_a_stored_record_makes_its_proof_fail(core):
    """The test promised to CMA, literally: change a stored record, the proof fails."""
    from marsad_core.db.models import Submission

    digest = _submit(core, 1)
    _anchorer().run_once()
    _edit(sa.update(Submission).values(severity_band="LOW"))

    proof = core.get(f"/v1/receipts/{digest}/proof").json()
    assert proof["verified"] is False
    assert proof["checks"]["record_unchanged"] is False
    assert proof["checks"]["root_on_ledger"] is True, "the check must say which part changed"


def test_editing_a_token_makes_its_proof_fail(core):
    from marsad_core.db.models import SubmissionToken

    digest = _submit(core, 1)
    _anchorer().run_once()
    _edit(sa.update(SubmissionToken).values(token="e" * 32))
    assert core.get(f"/v1/receipts/{digest}/proof").json()["verified"] is False


def test_rewriting_the_record_and_its_stored_digest_together_is_still_caught(core):
    """An administrator who is careful enough to update the digest column too."""
    from marsad_core.db.models import Submission

    digest = _submit(core, 1)
    _anchorer().run_once()
    _edit(sa.update(Submission).values(severity_band="LOW", payload_digest="d" * 64))
    assert core.get(f"/v1/receipts/{digest}/proof").json()["verified"] is False


def test_rewriting_the_anchored_leaf_as_well_breaks_the_root(core):
    """Editing every copy in the database still cannot change what the ledger holds."""
    from marsad_core.db.models import AnchorBatch, AnchorLeaf

    digest = _submit(core, 1)
    _submit(core, 2)
    _anchorer().run_once()
    _edit(sa.update(AnchorLeaf).where(AnchorLeaf.payload_digest == digest)
          .values(payload_digest="d" * 64))
    proof = core.get(f"/v1/receipts/{'d' * 64}/proof").json()
    assert proof["checks"]["included_in_batch"] is False
    assert proof["verified"] is False

    _edit(sa.update(AnchorBatch).values(merkle_root="c" * 64))
    proof = core.get(f"/v1/receipts/{'d' * 64}/proof").json()
    assert proof["checks"]["root_on_ledger"] is False


def test_the_local_chain_detects_a_rewritten_entry(core):
    from marsad_core.db.models import LocalLedgerEntry

    _submit(core, 1)
    _anchorer().run_once()
    _submit(core, 2)
    _anchorer().run_once()
    assert _anchorer().backend.chain_intact() is True
    _edit(sa.update(LocalLedgerEntry).where(LocalLedgerEntry.height == 1)
          .values(leaf_count=99))
    assert _anchorer().backend.chain_intact() is False


def test_a_proof_built_on_the_local_chain_says_it_is_reduced_fidelity(core):
    """An administrator could rewrite this chain whole. The proof must not hide that."""
    digest = _submit(core, 1)
    _anchorer().run_once()
    assert core.get(f"/v1/receipts/{digest}/proof").json()["ledger"]["reduced_fidelity"] is True
    assert core.get("/v1/ledger").json()["reduced_fidelity"] is True


def test_a_receipt_not_yet_batched_is_not_reported_as_verified(core):
    digest = _submit(core, 1)
    proof = core.get(f"/v1/receipts/{digest}/proof").json()
    assert (proof["status"], proof["verified"]) == ("NOT_YET_BATCHED", False)


def test_an_unknown_receipt_is_404_not_a_failed_proof(core):
    assert core.get(f"/v1/receipts/{'a' * 64}/proof").status_code == 404
    assert core.get("/v1/receipts/not-hex/proof").status_code == 422


def test_a_ledger_outage_never_blocks_a_submission_and_retries_later(core):
    """MARSAD works fully without the ledger. It may lag; it must not stop a report."""
    from marsad_core.ledger.backends import LedgerUnavailable

    anchorer = _anchorer()
    real = anchorer._backend

    class Down:
        name, reduced_fidelity = "down", True

        def anchor(self, *_):
            raise LedgerUnavailable("no quorum")

        def lookup(self, *_):
            raise LedgerUnavailable("no quorum")

    anchorer._backend = Down()
    digest = _submit(core, 1)
    run = anchorer.run_once()
    assert (run.batches_anchored, run.pending) == (0, 1)
    assert core.get(f"/v1/receipts/{digest}/proof").json()["status"] == "PENDING"

    anchorer._backend = real
    assert anchorer.run_once().batches_anchored == 1
    assert core.get(f"/v1/receipts/{digest}/proof").json()["verified"] is True


def test_a_batch_from_an_earlier_ledger_is_not_reported_as_tampering(core):
    """Changing ledger is a migration. It must not look like someone altered a record."""
    digest = _submit(core, 1)
    _anchorer().run_once()

    class Replacement:
        name, reduced_fidelity = "replacement", False

        def lookup(self, *_):
            raise AssertionError("an old root must not be looked up on the new ledger")

    _anchorer()._backend = Replacement()
    proof = core.get(f"/v1/receipts/{digest}/proof").json()
    assert proof["verified"] is False
    assert "anchored on local-hash-chain" in proof["ledger"]["error"]
    assert proof["checks"]["record_unchanged"] is True


def test_a_receipt_is_anchored_exactly_once(core):
    _submit(core, 1)
    _anchorer().run_once()
    assert _anchorer().run_once().batches_anchored == 0
    assert core.get("/v1/ledger").json()["batches"] == 1


def test_only_hashes_reach_the_ledger_and_a_proof_names_no_firm(core):
    """Purging a record later must leave nothing on the ledger that reveals it."""
    digest = _submit(core, 1)
    _anchorer().run_once()
    text = core.get(f"/v1/receipts/{digest}/proof").text
    for private in ("psd_firm00a", f"{1:032x}", "T1566", "BANK"):
        assert private not in text


def test_the_contract_cannot_overwrite_a_root():
    """The property the whole ledger exists for, stated in the source a reviewer reads."""
    source = (ROOT / "contracts" / "ReceiptAnchor.sol").read_text()
    assert 'require(anchors[root].timestamp == 0, "already anchored");' in source
    assert "selfdestruct" not in source and "delegatecall" not in source


# ---------------------------------------------------------------- regulator view


@pytest.fixture
def memory_core(monkeypatch) -> Iterator[TestClient]:
    from marsad_core.config import settings

    monkeypatch.setenv("MARSAD_CORE_STORE", "memory")
    settings.cache_clear()
    from marsad_core.main import STATE, app

    STATE.clear()
    with TestClient(app) as client:
        yield client
    STATE.clear()
    settings.cache_clear()


def _firm(n: int, ref: str, sector: str, token: str = "a" * 32) -> dict:
    payload = _payload(n, ref)
    payload.pop("obligation_ref")
    payload["coarse"]["sector"] = sector
    payload["tokens"] = [{"type": "IP", "token": token}]
    return payload


def test_the_regulator_sees_nothing_about_firms_until_k_have_reported(memory_core):
    """Two firms and a total is a disclosure about both of them."""
    for n, ref in enumerate(("psd_firm00a", "psd_firm00b")):
        memory_core.post("/v1/submissions", json=_firm(n, ref, "BANK"))
    view = memory_core.get("/v1/regulator/overview").json()
    assert view["gate"]["satisfied"] is False
    assert "campaigns" not in view and "sectors" not in view


def test_the_regulator_view_contains_no_firm_token_or_submission_id(memory_core):
    """Read-only and aggregate is the promise; a pseudonym here would break it."""
    refs = ("psd_firm00a", "psd_firm00b", "psd_firm00c")
    for n, ref in enumerate(refs):
        assert memory_core.post("/v1/submissions", json=_firm(n, ref, "BANK")).status_code == 200
    response = memory_core.get("/v1/regulator/overview")
    assert response.json()["gate"]["satisfied"] is True
    assert response.json()["campaigns"]["published"][0]["institutions"] == 3
    for private in (*refs, "a" * 32, "00000000-0000-4000-8000"):
        assert private not in response.text


def test_a_two_firm_campaign_is_withheld_from_the_market_view(memory_core):
    """Those two firms get their notice; the market does not get to see them."""
    memory_core.post("/v1/submissions", json=_firm(1, "psd_firm00a", "BANK", "a" * 32))
    memory_core.post("/v1/submissions", json=_firm(2, "psd_firm00b", "BANK", "a" * 32))
    memory_core.post("/v1/submissions", json=_firm(3, "psd_firm00c", "BANK", "b" * 32))
    campaigns = memory_core.get("/v1/regulator/overview").json()["campaigns"]
    assert campaigns["published"] == []
    assert campaigns["withheld_below_k"] >= 1


def test_a_sector_too_small_to_publish_is_never_left_to_be_found_by_subtraction(memory_core):
    """Three banks and one broker: showing "banks: 3" and a total would reveal the broker."""
    for n, ref in enumerate(("psd_firm00a", "psd_firm00b", "psd_firm00c")):
        memory_core.post("/v1/submissions", json=_firm(n, ref, "BANK", f"{n:032x}"))
    memory_core.post("/v1/submissions", json=_firm(9, "psd_firm00d", "BROKER", "f" * 32))
    groups = memory_core.get("/v1/regulator/overview").json()["sectors"]["groups"]
    assert [g["group"] for g in groups] == ["ALL_SECTORS"]
    assert groups[0]["institutions"] == 4


def test_the_regulator_view_states_that_impact_is_not_aggregated(memory_core):
    """The roadmap names impact trends; the boundary carries none. Say so, don't fake it."""
    impact = memory_core.get("/v1/regulator/overview").json()["impact"]
    assert impact["available"] is False


def test_the_regulator_view_needs_a_console_token_once_configured(memory_core, monkeypatch):
    from marsad_core.config import settings

    monkeypatch.setenv("MARSAD_CORE_CONSOLE_TOKENS", "regulator:a-regulator-token-long-enough")
    settings.cache_clear()
    assert memory_core.get("/v1/regulator/overview").status_code == 401
    assert memory_core.get("/v1/regulator/overview",
                           headers={"Authorization": "Bearer a-regulator-token-long-enough"}
                           ).status_code == 200
