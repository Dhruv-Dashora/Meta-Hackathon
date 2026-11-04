"""Muse Spark reliability tests (mocked transport — never live calls).

Covers timeout mapping, delayed success, retry-free single attempts,
safe duration/stage logging, and vision-failure recovery at the
service level.
"""

import logging
import time

import httpx
import pytest

from app.agents.base import AgentResult
from app.core.errors import SentinelError
from app.schemas.common import Confidence, EvidenceRef, Finding
from app.services import media_service
from app.services.muse_spark_client import MuseSparkClient
from app.services.sam31_client import Sam31Result
from app.services.unified_service import run_unified_analysis

API_KEY = "test-key-do-not-log"
IMAGE = "data:image/png;base64,iVBORw0KGgo="


class _StubTransport:
    """Scripted fake for the client's injected http_client."""

    def __init__(self, script):
        self._script = list(script)
        self.calls: list[dict] = []

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append(
            {"url": url, "headers": headers, "timeout": timeout}
        )
        outcome = self._script.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _timeout_exc():
    return httpx.ReadTimeout(
        "timed out",
        request=httpx.Request("POST", "https://api.meta.ai/v1/responses"),
    )


def _ok_response(text='{"findings": []}'):
    return httpx.Response(200, json={"output_text": text, "status": "completed"})


def test_timeout_maps_to_sentinel_error_without_retry():
    transport = _StubTransport([_timeout_exc()])
    client = MuseSparkClient(
        api_key=API_KEY, timeout_s=5.0, http_client=transport
    )
    with pytest.raises(SentinelError) as exc_info:
        client.analyze_image(IMAGE, "instruction")
    assert exc_info.value.code == "muse_spark_timeout"
    assert len(transport.calls) == 1


def test_timeout_logs_stage_and_elapsed_without_secrets(caplog):
    transport = _StubTransport([_timeout_exc()])
    client = MuseSparkClient(
        api_key=API_KEY, timeout_s=5.0, http_client=transport
    )
    with caplog.at_level(logging.INFO, logger="app.services.muse_spark_client"):
        with pytest.raises(SentinelError):
            client.analyze_image(IMAGE, "instruction")
    text = caplog.text
    assert "stage=ReadTimeout" in text
    assert "elapsed=" in text
    assert "timeout=5.0s" in text
    assert API_KEY not in text
    assert "Bearer" not in text
    assert "iVBORw0KGgo" not in text


def test_success_logs_duration_and_output_size(caplog):
    transport = _StubTransport([_ok_response()])
    client = MuseSparkClient(
        api_key=API_KEY, timeout_s=5.0, http_client=transport
    )
    with caplog.at_level(logging.INFO, logger="app.services.muse_spark_client"):
        assert (
            client.analyze_image(IMAGE, "instruction") == '{"findings": []}'
        )
    assert "Muse Spark response: http=200 elapsed=" in caplog.text
    assert "output text:" in caplog.text
    assert API_KEY not in caplog.text


def test_delayed_success_within_timeout():
    def slow_ok(url, headers=None, json=None, timeout=None):
        time.sleep(0.2)
        return _ok_response()

    class _Slow:
        def __init__(self):
            self.calls = 0

        def post(self, *args, **kwargs):
            self.calls += 1
            return slow_ok(*args, **kwargs)

    transport = _Slow()
    client = MuseSparkClient(
        api_key=API_KEY, timeout_s=5.0, http_client=transport
    )
    assert client.analyze_image(IMAGE, "instruction") == '{"findings": []}'
    assert transport.calls == 1


def test_recovery_after_timeout_on_fresh_attempt():
    transport = _StubTransport([_timeout_exc(), _ok_response()])
    client = MuseSparkClient(
        api_key=API_KEY, timeout_s=5.0, http_client=transport
    )
    with pytest.raises(SentinelError):
        client.analyze_image(IMAGE, "instruction")
    assert client.analyze_image(IMAGE, "instruction") == '{"findings": []}'
    assert len(transport.calls) == 2


def test_configured_timeout_reaches_transport():
    transport = _StubTransport([_ok_response(), _ok_response()])
    client = MuseSparkClient(
        api_key=API_KEY, timeout_s=42.5, http_client=transport
    )
    client.analyze_image(IMAGE, "instruction")
    assert transport.calls[0]["timeout"] == 42.5
    assert transport.calls[0]["url"].endswith("/responses")


def _png_bytes() -> bytes:
    from PIL import Image
    import io

    image = Image.new("RGB", (16, 16), color=(120, 130, 140))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class _FakeVision:
    def __init__(self, result: AgentResult) -> None:
        self._result = result

    def __call__(self, *args, **kwargs) -> "_FakeVision":
        return self

    def run(self, payload: dict) -> AgentResult:
        return self._result


class _FakeSam:
    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.model = "sam-3.1"

    def __call__(self, *args, **kwargs) -> "_FakeSam":
        return self

    def segment_image(self, image_data_url: str, prompt: str) -> Sam31Result:
        self.prompts.append(prompt)
        return Sam31Result()


def _smoke_finding(png: bytes) -> Finding:
    import hashlib

    evidence_id = f"sha256:{hashlib.sha256(png).hexdigest()}"
    return Finding(
        finding_id="vision-1",
        label="smoke",
        description="Observed: smoke in the distance.",
        confidence=Confidence(value=0.7),
        evidence_refs=[
            EvidenceRef(
                evidence_id=evidence_id,
                modality="image",
                uri_or_hash=evidence_id,
            )
        ],
    )


def test_vision_timeout_fails_service_then_recovers():
    png = _png_bytes()
    validated = media_service.validate_image_bytes(png, max_bytes=len(png) + 1)
    failing = _FakeVision(
        AgentResult(agent="vision", errors=["muse_spark_timeout: timed out"])
    )
    with pytest.raises(SentinelError) as exc_info:
        run_unified_analysis(
            validated, 16, 16, vision_factory=failing, sam_factory=_FakeSam()
        )
    assert exc_info.value.code == "vision_failed"
    recovered = _FakeVision(
        AgentResult(agent="vision", findings=[_smoke_finding(png)])
    )
    sam = _FakeSam()
    response = run_unified_analysis(
        validated, 16, 16, vision_factory=recovered, sam_factory=sam
    )
    assert [f.finding_id for f in response.findings] == ["vision-1"]
    assert sam.prompts == []
