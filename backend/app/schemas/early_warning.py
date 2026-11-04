"""Early-warning schemas (scaffold)."""

from pydantic import BaseModel, Field

from app.schemas.common import Finding


class EarlyWarningRequest(BaseModel):
    location_id: str = ""
    historical_evidence_ids: list[str] = Field(default_factory=list)
    recent_evidence_ids: list[str] = Field(default_factory=list)


class EarlyWarningResponse(BaseModel):
    incident_id: str
    findings: list[Finding] = Field(default_factory=list)
