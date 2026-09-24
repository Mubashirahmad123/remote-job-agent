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
| `API_CORS_ORIGINS` | localhost:3000/5173/8000/8080 | Comma-separated override; `file://` (`null` origin) is never allowed — serve the UI from the API |
| `API_CACHE_TTL` | `90` | Seconds, clamped to 60–120 |
| `CV_PATH` | `my_cv.pdf` | Primary CV (matching fallback, profile-cache anchor) |
| `CV_DIR` | empty | Optional CV-variants folder (`cvs/`); `GET /api/cv/variants` lists it, best CV picked per job |
| `MIN_MATCH_SCORE` | `70` | Curator threshold for GOOD MATCHES tab |
| `AUTO_APPLY_CONFIRM` | `false` | `false` = fill & review; `true` = live submit (danger) |

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
