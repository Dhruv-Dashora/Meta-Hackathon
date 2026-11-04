"""Agent 1 human-observation coverage tests (no model calls).

Pins the strengthened vision prompt contract (three categories, distinct
people observations, uncertainty, no danger inference) and verifies the
existing planner, impact, and reporting stages handle new-style people
findings: visible groups, ambiguous figures, absent/negated people, and
people competing with other SAM targets.
"""

from app.agents.impact_agent import ImpactAgent
from app.agents.report_content import scene_headline
from app.agents.vision_agent import VISION_INSTRUCTION
from app.schemas.common import Confidence, EvidenceRef, Finding
from app.schemas.incident import GeoContext, GeoStatus, RescuePriority
from app.services.prompt_planner import MAX_SAM_PROMPTS, derive_sam_prompts

EVIDENCE = "sha256:test-image"


def _finding(
    finding_id: str = "vision-1",
    label: str = "scene",
    description: str = "Observed: scene.",
    confidence: float = 0.85,
) -> Finding:
    return Finding(
        finding_id=finding_id,
        label=label,
        description=description,
        confidence=Confidence(value=confidence),
        evidence_refs=[
            EvidenceRef(
                evidence_id=EVIDENCE, modality="image", uri_or_hash=EVIDENCE
            )
        ],
    )


def _group_finding() -> Finding:
    return _finding(
        "vision-1",
        "people observed",
        "Observed: group of five people standing on dry ground.\n"
        "Affected feature: roadside verge\n"
        "Location in image: lower right, near the road bend",
    )


def _impact(findings, segmentations=None):
    return ImpactAgent().run(
        {
            "findings": list(findings),
            "segmentations": list(segmentations or []),
            "geo_context": GeoContext(
                status=GeoStatus.UNAVAILABLE, note="none provided"
            ),
        }
    ).data


def test_prompt_examines_three_categories():
    assert "Environmental hazards" in VISION_INSTRUCTION
    assert "Infrastructure" in VISION_INSTRUCTION
    assert "Visible human presence" in VISION_INSTRUCTION
    assert "floodwater" in VISION_INSTRUCTION
    assert "landslide debris" in VISION_INSTRUCTION
    assert "roads" in VISION_INSTRUCTION


def test_prompt_requires_distinct_people_observations():
    assert "distinct finding" in VISION_INSTRUCTION
    assert '"people observed"' in VISION_INSTRUCTION
    assert "image-relative location" in VISION_INSTRUCTION
    assert "observable circumstances" in VISION_INSTRUCTION
    assert "Do not bury" in VISION_INSTRUCTION
    assert '"people" or "person"' in VISION_INSTRUCTION


def test_prompt_handles_uncertainty_without_forcing():
    assert "distant, obscured, or ambiguous" in VISION_INSTRUCTION
    assert "lower the confidence" in VISION_INSTRUCTION
    assert "record no people finding" in VISION_INSTRUCTION
    assert "uncertainty notes" in VISION_INSTRUCTION


def test_prompt_forbids_danger_inference_and_keeps_shape():
    assert "buried or trapped people" in VISION_INSTRUCTION
    assert (
        "Never infer injuries, entrapment, rescue needs" in VISION_INSTRUCTION
    )
    assert "future disasters" in VISION_INSTRUCTION
    for field in (
        '"label"',
        '"observed"',
        '"affected_feature"',
        '"location_in_image"',
        '"inferred_impact"',
        '"uncertainty_notes"',
    ):
        assert field in VISION_INSTRUCTION
    assert "uncalibrated triage signal" in VISION_INSTRUCTION
    assert '{"findings": []}' in VISION_INSTRUCTION


def test_visible_group_selects_people():
    plan = derive_sam_prompts([_group_finding()])
    # The location line also names the road bend, so both are
    # considered with people ranked first.
    assert [d.prompt for d in plan] == ["people", "road"]
    assert plan[0].matched_keywords == ["people"]
    assert plan[0].triggered_by == ["vision-1"]


def test_people_compete_within_cap():
    findings = [
        _group_finding(),
        _finding("vision-2", "slope", "Observed: debris on the slope."),
        _finding("vision-3", "damage", "Observed: road cracked."),
        _finding("vision-4", "house", "Observed: house intact."),
    ]
    plan = derive_sam_prompts(findings)
    assert len(plan) == MAX_SAM_PROMPTS
    assert [d.prompt for d in plan] == ["people", "debris", "road"]


def test_ambiguous_person_stays_considered():
    finding = _finding(
        "vision-1",
        "possible figure",
        "Observed: possible person, distant and unclear.\n"
        "Location in image: upper slope, far distance",
        confidence=0.35,
    )
    plan = derive_sam_prompts([finding])
    assert [d.prompt for d in plan] == ["people"]


def test_negated_and_absent_people_select_nothing():
    negated = _finding(
        "vision-1", "clear scene", "Observed: no people visible."
    )
    assert derive_sam_prompts([negated]) == []
    absent = _finding(
        "vision-1", "slope", "Observed: bare slope with rocks."
    )
    assert derive_sam_prompts([absent]) == []


def test_clear_group_yields_conditional_concern_and_routine_rescue():
    data = _impact([_group_finding()])
    (concern,) = [
        c for c in data["exposure_concerns"] if c.feature == "people"
    ]
    assert concern.condition.startswith("If ")
    assert concern.status == "unverified"
    assert "not confirmed" in concern.concern
    safety = [
        a for a in data["verification_actions"] if a.kind == "people_safety"
    ]
    assert len(safety) == 1
    (rescue,) = data["rescue_priorities"]
    assert rescue.priority == RescuePriority.LOW
    assert "no danger" in rescue.rationale.lower()
    assert rescue.requires_human_review is True


def test_presence_alone_never_escalates_to_high():
    finding = _finding(
        "vision-1",
        "people observed",
        "Observed: people standing near calm water.\n"
        "Location in image: river bank, mid-frame",
    )
    data = _impact([finding])
    assert all(
        r.priority != RescuePriority.HIGH for r in data["rescue_priorities"]
    )
    danger = _finding(
        "vision-2",
        "exposure",
        "Observed: people trapped under debris.",
    )
    data = _impact([finding, danger])
    assert RescuePriority.HIGH in [r.priority for r in data["rescue_priorities"]]


def test_ambiguous_person_stays_hedged_without_danger():
    finding = _finding(
        "vision-1",
        "possible figure",
        "Observed: possible person, distant and unclear.\n"
        "Location in image: upper slope, far distance",
        confidence=0.35,
    )
    data = _impact([finding])
    assert all(
        r.priority != RescuePriority.HIGH for r in data["rescue_priorities"]
    )
    (rescue,) = data["rescue_priorities"]
    assert rescue.priority == RescuePriority.LOW
    assert "no danger is indicated" in rescue.unknowns


def test_people_tasks_never_duplicate():
    first = _group_finding()
    second = _finding(
        "vision-2",
        "people observed",
        "Observed: two people walking on the road.\n"
        "Location in image: center frame",
    )
    data = _impact([first, second])
    safety = [
        a for a in data["verification_actions"] if a.kind == "people_safety"
    ]
    assert len(safety) == 2
    assert len({a.action_id for a in safety}) == 2
    people_concerns = [
        c for c in data["exposure_concerns"] if c.feature == "people"
    ]
    assert len(people_concerns) == 2
    single = _impact([first])
    assert (
        len(
            [
                a
                for a in single["verification_actions"]
                if a.kind == "people_safety"
            ]
        )
        == 1
    )
    negated = _finding(
        "vision-9", "clear scene", "Observed: no people visible."
    )
    empty = _impact([negated])
    assert [
        a for a in empty["verification_actions"] if a.kind == "people_safety"
    ] == []
    assert [
        c for c in empty["exposure_concerns"] if c.feature == "people"
    ] == []


def test_headline_avoids_people_label_stutter():
    headline = scene_headline([_group_finding()])
    assert headline.startswith("People observed; safety review needed")
    assert "(people observed)" not in headline
    roadside = _finding(
        "vision-1", "people near road", "Observed: people near road."
    )
    assert "(people near road)" in scene_headline([roadside])
