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

Two rhythms: **write path** (scheduler/CLI/dashboard-triggered scrape → Sheets,
minutes) and **read path** (API → UI, seconds, TTL-cached). `POST /api/scrape`
starts a background scrape run in a daemon thread inside the API process
(single active run); the pipeline never serves HTTP itself.

## 2. Components

| Layer | Location | Role | State |
|---|---|---|---|
| Scraping | `agents/scrapper.py`, `tools/*scraper*.py` | 45+ boards → raw jobs (per-board `SCRAPER_TIMEOUT`; JobSpy opt-in via `ENABLE_JOBSPY` in isolated child process) | stateless per run |
| Curation | `agents/curator.py`, `tools/cv_*.py`, `tools/deduplicator.py` | dedup (MD5 `job_fingerprint`), keyword + optional FAISS scoring, rank | `seen_jobs.json`, `cv_embeddings.pkl` |
| Persistence | Google Sheets via `tools/sheet_writer.py` | 5 tabs: ALL JOBS, TOP MATCHES, GOOD MATCHES, APPLIED, STATS | the Sheet |
| Read API | `api/` | TTL cache over Sheets + `curated_jobs.json` enrichment left-join; action routers (scrape runs, tailored materials, CV profile edits) | in-process cache (90s) |
| Dashboard | `frontend/` | bento metrics, job desk, drawer, resume studio, fill-only review-package cockpit, kanban | browser + `localStorage` (token/base URL) |
| Automation | `scheduler.py`, `track.py`, `main.py`, `Run.py` | cron, tracker CLI, pipeline entry points; standalone CLI also has ATS Playwright fill (fill-only; blind submit permanently removed) | `data/`, `logs/` |

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
6. **Dashboard apply gate** — `POST /api/apply/{fp}` creates a local review
   package and, for Greenhouse/Lever only, fills the final tailored resume +
   cover letter in a visible Playwright browser window and captures a
   pre-submit screenshot served in-browser by
   `GET /api/apply/{fp}/screenshot`. The browser stays open for human
   review; this route never clicks submit. Unsupported ATSs receive a
   package only. The cockpit processes up to three eligible jobs
   sequentially under an enforced daily cap; its submit toggle remains
   disabled. Greenhouse `/intent` + `/submit` exist but fail closed with
   403 while `api/safety.py SUBMIT_ENABLED=False`, require
   `APPLY_API_TOKEN`, and refuse to click unless the refill verifies the
   resume + cover letter actually attached, the typed-field readback is
   `verified`/`repaired` (`mismatch`/`unavailable`/`missing_required`/error
   never click), and the minimum profile (name + email) was typed and
   verified. A Greenhouse fill with missing/unverified required fields is
   stored and reported as `needs_review`, never `filled_ready`. The legacy
   CLI blind submit is permanently removed. See `README.md` and `PM.md`.

## 4b. Planned — Phase 2.1 (design intent, not yet built)

| Item | Design intent | Why it is shaped this way |
|---|---|---|
| **2.1a CV-upload-first** | Upload → existing CV parse chain → the parsed profile becomes the *active* matching profile for the session; Resume Studio diffs job `tech_stack` (through the same `cache.extract_skills` canonicalization used by `/api/skills`) against CV skills and surfaces the missing set | Reuses the parser and the skill canonicalizer rather than adding a second notion of "skill". The new capability is the **diff**, not the upload |
| **2.1b Cache backend seam** | Put the TTL store in `api/cache.py` behind a small interface; keep in-process as the default; warn loudly at `--workers > 1` | The risk is not that multi-worker fails — it is that it *silently* succeeds while burning 4× Sheets quota and serving inconsistent reads. A seam keeps a future Redis swap contained; adding Redis now would be infrastructure for a scale problem this deployment does not have |

Spec: `PM.md` §2.1. Operations/PII rules: `PRODUCTION.md` §8.

## 5. Failure modes

| Failure | Behavior |
|---|---|
| Sheets down / `keys.json` missing | `data_source: snapshot` → local snapshot; else `empty` → UI empty state with error banner (no mock layer exists) |
| `curated_jobs.json` missing/corrupt | Enrichment fields `null`, never crash |
| API unreachable from browser | Per-section error/empty state naming the failed endpoint; UI stays usable |
| Slow first paint | Mock renders instantly; live data re-renders via `store.subscribe` |
| Bot-protected / generic-selector boards repeatedly `empty` (Naukri, CWJobs, TimesJobs, GoRemote, …) | Structural, not a regression (no per-board parser, bot wall, duplicate/dead URLs) — expected-empty, but already partially addressed (`BOT_PROTECTED_BOARDS` retry/header rotation, `SSL_ISSUE_BOARDS`, generic parser for GoRemote); see `PRODUCTION.md` §7 |
