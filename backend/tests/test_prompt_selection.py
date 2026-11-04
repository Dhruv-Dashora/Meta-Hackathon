"""Operational prompt-selection tests (no model calls).

Covers floods, landslides, building damage, people observations, mixed
hazards, and no-hazard images with synthetic finding texts (not demo
outputs) to avoid overfitting.
"""

from app.schemas.common import Confidence, Finding
from app.schemas.unified_analysis import PromptProvenance
from app.services.prompt_planner import (
    MAX_SAM_PROMPTS,
    derive_sam_prompts,
    plan_sam_prompts,
)


def _finding(
    finding_id: str,
    label: str,
    description: str,
    confidence: float = 0.7,
) -> Finding:
    return Finding(
        finding_id=finding_id,
        label=label,
        description=description,
        confidence=Confidence(value=confidence),
    )


def test_flood_ranks_hazard_and_affected_road():
    findings = [
        _finding("f1", "flood", "Observed: floodwater over the road.")
    ]
    plan = derive_sam_prompts(findings)
    assert [d.prompt for d in plan] == ["river", "road"]
    assert all(d.provenance == PromptProvenance.AUTOMATIC for d in plan)


def test_landslide_debris_over_road_attempts_both():
    findings = [
        _finding(
            "f1", "slope", "Observed: landslide debris over the road."
        )
    ]
    plan = derive_sam_prompts(findings)
    # Primary hazard evidence and affected infrastructure tie in tier 2;
    # the equal-confidence tie breaks alphabetically.
    assert [d.prompt for d in plan] == ["debris", "road"]
    assert all(d.provenance == PromptProvenance.AUTOMATIC for d in plan)
    assert plan[0].triggered_by == ["f1"]


def test_landslide_debris_without_infrastructure_selects_debris():
    findings = [
        _finding(
            "f1",
            "landslide debris",
            "Observed: landslide debris on the hillside.",
            confidence=0.92,
        )
    ]
    plan = plan_sam_prompts(findings)
    assert [d.prompt for d in plan] == ["debris"]
    assert plan[0].provenance == PromptProvenance.AUTOMATIC
    assert plan[0].triggered_by == ["f1"]
    # Concrete observed noun only: no rocks/mud substitution, no road fallback.
    assert "road" not in [d.prompt for d in plan]


def test_building_damage_selects_building():
    findings = [
        _finding(
            "f1", "damage", "Observed: building collapsed into rubble."
        )
    ]
    plan = derive_sam_prompts(findings)
    # Collapsed structure plus its rubble pile (mapped to debris).
    assert [d.prompt for d in plan] == ["building", "debris"]


def test_people_outrank_neutral_infrastructure():
    findings = [
        _finding("f1", "scene", "Observed: people near the road.")
    ]
    plan = derive_sam_prompts(findings)
    assert [d.prompt for d in plan] == ["people", "road"]


def test_people_in_danger_rank_first():
    findings = [
        _finding(
            "f1",
            "exposure",
            "Observed: people stranded in floodwater near houses.",
        )
    ]
    plan = derive_sam_prompts(findings)
    assert plan[0].prompt == "people"
    assert "river" in [d.prompt for d in plan]
    assert "building" in [d.prompt for d in plan]


def test_mixed_hazards_cap_at_three_with_people_first():
    findings = [
        _finding(
            "f1",
            "scene",
            "Observed: people by the flooded road, "
            "damaged building, river, vehicle.",
        )
    ]
    plan = derive_sam_prompts(findings)
    assert len(plan) == MAX_SAM_PROMPTS
    assert plan[0].prompt == "people"
    # Vehicle is lowest operational priority and drops out first.
    assert "vehicle" not in [d.prompt for d in plan]


def test_no_hazard_no_prompts_no_exploratory():
    findings = [
        _finding("f1", "smoke", "Observed: smoke in the distance.")
    ]
    assert derive_sam_prompts(findings) == []
    assert plan_sam_prompts(findings) == []


def test_empty_road_neutral_still_selected_without_exploratory():
    findings = [_finding("f1", "scene", "Observed: empty road.")]
    plan = plan_sam_prompts(findings)
    assert [d.prompt for d in plan] == ["road"]
    assert plan[0].provenance == PromptProvenance.AUTOMATIC


def test_inferred_only_mention_does_not_trigger():
    findings = [
        _finding(
            "f1",
            "field",
            "Observed: clear field.\nInferred impact: road could flood.",
        )
    ]
    assert derive_sam_prompts(findings) == []
    assert plan_sam_prompts(findings) == []


def test_conditional_observation_does_not_trigger():
    findings = [
        _finding(
            "f1",
            "slope",
            "Observed: road would be at risk if the slope fails.",
        )
    ]
    assert derive_sam_prompts(findings) == []
    assert plan_sam_prompts(findings) == []


def test_disclaimer_does_not_trigger_river():
    findings = [
        _finding(
            "f1", "advice", "Observed: do not approach the water."
        )
    ]
    assert derive_sam_prompts(findings) == []
    assert plan_sam_prompts(findings) == []


def test_confidence_orders_within_tier_without_threshold():
    low_river = _finding(
        "f1", "flood", "Observed: floodwater in the field.", confidence=0.2
    )
    high_building = _finding(
        "f2",
        "damage",
        "Observed: building cracked by impact.",
        confidence=0.9,
    )
    plan = derive_sam_prompts([low_river, high_building])
    # Both tier-2 (hazard / affected infrastructure); higher confidence first.
    assert [d.prompt for d in plan] == ["building", "river"]
    # Low confidence alone never suppresses a positive observation.
    assert derive_sam_prompts([low_river])[0].prompt == "river"


def test_user_targets_stay_first_within_cap():
    findings = [
        _finding("f1", "scene", "Observed: people by the river.")
    ]
    plan = plan_sam_prompts(findings, user_targets=["debris"])
    assert [d.prompt for d in plan] == ["debris", "people", "river"]
    assert plan[0].provenance == PromptProvenance.USER_REQUESTED
    assert plan[1].provenance == PromptProvenance.AUTOMATIC


def test_house_dedupes_to_building_user_wording_wins():
    findings = [
        _finding("f1", "scene", "Observed: building near road.")
    ]
    plan = plan_sam_prompts(findings, user_targets=["house"])
    assert [d.prompt for d in plan] == ["building", "road"]
    assert plan[0].requested_as == "house"


def test_uncertain_observation_still_triggers():
    findings = [
        _finding(
            "f1", "maybe", "Observed: possible road under mud, uncertain."
        )
    ]
    plan = derive_sam_prompts(findings)
    assert [d.prompt for d in plan] == ["road"]


def test_exploratory_never_for_people_and_never_without_hazard():
    # People observed without hazard: no infrastructure gap-fill.
    people_only = [
        _finding("f1", "scene", "Observed: people in a field.")
    ]
    plan = plan_sam_prompts(people_only)
    assert [d.prompt for d in plan] == ["people"]
    # No findings at all: nothing to justify exploration.
    assert plan_sam_prompts([]) == []


def test_rubble_maps_to_debris_prompt():
    findings = [
        _finding(
            "f1", "rubble", "Observed: rubble from a collapsed wall."
        )
    ]
    plan = derive_sam_prompts(findings)
    assert [d.prompt for d in plan] == ["debris"]
    assert plan[0].matched_keywords == ["rubble"]
    assert plan[0].provenance == PromptProvenance.AUTOMATIC


def test_no_rocks_or_mud_substitution_for_debris():
    findings = [
        _finding(
            "f1", "slope", "Observed: landslide debris on the slope."
        )
    ]
    plan = derive_sam_prompts(findings)
    assert [d.prompt for d in plan] == ["debris"]
    assert "rocks" not in [d.prompt for d in plan]
    assert "mud" not in [d.prompt for d in plan]
    assert "landslide" not in [d.prompt for d in plan]


def test_floodwater_without_infrastructure_selects_river_only():
    findings = [
        _finding(
            "f1", "flood", "Observed: floodwater across the fields."
        )
    ]
    plan = plan_sam_prompts(findings)
    assert [d.prompt for d in plan] == ["river"]
    assert plan[0].provenance == PromptProvenance.AUTOMATIC


def test_floodwater_around_houses_selects_river_and_building():
    findings = [
        _finding(
            "f1", "flood", "Observed: floodwater around houses."
        )
    ]
    plan = derive_sam_prompts(findings)
    # Affected infrastructure ties with the hazard in tier 2; the
    # equal-confidence tie breaks alphabetically (no rigid hazard-first).
    assert [d.prompt for d in plan] == ["building", "river"]


def test_damaged_bridge_selects_bridge_and_river():
    findings = [
        _finding(
            "f1", "bridge", "Observed: bridge cracked over the river."
        )
    ]
    plan = derive_sam_prompts(findings)
    assert [d.prompt for d in plan] == ["bridge", "river"]


def test_neutral_bridge_ranks_below_hazard():
    findings = [
        _finding("f1", "bridge", "Observed: bridge over the river.")
    ]
    plan = derive_sam_prompts(findings)
    assert [d.prompt for d in plan] == ["river", "bridge"]


def test_people_near_hazard_rank_first():
    findings = [
        _finding(
            "f1", "exposure", "Observed: people near landslide debris."
        )
    ]
    plan = derive_sam_prompts(findings)
    assert [d.prompt for d in plan] == ["people", "debris"]


def test_people_trapped_under_debris_rank_first():
    findings = [
        _finding(
            "f1",
            "exposure",
            "Observed: people trapped under debris.",
        )
    ]
    plan = derive_sam_prompts(findings)
    assert [d.prompt for d in plan] == ["people", "debris"]
    assert plan[0].provenance == PromptProvenance.AUTOMATIC


def test_competing_targets_cap_with_people_first():
    findings = [
        _finding(
            "f1",
            "scene",
            "Observed: people by the flooded road, "
            "damaged building, debris, vehicle.",
        )
    ]
    plan = derive_sam_prompts(findings)
    assert len(plan) == MAX_SAM_PROMPTS
    assert [d.prompt for d in plan] == ["people", "building", "debris"]
    assert "vehicle" not in [d.prompt for d in plan]


def test_affected_infrastructure_beats_low_confidence_debris():
    damaged_building = _finding(
        "f1",
        "damage",
        "Observed: building collapsed.",
        confidence=0.9,
    )
    faint_debris = _finding(
        "f2",
        "slope",
        "Observed: debris on the far slope.",
        confidence=0.2,
    )
    plan = derive_sam_prompts([faint_debris, damaged_building])
    # Same tier: confidence decides, so a credible structure beats faint
    # debris instead of hazards always ranking first.
    assert [d.prompt for d in plan] == ["building", "debris"]


def test_uncertain_debris_still_triggers():
    findings = [
        _finding(
            "f1",
            "maybe",
            "Observed: possible debris on the slope, uncertain.",
        )
    ]
    plan = derive_sam_prompts(findings)
    assert [d.prompt for d in plan] == ["debris"]


def test_negated_debris_suppresses_only_debris():
    findings = [
        _finding(
            "f1", "clear", "Observed: no landslide debris visible."
        )
    ]
    assert derive_sam_prompts(findings) == []
    assert plan_sam_prompts(findings) == []
    mixed = [
        _finding(
            "f1", "clear", "Observed: no debris, road clear."
        )
    ]
    assert [d.prompt for d in derive_sam_prompts(mixed)] == ["road"]


def test_unsupported_mud_only_yields_no_prompt():
    findings = [
        _finding("f1", "slope", "Observed: mud across the hillside.")
    ]
    assert derive_sam_prompts(findings) == []
    assert plan_sam_prompts(findings) == []


def test_bare_landslide_event_yields_no_prompt():
    findings = [
        _finding(
            "f1", "slope", "Observed: landslide on the hillside."
        )
    ]
    # Event noun without segmentable material or infrastructure: no
    # automatic prompt and no road fallback.
    assert derive_sam_prompts(findings) == []
    assert plan_sam_prompts(findings) == []


def test_scattered_rocks_only_yield_no_prompt():
    findings = [
        _finding(
            "f1", "slope", "Observed: scattered rocks on the slope."
        )
    ]
    assert derive_sam_prompts(findings) == []
    assert plan_sam_prompts(findings) == []


def test_inferred_debris_does_not_trigger():
    findings = [
        _finding(
            "f1",
            "slope",
            "Observed: clear slope.\nInferred impact: debris could slide.",
        )
    ]
    assert derive_sam_prompts(findings) == []
    assert plan_sam_prompts(findings) == []


def test_user_target_outranks_automatic_debris():
    findings = [
        _finding(
            "f1", "slope", "Observed: landslide debris on the slope."
        )
    ]
    plan = plan_sam_prompts(findings, user_targets=["bridge"])
    assert [d.prompt for d in plan] == ["bridge", "debris"]
    assert plan[0].provenance == PromptProvenance.USER_REQUESTED
    assert plan[1].provenance == PromptProvenance.AUTOMATIC


def test_user_rubble_dedupes_against_automatic_debris():
    findings = [
        _finding("f1", "slope", "Observed: debris on the slope.")
    ]
    plan = plan_sam_prompts(findings, user_targets=["rubble"])
    assert [d.prompt for d in plan] == ["debris"]
    assert plan[0].provenance == PromptProvenance.USER_REQUESTED
    assert plan[0].requested_as == "rubble"


def test_user_overpass_dedupes_against_automatic_bridge():
    findings = [
        _finding("f1", "bridge", "Observed: bridge over the river.")
    ]
    plan = plan_sam_prompts(findings, user_targets=["overpass"])
    assert [d.prompt for d in plan] == ["bridge", "river"]
    assert plan[0].requested_as == "overpass"


def test_human_made_compound_does_not_trigger_people():
    findings = [
        _finding(
            "f1",
            "embankment",
            "Observed: human-made embankment along the road.",
        )
    ]
    plan = derive_sam_prompts(findings)
    assert [d.prompt for d in plan] == ["road"]


def test_pedestrian_bridge_does_not_trigger_people():
    findings = [
        _finding(
            "f1",
            "bridge",
            "Observed: pedestrian bridge over the stream.",
        )
    ]
    plan = derive_sam_prompts(findings)
    assert "people" not in [d.prompt for d in plan]
    assert [d.prompt for d in plan] == ["river", "bridge"]


def test_pedestrian_person_still_triggers():
    on_bridge = [
        _finding(
            "f1", "scene", "Observed: pedestrian on the bridge."
        )
    ]
    assert derive_sam_prompts(on_bridge)[0].prompt == "people"
    crossing = [
        _finding(
            "f1", "scene", "Observed: pedestrian crossing the road."
        )
    ]
    assert derive_sam_prompts(crossing)[0].prompt == "people"


def test_label_assertion_vetoed_by_description_denial():
    findings = [
        _finding(
            "f1", "people", "Observed: no people visible in the frame."
        )
    ]
    assert derive_sam_prompts(findings) == []
    assert plan_sam_prompts(findings) == []


def test_label_assertion_stands_without_denial():
    findings = [
        _finding("f1", "river", "Observed: calm scene at dusk.")
    ]
    plan = derive_sam_prompts(findings)
    assert [d.prompt for d in plan] == ["river"]


def test_denial_never_vetoes_another_finding():
    label_only = _finding("f1", "people", "Observed: figures at dusk.")
    denying = _finding(
        "f2", "field", "Observed: no people in the field."
    )
    plan = derive_sam_prompts([label_only, denying])
    assert [d.prompt for d in plan] == ["people"]
    assert plan[0].triggered_by == ["f1"]


def test_modal_danger_keeps_safety_recall():
    findings = [
        _finding(
            "f1", "exposure", "Observed: people may be trapped inside."
        )
    ]
    plan = derive_sam_prompts(findings)
    # Hedged danger still attempts people first: missing a real person
    # costs more than a wasted prompt.
    assert [d.prompt for d in plan] == ["people"]


def test_exploratory_only_for_obscured_access_without_automatic():
    buried = [
        _finding(
            "f1", "slope", "Observed: valley floor buried in mud."
        )
    ]
    plan = plan_sam_prompts(buried)
    assert [d.prompt for d in plan] == ["road"]
    assert plan[0].provenance == PromptProvenance.EXPLORATORY
    # An automatic prompt already covers the scene: no gap-fill.
    covered = [
        _finding("f1", "slope", "Observed: debris buried the slope.")
    ]
    plan = plan_sam_prompts(covered)
    assert [d.prompt for d in plan] == ["debris"]
    assert plan[0].provenance == PromptProvenance.AUTOMATIC
