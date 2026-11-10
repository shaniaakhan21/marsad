"""
Where Merkle roots are written. The swap point for the trust assumption.

`LocalChainLedger` is a hash chain inside the core's own database. It makes the whole
pipeline work and catches accidental or partial edits, but an administrator holding the
database could rewrite the chain from end to end, so it says `reduced_fidelity = True`
and every proof it backs carries that label.

`BesuLedger` writes to a permissioned Hyperledger Besu network whose validators are run
by independent parties. There, rewriting a record requires a quorum of them.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from marsad_core.db.models import LocalLedgerEntry
from marsad_core.db.session import session_scope


class LedgerUnavailable(RuntimeError):
    """The ledger could not be written or read. Anchoring retries; submissions never wait."""


@dataclass(frozen=True)
class AnchorRecord:
    transaction: str
    block: int
    anchored_at: datetime


class LedgerBackend(Protocol):
    name: str
    reduced_fidelity: bool

    def anchor(self, root: str, leaf_count: int) -> AnchorRecord: ...
    def lookup(self, root: str) -> AnchorRecord | None: ...


class LocalChainLedger:
    """Append-only hash chain in the core database. See the module docstring."""

    name = "local-hash-chain"
    reduced_fidelity = True

    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory

    def anchor(self, root: str, leaf_count: int) -> AnchorRecord:
        now = datetime.now(timezone.utc)
        with session_scope(self._factory) as session:
            existing = session.scalar(
                sa.select(LocalLedgerEntry).where(LocalLedgerEntry.merkle_root == root))
            if existing is not None:
                return self._record(existing)
            tip = session.scalar(
                sa.select(LocalLedgerEntry).order_by(LocalLedgerEntry.height.desc()).limit(1))
            height = (tip.height + 1) if tip else 1
            entry = LocalLedgerEntry(
                height=height, merkle_root=root, leaf_count=leaf_count,
                previous_hash=tip.entry_hash if tip else "0" * 64,
                entry_hash="", anchored_at=now,
            )
            entry.entry_hash = self.entry_hash(entry)
            session.add(entry)
            session.flush()
            return self._record(entry)

    def lookup(self, root: str) -> AnchorRecord | None:
        with session_scope(self._factory) as session:
            entry = session.scalar(
                sa.select(LocalLedgerEntry).where(LocalLedgerEntry.merkle_root == root))
            return self._record(entry) if entry is not None else None

    def chain_intact(self) -> bool:
        """True if every entry links to the one before it and hashes to what it claims."""
        with session_scope(self._factory) as session:
            previous = "0" * 64
            for entry in session.scalars(
                sa.select(LocalLedgerEntry).order_by(LocalLedgerEntry.height)
            ):
                if entry.previous_hash != previous or self.entry_hash(entry) != entry.entry_hash:
                    return False
                previous = entry.entry_hash
        return True

    @staticmethod
    def entry_hash(entry: LocalLedgerEntry) -> str:
        material = json.dumps(
            [entry.height, entry.merkle_root, entry.leaf_count, entry.previous_hash],
            separators=(",", ":"),
        )
        return hashlib.sha256(material.encode()).hexdigest()

    @staticmethod
    def _record(entry: LocalLedgerEntry) -> AnchorRecord:
        return AnchorRecord(entry.entry_hash, entry.height, entry.anchored_at)


class BesuLedger:
    """
    Anchors roots through the ReceiptAnchor contract on a permissioned Besu network.

    `anchor` is idempotent: the contract keeps the first timestamp for a root, so a retry
    after a lost response reads the existing record instead of writing a second one.
    web3 is imported here so a core using the local chain never loads it.
    """

    name = "hyperledger-besu-qbft"
    reduced_fidelity = False

    def __init__(self, rpc_url: str, contract_address: str, private_key: str,
                 artifact_path: str, *, confirmation_timeout: int = 30) -> None:
        from web3 import Web3

        artifact = json.loads(Path(artifact_path).read_text())
        self._web3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 10}))
        self._contract = self._web3.eth.contract(
            address=Web3.to_checksum_address(contract_address), abi=artifact["abi"],
        )
        self._account = self._web3.eth.account.from_key(private_key)
        self._timeout = confirmation_timeout

    def lookup(self, root: str) -> AnchorRecord | None:
        try:
            timestamp, block = self._contract.functions.anchors(bytes.fromhex(root)).call()
        except Exception as exc:
            raise LedgerUnavailable(type(exc).__name__) from exc
        if timestamp == 0:
            return None
        return AnchorRecord(transaction=f"block:{block}", block=block,
                            anchored_at=datetime.fromtimestamp(timestamp, timezone.utc))

    def anchor(self, root: str, leaf_count: int) -> AnchorRecord:
        existing = self.lookup(root)
        if existing is not None:
            return existing
        try:
            transaction = self._contract.functions.anchor(
                bytes.fromhex(root), leaf_count,
            ).build_transaction({
                "from": self._account.address, "gasPrice": 0, "gas": 200_000,
                "nonce": self._web3.eth.get_transaction_count(self._account.address),
                "chainId": self._web3.eth.chain_id,
            })
            signed = self._account.sign_transaction(transaction)
            sent = self._web3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = self._web3.eth.wait_for_transaction_receipt(sent, timeout=self._timeout)
            if receipt["status"] != 1:
                raise LedgerUnavailable("anchor transaction reverted")
        except LedgerUnavailable:
            raise
        except Exception as exc:
            raise LedgerUnavailable(type(exc).__name__) from exc
        # The time comes from the contract, which is what a later proof will read, so
        # the record and every later check agree by construction.
        written = self.lookup(root)
        if written is None:
            raise LedgerUnavailable("transaction mined but the root is not on the contract")
        return AnchorRecord(sent.hex(), written.block, written.anchored_at)


__all__ = ["AnchorRecord", "BesuLedger", "LedgerBackend", "LedgerUnavailable",
           "LocalChainLedger"]
