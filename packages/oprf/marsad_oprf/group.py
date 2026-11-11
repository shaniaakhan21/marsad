"""
The ristretto255 group, as this package uses it.

No curve arithmetic is implemented here. Every operation is libsodium's, which is
constant-time and widely reviewed; this module only names them and enforces the one
rule RFC 9497 adds on top, that the identity element is not a valid protocol message.
A hand-written group in Python would be slower, variable-time, and would be the first
thing a cryptography reviewer asked us to delete.
"""

from __future__ import annotations

import pysodium as sodium

ELEMENT_BYTES = 32
SCALAR_BYTES = 32
_IDENTITY = bytes(ELEMENT_BYTES)


class InvalidElement(ValueError):
    """Bytes that do not decode to a usable group element or scalar."""


def validate_element(element: bytes) -> bytes:
    """RFC 9497 DeserializeElement: canonical encoding, and not the identity."""
    if len(element) != ELEMENT_BYTES or element == _IDENTITY:
        raise InvalidElement("not a valid non-identity ristretto255 element")
    if not sodium.crypto_core_ristretto255_is_valid_point(element):
        raise InvalidElement("not a valid ristretto255 encoding")
    return element


def validate_scalar(scalar: bytes) -> bytes:
    """A canonical scalar: 32 bytes, already reduced below the group order."""
    if len(scalar) != SCALAR_BYTES:
        raise InvalidElement("a scalar is 32 bytes")
    if reduce_scalar(scalar + bytes(32)) != scalar:
        raise InvalidElement("scalar is not reduced modulo the group order")
    return scalar


def from_uniform(uniform: bytes) -> bytes:
    return sodium.crypto_core_ristretto255_from_hash(uniform)


def base_mult(scalar: bytes) -> bytes:
    return sodium.crypto_scalarmult_ristretto255_base(scalar)


def mult(scalar: bytes, element: bytes) -> bytes:
    return sodium.crypto_scalarmult_ristretto255(scalar, element)


def add(a: bytes, b: bytes) -> bytes:
    return sodium.crypto_core_ristretto255_add(a, b)


def random_scalar() -> bytes:
    return sodium.crypto_core_ristretto255_scalar_random()


def reduce_scalar(wide: bytes) -> bytes:
    return sodium.crypto_core_ristretto255_scalar_reduce(wide)


def invert_scalar(scalar: bytes) -> bytes:
    return sodium.crypto_core_ristretto255_scalar_invert(scalar)


def scalar_add(a: bytes, b: bytes) -> bytes:
    return sodium.crypto_core_ristretto255_scalar_add(a, b)


def scalar_sub(a: bytes, b: bytes) -> bytes:
    return sodium.crypto_core_ristretto255_scalar_sub(a, b)


def scalar_mul(a: bytes, b: bytes) -> bytes:
    return sodium.crypto_core_ristretto255_scalar_mul(a, b)


def scalar_from_int(value: int) -> bytes:
    return value.to_bytes(SCALAR_BYTES, "little")
