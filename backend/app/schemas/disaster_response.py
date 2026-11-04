"""Disaster-response schemas (scaffold)."""

from pydantic import BaseModel, Field

from app.schemas.common import Finding


class DisasterAssessRequest(BaseModel):
    location_id: str = ""
    evidence_ids: list[str] = Field(default_factory=list)


class DisasterAssessResponse(BaseModel):
    incident_id: str
    findings: list[Finding] = Field(default_factory=list)
