"""Unified visual-evidence service: Muse Spark findings + SAM geometry.

Sequential workflow: VisionAgent findings first, then deterministic SAM
prompts (operator targets first, then positively observed objects ranked
by operational tier with confidence second, plus one optional justified
exploratory access check; max 3 executed). Shared by the
``/analyze-and-segment`` route and the disaster-response orchestrator so
both produce identical visual evidence from the same image.

Findings are always preserved when SAM fails, times out, or matches
nothing. Total failure (vision errors with zero findings) raises
``SentinelError`` for the caller to map to HTTP 502. A missing or
zero-match outcome never implies object absence, and SAM geometry never
confirms damage or exposure (linkage stays ``prompt_trigger_only``).
"""

from __future__ import annotations

import hashlib
import time
from typing import Any, Callable, Sequence

from app.agents.vision_agent import VisionAgent
from app.core.config import settings
from app.core.errors import SentinelError
from app.orchestrator.validators import (
    validate_segmentations,
    validate_workflow_status,
)
from app.schemas.segmentation import (
    SegmentBox,
    SegmentDetection,
    SegmentImageInfo,
    SegmentMask,
)
from app.schemas.unified_analysis import (
    PromptSegmentation,
    PromptStatus,
    UnifiedAnalysisResponse,
    WorkflowStatus,
)
from app.services import media_service
from app.services.muse_spark_client import MuseSparkClient
from app.services.prompt_planner import (
    MAX_SAM_PROMPTS,
    PROMPT_KEYWORDS,
    plan_sam_prompts,
)
from app.services.sam31_client import Sam31Client, Sam31Detection

# Minimum remaining workflow-budget seconds to start another SAM call.
# Below this, remaining prompts are reported as skipped (budget_exhausted).
MIN_SAM_CALL_SECONDS = 5.0


def to_segment_detections(
    detections: list[Sam31Detection], width: int, height: int
) -> tuple[list[SegmentDetection], list[str]]:
    """Bounds-filter SAM boxes against Pillow dims; drops OOB with warnings."""
    warnings: list[str] = []
    kept: list[SegmentDetection] = []
    for detection in detections:
        box = detection.box
        if not (0 <= box.x1 < box.x2 <= width and 0 <= box.y1 < box.y2 <= height):
            warnings.append(
                f"sam31_box_out_of_bounds: object {detection.object_id!r} skipped."
            )
            continue
        kept.append(
            SegmentDetection(
                object_id=detection.object_id,
                box=SegmentBox(
                    x1=box.x1,
                    y1=box.y1,
                    x2=box.x2,
                    y2=box.y2,
                ),
                mask=SegmentMask(
                    width=detection.mask.width,
                    height=detection.mask.height,
                    svg_path=detection.mask.svg_path,
                    rle_counts=detection.mask.rle_counts,
                ),
            )
        )
    return kept, warnings


def run_unified_analysis(
    validated: media_service.ValidatedImage,
    width: int,
    height: int,
    *,
    vision_factory: Callable[..., Any] | None = None,
    spark_factory: Callable[..., Any] | None = None,
    sam_factory: Callable[..., Any] | None = None,
    user_targets: Sequence[str] = (),
) -> UnifiedAnalysisResponse:
    """Run vision findings then targeted SAM segmentation (sequential).

    Factories default to the real clients; callers pass their own
    references so tests can substitute fakes per call site.
    ``user_targets`` are canonicalized operator terms; they execute first
    and automatic picks fill the remaining prompt slots.
    """
    vision_factory = vision_factory or VisionAgent
    spark_factory = spark_factory or MuseSparkClient
    sam_factory = sam_factory or Sam31Client
    started = time.monotonic()
    budget = settings.unified_workflow_budget_s
    data_url = media_service.image_to_data_url(validated)
    digest = hashlib.sha256(validated.data).hexdigest()
    evidence_id = f"sha256:{digest}"

    # Stage 1 (mandatory): Muse Spark vision findings.
    remaining = budget - (time.monotonic() - started)
    vision_timeout = min(
        settings.muse_spark_timeout_s, max(remaining, MIN_SAM_CALL_SECONDS)
    )
    vision = vision_factory(client=spark_factory(timeout_s=vision_timeout))
    vision_result = vision.run(
        {"image_data_url": data_url, "evidence_id": evidence_id}
    )
    if vision_result.errors and not vision_result.findings:
        raise SentinelError("vision_failed", "; ".join(vision_result.errors))
    warnings = list(vision_result.errors)

    # Stage 2: deterministic prompt plan (full plan kept for the audit trail).
    full_plan = plan_sam_prompts(
        vision_result.findings,
        user_targets=user_targets,
        max_prompts=len(PROMPT_KEYWORDS) + len(user_targets),
    )
    segmentations: list[PromptSegmentation] = []
    if not full_plan:
        warnings.append(
            "no_segmentable_concepts: findings named no road/river/"
            "building/vehicle/people/debris/bridge to segment."
        )
    for index, decision in enumerate(full_plan):
        if index >= MAX_SAM_PROMPTS:
            segmentations.append(
                PromptSegmentation(
                    prompt=decision.prompt,
                    linked_finding_ids=list(decision.triggered_by),
                    status=PromptStatus.SKIPPED,
                    error=(
                        "prompt_cap_exceeded: at most "
                        f"{MAX_SAM_PROMPTS} SAM prompts per request."
                    ),
                    provenance=decision.provenance,
                )
            )
            continue
        remaining = budget - (time.monotonic() - started)
        if remaining < MIN_SAM_CALL_SECONDS:
            segmentations.append(
                PromptSegmentation(
                    prompt=decision.prompt,
                    linked_finding_ids=list(decision.triggered_by),
                    status=PromptStatus.SKIPPED,
                    error=(
                        "budget_exhausted: insufficient workflow time "
                        "remaining for another SAM request."
                    ),
                    provenance=decision.provenance,
                )
            )
            continue
        sam_timeout = min(settings.sam31_timeout_s, remaining)
        try:
            sam_result = sam_factory(timeout_s=sam_timeout).segment_image(
                data_url, decision.prompt
            )
        except SentinelError as exc:
            segmentations.append(
                PromptSegmentation(
                    prompt=decision.prompt,
                    linked_finding_ids=list(decision.triggered_by),
                    status=PromptStatus.FAILED,
                    error=f"{exc.code}: {exc.message}",
                    provenance=decision.provenance,
                )
            )
            continue
        detections, box_warnings = to_segment_detections(
            sam_result.detections, width, height
        )
        warnings.extend(sam_result.warnings)
        warnings.extend(f"[{decision.prompt}] {w}" for w in box_warnings)
        segmentations.append(
            PromptSegmentation(
                prompt=decision.prompt,
                linked_finding_ids=list(decision.triggered_by),
                status=(
                    PromptStatus.OK
                    if detections
                    else PromptStatus.ZERO_MATCHES
                ),
                detections=detections,
                provenance=decision.provenance,
            )
        )

    attempted = [
        s
        for s in segmentations
        if s.status
        in (PromptStatus.OK, PromptStatus.ZERO_MATCHES, PromptStatus.FAILED)
    ]
    if not attempted:
        workflow_status = WorkflowStatus.VISION_ONLY
    elif all(
        s.status in (PromptStatus.OK, PromptStatus.ZERO_MATCHES)
        for s in attempted
    ) and len(attempted) == len(segmentations):
        workflow_status = WorkflowStatus.COMPLETED
    else:
        workflow_status = WorkflowStatus.PARTIAL

    # Self-consistency pins: construction above must satisfy the same
    # structural rules every consumer enforces. Findings are always
    # preserved — inconsistencies are reported, never silent.
    warnings.extend(
        validate_segmentations(
            segmentations,
            width=width,
            height=height,
            finding_ids={f.finding_id for f in vision_result.findings},
        )
    )
    warnings.extend(validate_workflow_status(segmentations, workflow_status))

    return UnifiedAnalysisResponse(
        incident_id=f"img-{digest[:12]}",
        image=SegmentImageInfo(
            width=width,
            height=height,
            mime_type=validated.mime_type,
            evidence_id=evidence_id,
        ),
        findings=vision_result.findings,
        prompt_plan=full_plan,
        segmentations=segmentations,
        workflow_status=workflow_status,
        warnings=warnings,
        user_targets=[t.strip() for t in user_targets if t.strip()],
    )
