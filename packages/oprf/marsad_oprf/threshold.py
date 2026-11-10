"""
Threshold evaluation: the key exists only as shares.

Shamir shares of the PRF key are held by independent custodians. A custodian evaluates
with its share and proves it did; the client combines any `threshold` partial results
in the exponent. The combined value is exactly what the unsplit key would have
produced, yet no custodian ever holds that key and no custodian alone can produce it.

Honest limits, stated where a reviewer will look
------------------------------------------------
`deal` is a trusted-dealer split: the key exists for a moment in the memory of whoever
runs the ceremony. Distributed key generation removes that moment and is the upgrade
path. Shares live in software until hardware security modules are procured. Tokenisers
built on this carry `software` in their scheme, so every record says so.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from marsad_oprf import group, voprf


class QuorumError(ValueError):
    """Fewer valid, distinct shares than the threshold requires."""


@dataclass(frozen=True)
class KeyShare:
    """What one custodian holds. `share` is secret and everything else is public."""

    epoch: int
    index: int
    threshold: int
    parties: int
    share: str

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def scalar(self) -> bytes:
        return bytes.fromhex(self.share)

    @property
    def public(self) -> bytes:
        return group.base_mult(self.scalar)


@dataclass(frozen=True)
class PublicKeySet:
    """What every connector pins. Fetching it from an evaluator would defeat the proof."""

    epoch: int
    threshold: int
    group_key: str
    public_shares: dict[int, str]

    def to_dict(self) -> dict:
        return asdict(self)


def deal(epoch: int, threshold: int, parties: int) -> tuple[list[KeyShare], PublicKeySet]:
    """Split a fresh key. The key itself is never returned; see the module docstring."""
    if not 2 <= threshold <= parties:
        raise ValueError("need 2 <= threshold <= parties, or one share could evaluate alone")

    secret = group.random_scalar()
    coefficients = [secret] + [group.random_scalar() for _ in range(threshold - 1)]

    shares: list[KeyShare] = []
    for index in range(1, parties + 1):
        x = group.scalar_from_int(index)
        value = bytes(group.SCALAR_BYTES)
        for coefficient in reversed(coefficients):  # Horner's rule
            value = group.scalar_add(group.scalar_mul(value, x), coefficient)
        shares.append(KeyShare(epoch, index, threshold, parties, value.hex()))

    return shares, PublicKeySet(
        epoch=epoch, threshold=threshold, group_key=group.base_mult(secret).hex(),
        public_shares={s.index: s.public.hex() for s in shares},
    )


def lagrange_at_zero(index: int, indices: list[int]) -> bytes:
    """The Lagrange coefficient for `index` when interpolating these indices at 0."""
    numerator = group.scalar_from_int(1)
    denominator = group.scalar_from_int(1)
    x_i = group.scalar_from_int(index)
    for other in indices:
        if other == index:
            continue
        x_j = group.scalar_from_int(other)
        numerator = group.scalar_mul(numerator, x_j)
        denominator = group.scalar_mul(denominator, group.scalar_sub(x_j, x_i))
    return group.scalar_mul(numerator, group.invert_scalar(denominator))


def combine(partials: dict[int, bytes], threshold: int) -> bytes:
    """
    Interpolate `threshold` partial results in the exponent.

    Refuses too few. Fewer points than the polynomial's degree still yield a value, a
    uniformly wrong one, so a short quorum must be an error and never a token.
    """
    if len(partials) < threshold:
        raise QuorumError(f"have {len(partials)} partial results, need {threshold}")
    indices = sorted(partials)[:threshold]
    total: bytes | None = None
    for index in indices:
        weighted = group.mult(lagrange_at_zero(index, indices), partials[index])
        total = weighted if total is None else group.add(total, weighted)
    assert total is not None
    return total


def assert_consistent(keys: PublicKeySet) -> None:
    """
    Check a pinned key set describes one polynomial and one group key.

    Run at connector start: a share list from two ceremonies would otherwise pass every
    proof and produce tokens that silently never match anyone's.
    """
    from itertools import combinations

    public = {int(i): bytes.fromhex(p) for i, p in keys.public_shares.items()}
    if len(public) < keys.threshold or keys.threshold < 2:
        raise QuorumError("key set has fewer custodians than its threshold")
    for subset in combinations(sorted(public), keys.threshold):
        if combine({i: public[i] for i in subset}, keys.threshold).hex() != keys.group_key:
            raise QuorumError(f"custodians {subset} do not reconstruct the group key")


__all__ = [
    "KeyShare", "PublicKeySet", "QuorumError", "assert_consistent", "combine", "deal",
    "lagrange_at_zero", "voprf",
]
