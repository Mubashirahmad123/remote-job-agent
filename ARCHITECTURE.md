# ARCHITECTURE.md — System Design (Backend + Frontend)

One-page map of how the Remote Job Agent fits together. Details live in
`BACKEND.md`, `FRONTEND.md`, `PRODUCTION.md`, `DESIGN.md`.

---

## 1. Big picture

```
45+ job boards ──▶ agents/scrapper.py ──▶ agents/curator.py ──▶ Google Sheets
   (API/HTML/          scrape              dedup → CV score      ALL JOBS
    Playwright/                             → rank               TOP / GOOD MATCHES
    JobSpy/Crawl4AI)                                             APPLIED / STATS
                                                                      │
                                                                      ▼
                                                            api/ (FastAPI reads)
                                                            TTL cache + enrichment
                                                                      │
                                                                      ▼
                                                        frontend/ dashboard (same-origin)
```

Two rhythms: **write path** (scheduler/CLI → Sheets, minutes) and **read path**
(API → UI, seconds, TTL-cached). The API never scrapes; the pipeline never serves HTTP.

## 2. Components

| Layer | Location | Role | State |
|---|---|---|---|
| Scraping | `agents/scrapper.py`, `tools/*scraper*.py` | 45+ boards → raw jobs | stateless per run |
| Curation | `agents/curator.py`, `tools/cv_*.py`, `tools/deduplicator.py` | dedup (MD5 `job_fingerprint`), keyword + optional FAISS scoring, rank | `seen_jobs.json`, `cv_embeddings.pkl` |
| Persistence | Google Sheets via `tools/sheet_writer.py` | 5 tabs: ALL JOBS, TOP MATCHES, GOOD MATCHES, APPLIED, STATS | the Sheet |
| Read API | `api/` | TTL cache over Sheets + `curated_jobs.json` enrichment left-join | in-process cache (90s) |
| Dashboard | `frontend/` | bento metrics, job desk, drawer, resume studio, auto-apply cockpit, kanban | browser + `localStorage` (token/base URL) |
| Automation | `scheduler.py`, `track.py`, `main.py`, `Run.py` | cron, tracker CLI, pipeline entry points | `data/`, `logs/` |

## 3. Data contracts

- **Job identity:** MD5 of `title|company|normalized_url` (`tools/deduplicator.py:job_fingerprint`).
  Stable across pipeline, Sheets, snapshot fallback, API (`{fingerprint}`), and UI (`job.id`).
- **Sheet columns:** `tools/sheet_writer.py:COLUMNS` (14 base columns) — the API's
  `JobOut` extends them with curator enrichment, all nullable.
- **Tracker columns:** owned by `tools/application_tracker.py` (12 columns), not the
  `sheet_writer` APPLIED fork — see `api/schemas.py` docstring.
- **API ↔ UI:** `api/schemas.py` ⇄ `frontend/js/api.js` + `store.normalizeJob/normalizeTracker`.

## 4. Key decisions (why things are this way)

1. **Lazy imports in `api/`** — `agents/curator.py` parses the CV at import time;
   the API imports pipeline modules only inside handlers (none needed for reads).
2. **Per-tab TTL cache (90s, clamp 60–120)** — one Sheet round-trip is ~1–3s per tab;
   uncached full load is ~10–15s plus quota burn.
3. **Snapshot fallback** — `ALL JOBS` serves `scraped_jobs.json`/`fresh_scrape.json`
   when Sheets is unreachable; `data_source` (`sheets|snapshot|empty`) keeps it honest.
4. **Same-origin UI** — `api/app.py` mounts `frontend/` so the dashboard opens at
   `http://127.0.0.1:8000/`; `file://` (`null` origin) is blocked by CORS by design.
5. **Localhost-first auth** — no token locally; non-local bind requires `API_TOKEN`
   enforced on every `/api/*` call including reads.
6. **Auto-apply safety gate** — `AUTO_APPLY_CONFIRM=false` fills & screenshots;
   submit needs explicit opt-in (see `agents/auto_applier.py`, cockpit in UI).

## 5. Failure modes

| Failure | Behavior |
|---|---|
| Sheets down / `keys.json` missing | `data_source: snapshot` → local snapshot; else `empty` → UI mock fallback with error banner |
| `curated_jobs.json` missing/corrupt | Enrichment fields `null`, never crash |
| API unreachable from browser | Per-section mock fallback; UI stays usable, banners explain |
| Slow first paint | Mock renders instantly; live data re-renders via `store.subscribe` |
