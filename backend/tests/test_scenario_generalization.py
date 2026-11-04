"""Cross-scenario generalization tests (no model calls, no demo data).

Synthetic observations exercise the pipeline's general behavior across
scene types: inferred text never grounds a read, fire is a first-class
hazard, visible components select segmentation candidates, inundation
never reads as structural damage, people-safety stays separate from
damage, SAM non-measurement never means absence, and abstention wins
when evidence is missing.
"""

from app.agents.condition_assessment import (
    access_priorities,
    damage_assessments,
    rescue_priorities,
)
from app.agents.impact_agent import ImpactAgent
from app.agents.report_content import hazard_gaps, scene_headline
from app.agents.reporting_agent import ReportingAgent
from app.orchestrator.validators import (
    validate_damage_assessments,
    validate_damage_consistency,
)
from app.schemas.common import Confidence, EvidenceRef, Finding
from app.schemas.incident import (
    DamageCategory,
    GeoContext,
    GeoStatus,
    HazardCategory,
    RescuePriority,
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
from app.services.prompt_planner import plan_sam_prompts

EVIDENCE = "sha256:scenario-image"


def _finding(
    finding_id: str = "f1",
    label: str = "scene",
    description: str = "Observed: scene.",
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


def _geo() -> GeoContext:
    return GeoContext(status=GeoStatus.UNAVAILABLE, note="none provided")


def _impact(findings, segmentations=None):
    return ImpactAgent().run(
        {
            "findings": findings,
            "segmentations": segmentations or [],
            "geo_context": _geo(),
        }
    ).data


def _damage_for(description: str, family: str):
    assessments, _ = damage_assessments([_finding(description=description)])
    matches = [a for a in assessments if a.feature == family]
    assert len(matches) == 1
    return matches[0]


# --- inferred text is never evidence (planner parity) ---


def test_inferred_impact_never_grounds_damage_or_priorities():
    finding = _finding(
        description=(
            "Observed: clear field.\n"
            "Inferred impact: the building may collapse."
        )
    )
    assessments, _ = damage_assessments([finding])
    assert assessments == []
    rescue, _ = rescue_priorities([finding])
    assert rescue[0].priority == RescuePriority.UNDETERMINED
    access, _ = access_priorities([finding])
    assert access[0].priority == RescuePriority.UNDETERMINED
    data = _impact([finding])
    assert data["damage_assessments"] == []
    assert data["exposure_concerns"] == []


def test_inferred_people_danger_never_raises_rescue():
    finding = _finding(
        "f1",
        "field",
        "Observed: clear field.\n"
        "Inferred impact: people may be trapped under debris.",
    )
    rescue, _ = rescue_priorities([finding])
    assert rescue[0].priority == RescuePriority.UNDETERMINED
    data = _impact([finding])
    people = [c for c in data["exposure_concerns"] if c.feature == "people"]
    assert people == []


# --- fire is a first-class hazard ---


def test_fire_building_reads_as_possible_damage():
    assessment = _damage_for("Observed: building on fire.", "building")
    assert assessment.category == DamageCategory.POSSIBLE_DAMAGE
    assert assessment.condition_class == "visible_damage"
    data = _impact([_finding(description="Observed: building on fire.")])
    (hazard,) = data["observed_hazards"]
    assert hazard.category == HazardCategory.VISIBLE_DAMAGE
    headline = scene_headline([_finding(description="Observed: building on fire.")])
    assert "fire" in headline.lower()
    assert "debris" not in headline.lower()
    topics = [topic for topic, *_ in hazard_gaps(
        [_finding(description="Observed: building on fire.")]
    )]
    assert "fire_conditions" in topics


def test_people_near_fire_need_review_not_rescue_claims():
    finding = _finding(description="Observed: people near the burning building.")
    rescue, _ = rescue_priorities([finding])
    assert rescue[0].priority == RescuePriority.MEDIUM


# --- visible components select segmentation candidates ---


def test_roof_only_observation_yields_building_prompt():
    finding = _finding(
        "f1", "rooftops", "Observed: rooftops visible above the water."
    )
    prompts = [d.prompt for d in plan_sam_prompts([finding])]
    assert "building" in prompts
    # The SAM prompt itself is never rewritten to the component noun.
    assert "roof" not in prompts
    assert "rooftops" not in prompts


def test_building_observation_still_prompts_building():
    finding = _finding(description="Observed: building beside the road.")
    prompts = [d.prompt for d in plan_sam_prompts([finding])]
    assert "building" in prompts


def test_road_and_bridge_prompts_stay_distinct():
    findings = [
        _finding("f1", "road", "Observed: road blocked by debris."),
        _finding("f2", "bridge", "Observed: bridge cracked."),
    ]
    prompts = {d.prompt for d in plan_sam_prompts(findings)}
    # Road and bridge stay distinct candidates (the observed debris is
    # itself a legitimate additional target).
    assert {"road", "bridge"} <= prompts


# --- inundation, burial, obstruction never read as collapse ---


def test_flooded_settlement_mixed_buildings_keep_conflict_explicit():
    findings = [
        _finding("f1", "building", "Observed: building collapsed."),
        _finding("f2", "building", "Observed: building intact."),
        _finding("f3", "houses", "Observed: houses flooded."),
    ]
    assessments, _ = damage_assessments(findings)
    assert len(assessments) == 1
    assessment = assessments[0]
    assert assessment.category == DamageCategory.APPARENT_MAJOR_DAMAGE
    assert assessment.basis_finding_ids == ["f1", "f2", "f3"]
    assert "disagree" in assessment.uncertainty_note
    assert validate_damage_consistency(assessments, findings) == []


def test_buildings_in_water_without_damage_stay_unproven_not_damaged():
    assessment = _damage_for(
        "Observed: water surrounds the buildings. "
        "No visible damage to the buildings.",
        "building",
    )
    assert assessment.category == DamageCategory.NO_VISIBLE_DAMAGE
    pure = _damage_for("Observed: houses flooded.", "building")
    assert pure.category == DamageCategory.POSSIBLE_DAMAGE
    assert pure.condition_class == "inundation"
    assert "does not establish structural damage" in pure.uncertainty_note


def test_partly_buried_structure_is_cover_not_structural_claim():
    assessment = _damage_for(
        "Observed: house partly buried under debris.", "building"
    )
    assert assessment.category == DamageCategory.POSSIBLE_DAMAGE
    assert assessment.condition_class == "surrounding_material"
    assert "does not establish structural damage" in (
        assessment.uncertainty_note + assessment.recommended_verification
    )


def test_debris_road_obstruction_keeps_access_separate_from_damage():
    data = _impact(
        [_finding("f1", "road", "Observed: road blocked by debris.")]
    )
    (assessment,) = data["damage_assessments"]
    assert assessment.category == DamageCategory.POSSIBLE_DAMAGE
    assert assessment.condition_class == "surrounding_material"
    access = {a.basis_finding_ids[0]: a for a in data["access_priorities"]}
    assert access["f1"].priority == RescuePriority.HIGH
    rescue = {r.basis_finding_ids[0]: r for r in data["rescue_priorities"]}
    assert rescue["f1"].priority == RescuePriority.UNDETERMINED


# --- people safety levels ---


def test_people_with_and_without_danger_get_distinct_attention():
    danger = _impact(
        [_finding("f1", "people", "Observed: person trapped under debris.")]
    )
    calm = _impact(
        [_finding("f1", "people", "Observed: people standing in the square.")]
    )
    assert danger["rescue_priorities"][0].priority == RescuePriority.HIGH
    assert calm["rescue_priorities"][0].priority == RescuePriority.LOW
    # Damage reads never absorb people evidence either way.
    assert danger["damage_assessments"] == []
    assert calm["damage_assessments"] == []


# --- abstention ---


def test_hazard_without_infrastructure_yields_no_damage_read():
    data = _impact(
        [_finding("f1", "floodwater", "Observed: floodwater over open ground.")]
    )
    assert data["damage_assessments"] == []
    assert any(c.feature == "river" for c in data["exposure_concerns"])


def test_normal_scene_abstains_everywhere():
    finding = _finding("f1", "meadow", "Observed: green meadow under clear sky.")
    data = _impact([finding])
    assert data["damage_assessments"] == []
    assert data["exposure_concerns"] == []
    assert data["rescue_priorities"][0].priority == RescuePriority.UNDETERMINED
    assert plan_sam_prompts([finding]) == []


def test_negated_infrastructure_selects_nothing():
    finding = _finding(description="Observed: no buildings visible.")
    assessments, _ = damage_assessments([finding])
    assert assessments == []
    assert plan_sam_prompts([finding]) == []


def test_smoke_alone_is_not_a_damage_read():
    finding = _finding(description="Observed: smoke over the ridge.")
    assessments, _ = damage_assessments([finding])
    assert assessments == []


# --- SAM outcomes never imply absence ---


def _detection() -> SegmentDetection:
    return SegmentDetection(
        object_id="obj-1",
        box=SegmentBox(x1=0, y1=0, x2=10, y2=10),
        mask=SegmentMask(width=10, height=10),
    )


def _dossier(findings, segmentations, workflow_status):
    vision = UnifiedAnalysisResponse(
        incident_id="img-scenario",
        image=SegmentImageInfo(
            width=320, height=334, mime_type="image/png", evidence_id=EVIDENCE
        ),
        findings=findings,
        segmentations=segmentations,
        workflow_status=workflow_status,
    )
    impact_data = dict(
        ImpactAgent().run(
            {
                "findings": list(findings),
                "segmentations": list(segmentations),
                "geo_context": _geo(),
            }
        ).data
    )
    return ReportingAgent().run(
        {
            "incident_id": vision.incident_id,
            "image": vision.image,
            "vision": vision,
            "impact_data": impact_data,
            "impact_error": None,
            "geo_context": _geo(),
            "trail": [],
        }
    ).data["dossier"]


def test_sam_zero_match_and_failure_preserve_visual_evidence():
    finding = _finding("f1", "road", "Observed: road flooded.")
    segmentations = [
        PromptSegmentation(
            prompt="road",
            linked_finding_ids=["f1"],
            status=PromptStatus.ZERO_MATCHES,
        ),
        PromptSegmentation(
            prompt="river",
            linked_finding_ids=[],
            status=PromptStatus.FAILED,
            error="sam_timeout",
        ),
    ]
    dossier = _dossier([finding], segmentations, WorkflowStatus.PARTIAL)
    assert dossier.findings == [finding]
    (assessment,) = dossier.damage_assessments
    assert assessment.category == DamageCategory.POSSIBLE_DAMAGE
    assert assessment.condition_class == "inundation"
    assert validate_damage_assessments(
        dossier.damage_assessments, {"f1"}, evidence_ids={EVIDENCE}
    ) == []
    concern_text = " ".join(
        f"{c.condition} {c.concern}" for c in dossier.exposure_concerns
    )
    assert "matched nothing; this does not mean" in concern_text
    # Partial workflow never masquerades as a completed full analysis.
    assert dossier.vision_workflow_status == WorkflowStatus.PARTIAL


def test_grouped_sam_concern_retains_every_supporting_finding():
    findings = [
        _finding("f1", "road", "Observed: road flooded near the market."),
        _finding("f2", "road", "Observed: road submerged by the bridge."),
    ]
    segmentations = [
        PromptSegmentation(
            prompt="road",
            linked_finding_ids=["f1", "f2"],
            status=PromptStatus.OK,
            detections=[_detection()],
        )
    ]
    data = _impact(findings, segmentations)
    grouped = [
        c for c in data["exposure_concerns"] if len(c.basis_finding_ids) == 2
    ]
    assert len(grouped) == 1
    assert set(grouped[0].basis_finding_ids) == {"f1", "f2"}
    (action,) = [
        a
        for a in data["verification_actions"]
        if a.action_id == grouped[0].verification_action_id
    ]
    assert set(action.related_finding_ids) == {"f1", "f2"}
    assert "Grouped review" in action.reason
