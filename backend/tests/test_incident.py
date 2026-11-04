"""Incident orchestration tests (mocked vision — never calls live APIs)."""

import io
import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.agents.base import AgentResult
from app.agents.impact_agent import ImpactAgent
from app.agents.reporting_agent import ReportingAgent
from app.core.errors import SentinelError
from app.main import app
from app.orchestrator import orchestrator as orch_module
from app.orchestrator.orchestrator import Orchestrator
from app.orchestrator.validators import (
    validate_exposure_concerns,
    validate_findings,
    validate_ledger,
)
from app.schemas.common import Confidence, EvidenceRef, Finding
from app.schemas.incident import (
    ExposureConcern,
    GeoContext,
    GeoStatus,
    VerificationAction,
)
from app.schemas.segmentation import SegmentBox, SegmentDetection, SegmentImageInfo, SegmentMask
from app.schemas.unified_analysis import (
    PromptSegmentation,
    PromptStatus,
    UnifiedAnalysisResponse,
    WorkflowStatus,
)
from app.services.geo_service import GeoValidationError, validate_geojson_bytes

client = TestClient(app)

PNG_EVIDENCE = "sha256:test-image"
GIF_BYTES = b"GIF89a" + b"\x00" * 32


def _png_bytes(width: int = 320, height: int = 334) -> bytes:
    image = Image.new("RGB", (width, height), color=(120, 130, 140))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _finding(
    finding_id: str = "vision-1-abc",
    label: str = "floodwater",
    description: str = "Observed: floodwater over the road.",
) -> Finding:
    return Finding(
        finding_id=finding_id,
        label=label,
        description=description,
        confidence=Confidence(value=0.8),
        evidence_refs=[
            EvidenceRef(
                evidence_id=PNG_EVIDENCE,
                modality="image",
                uri_or_hash=PNG_EVIDENCE,
            )
        ],
    )


def _segmentation(
    prompt: str = "road",
    status: PromptStatus = PromptStatus.OK,
    n_detections: int = 1,
    error: str | None = None,
) -> PromptSegmentation:
    return PromptSegmentation(
        prompt=prompt,
        linked_finding_ids=["vision-1-abc"],
        status=status,
        error=error,
        detections=[
            SegmentDetection(
                object_id=str(i),
                box=SegmentBox(x1=10, y1=20, x2=30, y2=40),
                mask=SegmentMask(width=20, height=20, svg_path="M0 0Z", rle_counts="a"),
            )
            for i in range(n_detections)
        ],
    )


def _vision_response(
    findings: list[Finding] | None = None,
    segmentations: list[PromptSegmentation] | None = None,
    status: WorkflowStatus = WorkflowStatus.COMPLETED,
) -> UnifiedAnalysisResponse:
    return UnifiedAnalysisResponse(
        incident_id="img-test123",
        image=SegmentImageInfo(
            width=320, height=334, mime_type="image/png", evidence_id=PNG_EVIDENCE
        ),
        findings=findings if findings is not None else [_finding()],
        prompt_plan=[],
        segmentations=segmentations if segmentations is not None else [_segmentation()],
        workflow_status=status,
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


# --- impact agent ---


def test_impact_separates_observed_and_conditional():
    result = ImpactAgent().run(
        {
            "findings": [_finding()],
            "segmentations": [_segmentation()],
            "geo_context": _geo_unavailable(),
        }
    )
    assert result.errors == []
    hazards = result.data["observed_hazards"]
    assert len(hazards) == 1
    assert hazards[0].finding_ids == ["vision-1-abc"]
    assert hazards[0].evidence_ids == [PNG_EVIDENCE]
    assert "floodwater" in hazards[0].summary
    concerns = result.data["exposure_concerns"]
    assert concerns != []
    actions = {a.action_id for a in result.data["verification_actions"]}
    for concern in concerns:
        assert concern.condition.strip() != ""
        assert concern.status == "unverified"
        assert concern.basis_finding_ids != []
        assert concern.basis_evidence_ids != []
        assert concern.verification_action_id in actions
    assert validate_exposure_concerns(concerns, result.data["verification_actions"]) == []


def test_impact_preserves_risk_words_in_observations():
    finding = _finding(description="Observed: blocked road with debris.")
    result = ImpactAgent().run(
        {"findings": [finding], "segmentations": [], "geo_context": _geo_unavailable()}
    )
    assert "blocked" in result.data["observed_hazards"][0].summary


def test_impact_geo_paths():
    without_geo = ImpactAgent().run(
        {"findings": [_finding()], "segmentations": [], "geo_context": _geo_unavailable()}
    )
    ids = [a.action_id for a in without_geo.data["verification_actions"]]
    assert "verify-geo-context" in ids
    with_geo = ImpactAgent().run(
        {"findings": [_finding()], "segmentations": [], "geo_context": _geo_provided()}
    )
    ids = [a.action_id for a in with_geo.data["verification_actions"]]
    assert "verify-geo-context" not in ids


def test_impact_people_finding_is_high_priority():
    finding = _finding(description="Observed: people near the river bank.")
    result = ImpactAgent().run(
        {"findings": [finding], "segmentations": [], "geo_context": _geo_unavailable()}
    )
    people = [
        a
        for a in result.data["verification_actions"]
        if a.action_id == f"verify-people-{finding.finding_id}"
    ]
    assert len(people) == 1
    assert people[0].priority == "high"


def test_impact_failed_and_zero_prompts_become_actions():
    result = ImpactAgent().run(
        {
            "findings": [_finding()],
            "segmentations": [
                _segmentation("road", PromptStatus.FAILED, 0, "sam31_timeout: slow."),
                _segmentation("river", PromptStatus.ZERO_MATCHES, 0),
            ],
            "geo_context": _geo_unavailable(),
        }
    )
    # No executed detections: no SAM-based concerns synthesized.
    assert result.data["exposure_concerns"] != []  # finding-based only
    assert all("segmented" not in c.condition for c in result.data["exposure_concerns"])
    ids = [a.action_id for a in result.data["verification_actions"]]
    assert "verify-seg-road" in ids
    assert "verify-seg-river" in ids


# --- validators ---


def _concern(**overrides) -> ExposureConcern:
    base = dict(
        concern_id="exp-1",
        condition="If the road is affected",
        concern="then access may be affected; severity is not confirmed",
        basis_finding_ids=["vision-1-abc"],
        basis_evidence_ids=[PNG_EVIDENCE],
        verification_action_id="verify-exp-1",
    )
    base.update(overrides)
    return ExposureConcern(**base)


def _action(action_id: str = "verify-exp-1") -> VerificationAction:
    return VerificationAction(
        action_id=action_id, action="Verify.", reason="Unverified.", priority="high"
    )


def test_validators_accept_qualified_blockage_statement():
    concern = _concern(
        condition="If the road is blocked",
        concern="then access may be affected; road blockage is not confirmed",
    )
    assert validate_exposure_concerns([concern], [_action()]) == []


def test_validators_reject_affirmative_conclusions():
    bad = _concern(
        condition="The road is blocked",
        concern="Access is cut off and severity is high",
    )
    errors = validate_exposure_concerns([bad], [_action()])
    assert any("no conditional language" in e for e in errors)


def test_validators_reject_missing_structure():
    assert validate_exposure_concerns(
        [_concern(condition="  ")], [_action()]
    ) != []
    assert validate_exposure_concerns(
        [_concern(basis_finding_ids=[])], [_action()]
    ) != []
    assert validate_exposure_concerns(
        [_concern(verification_action_id="missing")], [_action()]
    ) != []


def test_validate_findings_and_ledger():
    assert validate_findings([_finding()]) == []
    bad = _finding()
    bad.evidence_refs = []
    assert validate_findings([bad]) != []
    assert validate_ledger([PNG_EVIDENCE], {PNG_EVIDENCE}) == []
    assert validate_ledger(["sha256:nope"], {PNG_EVIDENCE}) != []


# --- geo validation ---


def _feature_collection() -> bytes:
    return json.dumps(
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [85.6, 28.2]},
                    "properties": {},
                },
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[85.6, 28.2], [85.7, 28.3]],
                    },
                    "properties": {},
                },
            ],
        }
    ).encode()


def test_geojson_valid_collection():
    info = validate_geojson_bytes(_feature_collection(), max_bytes=1024 * 512)
    assert info.feature_count == 2
    assert info.geometry_types == ["LineString", "Point"]


def test_geojson_single_feature_and_bare_geometry():
    feature = json.dumps(
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [85.6, 28.2]},
            "properties": {},
        }
    ).encode()
    assert validate_geojson_bytes(feature, max_bytes=1024).feature_count == 1
    bare = json.dumps({"type": "Point", "coordinates": [85.6, 28.2]}).encode()
    info = validate_geojson_bytes(bare, max_bytes=1024)
    assert info.geometry_types == ["Point"]


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        (b"not json", "invalid_geojson"),
        (b"", "empty_geojson"),
        (json.dumps({"type": "Catalog"}).encode(), "invalid_geojson"),
        (
            json.dumps(
                {"type": "Point", "coordinates": [999.0, 28.2]}
            ).encode(),
            "invalid_geojson",
        ),
        (
            json.dumps({"type": "Point", "coordinates": ["x", 1]}).encode(),
            "invalid_geojson",
        ),
    ],
)
def test_geojson_rejects_malformed(payload, code):
    with pytest.raises(GeoValidationError) as exc_info:
        validate_geojson_bytes(payload, max_bytes=1024)
    assert exc_info.value.code == code
    assert exc_info.value.status_code == 400


def test_geojson_rejects_oversize():
    with pytest.raises(GeoValidationError) as exc_info:
        validate_geojson_bytes(_feature_collection(), max_bytes=8)
    assert exc_info.value.code == "geojson_too_large"
    assert exc_info.value.status_code == 413


# --- reporting agent ---


def _impact_data_for(vision: UnifiedAnalysisResponse, geo: GeoContext) -> dict:
    return ImpactAgent().run(
        {
            "findings": list(vision.findings),
            "segmentations": list(vision.segmentations),
            "geo_context": geo,
        }
    ).data


def test_reporting_builds_completed_dossier():
    vision = _vision_response()
    geo = _geo_unavailable()
    result = ReportingAgent().run(
        {
            "incident_id": vision.incident_id,
            "image": vision.image,
            "vision": vision,
            "impact_data": _impact_data_for(vision, geo),
            "impact_error": None,
            "geo_context": geo,
            "trail": [],
        }
    )
    dossier = result.data["dossier"]
    assert dossier.incident_status.value == "completed"
    assert dossier.vision_workflow_status == WorkflowStatus.COMPLETED
    assert dossier.findings != []
    assert dossier.segmentation_summary[0].detection_count == 1
    assert dossier.observed_hazards != []
    assert dossier.exposure_concerns != []
    assert dossier.verification_actions != []
    assert dossier.uncertainty_notes != []
    assert PNG_EVIDENCE in [e.evidence_id for e in dossier.evidence_ledger]


def test_reporting_degraded_on_impact_failure():
    vision = _vision_response()
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
    assert dossier.incident_status.value == "partial"
    assert dossier.findings != []
    assert dossier.segmentation_summary != []
    assert dossier.exposure_concerns == []
    assert any("impact_unavailable" in w for w in dossier.warnings)
    assert any(
        a.action_id == "verify-impact-rerun" for a in dossier.verification_actions
    )
    assert any(
        "verify-finding-vision-1-abc" == a.action_id
        for a in dossier.verification_actions
    )


def test_reporting_drops_rejected_concerns():
    vision = _vision_response()
    geo = _geo_unavailable()
    data = _impact_data_for(vision, geo)
    data["exposure_concerns"].append(
        _concern(
            concern_id="exp-bad",
            condition="The road is blocked",
            concern="Access is cut off",
            verification_action_id="verify-exp-bad",
        )
    )
    data["verification_actions"].append(_action("verify-exp-bad"))
    result = ReportingAgent().run(
        {
            "incident_id": vision.incident_id,
            "image": vision.image,
            "vision": vision,
            "impact_data": data,
            "impact_error": None,
            "geo_context": geo,
            "trail": [],
        }
    )
    dossier = result.data["dossier"]
    assert "exp-bad" not in [c.concern_id for c in dossier.exposure_concerns]
    assert any("rejected_concern:exp-bad" in w for w in dossier.warnings)
    assert dossier.incident_status.value == "completed"


# --- orchestrator ---


def _validated_image():
    from app.services import media_service

    png = _png_bytes()
    return media_service.validate_image_bytes(png, max_bytes=10 * 1024 * 1024)


def test_orchestrator_order_and_trail(monkeypatch):
    calls: list[str] = []
    vision = _vision_response()

    def fake_vision(validated, width, height):
        calls.append("vision")
        return vision

    monkeypatch.setattr(orch_module, "run_unified_analysis", fake_vision)
    dossier = Orchestrator().run_workflow(
        "disaster_response",
        {
            "validated": _validated_image(),
            "width": 320,
            "height": 334,
            "geo_context": _geo_unavailable(),
        },
    )
    assert calls == ["vision"]
    assert [t.agent for t in dossier.agent_trail] == ["vision", "impact", "reporting"]
    assert all(t.status.value == "ok" for t in dossier.agent_trail)
    assert all(t.duration_s >= 0 for t in dossier.agent_trail)
    assert dossier.incident_status.value == "completed"


def test_orchestrator_impact_failure_degrades(monkeypatch):
    vision = _vision_response()
    monkeypatch.setattr(
        orch_module, "run_unified_analysis", lambda v, w, h: vision
    )

    class _Boom:
        def run(self, payload):
            raise RuntimeError("boom")

    monkeypatch.setattr(orch_module, "ImpactAgent", _Boom)
    dossier = Orchestrator().run_workflow(
        "disaster_response",
        {
            "validated": _validated_image(),
            "width": 320,
            "height": 334,
            "geo_context": _geo_unavailable(),
        },
    )
    assert dossier.incident_status.value == "partial"
    assert dossier.findings != []
    assert dossier.exposure_concerns == []
    impact_entry = [t for t in dossier.agent_trail if t.agent == "impact"][0]
    assert impact_entry.status.value == "failed"
    assert "impact_failed: RuntimeError" in impact_entry.notes
    assert "boom" not in impact_entry.notes


def test_orchestrator_reporting_failure_is_safe_error(monkeypatch):
    vision = _vision_response()
    monkeypatch.setattr(
        orch_module, "run_unified_analysis", lambda v, w, h: vision
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
                "width": 320,
                "height": 334,
                "geo_context": _geo_unavailable(),
            },
        )
    assert exc_info.value.code == "reporting_failed"
    assert "img-test123" in exc_info.value.message
    assert "boom" not in exc_info.value.message
    assert "Traceback" not in exc_info.value.message


def test_orchestrator_vision_failure_propagates(monkeypatch):
    def fake_vision(validated, width, height):
        raise SentinelError("vision_failed", "muse_spark_timeout: slow.")

    monkeypatch.setattr(orch_module, "run_unified_analysis", fake_vision)
    with pytest.raises(SentinelError) as exc_info:
        Orchestrator().run_workflow(
            "disaster_response",
            {
                "validated": _validated_image(),
                "width": 320,
                "height": 334,
                "geo_context": _geo_unavailable(),
            },
        )
    assert exc_info.value.code == "vision_failed"


# --- incident route ---


def _upload_incident(png: bytes, form: dict | None = None, files: list | None = None):
    return client.post(
        "/api/disaster-response/assess-incident",
        files=[("image", ("scene.png", png, "image/png"))] + (files or []),
        data=form or {},
    )


def test_incident_route_success_with_geo(monkeypatch):
    vision = _vision_response()
    seen: dict = {}

    def fake_vision(validated, width, height):
        seen["called"] = True
        return vision

    monkeypatch.setattr(orch_module, "run_unified_analysis", fake_vision)
    resp = _upload_incident(
        _png_bytes(),
        form={
            "location_label": "Rasuwa corridor",
            "latitude": "28.2",
            "longitude": "85.6",
        },
        files=[("geojson", ("area.geojson", _feature_collection(), "application/json"))],
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["incident_status"] == "completed"
    assert body["vision_workflow_status"] == "completed"
    assert body["geo_context"]["status"] == "provided"
    assert body["geo_context"]["provenance"] == "operator-provided, unverified"
    assert body["geo_context"]["geojson_feature_count"] == 2
    assert [t["agent"] for t in body["agent_trail"]] == ["vision", "impact", "reporting"]
    assert seen.get("called") is True


def test_incident_route_geo_unavailable(monkeypatch):
    monkeypatch.setattr(
        orch_module, "run_unified_analysis", lambda v, w, h: _vision_response()
    )
    resp = _upload_incident(_png_bytes())
    assert resp.status_code == 200
    body = resp.json()
    assert body["geo_context"]["status"] == "unavailable"
    assert any(
        a["action_id"] == "verify-geo-context" for a in body["verification_actions"]
    )


def test_incident_route_rejects_bad_geojson_without_vision(monkeypatch):
    called: list[bool] = []
    monkeypatch.setattr(
        orch_module,
        "run_unified_analysis",
        lambda v, w, h: called.append(True) or _vision_response(),
    )
    resp = _upload_incident(
        _png_bytes(),
        files=[("geojson", ("bad.geojson", b"not json", "application/json"))],
    )
    assert resp.status_code == 400
    assert "invalid_geojson" in resp.json()["detail"]
    assert called == []


def test_incident_route_rejects_partial_coords(monkeypatch):
    monkeypatch.setattr(
        orch_module, "run_unified_analysis", lambda v, w, h: _vision_response()
    )
    resp = _upload_incident(_png_bytes(), form={"latitude": "28.2"})
    assert resp.status_code == 400
    assert "incomplete_geo" in resp.json()["detail"]
    resp = _upload_incident(_png_bytes(), form={"latitude": "north"})
    assert resp.status_code == 400
    assert "invalid_geo" in resp.json()["detail"]


def test_incident_route_rejects_bad_image_without_vision(monkeypatch):
    called: list[bool] = []
    monkeypatch.setattr(
        orch_module,
        "run_unified_analysis",
        lambda v, w, h: called.append(True) or _vision_response(),
    )
    resp = _upload_incident(GIF_BYTES)
    assert resp.status_code == 400
    assert called == []


def test_incident_route_vision_failure_is_502(monkeypatch):
    def fake_vision(validated, width, height):
        raise SentinelError("vision_failed", "muse_spark_timeout: slow.")

    monkeypatch.setattr(orch_module, "run_unified_analysis", fake_vision)
    resp = _upload_incident(_png_bytes())
    assert resp.status_code == 502


def test_incident_route_impact_failure_partial(monkeypatch):
    monkeypatch.setattr(
        orch_module, "run_unified_analysis", lambda v, w, h: _vision_response()
    )

    class _Boom:
        def run(self, payload):
            raise RuntimeError("boom")

    monkeypatch.setattr(orch_module, "ImpactAgent", _Boom)
    resp = _upload_incident(_png_bytes())
    assert resp.status_code == 200
    body = resp.json()
    assert body["incident_status"] == "partial"
    assert body["findings"] != []
    assert body["exposure_concerns"] == []


def test_legacy_assess_still_scaffold():
    resp = client.post("/api/disaster-response/assess", json={})
    assert resp.status_code == 200
    assert resp.json()["incident_id"] == "scaffold"


# --- concern/action merge rules ---


def test_concern_merge_single_per_finding():
    finding = _finding(
        description=(
            "Observed: floodwater over the road.\n"
            "Affected feature: village road\n"
            "Location in image: lower third, center"
        )
    )
    result = ImpactAgent().run(
        {
            "findings": [finding],
            "segmentations": [_segmentation("road")],
            "geo_context": _geo_unavailable(),
        }
    )
    concerns = result.data["exposure_concerns"]
    assert len(concerns) == 1
    concern = concerns[0]
    assert "1 segmented 'road'" in concern.condition
    assert "village road" in concern.condition
    assert "lower third, center" in concern.condition
    assert "floodwater" in concern.concern
    assert concern.basis_finding_ids == ["vision-1-abc"]
    assert concern.basis_evidence_ids == [PNG_EVIDENCE]


def test_concern_excerpt_preserves_qualifiers():
    finding = _finding(
        description=(
            "Observed: possible debris.\n"
            "Affected feature: possible road edge\n"
            "Location in image: upper slope, not fully visible"
        )
    )
    result = ImpactAgent().run(
        {"findings": [finding], "segmentations": [], "geo_context": _geo_unavailable()}
    )
    (concern,) = result.data["exposure_concerns"]
    assert "possible road edge" in concern.condition
    assert "not fully visible" in concern.condition


def test_concern_cap_warns():
    findings = [
        _finding(f"f{i}", "debris", "Observed: debris on slope.") for i in range(8)
    ]
    segmentations = [
        _segmentation(prompt).model_copy(update={"linked_finding_ids": [f"f{i}"]})
        for i, prompt in enumerate(["road", "river", "building", "vehicle"])
    ]
    result = ImpactAgent().run(
        {
            "findings": findings,
            "segmentations": segmentations,
            "geo_context": _geo_unavailable(),
        }
    )
    assert len(result.data["exposure_concerns"]) == 6
    assert any("impact_concern_cap" in e for e in result.errors)


def test_action_merge_provenance():
    result = ImpactAgent().run(
        {
            "findings": [_finding()],
            "segmentations": [_segmentation("road")],
            "geo_context": _geo_provided(),
        }
    )
    actions = result.data["verification_actions"]
    (concern,) = result.data["exposure_concerns"]
    linked = [a for a in actions if a.action_id == concern.verification_action_id]
    assert len(linked) == 1
    assert concern.concern_id in linked[0].action
    assert "field-verify" in linked[0].action.lower()
    assert linked[0].kind == "concern_review"
    assert linked[0].concern_id == concern.concern_id
    # Distinct objectives stay separate: the finding keeps its own
    # confirmation review alongside the concern review.
    assert "verify-finding-vision-1-abc" in [a.action_id for a in actions]
    assert validate_exposure_concerns(result.data["exposure_concerns"], actions) == []


def test_no_merge_different_tasks():
    finding = _finding(description="Observed: people near blocked road.")
    result = ImpactAgent().run(
        {
            "findings": [finding],
            "segmentations": [
                _segmentation("road"),
                _segmentation("river", PromptStatus.FAILED, 0, "sam31_timeout: slow."),
            ],
            "geo_context": _geo_unavailable(),
        }
    )
    ids = [a.action_id for a in result.data["verification_actions"]]
    assert "verify-people-vision-1-abc" in ids
    assert "verify-seg-river" in ids
    assert "verify-geo-context" in ids


def test_multi_basis_concern_not_merged():
    f1 = _finding("f1", "debris", "Observed: debris.")
    f2 = _finding("f2", "smoke", "Observed: smoke.")
    seg = _segmentation("road").model_copy(update={"linked_finding_ids": ["f1", "f2"]})
    result = ImpactAgent().run(
        {"findings": [f1, f2], "segmentations": [seg], "geo_context": _geo_provided()}
    )
    ids = [a.action_id for a in result.data["verification_actions"]]
    assert "verify-finding-f1" in ids
    assert "verify-finding-f2" in ids
    assert (
        validate_exposure_concerns(
            result.data["exposure_concerns"], result.data["verification_actions"]
        )
        == []
    )


def test_concern_without_sam_detection():
    # Road evidence without any SAM support still raises the question.
    finding = _finding(
        description="Observed: cracked road surface with debris."
    )
    result = ImpactAgent().run(
        {"findings": [finding], "segmentations": [], "geo_context": _geo_unavailable()}
    )
    (concern,) = result.data["exposure_concerns"]
    assert concern.feature == "road"
    assert "not measured by segmentation" in concern.concern
    assert "does not mean" in concern.concern
    action = [
        a
        for a in result.data["verification_actions"]
        if a.action_id == concern.verification_action_id
    ][0]
    assert action.priority == "high"
    assert "passable" in action.unknown


def test_zero_match_never_means_absence():
    finding = _finding(description="Observed: road under mudslide debris.")
    seg = _segmentation("road", PromptStatus.ZERO_MATCHES, 0)
    result = ImpactAgent().run(
        {
            "findings": [finding],
            "segmentations": [seg],
            "geo_context": _geo_unavailable(),
        }
    )
    (concern,) = result.data["exposure_concerns"]
    assert "does not mean" in concern.concern
    assert "absent" in concern.concern


def test_people_concern_without_sam():
    finding = _finding(
        label="gathering", description="Observed: people near the river."
    )
    result = ImpactAgent().run(
        {"findings": [finding], "segmentations": [], "geo_context": _geo_unavailable()}
    )
    concerns = result.data["exposure_concerns"]
    assert len(concerns) == 1
    assert concerns[0].feature == "people"
    assert "not confirmed" in concerns[0].concern


def test_no_concern_without_supporting_evidence():
    finding = _finding("f1", "smoke", "Observed: smoke in the distance.")
    result = ImpactAgent().run(
        {"findings": [finding], "segmentations": [], "geo_context": _geo_unavailable()}
    )
    assert result.data["exposure_concerns"] == []
    assert any(
        a.action_id == "verify-finding-f1"
        for a in result.data["verification_actions"]
    )


def test_action_detail_fields_and_methods():
    from app.orchestrator.validators import (
        METHOD_SUGGESTIONS,
        validate_verification_actions,
    )

    result = ImpactAgent().run(
        {
            "findings": [_finding()],
            "segmentations": [_segmentation("road")],
            "geo_context": _geo_unavailable(),
        }
    )
    actions = result.data["verification_actions"]
    assert actions != []
    for action in actions:
        assert action.what.strip() != ""
        assert action.why_operational.strip() != ""
        assert action.unknown.strip() != ""
        assert action.priority_reason.strip() != ""
        assert action.method in METHOD_SUGGESTIONS
    assert (
        validate_verification_actions(actions, {"vision-1-abc"}) == []
    )


def test_merged_action_carries_detail_fields():
    result = ImpactAgent().run(
        {
            "findings": [_finding()],
            "segmentations": [_segmentation("road")],
            "geo_context": _geo_provided(),
        }
    )
    (concern,) = result.data["exposure_concerns"]
    (linked,) = [
        a
        for a in result.data["verification_actions"]
        if a.action_id == concern.verification_action_id
    ]
    assert linked.related_finding_ids == ["vision-1-abc"]
    assert "routes in active use" in linked.what
    assert "ground teams" in linked.why_operational
    assert "passable" in linked.unknown
    assert linked.method in {
        "Inspect on site from a safe location with local guidance."
    }
    separate = [
        a
        for a in result.data["verification_actions"]
        if a.action_id == "verify-finding-vision-1-abc"
    ]
    assert len(separate) == 1
    assert "vision-1-abc" in separate[0].what


def test_summary_grounding_and_gaps():
    vision = _vision_response(
        findings=[
            _finding("f1", "floodwater", "Observed: floodwater over the road."),
            _finding("f2", "smoke", "Observed: smoke."),
        ],
        segmentations=[
            _segmentation("road"),
            _segmentation("river", PromptStatus.ZERO_MATCHES, 0),
        ],
    )
    result = ReportingAgent().run(
        {
            "incident_id": vision.incident_id,
            "image": vision.image,
            "vision": vision,
            "impact_data": _impact_data_for(vision, _geo_unavailable()),
            "impact_error": None,
            "geo_context": _geo_unavailable(),
            "trail": [],
        }
    )
    dossier = result.data["dossier"]
    summary = dossier.situation_summary
    assert "floodwater" in summary.headline
    assert "smoke" in summary.observed
    assert "1 'road' region measured" in summary.observed
    assert "not absence" in summary.observed
    assert "Capture time is unknown" in summary.unknowns
    assert "passable" in summary.unknowns
    topics = {g.topic: g.status for g in dossier.information_gaps}
    assert topics["capture_time"] == "unknown"
    assert topics["incident_location"] == "unknown"
    assert topics["accessibility"] == "unknown"
    assert topics["ground_truth"] == "unknown"


def test_gaps_distinguish_unverified_geo():
    vision = _vision_response(findings=[], segmentations=[])
    result = ReportingAgent().run(
        {
            "incident_id": vision.incident_id,
            "image": vision.image,
            "vision": vision,
            "impact_data": _impact_data_for(vision, _geo_provided()),
            "impact_error": None,
            "geo_context": _geo_provided(),
            "trail": [],
        }
    )
    dossier = result.data["dossier"]
    location = [g for g in dossier.information_gaps if g.topic == "incident_location"][0]
    assert location.status == "unverified"
    assert "accessibility" not in [g.topic for g in dossier.information_gaps]


def test_finding_groups_and_geometry_equality():
    f1 = _finding("f1", "floodwater", "Observed: floodwater over the road.")
    f2 = _finding("f2", "smoke", "Observed: smoke.")
    seg = _segmentation("road").model_copy(update={"linked_finding_ids": ["f1"]})
    vision = _vision_response(findings=[f1, f2], segmentations=[seg])
    result = ReportingAgent().run(
        {
            "incident_id": vision.incident_id,
            "image": vision.image,
            "vision": vision,
            "impact_data": _impact_data_for(vision, _geo_unavailable()),
            "impact_error": None,
            "geo_context": _geo_unavailable(),
            "trail": [],
        }
    )
    dossier = result.data["dossier"]
    groups = {g.group_id: g for g in dossier.finding_groups}
    assert groups["grp-road"].finding_ids == ["f1"]
    assert groups["grp-other"].finding_ids == ["f2"]
    assert dossier.segmentations == vision.segmentations
    assert dossier.segmentations[0].detections[0].mask.svg_path != ""


def test_concern_safety_language():
    findings = [
        _finding("f1", "damage", "Observed: blocked road with debris."),
        _finding("f2", "floodwater", "Observed: floodwater over fields."),
    ]
    segmentations = [
        _segmentation("road").model_copy(update={"linked_finding_ids": ["f1"]}),
        _segmentation("river").model_copy(update={"linked_finding_ids": ["f2"]}),
    ]
    result = ImpactAgent().run(
        {
            "findings": findings,
            "segmentations": segmentations,
            "geo_context": _geo_unavailable(),
        }
    )
    concerns = result.data["exposure_concerns"]
    assert len(concerns) == 2
    assert len({c.condition for c in concerns}) == 2
    for concern in concerns:
        assert concern.status == "unverified"
        assert "not confirmed" in concern.concern
        assert "is blocked" not in concern.concern
    assert validate_exposure_concerns(concerns, result.data["verification_actions"]) == []
