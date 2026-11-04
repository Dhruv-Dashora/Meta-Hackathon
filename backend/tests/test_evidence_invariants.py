"""Evidence-integrity invariant tests (validators + reporting + reuse).

Pins the Phase-1 contracts: material conclusions link only to retained
findings/ledger evidence; concern-linked reviews reference retained
concerns; segmentation outcomes keep trigger-only linkage with honest
status/geometry; rejected conclusions leave no orphaned actions; and
partial failures are explicitly flagged.
"""

import pytest

from app.agents.impact_agent import ImpactAgent
from app.agents.reporting_agent import ReportingAgent
from app.core.errors import SentinelError
from app.orchestrator.orchestrator import Orchestrator
from app.orchestrator.validators import (
    orphaned_concern_action_ids,
    validate_damage_assessments,
    validate_damage_consistency,
    validate_exposure_concerns,
    validate_finding_review_coverage,
    validate_incident_status,
    validate_rescue_priorities,
    validate_segmentation_coverage,
    validate_segmentations,
    validate_verification_actions,
    validate_workflow_status,
)
from app.schemas.common import Confidence, EvidenceRef, Finding
from app.schemas.incident import (
    AgentStepStatus,
    AgentTrailEntry,
    DamageAssessment,
    DamageCategory,
    ExposureConcern,
    GeoContext,
    GeoStatus,
    IncidentStatus,
    RescueAttention,
    RescuePriority,
    VerificationAction,
)
from app.schemas.segmentation import (
    SegmentBox,
    SegmentDetection,
    SegmentImageInfo,
    SegmentMask,
)
from app.schemas.unified_analysis import (
    PromptProvenance,
    PromptSegmentation,
    PromptStatus,
    UnifiedAnalysisResponse,
    WorkflowStatus,
)

EVIDENCE = "sha256:test-image"


def _finding(
    finding_id: str = "vision-1",
    label: str = "floodwater",
    description: str = "Observed: floodwater over the road.",
) -> Finding:
    return Finding(
        finding_id=finding_id,
        label=label,
        description=description,
        confidence=Confidence(value=0.8),
        evidence_refs=[
            EvidenceRef(
                evidence_id=EVIDENCE, modality="image", uri_or_hash=EVIDENCE
            )
        ],
    )


def _detection(object_id: str = "0") -> SegmentDetection:
    return SegmentDetection(
        object_id=object_id,
        box=SegmentBox(x1=10, y1=20, x2=30, y2=40),
        mask=SegmentMask(width=20, height=20, svg_path="M0 0Z", rle_counts="a"),
    )


def _segmentation(
    prompt: str = "road",
    status: PromptStatus = PromptStatus.OK,
    linked: list[str] | None = None,
    error: str | None = None,
    provenance: PromptProvenance = PromptProvenance.AUTOMATIC,
) -> PromptSegmentation:
    return PromptSegmentation(
        prompt=prompt,
        linked_finding_ids=["vision-1"] if linked is None else linked,
        status=status,
        error=error,
        detections=[_detection()] if status == PromptStatus.OK else [],
        provenance=provenance,
    )


def _vision(
    findings: list[Finding] | None = None,
    segmentations: list[PromptSegmentation] | None = None,
    status: WorkflowStatus = WorkflowStatus.COMPLETED,
) -> UnifiedAnalysisResponse:
    return UnifiedAnalysisResponse(
        incident_id="img-test",
        image=SegmentImageInfo(
            width=320, height=334, mime_type="image/png", evidence_id=EVIDENCE
        ),
        findings=[_finding()] if findings is None else findings,
        segmentations=[_segmentation()] if segmentations is None else segmentations,
        workflow_status=status,
        warnings=[],
    )


def _geo() -> GeoContext:
    return GeoContext(status=GeoStatus.UNAVAILABLE, note="none provided")


def _concern(**overrides) -> ExposureConcern:
    base = dict(
        concern_id="exp-1",
        condition="If the road is affected",
        concern="then access may be affected; severity is not confirmed",
        basis_finding_ids=["vision-1"],
        basis_evidence_ids=[EVIDENCE],
        verification_action_id="verify-exp-1",
    )
    base.update(overrides)
    return ExposureConcern(**base)


def _action(action_id: str = "verify-exp-1", **overrides) -> VerificationAction:
    base = dict(
        action_id=action_id,
        action="Verify.",
        reason="Unverified.",
        priority="high",
        what="Check.",
        why_operational="Matters.",
        unknown="Outcome.",
        priority_reason="Ranked.",
    )
    base.update(overrides)
    return VerificationAction(**base)


def _dossier(vision, impact_data, **overrides):
    payload = {
        "incident_id": vision.incident_id,
        "image": vision.image,
        "vision": vision,
        "impact_data": impact_data,
        "impact_error": None,
        "geo_context": _geo(),
        "trail": [],
    }
    payload.update(overrides)
    return ReportingAgent().run(payload).data["dossier"]


def _impact_data(vision, geo=None):
    return ImpactAgent().run(
        {
            "findings": list(vision.findings),
            "segmentations": list(vision.segmentations),
            "geo_context": geo or _geo(),
        }
    ).data


# --- material conclusions link to retained evidence ---


def test_concern_dangling_basis_rejected():
    actions = [_action()]
    assert (
        validate_exposure_concerns(
            [_concern()], actions, finding_ids={"vision-1"}, evidence_ids={EVIDENCE}
        )
        == []
    )
    assert (
        validate_exposure_concerns(
            [_concern(basis_finding_ids=["gone"])],
            actions,
            finding_ids={"vision-1"},
            evidence_ids={EVIDENCE},
        )
        != []
    )
    assert (
        validate_exposure_concerns(
            [_concern(basis_evidence_ids=["sha256:gone"])],
            actions,
            finding_ids={"vision-1"},
            evidence_ids={EVIDENCE},
        )
        != []
    )


def test_damage_requires_uncertainty_note_for_every_category():
    good = DamageAssessment(
        assessment_id="dmg-road",
        feature="road",
        basis_finding_ids=["vision-1"],
        basis_evidence_ids=[EVIDENCE],
        category=DamageCategory.POSSIBLE_DAMAGE,
        rationale="reason",
        uncertainty_note="Extent unconfirmed.",
    )
    assert validate_damage_assessments([good], {"vision-1"}) == []
    bare = good.model_copy(update={"uncertainty_note": ""})
    assert validate_damage_assessments([bare], {"vision-1"}) != []
    assert (
        validate_damage_assessments(
            [good.model_copy(update={"basis_evidence_ids": ["sha256:gone"]})],
            {"vision-1"},
            evidence_ids={EVIDENCE},
        )
        != []
    )


def test_damage_consistency_enforces_max_severity_and_disagreement_note():
    findings = [
        _finding("f1", "road", "Observed: road intact."),
        _finding("f2", "road", "Observed: road cracked."),
    ]
    severe = DamageAssessment(
        assessment_id="dmg-road",
        feature="road",
        basis_finding_ids=["f1", "f2"],
        basis_evidence_ids=[EVIDENCE],
        category=DamageCategory.POSSIBLE_DAMAGE,
        rationale="reason",
        uncertainty_note="Single image. Observations disagree about this feature.",
    )
    assert validate_damage_consistency([severe], findings) == []
    downgraded = severe.model_copy(
        update={"category": DamageCategory.CANNOT_ASSESS}
    )
    assert validate_damage_consistency([downgraded], findings) != []
    silent = severe.model_copy(update={"uncertainty_note": "Extent unconfirmed."})
    assert any(
        "disagreement" in e for e in validate_damage_consistency([silent], findings)
    )
    unmentioned = severe.model_copy(update={"feature": "vehicle"})
    assert validate_damage_consistency([unmentioned], findings) != []


def test_rescue_basis_must_resolve_to_retained_evidence():
    good = RescueAttention(
        attention_id="att-1",
        priority=RescuePriority.MEDIUM,
        basis_finding_ids=["vision-1"],
        basis_evidence_ids=[EVIDENCE],
        rationale="reason",
        unknowns="Whether anyone is at risk.",
    )
    assert (
        validate_rescue_priorities(
            [good], {"vision-1"}, evidence_ids={EVIDENCE}
        )
        == []
    )
    assert (
        validate_rescue_priorities(
            [good.model_copy(update={"basis_evidence_ids": ["sha256:gone"]})],
            {"vision-1"},
            evidence_ids={EVIDENCE},
        )
        != []
    )


# --- verification actions are explicit and grounded ---


def test_concern_review_requires_back_link_and_retained_concern():
    linked = _action(
        related_finding_ids=["vision-1"],
        kind="concern_review",
        concern_id="exp-1",
    )
    assert (
        validate_verification_actions(
            [linked],
            {"vision-1"},
            concern_action_ids={"verify-exp-1"},
            concern_ids={"exp-1"},
        )
        == []
    )
    assert (
        validate_verification_actions(
            [linked.model_copy(update={"concern_id": None})],
            {"vision-1"},
            concern_action_ids={"verify-exp-1"},
            concern_ids={"exp-1"},
        )
        != []
    )
    assert (
        validate_verification_actions(
            [linked],
            {"vision-1"},
            concern_action_ids=set(),
            concern_ids=set(),
        )
        != []
    )


def test_finding_reviews_need_a_basis_and_detail_fields():
    assert (
        validate_verification_actions(
            [_action(related_finding_ids=["vision-1"])], {"vision-1"}
        )
        == []
    )
    assert (
        validate_verification_actions([_action()], {"vision-1"}) != []
    )
    assert (
        validate_verification_actions(
            [
                _action(
                    related_finding_ids=["vision-1"],
                    what="",
                    kind="people_safety",
                )
            ],
            {"vision-1"},
        )
        != []
    )


def test_segmentation_review_names_its_prompt():
    review = _action(
        "verify-seg-road", kind="segmentation_review", prompt="road"
    )
    assert validate_verification_actions([review], {"vision-1"}) == []
    assert (
        validate_verification_actions(
            [review.model_copy(update={"prompt": None})], {"vision-1"}
        )
        != []
    )


def test_finding_independent_followups_need_no_basis():
    geo = _action("verify-geo-context", kind="geo_context")
    routine = _action("verify-routine", kind="routine")
    assert validate_verification_actions([geo, routine], {"vision-1"}) == []


def test_every_finding_needs_review_coverage():
    assert (
        validate_finding_review_coverage(
            {"vision-1"}, [_action(related_finding_ids=["vision-1"])]
        )
        == []
    )
    assert validate_finding_review_coverage({"vision-1"}, [_action()]) != []


def test_unmeasured_prompts_need_segmentation_reviews():
    failed = _segmentation("road", PromptStatus.FAILED, error="sam31_timeout: slow.")
    zero = _segmentation("river", PromptStatus.ZERO_MATCHES)
    ok = _segmentation("road")
    review = _action(
        "verify-seg-road", kind="segmentation_review", prompt="road"
    )
    assert validate_segmentation_coverage([failed], [review]) == []
    assert validate_segmentation_coverage([zero], []) != []
    assert validate_segmentation_coverage([failed], []) != []
    assert validate_segmentation_coverage([ok], []) == []
    # Segmentation-only OK outcome (no triggering finding): review only.
    lone = _segmentation("debris", PromptStatus.OK, linked=[])
    assert validate_segmentation_coverage([lone], []) != []
    lone_review = _action(
        "verify-seg-debris", kind="segmentation_review", prompt="debris"
    )
    assert validate_segmentation_coverage([lone], [lone_review]) == []


# --- SAM outcomes: provenance, status honesty, geometry ---


def test_segmentation_structure_and_geometry():
    ok = _segmentation()
    assert (
        validate_segmentations(
            [ok], width=320, height=334, finding_ids={"vision-1"}
        )
        == []
    )
    empty_ok = PromptSegmentation(
        prompt="road", linked_finding_ids=["vision-1"], status=PromptStatus.OK
    )
    assert validate_segmentations([empty_ok]) != []
    zero_with_detections = PromptSegmentation(
        prompt="road",
        linked_finding_ids=["vision-1"],
        status=PromptStatus.ZERO_MATCHES,
        detections=[_detection()],
    )
    assert validate_segmentations([zero_with_detections]) != []
    failed_silent = _segmentation("road", PromptStatus.FAILED, error=None)
    assert validate_segmentations([failed_silent]) != []
    ok_with_error = _segmentation("road", PromptStatus.OK, error="stale")
    assert validate_segmentations([ok_with_error]) != []
    dangling = _segmentation("road", PromptStatus.OK, linked=["gone"])
    assert (
        validate_segmentations([dangling], finding_ids={"vision-1"}) != []
    )
    oob = PromptSegmentation(
        prompt="road",
        linked_finding_ids=["vision-1"],
        status=PromptStatus.OK,
        detections=[
            SegmentDetection(
                object_id="0",
                box=SegmentBox(x1=0, y1=0, x2=9999, y2=9999),
                mask=SegmentMask(width=9999, height=9999),
            )
        ],
    )
    assert validate_segmentations([oob], width=320, height=334) != []
    # Detections are preserved verbatim — masks/boxes are never rewritten.
    assert ok.detections[0].mask.svg_path == "M0 0Z"
    assert (ok.detections[0].box.x2, ok.detections[0].box.y2) == (30, 40)


def test_workflow_status_must_match_prompt_mix():
    ok = _segmentation("road")
    failed = _segmentation("river", PromptStatus.FAILED, error="sam31_timeout: slow.")
    skipped = _segmentation("road", PromptStatus.SKIPPED, error="prompt_cap_exceeded")
    assert validate_workflow_status([ok], WorkflowStatus.COMPLETED) == []
    assert validate_workflow_status([ok, failed], WorkflowStatus.PARTIAL) == []
    assert validate_workflow_status([skipped], WorkflowStatus.VISION_ONLY) == []
    assert validate_workflow_status([], WorkflowStatus.VISION_ONLY) == []
    assert validate_workflow_status([ok], WorkflowStatus.PARTIAL) != []
    assert validate_workflow_status([failed], WorkflowStatus.COMPLETED) != []


def test_incident_status_never_completed_on_failure():
    failed_trail = [
        AgentTrailEntry(
            agent="impact", status=AgentStepStatus.FAILED, notes="impact_failed"
        )
    ]
    assert (
        validate_incident_status(IncidentStatus.PARTIAL, failed_trail) == []
    )
    assert (
        validate_incident_status(IncidentStatus.COMPLETED, failed_trail) != []
    )
    assert validate_incident_status(IncidentStatus.COMPLETED, []) == []
    assert (
        validate_incident_status(
            IncidentStatus.PARTIAL, [], impact_failed=True
        )
        == []
    )
    assert (
        validate_incident_status(
            IncidentStatus.COMPLETED, [], impact_failed=True
        )
        != []
    )


# --- reporting: orphans, coverage, degraded flags ---


def test_rejected_concern_leaves_no_orphan_action():
    vision = _vision()
    data = _impact_data(vision)
    data["exposure_concerns"].append(
        _concern(
            concern_id="exp-bad",
            condition="The road is blocked",
            concern="Access is cut off",
            verification_action_id="verify-exp-bad",
        )
    )
    data["verification_actions"].append(_action("verify-exp-bad"))
    dossier = _dossier(vision, data)
    assert "exp-bad" not in [c.concern_id for c in dossier.exposure_concerns]
    assert "verify-exp-bad" not in [
        a.action_id for a in dossier.verification_actions
    ]
    assert any("rejected_concern:exp-bad" in w for w in dossier.warnings)
    assert any("orphan_action_dropped:verify-exp-bad" in w for w in dossier.warnings)
    assert "exposure_concerns" in dossier.degraded_sections


def test_orphan_pruning_restores_finding_coverage():
    vision = _vision()
    data = _impact_data(vision)
    # Drop every finding-grounded action except one concern review,
    # then reject that concern: the finding must still end up covered.
    concern = next(
        c for c in data["exposure_concerns"] if len(c.basis_finding_ids) == 1
    )
    merged = next(
        a
        for a in data["verification_actions"]
        if a.action_id == concern.verification_action_id
    )
    data["verification_actions"] = [merged]
    concern.condition = "The road is blocked"
    concern.concern = "Access is cut off"
    dossier = _dossier(vision, data)
    assert validate_finding_review_coverage(
        {"vision-1"}, dossier.verification_actions
    ) == []
    assert any(
        "review_coverage_restored:vision-1" in w for w in dossier.warnings
    )


def test_orphan_helper_keeps_shared_actions():
    actions = [_action("verify-exp-1"), _action("verify-exp-9")]
    assert (
        orphaned_concern_action_ids(
            actions, {"verify-exp-1", "verify-exp-9"}, {"verify-exp-1"}
        )
        == {"verify-exp-9"}
    )


def test_clean_dossier_has_no_degraded_sections():
    vision = _vision()
    dossier = _dossier(vision, _impact_data(vision))
    assert dossier.incident_status == IncidentStatus.COMPLETED
    assert dossier.degraded_sections == []
    assert dossier.segmentation_summary[0].provenance == PromptProvenance.AUTOMATIC


def test_impact_failure_is_partial_with_degraded_flag():
    vision = _vision()
    dossier = _dossier(
        vision,
        None,
        impact_error="impact_failed: RuntimeError.",
        trail=[
            AgentTrailEntry(agent="vision", status=AgentStepStatus.OK),
            AgentTrailEntry(agent="impact", status=AgentStepStatus.FAILED),
        ],
    )
    assert dossier.incident_status == IncidentStatus.PARTIAL
    assert "impact" in dossier.degraded_sections


def test_segmentation_only_observation_yields_review_not_concern():
    finding = _finding(label="smoke", description="Observed: smoke in the distance.")
    vision = _vision(
        findings=[finding],
        segmentations=[
            _segmentation(
                "debris",
                PromptStatus.OK,
                linked=[],
                provenance=PromptProvenance.USER_REQUESTED,
            )
        ],
        status=WorkflowStatus.COMPLETED,
    )
    result = ImpactAgent().run(
        {
            "findings": [finding],
            "segmentations": list(vision.segmentations),
            "geo_context": _geo(),
        }
    )
    assert result.data["exposure_concerns"] == []
    reviews = [
        a
        for a in result.data["verification_actions"]
        if a.kind == "segmentation_review"
    ]
    assert [a.prompt for a in reviews] == ["debris"]
    assert "operator-requested" in reviews[0].reason
    dossier = _dossier(vision, dict(result.data))
    assert validate_segmentation_coverage(
        list(vision.segmentations), dossier.verification_actions
    ) == []


def test_cached_evidence_with_bad_geometry_is_rejected():
    vision = _vision()
    vision.segmentations[0].linked_finding_ids = ["gone"]
    with pytest.raises(SentinelError) as exc_info:
        Orchestrator().run_workflow_from_vision(
            "disaster_response", vision, _geo(), "anl_test"
        )
    assert exc_info.value.code == "cached_evidence_invalid"
    vision = _vision(status=WorkflowStatus.PARTIAL)
    with pytest.raises(SentinelError) as exc_info:
        Orchestrator().run_workflow_from_vision(
            "disaster_response", vision, _geo(), "anl_test"
        )
    assert exc_info.value.code == "cached_evidence_invalid"
