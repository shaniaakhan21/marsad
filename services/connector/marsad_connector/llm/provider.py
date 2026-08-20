"""
LLM abstraction. Edge agents must run against a sovereign-hosted model, so the
provider is pluggable and the default is a deterministic stub that needs no
network — which also makes tests fast and CI hermetic.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any


class LLMProvider(ABC):
    name: str

    @abstractmethod
    async def extract(self, text: str, schema_hint: dict[str, Any]) -> dict[str, Any]:
        """Return structured fields. Implementations MUST validate before returning."""


class StubProvider(LLMProvider):
    """
    Deterministic, offline. Good enough to exercise the pipeline and to prove
    that nothing downstream depends on model availability — see the Offline
    operating mode in the design.
    """

    name = "stub"

    async def extract(self, text: str, schema_hint: dict[str, Any]) -> dict[str, Any]:
        return {"summary": text[:180], "fields": {}, "confidence": 0.0, "_stub": True}


class OpenAICompatibleProvider(LLMProvider):
    """
    For any OpenAI-compatible endpoint, including a locally served open-weight
    model (vLLM, Ollama). Deliberately not implemented here so that no real
    incident text can be sent anywhere by accident during the hackathon.
    """

    name = "openai_compatible"

    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        self.base_url, self.api_key, self.model = base_url, api_key, model

    async def extract(self, text: str, schema_hint: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError(
            "Wire this to a sovereign-hosted endpoint. Constrain output to the "
            "schema, set temperature 0, and validate every field before use."
        )


def build_llm(kind: str = "stub", **kw) -> LLMProvider:
    return {"stub": StubProvider}.get(kind, StubProvider)() if kind == "stub" \
        else OpenAICompatibleProvider(**kw)
