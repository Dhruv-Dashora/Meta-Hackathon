"""Content-presentation reliability tests (no model calls).

Pins that safety-critical text is never cut mid-word or silently
dropped: long locations/descriptions survive verbatim from findings
through concerns, reviews, hazard summaries, and the exported dossier;
action titles are concise structured headings; missing fields degrade
honestly.
"""

import json

from app.agents.condition_assessment import excerpt_clause
from app.agents.impact_agent import ImpactAgent
from app.agents.report_content import (
    action_title,
    finding_review_texts,
    location_excerpt,
    scene_observed,
)
from app.agents.reporting_agent import ReportingAgent
from app.schemas.common import Confidence, EvidenceRef, Finding
from app.schemas.incident import GeoContext, GeoStatus
from app.schemas.segmentation import SegmentImageInfo
from app.schemas.unified_analysis import (
    PromptSegmentation,
    PromptStatus,
    UnifiedAnalysisResponse,
    WorkflowStatus,
)

EVIDENCE = "sha256:test-image"
LONG_LOCATION = (
    "lower third of the image along the northern roadside embankment "
    "directly beneath the fractured concrete retaining wall and above "
    "the partially obstructed mountain roadway where loose sediment "
    "has accumulated across both travel lanes near the bend marker"
)
assert len(LONG_LOCATION) > 200


def _finding(
    finding_id: str = "vision-1",
    label: str = "slope",
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


def _segmentation(
    prompt: str = "road",
    status: PromptStatus = PromptStatus.OK,
    linked: list[str] | None = None,
) -> PromptSegmentation:
    return PromptSegmentation(
        prompt=prompt,
        linked_finding_ids=["vision-1"] if linked is None else linked,
        status=status,
    )


def _geo_unavailable() -> GeoContext:
    return GeoContext(status=GeoStatus.UNAVAILABLE, note="none provided")


def _vision(
    findings: list[Finding], segmentations: list[PromptSegmentation]
) -> UnifiedAnalysisResponse:
    return UnifiedAnalysisResponse(
        incident_id="img-test",
        image=SegmentImageInfo(
            width=320, height=334, mime_type="image/png", evidence_id=EVIDENCE
        ),
        findings=findings,
        segmentations=segmentations,
        workflow_status=WorkflowStatus.COMPLETED,
    )


def _dossier(findings, segmentations, impact_error=None):
    vision = _vision(findings, segmentations)
    impact_data = None
    if impact_error is None:
        impact_data = dict(
            ImpactAgent().run(
                {
                    "findings": list(findings),
                    "segmentations": list(segmentations),
                    "geo_context": _geo_unavailable(),
                }
            ).data
        )
    return ReportingAgent().run(
        {
            "incident_id": vision.incident_id,
            "image": vision.image,
            "vision": vision,
            "impact_data": impact_data,
            "impact_error": impact_error,
            "geo_context": _geo_unavailable(),
            "trail": [],
        }
    ).data["dossier"]


def test_location_excerpt_returns_full_long_location():
    finding = _finding(description=f"Location in image: {LONG_LOCATION}")
    assert location_excerpt(finding) == LONG_LOCATION


def test_location_excerpt_joins_parts_without_cuts():
    finding = _finding(
        description=(
            "Observed: slide.\n"
            f"Affected feature: {LONG_LOCATION}\n"
            f"Location in image: {LONG_LOCATION}"
        )
    )
    excerpt = location_excerpt(finding)
    assert excerpt == f"{LONG_LOCATION} — {LONG_LOCATION}"
    assert excerpt.endswith("bend marker")


def test_location_excerpt_missing_lines_fall_back():
    observed_only = _finding(description="Observed: bare slope.")
    assert location_excerpt(observed_only) == "bare slope."
    empty = _finding(description="")
    assert location_excerpt(empty) == ""


def test_scene_observed_keeps_full_location_tail():
    finding = _finding(description=f"Location in image: {LONG_LOCATION}")
    observed = scene_observed([finding], [])
    assert LONG_LOCATION in observed
    assert "bend marker" in observed


def test_concern_condition_keeps_full_location():
    finding = _finding(
        "vision-1",
        "floodwater",
        "Observed: floodwater over the road.\n"
        f"Location in image: {LONG_LOCATION}",
    )
    result = ImpactAgent().run(
        {
            "findings": [finding],
            "segmentations": [],
            "geo_context": _geo_unavailable(),
        }
    )
    (concern,) = result.data["exposure_concerns"]
    assert LONG_LOCATION in concern.condition


def test_hazard_summary_keeps_full_first_line():
    long_line = f"Observed: {LONG_LOCATION} with active movement"
    finding = _finding("vision-1", "slope", long_line)
    result = ImpactAgent().run(
        {
            "findings": [finding],
            "segmentations": [],
            "geo_context": _geo_unavailable(),
        }
    )
    (hazard,) = result.data["observed_hazards"]
    assert hazard.summary == f"slope: {long_line}"


def test_rationale_excerpt_keeps_full_clause():
    clause = (
        "the road surface shows extensive longitudinal cracking with "
        "partial subsidence of the downhill shoulder and displaced "
        "guardrail posts along a fifty meter stretch"
    )
    assert excerpt_clause(clause) == clause


def test_finding_review_keeps_compound_location_verbatim():
    finding = _finding(
        "vision-1",
        "roadside embankment",
        "Observed: embankment slumping toward the road; material "
        "spread across the ditch.\n"
        "Affected feature: roadside embankment\n"
        f"Location in image: {LONG_LOCATION}",
    )
    _, what = finding_review_texts(finding)
    assert LONG_LOCATION in what
    assert "roadside embankment" in what
    assert "vision-1" in what


def test_action_titles_derive_from_task_type():
    assert (
        action_title("finding_review", "roadside embankment")
        == "Roadside Embankment Assessment"
    )
    assert action_title("finding_review", "") == "Observation Assessment"
    assert action_title("concern_review", "road") == "Road Review"
    assert action_title("concern_review", "") == "General Review"
    assert action_title("people_safety") == "People Safety Check"
    assert (
        action_title("segmentation_review", "river")
        == "River Segmentation Review"
    )
    assert action_title("segmentation_review", "") == "Segmentation Review"
    assert action_title("geo_context") == "Location Context Request"
    assert action_title("routine") == "Routine Review"
    # Unknown kinds degrade to a generic heading, never task slices.
    assert action_title("mystery", "road") == "Review Task"


def test_impact_actions_all_carry_titles():
    findings = [
        _finding(
            "vision-1",
            "roadside embankment",
            "Observed: floodwater over the road.\n"
            "Affected feature: roadside embankment\n"
            f"Location in image: {LONG_LOCATION}",
        ),
        _finding(
            "vision-2", "gathering", "Observed: people near the road."
        ),
    ]
    segmentations = [
        _segmentation("road", PromptStatus.FAILED, linked=["vision-1"]),
        _segmentation("river", PromptStatus.ZERO_MATCHES, linked=[]),
        _segmentation("debris", PromptStatus.SKIPPED, linked=[]),
    ]
    result = ImpactAgent().run(
        {
            "findings": findings,
            "segmentations": segmentations,
            "geo_context": _geo_unavailable(),
        }
    )
    actions = result.data["verification_actions"]
    assert actions != []
    assert all(a.title.strip() for a in actions)
    by_id = {a.action_id: a for a in actions}
    assert (
        by_id["verify-finding-vision-1"].title
        == "Roadside Embankment Assessment"
    )
    assert by_id["verify-people-vision-2"].title == "People Safety Check"
    assert by_id["verify-seg-road"].title == "Road Segmentation Review"
    assert by_id["verify-geo-context"].title == "Location Context Request"
    concern_titles = [
        a.title for a in actions if a.kind == "concern_review"
    ]
    assert concern_titles != []
    assert all(t.endswith("Review") for t in concern_titles)


def test_fallback_actions_carry_titles():
    dossier = _dossier(
        [_finding("vision-1", "slope", "Observed: bare slope.")],
        [],
        impact_error="impact_failed: boom.",
    )
    assert dossier.verification_actions != []
    assert all(a.title.strip() for a in dossier.verification_actions)
    by_id = {a.action_id: a for a in dossier.verification_actions}
    assert by_id["verify-impact-rerun"].title == "Routine Review"
    assert (
        by_id["verify-finding-vision-1"].title == "Slope Assessment"
    )


def test_dossier_json_keeps_long_content_and_titles():
    finding = _finding(
        "vision-1",
        "floodwater",
        "Observed: floodwater over the road.\n"
        f"Location in image: {LONG_LOCATION}",
    )
    dossier = _dossier([finding], [_segmentation()])
    body = json.loads(dossier.model_dump_json())
    assert LONG_LOCATION in body["situation_summary"]["observed"]
    assert all(a["title"].strip() for a in body["verification_actions"])
    assert LONG_LOCATION in json.dumps(body["verification_actions"])


def test_empty_description_degrades_honestly():
    finding = _finding("vision-1", "slope", "")
    action, what = finding_review_texts(finding)
    assert "slope" in action
    assert "vision-1" in what
    dossier = _dossier([finding], [])
    assert dossier.findings[0].description == ""
    assert "slope" in dossier.situation_summary.observed
