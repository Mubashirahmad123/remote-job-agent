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

`docker-compose.yml` ships the full stack: `scheduler` (Mon/Thu daemon),
`runner` (on-demand CLI, `cli` profile), `api` (dashboard + endpoints), and
`caddy` (reverse proxy on 80/443 with automatic Let's Encrypt). Secrets stay
read-only mounts, never baked into the image. The `api` service keeps a
`127.0.0.1:8000` host port as an SSH-tunnel escape hatch — public traffic
reaches it only through Caddy.

`API_TOKEN` is required: compose binds the API `0.0.0.0` inside the container
and `api/app.py` refuses a non-local bind without it.

```bash
docker compose up -d --build          # api + scheduler + caddy
docker compose logs -f api
docker compose run --rm runner python -m pytest tests/
```

- `SITE_ADDRESS=:80` (default) — plain HTTP on the bare IP.
- `SITE_ADDRESS=yourname.duckdns.org` — Caddy fetches a Let's Encrypt cert
  automatically (needs 80/443 open) and redirects HTTP → HTTPS.
- Open the dashboard once with the token in the URL —
  `http://<host>/?token=<API_TOKEN>`; `frontend/js/auth-bootstrap.js` stores
  it in `localStorage` and strips it from the address bar.

**$0 walkthrough:** [`deploy/DEPLOY_ORACLE.md`](deploy/DEPLOY_ORACLE.md) —
Oracle Cloud Always Free VM + free DuckDNS hostname + `setup-vm.sh` bootstrap
(Docker, ufw/iptables fixups, runtime files), with ops + troubleshooting.

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
| `SITE_ADDRESS` | `:80` | Caddy site address (compose `caddy` service). A real hostname — free: DuckDNS — enables automatic Let's Encrypt HTTPS + HTTP→HTTPS redirect; bare IP stays plain HTTP |
| `CV_PATH` | `my_cv.pdf` | Primary CV (matching fallback, profile-cache anchor) |
| `CV_DIR` | empty | Optional CV-variants folder (`cvs/`); `GET /api/cv/variants` lists it, best CV picked per job |
| `MIN_MATCH_SCORE` | `70` | Curator threshold for GOOD MATCHES tab |
| `AUTO_APPLY_CONFIRM` | `false` | Legacy CLI flag, now ignored everywhere (blind submit permanently disabled). The HTTP API ignores it; Greenhouse `/intent` + `/submit` are gated by `SUBMIT_ENABLED=False` (403) plus `APPLY_API_TOKEN`. |
| `AUTO_APPLY_THRESHOLD` | `75` | Minimum match score for the auto-apply queue |
| `TIER_BATCH_MAX` | `75` | Auto-apply tier bound (`agents/auto_applier.py`): score ≤ this → batch tier, up to `TIER_DREAM_THRESHOLD` → mid tier |
| `TIER_DREAM_THRESHOLD` | `90` | Score ≥ this → dream tier — manual review only (dashboard apply returns 422) |

---

## 5. Security checklist

- Never commit `.env`, `keys.json`, `my_cv.pdf`, `scraped_jobs.json` (gitignored).
- Never bake secrets into images (`.dockerignore` enforces this); mount read-only.
- Expose the API beyond localhost only with `API_TOKEN` set and HTTPS in
  front — the shipped `caddy` compose service is the default edge (automatic
  Let's Encrypt when `SITE_ADDRESS` is a hostname); the app itself serves
  plain HTTP.
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
| Caddy can't get a certificate | `SITE_ADDRESS` must be a real hostname resolving to the host and 80/443 open (VCN ingress + ufw) — see `deploy/DEPLOY_ORACLE.md` §8 |
| Dashboard `401` on a token-protected deploy | Reopen `/?token=<API_TOKEN>` once — `auth-bootstrap.js` stores it in `localStorage` |

> Note: CV-upload-first flow (upload CV -> scrape/match on it -> Resume Studio surfaces missing sections like projects/certifications) is tracked in PM.md section 3 Backlog, not here. Current behavior: CV must pre-exist in the repo (my_cv.pdf / CV_PATH).
