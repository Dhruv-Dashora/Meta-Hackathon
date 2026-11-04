"""Agent tests: monitoring still a scaffold; impact/reporting implemented."""

import pytest

from app.agents.monitoring_agent import MonitoringAgent


def test_monitoring_placeholder_raises():
    with pytest.raises(NotImplementedError):
        MonitoringAgent().run({})


def test_monitoring_name():
    assert MonitoringAgent().name == "monitoring"
