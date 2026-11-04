"""Output validators: structural claim checks (no word blocklists).

Observations are never filtered: risk-related words in finding text are
legitimate evidence. What IS enforced is inference structure — every
exposure concern must be conditional, evidenced, unverified, and tied to
a human-review action. Concerns failing these checks are rejected with a
machine-readable message so the orchestrator can drop them loudly.

Material conclusions (concerns, damage reads, rescue/access/review
reads) must link only to retained findings and ledger evidence;
verification actions carry an explicit kind so concern-linked reviews,
finding reviews, and finding-independent follow-ups are each grounded
by their own rule; hazard reads use controlled categories; damage
covers assessable infrastructure only; priorities never fabricate
casualties, locations, or deployment; SAM outcomes keep trigger-only
linkage with consistent status/geometry; and status fields must match
the run they describe.
"""

from __future__ import annotations

from app.schemas.common import Finding
from app.schemas.incident import (
    AccessAttention,
    AgentStepStatus,
    AgentTrailEntry,
    DamageAssessment,
    DamageCategory,
    ExposureConcern,
    HazardCategory,
    IncidentStatus,
    ObservedHazard,
    RescueAttention,
    RescuePriority,
    ReviewAttention,
    VerificationAction,
)
from app.schemas.unified_analysis import (
    PromptSegmentation,
    PromptStatus,
    WorkflowStatus,
)

# Markers of explicit conditional language (matched case-insensitively in
# the condition + concern text joined together).
CONDITIONAL_MARKERS = frozenset(
    {
        "if ",
        "may",
        "might",
        "could",
        "possible",
        "possibly",
        "potential",
        "subject to",
        "pending",
        "unconfirmed",
        "not confirmed",
        "unknown",
        "whether",
        "assuming",
    }
)


def validate_findings(findings: list[Finding]) -> list[str]:
    """Check finding contracts; return error messages (empty = valid)."""
    errors: list[str] = []
    for index, finding in enumerate(findings):
        tag = finding.finding_id or f"index-{index}"
        if not finding.finding_id or not finding.label:
            errors.append(f"invalid_finding:{tag}: missing id or label.")
        if not finding.evidence_refs:
            errors.append(f"invalid_finding:{tag}: no evidence refs.")
        value = finding.confidence.value
        if not 0.0 <= value <= 1.0:
            errors.append(f"invalid_finding:{tag}: confidence out of range.")
    return errors


def validate_exposure_concerns(
    concerns: list[ExposureConcern],
    actions: list[VerificationAction],
    *,
    finding_ids: set[str] | None = None,
    evidence_ids: set[str] | None = None,
) -> list[str]:
    """Reject concerns lacking conditional, evidenced, actionable structure.

    When the retained finding/evidence id sets are supplied, basis refs
    must also resolve to retained evidence — dangling refs reject.
    """
    action_ids = {a.action_id for a in actions}
    errors: list[str] = []
    for concern in concerns:
        tag = concern.concern_id or "unknown"
        if not concern.condition.strip() or not concern.concern.strip():
            errors.append(
                f"rejected_concern:{tag}: empty condition or concern text."
            )
            continue
        joined = f"{concern.condition} {concern.concern}".lower()
        if not any(m in joined for m in CONDITIONAL_MARKERS):
            errors.append(
                f"rejected_concern:{tag}: no conditional language; "
                "affirmative conclusions require human verification."
            )
        if not concern.basis_finding_ids or not concern.basis_evidence_ids:
            errors.append(
                f"rejected_concern:{tag}: missing finding or evidence refs."
            )
        if finding_ids is not None:
            for fid in concern.basis_finding_ids:
                if fid not in finding_ids:
                    errors.append(
                        f"rejected_concern:{tag}: basis finding "
                        f"{fid!r} is not retained evidence."
                    )
        if evidence_ids is not None:
            for eid in concern.basis_evidence_ids:
                if eid not in evidence_ids:
                    errors.append(
                        f"rejected_concern:{tag}: basis evidence "
                        f"{eid!r} has no ledger entry."
                    )
        if concern.status != "unverified":
            errors.append(f"rejected_concern:{tag}: status must be unverified.")
        if concern.verification_action_id not in action_ids:
            errors.append(
                f"rejected_concern:{tag}: verification action "
                f"{concern.verification_action_id!r} not found."
            )
    return errors


def orphaned_concern_action_ids(
    actions: list[VerificationAction],
    dropped_concern_action_ids: set[str],
    retained_concern_action_ids: set[str],
) -> set[str]:
    """Action ids left orphaned by rejected concerns.

    A dropped concern's linked action is orphaned unless another retained
    concern still references the same action id.
    """
    return {
        a.action_id
        for a in actions
        if a.action_id in dropped_concern_action_ids
        and a.action_id not in retained_concern_action_ids
    }


def validate_ledger(cited_ids: list[str], ledger_ids: set[str]) -> list[str]:
    """Every cited evidence id must exist in the ledger."""
    return [
        f"ledger_gap:{cid}: cited evidence id has no ledger entry."
        for cid in cited_ids
        if cid not in ledger_ids
    ]


# Fixed safe verification-method suggestions. Methods are suggestions
# requiring local authority judgment; nothing here may advise entering
# floodwater, approaching unstable slopes, or accessing unsafe
# infrastructure. Empty method means "no suggestion offered".
METHOD_SUGGESTIONS = frozenset(
    {
        "Contact local responders and verify in person with local guidance.",
        "Inspect on site from a safe location with local guidance.",
        "Observe from a distance; do not approach the water.",
        "Compare with a second image angle of the same scene.",
        "Ask the image source for location or time details.",
        "Check local authority or operator records.",
        "Re-run analysis after obtaining clearer imagery.",
    }
)


def validate_verification_actions(
    actions: list,
    finding_ids: set[str],
    *,
    concern_action_ids: set[str] | None = None,
    concern_ids: set[str] | None = None,
) -> list[str]:
    """Check action linkage, methods, detail fields, and kind grounding.

    Every action needs what/why/unknown plus a priority rationale.
    Concern-linked reviews must reference a retained concern; finding
    and people-safety reviews need a retained finding basis;
    segmentation reviews name their prompt (geometry alone never proves
    damage, danger, or identity); geo/routine follow-ups are explicitly
    finding-independent. Related finding refs must always resolve.
    """
    errors: list[str] = []
    for action in actions:
        tag = action.action_id or "unknown"
        kind = getattr(action, "kind", "finding_review")
        for fid in action.related_finding_ids:
            if fid not in finding_ids:
                errors.append(
                    f"invalid_action:{tag}: related finding {fid!r} not found."
                )
        if action.method and action.method not in METHOD_SUGGESTIONS:
            errors.append(
                f"invalid_action:{tag}: method is not an approved suggestion."
            )
        if not action.priority_reason.strip():
            errors.append(
                f"invalid_action:{tag}: missing priority rationale."
            )
        for field in ("what", "why_operational", "unknown"):
            if not getattr(action, field, "").strip():
                errors.append(
                    f"invalid_action:{tag}: missing {field} detail."
                )
        if kind == "concern_review":
            if not action.related_finding_ids:
                errors.append(
                    f"invalid_action:{tag}: concern review lacks a "
                    "finding basis."
                )
            if concern_action_ids is not None and tag not in concern_action_ids:
                errors.append(
                    f"invalid_action:{tag}: concern review references no "
                    "retained concern action."
                )
            linked = getattr(action, "concern_id", None)
            if not linked:
                errors.append(
                    f"invalid_action:{tag}: concern review lacks a "
                    "concern back-link."
                )
            elif concern_ids is not None and linked not in concern_ids:
                errors.append(
                    f"invalid_action:{tag}: concern review references "
                    f"dropped concern {linked!r}."
                )
        elif kind in ("finding_review", "people_safety"):
            if not action.related_finding_ids:
                errors.append(
                    f"invalid_action:{tag}: {kind} lacks a finding basis."
                )
        elif kind == "segmentation_review":
            if not (getattr(action, "prompt", None) or "").strip():
                errors.append(
                    f"invalid_action:{tag}: segmentation review lacks "
                    "its prompt."
                )
    return errors


def validate_finding_review_coverage(
    finding_ids: set[str], actions: list
) -> list[str]:
    """Every retained finding needs at least one human-review action."""
    covered: set[str] = set()
    for action in actions:
        covered.update(action.related_finding_ids)
    return [
        f"finding_without_review:{fid}: no verification action covers it."
        for fid in sorted(finding_ids)
        if fid not in covered
    ]


def validate_segmentation_coverage(
    segmentations: list[PromptSegmentation], actions: list
) -> list[str]:
    """Unmeasured prompts need an explicit human-review action.

    Failed, zero-match, and skipped prompts never imply absence: each
    one must have a segmentation review naming its prompt so a human
    looks. Prompts that measured regions without any triggering finding
    (segmentation-only observations) likewise justify only a review
    request, never a conclusion.
    """
    reviewed = {
        getattr(a, "prompt", None)
        for a in actions
        if getattr(a, "kind", "") == "segmentation_review"
    }
    errors: list[str] = []
    for seg in segmentations:
        needs_review = seg.status in (
            PromptStatus.FAILED,
            PromptStatus.ZERO_MATCHES,
            PromptStatus.SKIPPED,
        ) or not seg.linked_finding_ids
        if needs_review and seg.prompt not in reviewed:
            errors.append(
                f"unreviewed_segmentation:{seg.prompt}: {seg.status.value} "
                "outcome has no segmentation review action."
            )
    return errors


ASSESSABLE_FEATURES = frozenset({"building", "road", "vehicle", "utility"})

# Fabricated-urgency markers: priorities must never assert these.
# Observations may contain these words as evidence; conclusions may
# not state them as facts. Checked in rationale + unknowns text.
_FABRICATED_MARKERS = frozenset(
    {
        "casualt",
        "victim",
        "fatalit",
        "deceased",
        "body count",
        "deploy",
        "dispatch",
    }
)


def _has_fabricated(text: str) -> str | None:
    lowered = text.lower()
    for marker in _FABRICATED_MARKERS:
        if marker in lowered:
            return marker
    return None


def validate_observed_hazards(
    hazards: list[ObservedHazard], finding_ids: set[str]
) -> list[str]:
    """Check hazard restatements: controlled category, retained basis."""
    errors: list[str] = []
    for hazard in hazards:
        tag = hazard.hazard_id or "unknown"
        if not isinstance(hazard.category, HazardCategory):
            errors.append(f"invalid_hazard:{tag}: unknown category.")
        if not hazard.summary.strip():
            errors.append(f"invalid_hazard:{tag}: missing summary.")
        for fid in hazard.finding_ids:
            if fid not in finding_ids:
                errors.append(
                    f"invalid_hazard:{tag}: basis finding {fid!r} not found."
                )
    return errors


def validate_damage_assessments(
    assessments: list[DamageAssessment],
    finding_ids: set[str],
    *,
    evidence_ids: set[str] | None = None,
) -> list[str]:
    """Check damage reads: provisional, evidenced, safety-honest.

    Every read needs an explicit uncertainty note — no category is ever
    certain from a single image — and every basis ref must resolve to
    retained findings (and ledger evidence when supplied), so reads stay
    grounded in finding observations rather than segmentation geometry.
    Only assessable infrastructure (buildings, roads/bridges, vehicles,
    utilities) may carry a read; water, people, and generic nouns never
    do. Positive reads need direct same-feature evidence; inadequate
    observations stay cannot_assess, never a default all-clear.
    """
    errors: list[str] = []
    for assessment in assessments:
        tag = assessment.assessment_id or "unknown"
        if not isinstance(assessment.category, DamageCategory):
            errors.append(f"invalid_damage:{tag}: unknown category.")
        if assessment.feature not in ASSESSABLE_FEATURES:
            errors.append(
                f"invalid_damage:{tag}: feature {assessment.feature!r} "
                "is not assessable infrastructure."
            )
        if not assessment.basis_finding_ids or not assessment.basis_evidence_ids:
            errors.append(
                f"invalid_damage:{tag}: missing finding or evidence refs."
            )
        for fid in assessment.basis_finding_ids:
            if fid not in finding_ids:
                errors.append(
                    f"invalid_damage:{tag}: basis finding {fid!r} not found."
                )
        if evidence_ids is not None:
            for eid in assessment.basis_evidence_ids:
                if eid not in evidence_ids:
                    errors.append(
                        f"invalid_damage:{tag}: basis evidence "
                        f"{eid!r} has no ledger entry."
                    )
        if not assessment.provisional:
            errors.append(f"invalid_damage:{tag}: must be provisional.")
        if not assessment.rationale.strip():
            errors.append(f"invalid_damage:{tag}: missing rationale.")
        if (
            assessment.category == DamageCategory.NO_VISIBLE_DAMAGE
            and not assessment.uncertainty_note.strip()
        ):
            errors.append(
                f"invalid_damage:{tag}: no-visible-damage needs an "
                "explicit not-safe uncertainty note."
            )
        elif not assessment.uncertainty_note.strip():
            errors.append(
                f"invalid_damage:{tag}: missing uncertainty note; every "
                "damage read stays provisional."
            )
    return errors


def validate_damage_consistency(
    assessments: list[DamageAssessment], findings: list[Finding]
) -> list[str]:
    """Cross-check damage merges against the finding observations.

    Recomputes each family's clause categories with the shared
    condition-assessment grounding (findings only — SAM geometry never
    contributes): the retained category must be the max-severity
    observation, and conflicting observations must carry an explicit
    disagreement note forcing human reconciliation.
    """
    from app.agents.condition_assessment import (
        family_clause_categories,
        family_consensus_category,
    )

    errors: list[str] = []
    for assessment in assessments:
        tag = assessment.assessment_id or "unknown"
        distinct = family_clause_categories(findings, assessment.feature)
        if not distinct:
            errors.append(
                f"invalid_damage:{tag}: feature {assessment.feature!r} "
                "has no assessable observation in the retained findings."
            )
            continue
        consensus = family_consensus_category(findings, assessment.feature)
        if consensus is not None and assessment.category != consensus:
            errors.append(
                f"invalid_damage:{tag}: category "
                f"{assessment.category.value} is not the max-severity "
                f"observation ({consensus.value})."
            )
        spread = {c for c in distinct if c != DamageCategory.CANNOT_ASSESS}
        if len(spread) > 1 and "disagree" not in (
            assessment.uncertainty_note or ""
        ).lower():
            errors.append(
                f"invalid_damage:{tag}: conflicting observations need an "
                "explicit disagreement note."
            )
    return errors


def validate_rescue_priorities(
    priorities: list[RescueAttention],
    finding_ids: set[str],
    *,
    evidence_ids: set[str] | None = None,
) -> list[str]:
    """Check rescue reads: valid priority, evidenced, review-required.

    Basis refs must resolve to retained findings (and ledger evidence
    when supplied): urgency is grounded in finding observations only,
    never in segmentation geometry or person/hazard co-occurrence.
    Person-alone observations are routine (low), never rescue urgency;
    findings with no person evidence are undetermined, never low. No
    casualties, locations, or deployment are ever asserted.
    """
    errors: list[str] = []
    for attention in priorities:
        tag = attention.attention_id or "unknown"
        if not isinstance(attention.priority, RescuePriority):
            errors.append(f"invalid_rescue:{tag}: unknown priority.")
        if not attention.basis_finding_ids and (
            attention.priority != RescuePriority.UNDETERMINED
        ):
            errors.append(
                f"invalid_rescue:{tag}: only undetermined may lack a basis."
            )
        for fid in attention.basis_finding_ids:
            if fid not in finding_ids:
                errors.append(
                    f"invalid_rescue:{tag}: basis finding {fid!r} not found."
                )
        if evidence_ids is not None:
            for eid in attention.basis_evidence_ids:
                if eid not in evidence_ids:
                    errors.append(
                        f"invalid_rescue:{tag}: basis evidence "
                        f"{eid!r} has no ledger entry."
                    )
        if not attention.requires_human_review:
            errors.append(f"invalid_rescue:{tag}: must require human review.")
        if not attention.rationale.strip():
            errors.append(f"invalid_rescue:{tag}: missing rationale.")
        if not attention.unknowns.strip():
            errors.append(f"invalid_rescue:{tag}: missing unknowns.")
        marker = _has_fabricated(
            f"{attention.rationale} {attention.unknowns}"
        )
        if marker is not None:
            errors.append(
                f"invalid_rescue:{tag}: fabricated urgency term "
                f"{marker!r}; never assert casualties or deployment."
            )
    return errors


def validate_access_priorities(
    priorities: list[AccessAttention],
    finding_ids: set[str],
    *,
    evidence_ids: set[str] | None = None,
) -> list[str]:
    """Check access reads: valid priority, evidenced, review-required."""
    errors: list[str] = []
    for attention in priorities:
        tag = attention.attention_id or "unknown"
        if not isinstance(attention.priority, RescuePriority):
            errors.append(f"invalid_access:{tag}: unknown priority.")
        if not attention.basis_finding_ids and (
            attention.priority != RescuePriority.UNDETERMINED
        ):
            errors.append(
                f"invalid_access:{tag}: only undetermined may lack a basis."
            )
        for fid in attention.basis_finding_ids:
            if fid not in finding_ids:
                errors.append(
                    f"invalid_access:{tag}: basis finding {fid!r} not found."
                )
        if evidence_ids is not None:
            for eid in attention.basis_evidence_ids:
                if eid not in evidence_ids:
                    errors.append(
                        f"invalid_access:{tag}: basis evidence "
                        f"{eid!r} has no ledger entry."
                    )
        if not attention.requires_human_review:
            errors.append(f"invalid_access:{tag}: must require human review.")
        if not attention.rationale.strip():
            errors.append(f"invalid_access:{tag}: missing rationale.")
        if not attention.unknowns.strip():
            errors.append(f"invalid_access:{tag}: missing unknowns.")
        marker = _has_fabricated(
            f"{attention.rationale} {attention.unknowns}"
        )
        if marker is not None:
            errors.append(
                f"invalid_access:{tag}: fabricated urgency term "
                f"{marker!r}; never assert casualties or deployment."
            )
    return errors


def validate_review_priorities(
    priorities: list[ReviewAttention],
    finding_ids: set[str],
    *,
    evidence_ids: set[str] | None = None,
) -> list[str]:
    """Check image-review reads: valid priority, evidenced, review-required."""
    errors: list[str] = []
    for review in priorities:
        tag = review.review_id or "unknown"
        if not isinstance(review.priority, RescuePriority):
            errors.append(f"invalid_review:{tag}: unknown priority.")
        if not review.basis_finding_ids and (
            review.priority != RescuePriority.UNDETERMINED
        ):
            errors.append(
                f"invalid_review:{tag}: only undetermined may lack a basis."
            )
        for fid in review.basis_finding_ids:
            if fid not in finding_ids:
                errors.append(
                    f"invalid_review:{tag}: basis finding {fid!r} not found."
                )
        if evidence_ids is not None:
            for eid in review.basis_evidence_ids:
                if eid not in evidence_ids:
                    errors.append(
                        f"invalid_review:{tag}: basis evidence "
                        f"{eid!r} has no ledger entry."
                    )
        if not review.requires_human_review:
            errors.append(f"invalid_review:{tag}: must require human review.")
        if not review.rationale.strip():
            errors.append(f"invalid_review:{tag}: missing rationale.")
        if not review.unknowns.strip():
            errors.append(f"invalid_review:{tag}: missing unknowns.")
        marker = _has_fabricated(f"{review.rationale} {review.unknowns}")
        if marker is not None:
            errors.append(
                f"invalid_review:{tag}: fabricated urgency term "
                f"{marker!r}; never assert casualties or deployment."
            )
    return errors


def validate_priority_consistency(
    rescue: list[RescueAttention],
    access: list[AccessAttention],
    review: list[ReviewAttention],
    findings: list[Finding],
) -> list[str]:
    """Cross-check priorities against the finding observations.

    Recomputes each list with the shared condition-assessment
    grounding (findings only): retained priorities must match the
    recomputed evidence gates, so person-alone, no-person, and
    access/review separations cannot drift.
    """
    from app.agents.condition_assessment import (
        access_priorities,
        rescue_priorities,
        review_priorities,
    )

    errors: list[str] = []
    expected_rescue, _ = rescue_priorities(findings)
    expected_access, _ = access_priorities(findings)
    expected_review, _ = review_priorities(findings)
    exp_r = {tuple(a.basis_finding_ids): a.priority for a in expected_rescue}
    exp_a = {tuple(a.basis_finding_ids): a.priority for a in expected_access}
    exp_v = {tuple(r.basis_finding_ids): r.priority for r in expected_review}
    for attention in rescue:
        key = tuple(attention.basis_finding_ids)
        if key in exp_r and attention.priority != exp_r[key]:
            errors.append(
                f"invalid_rescue:{attention.attention_id}: priority "
                f"{attention.priority.value} does not match evidence "
                f"gates ({exp_r[key].value})."
            )
    for attention in access:
        key = tuple(attention.basis_finding_ids)
        if key in exp_a and attention.priority != exp_a[key]:
            errors.append(
                f"invalid_access:{attention.attention_id}: priority "
                f"{attention.priority.value} does not match evidence "
                f"gates ({exp_a[key].value})."
            )
    for item in review:
        key = tuple(item.basis_finding_ids)
        if key in exp_v and item.priority != exp_v[key]:
            errors.append(
                f"invalid_review:{item.review_id}: priority "
                f"{item.priority.value} does not match evidence "
                f"gates ({exp_v[key].value})."
            )
    return errors


def validate_segmentations(
    segmentations: list[PromptSegmentation],
    *,
    width: int | None = None,
    height: int | None = None,
    finding_ids: set[str] | None = None,
) -> list[str]:
    """Check SAM outcomes: trigger-only linkage, status honesty, geometry.

    Detections are preserved verbatim (masks, boxes, and box-local
    geometry are never relabeled or suppressed here); what IS checked is
    structural honesty — prompt provenance retained, trigger-only
    association intact, detections present exactly for executed matches,
    errors recorded for failed/skipped prompts, and boxes ordered and
    inside the image. A prompt match is geometry only: it never proves
    damage, danger, or identity.
    """
    errors: list[str] = []
    for seg in segmentations:
        tag = seg.prompt or "unknown"
        if seg.association != "prompt_trigger_only":
            errors.append(
                f"invalid_segmentation:{tag}: association must stay "
                "prompt_trigger_only."
            )
        if seg.status == PromptStatus.OK and not seg.detections:
            errors.append(
                f"invalid_segmentation:{tag}: ok status needs detections."
            )
        if seg.status in (
            PromptStatus.ZERO_MATCHES,
            PromptStatus.FAILED,
            PromptStatus.SKIPPED,
        ) and seg.detections:
            errors.append(
                f"invalid_segmentation:{tag}: {seg.status.value} status "
                "must not carry detections."
            )
        if seg.status in (PromptStatus.FAILED, PromptStatus.SKIPPED):
            if not (seg.error or "").strip():
                errors.append(
                    f"invalid_segmentation:{tag}: {seg.status.value} "
                    "needs a recorded reason."
                )
        elif (seg.error or "").strip():
            errors.append(
                f"invalid_segmentation:{tag}: {seg.status.value} must not "
                "carry an error."
            )
        if finding_ids is not None:
            for fid in seg.linked_finding_ids:
                if fid not in finding_ids:
                    errors.append(
                        f"invalid_segmentation:{tag}: linked finding "
                        f"{fid!r} is not retained evidence."
                    )
        seen: set[str] = set()
        for detection in seg.detections:
            oid = detection.object_id or "unknown"
            if not detection.object_id:
                errors.append(
                    f"invalid_segmentation:{tag}: detection lacks an id."
                )
            elif oid in seen:
                errors.append(
                    f"invalid_segmentation:{tag}: duplicate object {oid!r}."
                )
            seen.add(oid)
            box = detection.box
            if not (0 <= box.x1 < box.x2 and 0 <= box.y1 < box.y2):
                errors.append(
                    f"invalid_segmentation:{tag}: object {oid!r} box "
                    "is not ordered and non-negative."
                )
            elif width is not None and height is not None and (
                box.x2 > width or box.y2 > height
            ):
                errors.append(
                    f"invalid_segmentation:{tag}: object {oid!r} box "
                    "falls outside the image."
                )
    return errors


def validate_workflow_status(
    segmentations: list[PromptSegmentation], workflow_status: WorkflowStatus
) -> list[str]:
    """The workflow status must match the prompt-outcome mix.

    Mirrors the documented rule: vision_only when no SAM call executed,
    completed when every prompt executed cleanly (ok or zero_matches),
    partial otherwise.
    """
    attempted = [
        s
        for s in segmentations
        if s.status
        in (PromptStatus.OK, PromptStatus.ZERO_MATCHES, PromptStatus.FAILED)
    ]
    if not attempted:
        expected = WorkflowStatus.VISION_ONLY
    elif all(
        s.status in (PromptStatus.OK, PromptStatus.ZERO_MATCHES)
        for s in attempted
    ) and len(attempted) == len(segmentations):
        expected = WorkflowStatus.COMPLETED
    else:
        expected = WorkflowStatus.PARTIAL
    if workflow_status != expected:
        return [
            f"workflow_status_mismatch:{workflow_status.value}: prompt "
            f"outcomes require {expected.value}."
        ]
    return []


def validate_incident_status(
    incident_status: IncidentStatus,
    trail: list[AgentTrailEntry],
    *,
    impact_failed: bool = False,
) -> list[str]:
    """A dossier is never completed when a required agent failed.

    ``impact_failed`` covers callers whose trail does not record the
    impact step (the orchestrator always records it; direct reporting
    calls pass the flag instead).
    """
    failed = [t.agent for t in trail if t.status == AgentStepStatus.FAILED]
    if impact_failed and "impact" not in failed:
        failed.append("impact")
    if failed and incident_status != IncidentStatus.PARTIAL:
        return [
            f"incident_status_mismatch:{incident_status.value}: failed "
            f"agent(s) {', '.join(sorted(set(failed)))} require partial."
        ]
    if not failed and incident_status != IncidentStatus.COMPLETED:
        return [
            f"incident_status_mismatch:{incident_status.value}: no agent "
            "failed, so the dossier is completed."
        ]
    return []
