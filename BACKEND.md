# BACKEND.md — FastAPI Reference (`api/`)

Reads over the Sheets pipeline **plus** Phase 2 action endpoints (scrape runs,
tailored materials, CV profile edits) — see `PM.md` for what is still backlog
(apply submit, skills aggregate).

Run: `venv\Scripts\python -m uvicorn api.app:app --host 127.0.0.1 --port 8000`
Docs: `http://127.0.0.1:8000/docs` · Tests: `venv\Scripts\python.exe -m pytest tests/ -q` (136 green, 8 files)

---

## 1. Layout (one file per group — keep it that way)

```
api/
  app.py            thin factory: CORS → include_router ×8 → static UI mount (LAST)
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
    tracker.py      GET /api/tracker, PATCH /api/tracker/{job_fingerprint}
    system.py       POST /api/jobs/refresh
    runs.py         POST /api/scrape, GET /api/scrape[/{run_id}] (registry: api/runs.py)
    materials.py    POST /api/resume/{fp} + download, POST /api/cover-letter/{fp} + download
                    (registry: api/materials.py — fp-mapped files only, no path params)
    cv.py           GET /api/cv/profile (cached parse, 501 when uncached),
                    PUT /api/cv/profile (Studio edits → on-disk cache, 501 when uncached),
                    GET /api/cv/variants (CVLibrary discovery w/ cvs/ fallback; missing dir → [])
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
| `source` | — | exact board match, case-insensitive |
| `limit` / `offset` | `50` / `0` | `limit` clamped 1–500 |

### `GET /api/jobs/{fp}` → `JobOut` (404 when unknown; searches ALL JOBS first)

### `GET /api/stats`
`{total_jobs, tabs{…}, by_source{…}, stats_rows[], curated_jobs}` — counts from
job tabs + raw STATS-tab rows. Never crashes (returns zeros on error).

### `GET /api/tracker?status=` → `TrackerEntry[]` (optional exact status filter)

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
`GET /api/scrape` (run list), then `POST /api/jobs/refresh`.

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
- `__main__` guard refuses non-local bind without `API_TOKEN`.
- CORS: localhost `:3000/:5173/:8000/:8080` by default, override via
  `API_CORS_ORIGINS`. `allow_methods = GET, POST, PUT, PATCH, OPTIONS`.
- Static UI mount is **last** so `/api/*` and `/docs` always win.

## 5. Testing

136 tests across 8 files (`venv\Scripts\python.exe -m pytest tests/ -q`):
`test_api_phase1.py` (18: faked `cache._read_tab_values` +
`_load_enrichment_map` — no credentials, no network; covers list/tab-400,
search+source+limit, enrichment join + `""→null`, get-one/404, stats snapshot,
tracker list/filter/patch-400/patch-404/patch-ok, refresh + refresh-400, health
secrets + heavy-import guards), `test_api_phase2.py`, `test_api_cv.py`
(profile GET/PUT + variants), `test_api_materials.py` (resume/cover-letter),
`test_api_freshness.py` (12-row Sheet mirror, refresh drops stale),
`test_api_jobs_contract.py` (ground-truth window + stale-row handling),
`test_auto_applier.py`, `test_country_filter.py`.
Mirror the Phase 1 fake pattern for new endpoints (fake `cache.*`, assert
status codes, never hit live Sheets).

## 6. Adding an endpoint (convention)

1. Schema in `schemas.py` (nullable fields, `""→null` validators).
2. Sheet/cache accessor in `cache.py` (lazy imports, never crash → `[]`/`None`).
3. New file in `routers/` (or extend the matching group file) + `include_router`.
4. Tests in `tests/test_api_<group>.py` following the Phase 1 fake pattern.
5. Frontend fn in `js/api.js` + row in README endpoint table.
