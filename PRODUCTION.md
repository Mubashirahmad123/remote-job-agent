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

> **Why this is a hard rule today, not a style preference.** Each worker is a
> separate process with its own copy of the 90s TTL cache. At `--workers 4`
> you get four independent refresh timers: up to **4× the Google Sheets calls**
> (a real quota risk), and two requests landing on different workers can return
> **different data** — one worker refreshed, another is still serving an older
> cache. A shared-cache seam is scheduled as Phase 2.1b (§8); until it lands,
> `--workers 1` is the supported configuration.

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
`docker-compose.yml` ships `scheduler` (daemon) + `runner` (on-demand CLI).
Add this `api` service for the dashboard (mirror the existing volume mounts —
secrets stay read-only mounts, never baked into the image):

```yaml
  api:
    build: .
    container_name: job-agent-api
    restart: unless-stopped
    # --workers 1 is required, not cosmetic: the sheet cache is per-process.
    # See §2 and the Phase 2.1b cache seam in §8b before changing this.
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
docker compose up -d --build          # api + scheduler + caddy
docker compose logs -f api
docker compose run --rm runner python -m pytest tests/
```

- `SITE_ADDRESS=:80` (default) — plain HTTP on the bare IP.
- `SITE_ADDRESS=yourname.duckdns.org` — Caddy fetches a Let's Encrypt cert
  automatically (needs 80/443 open) and redirects HTTP → HTTPS.
- Open the dashboard at `http://<host>/` — you'll reach the login page.
  Create the first user with `python create_user.py <username> [password]`
  (run inside the container: `docker compose exec api python create_user.py ...`).
  The `API_TOKEN` is server-side only (never in URLs, localStorage, JS, or
  responses); browser users authenticate via the session cookie.

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
| `API_TOKEN` | empty | **Server-side only.** When set, non-local binds are allowed and `Authorization: Bearer <API_TOKEN>` authorizes server-to-server `/api/*` calls (scheduler/CI). Browser users log in with username/password (HttpOnly session cookie). Never exposed to the browser. |
| `APPLY_API_TOKEN` | empty | Dedicated elevated token for `POST /api/apply/{fp}/intent` + `/submit` + tracker reconcile. These routes accept EITHER a valid dashboard login session (human-in-the-loop) OR `Bearer <APPLY_API_TOKEN>` (server-to-server). The general `API_TOKEN` is never accepted on them. Set before any submit unlock; unset fails closed with 401. |
| `API_CORS_ORIGINS` | localhost:3000/5173/8000/8080 | Comma-separated override; `file://` (`null` origin) is never allowed — serve the UI from the API. `allow_credentials=True` (auth is a cookie), so a wildcard is never accepted |
| `AUTH_DB_PATH` | `APPLY_STATE_DB_PATH` → `data/apply_submit.db` | Optional dedicated SQLite file for the `users`/`sessions` tables. Default reuses the apply-state DB — no new infrastructure |
| `SESSION_TTL_HOURS` | `168` | Session lifetime (7 days), clamped to 1–2160 |
| `SESSION_COOKIE_SECURE` | empty = auto | Empty sets `Secure` only when the request arrives as https. **Set `true` behind a TLS-terminating proxy** (docker-compose does) — the API container only ever sees plain HTTP from Caddy |
| `LOGIN_RATE_LIMIT` | `12` | Brute-force budget per client IP per window. Exceeding it → `429` + `Retry-After`, checked before any Argon2 work |
| `LOGIN_USER_RATE_LIMIT` | `6` | Brute-force budget per username per window. Cleared on a successful login; the per-IP budget is not |
| `LOGIN_RATE_WINDOW` | `600` | Sliding window in seconds, shared by both budgets |
| `PASSWORD_MAX_LENGTH` | `128` | Resource control, not just validation — `/api/auth/login` is unauthenticated, so an unbounded field buys a full Argon2id verify on arbitrary-length input |
| `TRUST_PROXY_HEADERS` | empty | Honour `X-Forwarded-For` for rate-limit keying. Leave empty when uvicorn runs with `--proxy-headers` (it already rewrites the client IP); trusting a client-supplied header would let an attacker mint a fresh bucket per request |
| `API_DOCS_ENABLED` | empty | Publish `/docs` + `/openapi.json` with no session. Default **gated**: anonymous → 401, logged-in browser → Swagger. Only enable on a trusted network |
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
- **Phase 2.1a (planned):** uploaded CVs are PII. Gitignored upload dir,
  content-sniffed type validation, server-side size cap, token-gated endpoint,
  never logged, never baked into an image. Full rules in §8a.

---

## 6. Monitoring

- `GET /api/health` → `{"status":"ok","sheets_configured":true,"data_source":"sheets"}`
  - `data_source: snapshot` = Sheets unreachable, serving local scrape snapshot
  - `data_source: empty` = no Sheets, no snapshot (UI shows an explicit empty state)
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
| UI shows `(snapshot: N)` / `(unavailable)` | Sheets unreachable → check `keys.json` present, sheet shared with `client_email`, `/api/health` |
| `UnicodeEncodeError: 'charmap' ... '\u274c'` on Windows | Fixed in `tools/sheet_writer.py` (UTF-8 stdout reconfigure); pull latest |
| CORS `null` origin blocked | By design — open `http://127.0.0.1:8000/`, never `file://...index.html` |
| `401 Unauthorized` on `/api/*` | No valid session. Browser: open `/` and log in. Server-to-server: if `API_TOKEN` is set, send `Authorization: Bearer <API_TOKEN>` |
| `Refusing non-local bind without API_TOKEN` | Bind `127.0.0.1` or set `API_TOKEN` |
| Stale data after scrape | `POST /api/jobs/refresh`, or wait out the TTL (≤120s) |
| Arbeitnow jobs saved with blank company (older runs) | Fixed 2026-10-01: parser now reads the API's `company_name` field; re-scrape to backfill |
| A few Arbeitnow postings link to the company homepage, not the job page | Upstream API limitation (`url` = company site for a minority of postings); kept as-is — verified a slug-built `/jobs/<slug>` URL 404s, so no safe rewrite exists |
| Bot-protected/generic-selector boards (Naukri, CWJobs, TimesJobs, GoRemote, etc.) repeatedly `empty` | Structural, not a regression: no dedicated parser exists (generic HTML selectors vs bot walls), GoRemote/FounditIN URLs duplicate other boards, Adzuna needs keys, JustRemote/NoDesk fail DNS. No earlier targeted fix found in history; leave as expected-empty |
| Caddy can't get a certificate | `SITE_ADDRESS` must be a real hostname resolving to the host and 80/443 open (VCN ingress + ufw) — see `deploy/DEPLOY_ORACLE.md` §8 |
| Dashboard `401` / redirects to `/login.html` | Not signed in — open `/` and log in, or create the first user with `python create_user.py` |
| Bot-protected/generic-selector boards (Naukri, CWJobs, TimesJobs, GoRemote, etc.) repeatedly `empty` | Structural, not a regression — **and not untried**: these boards have already had targeted work (see note below). Remaining causes: bot walls defeat generic HTML selectors (no per-board parser), GoRemote/FounditIN URLs duplicate other boards, Adzuna needs keys, JustRemote/NoDesk fail DNS. Treat as expected-empty; the next real fix is per-board parsers behind a browser render, not more retry tuning |

> **Prior work on the "expected-empty" boards (so this isn't read as virgin territory).**
> These boards were triaged and partially addressed before being parked:
> - `BOT_PROTECTED_BOARDS` (`agents/scrapper.py`) already contains `Naukri`,
>   `CWJobs`, `WorkInStartups`, plus Dice/BuiltIn/Shine/NoFluffJobs/etc. Membership
>   buys longer base delays (3–6s vs 1–3s), header-pool rotation on retry, and a
>   5–10s backoff + retry specifically on 403 instead of an immediate give-up.
> - `SSL_ISSUE_BOARDS` = {`TimesJobs`, `NaukriGulf`} — these fetch with
>   verification pre-disabled (`NaukriGulf` also carries `verify_ssl: False` in its
>   board config) after SSL handshake failures were observed.
> - `GoRemote` is explicitly routed to `parse_html_generic` in the board dispatch,
>   so it has a parser path; it yields nothing because its URL overlaps boards
>   already scraped and the generic selectors don't match its markup.
> - `JS_RENDERED_BOARDS` diverts browser-only boards to the PlaywrightStealth pass
>   rather than dropping them.
>
> Conclusion stands (these are structurally hard and may never reliably yield), but
> the cheap levers — retries, delays, header rotation, SSL fallback, generic parser,
> browser fallback — have all been pulled already. Anything further means
> per-board parsers against an authenticated/stealth browser session.

---

## 8. Live submit (supervised, one-time)

The submit switch now has **three** states, resolved by
`api.safety.submit_mode()`:

| Mode | How | Behaviour |
|---|---|---|
| `disarmed` | default | `/intent` + `/submit` → 403. No browser launched. |
| `dry_run` | `SUBMIT_ENABLED=true` **and** `SUBMIT_DRY_RUN=true` | Full real path — browser, fill, readback, every gate, submit-button lookup — then stops before `.click()`. No intent consumed, no claim, no daily-cap spend. Repeatable. |
| `armed` | `SUBMIT_ENABLED=true` only | The click happens. |

`api/safety.py` keeps `SUBMIT_ENABLED = False` in git; env arming is for a
single process so a live run never requires a tracked code edit.
`SUBMIT_DRY_RUN` alone cannot open the path.

Evidence per run lands in `data/submit_runs/<timestamp>-<fp>/` (trace, video,
HAR, pre/post-click DOM, `attempt.json`) and is gitignored. The post-click DOM
is captured **before** verification is judged, so a failed verification can be
diagnosed instead of guessed at.

Full procedure, including the operator review gate and how to read each
outcome: **`LIVE_SUBMIT.md`**.

Recon any posting without touching the pipeline:
`python -m tools.submit_recon <url> --json recon.json` (read-only; never
clicks or fills).

---

## 9. Planned — Phase 2.1 (operational impact)

Two items scheduled for the next 3–4 days (spec and acceptance criteria in
`PM.md` §2.1). Both change how this thing is *operated*, so the ops-relevant
parts are here rather than only in the product tracker.

### 8a. CV-upload-first flow — handling uploaded CVs (PII)

Today the CV is a file an operator places on disk (`CV_PATH` / `CV_DIR`).
Phase 2.1a adds an upload path through the dashboard, which means the server
starts **receiving personal data over HTTP**. Operational rules to apply when
it lands:

| Concern | Rule |
|---|---|
| Storage location | A dedicated upload dir (e.g. `uploads/cv/`), **gitignored** — same treatment as `my_cv.pdf` today |
| Accepted types | PDF/DOCX only, validated by content sniffing, not just the filename extension |
| Size cap | Enforced server-side (reject oversize before parsing, not after) |
| Retention | Uploads are PII: define a retention/cleanup policy before enabling, and never log CV contents or parsed personal fields |
| Auth | The upload endpoint must sit behind the same `API_TOKEN` gate as every other write route; never expose it on a non-local bind without a token (the existing bind guard already refuses this) |
| Backups/images | Never bake an uploaded CV into a Docker image or a snapshot artifact |

Operator-visible behaviour: the dashboard must always show **which CV is
active** (uploaded vs on-disk) and offer a reset to the on-disk default.
Ambiguity here would mean applying with the wrong CV — the one failure mode
that actually matters in this flow.

### 8b. Multi-worker cache — what will and will not be built

**The problem:** the cache is per-process (see §2). `--workers 4` ⇒ four caches
⇒ up to 4× Sheet reads and cross-worker inconsistency.

**Deliberately NOT building Redis now.** Nothing in current usage (single
operator, own dashboard) needs `--workers > 1`, and standing up a Redis
instance is infrastructure for a scale problem this deployment does not have —
the same reasoning that correctly deferred Celery and the Docker queue.

What Phase 2.1b *does* deliver:

1. A cache-backend seam in `api/cache.py` so a shared store (Redis, or a shared
   file/SQLite) can be dropped in later without touching every accessor.
   In-process remains the default.
2. A **startup warning** when `--workers > 1` / `WEB_CONCURRENCY > 1` is
   detected with the in-process backend, naming the consequence explicitly.
   The current risk is not that multi-worker is impossible — it is that it
   *silently* works while burning quota and serving inconsistent reads.

Checklist before anyone ever raises worker count:

- [ ] Shared cache backend configured and reachable
- [ ] `/api/health` reports the active cache backend
- [ ] Sheet read volume re-measured against quota under the new worker count
- [ ] `POST /api/jobs/refresh` verified to invalidate across *all* workers

---

> Note: CV-upload-first flow is **scheduled as Phase 2.1a** — product spec and
> acceptance criteria in `PM.md` §2.1, operational/PII rules in §8a above.
> Current behavior until it ships: the CV must pre-exist in the repo
> (`my_cv.pdf` / `CV_PATH`, or a folder via `CV_DIR`).
