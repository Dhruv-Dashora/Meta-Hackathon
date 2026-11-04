"""Export-contract tests: the dossier must serialize completely to JSON.

Both exports (JSON download, print-to-PDF) operate on this serialized
dossier without model calls. These tests pin the full technical shape:
findings, impact, segmentation provenance + geometry, verification
priorities, uncertainty, and reuse markers.
"""

import json

from app.agents.impact_agent import ImpactAgent
from app.agents.reporting_agent import ReportingAgent
from app.schemas.common import Confidence, EvidenceRef, Finding
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
from app.schemas.incident import GeoContext, GeoStatus

EVIDENCE = "sha256:test-image"


def _finding() -> Finding:
    return Finding(
        finding_id="vision-1",
        label="floodwater",
        description="Observed: floodwater over the road.",
        confidence=Confidence(value=0.8),
        evidence_refs=[
            EvidenceRef(
                evidence_id=EVIDENCE, modality="image", uri_or_hash=EVIDENCE
            )
        ],
    )


def _vision() -> UnifiedAnalysisResponse:
    return UnifiedAnalysisResponse(
        incident_id="img-test",
        image=SegmentImageInfo(
            width=320, height=334, mime_type="image/png", evidence_id=EVIDENCE
        ),
        findings=[_finding()],
        segmentations=[
            PromptSegmentation(
                prompt="road",
                linked_finding_ids=["vision-1"],
                status=PromptStatus.OK,
                detections=[
                    SegmentDetection(
                        object_id="0",
                        box=SegmentBox(x1=10, y1=20, x2=30, y2=40),
                        mask=SegmentMask(
                            width=20,
                            height=20,
                            svg_path="M0 0L1 0L1 1Z",
                            rle_counts="abc",
                        ),
                    )
                ],
                provenance=PromptProvenance.AUTOMATIC,
            )
        ],
        workflow_status=WorkflowStatus.COMPLETED,
        user_targets=[],
        analysis_ref="anl_testref",
    )


def _dossier_dict() -> dict:
    vision = _vision()
    geo = GeoContext(status=GeoStatus.UNAVAILABLE, note="none provided")
    impact_data = dict(
        ImpactAgent().run(
            {
                "findings": list(vision.findings),
                "segmentations": list(vision.segmentations),
                "geo_context": geo,
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
            "geo_context": geo,
            "trail": [],
            "analysis_ref": "anl_testref",
            "vision_source": "cached_reuse",
        }
    )
    dossier = result.data["dossier"]
    return json.loads(dossier.model_dump_json())


def test_export_preserves_findings_and_provenance():
    body = _dossier_dict()
    assert body["incident_id"] == "img-test"
    assert body["findings"][0]["finding_id"] == "vision-1"
    assert body["findings"][0]["evidence_refs"][0]["evidence_id"] == EVIDENCE
    assert body["findings"][0]["confidence"]["calibrated"] is False
    assert body["analysis_ref"] == "anl_testref"
    assert body["vision_source"] == "cached_reuse"
    assert body["evidence_ledger"] != []


def test_export_preserves_segmentation_geometry():
    body = _dossier_dict()
    seg = body["segmentations"][0]
    assert seg["prompt"] == "road"
    assert seg["association"] == "prompt_trigger_only"
    assert seg["provenance"] == "automatic"
    box = seg["detections"][0]["box"]
    assert (box["x1"], box["y1"], box["x2"], box["y2"]) == (10, 20, 30, 40)
    mask = seg["detections"][0]["mask"]
    assert (mask["width"], mask["height"]) == (20, 20)
    assert mask["svg_path"] == "M0 0L1 0L1 1Z"
    assert mask["rle_counts"] == "abc"
    assert body["segmentation_summary"][0]["detection_count"] == 1


def test_export_preserves_impact_and_priorities():
    body = _dossier_dict()
    assert body["observed_hazards"] != []
    assert body["exposure_concerns"] != []
    assert all(c["status"] == "unverified" for c in body["exposure_concerns"])
    damage = {d["feature"]: d["category"] for d in body["damage_assessments"]}
    assert damage["road"] == "cannot_assess"
    assert all(d["provisional"] is True for d in body["damage_assessments"])
    rescue = body["rescue_priorities"]
    assert len(rescue) == 1
    assert rescue[0]["priority"] == "undetermined"
    assert rescue[0]["requires_human_review"] is True
    assert body["access_priorities"] != []
    assert body["review_priorities"] != []
    assert body["verification_actions"] != []


def test_export_preserves_uncertainty_and_gaps():
    body = _dossier_dict()
    headline = body["situation_summary"]["headline"]
    assert "floodwater" in headline
    assert "unconfirmed" in headline
    assert "finding(s)" not in headline
    assert "(s)" not in headline
    assert body["uncertainty_notes"] != []
    assert body["information_gaps"] != []
    assert body["agent_trail"] == []
    assert isinstance(body["warnings"], list)
