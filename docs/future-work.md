# Future Work — Deferred Improvements

## Prompt planner 

- English keyword matching only; no synonyms beyond the fixed table
  (e.g. "thoroughfare" never triggers "road").
- Fixed 7-concept vocabulary (road, river, building, vehicle, people,
  debris, bridge). Hazard auto-prompting covers debris/rubble via the
  ``debris`` prompt and floodwater via ``river``; bare event nouns
  (landslide alone), mud/sediment, scattered rocks, and abstract zones
  have no automatic prompt. Zero SAM matches stay possible per prompt
  and never imply absence.
- Heuristic negation (3-word window, clause-bounded); complex
  phrasing can mislead it in either direction.
- No embedding/similarity fallback; no-match means no prompts.
- Hard cap of 3 SAM prompts per request.

## Orchestration follow-ups

- Persist dossiers/findings/reviews to SQLite (models exist, unused).
- Cache vision results by image hash to avoid duplicate Meta API calls.
- Implement the monitoring agent + early-warning workflow.
- GeoJSON spatial analysis (currently validation + counts only).
- Reporting persistence + verification-decision write path.
