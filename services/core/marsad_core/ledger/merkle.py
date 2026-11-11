"""
Merkle batching of receipt digests.

Anchoring one root per batch keeps every receipt provable while writing a single hash to
the ledger, however many reports the batch held. Leaves and interior nodes are hashed
with different prefixes (the RFC 6962 construction); without that, an interior node can
be passed off as a leaf and a proof forged for something never submitted.

An odd node is carried up unchanged rather than duplicated, because duplicating the last
leaf lets two different batches produce the same root.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

_LEAF = b"\x00"
_NODE = b"\x01"


def leaf_hash(digest_hex: str) -> bytes:
    return hashlib.sha256(_LEAF + bytes.fromhex(digest_hex)).digest()


def _node_hash(left: bytes, right: bytes) -> bytes:
    return hashlib.sha256(_NODE + left + right).digest()


@dataclass(frozen=True)
class ProofStep:
    """A sibling hash, and which side of the path it sits on."""

    side: str
    hash: str

    def as_dict(self) -> dict:
        return {"side": self.side, "hash": self.hash}


def _levels(digests: list[str]) -> list[list[bytes]]:
    if not digests:
        raise ValueError("cannot build a Merkle tree over nothing")
    levels = [[leaf_hash(d) for d in digests]]
    while len(levels[-1]) > 1:
        current = levels[-1]
        parents = [_node_hash(current[i], current[i + 1]) for i in range(0, len(current) - 1, 2)]
        if len(current) % 2:
            parents.append(current[-1])
        levels.append(parents)
    return levels


def root_of(digests: list[str]) -> str:
    return _levels(digests)[-1][0].hex()


def inclusion_path(digests: list[str], position: int) -> list[ProofStep]:
    path: list[ProofStep] = []
    index = position
    for level in _levels(digests)[:-1]:
        sibling = index + 1 if index % 2 == 0 else index - 1
        if sibling < len(level):
            side = "right" if index % 2 == 0 else "left"
            path.append(ProofStep(side, level[sibling].hex()))
        index //= 2
    return path


def root_from_path(digest_hex: str, path: list[ProofStep]) -> str:
    """What the root must be if this digest is in the tree. Needs no database."""
    current = leaf_hash(digest_hex)
    for step in path:
        other = bytes.fromhex(step.hash)
        current = _node_hash(other, current) if step.side == "left" else _node_hash(current, other)
    return current.hex()


__all__ = ["ProofStep", "inclusion_path", "leaf_hash", "root_from_path", "root_of"]
