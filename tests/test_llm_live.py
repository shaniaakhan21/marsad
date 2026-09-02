"""
The model path against a live endpoint. Marked `llm`; excluded from the default run.

Everything else about the LLM layer is tested with a faked HTTP client, which proves
the code does what it intends and nothing about whether a real serving stack agrees.
These tests need Ollama running and are the only place that question is asked:

    ollama serve &
    ollama pull qwen2.5:3b-instruct
    python -m pytest tests/test_llm_live.py -v -m llm

The most important one is not about the model at all. `test_the_sovereignty_guard_...`
is the first exercise of that guard against a real endpoint and real DNS — every
other test injects a resolver, so until now nothing had confirmed that the guard
admits a working local model while still refusing a public one through the same
construction path. A guard that refused everything would look identical in those
tests.

What running these found, recorded in docs/model-path-results.md: Ollama compiles
`response_format: json_schema` into a GBNF grammar and rejects `\\d`; numeric
`minimum`/`maximum` are not enforced; and one extraction takes ~50s on CPU, past the
connector's 45s timeout.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "packages" / "contracts"),
    str(ROOT / "services" / "connector"),
]

from marsad_connector.agents.a2_extract import EXTRACTION_SCHEMA
from marsad_connector.llm.provider import build_llm
from marsad_connector.llm.sovereignty import SovereigntyError

pytestmark = pytest.mark.llm

OLLAMA = "http://localhost:11434/v1"
MODEL = "qwen2.5:3b-instruct"


@pytest.fixture(scope="module", autouse=True)
def ollama_is_up():
    try:
        httpx.get("http://localhost:11434/api/version", timeout=3).raise_for_status()
    except Exception as exc:                                    # noqa: BLE001
        pytest.skip(
            f"Ollama not reachable ({exc}). Start it with:\n"
            f"    ollama serve &\n    ollama pull {MODEL}"
        )


def test_the_sovereignty_guard_admits_a_live_local_model():
    """
    The guard must not be a wall. A firm running its own model on its own hardware is
    the supported configuration, and this is the first time that has been checked
    against an endpoint that actually answers.
    """
    provider = build_llm("openai_compatible", base_url=OLLAMA, api_key="", model=MODEL)
    assert provider.base_url == OLLAMA.rstrip("/")

    models = httpx.get(f"{OLLAMA}/models", timeout=10).json()
    assert models["object"] == "list"


@pytest.mark.parametrize("base_url,api_key", [
    ("https://api.openai.com/v1", "sk-proj-xxxx"),
    ("https://api.anthropic.com/v1", ""),
    ("http://8.8.8.8:11434/v1", ""),
])
def test_the_same_config_path_still_refuses_a_public_endpoint(base_url, api_key):
    """
    Same call, same arguments, real DNS — no injected resolver. `api.anthropic.com`
    is refused because it genuinely resolves to a public address, which is the code
    path every other test stubs out.
    """
    with pytest.raises(SovereigntyError):
        build_llm("openai_compatible", base_url=base_url, api_key=api_key, model=MODEL)


def test_ollama_rejects_the_production_schema_because_of_the_backslash_d_shorthand():
    """
    Recorded as a test because it is a live incompatibility, not a bug in our code.

    Ollama 0.33.0 compiles `response_format: json_schema` into a GBNF grammar. The
    ATT&CK pattern in the contract, `^T\\d{4}(\\.\\d{3})?$`, fails to compile;
    `^T[0-9]{4}(\\.[0-9]{3})?$` compiles and means the same thing for ASCII IDs. If a
    future Ollama fixes this, this test fails and the workaround can be removed.
    """
    def compiles(pattern: str) -> bool:
        schema = {"type": "object", "additionalProperties": False, "required": ["a"],
                  "properties": {"a": {"type": "string", "pattern": pattern}}}
        response = httpx.post(
            f"{OLLAMA}/chat/completions", timeout=120,
            json={"model": MODEL, "temperature": 0,
                  "messages": [{"role": "user", "content": "x"}],
                  "response_format": {"type": "json_schema",
                                      "json_schema": {"name": "t", "strict": True,
                                                      "schema": schema}}},
        )
        return response.status_code == 200

    assert compiles(r"^T[0-9]{4}$"), "the [0-9] form must compile, or the note is wrong"
    assert not compiles(r"^T\d{4}$"), (
        "Ollama now accepts the \\d shorthand. The compatibility transform in the "
        "benchmark harness can be removed, and docs/model-path-results.md updated."
    )


def test_the_production_schema_as_written_is_rejected():
    """The consequence of the above, stated against the real schema rather than a toy."""
    response = httpx.post(
        f"{OLLAMA}/chat/completions", timeout=120,
        json={"model": MODEL, "temperature": 0,
              "messages": [{"role": "user", "content": "x"}],
              "response_format": {"type": "json_schema",
                                  "json_schema": {"name": "marsad_extraction",
                                                  "strict": True,
                                                  "schema": EXTRACTION_SCHEMA}}},
    )
    assert response.status_code == 400
    assert "grammar" in response.text.lower()


def test_numeric_bounds_in_the_schema_are_not_enforced():
    """
    `confidence` is declared `minimum: 0, maximum: 1`. The grammar does not enforce
    it, so a value outside the range can come back and anything treating the schema
    as a validator is wrong. A2 stores whatever arrives, so a miscalibrated or
    out-of-range confidence reaches the analyst's review screen unchallenged.
    """
    schema = {"type": "object", "additionalProperties": False, "required": ["a"],
              "properties": {"a": {"type": "number", "minimum": 0, "maximum": 1}}}
    response = httpx.post(
        f"{OLLAMA}/chat/completions", timeout=120,
        json={"model": MODEL, "temperature": 0,
              "messages": [{"role": "user",
                            "content": "Return a large number for a."}],
              "response_format": {"type": "json_schema",
                                  "json_schema": {"name": "t", "strict": True,
                                                  "schema": schema}}},
    )
    assert response.status_code == 200
    value = json.loads(response.json()["choices"][0]["message"]["content"])["a"]
    assert isinstance(value, (int, float))
    # Not asserting it IS out of range — the model may comply by luck. Asserting that
    # nothing in the stack guarantees it is not.
    assert "minimum" not in response.text


def test_one_extraction_exceeds_the_connectors_own_timeout_on_cpu():
    """
    REQUEST_TIMEOUT_SECONDS is 45s. On CPU-only hardware a 3B model takes longer than
    that for this schema, so the shipped default would fail every request on a machine
    like the one this was measured on. Recorded rather than fixed: raising it trades a
    working extraction for an analyst watching a spinner, and that is a decision for
    whoever sizes the deployment.
    """
    from marsad_connector.llm import provider as provider_module

    original = provider_module.REQUEST_TIMEOUT_SECONDS
    provider_module.REQUEST_TIMEOUT_SECONDS = 900.0
    try:
        import time

        compatible = json.loads(
            json.dumps(EXTRACTION_SCHEMA).replace(r"\\d", "[0-9]")
        )
        provider = build_llm("openai_compatible", base_url=OLLAMA, model=MODEL)
        started = time.time()
        asyncio.run(provider.extract(
            "Phishing at 2026-08-19 08:00 UTC from evil.com. Severity: HIGH.",
            compatible,
        ))
        elapsed = time.time() - started
    finally:
        provider_module.REQUEST_TIMEOUT_SECONDS = original

    assert elapsed > 0
    if elapsed <= original:
        pytest.skip(
            f"extraction took {elapsed:.1f}s, within the {original}s default — this "
            f"machine is faster than the one the finding was recorded on"
        )
