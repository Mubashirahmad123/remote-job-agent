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
  app.py            thin factory: CORS → _GateMiddleware → include_router ×13
                    (11 gated + `auth`/`liveness` open) → static UI mount (LAST)
  deps.py           cors_origins() + require_token() (Bearer <API_TOKEN> when set)
                    + resolve_actor() / require_actor() / require_submit_actor()
                    (Scenario A attribution — see §4)
  errors.py         failure()/missing(): traceback to the log, incident id to
                    the caller, never exception text in a response
  auth.py           Argon2id users, server-side sessions, roles, login-event
                    audit, in SQLite. db_path() resolves the env on EVERY call
  ratelimit.py      sliding-window login limiter (per-IP + per-username budgets)
  activity.py       merged actor-attributed audit feed
  apply_state.py    apply artifacts/claims/intents persistence. DB_PATH resolves
                    ONCE at import — unlike auth.db_path() — so tests must patch
                    the attribute (see tests/conftest.py)
  cache.py          sheet reads, TTL cache, curated enrichment, snapshot fallback,
                    CV profile cache + variant discovery
  schemas.py        JobOut, TrackerEntry, TrackerUpdate, HealthOut (+ VALID_TRACKER_STATUSES),
                    CvProfileOut, CvProfileUpdate, CvVariant
  mappers.py        to_job_out() / to_tracker_entry()
  materials.py      resume/cover-letter generation registry (fp-mapped files only)
  runs.py           background scrape-run registry (single active run)
  routers/
    auth.py         POST /api/auth/login, POST /api/auth/logout, GET /api/auth/me
                    (OPEN — the login page has to work before a session exists)
    liveness.py     GET /api/health/live (OPEN, exactly {"status":"ok"}, hidden
                    from the schema; for container/orchestrator probes)
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
    activity.py     GET /api/activity (merged audit feed; login events admin-only)
    apply.py        POST /api/apply/{fp} creates a local review package only
            (service: api/apply.py, gate: api/safety.py; no ATS browser or submit)
```

To debug: comment out one `include_router` line in `app.py` to isolate a group.
Routers are split into `_GATED_ROUTERS` (auth attached at the router level) and
`_OPEN_ROUTERS` (`auth`, `liveness`); add new routers to the gated tuple, since
per-route `Depends` alone fails **open** if one is forgotten.

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

### Planned — Phase 2.1 (not implemented yet)

- `POST /api/cv/upload` (multipart) — validate type (content-sniffed) + size,
  parse through the existing CV chain, return the structured profile. The
  uploaded profile becomes the active matching profile; `GET /api/cv/profile`
  gains a field saying **which** CV is active (uploaded vs on-disk) plus a
  reset path. Token-gated like every write route. Uploaded files are PII —
  storage rules in `PRODUCTION.md` §8a.
- Gap analysis reuses `cache.extract_skills` so job-side skills are
  canonicalized identically to `/api/skills` (role nouns already purged) —
  no second definition of "skill".
- Cache backend seam (2.1b): the TTL store moves behind a small interface,
  in-process stays default, and a `--workers > 1` startup warning is added.
  Redis is explicitly **not** being added yet. See `PM.md` §2.1.

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

## 4. Auth & CORS (`deps.py`, `app.py`, `auth.py`, `ratelimit.py`)

- **Three accepted credentials, checked in this order** (single predicate:
  `deps.credentials_ok`, shared by every gate so they cannot drift apart):
  1. valid `rja_session` HttpOnly cookie → allow;
  2. `Authorization: Bearer <API_TOKEN>` exact match → allow (a *wrong* Bearer
     is a 401, never a fallthrough);
  3. `open_access()` — `API_TOKEN` unset **and** zero users → allow.
  A DB read failure counts as "users may exist", so step 3 **fails closed**.
- `open_access()` is a fresh-clone localhost convenience only, and it is
  announced with a `warnings.warn` at every startup. It is *not* the same as
  "`API_TOKEN` empty → open": once `create_user.py` has run, an empty
  `API_TOKEN` means every `/api/*` route returns 401.
- Non-local bind refuses at import time inside `create_app()`, checked against
  **both** `API_HOST` and uvicorn's own `--host` flag. Reading only the env var
  let the documented `uvicorn api.app:app --host 0.0.0.0` bind publicly with
  `API_HOST` unset — which, combined with `open_access()`, meant a fully
  public API.
- **Auth is attached at the router level** (`_include_gated` →
  `include_router(dependencies=[Depends(require_token)])`) *and* per route.
  Per-route alone fails OPEN: one forgotten `Depends` on a new endpoint ships
  it public. Router-level makes the safe behaviour the default. `auth.py` is
  the only exempt router — `/api/auth/login` has to be reachable logged out.
  This must be done via `include_router(dependencies=...)`, **not** by
  appending to `router.dependencies`: this FastAPI version resolves included
  routers lazily (`_IncludedRouter`) and post-construction mutation is a
  silent no-op. `tests/test_api_auth_hardening.py` pins that trap.
- `_GateMiddleware` covers the three things no router dependency can reach:
  `/docs` + `/openapi.json` (FastAPI serves them itself — gated by default,
  `API_DOCS_ENABLED=true` to publish) and `/index.html` (the `StaticFiles`
  mount would otherwise hand out the dashboard shell past the `GET /`
  redirect). It also sets `X-Content-Type-Options`, `X-Frame-Options` and
  `Referrer-Policy` on every response, so a bare uvicorn deploy is not
  silently unprotected without Caddy. No CSP: the dashboard relies on inline
  `<script>`/`<style>` blocks and a strict policy would break it.
- **Login abuse resistance** (`ratelimit.py`): two sliding-window budgets —
  per client IP (`LOGIN_RATE_LIMIT`, default 12) and per username
  (`LOGIN_USER_RATE_LIMIT`, default 6) over `LOGIN_RATE_WINDOW` (default 600s)
  — are checked **before any Argon2 work** and answer `429` + `Retry-After`.
  Both are needed: per-IP alone lets one attacker lock out a NAT'd office,
  per-username alone lets an attacker spray one password from rotating IPs. A
  successful login clears the *username* budget only. The handler is
  `async def` and awaits its failure penalty — the previous sync `def` +
  `time.sleep(0.5)` held a threadpool worker per attempt, so ~40 concurrent
  bad passwords saturated the 40-thread pool and stalled every other sync
  route (measured 5.6s wall → 1.4s, with 34/40 answered 429 and no hashing).
- **A missing username costs the same as a wrong password** (`auth.py`,
  `_DECOY_PASSWORD_HASH`): `verify_login` used to return on `row is None`
  without touching Argon2, so an existing username cost one Argon2id verify
  (~97-107 ms at m=65536,t=3,p=4) and a non-existent one cost none. Measured
  over the real endpoint, 601-799 ms vs 507-508 ms — disjoint ranges, so a
  handful of requests sorted any candidate list into real accounts and not. The
  response body and the audit trail were already identical; wall-clock time was
  the only remaining channel. The no-such-user path now verifies against a decoy
  hash of a discarded random secret and throws the answer away, which puts both
  paths at 500 ms of failure penalty plus one verify. Deliberately **not**
  equalised: requests rejected on their own shape (empty or oversized password)
  skip the verify, because that branch depends on what the caller sent rather
  than on whether the account exists, and paying for a decoy verify there would
  re-open the unbounded-Argon2 hole `PASSWORD_MAX_LENGTH` closes.
- The limiters are **per-process**, which is exact under the deployed
  `--workers 1`. Scaling out multiplies every budget by the worker count — move
  them to a shared store first.
- **Action budgets** (`ratelimit.py`, `ACTION_KINDS`): the login limiter guards
  the only *unauthenticated* write. It guarded nothing else, so every
  authenticated caller could loop the endpoints that cost real money or real CPU
  with no ceiling at all — resume and cover-letter generation (an LLM call each),
  the headless-browser apply/intent/submit runs, and `/api/scrape` (~47 boards)
  plus `/api/jobs/refresh`. The audit confirmed `POST /api/scrape` returned
  **202 for the operator role** and the scrape actually ran, so one leaked
  operator session was an unbounded credit burn and an unbounded outbound
  traffic source. Two budgets, because the two classes differ by an order of
  magnitude in cost: `"action"` (per-job, `ACTION_RATE_LIMIT` default 60) and
  `"run"` (whole-pipeline, `RUN_RATE_LIMIT` default 6), both over 600s.
  Keyed on the **actor**, not the IP: keying on IP repeats the H1 mistake, where
  the budget becomes launderable by rotating source addresses and every operator
  behind one proxy shares a bucket. The actor is already resolved for
  attribution, so this costs nothing. Wired via `api.deps.action_budget(kind)`
  added *alongside* `require_token`, never replacing it — auth still runs first,
  so an anonymous caller gets 401 and spends no budget. A request that then
  fails (404, 400) **still spends** its unit, deliberately: the cost being
  limited is the handling, and a caller who can make requests error cheaply
  should not get unlimited ones.
- `LoginRequest` bounds `username` (≤64) and `password` (≤128). The ceiling is
  a resource control: `/api/auth/login` is unauthenticated, so an unbounded
  field lets one small JSON body buy a full Argon2id verify on 200 KB of
  input. `api.auth.verify_login` enforces the same bound for non-HTTP callers.
- **A password reset revokes every session for that user** (`update_password`
  deletes them in the same operation). Otherwise a stolen cookie survives the
  rotation for the rest of its 7-day TTL — which defeats the purpose of
  resetting.
- SQLite: schema DDL runs **once per (process, db path)**, not per request
  (`require_token` reads the sessions table on every call, and rebuilding the
  schema each time measured ~3.6 ms/request). `journal_mode=WAL` is set at
  init so the per-request session read is not blocked by a concurrent
  login/logout write.
- CORS: localhost `:3000/:5173/:8000/:8080` by default, override via
  `API_CORS_ORIGINS`. `allow_methods = GET, POST, PUT, PATCH, OPTIONS`.
  `allow_credentials=True` — auth is a cookie now, so a cross-origin dashboard
  configured via `API_CORS_ORIGINS` cannot authenticate without it.
  `cors_origins()` **filters** the override rather than passing it through:
  `*`, the `null` origin, non-http(s) schemes, and anything carrying a path,
  query or trailing slash are dropped with a `RuntimeWarning`, because
  Starlette matches these strings verbatim against the Origin header and dead
  entries look like they grant access. `*` is the important one — this text used
  to say `cors_origins()` "always returns an explicit list, never `*`" while
  nothing enforced it, and with `allow_credentials=True` Starlette *reflects*
  the caller's origin for a wildcard rather than rejecting it. Verified live:
  `Origin: https://evil.example` was echoed with
  `Access-Control-Allow-Credentials: true` and read `/api/jobs` using the
  operator's cookie. If every entry is rejected the localhost defaults apply,
  which is stricter than what was asked for and so fails safe.
- Static UI mount is **last** so `/api/*` and `/docs` always win.

### Session vs Token Precedence (Scenario A — Multi-Operator Attribution)

**Implemented** in `api/deps.py`: `resolve_actor()` (pure resolution),
`require_actor()` (401 if nothing resolves) and `require_submit_actor()`
(attribution **plus** the admin gate for `/submit`).

**Rule (explicit, not accidental):**

| Credential Present | Actor Recorded |
|---|---|
| Valid session cookie only | `username` (from `session_user(request)`) |
| Valid `APPLY_API_TOKEN` **or** `API_TOKEN` Bearer only | `"automation"` (fixed sentinel, `AUTOMATION_ACTOR`) |
| **Both** valid session **and** a valid Bearer token | **Session wins** → `username` |
| No credentials, but auth is not enforced at all (`open_access()` — fresh clone: no users, no `API_TOKEN`) | `"local-dev"` (`OPEN_ACCESS_ACTOR`), checked **last** |
| No credentials and auth **is** enforced | `""` → `require_actor` raises **401** |

This precedence is **intentional**: a human operator logged into the dashboard is
always attributed by username, even if an automation token is also present in the
request (a reverse proxy that injects the service token, or a test harness).
Recording `"automation"` there would blame the machine for a human's decision.

Two ordering rules that are easy to get wrong, both tested:

- `OPEN_ACCESS_ACTOR` is resolved **last**. `require_token` admits a fresh clone
  with no users configured, so failing closed on attribution would break every
  write on a first-run install — but the sentinel must never mask a real
  identity, so an authenticated username always wins.
- `"local-dev"` is deliberately **distinct** from `"automation"`. A row reading
  `local-dev` means "written while auth was off", not "written by a service
  token", and the difference is the whole point of an audit trail.

Note that `resolve_actor` accepts either Bearer secret **for attribution only**.
Authorization on the apply routes is unchanged and stricter — see below.

**Where the actor is written:** `actor TEXT` on `apply_claims`, `apply_intents`
and `apply_review_artifacts`, and `created_by` (column 13) on the Sheets APPLIED
tab. All three SQLite tables are upgraded **in place** with
`_add_column_if_missing` (`PRAGMA table_info` → conditional `ALTER`), because
SQLite has no `ADD COLUMN IF NOT EXISTS` and existing deployments hold real apply
history that must not be recreated. The Sheets column is **best-effort**: if the
header cannot be secured, attribution is dropped rather than the application row.
HTTP routes always pass the actor explicitly; only the CLI/scheduler rely on the
`AUTOMATION_ACTOR` service-layer default.

**Roles:** users carry `role` = `admin` or `operator` (`create_user.py --role`).
`require_submit_actor` enforces: if a session is present it **must** be admin —
the session wins for authorization too, matching the attribution precedence; if
there is no session, `APPLY_API_TOKEN` is accepted and attributed `"automation"`.
A service Bearer has **no role** (it is not a person), so it can never satisfy an
admin-only gate by itself. The first user created is admin and later users default
to operator, so a bootstrapping mistake cannot lock the only operator out.

**What attribution does *not* do:** it is forensics, not enforcement. The daily
apply budget (`daily_apply_caps`) is keyed on `cap_date` alone — one **global**
pool shared by every operator, with a second per-browser cap in `localStorage` —
so per-operator caps remain impossible (Scenario B, `PM.md` §5). Sheets status
changes are also unattributed: the APPLIED tab keeps no change history, so
`created_by` records who *added* a row and nothing more.

`GET /api/activity?limit=N` serves the merged, time-ordered feed. Its login
events carry client IPs and are therefore **admin-only**, decided from the
caller's role rather than a query parameter; `includes_login_events` in the
response explains why sign-in history is absent for a non-admin.

### Apply-Gated Routes Auth (unchanged, documented for clarity)

- `POST /api/apply/{fp}/intent` + `/submit` + tracker reconcile: **session OR `APPLY_API_TOKEN` only**
- `/submit` additionally requires, when the caller uses a session, that the
  session's role is `admin` (`require_submit_actor`)
- General `API_TOKEN` **never accepted** on these routes
- `SUBMIT_ENABLED=False` kill-switch still gates `/submit` (403) regardless of
  auth, and is evaluated **before** the actor dependency so the 403 ordering is
  preserved

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
4. **Errors**: a broad `except Exception` must `raise failure("<Action>", exc)`
   from `api/errors.py` — never `detail=f"...: {e}"`. The traceback goes to the
   server log under a short incident id and the caller gets the action name plus
   that id, which is greppable in `docker compose logs api`. Messages you wrote
   *for* the caller (`ValueError` from `cache.refresh`, the `DreamTierForbidden`
   family) keep going out verbatim; making those opaque hides nothing and breaks
   the dashboard. `tests/test_error_disclosure.py` walks every router's AST and
   fails the build on a new leak.
5. Tests in `tests/test_api_<group>.py` following the Phase 1 fake pattern.
6. Frontend fn in `js/api.js` + row in README endpoint table.
