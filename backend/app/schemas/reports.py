"""Report schemas (scaffold)."""

from pydantic import BaseModel, Field


class ReportSection(BaseModel):
    title: str
    body: str = ""


class IncidentReport(BaseModel):
    incident_id: str
    sections: list[ReportSection] = Field(default_factory=list)
    verification_priorities: list[str] = Field(default_factory=list)
