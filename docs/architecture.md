# Architecture — Himalayan Sentinel

## Principle

Single FastAPI server + in-process logical agents. No independent agent servers,
no separate model deployments. Controlled Python workflow with validated
structured inputs/outputs.

## Backend layout

```text
backend/app/
├── main.py               # FastAPI app, router wiring
├── core/                 # config (env only), logging, errors
├── api/                  # early_warning, disaster_response, verification, reports, health
├── schemas/              # Pydantic contracts (common + per-mode + reports)
├── agents/               # base + monitoring, vision, impact, reporting 
├── orchestrator/         # orchestrator + workflows/* + validators + failures
├── services/             # muse_spark, sam31, media, geo, hydromet, evidence_store
└── db/                   # SQLAlchemy models + session (DB file in ../storage/)
backend/storage/          # SQLite + runtime artifacts (gitignored)
backend/tests/            # pytest suite (mocked model clients, no live calls)
```

## Agents (logical, in-process)

1. `monitoring_agent` — scaffold (early-warning work, not implemented).
2. `vision_agent` — implemented: Muse Spark interpretation mapped to
   `Finding`s; SAM 3.1 segmentation via the unified service.
3. `impact_agent` — implemented: deterministic rules over findings +
   segmentation + optional geo. Separates observed hazards (restated,
   never new claims) from conditional unverified exposure concerns,
   each with evidence refs and a linked verification action.
4. `reporting_agent` — implemented: deterministic dossier assembly
   (no new factual claims, explicit gaps, degraded path on impact
   failure).

Agents expose `run(input) -> AgentResult` with evidence refs (plain
classes wired in `backend/app/services/unified_service.py` and the
disaster-response routes). `backend/app/agents/base.py` holds a legacy
protocol stub and is not subclassed.

## Orchestrator

- `orchestrator.py` — runs `disaster_response` vision -> impact ->
  reporting sequentially with per-step timing, `FailureRecord` capture,
  and an audit trail embedded in the dossier. Vision failure aborts
  (502); impact failure degrades (partial dossier); reporting failure
  returns an explicit error with no dossier claimed.
- `workflows/early_warning.py` — scaffold stub (raises
  `NotImplementedError`); early-warning analysis is planned.
- `workflows/disaster_response.py` — scaffold stub; the live workflow
  runs from the disaster-response routes via
  `services/unified_service.py`.
- `validators.py` — structural claim checks (conditional language,
  evidence refs, unverified status, action linkage, ledger integrity).

## Services

- `muse_spark_client`, `sam31_client` — live Meta integrations
  (backend-only key, httpx, `/responses` endpoints).
- `media_service` — upload validation (magic-byte type check) and
  data-URL encoding. Video/frame extraction is not implemented currently.
- `geo_service` — operator GeoJSON parsing/bounding helpers
  (no GeoPandas).
- `hydromet_service`, `evidence_store` — scaffold stubs
  (`NotImplementedError`); hydromet context is planned.

## Frontend

React + Vite + TS + Tailwind + Leaflet. Live pages: Analyze Image,
Image Intel, Incident Reports, Verification. Early-warning and
GeoIntel pages are honest static "planned, not yet live" placeholders.
API client only; no keys in frontend.

## Data

`data/demo/gyirong-rasuwa-2026-08/manifest.json` is an empty
placeholder (`{}`): no demo imagery or datasets are bundled, and none
should be committed without confirmed redistribution rights. Judges
bring their own disaster photograph (see the root README demo flow).
