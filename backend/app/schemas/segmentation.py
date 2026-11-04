"""Segmentation schemas for SAM 3.1 image results.

Coordinate convention (documented, frontend-compatible):
- All boxes are in SOURCE IMAGE pixels, origin at the top-left.
- Boxes are HALF-OPEN: x1/y1 inclusive, x2/y2 exclusive, so
  ``width = x2 - x1`` and ``height = y2 - y1``. (The SAM wire format sends
  inclusive x2/y2; ``meta_sam_parser`` normalizes to half-open right/bottom
  and this schema keeps that normalized form.)
- Masks are BOX-LOCAL rasters: width/height equal the paired box's
  width/height (verified on real decoder output). ``svg_path`` traces
  pixel corners spanning [-0.5, width-0.5] x [-0.5, height-0.5] in
  mask-local coordinates. Render by placing an SVG element at the box
  origin sized to the box, with
  ``viewBox="-0.5 -0.5 {width} {height}"`` and
  ``preserveAspectRatio="none"`` — mask edges then land exactly on the
  box rect, in the same image-pixel coordinate system as the boxes.
- RLE follows COCO: ``{"size": [height, width], "counts": str}``.

Segmentation outputs are geometry only. They MUST NOT assert damage,
blockage, or people findings — those are assessment questions answered by
agents plus human review, never by this endpoint.
"""

from pydantic import BaseModel, Field


class SegmentBox(BaseModel):
    """Half-open bounding box in source-image pixels."""

    x1: int = Field(ge=0)
    y1: int = Field(ge=0)
    x2: int = Field(ge=0)
    y2: int = Field(ge=0)


class SegmentMask(BaseModel):
    """One decoded mask in two frontend-friendly encodings."""

    width: int = Field(gt=0)
    height: int = Field(gt=0)
    svg_path: str = ""
    rle_counts: str = ""


class SegmentDetection(BaseModel):
    """One segmented object: stable id, box, and mask."""

    object_id: str
    box: SegmentBox
    mask: SegmentMask


class SegmentImageInfo(BaseModel):
    """Echo of the segmented image's identity and dimensions."""

    width: int = Field(gt=0)
    height: int = Field(gt=0)
    mime_type: str
    evidence_id: str


class SegmentImageResponse(BaseModel):
    """Response for POST /api/disaster-response/segment-image."""

    image: SegmentImageInfo
    prompt: str
    model: str
    detections: list[SegmentDetection] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
