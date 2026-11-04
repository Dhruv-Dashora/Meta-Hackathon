"""Cross-scenario robustness matrix (mocked vision — never calls live APIs).

Sixteen end-to-end incident scenarios through the deterministic
impact + reporting pipeline, asserting shared INVARIANTS rather than
exact wording: concern/action validity, grounded rescue escalation,
unknown exposure never defaulting to low, supported damage classes,
resolving ids, explicit uncertainty on conflicts, deterministic
ordering, adaptive sections, empty handling, single model-pass
counters, and complete/valid JSON.
"""

from __future__ import annotations

import hashlib
import io
import json
from collections import Counter

import pytest
from PIL import Image

from app.agents.base import AgentResult
from app.agents.condition_assessment import finding_mentions_person
from app.agents.impact_agent import ImpactAgent
from app.agents.report_content import people_in_danger
from app.agents.reporting_agent import ReportingAgent
from app.core.errors import SentinelError
from app.orchestrator import orchestrator as orch_module
from app.orchestrator.orchestrator import Orchestrator
from app.orchestrator.validators import (
    ASSESSABLE_FEATURES,
    CONDITIONAL_MARKERS,
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
    validate_segmentations,
    validate_verification_actions,
    validate_workflow_status,
)
from app.schemas.common import Confidence, EvidenceRef, Finding
from app.schemas.incident import (
    DamageCategory,
    GeoContext,
    GeoStatus,
    HazardCategory,
    IncidentDossier,
    IncidentStatus,
    RescuePriority,
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
from app.services import media_service
from app.services.sam31_client import (
    Sam31Box,
    Sam31Detection,
    Sam31Mask,
    Sam31Result,
)
from app.services.unified_service import run_unified_analysis

EVIDENCE = "sha256:test-image"
WIDTH, HEIGHT = 320, 334

_FABRICATED_TERMS = (
    "casualt",
    "victim",
    "fatalit",
    "deceased",
    "body count",
    "deploy",
    "dispatch",
)

_REQUIRED_DOSSIER_KEYS = frozenset(
    {
        "incident_id",
        "image",
        "vision_workflow_status",
        "incident_status",
        "situation_summary",
        "findings",
        "finding_groups",
        "information_gaps",
        "segmentation_summary",
        "segmentations",
        "observed_hazards",
        "exposure_concerns",
        "damage_assessments",
        "rescue_priorities",
        "access_priorities",
        "review_priorities",
        "geo_context",
        "uncertainty_notes",
        "verification_actions",
        "evidence_ledger",
        "agent_trail",
        "warnings",
        "degraded_sections",
    }
)


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


def _expected_workflow(
    segmentations: list[PromptSegmentation],
) -> WorkflowStatus:
    attempted = [
        s
        for s in segmentations
        if s.status
        in (PromptStatus.OK, PromptStatus.ZERO_MATCHES, PromptStatus.FAILED)
    ]
    if not attempted:
        return WorkflowStatus.VISION_ONLY
    if all(
        s.status in (PromptStatus.OK, PromptStatus.ZERO_MATCHES)
        for s in attempted
    ) and len(attempted) == len(segmentations):
        return WorkflowStatus.COMPLETED
    return WorkflowStatus.PARTIAL


def _vision(
    findings: list[Finding],
    segmentations: list[PromptSegmentation],
) -> UnifiedAnalysisResponse:
    return UnifiedAnalysisResponse(
        incident_id="img-matrix",
        image=SegmentImageInfo(
            width=WIDTH,
            height=HEIGHT,
            mime_type="image/png",
            evidence_id=EVIDENCE,
        ),
        findings=findings,
        prompt_plan=[],
        segmentations=segmentations,
        workflow_status=_expected_workflow(segmentations),
        warnings=[],
    )


def _geo_unavailable() -> GeoContext:
    return GeoContext(status=GeoStatus.UNAVAILABLE, note="none provided")


def _geo_provided() -> GeoContext:
    return GeoContext(
        status=GeoStatus.PROVIDED,
        location_label="Rasuwa corridor",
        latitude=28.2,
        longitude=85.6,
        note="operator test context",
    )


def _pipeline(
    vision: UnifiedAnalysisResponse,
    geo: GeoContext,
    impact_error: str | None = None,
) -> IncidentDossier:
    """Run the deterministic impact + reporting stages (no model calls)."""
    impact_data: dict | None = None
    if impact_error is None:
        impact_result = ImpactAgent().run(
            {
                "findings": list(vision.findings),
                "segmentations": list(vision.segmentations),
                "geo_context": geo,
            }
        )
        impact_data = dict(impact_result.data)
        # Mirror the orchestrator: impact notes (caps) ride vision warnings.
        vision.warnings.extend(impact_result.errors)
    return ReportingAgent().run(
        {
            "incident_id": vision.incident_id,
            "image": vision.image,
            "vision": vision,
            "impact_data": impact_data,
            "impact_error": impact_error,
            "geo_context": geo,
            "trail": [],
        }
    ).data["dossier"]


def _cited_evidence(
    vision: UnifiedAnalysisResponse, dossier: IncidentDossier
) -> list[str]:
    cited = [ref.evidence_id for f in vision.findings for ref in f.evidence_refs]
    for concern in dossier.exposure_concerns:
        cited.extend(concern.basis_evidence_ids)
    for assessment in dossier.damage_assessments:
        cited.extend(assessment.basis_evidence_ids)
    for attention in dossier.rescue_priorities:
        cited.extend(attention.basis_evidence_ids)
    for attention in dossier.access_priorities:
        cited.extend(attention.basis_evidence_ids)
    for item in dossier.review_priorities:
        cited.extend(item.basis_evidence_ids)
    return cited


def assert_global_invariants(
    dossier: IncidentDossier,
    vision: UnifiedAnalysisResponse,
    *,
    impact_failed: bool = False,
) -> None:
    """Shared invariant harness applied to every matrix scenario."""
    finding_ids = {f.finding_id for f in vision.findings}
    ledger_ids = {e.evidence_id for e in dossier.evidence_ledger}
    by_id = {f.finding_id: f for f in vision.findings}
    actions = {a.action_id: a for a in dossier.verification_actions}

    # Validator contracts all hold on the retained dossier.
    assert validate_findings(list(vision.findings)) == []
    assert (
        validate_exposure_concerns(
            dossier.exposure_concerns,
            dossier.verification_actions,
            finding_ids=finding_ids,
            evidence_ids=ledger_ids,
        )
        == []
    )
    assert validate_observed_hazards(dossier.observed_hazards, finding_ids) == []
    assert (
        validate_damage_assessments(
            dossier.damage_assessments, finding_ids, evidence_ids=ledger_ids
        )
        == []
    )
    assert (
        validate_damage_consistency(
            dossier.damage_assessments, list(vision.findings)
        )
        == []
    )
    assert (
        validate_rescue_priorities(
            dossier.rescue_priorities, finding_ids, evidence_ids=ledger_ids
        )
        == []
    )
    assert (
        validate_access_priorities(
            dossier.access_priorities, finding_ids, evidence_ids=ledger_ids
        )
        == []
    )
    assert (
        validate_review_priorities(
            dossier.review_priorities, finding_ids, evidence_ids=ledger_ids
        )
        == []
    )
    assert (
        validate_priority_consistency(
            dossier.rescue_priorities,
            dossier.access_priorities,
            dossier.review_priorities,
            list(vision.findings),
        )
        == []
    )
    assert (
        validate_verification_actions(
            dossier.verification_actions,
            finding_ids,
            concern_action_ids={
                c.verification_action_id for c in dossier.exposure_concerns
            },
            concern_ids={c.concern_id for c in dossier.exposure_concerns},
        )
        == []
    )
    assert (
        validate_finding_review_coverage(
            finding_ids, dossier.verification_actions
        )
        == []
    )
    assert (
        validate_segmentation_coverage(
            list(vision.segmentations), dossier.verification_actions
        )
        == []
    )
    assert (
        validate_segmentations(
            list(vision.segmentations),
            width=WIDTH,
            height=HEIGHT,
            finding_ids=finding_ids,
        )
        == []
    )
    assert (
        validate_workflow_status(
            list(vision.segmentations), vision.workflow_status
        )
        == []
    )
    assert (
        validate_incident_status(
            dossier.incident_status,
            list(dossier.agent_trail),
            impact_failed=impact_failed,
        )
        == []
    )
    assert validate_ledger(_cited_evidence(vision, dossier), ledger_ids) == []

    # Concern-action validity: every concern resolves to its own review.
    for concern in dossier.exposure_concerns:
        linked = actions[concern.verification_action_id]
        assert linked.kind == "concern_review"
        assert linked.concern_id == concern.concern_id
        assert concern.status == "unverified"
        joined = f"{concern.condition} {concern.concern}".lower()
        assert any(m in joined for m in CONDITIONAL_MARKERS)
        assert set(concern.basis_finding_ids) <= finding_ids
        assert set(concern.basis_evidence_ids) <= ledger_ids

    # No unsupported rescue escalation: high/medium need people evidence.
    for attention in dossier.rescue_priorities:
        basis = [by_id[f] for f in attention.basis_finding_ids if f in by_id]
        if attention.priority == RescuePriority.HIGH:
            assert any(people_in_danger(f) for f in basis)
        elif attention.priority == RescuePriority.MEDIUM:
            assert any(finding_mentions_person(f) for f in basis)
        # Unknown exposure never auto-LOW: no person evidence means
        # undetermined, never a routine all-clear.
        if basis and not any(finding_mentions_person(f) for f in basis):
            assert attention.priority == RescuePriority.UNDETERMINED

    # No fabricated urgency in any priority read.
    for read in (
        list(dossier.rescue_priorities)
        + list(dossier.access_priorities)
        + list(dossier.review_priorities)
    ):
        text = f"{read.rationale} {read.unknowns}".lower()
        assert not any(term in text for term in _FABRICATED_TERMS)
        assert read.requires_human_review is True
        assert set(read.basis_finding_ids) <= finding_ids

    # No unsupported damage class: assessable features, provisional,
    # always carrying an explicit uncertainty note.
    for assessment in dossier.damage_assessments:
        assert assessment.feature in ASSESSABLE_FEATURES
        assert assessment.provisional is True
        assert assessment.uncertainty_note.strip() != ""
        assert assessment.rationale.strip() != ""
        assert set(assessment.basis_finding_ids) <= finding_ids
        assert set(assessment.basis_evidence_ids) <= ledger_ids

    # Hazards restate retained findings with a controlled category.
    for hazard in dossier.observed_hazards:
        assert isinstance(hazard.category, HazardCategory)
        assert hazard.summary.strip() != ""
        assert set(hazard.finding_ids) <= finding_ids

    # Id uniqueness and vision preservation.
    assert len(actions) == len(dossier.verification_actions)
    assert len({c.concern_id for c in dossier.exposure_concerns}) == len(
        dossier.exposure_concerns
    )
    assert dossier.findings == vision.findings
    assert dossier.segmentations == vision.segmentations
    assert dossier.vision_workflow_status == vision.workflow_status

    # Sections adapt: geo follow-up appears exactly when geo is missing
    # (unless the action cap dropped it), empty vision gets a routine
    # review, and status reflects the run.
    capped = any(w.startswith("impact_action_cap") for w in dossier.warnings)
    if not vision.findings:
        assert "verify-routine" in actions
    if (
        dossier.geo_context.status == GeoStatus.UNAVAILABLE
        and not impact_failed
        and not capped
    ):
        assert "verify-geo-context" in actions
    if impact_failed:
        assert dossier.incident_status == IncidentStatus.PARTIAL
        assert "impact" in dossier.degraded_sections
        assert any("impact_unavailable" in w for w in dossier.warnings)
    else:
        assert dossier.incident_status == IncidentStatus.COMPLETED

    # JSON is complete and round-trips losslessly.
    body = json.loads(dossier.model_dump_json())
    assert _REQUIRED_DOSSIER_KEYS <= set(body)
    assert IncidentDossier.model_validate(body) == dossier


# --- 16 mocked scenarios: (findings, segmentations, geo, impact_error) ---


def _scenario_landslide_obscured_road():
    findings = [
        _finding(
            "f1",
            "slope",
            "Observed: landslide debris over the road.\n"
            "Affected feature: village road\n"
            "Location in image: lower slope, partly obscured",
        )
    ]
    segmentations = [_segmentation("road", linked=["f1"])]
    return findings, segmentations, _geo_unavailable(), None


def _scenario_flood_uncertain_building():
    findings = [
        _finding("f1", "floodwater", "Observed: floodwater over the road."),
        _finding(
            "f2",
            "building",
            "Observed: building near floodwater is possibly damaged.",
        ),
    ]
    segmentations = [
        _segmentation("road", linked=["f1"]),
        _segmentation("building", linked=["f2"]),
    ]
    return findings, segmentations, _geo_unavailable(), None


def _scenario_collapse_without_people():
    findings = [
        _finding(
            "f1", "building", "Observed: building collapsed into rubble."
        )
    ]
    segmentations = [_segmentation("building", linked=["f1"])]
    return findings, segmentations, _geo_unavailable(), None


def _scenario_people_without_danger():
    findings = [
        _finding("f1", "gathering", "Observed: people near the river bank.")
    ]
    return findings, [], _geo_unavailable(), None


def _scenario_credible_human_danger():
    findings = [
        _finding(
            "f1",
            "rescue",
            "Observed: person trapped in rubble near collapsed building.",
        )
    ]
    segmentations = [_segmentation("building", linked=["f1"])]
    return findings, segmentations, _geo_unavailable(), None


def _scenario_severe_hazard_unknown_exposure():
    findings = [
        _finding(
            "f1",
            "building",
            "Observed: building collapsed.\n"
            "Whether anyone is inside is unknown.",
        )
    ]
    segmentations = [_segmentation("building", linked=["f1"])]
    return findings, segmentations, _geo_unavailable(), None


def _scenario_road_damage_no_exposure():
    findings = [
        _finding(
            "f1", "damage", "Observed: cracked road surface with debris."
        )
    ]
    return findings, [], _geo_unavailable(), None


def _scenario_smoke_obscuring_infra():
    findings = [
        _finding(
            "f1",
            "smoke",
            "Observed: smoke obscuring the building; damage unclear.",
        ),
        _finding(
            "f2", "utility", "Observed: charred power pole near the road."
        ),
    ]
    segmentations = [_segmentation("building", linked=["f1"])]
    return findings, segmentations, _geo_unavailable(), None


def _scenario_competing_hazards():
    findings = [
        _finding("f1", "floodwater", "Observed: floodwater over the road."),
        _finding(
            "f2", "building", "Observed: building collapsed into rubble."
        ),
        _finding("f3", "gathering", "Observed: people near the river bank."),
    ]
    segmentations = [
        _segmentation("road", linked=["f1"]),
        _segmentation("building", linked=["f2"]),
    ]
    return findings, segmentations, _geo_unavailable(), None


def _scenario_no_disaster_evidence():
    findings = [
        _finding(
            "f1",
            "clear",
            "Observed: clear road, no damage, no people visible.",
        )
    ]
    return findings, [], _geo_unavailable(), None


def _scenario_contradictory_negated():
    findings = [
        _finding("f1", "road", "Observed: road intact."),
        _finding("f2", "damage", "Observed: road cracked with debris."),
        _finding("f3", "clear", "Observed: no people visible."),
    ]
    return findings, [], _geo_unavailable(), None


def _scenario_sam_zero_failed():
    findings = [
        _finding("f1", "floodwater", "Observed: floodwater over the road.")
    ]
    segmentations = [
        _segmentation("road", PromptStatus.ZERO_MATCHES, linked=["f1"]),
        _segmentation(
            "river",
            PromptStatus.FAILED,
            linked=["f1"],
            error="sam31_timeout: slow.",
        ),
    ]
    return findings, segmentations, _geo_unavailable(), None


def _scenario_sam_only_unlinked():
    findings = [
        _finding("f1", "smoke", "Observed: smoke in the distance.")
    ]
    segmentations = [
        _segmentation(
            "debris",
            linked=[],
            provenance=PromptProvenance.USER_REQUESTED,
        )
    ]
    return findings, segmentations, _geo_unavailable(), None


def _scenario_missing_location_time():
    findings = [
        _finding("f1", "floodwater", "Observed: floodwater over the road.")
    ]
    segmentations = [_segmentation("road", linked=["f1"])]
    return findings, segmentations, _geo_unavailable(), None


def _scenario_partial_impact_failure():
    findings = [
        _finding("f1", "floodwater", "Observed: floodwater over the road.")
    ]
    segmentations = [_segmentation("road", linked=["f1"])]
    return findings, segmentations, _geo_unavailable(), "impact_failed: boom."


def _scenario_long_many_observation_report():
    findings = [
        _finding("f1", "floodwater", "Observed: floodwater over the road."),
        _finding("f2", "damage", "Observed: road cracked with debris."),
        _finding(
            "f3", "building", "Observed: building collapsed into rubble."
        ),
        _finding(
            "f4", "building", "Observed: damaged house near the slope."
        ),
        _finding("f5", "gathering", "Observed: people near the river bank."),
        _finding(
            "f6", "utility", "Observed: charred power pole near the road."
        ),
        _finding(
            "f7", "vehicle", "Observed: vehicle beside debris on the lane."
        ),
        _finding("f8", "vehicle", "Observed: truck beside debris."),
        _finding("f9", "damage", "Observed: blocked highway with rubble."),
    ]
    segmentations = [
        _segmentation("road", linked=["f1", "f2"]),
        _segmentation("building", linked=["f3", "f4"]),
    ]
    return findings, segmentations, _geo_unavailable(), None


SCENARIOS = {
    "01-landslide-obscured-road": _scenario_landslide_obscured_road,
    "02-flood-uncertain-building": _scenario_flood_uncertain_building,
    "03-collapse-without-people": _scenario_collapse_without_people,
    "04-people-without-danger": _scenario_people_without_danger,
    "05-credible-human-danger": _scenario_credible_human_danger,
    "06-severe-hazard-unknown-exposure": _scenario_severe_hazard_unknown_exposure,
    "07-road-damage-no-exposure": _scenario_road_damage_no_exposure,
    "08-smoke-obscuring-infra": _scenario_smoke_obscuring_infra,
    "09-competing-hazards": _scenario_competing_hazards,
    "10-no-disaster-evidence": _scenario_no_disaster_evidence,
    "11-contradictory-negated": _scenario_contradictory_negated,
    "12-sam-zero-failed": _scenario_sam_zero_failed,
    "13-sam-only-unlinked": _scenario_sam_only_unlinked,
    "14-missing-location-time": _scenario_missing_location_time,
    "15-partial-impact-failure": _scenario_partial_impact_failure,
    "16-long-many-observation-report": _scenario_long_many_observation_report,
}


def _run_scenario(name: str) -> tuple[IncidentDossier, UnifiedAnalysisResponse]:
    findings, segmentations, geo, impact_error = SCENARIOS[name]()
    vision = _vision(findings, segmentations)
    return _pipeline(vision, geo, impact_error), vision


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_matrix_global_invariants(name):
    dossier, vision = _run_scenario(name)
    assert_global_invariants(
        dossier, vision, impact_failed=name == "15-partial-impact-failure"
    )


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_matrix_deterministic_ordering(name):
    first, _ = _run_scenario(name)
    second, _ = _run_scenario(name)
    assert first.model_dump_json() == second.model_dump_json()
    assert [a.action_id for a in first.verification_actions] == [
        a.action_id for a in second.verification_actions
    ]
    assert [c.concern_id for c in first.exposure_concerns] == [
        c.concern_id for c in second.exposure_concerns
    ]


# --- targeted per-scenario assertions (invariants, not wording) ---


def _rescue_for(dossier, finding_id):
    return next(
        r
        for r in dossier.rescue_priorities
        if finding_id in r.basis_finding_ids
    )


def test_01_landslide_road_concern_supported():
    dossier, _ = _run_scenario("01-landslide-obscured-road")
    road = [c for c in dossier.exposure_concerns if c.feature == "road"]
    assert road != []
    assert all("f1" in c.basis_finding_ids for c in road)
    reads = [a for a in dossier.damage_assessments if a.feature == "road"]
    assert reads != []
    assert all(a.category != DamageCategory.NO_VISIBLE_DAMAGE for a in reads)
    assert all(r.priority != RescuePriority.HIGH for r in dossier.rescue_priorities)


def test_02_flood_building_damage_stays_provisional():
    dossier, _ = _run_scenario("02-flood-uncertain-building")
    building = [a for a in dossier.damage_assessments if a.feature == "building"]
    assert building != []
    assert building[0].category == DamageCategory.POSSIBLE_DAMAGE
    assert "f2" in building[0].basis_finding_ids
    road = [c for c in dossier.exposure_concerns if c.feature == "road"]
    assert road != []


def test_03_collapse_without_people_no_rescue_escalation():
    dossier, _ = _run_scenario("03-collapse-without-people")
    assert dossier.rescue_priorities != []
    assert all(
        r.priority == RescuePriority.UNDETERMINED
        for r in dossier.rescue_priorities
    )
    reads = [a for a in dossier.damage_assessments if a.feature == "building"]
    assert reads[0].category == DamageCategory.APPARENT_MAJOR_DAMAGE
    assert [c for c in dossier.exposure_concerns if c.feature == "people"] == []


def test_04_people_without_danger_routine_not_urgent():
    dossier, vision = _run_scenario("04-people-without-danger")
    assert vision.workflow_status == WorkflowStatus.VISION_ONLY
    assert _rescue_for(dossier, "f1").priority == RescuePriority.LOW
    assert all(
        r.priority != RescuePriority.HIGH for r in dossier.rescue_priorities
    )
    assert [c for c in dossier.exposure_concerns if c.feature == "people"] != []
    people_actions = [
        a for a in dossier.verification_actions if a.kind == "people_safety"
    ]
    assert len(people_actions) == 1
    assert people_actions[0].priority == "high"


def test_05_credible_danger_escalates_with_basis():
    dossier, _ = _run_scenario("05-credible-human-danger")
    assert _rescue_for(dossier, "f1").priority == RescuePriority.HIGH
    hazards = [h for h in dossier.observed_hazards if "f1" in h.finding_ids]
    assert hazards[0].category == HazardCategory.HUMAN_EXPOSURE
    people = [c for c in dossier.exposure_concerns if c.feature == "people"]
    assert people != []
    linked = next(
        a
        for a in dossier.verification_actions
        if a.action_id == people[0].verification_action_id
    )
    assert linked.priority == "high"


def test_06_unknown_exposure_never_auto_low():
    dossier, _ = _run_scenario("06-severe-hazard-unknown-exposure")
    assert dossier.rescue_priorities != []
    assert all(
        r.priority == RescuePriority.UNDETERMINED
        for r in dossier.rescue_priorities
    )
    reads = [a for a in dossier.damage_assessments if a.feature == "building"]
    assert reads[0].category == DamageCategory.APPARENT_MAJOR_DAMAGE


def test_07_road_damage_raises_no_people_claims():
    dossier, _ = _run_scenario("07-road-damage-no-exposure")
    assert [c for c in dossier.exposure_concerns if c.feature == "people"] == []
    assert [
        a for a in dossier.verification_actions if a.kind == "people_safety"
    ] == []
    assert [c for c in dossier.exposure_concerns if c.feature == "road"] != []
    assert all(
        r.priority == RescuePriority.UNDETERMINED
        for r in dossier.rescue_priorities
    )


def test_08_obscured_infra_never_auto_damage_class():
    dossier, _ = _run_scenario("08-smoke-obscuring-infra")
    obscured = next(
        a
        for a in dossier.damage_assessments
        if a.feature == "building" and "f1" in a.basis_finding_ids
    )
    assert obscured.category == DamageCategory.CANNOT_ASSESS
    utility = [a for a in dossier.damage_assessments if a.feature == "utility"]
    assert utility != []
    assert utility[0].category == DamageCategory.POSSIBLE_DAMAGE
    assert all(
        r.priority != RescuePriority.HIGH for r in dossier.rescue_priorities
    )


def test_09_competing_hazards_stay_distinct():
    dossier, _ = _run_scenario("09-competing-hazards")
    assert len({c.feature for c in dossier.exposure_concerns}) >= 2
    assert len({a.feature for a in dossier.damage_assessments}) >= 2
    assert _rescue_for(dossier, "f3").priority == RescuePriority.LOW
    assert _rescue_for(dossier, "f1").priority == RescuePriority.UNDETERMINED
    assert _rescue_for(dossier, "f2").priority == RescuePriority.UNDETERMINED


def test_10_quiet_scene_and_empty_vision_handled():
    dossier, _ = _run_scenario("10-no-disaster-evidence")
    assert dossier.exposure_concerns == []
    assert dossier.damage_assessments != []
    assert all(
        a.category
        in (DamageCategory.CANNOT_ASSESS, DamageCategory.NO_VISIBLE_DAMAGE)
        for a in dossier.damage_assessments
    )
    assert dossier.uncertainty_notes != []
    # Fully empty vision: routine review only, still a valid dossier.
    empty_vision = _vision([], [])
    empty = _pipeline(empty_vision, _geo_unavailable())
    assert_global_invariants(empty, empty_vision)
    assert empty.exposure_concerns == []
    assert empty.damage_assessments == []


def test_11_conflicts_stay_explicitly_uncertain():
    dossier, _ = _run_scenario("11-contradictory-negated")
    reads = [a for a in dossier.damage_assessments if a.feature == "road"]
    assert len(reads) == 1
    assert reads[0].category == DamageCategory.POSSIBLE_DAMAGE
    assert "disagree" in reads[0].uncertainty_note.lower()
    assert {"f1", "f2"} <= set(reads[0].basis_finding_ids)
    # Negated people mention raises no people concern or safety task.
    assert [c for c in dossier.exposure_concerns if c.feature == "people"] == []
    assert [
        a for a in dossier.verification_actions if a.kind == "people_safety"
    ] == []


def test_12_unmeasured_prompts_need_reviews_never_absence():
    dossier, vision = _run_scenario("12-sam-zero-failed")
    assert vision.workflow_status == WorkflowStatus.PARTIAL
    reviews = {
        a.prompt
        for a in dossier.verification_actions
        if a.kind == "segmentation_review"
    }
    assert {"road", "river"} <= reviews
    road = [c for c in dossier.exposure_concerns if c.feature == "road"]
    assert road != []
    assert "does not mean" in road[0].concern
    assert any("river" in n.lower() for n in dossier.uncertainty_notes)


def test_13_unlinked_sam_regions_get_review_only():
    dossier, _ = _run_scenario("13-sam-only-unlinked")
    assert dossier.exposure_concerns == []
    reviews = [
        a
        for a in dossier.verification_actions
        if a.kind == "segmentation_review"
    ]
    assert [a.prompt for a in reviews] == ["debris"]
    assert "operator-requested" in reviews[0].reason
    summary = next(
        s for s in dossier.segmentation_summary if s.prompt == "debris"
    )
    assert summary.linked_finding_ids == []
    assert summary.detection_count == 1


def test_14_missing_geo_adapts_sections():
    dossier, _ = _run_scenario("14-missing-location-time")
    assert "verify-geo-context" in {
        a.action_id for a in dossier.verification_actions
    }
    topics = {g.topic: g.status for g in dossier.information_gaps}
    assert topics["capture_time"] == "unknown"
    assert topics["incident_location"] == "unknown"
    # Provided geo removes the follow-up and marks location unverified.
    findings, segmentations, _, _ = SCENARIOS["14-missing-location-time"]()
    provided = _pipeline(_vision(findings, segmentations), _geo_provided())
    assert "verify-geo-context" not in {
        a.action_id for a in provided.verification_actions
    }
    provided_topics = {g.topic: g.status for g in provided.information_gaps}
    assert provided_topics["incident_location"] == "unverified"


def test_15_partial_impact_failure_and_reporting_failure(monkeypatch):
    dossier, vision = _run_scenario("15-partial-impact-failure")
    assert dossier.incident_status == IncidentStatus.PARTIAL
    assert dossier.exposure_concerns == []
    assert dossier.damage_assessments == []
    assert dossier.findings == vision.findings
    assert "verify-impact-rerun" in {
        a.action_id for a in dossier.verification_actions
    }
    assert "verify-finding-f1" in {
        a.action_id for a in dossier.verification_actions
    }
    # Reporting failure yields an explicit safe error, never a dossier.
    findings, segmentations, geo, _ = SCENARIOS["15-partial-impact-failure"]()
    failed_vision = _vision(findings, segmentations)
    monkeypatch.setattr(
        orch_module, "run_unified_analysis", lambda v, w, h: failed_vision
    )

    class _Boom:
        def run(self, payload):
            raise RuntimeError("boom")

    monkeypatch.setattr(orch_module, "ReportingAgent", _Boom)
    with pytest.raises(SentinelError) as exc_info:
        Orchestrator().run_workflow(
            "disaster_response",
            {
                "validated": _validated_image(),
                "width": WIDTH,
                "height": HEIGHT,
                "geo_context": geo,
            },
        )
    assert exc_info.value.code == "reporting_failed"
    assert "boom" not in exc_info.value.message


def test_16_long_report_caps_explicitly():
    dossier, _ = _run_scenario("16-long-many-observation-report")
    assert len(dossier.exposure_concerns) == 6
    assert len(dossier.verification_actions) == 16
    assert any("impact_concern_cap" in w for w in dossier.warnings)
    assert "exposure_concerns" in dossier.degraded_sections
    assert "verification_actions" in dossier.degraded_sections
    assert dossier.finding_groups != []
    assert dossier.information_gaps != []


# --- model-call counters: single vision pass, no duplicates ---


def _png_bytes(width: int = WIDTH, height: int = HEIGHT) -> bytes:
    image = Image.new("RGB", (width, height), color=(120, 130, 140))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _validated_image():
    return media_service.validate_image_bytes(
        _png_bytes(), max_bytes=10 * 1024 * 1024
    )


class _CountingVision:
    """Vision fake recording every model-stage invocation."""

    def __init__(self, findings: list[Finding]) -> None:
        self._findings = findings
        self.calls = 0

    def __call__(self, *args, **kwargs) -> "_CountingVision":
        return self

    def run(self, payload: dict) -> AgentResult:
        self.calls += 1
        return AgentResult(agent="vision", findings=list(self._findings))


class _CountingSam:
    """SAM fake recording each prompt segmentation exactly once."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def __call__(self, *args, **kwargs) -> "_CountingSam":
        return self

    def segment_image(self, image_data_url: str, prompt: str) -> Sam31Result:
        self.prompts.append(prompt)
        return Sam31Result(
            detections=[
                Sam31Detection(
                    object_id="0",
                    box=Sam31Box(x1=10, y1=20, x2=30, y2=40),
                    mask=Sam31Mask(
                        width=20,
                        height=20,
                        svg_path="M0 0L1 0L1 1Z",
                        rle_counts="abc",
                    ),
                )
            ]
        )


def test_orchestrator_runs_single_vision_pass(monkeypatch):
    calls: list[str] = []
    findings, segmentations, geo, _ = SCENARIOS["02-flood-uncertain-building"]()
    vision = _vision(findings, segmentations)

    def fake_vision(validated, width, height):
        calls.append("vision")
        return vision

    monkeypatch.setattr(orch_module, "run_unified_analysis", fake_vision)
    dossier = Orchestrator().run_workflow(
        "disaster_response",
        {
            "validated": _validated_image(),
            "width": WIDTH,
            "height": HEIGHT,
            "geo_context": geo,
        },
    )
    assert calls == ["vision"]
    assert [t.agent for t in dossier.agent_trail] == ["vision", "impact", "reporting"]
    assert_global_invariants(dossier, vision)


def test_cached_reuse_makes_zero_model_calls(monkeypatch):
    def fail_vision(*args, **kwargs):
        raise AssertionError("cached reuse must not call models")

    monkeypatch.setattr(orch_module, "run_unified_analysis", fail_vision)
    findings, segmentations, geo, _ = SCENARIOS["01-landslide-obscured-road"]()
    vision = _vision(findings, segmentations)
    dossier = Orchestrator().run_workflow_from_vision(
        "disaster_response", vision, geo, "anl_test"
    )
    assert dossier.vision_source == "cached_reuse"
    assert dossier.incident_status == IncidentStatus.COMPLETED
    assert_global_invariants(dossier, vision)


def test_sam_called_once_per_planned_prompt():
    validated = _validated_image()
    evidence_id = f"sha256:{hashlib.sha256(validated.data).hexdigest()}"
    finding = Finding(
        finding_id="vision-1",
        label="floodwater",
        description="Observed: floodwater over the road.",
        confidence=Confidence(value=0.8),
        evidence_refs=[
            EvidenceRef(
                evidence_id=evidence_id,
                modality="image",
                uri_or_hash=evidence_id,
            )
        ],
    )
    vision_fake = _CountingVision([finding])
    sam_fake = _CountingSam()
    response = run_unified_analysis(
        validated,
        WIDTH,
        HEIGHT,
        vision_factory=vision_fake,
        sam_factory=sam_fake,
    )
    assert vision_fake.calls == 1
    planned = [d.prompt for d in response.prompt_plan]
    assert planned != []
    # Each planned prompt segmented exactly once: no duplicates, no gaps.
    assert Counter(sam_fake.prompts) == Counter(planned[: len(sam_fake.prompts)])
    assert len(sam_fake.prompts) == len(set(sam_fake.prompts))
    assert len(sam_fake.prompts) == len(
        [s for s in response.segmentations if s.status != PromptStatus.SKIPPED]
    )
