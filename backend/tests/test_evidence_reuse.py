"""Evidence-reuse tests: user targets, sessions, cache, from-analysis route.

All model clients are faked or unreached — never calls the real APIs.
"""

import hashlib
import io

from fastapi.testclient import TestClient
from PIL import Image

from app.agents.base import AgentResult
from app.api import disaster_response
from app.main import app
from app.schemas.common import Confidence, EvidenceRef, Finding
from app.schemas.unified_analysis import PromptProvenance
from app.services.analysis_store import (
    ANALYSIS_REF_PREFIX,
    SESSION_HEADER,
    AnalysisStore,
    SessionStore,
)
from app.services.prompt_planner import (
    MAX_SAM_PROMPTS,
    canonicalize_target,
    derive_sam_prompts,
    plan_sam_prompts,
)
from app.services.sam31_client import Sam31Box, Sam31Detection, Sam31Mask, Sam31Result

client = TestClient(app)


def _finding(finding_id: str, label: str, description: str = "") -> Finding:
    return Finding(
        finding_id=finding_id,
        label=label,
        description=description,
        confidence=Confidence(value=0.7),
    )


def _png_bytes(width: int = 320, height: int = 334) -> bytes:
    image = Image.new("RGB", (width, height), color=(120, 130, 140))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


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
        self.model = "sam-3.1"

    def __call__(self, *args, **kwargs) -> "_FakeSam":
        return self

    def segment_image(self, image_data_url: str, prompt: str) -> Sam31Result:
        self.prompts.append(prompt)
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _ExplodingClient:
    def __call__(self, *args, **kwargs):
        raise AssertionError("model client must not be constructed")


# --- planner: user targets ---


def test_user_target_executes_first_with_provenance():
    findings = [_finding("f1", "scene", "Observed: road by the river.")]
    plan = plan_sam_prompts(findings, user_targets=["house"])
    assert [d.prompt for d in plan] == ["building", "river", "road"]
    assert plan[0].provenance == PromptProvenance.USER_REQUESTED
    assert plan[0].requested_as == "house"
    assert plan[1].provenance == PromptProvenance.AUTOMATIC
    assert plan[1].triggered_by == ["f1"]


def test_user_synonym_dedupes_against_automatic():
    findings = [_finding("f1", "scene", "Observed: building near road.")]
    plan = plan_sam_prompts(findings, user_targets=["house"])
    assert [d.prompt for d in plan] == ["building", "road"]
    assert plan[0].provenance == PromptProvenance.USER_REQUESTED


def test_user_targets_dedupe_among_themselves():
    plan = plan_sam_prompts([], user_targets=["house", "building", "HOUSE"])
    assert [d.prompt for d in plan] == ["building"]


def test_unknown_user_term_passes_through_freeform():
    plan = plan_sam_prompts([], user_targets=["debris"])
    assert [d.prompt for d in plan] == ["debris"]
    assert plan[0].provenance == PromptProvenance.USER_REQUESTED
    assert plan[0].triggered_by == []


def test_user_targets_fill_cap_before_automatic():
    findings = [_finding("f1", "scene", "Observed: road, river, building.")]
    plan = plan_sam_prompts(
        findings, user_targets=["debris", "bridge"], max_prompts=MAX_SAM_PROMPTS
    )
    assert [d.prompt for d in plan] == ["debris", "bridge", "river"]


def test_people_auto_prompt_only_when_observed():
    with_people = [_finding("f1", "scene", "Observed: people near the road.")]
    plan = plan_sam_prompts(with_people)
    assert "people" in [d.prompt for d in plan]
    # People (tier 1 exposure) rank before neutral infrastructure.
    assert derive_sam_prompts(with_people)[0].prompt == "people"
    without_people = [_finding("f1", "scene", "Observed: empty road.")]
    assert "people" not in [d.prompt for d in plan_sam_prompts(without_people)]
    assert "person" not in [d.prompt for d in plan_sam_prompts([], ["road"])]


def test_people_negation_suppresses_auto_prompt():
    findings = [_finding("f1", "scene", "Observed: no people visible, road clear.")]
    assert [d.prompt for d in derive_sam_prompts(findings)] == ["road"]


def test_plan_deterministic_with_user_targets():
    findings = [_finding("f1", "scene", "Observed: river near road.")]
    first = plan_sam_prompts(findings, user_targets=["house"])
    second = plan_sam_prompts(findings, user_targets=["house"])
    assert [d.prompt for d in first] == [d.prompt for d in second]
    assert canonicalize_target(" House ") == "building"
    assert canonicalize_target("debris") == "debris"


# --- stores: sessions + bounded cache ---


def _vision_response(png: bytes):
    from app.schemas.segmentation import SegmentImageInfo
    from app.schemas.unified_analysis import UnifiedAnalysisResponse, WorkflowStatus

    evidence_id = f"sha256:{hashlib.sha256(png).hexdigest()}"
    return UnifiedAnalysisResponse(
        incident_id="img-test",
        image=SegmentImageInfo(
            width=320, height=334, mime_type="image/png", evidence_id=evidence_id
        ),
        findings=[_finding_with_evidence("f1", "road", "Observed: road.", png)],
        workflow_status=WorkflowStatus.VISION_ONLY,
    )


def test_session_create_and_validate():
    store = SessionStore()
    session_id = store.create()
    assert session_id
    assert store.valid(session_id)
    assert not store.valid("nope")
    assert not store.valid(None)
    assert not store.valid("")


def test_session_expiry():
    store = SessionStore(ttl_s=0)
    assert not store.valid(store.create())


def test_cache_roundtrip_same_session():
    png = _png_bytes()
    store = AnalysisStore()
    session_id = "s1"
    ref = store.store(session_id, _vision_response(png), 320, 334)
    assert ref is not None
    assert ref.startswith(ANALYSIS_REF_PREFIX)
    assert ref != f"sha256:{hashlib.sha256(png).hexdigest()}"
    cached = store.get(session_id, ref)
    assert cached is not None
    assert cached.response.findings[0].finding_id == "f1"


def test_cache_refs_unpredictable():
    png = _png_bytes()
    store = AnalysisStore()
    refs = {store.store("s", _vision_response(png), 320, 334) for _ in range(3)}
    assert len(refs) == 3


def test_cache_cross_session_denied_and_unknown_hidden():
    png = _png_bytes()
    store = AnalysisStore()
    ref = store.store("owner", _vision_response(png), 320, 334)
    assert store.get("other", ref) is None
    assert store.get("owner", "anl_missing") is None
    assert store.get(None, ref) is None
    assert store.get("owner", None) is None


def test_cache_expiry_and_eviction():
    png = _png_bytes()
    expired_store = AnalysisStore(ttl_s=0)
    ref = expired_store.store("s", _vision_response(png), 320, 334)
    assert expired_store.get("s", ref) is None

    small = AnalysisStore(max_entries=2)
    r1 = small.store("s", _vision_response(png), 320, 334)
    small.store("s", _vision_response(png), 320, 334)
    small.store("s", _vision_response(png), 320, 334)
    assert small.get("s", r1) is None


def test_cache_oversize_refused():
    tiny = AnalysisStore(max_entry_bytes=10)
    assert tiny.store("s", _vision_response(_png_bytes()), 320, 334) is None
    assert tiny.store("", _vision_response(_png_bytes()), 320, 334) is None


# --- routes: targets + sessions + from-analysis ---


def _upload(png: bytes, targets: str | None = None, session_id: str | None = None):
    data = {} if targets is None else {"targets": targets}
    headers = {} if session_id is None else {SESSION_HEADER: session_id}
    return client.post(
        "/api/disaster-response/analyze-and-segment",
        files={"image": ("scene.png", png, "image/png")},
        data=data,
        headers=headers,
    )


def test_route_user_target_reaches_sam_first(monkeypatch):
    png = _png_bytes()
    finding = _finding_with_evidence(
        "vision-1-abc", "scene", "Observed: road by the river.", png
    )
    vision = _FakeVision(AgentResult(agent="vision", findings=[finding]))
    sam = _FakeSam([Sam31Result(detections=[_detection("0")]) for _ in range(3)])
    monkeypatch.setattr(disaster_response, "VisionAgent", vision)
    monkeypatch.setattr(disaster_response, "Sam31Client", sam)
    resp = _upload(png, targets="house")
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_targets"] == ["house"]
    assert sam.prompts[0] == "building"
    assert body["segmentations"][0]["provenance"] == "user_requested"
    assert body["segmentations"][1]["provenance"] == "automatic"
    assert body["prompt_plan"][0]["requested_as"] == "house"


def test_route_user_target_without_findings_match(monkeypatch):
    png = _png_bytes()
    finding = _finding_with_evidence(
        "vision-1-abc", "smoke", "Observed: smoke in the distance.", png
    )
    vision = _FakeVision(AgentResult(agent="vision", findings=[finding]))
    sam = _FakeSam([Sam31Result()])
    monkeypatch.setattr(disaster_response, "VisionAgent", vision)
    monkeypatch.setattr(disaster_response, "Sam31Client", sam)
    resp = _upload(png, targets="debris")
    assert resp.status_code == 200
    assert sam.prompts == ["debris"]
    assert resp.json()["segmentations"][0]["status"] == "zero_matches"


def test_route_invalid_targets_rejected_before_models(monkeypatch):
    png = _png_bytes()
    vision = _FakeVision(AgentResult(agent="vision", findings=[]))
    sam = _FakeSam([])
    monkeypatch.setattr(disaster_response, "VisionAgent", vision)
    monkeypatch.setattr(disaster_response, "Sam31Client", sam)
    assert "targets_too_many" in _upload(png, targets="a,b,c,d").json()["detail"]
    assert "target_too_long" in _upload(png, targets="x" * 41).json()["detail"]
    assert "invalid_target" in _upload(png, targets="a\tb").json()["detail"]
    assert _upload(png, targets="a,b,c,d").status_code == 400
    assert vision.seen is None
    assert sam.prompts == []


def test_route_invalid_session_rejected_before_models(monkeypatch):
    png = _png_bytes()
    vision = _FakeVision(AgentResult(agent="vision", findings=[]))
    sam = _FakeSam([])
    monkeypatch.setattr(disaster_response, "VisionAgent", vision)
    monkeypatch.setattr(disaster_response, "Sam31Client", sam)
    resp = _upload(png, session_id="bogus")
    assert resp.status_code == 400
    assert "invalid_session" in resp.json()["detail"]
    assert vision.seen is None
    assert sam.prompts == []


def test_route_session_caches_analysis_ref(monkeypatch):
    png = _png_bytes()
    finding = _finding_with_evidence(
        "vision-1-abc", "scene", "Observed: road.", png
    )
    vision = _FakeVision(AgentResult(agent="vision", findings=[finding]))
    sam = _FakeSam([Sam31Result(detections=[_detection("0")]) for _ in range(2)])
    monkeypatch.setattr(disaster_response, "VisionAgent", vision)
    monkeypatch.setattr(disaster_response, "Sam31Client", sam)

    plain = _upload(png)
    assert plain.status_code == 200
    assert plain.json()["analysis_ref"] is None

    session_id = client.post("/api/session").json()["session_id"]
    assert session_id
    cached = _upload(png, session_id=session_id)
    assert cached.status_code == 200
    ref = cached.json()["analysis_ref"]
    assert ref is not None and ref.startswith(ANALYSIS_REF_PREFIX)
    assert ref != cached.json()["image"]["evidence_id"]


def test_from_analysis_requires_session():
    resp = client.post(
        "/api/disaster-response/assess-incident-from-analysis",
        json={"analysis_ref": "anl_missing"},
    )
    assert resp.status_code == 400
    assert "missing_session" in resp.json()["detail"]


def test_from_analysis_miss_is_404_with_rebuild_message(monkeypatch):
    session_id = client.post("/api/session").json()["session_id"]
    other = client.post("/api/session").json()["session_id"]
    png = _png_bytes()
    finding = _finding_with_evidence(
        "vision-1-abc", "scene", "Observed: road.", png
    )
    vision = _FakeVision(AgentResult(agent="vision", findings=[finding]))
    sam = _FakeSam([Sam31Result(detections=[_detection("0")])])
    monkeypatch.setattr(disaster_response, "VisionAgent", vision)
    monkeypatch.setattr(disaster_response, "Sam31Client", sam)
    ref = _upload(png, session_id=session_id).json()["analysis_ref"]

    for headers, body_ref in (
        ({SESSION_HEADER: session_id}, "anl_missing"),
        ({SESSION_HEADER: other}, ref),
    ):
        resp = client.post(
            "/api/disaster-response/assess-incident-from-analysis",
            json={"analysis_ref": body_ref},
            headers=headers,
        )
        assert resp.status_code == 404
        assert "rebuild the report from the image" in resp.json()["detail"]


def test_from_analysis_reuses_evidence_without_model_calls(monkeypatch):
    session_id = client.post("/api/session").json()["session_id"]
    png = _png_bytes()
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
    unified = _upload(png, session_id=session_id).json()
    assert sam.prompts == ["river", "road"]

    monkeypatch.setattr(disaster_response, "VisionAgent", _ExplodingClient())
    monkeypatch.setattr(disaster_response, "Sam31Client", _ExplodingClient())
    resp = client.post(
        "/api/disaster-response/assess-incident-from-analysis",
        json={"analysis_ref": unified["analysis_ref"], "location_label": "Rasuwa"},
        headers={SESSION_HEADER: session_id},
    )
    assert resp.status_code == 200
    dossier = resp.json()
    assert dossier["vision_source"] == "cached_reuse"
    assert dossier["analysis_ref"] == unified["analysis_ref"]
    assert [f["finding_id"] for f in dossier["findings"]] == ["vision-1-abc"]
    assert [s["prompt"] for s in dossier["segmentations"]] == ["river", "road"]
    assert dossier["geo_context"]["location_label"] == "Rasuwa"
    assert dossier["image"]["evidence_id"] == unified["image"]["evidence_id"]
    vision_entry = dossier["agent_trail"][0]
    assert vision_entry["agent"] == "vision"
    assert "no model calls" in vision_entry["notes"]


def test_from_analysis_rejects_bad_geo_without_side_effects(monkeypatch):
    session_id = client.post("/api/session").json()["session_id"]
    png = _png_bytes()
    finding = _finding_with_evidence(
        "vision-1-abc", "scene", "Observed: road.", png
    )
    vision = _FakeVision(AgentResult(agent="vision", findings=[finding]))
    sam = _FakeSam([Sam31Result(detections=[_detection("0")])])
    monkeypatch.setattr(disaster_response, "VisionAgent", vision)
    monkeypatch.setattr(disaster_response, "Sam31Client", sam)
    ref = _upload(png, session_id=session_id).json()["analysis_ref"]

    resp = client.post(
        "/api/disaster-response/assess-incident-from-analysis",
        json={"analysis_ref": ref, "latitude": 28.2},
        headers={SESSION_HEADER: session_id},
    )
    assert resp.status_code == 400
    assert "incomplete_geo" in resp.json()["detail"]

    out_of_range = client.post(
        "/api/disaster-response/assess-incident-from-analysis",
        json={"analysis_ref": ref, "latitude": 28.2, "longitude": 999.0},
        headers={SESSION_HEADER: session_id},
    )
    assert out_of_range.status_code == 400
    assert "invalid_geo" in out_of_range.json()["detail"]

    # The cached entry survives the rejected requests.
    ok = client.post(
        "/api/disaster-response/assess-incident-from-analysis",
        json={
            "analysis_ref": ref,
            "latitude": 28.2,
            "longitude": 85.6,
        },
        headers={SESSION_HEADER: session_id},
    )
    assert ok.status_code == 200
    assert ok.json()["geo_context"]["status"] == "provided"


def test_from_analysis_empty_findings_is_500(monkeypatch):
    from app.services.analysis_store import analysis_store

    session_id = client.post("/api/session").json()["session_id"]
    png = _png_bytes()
    response = _vision_response(png)
    response.findings = []
    ref = analysis_store.store(session_id, response, 320, 334)
    resp = client.post(
        "/api/disaster-response/assess-incident-from-analysis",
        json={"analysis_ref": ref},
        headers={SESSION_HEADER: session_id},
    )
    assert resp.status_code == 500
    assert "cached_evidence_invalid" in resp.json()["detail"]
    assert "Traceback" not in resp.json()["detail"]
