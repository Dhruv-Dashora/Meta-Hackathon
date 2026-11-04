"""Unified analysis schemas: Muse Spark findings + SAM 3.1 geometry.

Linkage semantics:
- Every finding and the image share one ``evidence_id`` (sha256 of the
  uploaded bytes), so findings and segmentations trace to the same image.
- ``linked_finding_ids`` records which findings TRIGGERED a SAM prompt. It is
  a prompt-selection audit trail only: a SAM detection NEVER confirms a
  finding, and segmentation geometry MUST NOT be read as damage, blockage,
  severity, or casualty evidence. The ``association`` literal is a constant
  reminder of that rule.
- ``workflow_status`` summarizes the run:
  - ``completed``: vision succeeded and every planned SAM prompt executed
    cleanly (each ``ok`` or ``zero_matches``).
  - ``partial``: vision succeeded, at least one SAM call executed, but at
    least one prompt ended ``failed`` or ``skipped``.
  - ``vision_only``: vision succeeded but no SAM call executed — either no
    promptable concept was found in the findings, or every planned prompt
    was skipped (over the prompt cap or out of workflow time budget).
"""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import Finding
from app.schemas.segmentation import SegmentDetection, SegmentImageInfo


class PromptStatus(str, Enum):
    OK = "ok"
    ZERO_MATCHES = "zero_matches"
    FAILED = "failed"
    SKIPPED = "skipped"


class WorkflowStatus(str, Enum):
    COMPLETED = "completed"
    PARTIAL = "partial"
    VISION_ONLY = "vision_only"


class PromptProvenance(str, Enum):
    USER_REQUESTED = "user_requested"
    AUTOMATIC = "automatic"
    EXPLORATORY = "exploratory"


class PromptDecision(BaseModel):
    """Audit trail: why a SAM prompt was (or was not) executed."""

    prompt: str
    triggered_by: list[str] = Field(default_factory=list)
    matched_keywords: list[str] = Field(default_factory=list)
    provenance: PromptProvenance = PromptProvenance.AUTOMATIC
    requested_as: str | None = None


class PromptSegmentation(BaseModel):
    """One SAM prompt's outcome. Geometry only — never a finding verdict."""

    prompt: str
    linked_finding_ids: list[str] = Field(default_factory=list)
    association: Literal["prompt_trigger_only"] = "prompt_trigger_only"
    status: PromptStatus
    error: str | None = None
    detections: list[SegmentDetection] = Field(default_factory=list)
    provenance: PromptProvenance = PromptProvenance.AUTOMATIC


class UnifiedAnalysisResponse(BaseModel):
    """Response for POST /api/disaster-response/analyze-and-segment."""

    incident_id: str
    image: SegmentImageInfo
    findings: list[Finding] = Field(default_factory=list)
    prompt_plan: list[PromptDecision] = Field(default_factory=list)
    segmentations: list[PromptSegmentation] = Field(default_factory=list)
    workflow_status: WorkflowStatus
    warnings: list[str] = Field(default_factory=list)
    user_targets: list[str] = Field(default_factory=list)
    analysis_ref: str | None = None
