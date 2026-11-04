# API Contract

Base URL: `http://localhost:8000`. All routes prefixed `/api`.

The disaster-response, session, verification, and reports routes below
are implemented. Routes marked **scaffold** return placeholder payloads
and make no AI calls.

## Health

- `GET /api/health` -> `{ "status": "ok", "service": "himalayan-sentinel" }`

## Session

- `POST /api/session` -> `{ "session_id": "..." }`. Opaque browser-session
  id (also cached in session storage); sent as the `x-session-id` header to
  bind cached analyses to one session.

## Early Warning (scaffold — planned, not implemented)

- `POST /api/early-warning/analyze` — historical vs recent comparison request.
- Returns a validated `EarlyWarningResponse` skeleton. No comparison,
  monitoring, or hydromet analysis is performed.

## Disaster Response

- `POST /api/disaster-response/assess` — legacy damage assessment
  request (**scaffold placeholder**). Returns a validated
  `DisasterResponse` skeleton; use `analyze-image` /
  `assess-incident` for the live workflow.
- `POST /api/disaster-response/analyze-image` — multipart `image`
  (JPEG/PNG/WebP, size-capped); Muse Spark findings. Model failures
  return 502.
- `POST /api/disaster-response/segment-image` — multipart `image` +
  `prompt` form field (one short noun phrase, max 120 chars, single
  line). Returns `SegmentImageResponse`: image dimensions,
  prompt/model echo, detections (`object_id`, half-open source-pixel
  box, mask as SVG path + COCO RLE with raster size), and warnings.
  Zero matches return 200 with `detections: []`. Upload problems
  return 400/413; prompt problems return 400; SAM failures return 502.
  Geometry only — no damage/blockage/people assertions.
- `POST /api/disaster-response/analyze-and-segment` — multipart `image`
  plus optional `targets` (comma-separated, max 3, each max 40 chars).
  Sequential Muse Spark findings, then deterministic SAM prompts:
  operator targets first (`user_requested`, synonym-deduped), then
  positively observed objects ranked by operational tier (people with
  danger, people, hazard/affected infrastructure, neutral
  infrastructure) with confidence second (`automatic`), plus one
  optional justified exploratory access check (`exploratory`); max 3
  executed; no fallback and no reserved slot. Returns
  `UnifiedAnalysisResponse`: shared `evidence_id`, `findings`,
  `prompt_plan` audit trail with provenance, per-prompt `segmentations`
  (`ok` / `zero_matches` / `failed` / `skipped`, linkage is
  `prompt_trigger_only`), `workflow_status` (`completed` / `partial` /
  `vision_only`), `user_targets` echo, `warnings`, and — when a valid
  `x-session-id` header is present — an `analysis_ref` for report
  reuse. Findings are preserved when SAM fails or matches nothing.
  Total workflow time budget `unified_workflow_budget_s` (default 90s);
  budget-exhausted prompts are `skipped`. Vision failure with no
  findings returns 502; upload/target/session problems return 400/413
  before any model call.
- `POST /api/disaster-response/assess-incident` — multipart `image` +
  optional `location_label`, `latitude`/`longitude`, `geojson` file.
  Runs vision → impact → reporting and returns an `IncidentDossier`:
  situation summary (headline + observed + unknowns), findings,
  finding groups, information gaps, segmentation summary plus embedded
  full `segmentations` geometry (copied from vision output — no
  recompute), observed hazards, conditional unverified exposure
  concerns (feature-tagged), operator-provided (unverified) geo
  context or an explicit unavailable statement, detailed verification
  actions (what/why/unknown/suggested method/priority rationale),
  evidence ledger, agent trail, and warnings. `incident_status` is
  `completed` only when all agents succeed, else `partial` (impact
  failed; concerns unavailable, never synthesized). Reporting failure
  returns 502 with no dossier claimed. Bad geo input returns 400/413
  before any model call. The dossier also carries provisional
  `damage_assessments` (per feature family: `no_visible_damage` /
  `possible_damage` / `apparent_major_damage` / `cannot_assess`,
  always provisional, never confirmed safety; each read carries a
  professional narrative — `observed_condition`, `rationale`,
  `uncertainty_note`, `recommended_verification` — plus a
  machine-readable `condition_class` and structured finding/evidence
  basis ids) and `rescue_priorities`
  (`high` only on explicit same-clause danger indication, else
  `medium` / `low` / `undetermined`; always human-review-required).
- `POST /api/disaster-response/assess-incident-from-analysis` — JSON
  `{analysis_ref, location_label?, latitude?, longitude?, geojson?}`
  plus the owning `x-session-id` header. Impact + reporting over the
  server-cached analysis with zero model calls; returns an
  `IncidentDossier` with `vision_source: cached_reuse`. Unknown,
  foreign-session, or expired references return 404 with a rebuild
  message; the operator must explicitly rebuild from the image. No
  client-submitted findings are ever accepted as evidence.

## Verification

- `GET /api/verification/queue` — pending human reviews.
- `POST /api/verification/{finding_id}` — submit human decision.

## Reports

- `GET /api/reports/{incident_id}` — structured incident report.

All payloads use `backend/app/schemas/*`. Every finding includes
`evidence_refs`, `confidence`, `timestamps`, `review_status`.
