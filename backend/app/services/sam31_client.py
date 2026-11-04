"""Meta SAM 3.1 segmentation client (Responses API via httpx).

Endpoint: POST {base_url}/responses, model sam-3.1 (non-streaming).
Auth: Bearer [REDACTED] (backend env only — never logged or returned).
Request: one message with a short noun-phrase ``input_text`` prompt plus one
``input_image`` data URL, ``metadata: {"mask_encoding": "one_bit"}``.
Output: special-token segmentation grammar in the ``output_text`` lane —
parsed ONLY with the official ``meta_sam_parser`` library, never by hand.

Official docs: https://dev.meta.ai/docs/sam/overview
              https://dev.meta.ai/docs/sam/segmenting
              https://dev.meta.ai/docs/sam/reading-segmentation
              https://dev.meta.ai/docs/sam/client-libraries
              https://dev.meta.ai/docs/protocols/responses

Non-streaming is the documented reliable path for single images: it "runs
the same segmentation and returns the complete result in one response, in
the same format". Streaming only adds progressive frame rendering, which
matters for long video clips, not single images.

Operational logging (INFO): request model/URL/truncated prompt, HTTP status
plus elapsed time, envelope shape (field names, status, output-item count,
lane found, content-part types and text lengths), output-text length, and
detection count. Parser diagnostics are logged sanitized (code/message/line
only). Never logs API keys, auth headers, images, request bodies, or raw
segmentation payloads.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.errors import SentinelError
from app.core.logging import get_logger

logger = get_logger(__name__)
# Diagnostic lines below are INFO so routine calls stay quiet-yet-visible.
# Set explicitly: hosting defaults (uvicorn/pytest) otherwise leave this
# logger at WARNING and the diagnostics would never surface.
logger.setLevel(logging.INFO)

MASK_ENCODING = "one_bit"
MAX_LOG_PROMPT_CHARS = 80
MAX_LOG_DIAG_MESSAGE_CHARS = 200


@dataclass(frozen=True)
class Sam31Box:
    """Half-open box in source-image pixels (x2/y2 exclusive)."""

    x1: int
    y1: int
    x2: int
    y2: int


@dataclass(frozen=True)
class Sam31Mask:
    """Decoded mask: raster size plus SVG-path and COCO-RLE encodings."""

    width: int
    height: int
    svg_path: str
    rle_counts: str


@dataclass(frozen=True)
class Sam31Detection:
    object_id: str
    box: Sam31Box
    mask: Sam31Mask


@dataclass(frozen=True)
class Sam31Result:
    detections: list[Sam31Detection] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class Sam31Client:
    """Minimal client: one image + noun-phrase prompt per request."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout_s: float | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        from app.core.config import settings  # deferred import for tests

        self._api_key = api_key if api_key is not None else settings.model_api_key
        self._base_url = (base_url or settings.sam31_base_url).rstrip("/")
        self._model = model or settings.sam31_model
        self._timeout_s = timeout_s if timeout_s is not None else settings.sam31_timeout_s
        self._http_client = http_client

    @property
    def model(self) -> str:
        return self._model

    def segment_image(self, image_data_url: str, prompt: str) -> Sam31Result:
        """Segment one image for one concept prompt; never raises raw errors."""
        if not self._api_key:
            raise SentinelError(
                "model_api_key_missing", "MODEL_API_KEY is not configured."
            )
        payload = {
            "model": self._model,
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {"type": "input_image", "image_url": image_data_url},
                    ],
                }
            ],
            "metadata": {"mask_encoding": MASK_ENCODING},
        }
        url = f"{self._base_url}/responses"
        # Safe: model, URL, and short operator prompt only — never the key,
        # headers, data URL, or request body.
        logger.info(
            "SAM 3.1 request: model=%s url=%s prompt=%r",
            self._model,
            url,
            prompt[:MAX_LOG_PROMPT_CHARS],
        )
        started = time.perf_counter()
        try:
            if self._http_client is not None:
                response = self._http_client.post(
                    url,
                    headers=self._auth_headers(),
                    json=payload,
                    timeout=self._timeout_s,
                )
            else:
                with httpx.Client(timeout=self._timeout_s) as client:
                    response = client.post(
                        url,
                        headers=self._auth_headers(),
                        json=payload,
                        timeout=self._timeout_s,
                    )
        except httpx.TimeoutException as exc:
            logger.warning("SAM 3.1 timeout after %.2fs", time.perf_counter() - started)
            raise SentinelError(
                "sam31_timeout", "SAM 3.1 request timed out."
            ) from exc
        except httpx.HTTPError as exc:
            logger.warning(
                "SAM 3.1 transport error after %.2fs", time.perf_counter() - started
            )
            raise SentinelError(
                "sam31_transport_error", "SAM 3.1 request failed."
            ) from exc
        elapsed = time.perf_counter() - started
        logger.info(
            "SAM 3.1 response: http=%s elapsed=%.2fs",
            response.status_code,
            elapsed,
        )
        if response.status_code >= 400:
            logger.warning("SAM 3.1 HTTP error: status=%s", response.status_code)
            raise SentinelError(
                "sam31_http_error",
                f"SAM 3.1 returned HTTP {response.status_code}.",
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise SentinelError(
                "sam31_bad_response", "SAM 3.1 returned invalid JSON."
            ) from exc
        text = extract_segmentation_text(body)
        logger.info("SAM 3.1 output text: %d chars", len(text))
        if text == "":
            # Documented zero-match signal: lane present but blank. Genuine
            # zero, not a parse failure — the parser has nothing to run on.
            logger.info("SAM 3.1 zero detections: empty output lane, no diagnostics")
            return Sam31Result()
        result = parse_segmentation_text(text)
        logger.info(
            "SAM 3.1 parsed: %d detections (%d warnings)",
            len(result.detections),
            len(result.warnings),
        )
        if result.warnings:
            logger.info("SAM 3.1 warnings: %s", "; ".join(result.warnings))
        return result

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}


def extract_segmentation_text(body: Any) -> str:
    """Extract the output-text lane from a non-streaming Responses body.

    Documented shapes only: top-level ``output_text``, or ``output`` items
    with ``output_text`` content parts. ``status`` other than ``completed``
    is an error. A present-but-empty lane is a valid zero-match result;
    a missing lane is a malformed response.
    """
    if not isinstance(body, dict):
        logger.warning("SAM 3.1 envelope: body is %s, not an object", type(body).__name__)
        raise SentinelError(
            "sam31_bad_response", "SAM 3.1 returned an unexpected body."
        )
    status = body.get("status")
    if status is not None and status != "completed":
        detail = ""
        error = body.get("error")
        if isinstance(error, dict) and error.get("code"):
            detail = f" ({error['code']})"
        logger.warning("SAM 3.1 envelope: status=%r%s", status, detail)
        raise SentinelError(
            "sam31_bad_response",
            f"SAM 3.1 response status is {status!r}{detail}.",
        )
    texts: list[str] = []
    lane_sources: list[str] = []
    part_summary: list[str] = []
    skipped = 0
    direct = body.get("output_text")
    if isinstance(direct, str):
        lane_sources.append("top-level")
        if direct.strip():
            texts.append(direct)
    output = body.get("output")
    if isinstance(output, list):
        output_shape = f"list[{len(output)}]"
        for item in output:
            if not isinstance(item, dict):
                skipped += 1
                continue
            content = item.get("content")
            if not isinstance(content, list):
                skipped += 1
                continue
            for part in content:
                if not isinstance(part, dict):
                    skipped += 1
                    continue
                part_text = part.get("text")
                # Structure only: part types and text lengths, never content.
                part_summary.append(
                    f"{part.get('type')}:{len(part_text)}ch"
                    if isinstance(part_text, str)
                    else f"{part.get('type')}:nonstr"
                )
                if part.get("type") == "output_text" and isinstance(part_text, str):
                    if "output-items" not in lane_sources:
                        lane_sources.append("output-items")
                    if part_text.strip():
                        texts.append(part_text)
    elif "output" in body:
        output_shape = type(output).__name__
        skipped += 1
    else:
        output_shape = "absent"
    # Field names, counts, and lengths only — never payload content. This line
    # distinguishes genuine zero matches (blank documented lane) from shape
    # mismatches (non-empty text in an undocumented location).
    logger.info(
        "SAM 3.1 envelope: status=%r fields=%s output=%s lane=%s content=[%s] skipped=%d",
        status,
        sorted(body.keys()),
        output_shape,
        "+".join(lane_sources) if lane_sources else "none",
        ",".join(part_summary),
        skipped,
    )
    if not lane_sources:
        raise SentinelError(
            "sam31_bad_response", "SAM 3.1 returned no output text."
        )
    return "\n".join(texts)


def _diagnostic_summary(diag: Any) -> str:
    """One-line parser diagnostic WITHOUT the raw wire payload.

    ``str(diagnostic)`` embeds the full grammar line in ``raw=...``; that must
    never reach logs or API warnings, so only code/message/line are kept.
    """
    code = getattr(diag, "code", None) or "unknown"
    message = getattr(diag, "message", None)
    if not isinstance(message, str) or not message:
        message = type(diag).__name__
    line = getattr(diag, "line", None)
    suffix = f" (line {line})" if isinstance(line, int) else ""
    return f"sam31_parser[{code}]: {message[:MAX_LOG_DIAG_MESSAGE_CHARS]}{suffix}"


def parse_segmentation_text(text: str) -> Sam31Result:
    """Parse SAM grammar text into detections via ``meta_sam_parser``."""
    try:
        from meta_sam_parser import (  # deferred: optional until installed
            CompletedOutcome,
            SegmentationBoxRecord,
            SegmentationMaskRecord,
            decode_mask_to_rle,
            decode_mask_to_svg_path,
            image_segmentation_format,
        )
    except ImportError as exc:
        # A missing/broken parser is a SAM failure like any other: the
        # unified workflow turns it into a failed segmentation and
        # preserves the vision findings instead of crashing the request.
        raise SentinelError(
            "sam31_unavailable", "SAM 3.1 parser is unavailable."
        ) from exc

    try:
        parser = image_segmentation_format().create_parser()
        for _snapshot in parser.push(text):
            pass
        finished = parser.finish(CompletedOutcome())
    except Exception as exc:
        raise SentinelError(
            "sam31_malformed_output", "SAM 3.1 returned unparsable output."
        ) from exc
    result = finished.result
    # Record shapes per the documented cross-language contract: box records
    # carry half-open left/top/right/bottom directly (the 0.1.0 run proved
    # there is no .bounds on box records), both record kinds carry object_id
    # (str), mask records carry .mask. Wire w/h is NOT read back — the route
    # validates boxes against authoritative Pillow dims.
    warnings = [
        _diagnostic_summary(d) for d in getattr(result, "diagnostics", None) or []
    ]
    boxes: dict[str, Any] = {}
    masks: dict[str, Any] = {}
    for record in result.records:
        if isinstance(record, SegmentationBoxRecord):
            boxes.setdefault(record.object_id, record)
        elif isinstance(record, SegmentationMaskRecord):
            masks.setdefault(record.object_id, record)
    detections: list[Sam31Detection] = []
    for object_id in boxes.keys() | masks.keys():
        box_record = boxes.get(object_id)
        mask_record = masks.get(object_id)
        if box_record is None or mask_record is None:
            warnings.append(f"sam31_partial_record: object {object_id!r} skipped.")
            continue
        x1, y1, x2, y2 = (
            box_record.left,
            box_record.top,
            box_record.right,
            box_record.bottom,
        )
        if not _valid_box_coords(x1, y1, x2, y2):
            warnings.append(f"sam31_invalid_box: object {object_id!r} skipped.")
            continue
        try:
            rle = decode_mask_to_rle(mask_record.mask)
            svg_path = decode_mask_to_svg_path(mask_record.mask)
            mask_height, mask_width = rle.size
            detection = Sam31Detection(
                object_id=object_id,
                box=Sam31Box(x1=x1, y1=y1, x2=x2, y2=y2),
                mask=Sam31Mask(
                    width=mask_width,
                    height=mask_height,
                    svg_path=svg_path,
                    rle_counts=rle.counts,
                ),
            )
        except MemoryError:
            raise
        except Exception as exc:
            warnings.append(f"sam31_invalid_mask: object {object_id!r} skipped.")
            logger.warning("SAM 3.1 mask decode failed: %s", type(exc).__name__)
            continue
        detections.append(detection)
    detections.sort(key=lambda d: d.object_id)
    if not detections:
        # Sanitized summaries only — never raw payloads (see _diagnostic_summary).
        logger.warning(
            "SAM 3.1 no usable detections from %d chars: %s",
            len(text),
            "; ".join(warnings) if warnings else "no parser diagnostics",
        )
        raise SentinelError(
            "sam31_malformed_output",
            "SAM 3.1 returned no usable detections.",
        )
    return Sam31Result(detections=detections, warnings=warnings)


def _valid_box_coords(x1: Any, y1: Any, x2: Any, y2: Any) -> bool:
    """Internal box sanity (non-negative, strictly ordered half-open)."""
    if not all(isinstance(v, int) and not isinstance(v, bool) for v in (x1, y1, x2, y2)):
        return False
    return 0 <= x1 < x2 and 0 <= y1 < y2
