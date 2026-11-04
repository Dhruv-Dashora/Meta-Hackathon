"""Shared evidence/confidence/review contracts.

Confidence semantics (see docs/evidence-model.md):
- `Confidence.value` is an UNCALIBRATED model signal on `scale` ("0-1").
- It is NOT a probability. Do not present it as "X% likely".
- Use only for triage ordering + verification priority until calibrated.
"""

from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


class ReviewStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    NEEDS_MORE_EVIDENCE = "needs_more_evidence"


class Confidence(BaseModel):
    """Uncalibrated model signal — NOT a probability."""

    value: float = Field(ge=0.0, le=1.0)
    scale: Literal["0-1"] = "0-1"
    calibrated: Literal[False] = False


class EvidenceRef(BaseModel):
    evidence_id: str
    modality: Literal["image", "video_frame", "geojson", "hydromet", "report"]
    uri_or_hash: str
    captured_at: Optional[datetime] = None


class Finding(BaseModel):
    finding_id: str
    label: str
    description: str = ""
    confidence: Confidence
    uncertainty_notes: str = ""
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    observed_at: Optional[datetime] = None
    analyzed_at: Optional[datetime] = None
    review_status: ReviewStatus = ReviewStatus.PENDING
