"""Monitoring Agent (scaffold): historical comparison + anomaly flags."""

from app.agents.base import AgentResult, BaseAgent


class MonitoringAgent(BaseAgent):
    name = "monitoring"

    def run(self, payload: dict) -> AgentResult:
        raise NotImplementedError("Scaffold placeholder — not implemented yet.")
