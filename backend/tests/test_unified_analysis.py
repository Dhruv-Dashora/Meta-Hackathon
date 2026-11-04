"""Unified analysis tests (mocked models — never calls the real APIs)."""

import hashlib
import io

from fastapi.testclient import TestClient
from PIL import Image

from app.agents.base import AgentResult
from app.api import disaster_response
from app.core.errors import SentinelError
from app.main import app
from app.schemas.common import Confidence, EvidenceRef, Finding
from app.services.prompt_planner import MAX_SAM_PROMPTS, derive_sam_prompts
from app.services.sam31_client import Sam31Box, Sam31Detection, Sam31Mask, Sam31Result

client = TestClient(app)

GIF_BYTES = b"GIF89a" + b"\x00" * 32


def _finding(finding_id: str, label: str, description: str = "") -> Finding:
    return Finding(
        finding_id=finding_id,
        label=label,
        description=description,
        confidence=Confidence(value=0.7),
    )


# --- prompt planner ---


def test_planner_priority_order():
    findings = [
        _finding("f1", "vehicle", "Observed: a car near the water."),
        _finding("f2", "floodwater", "Observed: floodwater over the road."),
    ]
    plan = derive_sam_prompts(findings)
    # Tier 2 (hazard + affected road) before tier 3 (neutral vehicle);
    # river before road alphabetically at equal confidence.
    assert [d.prompt for d in plan] == ["river", "road", "vehicle"]
    river = plan[0]
    assert river.triggered_by == ["f1", "f2"]
    assert "water" in river.matched_keywords or "floodwater" in river.matched_keywords


def test_planner_dedupes_across_findings():
    findings = [
        _finding("f1", "damage", "Observed: road cracked."),
        _finding("f2", "hazard", "Observed: highway blocked by mud."),
    ]
    plan = derive_sam_prompts(findings)
    assert [d.prompt for d in plan] == ["road"]
    assert plan[0].triggered_by == ["f1", "f2"]
    assert plan[0].matched_keywords == ["road", "highway"]


def test_planner_caps_at_max_prompts():
    assert MAX_SAM_PROMPTS == 3
    findings = [
        _finding("f1", "scene", "Observed: road, river, building, vehicle."),
    ]
    plan = derive_sam_prompts(findings)
    # River (tier 2 hazard) first, then neutral infrastructure alphabetically.
    assert [d.prompt for d in plan] == ["river", "building", "road"]
    plan2 = derive_sam_prompts(findings, max_prompts=2)
    assert [d.prompt for d in plan2] == ["river", "building"]


def test_planner_landslide_debris_selects_debris():
    findings = [
        _finding("f1", "landslide", "Observed: landslide debris on slope."),
    ]
    # The observed hazard material is attempted via its concrete noun.
    plan = derive_sam_prompts(findings)
    assert [d.prompt for d in plan] == ["debris"]
    assert plan[0].matched_keywords == ["debris"]


def test_unified_debris_zero_matches_is_not_absence():
    """Landslide debris is attempted; zero matches stay distinct from absence.

    Service-level (no HTTP): fake vision reports landslide debris, fake SAM
    matches nothing. The debris prompt must be planned and executed with
    ``automatic`` provenance, and the outcome must read ``zero_matches`` —
    never an empty plan and never an absence claim.
    """
    from app.agents.base import AgentResult as _AgentResult
    from app.schemas.unified_analysis import PromptStatus as _Status
    from app.schemas.unified_analysis import WorkflowStatus as _Workflow
    from app.services import media_service as _media
    from app.services.unified_service import run_unified_analysis

    png = _png_bytes()
    finding = _finding_with_evidence(
        "vision-1-abc",
        "landslide debris",
        "Observed: landslide debris on the hillside.",
        png,
    )
    vision = _FakeVision(_AgentResult(agent="vision", findings=[finding]))
    sam = _FakeSam([Sam31Result()])
    validated = _media.validate_image_bytes(png, max_bytes=len(png) + 1)
    response = run_unified_analysis(
        validated,
        320,
        334,
        vision_factory=vision,
        sam_factory=sam,
    )
    assert sam.prompts == ["debris"]
    assert [d.prompt for d in response.prompt_plan] == ["debris"]
    assert response.prompt_plan[0].provenance == "automatic"
    assert response.prompt_plan[0].triggered_by == ["vision-1-abc"]
    assert len(response.segmentations) == 1
    assert response.segmentations[0].status == _Status.ZERO_MATCHES
    assert response.segmentations[0].detections == []
    assert response.findings != []
    assert response.workflow_status == _Workflow.COMPLETED


def test_planner_no_match_no_fallback():
    findings = [_finding("f1", "smoke", "Observed: smoke in the distance.")]
    assert derive_sam_prompts(findings) == []
    assert derive_sam_prompts([]) == []


def test_planner_negation_suppresses_prompt():
    findings = [_finding("f1", "clear", "Observed: no road visible in frame.")]
    assert derive_sam_prompts(findings) == []


def test_planner_negation_only_blocks_negated_concept():
    findings = [
        _finding("f1", "mixed", "Observed: no vehicle present, road cracked."),
    ]
    plan = derive_sam_prompts(findings)
    assert [d.prompt for d in plan] == ["road"]


def test_planner_trailing_absence_suppresses():
    findings = [_finding("f1", "clear", "Observed: road absent from view.")]
    assert derive_sam_prompts(findings) == []
    findings = [_finding("f1", "clear", "Observed: road not visible here.")]
    assert derive_sam_prompts(findings) == []


def test_planner_uncertainty_still_triggers():
    findings = [
        _finding("f1", "maybe", "Observed: possible road under mud, uncertain.")
    ]
    plan = derive_sam_prompts(findings)
    assert [d.prompt for d in plan] == ["road"]


def test_planner_deterministic():
    findings = [
        _finding("f1", "a", "Observed: vehicle by the river."),
        _finding("f2", "b", "Observed: building near road."),
    ]
    first = derive_sam_prompts(findings)
    second = derive_sam_prompts(list(reversed(findings)))
    # Same prompt set in tier order regardless of input order.
    assert [d.prompt for d in first] == [d.prompt for d in second]
    assert first[0].prompt == "river"


# --- unified route tests (VisionAgent + Sam31Client mocked) ---


def _png_bytes(width: int = 320, height: int = 334) -> bytes:
    image = Image.new("RGB", (width, height), color=(120, 130, 140))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _upload(data: bytes):
    return client.post(
        "/api/disaster-response/analyze-and-segment",
        files={"image": ("scene.png", data, "image/png")},
    )


def _finding_with_evidence(
    finding_id: str, label: str, description: str, png: bytes
) -> Finding:
    evidence_id = f"sha256:{hashlib.sha256(png).hexdigest()}"
    return Finding(
        finding_id=finding_id,
        label=label,
        description=description,
        confidence=Confidence(value=0.8),
        evidence_refs=[
            EvidenceRef(
                evidence_id=evidence_id,
                modality="image",
                uri_or_hash=evidence_id,
            )
        ],
    )


def _detection(object_id: str = "0") -> Sam31Detection:
    return Sam31Detection(
        object_id=object_id,
        box=Sam31Box(x1=10, y1=20, x2=30, y2=40),
        mask=Sam31Mask(width=20, height=20, svg_path="M0 0L1 0L1 1Z", rle_counts="abc"),
    )


class _FakeVision:
    def __init__(self, result: AgentResult) -> None:
        self._result = result
        self.seen: dict | None = None

    def __call__(self, *args, **kwargs) -> "_FakeVision":
        return self

    def run(self, payload: dict) -> AgentResult:
        self.seen = payload
        return self._result


class _FakeSam:
    def __init__(self, outcomes: list) -> None:
        self._outcomes = list(outcomes)
        self.prompts: list[str] = []
        self.timeouts: list = []
        self.model = "sam-3.1"

    def __call__(self, *args, **kwargs) -> "_FakeSam":
        self.timeouts.append(kwargs.get("timeout_s"))
        return self

    def segment_image(self, image_data_url: str, prompt: str) -> Sam31Result:
        assert image_data_url.startswith("data:image/png;base64,")
        self.prompts.append(prompt)
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def test_unified_success_links_evidence(monkeypatch):
    png = _png_bytes()
    evidence_id = f"sha256:{hashlib.sha256(png).hexdigest()}"
    finding = _finding_with_evidence(
        "vision-1-abc", "floodwater", "Observed: floodwater over the road.", png
    )
    vision = _FakeVision(AgentResult(agent="vision", findings=[finding]))
    sam = _FakeSam(
        [
            Sam31Result(detections=[_detection("0")]),
            Sam31Result(detections=[_detection("1")]),
        ]
    )
    monkeypatch.setattr(disaster_response, "VisionAgent", vision)
    monkeypatch.setattr(disaster_response, "Sam31Client", sam)
    resp = _upload(png)
    assert resp.status_code == 200
    body = resp.json()
    assert body["incident_id"].startswith("img-")
    assert body["image"]["evidence_id"] == evidence_id
    assert (body["image"]["width"], body["image"]["height"]) == (320, 334)
    assert [f["finding_id"] for f in body["findings"]] == ["vision-1-abc"]
    assert body["findings"][0]["evidence_refs"][0]["evidence_id"] == evidence_id
    # Tier order: river (hazard) before affected road at equal confidence.
    assert [d["prompt"] for d in body["prompt_plan"]] == ["river", "road"]
    assert sam.prompts == ["river", "road"]
    assert len(body["segmentations"]) == 2
    first = body["segmentations"][0]
    assert first["status"] == "ok"
    assert first["linked_finding_ids"] == ["vision-1-abc"]
    assert first["association"] == "prompt_trigger_only"
    assert first["detections"][0]["object_id"] == "0"
    assert body["workflow_status"] == "completed"
    assert vision.seen is not None
    assert vision.seen["evidence_id"] == evidence_id


def test_unified_zero_matches_preserves_findings(monkeypatch):
    png = _png_bytes()
    finding = _finding_with_evidence(
        "vision-1-abc", "damage", "Observed: road cracked.", png
    )
    vision = _FakeVision(AgentResult(agent="vision", findings=[finding]))
    sam = _FakeSam([Sam31Result()])
    monkeypatch.setattr(disaster_response, "VisionAgent", vision)
    monkeypatch.setattr(disaster_response, "Sam31Client", sam)
    resp = _upload(png)
    assert resp.status_code == 200
    body = resp.json()
    assert body["findings"] != []
    assert body["segmentations"][0]["status"] == "zero_matches"
    assert body["segmentations"][0]["detections"] == []
    assert body["workflow_status"] == "completed"


def test_unified_partial_failure_preserves_findings(monkeypatch):
    png = _png_bytes()
    finding = _finding_with_evidence(
        "vision-1-abc", "scene", "Observed: road by the river.", png
    )
    vision = _FakeVision(AgentResult(agent="vision", findings=[finding]))
    sam = _FakeSam(
        [
            Sam31Result(detections=[_detection("0")]),
            SentinelError("sam31_timeout", "SAM 3.1 request timed out."),
        ]
    )
    monkeypatch.setattr(disaster_response, "VisionAgent", vision)
    monkeypatch.setattr(disaster_response, "Sam31Client", sam)
    resp = _upload(png)
    assert resp.status_code == 200
    body = resp.json()
    assert [s["status"] for s in body["segmentations"]] == ["ok", "failed"]
    assert "sam31_timeout" in body["segmentations"][1]["error"]
    assert "Traceback" not in body["segmentations"][1]["error"]
    assert body["findings"] != []
    assert body["workflow_status"] == "partial"


def test_unified_cap_skips_fourth_prompt(monkeypatch):
    png = _png_bytes()
    finding = _finding_with_evidence(
        "vision-1-abc", "scene", "Observed: road, river, building, vehicle.", png
    )
    vision = _FakeVision(AgentResult(agent="vision", findings=[finding]))
    sam = _FakeSam([Sam31Result(detections=[_detection()])] * 3)
    monkeypatch.setattr(disaster_response, "VisionAgent", vision)
    monkeypatch.setattr(disaster_response, "Sam31Client", sam)
    resp = _upload(png)
    assert resp.status_code == 200
    body = resp.json()
    assert [d["prompt"] for d in body["prompt_plan"]] == [
        "river",
        "building",
        "road",
        "vehicle",
    ]
    assert [s["status"] for s in body["segmentations"]] == [
        "ok",
        "ok",
        "ok",
        "skipped",
    ]
    assert "prompt_cap_exceeded" in body["segmentations"][3]["error"]
    assert sam.prompts == ["river", "building", "road"]
    assert body["workflow_status"] == "partial"


def test_unified_budget_exhaustion_skips_sam(monkeypatch):
    png = _png_bytes()
    finding = _finding_with_evidence(
        "vision-1-abc", "damage", "Observed: road cracked.", png
    )
    vision = _FakeVision(AgentResult(agent="vision", findings=[finding]))
    sam = _FakeSam([Sam31Result(detections=[_detection()])])
    monkeypatch.setattr(disaster_response, "VisionAgent", vision)
    monkeypatch.setattr(disaster_response, "Sam31Client", sam)
    monkeypatch.setattr(disaster_response.settings, "unified_workflow_budget_s", 0.0)
    resp = _upload(png)
    assert resp.status_code == 200
    body = resp.json()
    assert body["findings"] != []
    assert body["segmentations"][0]["status"] == "skipped"
    assert "budget_exhausted" in body["segmentations"][0]["error"]
    assert sam.prompts == []
    assert body["workflow_status"] == "vision_only"


def test_unified_no_concepts_is_vision_only(monkeypatch):
    png = _png_bytes()
    finding = _finding_with_evidence(
        "vision-1-abc", "smoke", "Observed: smoke in the distance.", png
    )
    vision = _FakeVision(AgentResult(agent="vision", findings=[finding]))
    sam = _FakeSam([])
    monkeypatch.setattr(disaster_response, "VisionAgent", vision)
    monkeypatch.setattr(disaster_response, "Sam31Client", sam)
    resp = _upload(png)
    assert resp.status_code == 200
    body = resp.json()
    assert body["prompt_plan"] == []
    assert body["segmentations"] == []
    assert any("no_segmentable_concepts" in w for w in body["warnings"])
    assert body["workflow_status"] == "vision_only"
    assert sam.prompts == []


def test_unified_vision_failure_is_502(monkeypatch):
    vision = _FakeVision(
        AgentResult(agent="vision", errors=["muse_spark_timeout: timed out"])
    )
    sam = _FakeSam([])
    monkeypatch.setattr(disaster_response, "VisionAgent", vision)
    monkeypatch.setattr(disaster_response, "Sam31Client", sam)
    resp = _upload(_png_bytes())
    assert resp.status_code == 502
    assert sam.prompts == []


def test_unified_rejects_bad_upload_without_model_calls(monkeypatch):
    vision = _FakeVision(AgentResult(agent="vision", findings=[]))
    sam = _FakeSam([])
    monkeypatch.setattr(disaster_response, "VisionAgent", vision)
    monkeypatch.setattr(disaster_response, "Sam31Client", sam)
    resp = _upload(GIF_BYTES)
    assert resp.status_code == 400
    assert "unsupported_image_type" in resp.json()["detail"]
    assert vision.seen is None
    assert sam.prompts == []


def test_unified_rejects_oversize_without_model_calls(monkeypatch):
    vision = _FakeVision(AgentResult(agent="vision", findings=[]))
    sam = _FakeSam([])
    monkeypatch.setattr(disaster_response, "VisionAgent", vision)
    monkeypatch.setattr(disaster_response, "Sam31Client", sam)
    monkeypatch.setattr(disaster_response.settings, "max_image_bytes", 8)
    resp = _upload(_png_bytes())
    assert resp.status_code == 413
    assert vision.seen is None
    assert sam.prompts == []


def test_unified_timeouts_respect_budget_defaults(monkeypatch):
    png = _png_bytes()
    finding = _finding_with_evidence(
        "vision-1-abc", "damage", "Observed: road cracked.", png
    )
    vision = _FakeVision(AgentResult(agent="vision", findings=[finding]))
    sam = _FakeSam([Sam31Result()])
    spark_timeouts: list = []
    monkeypatch.setattr(disaster_response, "VisionAgent", vision)
    monkeypatch.setattr(disaster_response, "Sam31Client", sam)
    monkeypatch.setattr(
        disaster_response,
        "MuseSparkClient",
        lambda *a, **k: spark_timeouts.append(k.get("timeout_s")) or None,
    )
    resp = _upload(png)
    assert resp.status_code == 200
    # Default 90s budget leaves standalone defaults untouched.
    assert spark_timeouts == [disaster_response.settings.muse_spark_timeout_s]
    assert sam.timeouts == [disaster_response.settings.sam31_timeout_s]
