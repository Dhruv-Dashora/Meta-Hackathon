# Evidence Model — Traceability, Confidence, Review

## Traceability

Every AI finding MUST link to one or more evidence items:

- `evidence_refs[]`: `{ evidence_id, modality, uri_or_hash, captured_at }`
- Modalities: `image | video_frame | geojson | hydromet | report`
- Media stored outside git; DB stores URI/hash + timestamps, not binaries.

## Confidence — meaning and limitations

`confidence` is a structured, uncalibrated signal:

```json
{ "value": 0.72, "scale": "0-1", "calibrated": false }
```

Rules:

1. **NOT a probability.** Do not read 0.72 as "72% likely true".
   No calibration, no base rates, no controlled evaluation yet.
2. **Relative ranking only.** Useful for triage/verification priority,
   not for decisions or public alerts.
3. **Source-dependent.** Vision-language scores, detector scores, and
   heuristic flags are not comparable across agents without calibration.
4. **Uncertainty is explicit.** Agents SHOULD also emit `uncertainty`
   notes (occlusion, low resolution, single-view, missing context).
5. **Single-image limits.** Never claim reliable disaster prediction from
   one image; historical + hydromet context and human review required.
6. Future work: calibration study, reliability diagrams, per-agent thresholds.
   Until then, UI MUST label confidence as "uncalibrated model signal".

## Timestamps

- `observed_at` (media capture), `analyzed_at` (agent run), `updated_at`.
- ISO 8601 UTC. Missing capture time MUST be explicit `null`, never invented.

## Human review

`review_status`: `pending | confirmed | rejected | needs_more_evidence`.
Default `pending`. People-detection findings REQUIRE human verification
before any prioritization display.
