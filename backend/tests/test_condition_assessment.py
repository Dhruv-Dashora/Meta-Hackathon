"""Condition-assessment tests: damage grounding + rescue-attention safety.

Deterministic text analysis only — no model clients involved.
"""

from app.agents.condition_assessment import damage_assessments, rescue_priorities
from app.agents.impact_agent import ImpactAgent
from app.agents.reporting_agent import ReportingAgent
from app.orchestrator.validators import (
    validate_damage_assessments,
    validate_rescue_priorities,
)
from app.schemas.common import Confidence, EvidenceRef, Finding
from app.schemas.incident import (
    DamageAssessment,
    DamageCategory,
    GeoContext,
    GeoStatus,
    RescueAttention,
    RescuePriority,
)

EVIDENCE = "sha256:test-image"


def _finding(
    finding_id: str = "vision-1",
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


def _geo_unavailable() -> GeoContext:
    return GeoContext(status=GeoStatus.UNAVAILABLE, note="none provided")


def _category_for(description: str, family: str) -> DamageAssessment:
    assessments, _ = damage_assessments([_finding(description=description)])
    matches = [a for a in assessments if a.feature == family]
    assert len(matches) == 1
    return matches[0]


# --- damage: positive / negative / uncertain / unrelated ---


def test_damage_strong_cue_is_apparent_major():
    assessment = _category_for("Observed: building collapsed.", "building")
    assert assessment.category == DamageCategory.APPARENT_MAJOR_DAMAGE
    assert assessment.provisional is True
    assert assessment.basis_finding_ids == ["vision-1"]
    assert assessment.basis_evidence_ids == [EVIDENCE]
    assert "collapsed" in assessment.rationale
    assert "not an engineering finding" in assessment.rationale


def test_damage_moderate_cue_is_possible():
    assessment = _category_for("Observed: road cracked.", "road")
    assert assessment.category == DamageCategory.POSSIBLE_DAMAGE
    assert "cracked" in assessment.rationale
    assert "road" in assessment.rationale


def test_damage_negation_is_no_visible_damage_not_possible():
    assessment = _category_for(
        "Observed: no visible collapse of the building.", "building"
    )
    assert assessment.category == DamageCategory.NO_VISIBLE_DAMAGE
    assert "not confirmed structural safety" in assessment.uncertainty_note


def test_damage_uncertainty_downgrades_strong_cue():
    assessment = _category_for("Observed: possibly collapsed building.", "building")
    assert assessment.category == DamageCategory.POSSIBLE_DAMAGE
    assert "uncertain wording" in assessment.rationale


def test_damage_cue_in_other_clause_is_not_linked():
    assessment = _category_for(
        "Observed: rubble in the field. The road looks fine.", "road"
    )
    assert assessment.category == DamageCategory.CANNOT_ASSESS


def test_damage_unrelated_feature_yields_no_assessment():
    assessments, _ = damage_assessments(
        [_finding(description="Observed: debris on the hillside.")]
    )
    assert assessments == []


def test_damage_feature_without_detail_is_cannot_assess():
    assessment = _category_for("Observed: road.", "road")
    assert assessment.category == DamageCategory.CANNOT_ASSESS
    # Provenance stays structured: the id backs the read but never
    # appears in the narrative prose.
    assert "vision-1" not in assessment.rationale
    assert assessment.basis_finding_ids == ["vision-1"]


def test_damage_conflicting_observations_keep_severe_with_note():
    assessments, _ = damage_assessments(
        [
            _finding("f1", "road", "Observed: road intact."),
            _finding("f2", "road", "Observed: road cracked."),
        ]
    )
    assert len(assessments) == 1
    assessment = assessments[0]
    assert assessment.category == DamageCategory.POSSIBLE_DAMAGE
    assert assessment.basis_finding_ids == ["f1", "f2"]
    assert "disagree" in assessment.uncertainty_note


def test_damage_no_findings_no_assessments():
    assessments, notes = damage_assessments([])
    assert assessments == []
    assert notes == []


def test_damage_validators():
    good = _category_for("Observed: road cracked.", "road")
    assert validate_damage_assessments([good], {"vision-1"}) == []
    missing_basis = DamageAssessment(
        assessment_id="dmg-x",
        feature="road",
        category=DamageCategory.POSSIBLE_DAMAGE,
        rationale="reason",
    )
    assert validate_damage_assessments([missing_basis], {"vision-1"}) != []
    unsafe_all_clear = DamageAssessment(
        assessment_id="dmg-y",
        feature="road",
        basis_finding_ids=["vision-1"],
        basis_evidence_ids=[EVIDENCE],
        category=DamageCategory.NO_VISIBLE_DAMAGE,
        rationale="reason",
        uncertainty_note="",
    )
    errors = validate_damage_assessments([unsafe_all_clear], {"vision-1"})
    assert any("not-safe" in e for e in errors)


# --- rescue-attention safety ---


def _priority_for(description: str) -> RescueAttention:
    ranked, _ = rescue_priorities([_finding(description=description)])
    assert len(ranked) == 1
    return ranked[0]


def test_rescue_explicit_danger_is_high():
    attention = _priority_for("Observed: person trapped under debris.")
    assert attention.priority == RescuePriority.HIGH
    assert attention.requires_human_review is True
    assert attention.basis_finding_ids == ["vision-1"]
    assert "urgent authorized human assessment" in attention.rationale


def test_rescue_cooccurrence_is_never_high():
    attention = _priority_for("Observed: people near the river bank.")
    assert attention.priority == RescuePriority.LOW
    assert "no danger" in attention.rationale
    assert attention.unknowns.strip() != ""


def test_rescue_hedged_danger_is_medium_not_high():
    attention = _priority_for("Observed: person possibly trapped under debris.")
    assert attention.priority == RescuePriority.MEDIUM
    assert "hedges" in attention.rationale


def test_rescue_negated_danger_is_not_high():
    attention = _priority_for("Observed: no one trapped in the vehicle.")
    assert attention.priority != RescuePriority.HIGH
    assert "urgent" not in attention.rationale


def test_rescue_danger_without_person_is_undetermined():
    attention = _priority_for("Observed: vehicle trapped in mud.")
    assert attention.priority == RescuePriority.UNDETERMINED
    assert "no person" in attention.rationale


def test_rescue_access_question_is_undetermined_not_rescue():
    attention = _priority_for("Observed: road blocked by landslide.")
    assert attention.priority == RescuePriority.UNDETERMINED
    assert "no person" in attention.rationale.lower()


def test_rescue_clauses_do_not_combine_people_and_danger():
    attention = _priority_for(
        "Observed: people in the shelter. The river flooded the road."
    )
    assert attention.priority == RescuePriority.LOW
    assert "exposure" not in attention.rationale


def test_rescue_quiet_observation_without_person_is_undetermined():
    attention = _priority_for("Observed: road clear and intact.")
    assert attention.priority == RescuePriority.UNDETERMINED


def test_rescue_vacuous_finding_is_undetermined():
    ranked, _ = rescue_priorities([_finding("f1", "x", "")])
    assert ranked[0].priority == RescuePriority.UNDETERMINED


def test_rescue_no_findings_is_single_undetermined():
    ranked, notes = rescue_priorities([])
    assert len(ranked) == 1
    assert ranked[0].priority == RescuePriority.UNDETERMINED
    assert ranked[0].basis_finding_ids == []
    assert notes == []


def test_rescue_never_infers_victimhood_or_proximity():
    for description in (
        "Observed: people near the river bank.",
        "Observed: vehicle trapped in mud.",
        "Observed: road blocked by landslide.",
        "Observed: people in the shelter. The river flooded the road.",
    ):
        rationale = _priority_for(description).rationale.lower()
        assert "victim" not in rationale
        assert "entrapment" not in rationale
        assert "proximity" not in rationale
        assert "casualt" not in rationale


def test_rescue_validators():
    good = _priority_for("Observed: person trapped under debris.")
    assert validate_rescue_priorities([good], {"vision-1"}) == []
    baseless_high = RescueAttention(
        attention_id="att-x", priority=RescuePriority.HIGH, rationale="reason"
    )
    errors = validate_rescue_priorities([baseless_high], {"vision-1"})
    assert any("only undetermined may lack a basis" in e for e in errors)


# --- impact + reporting integration ---


def test_impact_returns_damage_and_rescue():
    result = ImpactAgent().run(
        {
            "findings": [
                _finding("f1", "scene", "Observed: road cracked."),
                _finding("f2", "crowd", "Observed: people near the river."),
            ],
            "segmentations": [],
            "geo_context": _geo_unavailable(),
        }
    )
    damage = {d.feature: d.category for d in result.data["damage_assessments"]}
    assert damage == {"road": DamageCategory.POSSIBLE_DAMAGE}
    rescue = {r.basis_finding_ids[0]: r.priority for r in result.data["rescue_priorities"]}
    assert rescue == {
        "f1": RescuePriority.UNDETERMINED,
        "f2": RescuePriority.LOW,
    }
    access = {a.basis_finding_ids[0]: a.priority for a in result.data["access_priorities"]}
    assert access["f1"] == RescuePriority.MEDIUM
    assert access["f2"] == RescuePriority.UNDETERMINED
    review = {r.basis_finding_ids[0]: r.priority for r in result.data["review_priorities"]}
    assert review["f1"] == RescuePriority.MEDIUM
    assert review["f2"] == RescuePriority.MEDIUM


def test_dossier_carries_validated_damage_and_rescue():
    from app.schemas.segmentation import SegmentImageInfo
    from app.schemas.unified_analysis import UnifiedAnalysisResponse, WorkflowStatus

    finding = _finding()
    vision = UnifiedAnalysisResponse(
        incident_id="img-test",
        image=SegmentImageInfo(
            width=320, height=334, mime_type="image/png", evidence_id=EVIDENCE
        ),
        findings=[finding],
        workflow_status=WorkflowStatus.VISION_ONLY,
    )
    impact_data = dict(
        ImpactAgent().run(
            {
                "findings": [finding],
                "segmentations": [],
                "geo_context": _geo_unavailable(),
            }
        ).data
    )
    impact_data["damage_assessments"] = list(impact_data["damage_assessments"]) + [
        DamageAssessment(
            assessment_id="dmg-bogus",
            feature="road",
            basis_finding_ids=["no-such-finding"],
            basis_evidence_ids=[EVIDENCE],
            category=DamageCategory.POSSIBLE_DAMAGE,
            rationale="fabricated",
        )
    ]
    result = ReportingAgent().run(
        {
            "incident_id": vision.incident_id,
            "image": vision.image,
            "vision": vision,
            "impact_data": impact_data,
            "impact_error": None,
            "geo_context": _geo_unavailable(),
            "trail": [],
        }
    )
    dossier = result.data["dossier"]
    assert "dmg-bogus" not in {d.assessment_id for d in dossier.damage_assessments}
    assert any("invalid_damage" in w for w in dossier.warnings)
    assert dossier.rescue_priorities != []


def test_dossier_degraded_path_has_empty_condition_sections():
    from app.schemas.segmentation import SegmentImageInfo
    from app.schemas.unified_analysis import UnifiedAnalysisResponse, WorkflowStatus

    vision = UnifiedAnalysisResponse(
        incident_id="img-test",
        image=SegmentImageInfo(
            width=320, height=334, mime_type="image/png", evidence_id=EVIDENCE
        ),
        findings=[_finding()],
        workflow_status=WorkflowStatus.VISION_ONLY,
    )
    result = ReportingAgent().run(
        {
            "incident_id": vision.incident_id,
            "image": vision.image,
            "vision": vision,
            "impact_data": None,
            "impact_error": "impact_failed: RuntimeError.",
            "geo_context": _geo_unavailable(),
            "trail": [],
        }
    )
    dossier = result.data["dossier"]
    assert dossier.damage_assessments == []
    assert dossier.rescue_priorities == []


def test_headline_is_plain_language():
    from app.schemas.segmentation import SegmentImageInfo
    from app.schemas.unified_analysis import UnifiedAnalysisResponse, WorkflowStatus

    vision = UnifiedAnalysisResponse(
        incident_id="img-test",
        image=SegmentImageInfo(
            width=320, height=334, mime_type="image/png", evidence_id=EVIDENCE
        ),
        findings=[
            _finding("f1", "floodwater", "Observed: floodwater."),
            _finding("f2", "smoke", "Observed: smoke."),
        ],
        workflow_status=WorkflowStatus.VISION_ONLY,
    )
    impact_data = dict(
        ImpactAgent().run(
            {
                "findings": list(vision.findings),
                "segmentations": [],
                "geo_context": _geo_unavailable(),
            }
        ).data
    )
    result = ReportingAgent().run(
        {
            "incident_id": vision.incident_id,
            "image": vision.image,
            "vision": vision,
            "impact_data": impact_data,
            "impact_error": None,
            "geo_context": _geo_unavailable(),
            "trail": [],
        }
    )
    headline = result.data["dossier"].situation_summary.headline
    assert headline == (
        "Possible flooding (floodwater); water extent unconfirmed. "
        "Further observations need review."
    )
    assert "finding(s)" not in headline
