# BACKEND.md — FastAPI Reference (`api/`)

Phase 1 **reads** over the Sheets pipeline. No scraping, no writes (except the
tracker-status PATCH and cache refresh) — see `PM.md` for Phase 2 actions.

Run: `venv\Scripts\python -m uvicorn api.app:app --host 127.0.0.1 --port 8000`
Docs: `http://127.0.0.1:8000/docs` · Tests: `python -m pytest tests/test_api_phase1.py`

---

## 1. Layout (one file per group — keep it that way)

```
api/
  app.py            thin factory: CORS → include_router ×5 → static UI mount (LAST)
  deps.py           cors_origins() + require_token() (Bearer <API_TOKEN> when set)
  cache.py          sheet reads, TTL cache, curated enrichment, snapshot fallback
  schemas.py        JobOut, TrackerEntry, TrackerUpdate, HealthOut (+ VALID_TRACKER_STATUSES)
  mappers.py        to_job_out() / to_tracker_entry()
  routers/
    health.py       GET /api/health
    jobs.py         GET /api/jobs, GET /api/jobs/{job_fingerprint}
    stats.py        GET /api/stats
    tracker.py      GET /api/tracker, PATCH /api/tracker/{job_fingerprint}
    system.py       POST /api/jobs/refresh
    runs.py         POST /api/scrape, GET /api/scrape[/{run_id}] (registry: api/runs.py)
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
  `API_CORS_ORIGINS`. `allow_methods = GET, POST, PATCH, OPTIONS`.
- Static UI mount is **last** so `/api/*` and `/docs` always win.

## 5. Testing

`tests/test_api_phase1.py` (18 tests): fakes `cache._read_tab_values` +
`_load_enrichment_map` — no credentials, no network. Covers list/tab-400,
search+source+limit, enrichment join + `""→null`, get-one/404, stats snapshot,
tracker list/filter/patch-400/patch-404/patch-ok, refresh + refresh-400, health
secrets + heavy-import guards. Mirror this pattern for Phase 2 (fake `cache.*`,
assert status codes, never hit live Sheets).

## 6. Adding an endpoint (convention)

1. Schema in `schemas.py` (nullable fields, `""→null` validators).
2. Sheet/cache accessor in `cache.py` (lazy imports, never crash → `[]`/`None`).
3. New file in `routers/` (or extend the matching group file) + `include_router`.
4. Tests in `tests/test_api_phase2.py` following the Phase 1 fake pattern.
5. Frontend fn in `js/api.js` + row in README endpoint table.
