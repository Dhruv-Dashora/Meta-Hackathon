"""Base agent contract (scaffold)."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentResult:
    agent: str
    findings: list[Any] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)


class BaseAgent:
    name = "base"

    def run(self, payload: dict) -> AgentResult:
        raise NotImplementedError("Scaffold placeholder — not implemented yet.")
