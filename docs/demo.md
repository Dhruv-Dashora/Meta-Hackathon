# Demo — Himalayan Sentinel (live workflow)

Run the backend and frontend first (see the root README), with
`MODEL_API_KEY` set in `backend/.env`. Use a disaster photograph you
have the rights to show; no imagery is bundled with this repository.

## Part 1 — Analyze an image

1. Open **Analyze Image** and upload the photograph (JPEG/PNG/WebP,
   max 5 MB). Optionally add up to 3 focus areas (e.g. `house, debris`).
2. Run the analysis. The progress bar advances through the pipeline:
   Muse Spark findings, then SAM 3.1 outlines for up to 3
   deterministic prompts (your focus areas first).
3. Point out: findings labeled "Visual Observation N"; outlined
   regions are visual guides only — an outline never proves damage.

## Part 2 — Incident report

1. Open **Incident Reports** and build the report from the same image.
   The cached analysis is reused (no new model calls).
2. Walk the report top to bottom:
   - **Analysis Summary** — stage statuses; open **Technical Details**
     for timings, source, and diagnostics.
   - **Provisional damage** — observed condition, assessment,
     uncertainty ("surrounding mud or debris does not establish
     structural damage"), recommended verification.
   - **Location & Unverified Information** — operator location is
     unverified; unknowns are grouped, not buried.
3. Work the **Verification** checklist; note that people-related
   urgency needs explicit observed danger, never keyword frequency.

## Part 3 — Exports

1. **Print Brief** — the complete report as a print/PDF document,
   with full technical provenance at the end.
2. **Download JSON** — the machine-readable dossier: every finding id,
   evidence id, mask geometry, and assessment basis for audit.

## Planned 

Early-warning historical comparison, monitoring, and hydromet context
exist only as schema/scaffold and are labeled as planned in the app.
Do not present them as working features.

## Guardrails

- Label all AI outputs as unverified until human review.
- Confidence is an uncalibrated signal, never a probability.
- The system never dispatches rescue or confirms damage.
