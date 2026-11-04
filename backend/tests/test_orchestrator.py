"""Orchestrator unit tests (execution paths live in test_incident.py)."""

import pytest

from app.agents.base import AgentResult
from app.core.errors import SentinelError
from app.orchestrator.orchestrator import Orchestrator


def test_unknown_workflow_rejected():
    with pytest.raises(SentinelError) as exc_info:
        Orchestrator().run_workflow("nope", {})
    assert exc_info.value.code == "unknown_workflow"


def test_collect_lists_agents():
    result = Orchestrator().collect(
        [AgentResult(agent="vision"), AgentResult(agent="impact")]
    )
    assert result == {"results": ["vision", "impact"]}
