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
bulk enumeration becomes detectable and unilaterally impossible. That is
`OprfTokeniser` here, `crypto/oprf_client.py` for the round trip, and
`services/evaluator` for the custodians.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import unicodedata
from abc import ABC, abstractmethod

from marsad_contracts.boundary import IndicatorType

from marsad_connector.lang.arabic import normalise as normalise_arabic

TOKEN_LEN = 32  # hex chars retained; 128 bits is ample for equality matching

#: Hex chars of PRF output in an OPRF token, which is prefixed by 8 hex chars of epoch.
#: The prefix is why tokens from different key epochs can never compare equal, with no
#: new field on the boundary contract. The 40-char length also keeps them apart from
#: the 32-char HMAC tokens during a migration.
OPRF_OUTPUT_HEX = 32

#: (indicator type, canonical value) -> token, for one incident.
TokenTable = dict[tuple[IndicatorType, str], str]


class OprfUnavailable(RuntimeError):
    """A quorum of custodians could not be reached or could not prove their work."""


class TokenNotEvaluated(RuntimeError):
    """An indicator reached A3 that the custodians were never asked about."""


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


#: Separates provider tokens from indicator tokens. Without it, a provider's domain and
#: the same domain seen in an attack would tokenise alike, and the core could link a
#: firm's supplier list to its incidents.
PROVIDER_DOMAIN_SEPARATOR = b"PROVIDER\x1f"

_PROVIDER_DOMAIN = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)+$")


def canonical_provider(domain: str) -> str:
    """
    A provider's identity is its internet domain, in canonical form.

    A domain rather than a name, because two firms will write a name differently and
    their tokens would never meet, with no error to notice.
    """
    canonical = canonicalise(domain, IndicatorType.DOMAIN)
    if not _PROVIDER_DOMAIN.match(canonical):
        raise ValueError("a provider is identified by its internet domain")
    return canonical


def provider_input(canonical: str) -> bytes:
    return PROVIDER_DOMAIN_SEPARATOR + canonical.encode()


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

    def tokenise_provider(self, canonical: str) -> str:
        return hmac.new(self._key, provider_input(canonical), hashlib.sha256).hexdigest()[:TOKEN_LEN]


class OprfTokeniser(Tokeniser):
    """
    Tokens from the threshold OPRF, already fetched for this incident.

    A lookup table and nothing more. The network round trip to the key custodians
    happens beforehand in `oprf_client.resolve_tokens`, so the redaction agent that
    calls this still holds no network capability.

    A value missing from the table raises `TokenNotEvaluated`, deliberately not a
    ValueError: A3 drops an untokenisable indicator on ValueError and carries on, which
    is right for an empty value and wrong for a value the protocol skipped. That would
    be a submission quietly missing an indicator. Here the build fails instead.
    """

    def __init__(self, table: TokenTable, scheme: str) -> None:
        self._table = table
        self.scheme = scheme

    def tokenise(self, value: str, indicator_type: IndicatorType) -> str:
        canonical = canonicalise(value, indicator_type)
        try:
            return self._table[(indicator_type, canonical)]
        except KeyError:
            raise TokenNotEvaluated(
                "an indicator reached A3 without having been evaluated by the custodians"
            ) from None


def build_tokeniser(scheme: str = "hmac") -> Tokeniser:
    """
    Factory for tokenisers that need no per-incident setup.

    The OPRF is built per incident by `oprf_client.resolve_tokens`, so asking for it
    here is a programming error and fails rather than falling back to something weaker.
    """
    match scheme.lower():
        case "hmac":
            return HmacTokeniser()
        case "oprf":
            raise ValueError("OPRF tokens are per incident; use oprf_client.resolve_tokens")
        case _:
            raise ValueError(f"unknown tokeniser scheme: {scheme!r}")
