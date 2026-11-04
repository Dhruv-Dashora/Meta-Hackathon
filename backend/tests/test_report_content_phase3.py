"""Phase-3 report-content tests: headlines, scene text, gaps, and tasks.

Pins the deterministic content rules shared by the impact and reporting
agents: concise hazard-aware headlines, natural observed-scene text,
conditional impact statements that differ per hazard, explicit gaps,
and actionable verification objectives — with no generic filler, no
new factual claims, and negation/uncertainty preserved.
"""

from app.agents.impact_agent import ImpactAgent
from app.agents.report_content import (
    finding_signals,
    hazard_gaps,
    scene_headline,
    scene_observed,
    scene_unknowns,
)
from app.agents.reporting_agent import ReportingAgent
from app.orchestrator.validators import (
    validate_exposure_concerns,
    validate_verification_actions,
)
from app.schemas.common import Confidence, EvidenceRef, Finding
from app.schemas.incident import GeoContext, GeoStatus
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


def _geo() -> GeoContext:
    return GeoContext(status=GeoStatus.UNAVAILABLE, note="none provided")


def _segmentation(
    prompt: str = "road",
    status: PromptStatus = PromptStatus.OK,
    linked: list[str] | None = None,
) -> PromptSegmentation:
    return PromptSegmentation(
        prompt=prompt,
        linked_finding_ids=["vision-1"] if linked is None else linked,
        status=status,
        detections=[
            SegmentDetection(
                object_id="0",
                box=SegmentBox(x1=10, y1=20, x2=30, y2=40),
                mask=SegmentMask(
                    width=20, height=20, svg_path="M0 0Z", rle_counts="a"
                ),
            )
        ]
        if status == PromptStatus.OK
        else [],
    )


def _impact(findings, segmentations=None):
    return ImpactAgent().run(
        {
            "findings": findings,
            "segmentations": segmentations or [],
            "geo_context": _geo(),
        }
    ).data


def _dossier(findings, segmentations):
    vision = UnifiedAnalysisResponse(
        incident_id="img-test",
        image=SegmentImageInfo(
            width=320, height=334, mime_type="image/png", evidence_id=EVIDENCE
        ),
        findings=findings,
        segmentations=segmentations,
        workflow_status=WorkflowStatus.COMPLETED,
        warnings=[],
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


# --- (A) headlines: hazard-aware, conditional, abstain when unsafe ---


def test_headline_names_flood_with_water_unknown():
    headline = scene_headline(
        [_finding(description="Observed: floodwater over the road.")]
    )
    assert "floodwater" in headline or "flooding" in headline
    assert "water extent unconfirmed" in headline
    assert "Possible" in headline
    assert "finding(s)" not in headline
    assert "(s)" not in headline


def test_headline_names_collapse_with_stability_unknown():
    headline = scene_headline(
        [_finding(label="ruin", description="Observed: building collapsed.")]
    )
    assert "structural damage" in headline
    assert "stability unconfirmed" in headline
    assert "ruin" in headline


def test_headline_names_landslide_with_extent_unknown():
    headline = scene_headline(
        [_finding(label="slope", description="Observed: landslide debris.")]
    )
    assert "slope debris" in headline
    assert "extent unconfirmed" in headline


def test_headline_names_people_in_danger_first():
    headline = scene_headline(
        [
            _finding(
                "f1", "crowd", "Observed: person trapped under debris."
            ),
            _finding(
                "f2", "floodwater", "Observed: floodwater over the road."
            ),
        ]
    )
    assert headline.startswith("People possibly in danger (crowd)")
    assert "flooding" in headline


def test_headline_quiet_scene_states_no_supported_hazard():
    headline = scene_headline(
        [_finding(label="trees", description="Observed: trees by the field.")]
    )
    assert "no hazard indicators confirmed" in headline
    assert "Possible" not in headline


def test_headline_negated_scene_abstains():
    headline = scene_headline([_finding("f1", "x", "")])
    assert headline == "No confirmed hazard: observations are negated or unclear."


def test_headline_empty_scene_abstains():
    assert scene_headline([]) == (
        "No findings: no supported assessment from this image."
    )


def test_headline_negated_flood_is_not_flood():
    headline = scene_headline(
        [
            _finding(
                label="road",
                description="Observed: no floodwater on the road today.",
            )
        ]
    )
    assert "flooding" not in headline
    assert "no hazard indicators confirmed" in headline


# --- (B) observed scene: natural, excerpted, honest plurals ---


def test_observed_uses_excerpts_not_counts():
    observed = scene_observed(
        [
            _finding(
                "f1",
                "floodwater",
                "Observed: floodwater over the road.\n"
                "Affected feature: village road\n"
                "Location in image: lower third, center",
            )
        ],
        [_segmentation("road")],
    )
    assert "village road" in observed
    assert "lower third, center" in observed
    assert "finding(s)" not in observed
    assert "(s)" not in observed
    assert "1 'road' region measured" in observed


def test_observed_pluralizes_and_never_claims_absence():
    observed = scene_observed(
        [_finding()],
        [
            _segmentation("road"),
            _segmentation("river", PromptStatus.ZERO_MATCHES, linked=[]),
            _segmentation("bridge", PromptStatus.FAILED, linked=[]),
        ],
    )
    assert "region measured" in observed
    assert "not absence" in observed
    assert "segmentation failed" in observed
    assert "(s)" not in observed


# --- (C) unknowns + gaps: explicit and hazard-specific ---


def test_unknowns_carry_hazard_specific_bits():
    unknowns = scene_unknowns(
        [_finding(description="Observed: floodwater over the road.")],
        False,
        [_segmentation("road")],
    )
    assert "Capture time is unknown" in unknowns
    assert "water depth, extent, and trend are unconfirmed" in unknowns
    assert "passable" in unknowns
    assert "no field ground truth exists" in unknowns


def test_gaps_cover_each_hazard_family():
    topics = {
        topic
        for topic, _d, _w, _s in hazard_gaps(
            [
                _finding(
                    "f1", "water", "Observed: floodwater over the road."
                ),
                _finding(
                    "f2", "ruin", "Observed: building collapsed rubble."
                ),
                _finding(
                    "f3", "slope", "Observed: landslide debris on slope."
                ),
                _finding(
                    "f4", "crowd", "Observed: people near the river bank."
                ),
            ]
        )
    }
    assert topics == {
        "water_conditions",
        "structural_condition",
        "slope_conditions",
        "human_exposure",
    }


def test_gaps_abstain_for_quiet_scene():
    gaps = hazard_gaps(
        [_finding(label="trees", description="Observed: trees by the field.")]
    )
    assert [topic for topic, _d, _w, _s in gaps] == ["hazard_assessment"]
    assert "no damage or access assessment is made" in gaps[0][1]


def test_signals_respect_negation_and_word_boundaries():
    assert finding_signals(
        _finding(description="Observed: no floodwater visible.")
    ) == frozenset()
    assert finding_signals(
        _finding(description="Observed: careful business as usual.")
    ) == frozenset()
    assert "flood" in finding_signals(
        _finding(description="Observed: floodwater over the road.")
    )


# --- (D) concerns: distinct conditional statements per hazard ---


def test_road_concerns_differ_by_hazard_and_stay_conditional():
    flood = _impact(
        [_finding(description="Observed: floodwater over the road.")]
    )["exposure_concerns"]
    debris = _impact(
        [_finding(description="Observed: road blocked by debris.")]
    )["exposure_concerns"]
    slide = _impact(
        [_finding(description="Observed: road blocked by landslide.")]
    )["exposure_concerns"]
    assert len(flood) == len(debris) == len(slide) == 1
    texts = {c.concern for c in (flood[0], debris[0], slide[0])}
    assert len(texts) == 3
    assert "standing water" in flood[0].concern
    assert "block" in debris[0].concern
    assert "slope debris" in slide[0].concern
    for concern in (flood[0], debris[0], slide[0]):
        assert "not confirmed" in concern.concern
        assert concern.status == "unverified"


def test_concern_consequence_names_collapse_instability():
    data = _impact(
        [_finding(description="Observed: building collapsed rubble.")],
        [_segmentation("building")],
    )
    building = [c for c in data["exposure_concerns"] if c.feature == "building"]
    assert len(building) == 1
    assert "unstable" in building[0].concern
    assert "occupancy" in building[0].concern
    assert validate_exposure_concerns(
        data["exposure_concerns"], data["verification_actions"]
    ) == []


# --- (E) verification tasks: actionable, specific, valid ---


def test_concern_review_states_objective_not_echo():
    data = _impact(
        [_finding(description="Observed: floodwater over the road.")],
        [_segmentation("road")],
    )
    (concern,) = data["exposure_concerns"]
    (linked,) = [
        a
        for a in data["verification_actions"]
        if a.action_id == concern.verification_action_id
    ]
    assert concern.concern_id in linked.action
    assert "road" in linked.action
    assert "routes in active use" in linked.what
    assert "check whether the road is passable" in linked.what
    assert linked.what != concern.condition
    assert linked.reason != f"Concern premise: {concern.condition}."
    assert "unverified" in linked.reason.lower()
    assert validate_verification_actions(
        data["verification_actions"], {"vision-1"}
    ) == []


def test_finding_review_names_excerpt_and_objective():
    data = _impact(
        [
            _finding(
                "f1",
                "floodwater",
                "Observed: floodwater over the road.\n"
                "Affected feature: village road\n"
                "Location in image: lower third",
            )
        ]
    )
    (review,) = [
        a
        for a in data["verification_actions"]
        if a.action_id == "verify-finding-f1"
    ]
    assert "village road" in review.what
    assert "f1" in review.what
    assert "standing-water extent" in review.what
    assert "standing-water extent" in review.action
    assert "(s)" not in review.what


def test_actions_hold_no_generic_counts_and_stay_ordered():
    data = _impact(
        [
            _finding("f1", "a", "Observed: floodwater over the road."),
            _finding("f2", "b", "Observed: building collapsed."),
        ],
        [_segmentation("road")],
    )
    again = _impact(
        [
            _finding("f1", "a", "Observed: floodwater over the road."),
            _finding("f2", "b", "Observed: building collapsed."),
        ],
        [_segmentation("road")],
    )
    first = [a.action_id for a in data["verification_actions"]]
    second = [a.action_id for a in again["verification_actions"]]
    assert first == second
    assert len(set(first)) == len(first)
    for action in data["verification_actions"]:
        joined = f"{action.action} {action.what} {action.reason}"
        assert "finding(s)" not in joined
        assert "(s)" not in joined
        assert action.what.strip() != ""
        assert action.unknown.strip() != ""


# --- (F) dossier integration: headline, gaps, and fallback tasks ---


def test_dossier_carries_headline_and_hazard_gaps():
    dossier = _dossier(
        [
            _finding(
                label="floodwater",
                description="Observed: floodwater over the road.",
            )
        ],
        [_segmentation("road")],
    )
    assert "flooding" in dossier.situation_summary.headline
    assert (
        "Observed floodwater: floodwater over the road."
        in dossier.situation_summary.observed
    )
    topics = [g.topic for g in dossier.information_gaps]
    assert "water_conditions" in topics
    assert "accessibility" in topics
    assert topics.index("water_conditions") < topics.index("ground_truth")


def test_dossier_quiet_scene_abstains_everywhere():
    dossier = _dossier(
        [_finding(label="trees", description="Observed: trees by the field.")],
        [],
    )
    assert "no hazard indicators confirmed" in (
        dossier.situation_summary.headline
    )
    assert dossier.exposure_concerns == []
    topics = [g.topic for g in dossier.information_gaps]
    assert "hazard_assessment" in topics


def test_dossier_fallback_tasks_stay_specific():
    vision = UnifiedAnalysisResponse(
        incident_id="img-test",
        image=SegmentImageInfo(
            width=320, height=334, mime_type="image/png", evidence_id=EVIDENCE
        ),
        findings=[
            _finding(
                "f1",
                "floodwater",
                "Observed: floodwater over the road.\n"
                "Affected feature: village road",
            )
        ],
        segmentations=[],
        workflow_status=WorkflowStatus.VISION_ONLY,
        warnings=[],
    )
    dossier = ReportingAgent().run(
        {
            "incident_id": vision.incident_id,
            "image": vision.image,
            "vision": vision,
            "impact_data": None,
            "impact_error": "impact_failed: RuntimeError.",
            "geo_context": _geo(),
            "trail": [],
        }
    ).data["dossier"]
    (review,) = [
        a
        for a in dossier.verification_actions
        if a.action_id == "verify-finding-f1"
    ]
    assert "village road" in review.what
    assert "standing-water extent" in review.what
    assert validate_verification_actions(
        dossier.verification_actions, {"f1"}
    ) == []
