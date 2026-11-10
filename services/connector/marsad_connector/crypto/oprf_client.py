"""
Fetching tokens from the key custodians, before A3 runs.

Why this is not inside the tokeniser that A3 calls
--------------------------------------------------
A3 holds no network capability, and that is a property worth more than a tidy call
graph: a reviewer reads one short file and knows nothing in it can talk to anything. An
OPRF needs a round trip, so the round trip happens here, first, for the whole incident.
A3 is then handed a finished lookup table (`OprfTokeniser`) and stays exactly as
network-free as it was.

Batching gives one round trip per incident rather than one per indicator, and one proof
per custodian.

What goes on the wire
---------------------
Only the blinded elements defined by `OprfEvaluationRequest`, freshly randomised every
time. This module reads indicator types and values and nothing else about an incident.

Failure
-------
Every partial result is checked against the public share pinned in this connector's
configuration. A custodian that fails its proof is ignored, and a quorum of honest
custodians still works. Short of a quorum this raises `OprfUnavailable`: there is no
fallback to a weaker token, because a silent downgrade is the outcome the whole upgrade
exists to prevent.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

import httpx
from marsad_contracts.boundary import (
    IndicatorType,
    OprfEvaluationRequest,
    OprfEvaluationResponse,
)
from marsad_oprf import voprf
from marsad_oprf.threshold import PublicKeySet, assert_consistent, combine
from pydantic import ValidationError

from marsad_connector.crypto.tokeniser import (
    OPRF_OUTPUT_HEX,
    OprfTokeniser,
    OprfUnavailable,
    TokenTable,
    canonicalise,
)

log = logging.getLogger("marsad.connector.oprf")

#: Matches A3's ceiling and the contract's. An incident cannot become a larger query.
MAX_ELEMENTS = 512


@dataclass(frozen=True)
class Custodian:
    index: int
    url: str
    public_share: bytes


@dataclass(frozen=True)
class OprfConfig:
    epoch: int
    threshold: int
    custodians: tuple[Custodian, ...]
    custody_label: str = "software"

    @classmethod
    def parse(cls, epoch: int, threshold: int, group_key: str, raw_custodians: str,
              custody_label: str = "software") -> OprfConfig:
        """Build from settings, and refuse a key set that does not hang together."""
        entries = json.loads(raw_custodians)
        keys = PublicKeySet(
            epoch=epoch, threshold=threshold, group_key=group_key,
            public_shares={int(e["index"]): e["public_share"] for e in entries},
        )
        assert_consistent(keys)
        return cls(
            epoch=epoch, threshold=threshold, custody_label=custody_label,
            custodians=tuple(
                Custodian(int(e["index"]), e["url"].rstrip("/"), bytes.fromhex(e["public_share"]))
                for e in entries
            ),
        )

    @property
    def scheme(self) -> str:
        return (f"oprf-ristretto255-sha512-e{self.epoch}-"
                f"{self.threshold}of{len(self.custodians)}-{self.custody_label}")


ClientFactory = Callable[[Custodian], httpx.AsyncClient]


def indicator_input(indicator_type: IndicatorType, canonical: str) -> bytes:
    """Domain-separated by type, so an IP and a domain with one spelling cannot collide."""
    return f"{indicator_type.value}\x1f{canonical}".encode()


def _distinct_indicators(
    indicators: Iterable[dict[str, Any]],
) -> list[tuple[IndicatorType, str]]:
    """
    The (type, canonical value) pairs A3 will ask for, in A3's order.

    Same drops as A3, for the same reasons: an unknown type or an empty value is not
    tokenised. Nothing is sent for what A3 would have discarded.
    """
    distinct: dict[tuple[IndicatorType, str], None] = {}
    for raw in indicators or []:
        try:
            itype = IndicatorType(raw["type"])
            distinct[(itype, canonicalise(raw["value"], itype))] = None
        except (KeyError, ValueError):
            continue
        if len(distinct) >= MAX_ELEMENTS:
            break
    return list(distinct)


async def _ask(
    custodian: Custodian, config: OprfConfig, body: dict, blinded: list[bytes],
    client_factory: ClientFactory, client_label: str,
) -> tuple[int, list[bytes]] | None:
    """One custodian's verified partial results, or None. Failures are logged, not raised."""
    try:
        async with client_factory(custodian) as client:
            response = await client.post(
                f"{custodian.url}/v1/oprf/evaluate", json=body,
                headers={"X-Marsad-Client": client_label},
            )
        response.raise_for_status()
        answer = OprfEvaluationResponse.model_validate(response.json())
        if answer.index != custodian.index or answer.epoch != config.epoch:
            raise voprf.ProofError("answered for the wrong custodian or epoch")
        evaluated = [bytes.fromhex(e) for e in answer.evaluated_elements]
        voprf.verify_proof(
            custodian.public_share, blinded, evaluated,
            voprf.Proof.from_bytes(bytes.fromhex(answer.proof)),
        )
    except voprf.ProofError as exc:
        # Reported loudly and differently from an outage: this is evidence of a
        # misbehaving custodian, which is a governance event and not a network one.
        log.error("oprf.proof_failed custodian=%d reason=%s", custodian.index, exc)
        return None
    except (httpx.HTTPError, ValidationError, ValueError) as exc:
        log.warning("oprf.custodian_unavailable custodian=%d err=%s",
                    custodian.index, type(exc).__name__)
        return None
    return custodian.index, evaluated


async def resolve_tokens(
    indicators: Iterable[dict[str, Any]], config: OprfConfig,
    client_factory: ClientFactory, *, client_label: str = "unauthenticated",
) -> OprfTokeniser:
    """Run the protocol for one incident and return a tokeniser A3 can use offline."""
    pairs = _distinct_indicators(indicators)
    table: TokenTable = {}
    if not pairs:
        return OprfTokeniser(table, config.scheme)

    inputs = [indicator_input(t, v) for t, v in pairs]
    blinds_and_elements = [voprf.blind(i) for i in inputs]
    blinded = [element for _, element in blinds_and_elements]
    body = OprfEvaluationRequest(
        epoch=config.epoch, blinded_elements=[b.hex() for b in blinded],
    ).model_dump(mode="json")

    answers = await asyncio.gather(*(
        _ask(c, config, body, blinded, client_factory, client_label)
        for c in config.custodians
    ))
    valid = {index: evaluated for index, evaluated in filter(None, answers)}
    if len(valid) < config.threshold:
        raise OprfUnavailable(
            f"{len(valid)} of the {config.threshold} key custodians required answered "
            f"with a valid proof"
        )

    prefix = f"{config.epoch:08x}"
    for position, (pair, data) in enumerate(zip(pairs, inputs, strict=True)):
        combined = combine(
            {index: evaluated[position] for index, evaluated in valid.items()}, config.threshold,
        )
        output = voprf.finalize(data, blinds_and_elements[position][0], combined)
        table[pair] = prefix + hashlib.sha256(output).hexdigest()[:OPRF_OUTPUT_HEX]

    log.info("oprf.resolved indicators=%d custodians_valid=%d", len(pairs), len(valid))
    return OprfTokeniser(table, config.scheme)


__all__ = ["Custodian", "OprfConfig", "OprfUnavailable", "indicator_input", "resolve_tokens"]
