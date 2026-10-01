# PRODUCTION.md — Deployment & Operations Guide

How to run the Remote Job Agent (API + dashboard + scheduler) beyond local dev.

---

## 1. Prerequisites

- Python 3.11+, or Docker Engine + `docker compose`
- `.env` filled (copy from `.env.example`) — strict dotenv format: exact
  `UPPER_SNAKE=key`, no spaces around `=`
- `keys.json` — Google Cloud service-account key in the project root
- The Google Sheet shared with the service account's `client_email` (Editor)
- `my_cv.pdf` in the project root (CV matching fallback)

Verify wiring before deploying:

```bash
venv\Scripts\python -m uvicorn api.app:app --host 127.0.0.1 --port 8000
# http://127.0.0.1:8000/api/health -> sheets_configured: true, data_source: "sheets"
```

---

## 2. Local production run

```powershell
# API + dashboard (same-origin UI at /)
$env:PYTHONPATH = "."
venv\Scripts\python.exe -m uvicorn api.app:app --host 127.0.0.1 --port 8000 --workers 1

# Scheduler (separate terminal — Mon/Thu scrape, daily quick checks)
venv\Scripts\python.exe scheduler.py
```

Keep `--workers 1`: the sheet cache is in-process per worker; multiple workers
duplicate Sheet reads and can exceed quota.

Dashboard Scrape Now needs no Docker: `POST /api/scrape` runs the scrape in a
background thread inside this same API process (single active run; 409 while
one is running), then `POST /api/jobs/refresh` picks up the fresh rows.

---

## 3. Docker deployment

`docker-compose.yml` ships `scheduler` (daemon) + `runner` (on-demand CLI).
Add this `api` service for the dashboard (mirror the existing volume mounts —
secrets stay read-only mounts, never baked into the image):

```yaml
  api:
    build: .
    container_name: job-agent-api
    restart: unless-stopped
    command: ["python", "-m", "uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
    env_file:
      - .env
    environment:
      - PLAYWRIGHT_HEADLESS=true
      - TZ=${TZ:-Asia/Kolkata}
    ports:
      - "127.0.0.1:8000:8000"   # bind 127.0.0.1; use "8000:8000" + API_TOKEN for LAN
    volumes:
      - ./.env:/app/.env:ro
      - ./keys.json:/app/keys.json:ro
      - ./my_cv.pdf:/app/my_cv.pdf:ro
      - ./data:/app/data
      - ./logs:/app/logs
      - ./seen_jobs.json:/app/seen_jobs.json
      - ./scraped_jobs.json:/app/scraped_jobs.json
      - ./curated_jobs.json:/app/curated_jobs.json
      - ./apply_packages:/app/apply_packages
      - ./resumes:/app/resumes
      - ./cover_letters:/app/cover_letters
      - ./screenshots:/app/screenshots
```

```bash
docker compose up -d scheduler api
docker compose logs -f api
docker compose run --rm runner python -m pytest tests/
```

---

## 4. Configuration reference (`.env`)

| Variable | Default | Notes |
|---|---|---|
| `GOOGLE_SHEETS_ID` | — | Sheet key (required for `data_source: sheets`) |
| `GOOGLE_SERVICE_ACCOUNT` | `keys.json` | Path must exist; presence-only check in `/api/health` |
| `API_HOST` | `127.0.0.1` | Non-local bind refuses to start without `API_TOKEN` |
| `API_PORT` | `8000` | — |
| `API_TOKEN` | empty | When set, all `/api/*` need `Authorization: Bearer <token>` (even reads) |
| `APPLY_API_TOKEN` | empty | Dedicated token for `POST /api/apply/{fp}/intent` + `/submit` (unconditional auth; `API_TOKEN` is never accepted there). Set before any submit unlock; unset fails closed with 401 |
| `API_CORS_ORIGINS` | localhost:3000/5173/8000/8080 | Comma-separated override; `file://` (`null` origin) is never allowed — serve the UI from the API |
| `API_CACHE_TTL` | `90` | Seconds, clamped to 60–120 |
| `CV_PATH` | `my_cv.pdf` | Primary CV (matching fallback, profile-cache anchor) |
| `CV_DIR` | empty | Optional CV-variants folder (`cvs/`); `GET /api/cv/variants` lists it, best CV picked per job |
| `MIN_MATCH_SCORE` | `70` | Curator threshold for GOOD MATCHES tab |
| `AUTO_APPLY_CONFIRM` | `false` | Legacy CLI flag, now ignored everywhere (blind submit permanently disabled). The HTTP API ignores it; Greenhouse `/intent` + `/submit` are gated by `SUBMIT_ENABLED=False` (403) plus `APPLY_API_TOKEN`. |

---

## 5. Security checklist

- Never commit `.env`, `keys.json`, `my_cv.pdf`, `scraped_jobs.json` (gitignored).
- Never bake secrets into images (`.dockerignore` enforces this); mount read-only.
- Expose the API beyond localhost only with `API_TOKEN` set + HTTPS in front
  (reverse proxy); the app itself serves plain HTTP.
- Health endpoint leaks nothing: `sheets_configured` / `curated_jobs_loaded`
  are presence-only signals (covered by `tests/test_api_phase1.py`).

---

## 6. Monitoring

- `GET /api/health` → `{"status":"ok","sheets_configured":true,"data_source":"sheets"}`
  - `data_source: snapshot` = Sheets unreachable, serving local scrape snapshot
  - `data_source: empty` = no Sheets, no snapshot (UI shows mock fallback)
- `POST /api/jobs/refresh` clears the TTL cache after a scheduled scrape lands.
- Logs: `logs/scraper.log` (scheduler); `docker compose logs -f api` (container).
- Sidebar `Hot` badge is live (`dashboard.js:_applyMetrics` ← `/api/stats`
  `tabs`). Open question (decide later): should "Hot" mean **A)** TOP MATCHES
  only (score ≥ 85, strict, matches the Command Deck card) or **B)** TOP +
  GOOD MATCHES (score ≥ 70, everything curated)? Currently A; reads 0 while
  no job scores 85+ even when Total Jobs is 24.

---

## 7. Troubleshooting

| Symptom | Cause → Fix |
|---|---|
| UI shows `(snapshot: N)` / `(mock)` | Sheets unreachable → check `keys.json` present, sheet shared with `client_email`, `/api/health` |
| `UnicodeEncodeError: 'charmap' ... '\u274c'` on Windows | Fixed in `tools/sheet_writer.py` (UTF-8 stdout reconfigure); pull latest |
| CORS `null` origin blocked | By design — open `http://127.0.0.1:8000/`, never `file://...index.html` |
| `401 Unauthorized` on `/api/*` | `API_TOKEN` is set → send `Authorization: Bearer <token>` (frontend: `localStorage rja_api_token`) |
| `Refusing non-local bind without API_TOKEN` | Bind `127.0.0.1` or set `API_TOKEN` |
| Stale data after scrape | `POST /api/jobs/refresh`, or wait out the TTL (≤120s) |
| Arbeitnow jobs saved with blank company (older runs) | Fixed 2026-10-01: parser now reads the API's `company_name` field; re-scrape to backfill |
| A few Arbeitnow postings link to the company homepage, not the job page | Upstream API limitation (`url` = company site for a minority of postings); kept as-is — verified a slug-built `/jobs/<slug>` URL 404s, so no safe rewrite exists |
| Bot-protected/generic-selector boards (Naukri, CWJobs, TimesJobs, GoRemote, etc.) repeatedly `empty` | Structural, not a regression: no dedicated parser exists (generic HTML selectors vs bot walls), GoRemote/FounditIN URLs duplicate other boards, Adzuna needs keys, JustRemote/NoDesk fail DNS. No earlier targeted fix found in history; leave as expected-empty |

> Note: CV-upload-first flow (upload CV -> scrape/match on it -> Resume Studio surfaces missing sections like projects/certifications) is tracked in PM.md section 3 Backlog, not here. Current behavior: CV must pre-exist in the repo (my_cv.pdf / CV_PATH).
