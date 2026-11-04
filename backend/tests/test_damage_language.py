"""Refined damage-language tests: professional narrative, full provenance.

The main damage narrative must read as an evidence-grounded field
report (infrastructure asset, directly observed condition, provisional
assessment, remaining uncertainty, recommended human verification) —
never as rule-engine mechanics. Finding ids, keyword-match talk, and
linkage reasoning stay out of the narrative; the structured basis ids
and JSON exports keep full provenance.

Deterministic text analysis only — no model clients involved.
"""

import json

from app.agents.condition_assessment import damage_assessments
from app.schemas.common import Confidence, EvidenceRef, Finding
from app.schemas.incident import DamageAssessment, DamageCategory

EVIDENCE = "sha256:test-image"

# Rule-mechanic phrasing that must never appear in the main narrative.
RULE_TELLS = (
    "Finding '",
    "describes",
    "linked to",
    "in one observation",
    "keyword",
    "cue",
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


def _category_for(description: str, family: str) -> DamageAssessment:
    assessments, _ = damage_assessments([_finding(description=description)])
    matches = [a for a in assessments if a.feature == family]
    assert len(matches) == 1
    return matches[0]


def _narrative(assessment: DamageAssessment) -> str:
    return " ".join(
        [
            assessment.observed_condition,
            assessment.rationale,
            assessment.uncertainty_note,
            assessment.recommended_verification,
        ]
    )


def test_positive_reads_hide_ids_and_rule_mechanics():
    assessment = _category_for("Observed: building collapsed.", "building")
    assert assessment.category == DamageCategory.APPARENT_MAJOR_DAMAGE
    narrative = _narrative(assessment)
    assert "vision-1" not in narrative
    for tell in RULE_TELLS:
        assert tell not in narrative
    assert "not an engineering finding" in assessment.rationale


def test_cannot_assess_hides_ids_and_rule_mechanics():
    assessment = _category_for("Observed: road.", "road")
    assert assessment.category == DamageCategory.CANNOT_ASSESS
    narrative = _narrative(assessment)
    assert "vision-1" not in narrative
    for tell in RULE_TELLS:
        assert tell not in narrative
    # Provenance stays structured, not in prose.
    assert assessment.basis_finding_ids == ["vision-1"]
    assert assessment.basis_evidence_ids == [EVIDENCE]


def test_debris_does_not_establish_structural_damage():
    assessment = _category_for(
        "Observed: debris around the building.", "building"
    )
    assert assessment.category == DamageCategory.POSSIBLE_DAMAGE
    assert assessment.condition_class == "surrounding_material"
    assert "debris" in assessment.observed_condition.lower()
    assert "building" in assessment.observed_condition.lower()
    assert "does not establish structural damage" in (
        assessment.uncertainty_note + assessment.recommended_verification
    )
    assert "structural integrity" in _narrative(assessment).lower() or (
        "whether the" in assessment.recommended_verification.lower()
    )


def test_inundation_distinguished_from_structural_damage():
    assessment = _category_for("Observed: road flooded.", "road")
    assert assessment.category == DamageCategory.POSSIBLE_DAMAGE
    assert assessment.condition_class == "inundation"
    combined = _narrative(assessment).lower()
    assert "water" in combined
    assert "does not" in combined and "structural damage" in combined


def test_obstruction_read_names_passage_not_structure():
    assessment = _category_for(
        "Observed: road blocked by landslide.", "road"
    )
    assert assessment.category == DamageCategory.POSSIBLE_DAMAGE
    assert assessment.condition_class == "obstruction"
    combined = _narrative(assessment).lower()
    assert "obstruct" in combined
    assert "whether the" in combined


def test_visible_damage_read_stays_severe_and_structured():
    assessment = _category_for("Observed: bridge collapsed.", "road")
    assert assessment.category == DamageCategory.APPARENT_MAJOR_DAMAGE
    assert assessment.condition_class == "visible_damage"
    assert "bridge" in assessment.observed_condition.lower()
    assert assessment.recommended_verification.strip() != ""
    assert assessment.uncertainty_note.strip() != ""


def test_refined_language_is_general_across_infrastructure():
    cases = [
        ("Observed: house collapsed.", "building", "house"),
        ("Observed: bridge cracked.", "road", "bridge"),
        ("Observed: truck damaged.", "vehicle", "truck"),
        ("Observed: transformer tilted.", "utility", "transformer"),
    ]
    for description, family, asset in cases:
        assessment = _category_for(description, family)
        narrative = _narrative(assessment)
        assert asset in assessment.observed_condition.lower()
        assert "vision-1" not in narrative
        for tell in RULE_TELLS:
            assert tell not in narrative
        assert assessment.recommended_verification.strip() != ""


def test_negation_and_hedging_language_preserved():
    intact = _category_for(
        "Observed: no visible collapse of the building.", "building"
    )
    assert intact.category == DamageCategory.NO_VISIBLE_DAMAGE
    assert "not confirmed structural safety" in intact.uncertainty_note
    assert "vision-1" not in _narrative(intact)
    hedged = _category_for(
        "Observed: possibly collapsed building.", "building"
    )
    assert hedged.category == DamageCategory.POSSIBLE_DAMAGE
    assert "uncertain wording" in hedged.rationale


def test_provenance_preserved_in_json_export():
    assessment = _category_for("Observed: debris around the building.", "building")
    body = json.loads(assessment.model_dump_json())
    assert body["basis_finding_ids"] == ["vision-1"]
    assert body["basis_evidence_ids"] == [EVIDENCE]
    assert body["observed_condition"].strip() != ""
    assert body["recommended_verification"].strip() != ""
    assert body["condition_class"] == "surrounding_material"
    assert body["provisional"] is True
