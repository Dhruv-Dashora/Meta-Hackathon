"""Segment-image slice tests (mocked model — never calls the real API)."""

import io
import json
import logging
import re

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.api import disaster_response
from app.core.errors import SentinelError
from app.main import app
from app.services.sam31_client import (
    Sam31Box,
    Sam31Client,
    Sam31Detection,
    Sam31Mask,
    Sam31Result,
    extract_segmentation_text,
    parse_segmentation_text,
)

client = TestClient(app)

# Real SAM grammar sample from the meta_sam_parser documentation: frame 0,
# two objects, 320x334 source, lossless masks (27x60 and 27x48). Offline,
# deterministic, exercises the real parser incl. base85 mask decoding.
SAMPLE_GRAMMAR = (
    "<0f>0<|box;x1=211;y1=228;x2=270;y2=254;w=320;h=334|>"
    "<|mask;x=0;y=0;data=27,60,~!!!!M!0c[0o91w?q1!pIH4pPRVp2B3'7`e.ioeAf6-k/#Xd8%dX9x(|>"
    ",1<|box;x1=155;y1=228;x2=202;y2=254;w=320;h=334|>"
    "<|mask;x=0;y=0;data=27,48,~!!!!J!0c[q=Pj_zs=*4C4(/./x#:/`S_GnD`=o3?X{emCgO$y@|>\n"
)

GIF_BYTES = b"GIF89a" + b"\x00" * 32
FAKE_PNG_BYTES = bytes.fromhex("89504e470d0a1a0a") + b"\x00" * 32


def _png_bytes(width: int = 320, height: int = 334) -> bytes:
    image = Image.new("RGB", (width, height), color=(120, 130, 140))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _upload(data: bytes, prompt: str | None = "road", filename: str = "scene.png"):
    form: dict[str, str] = {}
    if prompt is not None:
        form["prompt"] = prompt
    return client.post(
        "/api/disaster-response/segment-image",
        files={"image": (filename, data, "image/png")},
        data=form,
    )


def _detection(
    object_id: str = "0",
    box: Sam31Box | None = None,
) -> Sam31Detection:
    return Sam31Detection(
        object_id=object_id,
        box=box or Sam31Box(x1=10, y1=20, x2=30, y2=40),
        mask=Sam31Mask(width=60, height=27, svg_path="M0 0L1 0L1 1Z", rle_counts="abc"),
    )


class _FakeClient:
    def __init__(
        self, result: Sam31Result | None = None, error: Exception | None = None
    ) -> None:
        self._result = result or Sam31Result()
        self._error = error
        self.seen: dict | None = None
        self.model = "sam-3.1"

    def segment_image(self, image_data_url: str, prompt: str) -> Sam31Result:
        self.seen = {"image_data_url": image_data_url, "prompt": prompt}
        if self._error is not None:
            raise self._error
        return self._result


# --- endpoint tests (Sam31Client mocked) ---


def test_segment_image_success(monkeypatch):
    fake = _FakeClient(Sam31Result(detections=[_detection()]))
    monkeypatch.setattr(disaster_response, "Sam31Client", lambda: fake)
    resp = _upload(_png_bytes(), "road")
    assert resp.status_code == 200
    body = resp.json()
    assert body["prompt"] == "road"
    assert body["model"] == "sam-3.1"
    assert body["image"]["width"] == 320
    assert body["image"]["height"] == 334
    assert body["image"]["mime_type"] == "image/png"
    assert body["image"]["evidence_id"].startswith("sha256:")
    assert len(body["detections"]) == 1
    detection = body["detections"][0]
    assert detection["object_id"] == "0"
    assert detection["box"] == {"x1": 10, "y1": 20, "x2": 30, "y2": 40}
    assert detection["mask"]["width"] == 60
    assert body["warnings"] == []
    assert fake.seen is not None
    assert fake.seen["image_data_url"].startswith("data:image/png;base64,")
    assert fake.seen["prompt"] == "road"


def test_segment_image_empty_detections_is_valid(monkeypatch):
    fake = _FakeClient(Sam31Result())
    monkeypatch.setattr(disaster_response, "Sam31Client", lambda: fake)
    resp = _upload(_png_bytes(), "vehicle")
    assert resp.status_code == 200
    assert resp.json()["detections"] == []


def test_segment_image_drops_out_of_bounds_box_with_warning(monkeypatch):
    # Route validates boxes against authoritative Pillow dims (320x334 here):
    # the out-of-bounds detection is dropped with a warning, the valid one stays.
    result = Sam31Result(
        detections=[
            _detection("0", Sam31Box(x1=0, y1=0, x2=9999, y2=9999)),
            _detection("1"),
        ]
    )
    fake = _FakeClient(result)
    monkeypatch.setattr(disaster_response, "Sam31Client", lambda: fake)
    resp = _upload(_png_bytes(), "road")
    assert resp.status_code == 200
    body = resp.json()
    assert [d["object_id"] for d in body["detections"]] == ["1"]
    assert any("out_of_bounds" in w for w in body["warnings"])


@pytest.mark.parametrize("prompt", ["", "   "])
def test_segment_image_rejects_empty_prompt(monkeypatch, prompt):
    fake = _FakeClient(Sam31Result(detections=[_detection()]))
    monkeypatch.setattr(disaster_response, "Sam31Client", lambda: fake)
    resp = _upload(_png_bytes(), prompt)
    assert resp.status_code == 400
    assert "empty_prompt" in resp.json()["detail"]
    assert fake.seen is None


def test_segment_image_rejects_long_prompt(monkeypatch):
    fake = _FakeClient(Sam31Result(detections=[_detection()]))
    monkeypatch.setattr(disaster_response, "Sam31Client", lambda: fake)
    resp = _upload(_png_bytes(), "x" * 121)
    assert resp.status_code == 400
    assert "prompt_too_long" in resp.json()["detail"]
    assert fake.seen is None


def test_segment_image_rejects_control_chars(monkeypatch):
    fake = _FakeClient(Sam31Result(detections=[_detection()]))
    monkeypatch.setattr(disaster_response, "Sam31Client", lambda: fake)
    resp = _upload(_png_bytes(), "road\nvehicle")
    assert resp.status_code == 400
    assert "invalid_prompt" in resp.json()["detail"]
    assert fake.seen is None


def test_segment_image_rejects_missing_prompt(monkeypatch):
    fake = _FakeClient(Sam31Result(detections=[_detection()]))
    monkeypatch.setattr(disaster_response, "Sam31Client", lambda: fake)
    resp = _upload(_png_bytes(), None)
    assert resp.status_code == 400
    assert "empty_prompt" in resp.json()["detail"]
    assert fake.seen is None


def test_segment_image_rejects_wrong_content(monkeypatch):
    fake = _FakeClient(Sam31Result(detections=[_detection()]))
    monkeypatch.setattr(disaster_response, "Sam31Client", lambda: fake)
    resp = _upload(GIF_BYTES, "road")
    assert resp.status_code == 400
    assert "unsupported_image_type" in resp.json()["detail"]
    assert fake.seen is None


def test_segment_image_rejects_unreadable_image(monkeypatch):
    fake = _FakeClient(Sam31Result(detections=[_detection()]))
    monkeypatch.setattr(disaster_response, "Sam31Client", lambda: fake)
    # PNG magic bytes but not a decodable image: validation passes, PIL fails.
    resp = _upload(FAKE_PNG_BYTES, "road")
    assert resp.status_code == 400
    assert "unreadable_image" in resp.json()["detail"]
    assert fake.seen is None


def test_segment_image_rejects_oversize(monkeypatch):
    fake = _FakeClient(Sam31Result(detections=[_detection()]))
    monkeypatch.setattr(disaster_response, "Sam31Client", lambda: fake)
    monkeypatch.setattr(disaster_response.settings, "max_image_bytes", 8)
    resp = _upload(_png_bytes(), "road")
    assert resp.status_code == 413
    assert fake.seen is None


def test_segment_image_model_failure_is_502(monkeypatch):
    fake = _FakeClient(error=SentinelError("sam31_timeout", "timed out"))
    monkeypatch.setattr(disaster_response, "Sam31Client", lambda: fake)
    resp = _upload(_png_bytes(), "road")
    assert resp.status_code == 502
    assert "sam31_timeout" in resp.json()["detail"]


# --- Sam31Client tests (httpx MockTransport — no network) ---


def _mocked_client(handler, **kwargs) -> Sam31Client:
    transport = httpx.MockTransport(handler)
    return Sam31Client(
        api_key="test-key",
        base_url="https://api.meta.ai/v1",
        model="sam-3.1",
        http_client=httpx.Client(transport=transport),
        **kwargs,
    )


def test_client_sends_exact_sam_request():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={"status": "completed", "output_text": ""})

    result = _mocked_client(handler).segment_image("data:image/png;base64,AAA", "road")
    assert result.detections == []
    assert seen["url"] == "https://api.meta.ai/v1/responses"
    assert seen["auth"] == "Bearer test-key"
    assert seen["body"]["model"] == "sam-3.1"
    message = seen["body"]["input"][0]
    assert message["type"] == "message"
    assert message["role"] == "user"
    content = message["content"]
    assert content[0] == {"type": "input_text", "text": "road"}
    assert content[1]["type"] == "input_image"
    assert content[1]["image_url"] == "data:image/png;base64,AAA"
    assert seen["body"]["metadata"] == {"mask_encoding": "one_bit"}


def test_client_parses_output_items_envelope():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": SAMPLE_GRAMMAR}],
                    }
                ],
            },
        )

    result = _mocked_client(handler).segment_image("data:image/png;base64,AAA", "road")
    assert [d.object_id for d in result.detections] == ["0", "1"]


def test_client_empty_lane_is_zero_matches():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "completed", "output_text": "  "})

    result = _mocked_client(handler).segment_image("data:image/png;base64,AAA", "road")
    assert result == Sam31Result()


def test_client_failed_status_is_bad_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"status": "failed", "error": {"code": "server_error"}, "output": []},
        )

    with pytest.raises(SentinelError) as exc_info:
        _mocked_client(handler).segment_image("data:image/png;base64,AAA", "road")
    assert exc_info.value.code == "sam31_bad_response"


def test_client_missing_lane_is_bad_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "completed", "output": []})

    with pytest.raises(SentinelError) as exc_info:
        _mocked_client(handler).segment_image("data:image/png;base64,AAA", "road")
    assert exc_info.value.code == "sam31_bad_response"


def test_client_garbage_output_is_malformed():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "completed", "output_text": "hello??"})

    with pytest.raises(SentinelError) as exc_info:
        _mocked_client(handler).segment_image("data:image/png;base64,AAA", "road")
    assert exc_info.value.code == "sam31_malformed_output"


def test_client_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    with pytest.raises(SentinelError) as exc_info:
        _mocked_client(handler).segment_image("data:image/png;base64,AAA", "road")
    assert exc_info.value.code == "sam31_http_error"


def test_client_bad_json():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json")

    with pytest.raises(SentinelError) as exc_info:
        _mocked_client(handler).segment_image("data:image/png;base64,AAA", "road")
    assert exc_info.value.code == "sam31_bad_response"


def test_client_timeout():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow")

    with pytest.raises(SentinelError) as exc_info:
        _mocked_client(handler).segment_image("data:image/png;base64,AAA", "road")
    assert exc_info.value.code == "sam31_timeout"


def test_client_missing_key_makes_no_request():
    requested = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requested
        requested = True
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(handler)
    client = Sam31Client(api_key="", http_client=httpx.Client(transport=transport))
    with pytest.raises(SentinelError) as exc_info:
        client.segment_image("data:image/png;base64,AAA", "road")
    assert exc_info.value.code == "model_api_key_missing"
    assert requested is False


# --- envelope extraction ---


def test_extract_segmentation_text_shapes():
    assert extract_segmentation_text({"output_text": " hi "}) == " hi "
    body = {
        "output": [
            {"content": [{"type": "output_text", "text": "a"}]},
            {"content": [{"type": "output_text", "text": "b"}]},
        ]
    }
    assert extract_segmentation_text(body) == "a\nb"
    assert extract_segmentation_text({"status": "completed", "output_text": ""}) == ""
    with pytest.raises(SentinelError):
        extract_segmentation_text({"status": "incomplete"})
    with pytest.raises(SentinelError):
        extract_segmentation_text({"status": "completed"})
    with pytest.raises(SentinelError):
        extract_segmentation_text([])


# --- grammar parsing + geometry/alignment (real parser, offline) ---


def test_parse_sample_yields_two_detections():
    result = parse_segmentation_text(SAMPLE_GRAMMAR)
    assert [d.object_id for d in result.detections] == ["0", "1"]
    first = result.detections[0]
    # Wire x2/y2 are inclusive; our boxes are half-open (+1).
    assert (first.box.x1, first.box.y1, first.box.x2, first.box.y2) == (211, 228, 271, 255)
    assert (first.mask.width, first.mask.height) == (60, 27)
    assert first.mask.svg_path != ""
    assert first.mask.rle_counts != ""


def _parsed_sample_masks():
    """Client result plus raw parser masks for SAMPLE_GRAMMAR (offline)."""
    from meta_sam_parser import (
        CompletedOutcome,
        SegmentationMaskRecord,
        image_segmentation_format,
    )

    parser = image_segmentation_format().create_parser()
    for _snapshot in parser.push(SAMPLE_GRAMMAR):
        pass
    records = parser.finish(CompletedOutcome()).result.records
    masks = {
        record.object_id: record.mask
        for record in records
        if isinstance(record, SegmentationMaskRecord)
    }
    return parse_segmentation_text(SAMPLE_GRAMMAR), masks


def test_svg_path_coordinates_use_mask_pixel_frame():
    # Real 0.1.0 output traces pixel corners around pixel centers, so coords
    # span [-0.5, W-0.5] x [-0.5, H-0.5] in mask-local coordinates. The path
    # bbox equals the raster foreground bbox expanded by exactly 0.5, and the
    # frontend places the SVG at the box origin for 1:1 alignment.
    from meta_sam_parser import decode_mask_to_raster

    result, masks = _parsed_sample_masks()
    for detection in result.detections:
        numbers = [float(v) for v in re.findall(r"-?\d+(?:\.\d+)?", detection.mask.svg_path)]
        assert numbers and len(numbers) % 2 == 0
        xs = numbers[0::2]
        ys = numbers[1::2]
        assert min(xs) >= -0.5 and max(xs) <= detection.mask.width - 0.5
        assert min(ys) >= -0.5 and max(ys) <= detection.mask.height - 0.5
        raster = decode_mask_to_raster(masks[detection.object_id])
        foreground = [i for i, v in enumerate(raster) if v == 1]
        cols = [i % detection.mask.width for i in foreground]
        rows = [i // detection.mask.width for i in foreground]
        assert min(xs) == min(cols) - 0.5
        assert max(xs) == max(cols) + 0.5
        assert min(ys) == min(rows) - 0.5
        assert max(ys) == max(rows) + 0.5


def test_mask_foreground_aligns_with_box():
    """Mask foreground placed at its box origin must sit inside the box.

    Placement contract (verified on real 0.1.0 decoder output): mask rasters
    are box-sized and box-local, so foreground pixel (col, row) maps to image
    (x1 + col, y1 + row) at 1:1 — the transformation the frontend implements
    with a nested SVG at the box origin. (An earlier full-frame scaling was
    wrong: it stretched box-sized masks across the whole image.)
    """
    from meta_sam_parser import decode_mask_to_raster

    result, masks = _parsed_sample_masks()
    assert len(result.detections) == 2
    for detection in result.detections:
        box = detection.box
        box_w, box_h = box.x2 - box.x1, box.y2 - box.y1
        assert (detection.mask.width, detection.mask.height) == (box_w, box_h)
        raster = decode_mask_to_raster(masks[detection.object_id])
        assert len(raster) == detection.mask.width * detection.mask.height
        foreground = [i for i, v in enumerate(raster) if v == 1]
        assert foreground
        cols = [i % detection.mask.width for i in foreground]
        rows = [i // detection.mask.width for i in foreground]
        scale_x = box_w / detection.mask.width
        scale_y = box_h / detection.mask.height
        fx1 = box.x1 + min(cols) * scale_x
        fy1 = box.y1 + min(rows) * scale_y
        fx2 = box.x1 + (max(cols) + 1) * scale_x
        fy2 = box.y1 + (max(rows) + 1) * scale_y
        assert fx1 >= box.x1 and fy1 >= box.y1
        assert fx2 <= box.x2 and fy2 <= box.y2


def test_invalid_box_record_rejects_line():
    # Observed meta-sam-parser 0.1.0 behavior: inverted box corners fail the
    # strict parse with no usable detections, so the client surfaces
    # sam31_malformed_output (HTTP 502 at the route) — never silent partials.
    bad_box = SAMPLE_GRAMMAR.replace(
        "0<|box;x1=211;y1=228;x2=270;y2=254;w=320;h=334|>",
        "0<|box;x1=270;y1=228;x2=211;y2=254;w=320;h=334|>",
        1,
    )
    with pytest.raises(SentinelError) as exc_info:
        parse_segmentation_text(bad_box)
    assert exc_info.value.code == "sam31_malformed_output"


def test_truncated_mask_payload_drops_record_with_warning():
    # Truncation breaks exact-length validation: the real 0.1.0 parser reports
    # an invalid_mask_payload diagnostic and drops that record while the valid
    # sibling survives — partial results always carry warnings, never silence.
    trunc = SAMPLE_GRAMMAR.replace("dX9x(|>", "(|>", 1)
    result = parse_segmentation_text(trunc)
    assert [d.object_id for d in result.detections] == ["1"]
    assert result.warnings != []


def test_all_records_unusable_is_malformed():
    with pytest.raises(SentinelError) as exc_info:
        parse_segmentation_text("<0f>0<|box;x1=1;y1=1;x2=2;w=320|>")
    assert exc_info.value.code == "sam31_malformed_output"


def test_parser_diagnostic_warnings_exclude_raw_payload():
    trunc = SAMPLE_GRAMMAR.replace("dX9x(|>", "(|>", 1)
    result = parse_segmentation_text(trunc)
    assert result.warnings != []
    assert any("invalid_mask_payload" in w for w in result.warnings)
    for warning in result.warnings:
        assert "raw=" not in warning
        assert "<0f>" not in warning
        assert "data=27,60" not in warning


# --- diagnostic logging (caplog — no network, no secrets) ---


def test_logging_summarizes_empty_lane_without_secrets(caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "completed", "output_text": ""})

    with caplog.at_level(logging.INFO, logger="app.services.sam31_client"):
        result = _mocked_client(handler).segment_image(
            "data:image/png;base64,QUJDREVGR0g=", "trees"
        )
    assert result.detections == []
    text = caplog.text
    assert "model=sam-3.1" in text
    assert "https://api.meta.ai/v1/responses" in text
    assert "prompt='trees'" in text
    assert "http=200" in text
    assert "elapsed=" in text
    assert "lane=top-level" in text
    assert "output text: 0 chars" in text
    assert "zero detections" in text
    assert "QUJDREVGR0g=" not in text
    assert "test-key" not in text
    assert "Authorization" not in text


def test_logging_reports_http_failures(caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    with caplog.at_level(logging.INFO, logger="app.services.sam31_client"):
        with pytest.raises(SentinelError):
            _mocked_client(handler).segment_image("data:image/png;base64,AAA", "road")
    assert "http=500" in caplog.text
    assert "HTTP error" in caplog.text


def test_logging_reports_rejected_envelope(caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"status": "failed", "error": {"code": "server_error"}}
        )

    with caplog.at_level(logging.INFO, logger="app.services.sam31_client"):
        with pytest.raises(SentinelError) as exc_info:
            _mocked_client(handler).segment_image("data:image/png;base64,AAA", "road")
    assert exc_info.value.code == "sam31_bad_response"
    assert "status='failed'" in caplog.text


def test_logging_reports_detections_and_unparsable_output(caplog):
    def ok_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"status": "completed", "output_text": SAMPLE_GRAMMAR}
        )

    def bad_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "completed", "output_text": "hi??"})

    with caplog.at_level(logging.INFO, logger="app.services.sam31_client"):
        result = _mocked_client(ok_handler).segment_image(
            "data:image/png;base64,AAA", "road"
        )
    assert len(result.detections) == 2
    assert "parsed: 2 detections" in caplog.text
    assert SAMPLE_GRAMMAR[:40] not in caplog.text
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="app.services.sam31_client"):
        with pytest.raises(SentinelError):
            _mocked_client(bad_handler).segment_image("data:image/png;base64,AAA", "road")
    assert "no usable detections" in caplog.text
    assert "hi??" not in caplog.text
