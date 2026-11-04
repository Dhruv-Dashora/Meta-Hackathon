"""Phase-2 impact-rule tests: hazard categories, assessable damage,
three separate priorities, and verification grouping.

Pins the generalized rules: controlled hazard interpretation with
negation/word-boundary predicates; damage only for assessable
infrastructure; strict rescue gates with separate access/review
urgencies; and verification tasks that retain evidence without
merging distinct objectives.
"""

from app.agents.condition_assessment import (
    access_priorities,
    damage_assessments,
    rescue_priorities,
    review_priorities,
)
from app.agents.impact_agent import ImpactAgent
from app.orchestrator.validators import (
    validate_access_priorities,
    validate_damage_assessments,
    validate_priority_consistency,
    validate_rescue_priorities,
    validate_review_priorities,
)
from app.schemas.common import Confidence, EvidenceRef, Finding
from app.schemas.incident import (
    DamageCategory,
    GeoContext,
    GeoStatus,
    HazardCategory,
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


# --- (A) hazard categories ---


def test_hazard_visible_damage_for_linked_cue():
    data = _impact([_finding(description="Observed: building collapsed.")])
    assert data["observed_hazards"][0].category == (
        HazardCategory.VISIBLE_DAMAGE
    )


def test_hazard_human_exposure_for_people_plus_danger():
    data = _impact([_finding(description="Observed: person trapped in mud.")])
    assert data["observed_hazards"][0].category == (
        HazardCategory.HUMAN_EXPOSURE
    )


def test_hazard_exposed_infrastructure_for_risk_context():
    data = _impact([_finding(description="Observed: floodwater over the road.")])
    assert data["observed_hazards"][0].category == (
        HazardCategory.EXPOSED_INFRASTRUCTURE
    )


def test_hazard_mechanism_for_process_observation():
    data = _impact([_finding(description="Observed: landslide on the slope.")])
    category = data["observed_hazards"][0].category
    assert category in (HazardCategory.MECHANISM, HazardCategory.VISIBLE_DAMAGE)


def test_hazard_unknown_for_negated_only():
    data = _impact(
        [_finding(description="Observed: no damage, no people visible.")]
    )
    assert data["observed_hazards"][0].category in (
        HazardCategory.UNKNOWN,
        HazardCategory.UNCLASSIFIED,
        HazardCategory.OBSERVED_FEATURE,
    )


def test_hazard_unclassified_for_unmatched_substance():
    data = _impact([_finding(description="Observed: smoke in the distance.")])
    assert data["observed_hazards"][0].category == (
        HazardCategory.UNCLASSIFIED
    )


def test_word_boundaries_reject_substrings():
    # "car" in "careful", "bus" in "business" must not match.
    data = _impact(
        [_finding(description="Observed: careful business as usual.")]
    )
    assert data["exposure_concerns"] == []
    assert data["observed_hazards"][0].category in (
        HazardCategory.UNKNOWN,
        HazardCategory.UNCLASSIFIED,
    )


def test_negated_people_raise_no_people_concern_or_action():
    data = _impact([_finding(description="Observed: no people visible.")])
    assert [c for c in data["exposure_concerns"] if c.feature == "people"] == []
    assert [
        a
        for a in data["verification_actions"]
        if a.kind == "people_safety"
    ] == []


# --- (B) assessable damage only ---


def test_damage_skips_river_and_people():
    assessments, _ = damage_assessments(
        [_finding(description="Observed: floodwater over the river.")]
    )
    assert assessments == []
    assessments, _ = damage_assessments(
        [_finding(description="Observed: people near the bank.")]
    )
    assert assessments == []


def test_damage_covers_utility_and_bridge_as_road():
    assessments, _ = damage_assessments(
        [_finding(description="Observed: power pole tilted.")]
    )
    assert [a.feature for a in assessments] == ["utility"]
    assessments, _ = damage_assessments(
        [_finding(description="Observed: bridge collapsed.")]
    )
    assert [a.feature for a in assessments] == ["road"]
    assert assessments[0].category == DamageCategory.APPARENT_MAJOR_DAMAGE


def test_damage_never_defaults_to_all_clear():
    assessments, _ = damage_assessments(
        [_finding(description="Observed: road.")]
    )
    assert assessments[0].category == DamageCategory.CANNOT_ASSESS
    bad = assessments[0].model_copy(update={"feature": "river"})
    assert validate_damage_assessments([bad], {"vision-1"}) != []


def test_damage_positive_reads_stay_provisional_not_engineering():
    assessments, _ = damage_assessments(
        [_finding(description="Observed: building collapsed.")]
    )
    assert assessments[0].provisional is True
    assert "not an engineering finding" in assessments[0].rationale


# --- (C) three separate priorities ---


def test_rescue_strict_person_alone_is_low_no_person_undetermined():
    ranked, _ = rescue_priorities(
        [_finding(description="Observed: people near the river bank.")]
    )
    assert ranked[0].priority == RescuePriority.LOW
    ranked, _ = rescue_priorities(
        [_finding(description="Observed: road blocked by landslide.")]
    )
    assert ranked[0].priority == RescuePriority.UNDETERMINED
    assert validate_rescue_priorities(ranked, {"vision-1"}) == []


def test_access_rates_blockage_high_and_quiet_low():
    ranked, _ = access_priorities(
        [_finding(description="Observed: road blocked by landslide.")]
    )
    assert ranked[0].priority == RescuePriority.HIGH
    ranked, _ = review_priorities(
        [_finding(description="Observed: road clear and intact.")]
    )
    assert ranked[0].priority == RescuePriority.LOW
    assert validate_access_priorities(
        access_priorities(
            [_finding(description="Observed: road blocked.")]
        )[0],
        {"vision-1"},
    ) == []


def test_review_rates_danger_first_and_vacuous_undetermined():
    ranked, _ = review_priorities(
        [_finding(description="Observed: person trapped under debris.")]
    )
    assert ranked[0].priority == RescuePriority.HIGH
    ranked, _ = review_priorities([_finding("f1", "x", "")])
    assert ranked[0].priority == RescuePriority.UNDETERMINED
    assert validate_review_priorities(
        review_priorities([_finding()])[0], {"vision-1"}
    ) == []


def test_priorities_carry_unknowns_and_no_fabrications():
    data = _impact(
        [
            _finding("f1", "scene", "Observed: person trapped in mud."),
            _finding("f2", "road", "Observed: road blocked."),
        ]
    )
    for key in ("rescue_priorities", "access_priorities", "review_priorities"):
        for item in data[key]:
            assert item.unknowns.strip() != ""
            assert item.requires_human_review is True
            joined = f"{item.rationale} {item.unknowns}".lower()
            for banned in ("casualt", "victim", "deploy", "dispatch"):
                assert banned not in joined
    assert validate_priority_consistency(
        data["rescue_priorities"],
        data["access_priorities"],
        data["review_priorities"],
        [_finding("f1", "scene", "Observed: person trapped in mud."),
         _finding("f2", "road", "Observed: road blocked.")],
    ) == []


# --- (D) verification grouping ---


def test_distinct_objectives_stay_separate_and_grouped_ids_retained():
    f1 = _finding("f1", "debris", "Observed: blocked road with debris.")
    data = _impact([f1])
    ids = [a.action_id for a in data["verification_actions"]]
    assert "verify-finding-f1" in ids
    concern_ids = [c.verification_action_id for c in data["exposure_concerns"]]
    for cid in concern_ids:
        assert cid in ids
    # Multi-finding concern groups retain every id.
    f2 = _finding("f2", "road", "Observed: cracked road surface.")
    from app.schemas.segmentation import (
        SegmentBox,
        SegmentDetection,
        SegmentMask,
    )
    from app.schemas.unified_analysis import (
        PromptSegmentation,
        PromptStatus,
    )

    seg = PromptSegmentation(
        prompt="road",
        linked_finding_ids=["f1", "f2"],
        status=PromptStatus.OK,
        detections=[
            SegmentDetection(
                object_id="0",
                box=SegmentBox(x1=10, y1=20, x2=30, y2=40),
                mask=SegmentMask(
                    width=20, height=20, svg_path="M0 0Z", rle_counts="a"
                ),
            )
        ],
    )
    grouped = _impact([f1, f2], [seg])
    multi = [
        c for c in grouped["exposure_concerns"] if len(c.basis_finding_ids) > 1
    ]
    assert multi != []
    review = next(
        a
        for a in grouped["verification_actions"]
        if a.action_id == multi[0].verification_action_id
    )
    assert set(review.related_finding_ids) == set(multi[0].basis_finding_ids)
