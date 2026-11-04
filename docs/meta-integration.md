# Meta Integration Notes

## Rule

Do not invent Meta API endpoints or capabilities. Verify official Meta
documentation for Muse Spark and SAM 3.1 before writing any integration code.

## Muse Spark (implemented — single-image analysis)

Official documentation:

- Quickstart: https://dev.meta.ai/docs/quickstart
- Image understanding: https://dev.meta.ai/docs/image-understanding

Contract in use:

- Base URL: `https://api.meta.ai/v1`
- Endpoint: `POST /responses`
- Model: `muse-spark-1.3`
- Auth: `Authorization: Bearer <MODEL_API_KEY>` (backend env only)
- Image input: `input_image` content block with a Base64 data URL,
  plus an `input_text` instruction block.

Configuration (see `backend/.env.example`, never commit `backend/.env`):

- `MODEL_API_KEY` — Bearer token. Never log it, never return it in
  errors or API responses.
- `MUSE_SPARK_BASE_URL` (default `https://api.meta.ai/v1`)
- `MUSE_SPARK_MODEL` (default `muse-spark-1.3`)
- `MUSE_SPARK_TIMEOUT_S` (default `60.0`; single attempt, no automatic
  retries — a retry would double API cost on every slow call)
- `MAX_IMAGE_BYTES` (default `5242880`; JPEG/PNG/WebP by magic bytes)

Wiring: `POST /api/disaster-response/analyze-image` validates one
multipart image (`media_service`), calls Muse Spark from the backend
only (`muse_spark_client`), and maps structured JSON through
`VisionAgent` into the existing `Finding` schema. Automated tests mock
the client transport and never make live API calls.

Confidence is NOT calibrated: `Finding.confidence` stays
`{"scale": "0-1", "calibrated": false}` and is an uncalibrated triage
signal, not a probability. Every finding carries uncertainty notes and
`review_status: pending` per `docs/evidence-model.md`.

## SAM 3.1 (implemented — single-image segmentation)

Official documentation:

- Overview: https://dev.meta.ai/docs/sam/overview
- Segmenting with prompts: https://dev.meta.ai/docs/sam/segmenting
- Reading segmentation output: https://dev.meta.ai/docs/sam/reading-segmentation
- Client libraries: https://dev.meta.ai/docs/sam/client-libraries
- Media segmentation: https://dev.meta.ai/docs/media-segmentation
- Responses API protocol: https://dev.meta.ai/docs/protocols/responses
- Cookbook: https://dev.meta.ai/docs/cookbook/sam-api-basics
- Error handling: https://dev.meta.ai/docs/error-handling

Contract in use:

- Base URL: `https://api.meta.ai/v1`
- Endpoint: `POST /responses` (non-streaming)
- Model: `sam-3.1`
- Auth: `Authorization: Bearer <MODEL_API_KEY>` (backend env only;
  same key as Muse Spark, no separate key)
- Request: one `{"type": "message", "role": "user"}` input item with a
  short noun-phrase `input_text` prompt plus one `input_image` data URL,
  and `metadata: {"mask_encoding": "one_bit"}`.
- Output: special-token segmentation grammar in the `output_text` lane
  (`<Nf>id<|box;...|><|mask;...|>`), parsed ONLY with the official
  `meta_sam_parser` package — never by hand.
- Empty `output_text` with `status: completed` is a valid zero-match
  result, not an error.

Key wire facts (see reading-segmentation):

- One line per image (`<0f>`); boxes in source pixels, wire `x2`/`y2`
  INCLUSIVE (the parser normalizes to half-open `right`/`bottom`).
- Mask `data=H,W,…` is height-first and smaller than the source frame;
  encoding marker `~` (lossless) or `!` (one_bit); payload is BASE85,
  not base64. Object ids are stable but not dense/0-based.
- One concept per request; commands, questions, and comma lists do not
  work. Concrete nouns match best (`road`, `vehicle`, `river water`).

Configuration (see `backend/.env.example`, never commit `backend/.env`):

- `MODEL_API_KEY` — shared Bearer [REDACTED] Never log it, never return it.
- `SAM31_BASE_URL` (default `https://api.meta.ai/v1`)
- `SAM31_MODEL` (default `sam-3.1`)
- `SAM31_TIMEOUT_S` (default `60.0`)

Wiring: `POST /api/disaster-response/segment-image` validates one
multipart image (`media_service`, JPEG/PNG/WebP by magic bytes) plus a
short `prompt` form field, reads displayed dimensions with Pillow
(post-EXIF-orientation, matching SAM coordinates), calls SAM 3.1 from
the backend only (`sam31_client`), and returns boxes (half-open source
pixels) plus masks (SVG path + COCO RLE) in
`SegmentImageResponse`. Segmentation is geometry only: it MUST NOT
assert damage, blockage, or people findings. Automated tests mock the
client transport and exercise the real offline parser against a
documented grammar sample; they never make live API calls.

Streaming note: streaming is the recommended path for long video clips
(progressive frames, no server-side time limit) but is NOT required —
non-streaming "runs the same segmentation and returns the complete
result in one response, in the same format". Single images use
non-streaming; revisit streaming only if video support is added.

Operational logging (`sam31_client`, INFO): request model/URL/truncated
prompt, HTTP status plus elapsed time, envelope shape (field names, status,
output-item count, lane found, content-part types and text lengths),
output-text length, and detection count. A blank documented lane is logged
as a genuine zero-match; anything else unusable is loud (502). Parser
diagnostics are sanitized (code/message/line only) in both logs and API
warnings. Keys, auth headers, images, request bodies, and raw segmentation
payloads are never logged.
