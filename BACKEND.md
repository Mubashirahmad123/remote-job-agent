# BACKEND.md — FastAPI Reference (`api/`)

Reads over the Sheets pipeline **plus** Phase 2 action endpoints (scrape runs,
tailored materials, CV profile edits, and ATS fill-and-review for supported boards).
The Greenhouse `POST /api/apply/{fp}/intent` + `/submit` routes exist but fail
closed with 403 while `api/safety.py SUBMIT_ENABLED=False`; Lever has no submit
path by design. See the gated 2b spec and current execution status in `PM.md`.

Run: `venv\Scripts\python -m uvicorn api.app:app --host 127.0.0.1 --port 8000`
Docs: `http://127.0.0.1:8000/docs` · Tests: `venv\Scripts\python.exe -m pytest tests/ -q` (last verified 2026-10-01: 291 passed, 1 skipped)

---

## 1. Layout (one file per group — keep it that way)

```
api/
  app.py            thin factory: CORS → include_router ×9 → static UI mount (LAST)
  deps.py           cors_origins() + require_token() (Bearer <API_TOKEN> when set)
  cache.py          sheet reads, TTL cache, curated enrichment, snapshot fallback,
                    CV profile cache + variant discovery
  schemas.py        JobOut, TrackerEntry, TrackerUpdate, HealthOut (+ VALID_TRACKER_STATUSES),
                    CvProfileOut, CvProfileUpdate, CvVariant
  mappers.py        to_job_out() / to_tracker_entry()
  materials.py      resume/cover-letter generation registry (fp-mapped files only)
  runs.py           background scrape-run registry (single active run)
  routers/
    health.py       GET /api/health
    jobs.py         GET /api/jobs, GET /api/jobs/{job_fingerprint}
    stats.py        GET /api/stats
    skills.py       GET /api/skills (tech_stack demand aggregate)
    tracker.py      GET /api/tracker, POST /api/tracker, PATCH /api/tracker/{job_fingerprint}
    system.py       POST /api/jobs/refresh
    runs.py         POST /api/scrape, GET /api/scrape[/{run_id}] (registry: api/runs.py)
    materials.py    POST /api/resume/{fp} + download, POST /api/cover-letter/{fp} + download
                    (registry: api/materials.py — fp-mapped files only, no path params)
    cv.py           GET /api/cv/profile (cached parse, 501 when uncached),
                    PUT /api/cv/profile (Studio edits → on-disk cache, 501 when uncached),
                    GET /api/cv/variants (CVLibrary discovery w/ cvs/ fallback; missing dir → [])
    apply.py        POST /api/apply/{fp} creates a local review package only
            (service: api/apply.py, gate: api/safety.py; no ATS browser or submit)
```

To debug: comment out one `include_router` line in `app.py` to isolate a group.

## 2. Endpoints

### `GET /api/health` → `HealthOut`
`{status, sheets_configured, curated_jobs_loaded, data_source}`.
Presence-only — asserts in tests that no secret substrings leak.

### `GET /api/jobs` → `JobOut[]`
| Param | Default | Notes |
|---|---|---|
| `tab` | `ALL JOBS` | `ALL JOBS` / `TOP MATCHES` / `GOOD MATCHES`, else 400 |
| `q` | — | substring over title + company + summary + tech_stack |
| `source` | — | exact board match, case-insensitive; the value is canonicalized, so `?source=RemoteOKAPI` and `?source=RemoteOK` both return the merged set |
| `limit` / `offset` | `50` / `0` | `limit` clamped 1–500 |

### `GET /api/jobs/{fp}` → `JobOut` (404 when unknown; searches ALL JOBS first)

### `GET /api/stats`
`{total_jobs, tabs{…}, by_source{…}, stats_rows[], curated_jobs}` — counts from
job tabs + raw STATS-tab rows. Never crashes (returns zeros on error).

`by_source` keys are canonical (`tools/sources.py`): board keys that alias the
same provider — `RemoteOKAPI`→`RemoteOK`, `Remojobs-*`→`Remotive`,
`FounditIN`→`Naukri` — are merged. Normalization runs on **read** (in
`cache.get_tab_rows`) as well as on write, because rows already in the Sheet
were written under the old keys; a write-only fix would stay split until the
sheet was rebuilt. Unknown board names pass through untouched, so a genuinely
new board is never absorbed into an existing one.

### `GET /api/skills?tab=&limit=` → `SkillsOut`
`{tab, total_jobs, jobs_with_stack, unique_skills, skills[{name, count, pct}]}`
— aggregates the free-text `tech_stack` column across one job tab.

| Param | Default | Notes |
|---|---|---|
| `tab` | `ALL JOBS` | must be a job tab (`ALL JOBS`/`TOP MATCHES`/`GOOD MATCHES`); `APPLIED`/`STATS` → 400 |
| `limit` | `12` | clamped 1–100; caps the returned list only, `unique_skills` still reports the full total |

Aggregation rules (`cache.extract_skills` / `cache.get_skills_snapshot`):
- Splits on `, ; |` newline and bullets — **not** on `/`, so `CI/CD` and
  `TCP/IP` survive intact.
- Canonicalizes aliases before counting (`js`/`JS`/`javascript` → `JavaScript`,
  `node`/`nodejs`/`Node.js` → `Node.js`, `k8s` → `Kubernetes`, `postgres` →
  `PostgreSQL`). Without this the cloud showed the same skill three times,
  because scraper regex joins, Gemini enrichment, and manual rows all write
  the column differently.
- Drops noise: stopwords (`n/a`, `various`, `remote`), tokens with no letters
  (`5+`), >3-word prose, >32-char tokens.
- Drops ROLE nouns (`developer`, `engineer`, `software`, `web`, `backend`,
  `front-end`, `full-stack`). These are not stray text: `TECH_FILTER` emits
  them into `tech_stack` on nearly every row because the same regex also gates
  "is this a dev job". Left in, they outrank every real technology. Role is
  derived separately (`store.js _deriveRole`).
- Folds hyphen/underscore to space, so `Back-end`/`back end`/`BACKEND` are one
  key rather than three pills.
- Counts each skill **once per job**, so a cell listing `Python, python`
  contributes 1.
- `pct` = share of `jobs_with_stack`, not `total_jobs` — rows with an empty
  stack would otherwise deflate every percentage.
- Sort is count desc, then name asc, so identical reads return identical order.
- Never crashes: a Sheets failure returns the zeroed shape, same contract as
  `/api/stats`.

### `GET /api/tracker?status=` → `TrackerEntry[]` (optional exact status filter)
Supports both APPLIED header shapes: the compact tracker CLI header and the
full auto-apply/sheet-writer fork (`job_fingerprint`, `applied_at`, `scraped_at`,
job context). Fill-only statuses are preserved for the frontend Review column.

### `POST /api/tracker` ← `{apply_url, job_title?, company?, notes?, ...}`
Adds a manual application row to APPLIED via `tools.application_tracker.mark_applied`,
refreshes the tracker cache, and returns the created `TrackerEntry`.

### `PATCH /api/tracker/{fp}` ← `{status, notes}`
Status must be in `applied|interviewing|offer|rejected|withdrawn|ghosted` (400 otherwise).
Resolves fingerprint **or** raw `apply_url` → `tools.application_tracker.update_status`
→ refreshes APPLIED cache → returns the fresh row. 404 unknown, 502 sheet-write failure.

### `POST /api/jobs/refresh` ← `{tab?}`
Clears cache (+ enrichment map), re-warms, returns `{status, cleared[], warmed{tab:count}}`.
400 on unknown tab.

### `POST /api/scrape` → `202 {run_id, status}` (409 while a run is active)
Starts a background scrape run via `api/runs.py` (single active run; no
multi-scrape overlap). Writes go through curator → Sheets; callers poll
`GET /api/scrape/{run_id}` (`{status, phase, scraped, curated, error}`) or
`GET /api/scrape` (run list), then `POST /api/jobs/refresh`. Each board runs
under a time budget (`SCRAPER_TIMEOUT`, default 300s, min 30s — see
`agents/scrapper.py:_run_optional_scraper`): a hung board is recorded as an
`error` with a timeout message and the run continues. JobSpy is special:
`python-jobspy`'s native `tls-client` can segfault the whole interpreter on
Windows, so it is opt-in only (`ENABLE_JOBSPY=true`, default `false` →
`skipped-disabled`) and runs in an isolated `spawn` child process
(`_run_jobspy_isolated`): a child crash/timeout fails just that board and
the run still reaches summary/curate. Scope is tuned via `JOBSPY_SITES`
(default `linkedin,indeed`) and `JOBSPY_TERMS` (default 1 term). Pollers must
treat 404 (unknown run_id, e.g. after a server restart wipes the in-memory
registry) as terminal — never poll forever. The dashboard keeps a single
poll loop per page (`pollActive` guard in `frontend/js/app.js`), so a
refresh-resume plus click/409 path never stacks concurrent
`GET /api/scrape/{run_id}` loops.

### `POST /api/resume/{fp}` → `{status, filename}` (+ `GET …/download` PDF)
### `POST /api/cover-letter/{fp}` → `{status, filename, cover_letter}` (+ `GET …/download` text)
`api/materials.py` resolves the fingerprint against Sheets/snapshot rows,
runs `resume_generator` / `gemini_tools`, and serves fp-mapped files only
(404 unknown job / nothing generated yet, 502 generation failure).

### `GET /api/cv/profile` → `CvProfileOut` (501 when no fresh cache)
Cheap read only: `cache.get_cv_profile()` serves the on-disk
`tools/cv_parser._load_cached_profile` result (<7-day `cache/cv_profile_*.json`)
with an in-memory copy — never calls `parse_cv`, so no LLM work per request.
No fresh cache → `501 "No cached CV profile available…"`. Never invents data.

### `PUT /api/cv/profile` ← `CvProfileUpdate` → `CvProfileOut` (501 when uncached)
Persists Resume Studio edits (`cache.save_cv_profile`) into the on-disk
`cache/cv_profile_*.json` anchor. Merges whitelisted contact + skill fields
only — never triggers LLM parsing; unknown fields ignored, bad types coerced,
never 500 on bad input.

### `GET /api/cv/variants` → `CvVariant[]`
`cache.list_cv_variants()` via `tools/cv_library.CVLibrary()` discovery
(profiles stay lazy, no parsing) with a `cvs/`-dir scan fallback (safe
basenames + `_extract_domain_tags`, else `["general"]`). Missing dir →
`[]`, never 500.

### `POST /api/apply/{fp}` ← `{mode:"review"}` → `{status, tier, package_path, screenshot_path, apply_url, browser_opened}` (Phase 2a fill-and-review)
`api/apply.fill_review()` resolves the fingerprint via `cache.get_job`
(404 unknown), classifies tier via `agents.auto_applier.classify_tier`
(lazy import), dream tier → 422, else builds a local apply package via
`generate_apply_package`. For Greenhouse and Lever, it then launches a visible
Playwright browser (headless only in a container) and calls the existing
fill-only form helper. A worker thread owns the browser and keeps the page open
for manual review; closing the application tab or a 30-minute timeout closes
the browser. It captures a pre-submit screenshot. Other ATS platforms return
`package_only` without launching a browser. No sheet write or submit click occurs.
Any `mode` other than `"review"` → 400. `AUTO_APPLY_CONFIRM` is ignored
everywhere (legacy CLI blind submit permanently removed) — env cannot
re-enable submit over HTTP (`api/safety.py` `SUBMIT_ENABLED=False` fails
`/intent` + `/submit` closed with 403). Never writes `status:"submitted"`.

The cockpit calls this endpoint sequentially for up to three highest-scoring
eligible jobs per trigger (enforced daily cap with per-day persisted count),
then displays per-job status, in-browser screenshot preview
(`GET /api/apply/{fp}/screenshot`), local package paths, and a posting link
for package-only ATSs. The review fill carries the final tailored resume +
cover letter (same files a later submit would send). A Greenhouse fill whose
required applicant fields are missing/unverified is stored and returned as
`needs_review` (with `field_verification` + `profile_fields_verified` exposed)
instead of `filled_ready`, so intent (409) and submit (410) reject it before
any browser work. The separate CLI
`agents/auto_applier.py` path is fill-only; its legacy blind submit was
permanently removed.

The modules `api/apply_claims.py`, `api/apply_intents.py`,
`api/apply_validation.py`, and `api/apply_verification.py` back the
authenticated Greenhouse pair `POST /api/apply/{fp}/intent` +
`POST /api/apply/{fp}/submit`, which are mounted but fail closed with 403
while the kill-switch `api/safety.py SUBMIT_ENABLED=False` holds. Lever has
no submit path by design.

## 3. Cache (`cache.py`)

- **Tabs:** `JOB_TABS = ALL JOBS, TOP MATCHES, GOOD MATCHES`; `APPLIED`; `STATS`.
- **Reader:** own per-tab `get_all_values` + header→dict mapping (because
  `sheet_writer.get_all_rows()` only reads ALL JOBS). Lazy `tools` imports only —
  importing `api.*` must never touch the network or `agents/`.
- **TTL:** 90s default (`API_CACHE_TTL`, clamped 60–120), per tab + enrichment map.
- **Enrichment:** left-join `curated_jobs.json` on `job_fingerprint` (dict-with-`jobs`
  or bare-list payload); missing file/bad JSON → `{}`; absent fields → `null`.
- **Snapshot fallback:** empty ALL JOBS + `SNAPSHOT_FILES = scraped_jobs.json,
  fresh_scrape.json` → sheet-shaped rows with pipeline-MD5 fingerprints, unscored
  fields `""`, `status: NEW`. `data_source()` reports `sheets|snapshot|empty`
  without network calls.
- **Schemas:** `""` → `null`; numeric strings → float; bool-ish strings → bool
  (`computed/done` count as true) — Sheets stores everything as strings.

## 4. Auth & CORS (`deps.py`, `app.py`)

- `API_TOKEN` empty → open (local-dev default). Set → exact-match Bearer required
  on **every** `/api/*`, reads included.
- Non-local bind refuses at import time inside `create_app()` (covers the
  documented `uvicorn api.app:app` path, not just `python api/app.py`).
- CORS: localhost `:3000/:5173/:8000/:8080` by default, override via
  `API_CORS_ORIGINS`. `allow_methods = GET, POST, PUT, PATCH, OPTIONS`.
- Static UI mount is **last** so `/api/*` and `/docs` always win.

## 5. Testing

The suite was last fully verified 2026-10-01 at 291 passed, 1 skipped
(`venv\Scripts\python.exe -m pytest tests/ -q`):
`test_api_phase1.py` (18: faked `cache._read_tab_values` +
`_load_enrichment_map` — no credentials, no network; covers list/tab-400,
search+source+limit, enrichment join + `""→null`, get-one/404, stats snapshot,
tracker list/filter/APPLIED-header-fork preservation/create/patch-400/patch-404/patch-ok, refresh + refresh-400, health
secrets + heavy-import guards), `test_api_phase2.py`, `test_api_apply.py`
(fill-only happy path, default-review, 404, non-review → 400, dream → 422,
no heavy imports, kill-switch 403 on intent/submit when disabled,
attachment-gate refusals, field-readback gate (verified/repaired proceed;
mismatch/unavailable/missing_required never click) + minimum-profile gate
(name first_name/full_name + email required), bind-guard refuse/allow), `test_api_cv.py`
(profile GET/PUT + variants), `test_api_materials.py` (resume/cover-letter),
`test_api_freshness.py` (12-row Sheet mirror, refresh drops stale),
`test_api_jobs_contract.py` (ground-truth window + stale-row handling),
`test_auto_applier.py`, `test_country_filter.py`, and
`test_apply_submit_primitives.py` (fill fakes incl. attachment verification,
isolated claim/intent/validation/verification primitives incl. consumed-intent
replacement and failed_refunded-claim retry, score-coercion params; exact Lever
confirmation text is a deliberate skip pending a free live observation).
`test_api_apply.py` stubs the ATS fill
runner; tests do not launch actual ATS pages. Route-level 2b contract suite:
intent/submit routes are mounted and covered (kill-switch 403, auth, triple
gate, claim-first, attachment gate, status matrix). Mirror the Phase 1 fake
pattern for new endpoints (fake `cache.*`, assert
status codes, never hit live Sheets).

## 6. Adding an endpoint (convention)

1. Schema in `schemas.py` (nullable fields, `""→null` validators).
2. Sheet/cache accessor in `cache.py` (lazy imports, never crash → `[]`/`None`).
3. New file in `routers/` (or extend the matching group file) + `include_router`.
4. Tests in `tests/test_api_<group>.py` following the Phase 1 fake pattern.
5. Frontend fn in `js/api.js` + row in README endpoint table.
