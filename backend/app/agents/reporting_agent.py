"""Reporting Agent: deterministic incident-dossier assembly (no model calls).

Builds the ``IncidentDossier`` from vision output, impact output (or an
impact failure note), and operator geo context. Adds no new factual
claims: every section restates or summarizes agent outputs with evidence
ids, and every gap is labeled explicitly.

Degraded path (``impact_data`` is None): concerns are unavailable and are
NOT synthesized. The dossier carries observed evidence plus fallback
review actions and ``incident_status`` stays ``partial``.
"""

from __future__ import annotations

from app.agents.base import AgentResult, BaseAgent
from app.agents.report_content import (
    action_title,
    finding_review_texts,
    hazard_gaps,
    scene_headline,
    scene_observed,
    scene_unknowns,
)
from app.agents.vision_agent import SINGLE_IMAGE_LIMITATIONS
from app.orchestrator.validators import (
    orphaned_concern_action_ids,
    validate_access_priorities,
    validate_damage_assessments,
    validate_damage_consistency,
    validate_exposure_concerns,
    validate_finding_review_coverage,
    validate_findings,
    validate_incident_status,
    validate_ledger,
    validate_observed_hazards,
    validate_priority_consistency,
    validate_rescue_priorities,
    validate_review_priorities,
    validate_segmentation_coverage,
    validate_verification_actions,
)
from app.schemas.incident import (
    AccessAttention,
    AgentTrailEntry,
    DamageAssessment,
    EvidenceLedgerEntry,
    ExposureConcern,
    FindingGroup,
    GeoContext,
    GeoStatus,
    IncidentDossier,
    IncidentStatus,
    InformationGap,
    ObservedHazard,
    RescueAttention,
    ReviewAttention,
    SegmentationSummary,
    SituationSummary,
    VerificationAction,
)
from app.schemas.segmentation import SegmentImageInfo
from app.schemas.unified_analysis import PromptStatus, UnifiedAnalysisResponse

MAX_FALLBACK_FINDING_ACTIONS = 8

# Impact cap notes (arriving via vision warnings) mapped to the dossier
# section that lost content, so partial lists are explicitly flagged.
_IMPACT_CAP_SECTIONS = {
    "impact_concern_cap": "exposure_concerns",
    "impact_action_cap": "verification_actions",
    "impact_damage_cap": "damage_assessments",
    "impact_rescue_cap": "rescue_priorities",
    "impact_access_cap": "access_priorities",
    "impact_review_cap": "review_priorities",
}


class ReportingAgent(BaseAgent):
    name = "reporting"

    def run(self, payload: dict) -> AgentResult:
        incident_id: str = payload["incident_id"]
        image: SegmentImageInfo = payload["image"]
        vision: UnifiedAnalysisResponse = payload["vision"]
        impact_data: dict | None = payload.get("impact_data")
        impact_error: str | None = payload.get("impact_error")
        geo_context: GeoContext = payload["geo_context"]
        trail: list[AgentTrailEntry] = list(payload.get("trail") or [])
        warnings: list[str] = list(vision.warnings)
        degraded: list[str] = []

        def flag(section: str) -> None:
            if section not in degraded:
                degraded.append(section)

        summaries = [
            SegmentationSummary(
                prompt=seg.prompt,
                status=seg.status,
                detection_count=len(seg.detections),
                linked_finding_ids=list(seg.linked_finding_ids),
                provenance=seg.provenance,
            )
            for seg in vision.segmentations
        ]

        ledger = _evidence_ledger(vision)
        ledger_ids = {entry.evidence_id for entry in ledger}
        finding_ids = {f.finding_id for f in vision.findings}
        finding_errors = validate_findings(list(vision.findings))
        if finding_errors:
            for error in finding_errors:
                if error not in warnings:
                    warnings.append(error)
            flag("findings")

        if impact_data is None:
            hazards: list[ObservedHazard] = []
            concerns: list[ExposureConcern] = []
            damage: list[DamageAssessment] = []
            rescue: list[RescueAttention] = []
            access: list[AccessAttention] = []
            review: list[ReviewAttention] = []
            actions = _fallback_actions(vision, geo_context)
            incident_status = IncidentStatus.PARTIAL
            flag("impact")
            warnings.append(
                "impact_unavailable: "
                f"{impact_error or 'impact assessment failed.'} "
                "Exposure concerns were not generated."
            )
        else:
            hazards = list(impact_data.get("observed_hazards") or [])
            concerns = list(impact_data.get("exposure_concerns") or [])
            actions = list(impact_data.get("verification_actions") or [])
            damage = list(impact_data.get("damage_assessments") or [])
            rescue = list(impact_data.get("rescue_priorities") or [])
            access = list(impact_data.get("access_priorities") or [])
            review = list(impact_data.get("review_priorities") or [])
            hazard_errors = validate_observed_hazards(hazards, finding_ids)
            if hazard_errors:
                rejected_haz = _rejected_ids(hazard_errors)
                hazards = [
                    h for h in hazards if h.hazard_id not in rejected_haz
                ]
                warnings.extend(hazard_errors)
                flag("observed_hazards")
            dropped_concern_action_ids = {
                c.verification_action_id for c in concerns
            }
            rejection_errors = validate_exposure_concerns(
                concerns,
                actions,
                finding_ids=finding_ids,
                evidence_ids=ledger_ids,
            )
            if rejection_errors:
                rejected = _rejected_ids(rejection_errors)
                concerns = [
                    c for c in concerns if c.concern_id not in rejected
                ]
                warnings.extend(rejection_errors)
                flag("exposure_concerns")
            retained_concern_action_ids = {
                c.verification_action_id for c in concerns
            }
            dropped_concern_action_ids -= retained_concern_action_ids
            damage_errors = validate_damage_assessments(
                damage, finding_ids, evidence_ids=ledger_ids
            )
            damage_errors += validate_damage_consistency(
                damage, list(vision.findings)
            )
            if damage_errors:
                rejected_damage = _rejected_ids(damage_errors)
                damage = [
                    d for d in damage if d.assessment_id not in rejected_damage
                ]
                warnings.extend(damage_errors)
                flag("damage_assessments")
            rescue_errors = validate_rescue_priorities(
                rescue, finding_ids, evidence_ids=ledger_ids
            )
            rescue_errors += validate_access_priorities(
                access, finding_ids, evidence_ids=ledger_ids
            )
            rescue_errors += validate_review_priorities(
                review, finding_ids, evidence_ids=ledger_ids
            )
            rescue_errors += validate_priority_consistency(
                rescue, access, review, list(vision.findings)
            )
            if rescue_errors:
                rejected_rescue = _rejected_ids(rescue_errors)
                rescue = [
                    r for r in rescue if r.attention_id not in rejected_rescue
                ]
                access = [
                    a for a in access if a.attention_id not in rejected_rescue
                ]
                review = [
                    v for v in review if v.review_id not in rejected_rescue
                ]
                warnings.extend(rescue_errors)
                for err in rescue_errors:
                    if err.startswith("invalid_rescue"):
                        flag("rescue_priorities")
                    elif err.startswith("invalid_access"):
                        flag("access_priorities")
                    elif err.startswith("invalid_review"):
                        flag("review_priorities")
            # Rejected concerns leave no orphaned dependent actions: drop
            # their linked reviews (unless a retained concern still uses
            # the same action), then restore finding-review coverage so
            # every retained finding still has a human-review action.
            orphans = orphaned_concern_action_ids(
                actions, dropped_concern_action_ids, retained_concern_action_ids
            )
            if orphans:
                actions = [a for a in actions if a.action_id not in orphans]
                for aid in sorted(orphans):
                    warnings.append(
                        f"orphan_action_dropped:{aid}: its concern was "
                        "rejected; the review is removed with it."
                    )
                flag("verification_actions")
            used_action_ids = {a.action_id for a in actions}
            for gap in validate_finding_review_coverage(finding_ids, actions):
                fid = gap.split(":")[1]
                restored = _restored_finding_action(
                    vision, fid, taken=used_action_ids
                )
                used_action_ids.add(restored.action_id)
                actions.append(restored)
                warnings.append(
                    f"review_coverage_restored:{fid}: replacement review "
                    "added after a rejected conclusion."
                )
                flag("verification_actions")
            incident_status = IncidentStatus.COMPLETED

        uncertainty = _uncertainty_notes(vision, geo_context, impact_data is None)
        cited = [ref.evidence_id for f in vision.findings for ref in f.evidence_refs]
        for concern in concerns:
            cited.extend(concern.basis_evidence_ids)
        for assessment in damage:
            cited.extend(assessment.basis_evidence_ids)
        for attention in rescue:
            cited.extend(attention.basis_evidence_ids)
        for attention in access:
            cited.extend(attention.basis_evidence_ids)
        for item in review:
            cited.extend(item.basis_evidence_ids)
        ledger_errors = validate_ledger(cited, ledger_ids)
        if ledger_errors:
            warnings.extend(ledger_errors)
            flag("evidence_ledger")
        action_errors = validate_verification_actions(
            actions,
            finding_ids,
            concern_action_ids={c.verification_action_id for c in concerns},
            concern_ids={c.concern_id for c in concerns},
        )
        if action_errors:
            warnings.extend(action_errors)
            flag("verification_actions")
        seg_coverage_errors = validate_segmentation_coverage(
            list(vision.segmentations), actions
        )
        if seg_coverage_errors:
            warnings.extend(seg_coverage_errors)
            flag("verification_actions")
        for warning in warnings:
            for prefix, section in _IMPACT_CAP_SECTIONS.items():
                if warning.startswith(prefix):
                    flag(section)
        status_errors = validate_incident_status(
            incident_status, trail, impact_failed=impact_data is None
        )
        if status_errors:
            # Never look complete when an agent failed: force partial.
            incident_status = IncidentStatus.PARTIAL
            warnings.extend(status_errors)
            flag("impact")

        dossier = IncidentDossier(
            incident_id=incident_id,
            image=image,
            analysis_ref=payload.get("analysis_ref"),
            vision_source=payload.get("vision_source", "fresh_analysis"),
            vision_workflow_status=vision.workflow_status,
            incident_status=incident_status,
            situation_summary=_situation_summary(vision, geo_context),
            findings=list(vision.findings),
            finding_groups=_finding_groups(vision),
            information_gaps=_information_gaps(vision, geo_context),
            segmentation_summary=summaries,
            segmentations=list(vision.segmentations),
            observed_hazards=hazards,
            exposure_concerns=concerns,
            damage_assessments=damage,
            rescue_priorities=rescue,
            access_priorities=access,
            review_priorities=review,
            geo_context=geo_context,
            uncertainty_notes=uncertainty,
            verification_actions=actions,
            evidence_ledger=ledger,
            agent_trail=trail,
            warnings=warnings,
            degraded_sections=degraded,
        )
        return AgentResult(agent=self.name, findings=[], errors=[], data={"dossier": dossier})


def _rejected_ids(errors: list[str]) -> set[str]:
    ids: set[str] = set()
    for error in errors:
        parts = error.split(":")
        if len(parts) >= 2:
            ids.add(parts[1])
    return ids


def _fallback_actions(
    vision: UnifiedAnalysisResponse, geo_context: GeoContext
) -> list[VerificationAction]:
    """Review actions from available evidence only — no synthesized concerns."""
    actions = [
        VerificationAction(
            action_id="verify-impact-rerun",
            action="Impact assessment is unavailable: manually review the "
            "findings below or re-run the assessment.",
            reason="The impact step failed; no exposure concerns were generated.",
            priority="high",
            what="Review each finding below without impact guidance, or "
            "re-run the assessment.",
            why_operational="Findings still need human review despite the "
            "failed impact step.",
            unknown="Prioritized concerns; derive them manually for now.",
            method="Re-run analysis after obtaining clearer imagery.",
            priority_reason="Impact failure leaves findings untriaged.",
            kind="routine",
            title=action_title("routine"),
        )
    ]
    for finding in vision.findings[:MAX_FALLBACK_FINDING_ACTIONS]:
        review_action, review_what = finding_review_texts(finding)
        actions.append(
            VerificationAction(
                action_id=f"verify-finding-{finding.finding_id}",
                action=review_action,
                reason="AI observation is unverified until human review.",
                priority="high",
                related_finding_ids=[finding.finding_id],
                what=review_what,
                why_operational="Unverified observations must be confirmed "
                "before operational use.",
                unknown="Whether the observation is accurate and relevant.",
                method="Compare with a second image angle of the same scene.",
                priority_reason="Impact failure; every finding needs review.",
                kind="finding_review",
                title=action_title("finding_review", finding.label),
            )
        )
    if geo_context.status == GeoStatus.UNAVAILABLE:
        actions.append(
            VerificationAction(
                action_id="verify-geo-context",
                action="Obtain operator location context (label or "
                "coordinates) to ground follow-up.",
                reason="No geospatial context was provided with this image.",
                priority="medium",
                what="Ask the image source for a location label or coordinates.",
                why_operational="Location context focuses verification on the "
                "right area.",
                unknown="Where this image was taken.",
                method="Ask the image source for location or time details.",
                priority_reason="Helpful context; not blocking for image review.",
                kind="geo_context",
                title=action_title("geo_context"),
            )
        )
    return actions


def _restored_finding_action(
    vision: UnifiedAnalysisResponse, finding_id: str, taken: set[str]
) -> VerificationAction:
    """Replacement review when a finding lost its covering action.

    Used only after a rejected conclusion orphaned the action that had
    covered this finding: the finding itself is retained evidence and
    still needs independent human review.
    """
    finding = next(
        (f for f in vision.findings if f.finding_id == finding_id),
        None,
    )
    if finding is not None:
        review_action, review_what = finding_review_texts(finding)
    else:
        review_action = (
            f"Human review of '{finding_id}': confirm what is visible."
        )
        review_what = (
            f"For finding '{finding_id}', confirm what is visible; "
            "confirm the observation is accurate."
        )
    action_id = f"verify-finding-{finding_id}"
    if action_id in taken:
        action_id = f"{action_id}-restored"
    return VerificationAction(
        action_id=action_id,
        action=review_action,
        reason="The finding's covering review was removed with a rejected "
        "conclusion; independent review is still required.",
        priority="high",
        related_finding_ids=[finding_id],
        what=review_what,
        why_operational="Unverified observations must be confirmed before "
        "operational use.",
        unknown="Whether the observation is accurate and relevant.",
        method="Compare with a second image angle of the same scene.",
        priority_reason="Restored coverage after a rejected conclusion.",
        kind="finding_review",
        title=action_title(
            "finding_review", finding.label if finding is not None else finding_id
        ),
    )


def _situation_summary(
    vision: UnifiedAnalysisResponse, geo_context: GeoContext
) -> SituationSummary:
    """Compose a grounded headline + observed/unknowns from vision output.

    Shared report-content rules: a hazard-aware headline, a natural
    observed-scene description, and explicit unknowns. Every quoted
    label, excerpt, and count comes from the inputs.
    """
    findings = list(vision.findings)
    segmentations = list(vision.segmentations)
    return SituationSummary(
        headline=scene_headline(findings),
        observed=scene_observed(findings, segmentations),
        unknowns=scene_unknowns(
            findings,
            geo_context.status == GeoStatus.PROVIDED,
            segmentations,
        ),
    )


def _finding_groups(vision: UnifiedAnalysisResponse) -> list[FindingGroup]:
    """Group findings by shared SAM-prompt linkage (display aid only)."""
    by_id = {f.finding_id: f for f in vision.findings}
    groups: list[FindingGroup] = []
    grouped: set[str] = set()
    for seg in vision.segmentations:
        members = [fid for fid in seg.linked_finding_ids if fid in by_id]
        if not members:
            continue
        evidence: list[str] = []
        for fid in members:
            grouped.add(fid)
            for ref in by_id[fid].evidence_refs:
                if ref.evidence_id not in evidence:
                    evidence.append(ref.evidence_id)
        groups.append(
            FindingGroup(
                group_id=f"grp-{seg.prompt}",
                title=f"{seg.prompt}-related observations",
                finding_ids=members,
                evidence_ids=evidence,
            )
        )
    leftovers = [f.finding_id for f in vision.findings if f.finding_id not in grouped]
    if leftovers:
        evidence = []
        for fid in leftovers:
            for ref in by_id[fid].evidence_refs:
                if ref.evidence_id not in evidence:
                    evidence.append(ref.evidence_id)
        groups.append(
            FindingGroup(
                group_id="grp-other",
                title="Other observations",
                finding_ids=leftovers,
                evidence_ids=evidence,
            )
        )
    return groups


def _information_gaps(
    vision: UnifiedAnalysisResponse, geo_context: GeoContext
) -> list[InformationGap]:
    """Explicit unknowns, unverified items, and their operational relevance."""
    gaps = [
        InformationGap(
            topic="capture_time",
            detail="Image capture time is not recorded.",
            why_matters="Recency determines how urgently findings need review.",
            status="unknown",
        )
    ]
    if geo_context.status == GeoStatus.UNAVAILABLE:
        gaps.append(
            InformationGap(
                topic="incident_location",
                detail="No location was supplied with this image.",
                why_matters="Without a location, follow-up cannot be directed.",
                status="unknown",
            )
        )
    else:
        gaps.append(
            InformationGap(
                topic="incident_location",
                detail="Location is operator-provided and has not been "
                "independently verified; image contents are not confirmed "
                "to correspond to it.",
                why_matters="Unverified locations must not drive dispatch "
                "decisions alone.",
                status="unverified",
            )
        )
    road_relevant = any(
        seg.prompt == "road" for seg in vision.segmentations
    ) or any("road" in f.label.lower() for f in vision.findings)
    if road_relevant:
        gaps.append(
            InformationGap(
                topic="accessibility",
                detail="Whether visible roads are passable is unconfirmed.",
                why_matters="Passability decides whether ground teams can "
                "use the route.",
                status="unknown",
            )
        )
    for topic, detail, why_matters, status in hazard_gaps(
        list(vision.findings)
    ):
        gaps.append(
            InformationGap(
                topic=topic,
                detail=detail,
                why_matters=why_matters,
                status=status,  # type: ignore[arg-type]
            )
        )
    gaps.append(
        InformationGap(
            topic="ground_truth",
            detail="No field confirmation exists for any finding in this report.",
            why_matters="Imagery alone cannot confirm conditions on the ground.",
            status="unknown",
        )
    )
    return gaps


def _uncertainty_notes(
    vision: UnifiedAnalysisResponse,
    geo_context: GeoContext,
    impact_missing: bool,
) -> list[str]:
    notes = [SINGLE_IMAGE_LIMITATIONS]
    for seg in vision.segmentations:
        if seg.status == PromptStatus.FAILED:
            notes.append(
                f"Segmentation for '{seg.prompt}' failed, so '{seg.prompt}' "
                "areas could not be measured from this image."
            )
        elif seg.status == PromptStatus.SKIPPED:
            notes.append(
                f"Segmentation for '{seg.prompt}' was skipped, so "
                f"'{seg.prompt}' areas were not measured."
            )
        elif seg.status == PromptStatus.ZERO_MATCHES:
            notes.append(
                f"Prompt '{seg.prompt}' matched nothing: the concept may be "
                "absent or the prompt may not fit this image."
            )
    if geo_context.status == GeoStatus.UNAVAILABLE:
        notes.append(
            "No geospatial context was provided: image contents cannot be "
            "placed on a map and no route, distance, or population claims "
            "are made."
        )
    else:
        notes.append(
            "Location context is operator-provided and unverified: image "
            "contents are not confirmed to correspond to the supplied "
            "coordinates, and no spatial analysis was performed."
        )
    if impact_missing:
        notes.append(
            "Impact reasoning is unavailable for this report: exposure "
            "concerns were not generated."
        )
    notes.append(
        "Segmentation geometry never confirms findings: finding-to-mask "
        "links record prompt selection only."
    )
    return notes


def _evidence_ledger(vision: UnifiedAnalysisResponse) -> list[EvidenceLedgerEntry]:
    ledger = [
        EvidenceLedgerEntry(
            evidence_id=vision.image.evidence_id,
            modality="image",
            source="operator upload",
        )
    ]
    seen = {vision.image.evidence_id}
    for finding in vision.findings:
        for ref in finding.evidence_refs:
            if ref.evidence_id not in seen:
                seen.add(ref.evidence_id)
                ledger.append(
                    EvidenceLedgerEntry(
                        evidence_id=ref.evidence_id,
                        modality=ref.modality,
                        source="vision:Muse Spark",
                    )
                )
    return ledger
