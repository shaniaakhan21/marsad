"""Common agent surface. Keeps autonomy explicit rather than implied."""
from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any


class Autonomy(str, Enum):
    AUTOMATIC = "AUTOMATIC"                  # runs unattended
    PROPOSE_CONFIRM = "PROPOSE_CONFIRM"      # human confirms before effect
    DRAFT_ONLY = "DRAFT_ONLY"                # never takes the final action
    FAIL_CLOSED = "FAIL_CLOSED"              # halts if its supervisor is absent


class Agent(ABC):
    """Every agent declares its id, autonomy and whether it may cross the boundary."""

    agent_id: str
    autonomy: Autonomy
    may_cross_boundary: bool = False

    @abstractmethod
    async def run(self, payload: dict[str, Any]) -> dict[str, Any]: ...
