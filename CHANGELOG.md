# CHANGELOG.md

## Unreleased (2026-09-24 — Phase 2 actions + Studio fixes)

- Action API: `POST /api/scrape` + `GET /api/scrape[/{run_id}]` (single-active-run
  registry `api/runs.py`); `POST /api/resume/{fp}` + `POST /api/cover-letter/{fp}`
  with downloads (`api/materials.py`, fp-mapped files only); `PUT /api/cv/profile`
  (Studio edits into on-disk cache, no LLM per request).
- New tests: `test_api_cv.py`, `test_api_materials.py`, `test_api_freshness.py`,
  `test_api_jobs_contract.py` (+ `test_api_phase2.py`) — suite now **136 passed**.
- Resume Studio: live tailor flow (fingerprint select, progress steps, cover-letter
  preview), profile Edit/Save with local override + API sync, variant select/add;
  preview card starts hidden and the demo fallback renders dynamically from the
  selected job + profile (no hardcoded fixture); skills textarea fixed
  (full-width block layout, min-height 110px, auto-grow).
- Docs: BACKEND (×8 routers, new endpoints, PUT allow-method, test counts),
  FRONTEND (api.js fns, Studio live state), PM (Phase 2 status + next),
  TESTER (136/8 files), README (structure + endpoint table), AGENTS,
  ARCHITECTURE.

## 2026-09-23 — Phase 1e: docs + live Sheets

- New docs: `PRODUCTION.md`, `ARCHITECTURE.md`, `BACKEND.md`, `FRONTEND.md`,
  `PM.md`, `REVIEWER.md`, `TESTER.md`, `CONTRIBUTING.md`; README API section.
- `keys.json` wired; `/api/health` → `sheets_configured: true`, live Sheet
  (`LIVE Remote Jobs Tracker`: 12 ALL JOBS, 12 GOOD MATCHES).
- Fixed Windows cp1252 emoji crash in `tools/sheet_writer.py` (UTF-8 stdout
  reconfigure) — it was masking the Sheet connection as a failure.

## 2026-09-23 — Phase 1d: data honesty

- `ALL JOBS` snapshot fallback (`scraped_jobs.json` → `fresh_scrape.json`, 96 rows)
  with pipeline-MD5 fingerprints; `data_source` (`sheets|snapshot|empty`) on
  `/api/health`; UI source badges + score-gate auto-drop for unscored snapshots.

## 2026-09-23 — Phase 1c: frontend wiring

- New `frontend/js/api.js` (per-router client, token/base-URL support, coded errors).
- `store.js`: live loaders + normalization + per-section mock fallback.
- `jobDesk`/`dashboard`/`tracker`/`jobDrawer` live; `app.js` async boot
  (mock first paint → live re-render); Sync Sheets + global search wired.

## 2026-09-23 — Phase 1b: API split + same-origin UI

- `api/app.py` monolith → `deps.py`, `mappers.py`, `routers/{health,jobs,stats,tracker,system}.py`.
- `frontend/` mounted via `StaticFiles` (`GET /` → dashboard, zero CORS).
- `.env.example` + `requirements.txt`: `API_*` vars, fastapi/uvicorn/pydantic/httpx.

## 2026-09-23 — Phase 1: read API

- `api/` (app/cache/schemas) + `tests/test_api_phase1.py` (18 tests, faked Sheets):
  health, jobs list/search/get-one, stats, tracker list/patch, refresh.
- TTL cache (90s), curated enrichment join, Bearer auth + localhost-first bind rule.

## Pre-existing — Phase 0: pipeline

- 45+ board scrapers, curator (dedup/CV match/rank), Sheets 5-tab dashboard,
  LLM fallback chain (Gemini→Groq→Mistral→GLM→Ollama), auto-apply pipeline,
  tracker CLI, scheduler, Docker + compose.
