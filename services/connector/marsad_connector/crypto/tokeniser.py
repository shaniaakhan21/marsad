"""
Tokenisation — the swap point between the hackathon prototype and production.

The whole privacy claim rests on this module. Everything above it is written
against the `Tokeniser` protocol, so upgrading from HMAC to a real OPRF is a
change of binding in one place, not a rewrite.

WHY HMAC IS NOT ENOUGH FOR PRODUCTION
-------------------------------------
Indicators are low-entropy. The entire IPv4 space is 2^32 values; UAE IBANs and
mobile numbers are similarly enumerable. Anyone holding an HMAC token *and* the
key can brute-force the input in seconds, and anyone holding the token alone can
still confirm a guess if they ever obtain the key. Because a single shared key is
used across institutions, the party holding it can enumerate everyone's
indicators — which is precisely the position we promise no one occupies.

An OPRF fixes this: the institution learns PRF(k, x) through an oblivious
protocol without learning k, and the key holder never sees x. Combined with
threshold custody (no single party can use k alone), rate limiting and audit,
bulk enumeration becomes detectable and unilaterally impossible.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import unicodedata
from abc import ABC, abstractmethod

from marsad_contracts.boundary import IndicatorType

from marsad_connector.lang.arabic import normalise as normalise_arabic

TOKEN_LEN = 32  # hex chars retained; 128 bits is ample for equality matching


def canonicalise(value: str, indicator_type: IndicatorType) -> str:
    """
    Normalise before tokenising, or two institutions holding the same indicator
    produce different tokens and the correlation silently fails.

    This function is part of the security surface: it must be identical across
    every connector, so it lives here rather than in caller code.

    Arabic normalisation is applied unconditionally, to every value, and never
    behind a language check. Two institutions writing the same Arabic-bearing
    indicator — one with hamza and diacritics, one without — must produce the same
    token, and a language detector that answered differently on the two sides would
    break that with no error to notice: just a token that never matches. The same
    `normalise` used here is the one A2 matches with, so write and query cannot drift
    apart. See `lang/arabic.py`.
    """
    v = normalise_arabic(unicodedata.normalize("NFKC", value)).strip().lower()

    if indicator_type in (IndicatorType.DOMAIN, IndicatorType.URL):
        v = v.removeprefix("http://").removeprefix("https://").rstrip("/")
        v = v.removeprefix("www.")
        # de-obfuscate the common defanged forms analysts paste in
        v = v.replace("[.]", ".").replace("(.)", ".").replace("[dot]", ".")
    elif indicator_type in (IndicatorType.IBAN, IndicatorType.ACCOUNT, IndicatorType.WALLET):
        v = "".join(ch for ch in v if ch.isalnum())
    elif indicator_type is IndicatorType.IP:
        v = v.replace("[.]", ".").strip("[]")

    if not v:
        raise ValueError("indicator is empty after canonicalisation")
    return v


class Tokeniser(ABC):
    """Contract every tokenisation strategy must satisfy."""

    #: Advertised in submissions so the core knows which epoch/scheme produced a token.
    scheme: str

    @abstractmethod
    def tokenise(self, value: str, indicator_type: IndicatorType) -> str:
        """Return a hex token of length TOKEN_LEN. Must be deterministic."""

    def tokenise_many(
        self, values: list[tuple[IndicatorType, str]]
    ) -> list[tuple[IndicatorType, str]]:
        return [(t, self.tokenise(v, t)) for t, v in values]


class HmacTokeniser(Tokeniser):
    """
    PROTOTYPE ONLY. Deterministic keyed hash with a shared secret.

    Adequate to demonstrate correlation mechanics. NOT adequate for real
    institutional data — see the module docstring.
    """

    scheme = "hmac-sha256-v1-PROTOTYPE"

    def __init__(self, key: bytes | None = None) -> None:
        key = key or os.environ.get("MARSAD_TOKEN_KEY", "").encode()
        if not key:
            raise RuntimeError("MARSAD_TOKEN_KEY is required")
        if len(key) < 16:
            raise RuntimeError("MARSAD_TOKEN_KEY must be at least 16 bytes")
        self._key = key

    def tokenise(self, value: str, indicator_type: IndicatorType) -> str:
        canonical = canonicalise(value, indicator_type)
        # Domain-separate by type so an IP and a domain with the same text
        # cannot collide into a false correlation.
        msg = f"{indicator_type.value}\x1f{canonical}".encode()
        return hmac.new(self._key, msg, hashlib.sha256).hexdigest()[:TOKEN_LEN]


class OprfTokeniser(Tokeniser):
    """
    PRODUCTION TARGET — not yet implemented.

    Intended shape: an oblivious PRF over Ristretto255 (VOPRF, RFC 9497).

        1. connector blinds the canonicalised indicator      -> blinded element
        2. core (or threshold quorum) evaluates with key k   -> evaluated element
        3. connector unblinds and finalises                  -> token

    The connector never learns k; the evaluator never learns the indicator.
    Key material sits in an HSM under threshold custody so no single party can
    evaluate alone, and every evaluation is metered and audited to make bulk
    enumeration visible.

    Implementation notes for whoever picks this up:
      * `pysodium` / `libsodium` expose the Ristretto255 operations needed.
      * Batch blinding matters — one round trip per incident, not per indicator.
      * Key epochs must be recorded in `scheme` so the core never compares
        tokens produced under different keys and reports a false negative.
    """

    scheme = "oprf-ristretto255-v1"

    def __init__(self, *_, **__) -> None:
        raise NotImplementedError(
            "OprfTokeniser is the production target. Implement RFC 9497 VOPRF "
            "with threshold key custody before processing real institutional data."
        )

    def tokenise(self, value: str, indicator_type: IndicatorType) -> str:  # pragma: no cover
        raise NotImplementedError


def build_tokeniser(scheme: str = "hmac") -> Tokeniser:
    """Factory. The only place a concrete tokeniser is chosen."""
    match scheme.lower():
        case "hmac":
            return HmacTokeniser()
        case "oprf":
            return OprfTokeniser()
        case _:
            raise ValueError(f"unknown tokeniser scheme: {scheme!r}")
