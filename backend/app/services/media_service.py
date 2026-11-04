"""Media ingest.

MVP VIDEO POLICY: keep processing lightweight — extract SELECTED FRAMES
(e.g. uniform sampling or operator-chosen timestamps) rather than decoding
or analyzing entire videos. Full-video processing is out of MVP scope.

Image uploads: validated by magic bytes (never trust filename or declared
MIME type alone), size-capped, and converted to Base64 data URLs for the
Muse Spark Responses API.
"""

import base64
from dataclasses import dataclass

from fastapi import UploadFile

from app.core.errors import SentinelError

JPEG_MIME = "image/jpeg"
PNG_MIME = "image/png"
WEBP_MIME = "image/webp"

ALLOWED_IMAGE_MIMES = (JPEG_MIME, PNG_MIME, WEBP_MIME)

_PNG_MAGIC = bytes.fromhex("89504e470d0a1a0a")
_READ_CHUNK_SIZE = 64 * 1024


class ImageValidationError(SentinelError):
    """Unsupported, malformed, or oversized image upload."""

    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(code, message)
        self.status_code = status_code


def extract_selected_frames(video_path: str, timestamps: list[float]) -> list[str]:
    raise NotImplementedError("Scaffold placeholder — not implemented yet.")


def sniff_image_mime(data: bytes) -> str | None:
    """Detect JPEG/PNG/WebP from magic bytes. Returns MIME type or None."""
    if len(data) >= 3 and data[:3] == b"\xff\xd8\xff":
        return JPEG_MIME
    if len(data) >= 8 and data[:8] == _PNG_MAGIC:
        return PNG_MIME
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return WEBP_MIME
    return None


@dataclass(frozen=True)
class ValidatedImage:
    data: bytes
    mime_type: str


def validate_image_bytes(
    data: bytes, *, max_bytes: int, filename: str | None = None
) -> ValidatedImage:
    """Validate raw image bytes by size and actual content."""
    if not data:
        raise ImageValidationError("empty_image", "Uploaded file is empty.")
    if len(data) > max_bytes:
        raise ImageValidationError(
            "image_too_large",
            f"Image exceeds the {max_bytes}-byte limit.",
            status_code=413,
        )
    mime = sniff_image_mime(data)
    if mime is None:
        raise ImageValidationError(
            "unsupported_image_type",
            "Unsupported image format. Allowed: JPEG, PNG, WebP.",
        )
    return ValidatedImage(data=data, mime_type=mime)


def image_to_data_url(image: ValidatedImage) -> str:
    """Convert validated image bytes to a Base64 data URL."""
    encoded = base64.b64encode(image.data).decode("ascii")
    return f"data:{image.mime_type};base64,{encoded}"


async def read_upload_bounded(upload: UploadFile, *, max_bytes: int) -> bytes:
    """Read an upload in chunks, refusing files larger than max_bytes."""
    data = bytearray()
    while True:
        chunk = await upload.read(_READ_CHUNK_SIZE)
        if not chunk:
            break
        data += chunk
        if len(data) > max_bytes:
            raise ImageValidationError(
                "image_too_large",
                f"Image exceeds the {max_bytes}-byte limit.",
                status_code=413,
            )
    return bytes(data)
