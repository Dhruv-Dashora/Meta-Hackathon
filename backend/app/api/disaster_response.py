"""Disaster-response routes: assess + image analysis/segmentation."""

import hashlib
import io
import json

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile
from PIL import Image, ImageOps
from pydantic import BaseModel

from app.agents.vision_agent import VisionAgent
from app.core.config import settings
from app.core.errors import SentinelError
from app.schemas.disaster_response import DisasterAssessRequest, DisasterAssessResponse
from app.schemas.incident import (
    GeoContext,
    GeoStatus,
    IncidentDossier,
)
from app.schemas.segmentation import (
    SegmentImageInfo,
    SegmentImageResponse,
)
from app.schemas.unified_analysis import (
    UnifiedAnalysisResponse,
)
from app.services import media_service
from app.services.analysis_store import (
    SESSION_HEADER,
    analysis_store,
    session_store,
)
from app.services.geo_service import GeoValidationError, validate_geojson_bytes
from app.services.muse_spark_client import MuseSparkClient
from app.services.prompt_planner import MAX_USER_TARGET_CHARS, MAX_USER_TARGETS
from app.services.sam31_client import Sam31Client
from app.services.unified_service import (
    MIN_SAM_CALL_SECONDS,  # noqa: F401 (re-exported for compatibility)
    run_unified_analysis,
    to_segment_detections,
)

MAX_PROMPT_CHARS = 120

router = APIRouter(prefix="/disaster-response", tags=["disaster-response"])


@router.post("/assess", response_model=DisasterAssessResponse)
def assess(payload: DisasterAssessRequest) -> DisasterAssessResponse:
    return DisasterAssessResponse(incident_id="scaffold", findings=[])


async def _read_validated_upload_async(
    image: UploadFile,
) -> media_service.ValidatedImage:
    """Read and validate an image upload; raises HTTPException on problems."""
    try:
        raw = await media_service.read_upload_bounded(
            image, max_bytes=settings.max_image_bytes
        )
        return media_service.validate_image_bytes(
            raw, max_bytes=settings.max_image_bytes, filename=image.filename
        )
    except media_service.ImageValidationError as exc:
        raise HTTPException(
            status_code=exc.status_code, detail=f"{exc.code}: {exc.message}"
        ) from exc


def _image_dimensions(data: bytes) -> tuple[int, int]:
    """Authoritative displayed image size; raises HTTPException if unreadable."""
    Image.MAX_IMAGE_PIXELS = settings.max_image_pixels
    try:
        with Image.open(io.BytesIO(data)) as pil_image:
            # SAM coordinates use displayed size (post-EXIF-orientation).
            oriented = ImageOps.exif_transpose(pil_image)
            width, height = oriented.size
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail=f"unreadable_image: {type(exc).__name__}"
        ) from exc
    if width * height > settings.max_image_pixels:
        raise HTTPException(
            status_code=413,
            detail=(
                "image_too_many_pixels: decoded image exceeds "
                f"{settings.max_image_pixels} pixels."
            ),
        )
    return width, height


@router.post("/analyze-image", response_model=DisasterAssessResponse)
async def analyze_image(image: UploadFile = File(...)) -> DisasterAssessResponse:
    validated = await _read_validated_upload_async(image)
    data_url = media_service.image_to_data_url(validated)
    digest = hashlib.sha256(validated.data).hexdigest()
    evidence_id = f"sha256:{digest}"
    result = VisionAgent().run(
        {"image_data_url": data_url, "evidence_id": evidence_id}
    )
    if result.errors and not result.findings:
        raise HTTPException(status_code=502, detail="; ".join(result.errors))
    return DisasterAssessResponse(
        incident_id=f"img-{digest[:12]}", findings=result.findings
    )


@router.post("/segment-image", response_model=SegmentImageResponse)
async def segment_image(
    image: UploadFile = File(...), prompt: str = Form("")
) -> SegmentImageResponse:
    """Segment one image for one concrete concept prompt (SAM 3.1).

    Geometry only — boxes and masks, never damage/blockage assertions.

    The Form default is "" (not required): FastAPI converts an empty-string
    form value to missing, so Form(...) would answer HTTP 422. Our contract
    answers HTTP 400 for every prompt problem via the checks below.
    """
    normalized_prompt = prompt.strip()
    if not normalized_prompt:
        raise HTTPException(status_code=400, detail="empty_prompt: prompt is empty.")
    if len(normalized_prompt) > MAX_PROMPT_CHARS:
        raise HTTPException(
            status_code=400,
            detail=f"prompt_too_long: prompt exceeds {MAX_PROMPT_CHARS} chars.",
        )
    if any(ord(ch) < 32 for ch in normalized_prompt):
        raise HTTPException(
            status_code=400, detail="invalid_prompt: prompt has control chars."
        )
    validated = await _read_validated_upload_async(image)
    width, height = _image_dimensions(validated.data)
    data_url = media_service.image_to_data_url(validated)
    digest = hashlib.sha256(validated.data).hexdigest()
    evidence_id = f"sha256:{digest}"
    client = Sam31Client()
    try:
        result = client.segment_image(data_url, normalized_prompt)
    except SentinelError as exc:
        raise HTTPException(
            status_code=502, detail=f"{exc.code}: {exc.message}"
        ) from exc
    detections, box_warnings = to_segment_detections(
        result.detections, width, height
    )
    warnings = list(result.warnings) + box_warnings
    return SegmentImageResponse(
        image=SegmentImageInfo(
            width=width,
            height=height,
            mime_type=validated.mime_type,
            evidence_id=evidence_id,
        ),
        prompt=normalized_prompt,
        model=client.model,
        detections=detections,
        warnings=warnings,
    )


def _parse_user_targets(raw_targets: str) -> list[str]:
    """Split and validate the optional comma-separated targets field."""
    terms = [term.strip() for term in raw_targets.split(",")]
    targets = [term for term in terms if term]
    if len(targets) > MAX_USER_TARGETS:
        raise HTTPException(
            status_code=400,
            detail=f"targets_too_many: at most {MAX_USER_TARGETS} targets.",
        )
    for term in targets:
        if len(term) > MAX_USER_TARGET_CHARS:
            raise HTTPException(
                status_code=400,
                detail="target_too_long: target exceeds "
                f"{MAX_USER_TARGET_CHARS} chars.",
            )
        if any(ord(ch) < 32 for ch in term):
            raise HTTPException(
                status_code=400, detail="invalid_target: target has control chars."
            )
    return targets


def _require_session(session_id: str | None) -> str:
    """Validate the session binding header; raises HTTPException."""
    if not session_id:
        raise HTTPException(
            status_code=400,
            detail=f"missing_session: {SESSION_HEADER} header is required.",
        )
    if not session_store.valid(session_id):
        raise HTTPException(
            status_code=400,
            detail="invalid_session: session is unknown or expired.",
        )
    return session_id


@router.post("/analyze-and-segment", response_model=UnifiedAnalysisResponse)
async def analyze_and_segment(
    image: UploadFile = File(...),
    targets: str = Form(""),
    session_id: str | None = Header(default=None, alias=SESSION_HEADER),
) -> UnifiedAnalysisResponse:
    """One image -> Muse Spark findings -> targeted SAM geometry (sequential).

    Findings are always preserved when SAM fails, times out, or matches
    nothing. SAM output is geometry only; ``linked_finding_ids`` marks which
    findings triggered each prompt and never confirms them.

    ``targets`` is an optional comma-separated list of operator-requested
    segmentation concepts; they execute before automatic picks. When a
    valid session header is present, the server-generated response is
    cached and its ``analysis_ref`` is returned for report reuse.
    """
    user_targets = _parse_user_targets(targets)
    if session_id is not None and not session_store.valid(session_id):
        raise HTTPException(
            status_code=400,
            detail="invalid_session: session is unknown or expired.",
        )
    validated = await _read_validated_upload_async(image)
    width, height = _image_dimensions(validated.data)
    try:
        response = run_unified_analysis(
            validated,
            width,
            height,
            vision_factory=VisionAgent,
            spark_factory=MuseSparkClient,
            sam_factory=Sam31Client,
            user_targets=user_targets,
        )
    except SentinelError as exc:
        raise HTTPException(
            status_code=502, detail=f"{exc.code}: {exc.message}"
        ) from exc
    if session_id is not None:
        ref = analysis_store.store(
            session_id, response, width=width, height=height
        )
        if ref is None:
            response.warnings.append(
                "analysis_not_cached: response exceeded the cache size "
                "limit; reports must rebuild from the image."
            )
        else:
            response.analysis_ref = ref
    return response


class IncidentFromAnalysisRequest(BaseModel):
    """Build a dossier from server-cached vision evidence (no model calls)."""

    analysis_ref: str
    location_label: str = ""
    latitude: float | None = None
    longitude: float | None = None
    geojson: dict | None = None


@router.post("/assess-incident-from-analysis", response_model=IncidentDossier)
async def assess_incident_from_analysis(
    payload: IncidentFromAnalysisRequest,
    session_id: str | None = Header(default=None, alias=SESSION_HEADER),
) -> IncidentDossier:
    """Impact + reporting over a cached unified analysis (no model calls).

    Only server-held evidence is used: the reference plus the owning
    session id select the entry; client-submitted findings are never
    accepted. A miss or expired entry answers 404 and the operator must
    explicitly rebuild from the image.
    """
    from app.orchestrator.orchestrator import Orchestrator  # deferred: startup cost

    session_id = _require_session(session_id)
    cached = analysis_store.get(session_id, payload.analysis_ref)
    if cached is None:
        raise HTTPException(
            status_code=404,
            detail="analysis_not_found: cached analysis is unavailable or "
            "expired; rebuild the report from the image.",
        )
    geojson_bytes: bytes | None = None
    if payload.geojson is not None:
        geojson_bytes = json.dumps(payload.geojson).encode("utf-8")
    geo_context = _geo_context_from_parts(
        payload.location_label,
        _coordinate_or_none(payload.latitude, "latitude", -90.0, 90.0),
        _coordinate_or_none(payload.longitude, "longitude", -180.0, 180.0),
        geojson_bytes,
    )
    try:
        return Orchestrator().run_workflow_from_vision(
            "disaster_response",
            cached.response,
            geo_context,
            payload.analysis_ref,
        )
    except SentinelError as exc:
        status_code = 500 if exc.code == "cached_evidence_invalid" else 502
        raise HTTPException(
            status_code=status_code, detail=f"{exc.code}: {exc.message}"
        ) from exc


@router.post("/assess-incident", response_model=IncidentDossier)
async def assess_incident(
    image: UploadFile = File(...),
    location_label: str = Form(""),
    latitude: str = Form(""),
    longitude: str = Form(""),
    geojson: UploadFile | None = File(default=None),
) -> IncidentDossier:
    """Vision -> impact -> reporting dossier for one image (sequential).

    Optional geo fields/files are operator-provided and unverified: image
    contents are never inferred to correspond to supplied coordinates and
    no spatial analysis is performed.
    """
    from app.orchestrator.orchestrator import Orchestrator  # deferred: startup cost

    validated = await _read_validated_upload_async(image)
    width, height = _image_dimensions(validated.data)
    geo_context = await _operator_geo_context(
        location_label, latitude, longitude, geojson
    )
    try:
        return Orchestrator().run_workflow(
            "disaster_response",
            {
                "validated": validated,
                "width": width,
                "height": height,
                "geo_context": geo_context,
            },
        )
    except SentinelError as exc:
        raise HTTPException(
            status_code=502, detail=f"{exc.code}: {exc.message}"
        ) from exc


async def _operator_geo_context(
    location_label: str,
    latitude: str,
    longitude: str,
    geojson: UploadFile | None,
) -> GeoContext:
    """Build the operator geo context; raises HTTPException on bad input."""
    raw: bytes | None = None
    if geojson is not None and geojson.filename:
        raw = await geojson.read(settings.max_geojson_bytes + 1)
    return _geo_context_from_parts(
        location_label,
        _parse_coordinate(latitude, "latitude", -90.0, 90.0),
        _parse_coordinate(longitude, "longitude", -180.0, 180.0),
        raw,
    )


def _geo_context_from_parts(
    location_label: str,
    latitude: float | None,
    longitude: float | None,
    geojson_bytes: bytes | None,
) -> GeoContext:
    """Build the operator geo context; raises HTTPException on bad input."""
    label = location_label.strip()
    if (latitude is None) != (longitude is None):
        raise HTTPException(
            status_code=400,
            detail="incomplete_geo: provide both latitude and longitude or neither.",
        )
    feature_count: int | None = None
    if geojson_bytes is not None:
        if len(geojson_bytes) > settings.max_geojson_bytes:
            raise HTTPException(
                status_code=413,
                detail="geojson_too_large: GeoJSON exceeds the size limit.",
            )
        try:
            info = validate_geojson_bytes(
                geojson_bytes, max_bytes=settings.max_geojson_bytes
            )
        except GeoValidationError as exc:
            raise HTTPException(
                status_code=exc.status_code, detail=f"{exc.code}: {exc.message}"
            ) from exc
        feature_count = info.feature_count
    if not label and latitude is None and feature_count is None:
        return GeoContext(
            status=GeoStatus.UNAVAILABLE,
            note="No geospatial context provided; geo-dependent questions "
            "need operator follow-up.",
        )
    return GeoContext(
        status=GeoStatus.PROVIDED,
        location_label=label,
        latitude=latitude,
        longitude=longitude,
        geojson_feature_count=feature_count,
        note="Operator-provided location context; image contents are not "
        "verified to correspond to these coordinates.",
    )


def _coordinate_or_none(
    value: float | None, name: str, low: float, high: float
) -> float | None:
    if value is None:
        return None
    if not low <= value <= high:
        raise HTTPException(
            status_code=400, detail=f"invalid_geo: {name} out of range."
        )
    return value


def _parse_coordinate(
    value: str, name: str, low: float, high: float
) -> float | None:
    text = value.strip()
    if not text:
        return None
    try:
        number = float(text)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail=f"invalid_geo: {name} is not a number."
        ) from exc
    if not low <= number <= high:
        raise HTTPException(
            status_code=400, detail=f"invalid_geo: {name} out of range."
        )
    return number
