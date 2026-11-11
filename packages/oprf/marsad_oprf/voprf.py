"""
RFC 9497 VOPRF, ciphersuite ristretto255-SHA512.

Why an oblivious PRF, and why the verifiable mode
-------------------------------------------------
Indicators are low-entropy, so a token made with a key anyone holds can be reversed by
trying every IPv4 address. With an OPRF the firm learns PRF(k, x) without learning k,
and whoever holds k never sees x. The verifiable mode adds a proof that the evaluator
used the key it committed to; without it, one evaluator could answer with a different
key for one firm and quietly stop that firm's indicators ever matching anyone's. That
would be a targeted suppression of the collective signal, undetectable by the victim.

`tests/test_oprf.py` checks this module against the RFC's own test vectors, byte for
byte. Parameters named `r` and `blind_scalar` exist only so those vectors can be
replayed; production callers leave them unset and get fresh randomness.
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass

from marsad_oprf import group

CONTEXT = b"OPRFV1-\x01-ristretto255-SHA512"
_HASH_BYTES = 64
_BLOCK_BYTES = 128
_MAX_INPUT = 65535


class ProofError(ValueError):
    """An evaluation whose proof does not verify. Never use its output."""


def _i2osp(value: int, length: int) -> bytes:
    return value.to_bytes(length, "big")


def _framed(*parts: bytes) -> bytes:
    return b"".join(struct.pack(">H", len(p)) + p for p in parts)


def expand_message_xmd(message: bytes, dst: bytes, length: int) -> bytes:
    """RFC 9380 section 5.3.1 with SHA-512. Only ever asked for 64 bytes here."""
    ell = (length + _HASH_BYTES - 1) // _HASH_BYTES
    if ell > 255 or len(dst) > 255:
        raise ValueError("expand_message_xmd parameters out of range")
    dst_prime = dst + _i2osp(len(dst), 1)
    b0 = hashlib.sha512(
        bytes(_BLOCK_BYTES) + message + _i2osp(length, 2) + b"\x00" + dst_prime
    ).digest()
    block = hashlib.sha512(b0 + b"\x01" + dst_prime).digest()
    output = block
    for i in range(2, ell + 1):
        mixed = bytes(x ^ y for x, y in zip(b0, block, strict=True))
        block = hashlib.sha512(mixed + _i2osp(i, 1) + dst_prime).digest()
        output += block
    return output[:length]


def hash_to_group(data: bytes) -> bytes:
    return group.from_uniform(expand_message_xmd(data, b"HashToGroup-" + CONTEXT, 64))


def hash_to_scalar(data: bytes) -> bytes:
    return group.reduce_scalar(expand_message_xmd(data, b"HashToScalar-" + CONTEXT, 64))


def blind(data: bytes, *, blind_scalar: bytes | None = None) -> tuple[bytes, bytes]:
    """The client's first move: returns (blind, blinded element). Keep the blind local."""
    if len(data) > _MAX_INPUT:
        raise ValueError("input exceeds the RFC 9497 length limit")
    scalar = blind_scalar if blind_scalar is not None else group.random_scalar()
    return scalar, group.mult(scalar, hash_to_group(data))


def blind_evaluate(key: bytes, blinded: bytes) -> bytes:
    """The evaluator's move. Validates first: the element came from the network."""
    return group.mult(key, group.validate_element(blinded))


def unblind(blind_scalar: bytes, evaluated: bytes) -> bytes:
    return group.mult(group.invert_scalar(blind_scalar), evaluated)


def finalize(data: bytes, blind_scalar: bytes, evaluated: bytes) -> bytes:
    unblinded = unblind(blind_scalar, evaluated)
    return hashlib.sha512(_framed(data, unblinded) + b"Finalize").digest()


def evaluate(key: bytes, data: bytes) -> bytes:
    """The PRF computed directly by someone holding both key and input. For tests."""
    issued = group.mult(key, hash_to_group(data))
    return hashlib.sha512(_framed(data, issued) + b"Finalize").digest()


# ---------------------------------------------------------------- the proof


@dataclass(frozen=True)
class Proof:
    c: bytes
    s: bytes

    def to_bytes(self) -> bytes:
        return self.c + self.s

    @classmethod
    def from_bytes(cls, raw: bytes) -> Proof:
        if len(raw) != group.SCALAR_BYTES * 2:
            raise ProofError("a proof is two scalars")
        try:
            return cls(group.validate_scalar(raw[:32]), group.validate_scalar(raw[32:]))
        except group.InvalidElement as exc:
            raise ProofError(str(exc)) from exc


def _composite_seed(public: bytes) -> bytes:
    return hashlib.sha512(_framed(public, b"Seed-" + CONTEXT)).digest()


def _composite_weight(seed: bytes, index: int, c: bytes, d: bytes) -> bytes:
    transcript = (
        _i2osp(len(seed), 2) + seed + _i2osp(index, 2) + _framed(c, d) + b"Composite"
    )
    return hash_to_scalar(transcript)


def _challenge(public: bytes, m: bytes, z: bytes, t2: bytes, t3: bytes) -> bytes:
    return hash_to_scalar(_framed(public, m, z, t2, t3) + b"Challenge")


def _sum(accumulator: bytes | None, element: bytes) -> bytes:
    return element if accumulator is None else group.add(accumulator, element)


def generate_proof(
    key: bytes, public: bytes, blinded: list[bytes], evaluated: list[bytes],
    *, r: bytes | None = None,
) -> Proof:
    """One DLEQ proof over the whole batch, so a batch costs one proof and not many."""
    seed = _composite_seed(public)
    m: bytes | None = None
    for i, (c, d) in enumerate(zip(blinded, evaluated, strict=True)):
        m = _sum(m, group.mult(_composite_weight(seed, i, c, d), c))
    if m is None:
        raise ValueError("cannot prove an empty batch")
    z = group.mult(key, m)

    nonce = r if r is not None else group.random_scalar()
    t2 = group.base_mult(nonce)
    t3 = group.mult(nonce, m)
    c = _challenge(public, m, z, t2, t3)
    return Proof(c=c, s=group.scalar_sub(nonce, group.scalar_mul(c, key)))


def verify_proof(
    public: bytes, blinded: list[bytes], evaluated: list[bytes], proof: Proof,
) -> None:
    """Returns only if the batch was evaluated under `public`. Raises otherwise."""
    if len(blinded) != len(evaluated) or not blinded:
        raise ProofError("batch sizes do not match")
    seed = _composite_seed(public)
    m: bytes | None = None
    z: bytes | None = None
    try:
        for i, (c, d) in enumerate(zip(blinded, evaluated, strict=True)):
            group.validate_element(d)
            weight = _composite_weight(seed, i, c, d)
            m = _sum(m, group.mult(weight, c))
            z = _sum(z, group.mult(weight, d))
        t2 = group.add(group.base_mult(proof.s), group.mult(proof.c, public))
        t3 = group.add(group.mult(proof.s, m), group.mult(proof.c, z))
    except (group.InvalidElement, ValueError, RuntimeError) as exc:
        raise ProofError(f"evaluation is malformed: {exc}") from exc
    if _challenge(public, m, z, t2, t3) != proof.c:
        raise ProofError("proof does not verify against this evaluator's public key")
