"""Analyze-image slice tests (mocked model — never calls the real API)."""

import asyncio
import io
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.agents.base import AgentResult
from app.agents.vision_agent import VisionAgent
from app.api import disaster_response
from app.core.errors import SentinelError
from app.main import app
from app.schemas.common import Confidence, Finding, ReviewStatus
from app.services import media_service
from app.services.muse_spark_client import MuseSparkClient, extract_output_text

client = TestClient(app)

PNG_BYTES = bytes.fromhex("89504e470d0a1a0a") + b"\x00" * 32
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 32
WEBP_BYTES = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 32
GIF_BYTES = b"GIF89a" + b"\x00" * 32
TEXT_BYTES = b"hello world, not an image"

MODEL_FINDINGS_JSON = json.dumps(
    {
        "findings": [
            {
                "label": "floodwater",
                "observed": "Standing water covering the road surface.",
                "affected_feature": "village road",
                "location_in_image": "lower third, center",
                "inferred_impact": "Road may be impassable to vehicles.",
                "confidence": 0.8,
                "uncertainty_notes": "Water depth unknown from this angle.",
            }
        ]
    }
)


def _upload(filename: str, data: bytes, mime: str):
    return client.post(
        "/api/disaster-response/analyze-image",
        files={"image": (filename, data, mime)},
    )


class _FakeAgent:
    def __init__(self, result: AgentResult) -> None:
        self._result = result
        self.seen: dict | None = None

    def run(self, payload: dict) -> AgentResult:
        self.seen = payload
        return self._result


def _finding() -> Finding:
    return Finding(
        finding_id="vision-1-test",
        label="floodwater",
        confidence=Confidence(value=0.8),
    )


# --- media_service unit tests ---


@pytest.mark.parametrize(
    ("data", "mime"),
    [(PNG_BYTES, "image/png"), (JPEG_BYTES, "image/jpeg"), (WEBP_BYTES, "image/webp")],
)
def test_sniff_supported_formats(data, mime):
    assert media_service.sniff_image_mime(data) == mime


@pytest.mark.parametrize("data", [GIF_BYTES, TEXT_BYTES, b"", b"\x00" * 4])
def test_sniff_rejects_unsupported_or_malformed(data):
    assert media_service.sniff_image_mime(data) is None


def test_validate_and_data_url_roundtrip():
    image = media_service.validate_image_bytes(PNG_BYTES, max_bytes=1024)
    assert image.mime_type == "image/png"
    url = media_service.image_to_data_url(image)
    assert url.startswith("data:image/png;base64,")


def test_validate_rejects_oversize():
    with pytest.raises(media_service.ImageValidationError) as exc_info:
        media_service.validate_image_bytes(PNG_BYTES, max_bytes=8)
    assert exc_info.value.status_code == 413


def test_read_upload_bounded_enforces_limit():
    from fastapi import UploadFile

    upload = UploadFile(filename="big.png", file=io.BytesIO(PNG_BYTES))
    data = asyncio.run(media_service.read_upload_bounded(upload, max_bytes=1024))
    assert data == PNG_BYTES
    upload = UploadFile(filename="big.png", file=io.BytesIO(PNG_BYTES))
    with pytest.raises(media_service.ImageValidationError):
        asyncio.run(media_service.read_upload_bounded(upload, max_bytes=8))


# --- endpoint tests (VisionAgent mocked) ---


def test_analyze_image_success(monkeypatch):
    fake = _FakeAgent(AgentResult(agent="vision", findings=[_finding()]))
    monkeypatch.setattr(disaster_response, "VisionAgent", lambda: fake)
    resp = _upload("flood.png", PNG_BYTES, "image/png")
    assert resp.status_code == 200
    body = resp.json()
    assert body["incident_id"].startswith("img-")
    assert len(body["findings"]) == 1
    finding = body["findings"][0]
    assert finding["confidence"]["calibrated"] is False
    assert finding["review_status"] == "pending"
    assert fake.seen is not None
    assert fake.seen["image_data_url"].startswith("data:image/png;base64,")
    assert fake.seen["evidence_id"].startswith("sha256:")


def test_analyze_image_rejects_wrong_content(monkeypatch):
    fake = _FakeAgent(AgentResult(agent="vision", findings=[_finding()]))
    monkeypatch.setattr(disaster_response, "VisionAgent", lambda: fake)
    # PNG filename + declared MIME, but GIF bytes: content sniffing must win.
    resp = _upload("evil.png", GIF_BYTES, "image/png")
    assert resp.status_code == 400
    assert "unsupported_image_type" in resp.json()["detail"]
    assert fake.seen is None


def test_analyze_image_rejects_oversize(monkeypatch):
    fake = _FakeAgent(AgentResult(agent="vision", findings=[_finding()]))
    monkeypatch.setattr(disaster_response, "VisionAgent", lambda: fake)
    monkeypatch.setattr(
        disaster_response.settings, "max_image_bytes", 8
    )
    resp = _upload("flood.png", PNG_BYTES, "image/png")
    assert resp.status_code == 413
    assert fake.seen is None


def test_analyze_image_model_failure_is_502(monkeypatch):
    fake = _FakeAgent(
        AgentResult(agent="vision", errors=["muse_spark_timeout: timed out"])
    )
    monkeypatch.setattr(disaster_response, "VisionAgent", lambda: fake)
    resp = _upload("flood.png", PNG_BYTES, "image/png")
    assert resp.status_code == 502


# --- VisionAgent tests (MuseSparkClient stubbed) ---


class _StubClient:
    def __init__(self, output: str = "", error: Exception | None = None) -> None:
        self._output = output
        self._error = error

    def analyze_image(self, image_data_url: str, instruction: str) -> str:
        assert image_data_url.startswith("data:image/")
        assert "JSON only" in instruction
        if self._error is not None:
            raise self._error
        return self._output


def test_vision_agent_maps_findings():
    result = VisionAgent(client=_StubClient(output=MODEL_FINDINGS_JSON)).run(
        {"image_data_url": "data:image/png;base64,AAA", "evidence_id": "sha256:abc"}
    )
    assert result.errors == []
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.label == "floodwater"
    assert "Standing water" in finding.description
    assert "village road" in finding.description
    assert finding.confidence.calibrated is False
    assert finding.confidence.value == 0.8
    assert finding.review_status == ReviewStatus.PENDING
    assert finding.uncertainty_notes != ""
    assert finding.evidence_refs[0].modality == "image"
    assert finding.observed_at is None


def test_vision_agent_empty_findings_is_valid():
    result = VisionAgent(client=_StubClient(output='{"findings": []}')).run(
        {"image_data_url": "data:image/png;base64,AAA"}
    )
    assert result.errors == []
    assert result.findings == []


def test_vision_agent_malformed_output_fails_safely():
    result = VisionAgent(client=_StubClient(output="not json at all")).run(
        {"image_data_url": "data:image/png;base64,AAA"}
    )
    assert result.findings == []
    assert any("invalid_model_output" in e for e in result.errors)


def test_vision_agent_client_error_fails_safely():
    result = VisionAgent(
        client=_StubClient(error=SentinelError("muse_spark_timeout", "timed out"))
    ).run({"image_data_url": "data:image/png;base64,AAA"})
    assert result.findings == []
    assert any("muse_spark_timeout" in e for e in result.errors)


def test_vision_agent_missing_input():
    result = VisionAgent(client=_StubClient(output=MODEL_FINDINGS_JSON)).run({})
    assert result.findings == []
    assert result.errors != []


# --- MuseSparkClient tests (httpx MockTransport — no network) ---


def _mocked_client(handler, **kwargs) -> MuseSparkClient:
    transport = httpx.MockTransport(handler)
    return MuseSparkClient(
        api_key="test-key",
        base_url="https://api.meta.ai/v1",
        model="muse-spark-1.3",
        http_client=httpx.Client(transport=transport),
        **kwargs,
    )


def test_client_sends_responses_request():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        body = json.loads(request.content.decode("utf-8"))
        seen["body"] = body
        return httpx.Response(200, json={"output_text": '{"findings": []}'})

    text = _mocked_client(handler).analyze_image("data:image/png;base64,AAA", "hi")
    assert text == '{"findings": []}'
    assert seen["url"] == "https://api.meta.ai/v1/responses"
    assert seen["auth"] == "Bearer test-key"
    assert seen["body"]["model"] == "muse-spark-1.3"
    content = seen["body"]["input"][0]["content"]
    assert content[0]["type"] == "input_text"
    assert content[1]["type"] == "input_image"
    assert content[1]["image_url"] == "data:image/png;base64,AAA"


def test_extract_output_text_shapes():
    assert extract_output_text({"output_text": " hi "}) == "hi"
    assert (
        extract_output_text(
            {"output": [{"content": [{"type": "output_text", "text": "deep"}]}]}
        )
        == "deep"
    )
    assert extract_output_text({"output": []}) == ""
    assert extract_output_text({}) == ""


def test_client_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    with pytest.raises(SentinelError) as exc_info:
        _mocked_client(handler).analyze_image("data:image/png;base64,AAA", "hi")
    assert exc_info.value.code == "muse_spark_http_error"


def test_client_bad_json():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json")

    with pytest.raises(SentinelError) as exc_info:
        _mocked_client(handler).analyze_image("data:image/png;base64,AAA", "hi")
    assert exc_info.value.code == "muse_spark_bad_response"


def test_client_empty_output():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"output_text": "  "})

    with pytest.raises(SentinelError) as exc_info:
        _mocked_client(handler).analyze_image("data:image/png;base64,AAA", "hi")
    assert exc_info.value.code == "muse_spark_empty_output"


def test_client_timeout():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow")

    with pytest.raises(SentinelError) as exc_info:
        _mocked_client(handler).analyze_image("data:image/png;base64,AAA", "hi")
    assert exc_info.value.code == "muse_spark_timeout"


def test_client_missing_key_makes_no_request():
    client = MuseSparkClient(api_key="")
    with pytest.raises(SentinelError) as exc_info:
        client.analyze_image("data:image/png;base64,AAA", "hi")
    assert exc_info.value.code == "model_api_key_missing"
