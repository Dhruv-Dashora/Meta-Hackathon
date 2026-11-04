"""Failure handling: retries, fallbacks, audit trail (scaffold)."""

from dataclasses import dataclass, field


@dataclass
class FailureRecord:
    step: str
    error: str
    attempts: int = 1
    notes: list[str] = field(default_factory=list)
