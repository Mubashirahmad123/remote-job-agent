# CHANGELOG.md

## Unreleased (2026-10-01 — Submit minimum-profile gate)

- `_fill_greenhouse_form` (`agents/auto_applier.py`) now emits
  `profile_fields_verified` and downgrades a vacuous `verified` (zero typed
  fields, selector drift) to `missing_required`, which fails closed.
- `_run_greenhouse_submit` (`api/apply.py`) requires name (`first_name` or
  `full_name`) + `email` in `profile_fields_verified` before any click.
- Tests: no-profile / no-email / no-name / missing_required → no click;
  `full_name`+email passes; filler vacuous case → `missing_required`.
  `jobDesk.js` sort now honors the `scraped_at` fallback from its comment.
  `PRODUCTION.md` free-form CV note folded into a `PM.md` backlog pointer.
- `SUBMIT_ENABLED` stays `False` — live submit still locked.
- Full suite: 286 passed, 1 skipped (+7 profile-gate tests).

## Unreleased (2026-10-01 — Submit field-readback hard gate)

- `_run_greenhouse_submit` (`api/apply.py`) now treats the filler's
  `field_verification` as a hard no-click gate: only `"verified"` (first-pass
  readback match) or `"repaired"` (re-typed, final readback match) proceed.
  `"mismatch"` (drift survived 3 repair passes), `"unavailable"` (no readback
  possible), or any other state fails closed before any submit click — even
  when attachments verify cleanly.
- Tests: `mismatch`/`unavailable` → no click; `verified`/`repaired` → proceed
  past the gate; existing attachment-gate tests now pass an explicit passing
  field state so each test still targets its own gate.
- `SUBMIT_ENABLED` stays `False` — live submit still locked.
- Full suite: 279 passed, 1 skipped (+4 field-gate tests).

## Unreleased (2026-10-01 — Sidebar Hot badge live)

- The sidebar `topMatchCountBadge` was hardcoded to `11 Hot` in `index.html`
  and never updated by any script, while Command Deck showed the live
  `TOP MATCHES` tab count (e.g. 24). `dashboard.js:_applyMetrics` now sets
  the badge from the same live `/api/stats` tabs on every render.

## Unreleased (2026-10-01 — Curated Jobs newest-first)

- `frontend/js/components/jobDesk.js:getFilteredJobs` sorts newest-first by
  `posted_date_iso` (desc, undated rows last). Sheet order is oldest-first
  (appends land at the bottom), so without this new jobs sat at the end of
  the Curated Jobs tab. Apply queue still ranks by score (unchanged).

## Unreleased (2026-10-01 — Review-queue screenshot 404 spam)

- `frontend/js/components/autoApply.js` fabricated a screenshot URL from the
  fingerprint even when the backend returned `screenshot_url: null`
  (package-only), causing GET 404 pairs (`<img>` + authenticated-fetch
  fallback) on every render for package-only results. The backend response is
  now the source of truth — no URL is built when it says `null`, so the
  honest empty state renders with zero requests.

## Unreleased (2026-10-01 — Submit blockers: intent immutability + dedicated token)

- Intent/material immutability (`api/apply.py:create_greenhouse_intent`):
  intent now REUSES the reviewed artifact's resume + cover letter verbatim —
  no regeneration, no package rebuild, no artifact rewrite. Reviewed ==
  submitted by construction; missing/stale materials fail closed (502).
- Duplicate intent while one is live is rejected (409) BEFORE any expensive
  work via a read-only pre-check (`live_intent_retry_after` in
  `api/apply_intents.py`), so a rejected request can no longer mutate the
  first token's artifact. Race path still 409s via `create_intent`.
- Apply auth is now dedicated: `require_apply_token` accepts ONLY
  `APPLY_API_TOKEN` (the `API_TOKEN` fallback is removed); unset token fails
  closed 401. New test proves `API_TOKEN`-only gets 401 on both routes.
- Frontend: Auto-Apply review-result posting link now goes through
  `JobAgent.safeHttpUrl` (was raw `applyUrl`), closing the last unescaped
  `javascript:`/`data:` link surface.
- Tests: intent suite rewritten to the reuse invariant (no-regeneration,
  stale-materials 502, duplicate-leaves-artifact-untouched) + dedicated-token
  401 test. `SUBMIT_ENABLED` stays `False` — live submit still locked.
- Full suite re-verified: 275 passed, 1 skipped (was 273; +2 net new tests).

- Curator match logging: fixed doubled sign (`(28++0)` → `(28+0)`) in
  `agents/curator.py` — a literal `+` plus a `:+d` value printed both signs.
- Arbeitnow company backfill: the API field is `company_name`, not `company`
  (`agents/scrapper.py:parse_json_arbeitnow`); older runs saved blank company.
  A minority of postings link to the company homepage (upstream `url` field);
  a slug-built `/jobs/<slug>` URL was verified to 404, so links stay as-is.
- Scrape-status polling: single-loop guard (`pollActive`) in
  `frontend/js/app.js` — a refresh-resume plus click/409 path could stack
  concurrent `GET /api/scrape/{id}` loops; interval stays 5s.
- `tools/sheet_writer.py:append_rows` validated the sample row before
  `prepare_job_for_sheet` auto-filled `scraped_at`/`status`/`job_fingerprint`,
  warning spuriously every run; validation now runs on the prepared copy.
- Scraper failures diagnosed as structural, not a regression (bot walls,
  generic-selector mismatch, duplicate board URLs, missing Adzuna keys, dead
  DNS); no earlier targeted fix found in history. Details: `PRODUCTION.md` §7.
- Full suite re-verified: 273 passed, 1 skipped.

- Kill switch enforced: `POST /api/apply/{fp}/intent` + `/submit` fail closed
  with 403 while `api/safety.py SUBMIT_ENABLED=False` (router + service level).
- Review fill carries the final tailored resume + cover letter (same files a
  submit would send); response reports `materials_note: final` or an honest
  `fallback-empty` reason. Submit refill refuses to click unless the resume +
  cover letter verify as attached (`files.length` readback).
- Legacy CLI blind submit permanently removed (`AUTO_APPLY_CONFIRM` ignored
  everywhere); score parsing coerces `"85.0"`/`""`/`None`/`"87%"` instead of
  crashing; consumed intents are replaceable and `failed_refunded` claims can
  retry; package HTML escaped with `rel="noopener noreferrer"`.
- Cockpit: daily cap enforced (persisted per-day count), in-browser screenshot
  preview (`GET /api/apply/{fp}/screenshot`), attachment-copy mismatch fixed,
  sidebar/dashboard cap numbers live, blob-URL leak fixed.
- Frontend XSS sweep: `JobAgent.escapeHtml` + `safeHttpUrl` (`js/escape.js`);
  drawer/toast/grid-table/tracker/cards/dashboard sources escaped; only
  `http(s)` posting URLs assigned. Full suite: 273 passed, 1 skipped.

## Unreleased (2026-09-29 — Auto-Apply cockpit fill-and-review)

- Connected the fill-only API to the existing Greenhouse/Lever form fillers.
  Each supported job opens a visible review window, fills supported fields,
  captures a pre-submit screenshot, and stays open for manual review/submission;
  the backend never clicks submit. Unsupported ATSs remain package-only.
- Auto-Apply Cockpit processes up to three eligible jobs sequentially, reports
  per-job fill/package outcomes without aborting later jobs, and shows actual
  latest-run results instead of a static screenshot mockup.
- Replaced placeholder Playwright telemetry with actual review-queue activity.
  Auto-Submit remains disabled and there are still no HTTP submit routes.
- Terminal messages render as text nodes so untrusted job titles and API errors
  cannot inject markup into the cockpit log.
- 2b submit remains gated: F1/F2 and independent test primitives are in place; Lever
  confirmation-copy observation is blocked on a legitimate isolated trial
  posting. Latest full suite: 222 passed, 1 expected xfail.

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
- Scrape robustness: per-board time budget (`SCRAPER_TIMEOUT`, default 300s)
  so a hung board is skipped instead of stalling the run; board-start
  "running" state for the monitor; poll loop resets to idle on
  404/unreachable instead of sticking on "Scraping…" (`tests/test_scraper_timeout.py`).
- JobSpy isolation: opt-in only (`ENABLE_JOBSPY`, default `false` →
  `skipped-disabled`); when enabled it runs in a `spawn` child process
  (`_run_jobspy_isolated`) so a native `tls-client` segfault fails just that
  board and the run still reaches summary/curate; scope via `JOBSPY_SITES` /
  `JOBSPY_TERMS` (defaults: `linkedin,indeed` × 1 term).

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
