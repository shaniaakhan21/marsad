"""
The canary test — MARSAD's central claim, made falsifiable.

The claim is one sentence: narrative, plaintext indicators and PII never leave the
institution. Every other test in this repository checks a mechanism that supports that
claim. This one checks the claim itself, the only way a claim like it can be checked —
by planting a string that could only have come from inside the perimeter, running the
real pipeline end to end, and then looking everywhere the core can hold or emit
anything.

What "everywhere" means here
----------------------------
Core state is in-memory today, so the equivalent of "every table, every column" is an
exhaustive recursive walk of the core's entire object graph: dicts, lists, sets,
dataclasses, Pydantic models, and the attributes of every object reachable from
`STATE`. That is strictly more thorough than a column sweep, because it also reaches
indexes, caches and engine internals that no schema would list.
`test_core_still_has_no_database_this_sweep_would_miss` fails the build the day a real
database is introduced, so the sweep cannot silently stop covering the store.

Alongside that: every response the core API can produce, including its OpenAPI
document, and every log line the core writes.

Why the positive controls matter more than the assertions
---------------------------------------------------------
A canary test that passes because the canary was never planted, or because the
pipeline never ran, is worse than no test — it is a green light with nothing behind
it. So every canary is asserted PRESENT on the edge before it is asserted ABSENT at
the core, and the core is asserted to have actually ingested the submission. If the
plumbing breaks, these fail first and loudly.
"""

from __future__ import annotations

import dataclasses
import logging
import secrets
import sys
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "packages" / "contracts"),
    str(ROOT / "services" / "connector"),
    str(ROOT / "services" / "core"),
]

from marsad_connector.agents.a2_extract import ExtractionAgent
from marsad_connector.agents.a3_redact import RedactionAgent
from marsad_connector.crypto.tokeniser import HmacTokeniser
from marsad_connector.lang.arabic import normalise
from marsad_contracts.boundary import Sector, SizeBand

KEY = b"canary-key-at-least-sixteen-bytes-long"

#: Loggers that belong to the core. Connector-side loggers are inside the perimeter
#: and may legitimately mention plaintext; core-side ones may not.
CORE_LOGGERS = ("marsad.core", "marsad.correlation", "marsad.similarity")

#: Depth cap for the object walk. Nothing in core state is anywhere near this deep;
#: it exists so a cycle the id-set misses cannot hang the suite.
MAX_DEPTH = 40


# ---------------------------------------------------------------- the canaries


def _canary(label: str) -> str:
    """
    A string that could only have come from inside the institution.

    Random per run: a fixed value could pass because a previous run's copy was
    cleaned up, and could fail because one was not. Long enough that a collision
    with real content is not a thing that happens.
    """
    return f"{label}{secrets.token_hex(16)}"


@dataclasses.dataclass(frozen=True)
class Canaries:
    """Every planted string, and where each one is planted."""

    prose: str
    span: str
    indicator: str
    notes: str
    arabic_raw: str
    arabic_normalised: str

    def all_forms(self) -> tuple[str, ...]:
        return (self.prose, self.span, self.indicator, self.notes,
                self.arabic_raw, self.arabic_normalised)


@pytest.fixture
def canaries() -> Canaries:
    arabic_raw = f"قناة{secrets.token_hex(12)}"
    return Canaries(
        prose=_canary("CanaryProse"),
        # Planted as a vendor name so extraction captures it into
        # third_party_dependencies AND quotes it verbatim as span evidence — the
        # provenance surface free-text intake introduced.
        span=_canary("CanaryVendor"),
        indicator=_canary("canary-indicator"),
        notes=_canary("CanaryNotes"),
        arabic_raw=arabic_raw,
        # Normalisation rewrites Arabic, so the canary exists in two forms and both
        # must be absent. A single-language test cannot see this case at all.
        arabic_normalised=normalise(arabic_raw),
    )


# ---------------------------------------------------------------- the sweep


def _render(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", "ignore")
    if isinstance(value, (int, float, bool, datetime)) or value is None:
        return str(value)
    return None


def _walk(obj: Any, path: str = "STATE", seen: set[int] | None = None,
          depth: int = 0) -> Iterator[tuple[str, str]]:
    """
    Yield (path, string) for every value reachable from `obj`.

    Deliberately exhaustive rather than schema-driven: the point is to find a leak
    somewhere nobody thought to look, which by definition is not in the schema
    someone wrote.
    """
    if depth > MAX_DEPTH:
        return
    seen = seen if seen is not None else set()
    if id(obj) in seen:
        return
    seen.add(id(obj))

    rendered = _render(obj)
    if rendered is not None:
        yield path, rendered
        return

    if isinstance(obj, BaseModel):
        yield from _walk(obj.model_dump(mode="json"), f"{path}.model_dump()", seen, depth + 1)
        return
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        for f in dataclasses.fields(obj):
            yield from _walk(getattr(obj, f.name, None), f"{path}.{f.name}", seen, depth + 1)
        return
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield from _walk(key, f"{path}.<key>", seen, depth + 1)
            yield from _walk(value, f"{path}[{key!r}]", seen, depth + 1)
        return
    if isinstance(obj, (list, tuple, set, frozenset)):
        for index, value in enumerate(obj):
            yield from _walk(value, f"{path}[{index}]", seen, depth + 1)
        return
    if hasattr(obj, "__dict__"):
        for name, value in vars(obj).items():
            yield from _walk(value, f"{path}.{name}", seen, depth + 1)
    for name in getattr(obj, "__slots__", ()):
        yield from _walk(getattr(obj, name, None), f"{path}.{name}", seen, depth + 1)


def _defect(canary: str, where: str, detail: str) -> str:
    return (
        f"\n\nCANARY ESCAPED THE BOUNDARY.\n\n"
        f"  canary : {canary}\n"
        f"  found  : {where}\n"
        f"  context: {detail[:400]}\n\n"
        f"This is a DEFECT, not a data problem. A string planted inside the "
        f"institution reached the core, which means narrative, an analyst's notes or a "
        f"plaintext indicator can reach it too. Do not adjust this test to pass. Find "
        f"the path the string took and close it: the boundary contract in "
        f"packages/contracts/marsad_contracts/boundary.py is the only thing that may "
        f"cross, and a3_redact.py is the only component that may build it.\n"
    )


def _assert_absent(canaries: Canaries, pairs: Iterator[tuple[str, str]], surface: str) -> None:
    for path, text in pairs:
        lowered = text.lower()
        for canary in canaries.all_forms():
            if canary.lower() in lowered:
                pytest.fail(_defect(canary, f"{surface} at {path}", text))


# ---------------------------------------------------------------- the pipeline


@pytest.fixture
def core_client(monkeypatch) -> Iterator[TestClient]:
    """
    A real core process in-process, with the network unreachable.

    The open-data fetchers are routed through a closed port so a portal outage can
    never make this test flaky, exactly as the e2e suite does it.
    """
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        monkeypatch.setenv(var, "http://127.0.0.1:9")

    from marsad_core.main import app

    with TestClient(app) as client:
        yield client


def _run_full_pipeline(narrative: str, notes: str | None, client: TestClient,
                       institution_ref: str) -> dict:
    """
    A2 extraction -> human confirmation -> A3 redaction -> submission -> core.

    The real path, with no step stubbed. If any of it stops working this test fails
    before it gets anywhere near an assertion about leakage.
    """
    import asyncio

    draft = asyncio.run(ExtractionAgent().propose(narrative, analyst_notes=notes))
    confirmed = draft.confirm(analyst="canary.analyst", edits={"severity": "HIGH"})
    submission = RedactionAgent(HmacTokeniser(KEY)).build_submission(
        confirmed, institution_ref=institution_ref,
        sector=Sector.BANK, size_band=SizeBand.LARGE,
    )
    response = client.post("/v1/submissions", json=submission.model_dump(mode="json"))
    response.raise_for_status()
    return {"draft": draft, "confirmed": confirmed,
            "submission": submission, "response": response.json()}


@pytest.fixture
def english_narrative(canaries: Canaries) -> str:
    return (
        f"Finance staff received a credential-harvesting email impersonating the SSO "
        f"portal at 2026-08-19 08:00 UTC. The {canaries.prose} workflow was affected. "
        f"Credentials were submitted to {canaries.indicator}.com. Our provider "
        f"{canaries.span} confirmed the outage. Severity: HIGH."
    )


@pytest.fixture
def arabic_narrative(canaries: Canaries) -> str:
    return (
        f"رصد فريق الأمن رسالة تصيد استهدفت منصة التداول في 2026-08-19 08:00 UTC. "
        f"تأثر النظام {canaries.arabic_raw} بشكل مباشر. "
        f"تم إرسال البيانات إلى {canaries.indicator}-ar.com. الأثر: عالي."
    )


# ================================================================= the tests


def test_the_canaries_are_actually_planted_and_distinct(canaries, english_narrative,
                                                        arabic_narrative):
    """
    Vacuity guard, first. Everything below is worthless if the canaries are not in
    the text, or if the Arabic canary happens not to change under normalisation —
    that would silently reduce the Arabic case to the English one.
    """
    for canary in (canaries.prose, canaries.span, canaries.indicator):
        assert canary in english_narrative
    assert canaries.arabic_raw in arabic_narrative

    assert canaries.arabic_raw != canaries.arabic_normalised, (
        "the Arabic canary must be rewritten by normalisation, or this test is not "
        "exercising the two-forms case it exists for"
    )
    assert len(set(canaries.all_forms())) == len(canaries.all_forms())


def test_a_canary_planted_in_a_narrative_never_reaches_the_core(
    canaries, english_narrative, core_client, caplog,
):
    """
    THE test. Plant, run the whole pipeline, then look everywhere the core can hold
    or say anything.
    """
    caplog.set_level(logging.DEBUG)
    result = _run_full_pipeline(english_narrative, f"Analyst note: {canaries.notes}.",
                                core_client, "psd_canary01")

    # -- positive controls: the canaries were in the pipeline, and it ran ----
    assert canaries.prose in result["confirmed"].narrative
    assert canaries.notes in result["confirmed"].analyst_notes
    assert result["response"]["accepted"] is True
    assert core_client.get("/health").json()["submissions"] == 1
    assert result["submission"].tokens, "nothing was tokenised, so nothing was proven"

    # -- every value reachable in core state --------------------------------
    from marsad_core.main import STATE
    _assert_absent(canaries, _walk(STATE), "core state")

    # -- every response the core API can produce ----------------------------
    _assert_absent(canaries, _walk(result["response"], "POST /v1/submissions"),
                   "core API response")
    for route in sorted({r.path for r in core_client.app.routes
                         if "GET" in getattr(r, "methods", set()) and "{" not in r.path}):
        body = core_client.get(route)
        _assert_absent(canaries, iter([(route, body.text)]), "core API response")
    _assert_absent(canaries, iter([("/openapi.json", core_client.get("/openapi.json").text)]),
                   "core OpenAPI document")

    # -- every line the core logged -----------------------------------------
    core_lines = [(f"{r.name}:{r.lineno}", r.getMessage()) for r in caplog.records
                  if r.name.startswith(CORE_LOGGERS)]
    assert core_lines, "the core logged nothing, so the log sweep proved nothing"
    _assert_absent(canaries, iter(core_lines), "core log output")


def test_extraction_provenance_never_crosses_the_boundary(
    canaries, english_narrative, core_client,
):
    """
    The leak surface free-text intake introduced.

    Spans quote the narrative literally, evidence strings are verbatim slices of it,
    and per-field sources sit on the confirmed incident. None of it is in the boundary
    contract, so none of it may cross — and A3 reading from an allow-list is what
    makes that true rather than hoped for.
    """
    result = _run_full_pipeline(english_narrative, None, core_client, "psd_canary02")
    draft, confirmed = result["draft"], result["confirmed"]

    # -- positive control: the canary really did become provenance -----------
    vendor_field = draft.fields["third_party_dependencies"]
    assert canaries.span in (vendor_field.value or []), (
        "the vendor canary was not extracted, so this test is not exercising the "
        "provenance surface it was written for"
    )
    assert vendor_field.evidence and canaries.span in vendor_field.evidence
    assert vendor_field.span is not None
    assert canaries.span in english_narrative[vendor_field.span[0]:vendor_field.span[1]]
    assert canaries.span in confirmed.third_party_dependencies
    assert confirmed.narrative_normalised, "the normalised copy must exist to be tested"

    # -- and none of it crossed ---------------------------------------------
    from marsad_core.main import STATE
    _assert_absent(canaries, _walk(STATE), "core state")

    payload = result["submission"].model_dump_json()
    for provenance in ("evidence", "span", "confidence", "third_party", "affected_services",
                       "narrative_normalised", "draft_id", "confirmed_by", "canary.analyst"):
        assert provenance not in payload, (
            f"{provenance!r} appears in the outbound payload — extraction provenance "
            f"is crossing the boundary"
        )


def test_an_arabic_canary_never_reaches_the_core_in_either_form(
    canaries, arabic_narrative, core_client, caplog,
):
    """
    Normalisation rewrites Arabic, so a planted canary exists in two forms: what the
    analyst typed, and what the matcher saw. Both are inside the institution and
    neither may cross. A test that checked only the typed form would miss a leak of
    the normalised copy entirely — and the connector stores that copy deliberately.
    """
    caplog.set_level(logging.DEBUG)
    result = _run_full_pipeline(arabic_narrative, None, core_client, "psd_canary03")

    # -- positive controls: both forms are live inside the perimeter ---------
    assert canaries.arabic_raw in result["confirmed"].narrative
    assert canaries.arabic_normalised in result["confirmed"].narrative_normalised
    assert result["response"]["accepted"] is True

    from marsad_core.main import STATE
    _assert_absent(canaries, _walk(STATE), "core state")
    _assert_absent(canaries, _walk(result["response"], "POST /v1/submissions"),
                   "core API response")
    for route in ("/health", "/v1/correlations"):
        _assert_absent(canaries, iter([(route, core_client.get(route).text)]),
                       "core API response")
    _assert_absent(canaries, iter([(f"{r.name}", r.getMessage()) for r in caplog.records
                                   if r.name.startswith(CORE_LOGGERS)]), "core log output")


def test_a_plaintext_indicator_is_replaced_by_a_token_that_still_correlates(
    canaries, english_narrative, core_client,
):
    """
    The canary planted as an indicator proves both halves at once: the plaintext did
    not cross, and something derived from it did — otherwise "nothing leaked" would
    be satisfiable by sending nothing at all.
    """
    result = _run_full_pipeline(english_narrative, None, core_client, "psd_canary04")
    payload = result["submission"].model_dump_json()

    assert canaries.indicator not in payload
    tokens = [kt.token for kt in result["submission"].tokens]
    assert tokens, "no tokens crossed, so correlation could never fire"
    for token in tokens:
        assert len(token) >= 32 and all(c in "0123456789abcdef" for c in token)

    # the same indicator, at a second institution, tokenises identically — which is
    # the entire point of sending the token rather than nothing.
    other = _run_full_pipeline(english_narrative, None, core_client, "psd_canary05")
    assert set(tokens) & {kt.token for kt in other["submission"].tokens}
    assert other["response"]["correlations"], "the two firms did not correlate"


def test_core_still_has_no_database_this_sweep_would_miss():
    """
    The sweep above walks core's in-memory state exhaustively, which is the whole
    store today. The roadmap puts Postgres next, and a database added without
    extending this sweep would leave the canary test quietly checking a store that no
    longer holds anything. So: fail the day one appears.
    """
    core_sources = list((ROOT / "services" / "core" / "marsad_core").rglob("*.py"))
    assert core_sources
    users = [p.relative_to(ROOT) for p in core_sources
             if "sqlalchemy" in p.read_text(encoding="utf-8").lower()]
    assert not users, (
        f"core now uses a database ({users}). Extend the canary sweep to iterate every "
        f"table and every column of it before removing this assertion — otherwise the "
        f"central privacy claim is no longer being checked where the data actually is."
    )


def test_the_sweep_can_actually_find_a_leak(canaries, core_client):
    """
    The test that keeps every assertion above honest.

    A sweep that cannot detect a leak is a green light with nothing behind it, and
    nothing else in this file would notice. So: plant a canary directly into core
    state the way a real defect would — a field someone added to a stored object —
    and require the sweep to find it, at the right path, with the defect message.
    """
    from marsad_core.main import STATE

    core_client.get("/health")           # force lifespan, so STATE is populated
    engine = STATE["engine"]

    # A leak as it would actually look: narrative smuggled onto a stored object.
    engine._leaked_for_test = {"note": f"analyst wrote: {canaries.prose}"}
    try:
        found = [(path, text) for path, text in _walk(STATE)
                 if canaries.prose.lower() in text.lower()]
        assert found, (
            "the sweep did not find a canary planted directly in core state — every "
            "other assertion in this file is therefore meaningless"
        )
        assert any("_leaked_for_test" in path for path, _ in found)

        with pytest.raises(pytest.fail.Exception, match="CANARY ESCAPED THE BOUNDARY"):
            _assert_absent(canaries, _walk(STATE), "core state")
    finally:
        del engine._leaked_for_test

    # and the sweep is clean again once the leak is removed
    _assert_absent(canaries, _walk(STATE), "core state")


def test_the_sweep_reaches_nested_and_indexed_structures(canaries):
    """
    The paths a leak would actually take are not top-level attributes. Prove the walk
    reaches inside dicts, lists, sets, dataclasses and Pydantic models — a sweep that
    stopped at depth one would pass while a token index quietly held plaintext.
    """
    from marsad_contracts.boundary import CoarseMetadata

    @dataclasses.dataclass
    class Nested:
        buried: dict

    haystack = {
        "list": [{"deep": [{"deeper": canaries.prose}]}],
        "set": {canaries.notes},
        "dataclass": Nested(buried={"k": [canaries.span]}),
        "pydantic": CoarseMetadata(
            sector="BANK", size_band="LARGE", severity_band="HIGH",
            ts_bucket=datetime(2026, 8, 19, 8, 0, tzinfo=timezone.utc),
        ),
        "arabic": canaries.arabic_normalised,
    }
    reachable = " ".join(text for _, text in _walk(haystack))
    for canary in (canaries.prose, canaries.notes, canaries.span, canaries.arabic_normalised):
        assert canary in reachable, f"the walk failed to reach {canary[:16]}…"
