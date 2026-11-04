"""Orchestrator: sequential vision -> impact -> reporting with audit trail.

Each step is timed and recorded in the dossier's agent trail. Failure
policy:
- Vision total failure: no dossier possible; the error propagates and the
  route maps it to HTTP 502 (same as the unified endpoint).
- Impact failure: degraded dossier — observed evidence plus fallback
  review actions, ``incident_status`` partial, failure in the trail.
  Missing concerns are never synthesized.
- Reporting failure: no dossier is claimed; an explicit safe error
  propagates (incident id plus finding/prompt counts only).
"""

from __future__ import annotations

import time

from app.agents.base import AgentResult
from app.agents.impact_agent import ImpactAgent
from app.agents.reporting_agent import ReportingAgent
from app.core.errors import SentinelError
from app.orchestrator.failures import FailureRecord
from app.orchestrator.validators import (
    validate_findings,
    validate_segmentations,
    validate_workflow_status,
)
from app.schemas.incident import (
    AgentStepStatus,
    AgentTrailEntry,
    GeoContext,
    IncidentDossier,
)
from app.schemas.unified_analysis import UnifiedAnalysisResponse
from app.services.unified_service import run_unified_analysis

WORKFLOW_DISASTER_RESPONSE = "disaster_response"


class Orchestrator:
    def run_workflow(self, mode: str, payload: dict) -> IncidentDossier:
        if mode != WORKFLOW_DISASTER_RESPONSE:
            raise SentinelError(
                "unknown_workflow", f"Unknown workflow {mode!r}."
            )
        validated = payload["validated"]
        width: int = payload["width"]
        height: int = payload["height"]
        geo_context = payload["geo_context"]
        trail: list[AgentTrailEntry] = []
        failures: list[FailureRecord] = []

        # Step 1: vision (unified Muse Spark + SAM service).
        started = time.perf_counter()
        try:
            vision = run_unified_analysis(validated, width, height)
        except SentinelError as exc:
            trail.append(
                AgentTrailEntry(
                    agent="vision",
                    status=AgentStepStatus.FAILED,
                    duration_s=time.perf_counter() - started,
                    notes=f"{exc.code}: {exc.message}",
                )
            )
            failures.append(
                FailureRecord(step="vision", error=f"{exc.code}: {exc.message}")
            )
            raise
        vision_duration = time.perf_counter() - started
        finding_errors = validate_findings(list(vision.findings))
        vision.warnings.extend(finding_errors)
        trail.append(
            AgentTrailEntry(
                agent="vision",
                status=AgentStepStatus.OK,
                duration_s=vision_duration,
                notes=(
                    f"{len(vision.findings)} findings, "
                    f"{len(vision.segmentations)} prompts, "
                    f"status {vision.workflow_status.value}."
                ),
            )
        )
        return self._complete_dossier(
            vision, geo_context, trail, failures, analysis_ref=None
        )

    def run_workflow_from_vision(
        self,
        mode: str,
        vision: UnifiedAnalysisResponse,
        geo_context: GeoContext,
        analysis_ref: str,
    ) -> IncidentDossier:
        """Impact + reporting over server-cached vision evidence (no models).

        ``vision`` must be a server-held cached response, never
        client-submitted data. It is re-validated before use.
        """
        if mode != WORKFLOW_DISASTER_RESPONSE:
            raise SentinelError(
                "unknown_workflow", f"Unknown workflow {mode!r}."
            )
        if not vision.findings:
            raise SentinelError(
                "cached_evidence_invalid",
                "Cached analysis has no findings; rebuild from the image.",
            )
        vision = vision.model_copy(deep=True)
        finding_errors = validate_findings(list(vision.findings))
        if finding_errors:
            raise SentinelError(
                "cached_evidence_invalid",
                f"Cached analysis failed validation: {finding_errors[0]}",
            )
        structural_errors = validate_segmentations(
            list(vision.segmentations),
            width=vision.image.width,
            height=vision.image.height,
            finding_ids={f.finding_id for f in vision.findings},
        ) + validate_workflow_status(
            list(vision.segmentations), vision.workflow_status
        )
        if structural_errors:
            raise SentinelError(
                "cached_evidence_invalid",
                f"Cached analysis failed validation: {structural_errors[0]}",
            )
        trail = [
            AgentTrailEntry(
                agent="vision",
                status=AgentStepStatus.OK,
                duration_s=0.0,
                notes=(
                    f"reused cached analysis {analysis_ref} (no model calls); "
                    f"{len(vision.findings)} findings, "
                    f"{len(vision.segmentations)} prompts, "
                    f"status {vision.workflow_status.value}."
                ),
            )
        ]
        return self._complete_dossier(
            vision,
            geo_context,
            trail,
            [],
            analysis_ref=analysis_ref,
            vision_source="cached_reuse",
        )

    def _complete_dossier(
        self,
        vision: UnifiedAnalysisResponse,
        geo_context: GeoContext,
        trail: list[AgentTrailEntry],
        failures: list[FailureRecord],
        analysis_ref: str | None,
        vision_source: str = "fresh_analysis",
    ) -> IncidentDossier:
        # Step 2: impact (deterministic; failure degrades, never blocks).
        started = time.perf_counter()
        impact_data: dict | None = None
        impact_error: str | None = None
        try:
            impact_result: AgentResult = ImpactAgent().run(
                {
                    "findings": list(vision.findings),
                    "segmentations": list(vision.segmentations),
                    "geo_context": geo_context,
                }
            )
            impact_data = dict(impact_result.data)
            vision.warnings.extend(impact_result.errors)
            trail.append(
                AgentTrailEntry(
                    agent="impact",
                    status=AgentStepStatus.OK,
                    duration_s=time.perf_counter() - started,
                    notes=(
                        f"{len(impact_data.get('exposure_concerns', []))} "
                        "concerns, "
                        f"{len(impact_data.get('verification_actions', []))} "
                        "actions, "
                        f"{len(impact_data.get('damage_assessments', []))} "
                        "damage reads, "
                        f"{len(impact_data.get('rescue_priorities', []))} "
                        "rescue reads, "
                        f"{len(impact_data.get('access_priorities', []))} "
                        "access reads, "
                        f"{len(impact_data.get('review_priorities', []))} "
                        "review reads."
                    ),
                )
            )
        except Exception as exc:  # degrade safely; never leak internals
            impact_error = f"impact_failed: {type(exc).__name__}."
            failures.append(FailureRecord(step="impact", error=impact_error))
            trail.append(
                AgentTrailEntry(
                    agent="impact",
                    status=AgentStepStatus.FAILED,
                    duration_s=time.perf_counter() - started,
                    notes=impact_error,
                )
            )

        # Step 3: reporting (failure means no dossier is claimed).
        started = time.perf_counter()
        try:
            report_result: AgentResult = ReportingAgent().run(
                {
                    "incident_id": vision.incident_id,
                    "image": vision.image,
                    "vision": vision,
                    "impact_data": impact_data,
                    "impact_error": impact_error,
                    "geo_context": geo_context,
                    "trail": trail,
                    "analysis_ref": analysis_ref,
                    "vision_source": vision_source,
                }
            )
        except Exception as exc:
            failures.append(
                FailureRecord(
                    step="reporting", error=f"reporting_failed: {type(exc).__name__}"
                )
            )
            raise SentinelError(
                "reporting_failed",
                f"Dossier assembly failed for {vision.incident_id} "
                f"({len(vision.findings)} findings, "
                f"{len(vision.segmentations)} prompts preserved in "
                "vision output).",
            ) from exc
        dossier: IncidentDossier = report_result.data["dossier"]
        dossier.agent_trail.append(
            AgentTrailEntry(
                agent="reporting",
                status=AgentStepStatus.OK,
                duration_s=time.perf_counter() - started,
                notes=f"incident_status {dossier.incident_status.value}.",
            )
        )
        return dossier

    def collect(self, results: list[AgentResult]) -> dict:
        return {"results": [r.agent for r in results]}
