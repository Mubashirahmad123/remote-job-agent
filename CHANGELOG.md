# CHANGELOG.md

## 2026-10-28 (c) — A1/A2 portability closed + B6/B7/B8/B9 backlog bundle

- **A1** — portability hunks of `40e5fc1ab` (another branch) applied by hand:
  4 bare `read_text()` → `encoding="utf-8"`
  (`test_dependency_hygiene`, `test_embedding_cache`, `test_suite_hermeticity`
  ×2; the other 5 already landed via `test_glm_client`) + url_guard report-key
  normalization `.replace("\\", "/")`. This is what actually fixed the
  persistent Windows failure
  `test_url_guard.py::test_the_scan_actually_finds_sinks` (dict-key mismatch
  `'agents\auto_applier.py'` vs `'agents/auto_applier.py'`), evidenced RED→GREEN
  with `PYTHONIOENCODING` unset.
- **A2** — all pre-existing Windows failures diagnosed first, then fixed
  honestly (no skip power): (1) the CrewAI `offline_sdk` guard fired on the
  Proactor event loop's self-pipe (stdlib `socket.socketpair()` on Windows
  connects an ephemeral 127.0.0.1 pair to itself) — the guard now exempts only
  that caller frame and forwards to the real connect, so the file is 7/7; (2)
  the mcp-metadata failure was local venv drift (crewai 1.14.7 vs lock's
  1.6.1), cured by a full re-sync to `requirements.lock.txt`; (3) the 5 docker
  heredoc failures came from `shutil.which("bash")` finding the **WSL launcher
  stub** on a host with no WSL distro — replaced with a functional
  `_usable_bash()` probe (`bash -n` must succeed), so they are justified skips
  with an exact reason here and real checks on Linux CI. Full run:
  **1140 passed / 9 skipped / 0 failed** (9 skips every one justified:
  5 docker + 3 POSIX-Bash leak-injection + 1 deliberate Lever) — the old
  env-class failure baseline is retired; see `TESTER.md`.
- **B6** — `PUT /api/cv/profile` no longer has zero coverage:
  `test_api_cv.py::TestPutCvProfile` (11 tests) pins the route contract (happy
  merged echo, empty body, 501 no-anchor, 422-not-500, whitelisted extras) and
  the REAL merge semantics of `cache.save_cv_profile` (partial merge preserves
  untouched fields; skills comma-string is coerced at the schema boundary;
  None clears; name/full_name stay in sync; never touches the LLM).
- **B7** — the tested branch: submit-claim concurrent rejection was already
  barrier-synchronized in `tests/test_apply_submit_primitives.py
  ::test_concurrent_*`; disposition + single-supervised-run sign-off recorded
  in `LIVE_SUBMIT.md` §6b (submit keeps TTL liveness — a heartbeat would only
  widen the double-submit window; revisit if multi-operator ever ships).
- **B8** — `days_ago()` is real (unit-tested in `test_audit_fixes.py`); the
  date filter is opt-in via `SCRAPER_MAX_AGE_DAYS` with unparseable dates KEPT,
  documented as deliberate config (PO #4).
- **B9** — bundle: no runs-registry watchdog by design (a recorded-only
  watchdog frees the budget for a second hung run; restart-caveat documented
  in `api/runs.py` + pinned by a wedged-run recovery test); bad-tab-400 tests
  for `/api/jobs` and `/api/apply/queue`; the screenshot endpoint now verifies
  image type by magic bytes (a text file named `.png` can no longer be served
  as `image/png` as fake operator evidence); `ApplyOut` stays unbundled after
  verifying the UI reads six fields the model would strip (PO #5, decision
  recorded in the schema docstring).
- **B5 remainder / B3 remainder** — jobDesk TABLE mirrors card-grid
  loading/error/empty states (state rows in `<tbody>`, `jobs.css`) with e2e
  guards; mid-action 401 recovery pinned (external session revocation → first
  page API call → full-page bounce to login). E2E now **88 passed / 0 failed**.

## 2026-10-28 (b) — pip-audit wave: fpdf2 + litellm upgraded, pillow re-keyed and re-accepted

The advisory databases re-keyed pillow's 2026 CVE records into PYSEC/GHSA
aliases on 2026-10-28, which both wiped ten old baseline lines and produced
eleven "new" findings at the same pin. Verified against OSV (aliases
individually checked): **10 of the 11 are the same vulnerabilities under new
IDs** (fixed only in pillow **13.0.0**), and one (`PYSEC-2026-4332`, alias
CVE-2026-112403) is genuinely additional coverage that never had a CVE record
in the baseline.

- **Upgraded (both fixes real and resolvable):**
  - `fpdf2 2.7.9 → 2.8.8` clears CVE-2026-114609/114610 (shared image loader
    dereference, "prior to 2.8.8"). Direct pin; render smoke + suite green.
  - New bounded direct pin `litellm==1.100.4` clears CVE-2026-114612 (fixed
    1.100.4+). `litellm` arrives via crawl4ai (`~=1.48` — any 1.x), so the
    pin is satisfiable without touching crawl4ai.
- **Accepted, owned in `deploy/audit-baseline.txt`:** the 11 pillow PYSEC
  entries. Pillow cannot move at all while `crawl4ai==0.3.74` requires
  `pillow~=10.4`, and crawl4ai's own fix line is five minors away — so this
  stays B10-class staged work, whose pillow wave target is now **13.0.0**
  (the 12.x target in the original plan no longer covers the 2026 set). The
  baseline header keeps the full decision trail (2026-10-16 MCP, 2026-10-27
  pillow-blocked-by-crawl4ai, 2026-10-28 re-key events).
- Pruned the 10 obsolete `pillow==10.4.0 CVE-2026-…` lines (no longer
  reproduce as CVE records; their PYSEC successors hold the risk slot, so a
  regression can still never come back silently).
- Lock recompiled (`uv pip compile --universal`), venv synced, audit runs
  **OK — 82 findings, all in the baseline, nothing new.** Full pytest counts
  recorded in `TESTER.md`.

## 2026-10-28 — audit B4 + B5 + Q5: the remaining fake/demo surfaces close

- **B4 — the three demo surfaces now disclose themselves:**
  1. *Generation catch → demo engine.* A live-generation failure previously
     left only a 3.2s toast, then `runShrinkEngine()` rendered a package
     indistinguishable from generated material, and its final toast blamed
     "the API is unreachable" even when the API had just answered 500. Now
     the failure reason is pinned PERSISTENTLY on the preview card
     (`.package-notice`, `textContent`-only) via `runShrinkEngine({reason})`,
     and the card toast reads "Demo package ready — not generated
     material." — the why outlives the toast TTL.
  2. *Drawer save.* The toast claimed "Job bookmarked in your saved list"
     — no saved list exists anywhere in this product. The button now
     performs the job card's real Tailor mechanic (`setSelectedJob`, with
     the `rja_tailor_fp` queue fallback) and says so; the button is
     relabeled "Tailor target".
  3. *Demo package download.* The old fallback downloaded
     `Apply_Package.zip` whose body was the text `PK [demo package]` — a
     fake archive. It now refuses honestly with a warn toast. Demo/missing
     cover-letter downloads keep working but carry self-labeling content
     and a disclosure toast.
- **B5 — `dashboard._trackerColumn()` was missing `needs_review`** — the
  tracker itself mapped the status, but dashboard pipeline metrics silently
  bucketed those rows under "applied". Now mapped `needs_review → review`,
  with a guard test pinning the whole mapping table against tracker parity.
- **Q5 — stale mock wording** swept: the `[store] stats fallback to mock`
  console copy, the store header's "loaders (live with mock fallback)", the
  `dataSource: 'mock'` placeholder comment, the Studio's "mockData.js
  fallback" comment, and `api/cache.py data_source()`'s "UI shows mock
  fallback" docstring. No behavior change (the pre-health `'mock'`
  placeholder value that consumers branch on stays — its comment now says
  that plainly).
- **e2e guards (+5 in smoke.test.mjs):** column-parity mapping; the
  persistent-reason failed-generation flow; drawer tailor-target effect
  with the old "bookmarked" copy banned; the honest package-download
  refusal; and "fallback to mock" strings banned from live-loader sources.
  Harness: environment.test.mjs now settles 300ms before `window.close()`
  so a pending app.js boot continuation cannot race the torn-down jsdom
  global (observed once during the day's full-suite runs as
  `document is undefined` in app.js:51; did not reproduce on a clean-HEAD
  run, nor after the settle across two further full runs).
- Final run counts are recorded in `TESTER.md`.

## 2026-10-28 — Option A: CV upload ships — the dropzone registers real tagged variants

The B2 story had the honest state but no feature: without an endpoint, picking
a CV could only say "Selected locally — no upload". This closes PM-3 by
activating the already-tested CVLibrary machinery instead of inventing a
parallel store:

- **`POST /api/cv/upload?filename=`** (`api/routers/cv.py` + new
  `api/cv_store.py`): raw-body upload — **no `python-multipart` dependency
  added**; the File bytes are the body, the safe filename a query param.
  Server cap `CV_UPLOAD_MAX_MB` (default 10, clamped 1–50), magic-byte
  checks per extension, atomic temp+`os.replace` store into `CV_DIR`
  (default `cvs/`).
- **Registration == filename:** the stored name is
  `<safe stem>__<md5[:8]>.<ext>`; domain tags keep living in the filename,
  so `tools/cv_library._extract_domain_tags` discovers the identical tags at
  scoring time, and the md5 suffix keeps re-uploads unique while aligning
  with cv_parser's hash-keyed profile cache.
- **Offline only (standing rule):** the endpoint never calls the LLM. It
  probes `extract_cv_text` and applies the stored⇒readable rule —
  unconsumable input is deleted and rejected 422 (the 2026-10-03
  poisoned-cache lesson). A fresh (<7 days, non-shell) cached profile for
  the identical content hash is reported when it already exists.
- **Auth + attribution:** `action_budget("action")` then `require_token`,
  mirroring the apply routes; ingest runs on the threadpool, never on the
  event loop.
- **Default CV untouched, PII fenced:** `my_cv.pdf` stays primary; `cvs/`
  is gitignored, mounted rw into scheduler/runner/api in docker-compose,
  and logs carry name/size/outcome only — never file contents.
- **Frontend:** `api.js` gains `uploadCv(file)` (raw File body); Resume
  Studio `uploadCvFile()` is wired into BOTH the dropzone and the +Add
  Variant picker. The server reply is the only source of any "Registered ·
  tags" claim; in flight the badge claims just "Uploading…"; on
  404/501/405/unreachable the honest local-only states remain as fallback;
  any other failure shows the server's verdict and claims nothing. The B2
  guard now pins the fallback copy explicitly; new guards cover the
  confirmed-upload contract, the wiring chain, and the outage fallback.
  `?v=` cache stamps bumped to 10.
- **Tests:** new `tests/test_cv_upload.py` (happy/tagging/dedup paths, all
  rejection codes, stale+shell probe rules, live CVLibrary listing, a
  no-heavy-imports guard; isolated — no network, no LLM, no real PDF
  engines, temp dirs only). Final Windows counts for this change are
  recorded in `TESTER.md`.

## 2026-10-28 — audit B1 + B2: the dashboard no longer claims successes it never performed

Both P0 "dashboard misleads" from the 2026-10-18 audit **survived the
2026-10-26 design rebuild** (the rebuild carried the two fakes across into the
new markup; re-verified at current HEAD before fixing). Fixed at the source of
the claim — no new feature was built for either:

- **B1 — Sync Sheets had two handlers, and the fake one always "succeeded".**
  `js/components/navigation.js` attached a second click handler to
  `#btnSyncSheets` beside the real one in `js/app.js`: an 800ms "Syncing…"
  spinner then a guaranteed "Google Sheets sync complete: ALL JOBS, TOP
  MATCHES, APPLIED up to date" toast, regardless of what the real
  `POST /api/jobs/refresh` did. The fake handler and its now-unused ref are
  removed; the real handler (outcome-keyed honest toasts) is the only wiring.
- **B2 — Resume import claimed "Uploaded & Parsed" for a file it never
  uploaded.** Picking a file in the CV Studio dropzone rendered an emerald
  "Uploaded & Parsed" badge and toasted "Extracted skills and contact profile
  cache" — while no upload endpoint exists on `main` (CV upload is deferred
  with the future `user` product, PM.md §2.1a), so nothing was uploaded,
  parsed, extracted or cached. The panel now renders "Selected locally — no
  upload" and the toast describes what actually happened, including that the
  agent still works from the configured on-disk CV (`CV_PATH`/`CV_DIR`).
  The filename also passes through `escapeHtml` before the `innerHTML` badge
  now; previously it was interpolated raw.
- **Guard tests — the first three concrete cases of the B3 demo-leak suite**
  (`tests/e2e/smoke.test.mjs`): (1) #btnSyncSheets may only be wired by
  `js/app.js` and its handler must call the live refresh (static, in header
  layout contract); (2) a Sync click must issue the refresh, show an
  outcome-keyed toast, and no "sync complete" copy may appear inside the
  retired fake handler's 800ms window (behavioral, live API); (3) a CV pick
  must render "Selected locally" and a "nothing was uploaded or parsed" toast
  (behavioral).
- **Frontend E2E: 77 passed, 0 failed** (Windows, full `npm test --prefix
  tests/e2e`).
- **Harness fix — pre-existing Windows flake, proven not caused by this diff:**
  the full-suite run showed `tests/e2e/environment.test.mjs` cleanup failures
  (EPERM removing the temp isolation dir; throwaway SQLite files apparently
  still present after `stopApi`). A clean-HEAD stash-baseline run reproduced
  the failure with the failing node **moving between tests** (101 vs 140) on
  identical code — a kill→handle-release race, not app behavior. `cleanup()`
  now waits (bounded, `waitFor`) for the throwaway DBs (`''`, `-wal`, `-shm`)
  to vanish before the strict `assertRemoved`, and retries the temp-dir
  `rmSync` on a ladder, warning instead of failing an otherwise-green test if
  a genuine lock survives. Suite green on Windows after the fix.

Still open from the audit: Q5 (store.js mock-label sweep), B4 (honest-demo
pass on the remaining demo surfaces: demo shrink fallback, drawer save toast,
package download demo mode), B5 table parity.

## 2026-10-21 (b) — review follow-up: title signals, zero-scoring, rejection rules, ranking transparency

Five findings from the second review of the same 2026-10-18 run, verified
against the live code and the **current** cached CV profile before fixing:

1. **preferred_titles no longer silently empty** — the cached profile now
   carries `['Software Engineer', 'Full Stack Developer']` (dashboard CV
   Studio edit), so the title-alignment bonus is live. Hardened anyway:
   when the list is empty, `_extract_title_keywords` derives the same role
   keywords from the CV's experience titles; a deliberately-set non-empty
   list is respected as-is.
2. **Zero-scoring incomplete descriptions fixed** — "Software Engineer" with
   no recognizable tech skills scored a hard 0 (the no-skills early return
   bypassed even the capped path). It now scores capped title/seniority
   signal (reason: "No recognizable tech skills; title signals only") and
   lands in the maybe range instead of the void.
3. **`\bintegration engineer\b` removed from TITLE_ONLY_PATTERNS** — it
   rejected "Backend Integration Engineer (APIs)" before scoring. The
   enterprise platforms it guarded (Mulesoft, NetSuite, D365, SAP, ERP, ETL)
   keep their own tool patterns, so "Mulesoft Integration Engineer" is still
   rejected.
4. **Match quality vs ranking separated** — `rank_score` is now stored on
   each job alongside `match_score` (CV fit, the gate) and `ranking_score`
   (match + freshness), with the three documented at the ranking step; the
   top-3 log line prints "Match: X | Rank: Y".
5. **Per-job score breakdown** — `score()` returns a `breakdown` dict
   (core_coverage, core_credit, exact/tooling/title/seniority bonuses,
   cap_applied) so any explanation can be checked against the numbers that
   produced it. Verified: with today's populated preferred_titles the
   title bonus IS active (the audit-time "bonus always zero" claim was true
   only for the empty-titles snapshot).

Deliberately unchanged, per the review's own recommendation: no
sentence-transformers/faiss install, no scoring-weight changes — the C1
decision from the 2026-10-21 (a) entry already matches it.

## 2026-10-21 (a) — audit remediation: matcher, dedup, sheets backoff, board breaker, PM quick wins

Implementation pass over `AUDIT.md` (2026-10-18) and `PM.md` §1a quick wins,
done one finding at a time. Regression coverage in `tests/test_audit_fixes.py`.

### Matching engine (C1, C2, C4, PM-1, PM-4)

- **C2 — coverage inversion fixed** (`tools/cv_matcher.py`): the main term is
  now a concave (sqrt) credit instead of linear coverage. A 3/5 core match —
  the audit's failing case — moved from ~55 (LOW) to ~79 (PASS); strict
  ordering preserved. Genuine zero-overlap stays a hard 0. Postings with **no
  recognizable core stack** (stub text) no longer die at 0: title/tooling
  signals score, capped by `NO_CORE_STACK_CEILING = 55` so they land in the
  maybe range for triage instead of passing unverified.
- **C1 — threshold decision documented, not silently re-tuned**: `MIN_SCORE`
  stays 70 in both modes; the recalibration IS the C2/C3 fixes (re-enabling
  sentence-transformers/faiss was rejected as a heavy torch dependency). The
  active mode + gate are now printed every run so future changes are
  deliberate.
- **C4 — LOW MATCH lines print the computed `match_reason`** (was computed,
  stored, and hidden — the exact change that would have exposed C3
  immediately).
- **PM-4 — body rejection patterns require a role noun**: bare
  `\bcybersecurity\b` became `\bcybersecurity (engineer|analyst|...)`. The
  BeyondTrust Cloud Engineer collateral case is fixed; titles keep the bare
  pattern.
- **PM-1 — tier bars are env-configurable** (`TOP_MATCH_THRESHOLD`,
  `GOOD_MATCH_THRESHOLD` following `MIN_MATCH_SCORE`) so the sheet routing
  and the scorer gate can never silently disagree.

### Funnel integrity (Bugs 1–4, Bug 6 input quality)

- **Bug 1 — missing-URL drops are counted** (`missing_url` in stats + run
  log); the audit's vanishing 4 jobs can no longer disappear silently.
- **Bug 2 — cross-board dedup pass** keyed on `(title, company)` alone
  (`tools/deduplicator.py: title_company_key`); same-opening-different-URL
  duplicates collapse, `cross_board_dupes` counted.
- **Bug 3 — freshness day 7 now 0** (was +2 via the `<= 7` branch);
  **Bug 4 — future-dated postings get no boost** (one day ahead = timezone
  skew → today's boost; further ahead → 0).
- **C3 — all nine stub summaries replaced with real card text**
  (`agents/scrapper.py`): `_card_description()` extracts per-board
  description nodes with a card-text fallback, `_stack_from()` derives
  tech_stack from title **+ body** (RSS parsers included). Stub strings
  ("Himalayas remote listing", ...) are gone — they scored such jobs 0
  unconditionally and defeated the country filter.

### Reliability (Bug 5, §6)

- **Bug 5 — Sheets writes back off and isolate**: `_sheets_backoff()` retries
  429/5xx with 1/2/4s + jitter; each phase (ALL JOBS append → tier appends →
  STATS → cleanup → formatting) fails independently instead of one exception
  skipping STATS + cleanup; STATS is written every run; formatting is skipped
  when nothing structural changed (the observed 429 source).
- **§6 — board circuit breaker**: after 3 consecutive failed runs a board is
  skipped for 5 runs (`cache/board_health.json`, gitignored), with recovery
  auto-reset and the skip surfaced in the tracker. TimesJobs dropped
  (fail-closed TLS + out of region; burned 3 retries every run).
- **§6 — cached gspread client**: one authorized client per spreadsheet key
  for the process lifetime (`tools/sheet_writer.py`), ending the repeated
  "Connected to spreadsheet" handshakes and token refreshes per run.
- **§6 — favicon 204**: browsers auto-request `/favicon.ico`; the static
  mount 404ed it into the logs every page load. Now a deliberate 204.
- **§6 — yield-per-LLM-call accounting**: `generate_with_fallback` counts
  every provider ATTEMPT (a Gemini 503 + Groq fallback = 2 attempts — the
  audit's exact cost scenario); `scrape_all` resets at run start and records
  attempts + provider split into the YieldTracker after the Crawl4AI pass
  (`tracker.llm()`, a new `llm` jobs/attempts column in the board table and
  the JSONL log). The yield-floor decision stays MANUAL — one provider
  outage must not auto-disable a board.
- **C5 — CV selection no longer double-scores**: `CVLibrary.pick_best_scored`
  returns the winning result; curator reuses it. The misleading
  `Best CV … (score 0)` log line only prints with >1 CV registered.
- **B8 — `days_ago()` is real again** and the age filter is deliberate
  config: `SCRAPER_MAX_AGE_DAYS > 0` enables it in `scrape_all` (default 0 =
  the documented bypass, PO decision #4).

### §6 fleet fixes

- **TheMuse fixed, not dropped**: the old URL's slice (`category=Computer
  and IT` + `category=Software Engineer`) landed on IT-support pages —
  20/20 correctly rejected, board yielded 0 every run. New URL verified
  live (`category=Software Engineering` + full-name `level=` values; both
  filters honored, 93538 → 56665). **Root cause of the 0 was actually
  `_accept_job`**: it stuffed the full HTML description into the
  `tech_stack` check, so `NON_DEV_FILTER` matched single tool/role words
  anywhere in the body — "Software Engineer, Hardware Test & Automation"
  died because its own text says "hardware". Fixed for ALL API parsers
  (title gate unchanged; body feeds only the role-word check; downstream
  `BODY_REJECTION_PATTERNS` still guards body text). The Muse now yields
  ~4-5 dev jobs per page of 20.
- **Dropped with evidence**: WorkInStartups (405 on GET for every
  non-browser client, verified via the scraper and an independent fetch),
  Naukri (bot wall + India-focused, outside ALLOWED_COUNTRY_TERMS), and
  FounditIN (same naukri.com endpoint).

### PM quick wins (Q1–Q8)

- **Q1 (P0)**: hardcoded `SESSION_COOKIE_SECURE=true` removed from
  `docker-compose.yml` — bare-IP HTTP login works again via the
  `X-Forwarded-Proto` auto-detect; forced Secure broke the documented first
  deployment.
- **Q2**: `_warn_multi_worker()` in `create_app` shouts when
  `WEB_CONCURRENCY > 1` (per-process cache/registry/limiter consequences).
- **Q3**: `.env.example` synced — added `SEMANTIC_WEIGHT`, `KEYWORD_WEIGHT`,
  `AUTO_APPLY_DAILY_CAP`, `SCRAPER_TIMEOUT`, `SUBMIT_ARTIFACT_DIR`,
  `SUBMIT_HEADLESS`, `SNAPSHOT_FILE`, `PW_DIAG_LINES`,
  `JOBSPY_COUNTRY_INDEED/LOCATION/PROXIES`, plus the new tier/breaker/date
  knobs; obsolete `ALLOWED_COUNTRIES` removed; `SUBMIT_ENABLED`/`SUBMIT_DRY_RUN`
  absence documented (armed only via `LIVE_SUBMIT.md`).
- **Q4**: `api/deps.py` token compares unified on `_bearer_matches`
  (`hmac.compare_digest`) at both call sites.
- **Q6**: scrape-run errors carry the `api/errors.py` incident-id pattern
  (traceback → server log, action + id → run record) instead of raw exception
  text; `test_worker_error_recorded` pins the new contract.
- **Q7**: `api/review_worker.py` thread start catches `Exception`, not
  `BaseException` (interpreter exits surfaced as KeyError → 500).
- **Q8**: `LIVE_SUBMIT.md` 90s-timeout entry reconciled — repair status
  documented, live rerun explicitly still open (A5).

Not done this pass (by decision, not omission): PM-2 dashboard UI (backend
`MAYBE_MATCHES` tab shipped opt-in; jobDesk view is B-phase frontend work),
PM-3 CV variant registration (needs real tagged CV files from the operator),
PM-5 manual sheet review, Q5 frontend sweep, and the B3 demo-leak e2e suite.


## 2026-10-17 — fix rate-limit Retry-After boundary overflow (Windows flake)

- The sliding-window limiter computed `retry_after` as `int(remaining) + 1`.
  On Windows, `time.monotonic()` is `GetTickCount64()` (~15.6ms resolution;
  measured here: 199,992 of 200,000 consecutive reads returned an identical
  value), so the budget hits and the denial can share one tick, the remaining
  time is exactly the whole window, and the formula reported window+1 —
  `retry_after` 601 for a 600-second window. This is the "601 seconds versus a
  600-second assertion" failure recorded in the Windows full-suite run in
  `TESTER.md`; the ns-resolution Linux CI clock cannot reproduce it.
- Replace it with the house pattern already used in `fill_claims.py` and
  `apply_claims.py`: `max(1, math.ceil(remaining))`, keeping `retry_after`
  inside `[1, window]` on any clock. The invariant is documented on `Decision`.
- Two regression tests pin both boundaries: a same-tick denial must report the
  window itself (failed with 601 against the old formula, RED-first) and a
  0.5-second remainder must round up to 1. Rate-limit/auth/proxy/timing
  suites: **85 passed**.
- No requirements, lock or submit changes; `SUBMIT_ENABLED` stays false; no
  deployment. The other Windows environment failures in `TESTER.md` remain
  open.

## 2026-10-17 — survive list-typed LLM extraction fields; serve /health liveness alias

- A dashboard scrape died after scraping completed with
  `AttributeError: 'list' object has no attribute 'strip'`: the Gemini answer to
  `extract_jobs_from_markdown` carried `"tech_stack": ["Python", "Docker"]`-style
  arrays, and `is_valid_dev_job()` called `.strip()` on the list at the end of
  `scrape_all()`. The curator's sanitizer previously converted only `None` → `""`,
  so nothing in the pipeline coerced non-string scalars.
- Two-layer fix. `agents/gemini_tools.py` coerces every extracted field to text at
  the LLM boundary (`_coerce_text`/`_normalize_extracted_job`: lists joined with
  `", "`, dict values flattened, scalars stringified, non-dict rows dropped), and
  `agents/curator.py::sanitize_string_fields` now flattens None/list/tuple/scalar
  values in place before dedup, CV matching or Sheets writing touch a raw job.
  The documented 8-field extraction schema is enforced; rogue keys are dropped.
- `tests/test_markdown_extraction.py`: 16 cases — coercion shapes, schema
  normalization, monkeypatched LLM responses (fenced, non-array, empty markdown)
  and the exact crash path through `is_valid_dev_job` + `job_fingerprint`.
- `GET /health` now serves the identical `{"status":"ok"}` payload as
  `GET /api/health/live` (same ungated `liveness` router, same deliberately-empty
  disclosure). An external poller — no repo code, current or historical, calls
  bare `/health`; the dashboard has always used `/api/health` — was logging a 404
  every few seconds. Live-verified against a running uvicorn: `/health` 200,
  `/api/health/live` 200, `/api/health` still 401. Pinned by
  `test_health_alias_serves_open_liveness`; BACKEND/README/PRODUCTION updated.
- Two harness fixes. `tests/test_glm_client.py` source-reading tests now pass
  `encoding="utf-8"` — the platform-default cp1252 decode crashed on the source
  files' non-ASCII bytes on Windows, verified failing on stashed clean HEAD
  (CI's Linux default is UTF-8, so it passed there). `test_api_phase1.py`'s
  `test_no_heavy_imports_at_startup` asserts on modules *added* by the request
  instead of absolute `sys.modules` absence, which any test file importing
  `agents.curator` at collection time would break by file order.
- Touched suites: 164 passed, 7 skipped; `test_api_phase1.py` 21 passed. The full
  Windows run reported 7 failed, 5 errors — identical on stashed clean HEAD and
  all environment-specific (Docker CI parsing, CrewAI SDK, timing); itemized in
  `TESTER.md`. No deployment, no live Sheets writes beyond an operator-initiated
  scrape, no dependency changes.

## 2026-10-16 — fix Greenhouse confirmation discovery and visible-copy verification

- Supersede the 2026-10-03 Democorp recon result below: the original extractor
  missed metadata in Greenhouse's bare `window.__remixContext` bootstrap/runtime
  state. The 2026-10-16 read-only probe found `/example/jobs/83446/confirmation`
  and the job's HTML-formatted `confirmation_message`. Greenhouse removes the
  bootstrap script from the DOM shortly after startup, but runtime loader data
  was still available; immediate and 10-second extractions agreed.
- `_greenhouse_confirmation_data` now reads the Remix runtime and script
  fallback. `verify_greenhouse_confirmation` strips markup, unescapes entities,
  and collapses whitespace on expected and actual text; it retains exact path
  and case-sensitive full-message containment, and rejects empty normalized
  copy. Fixture regressions were mutation-checked: both new cases failed
  before the verifier change and passed after it.
- Read-only recon now finds confirmation metadata, the submit button and no
  unhandled required fields; it continues to detect reCAPTCHA. No form fill,
  dry run, intent, submit click, or submission occurred. Post-submit matching
  remains unobserved; `SUBMIT_ENABLED` remains false.
- Targeted tests: **101 passed, 1 skipped**. The full Windows run reported
  **22 failed, 1028 passed, 4 skipped, 1 teardown error**; environment failures
  are itemized in `TESTER.md`. The full-suite gate is not green on this Windows
  environment. No commit, push, or live-submit claim is made.

## 2026-10-16 — remediate PR #31 CI and MCP security finding

- Fix CVE-2026-59951 with MCP 1.30.0, not an audit exception or metadata override.
  Deliberately roll CrewAI back from 1.14.7 to 1.6.1, whose declared MCP bounds
  permit the fix. Real SDK tests build the production factory, run an offline
  kickoff and construct configured provider adapters without network access.
- Retain the existing JSON-repair advisory on required 0.25.2 (previously 0.25.3);
  document that risk migration explicitly. Remove the three fixed MCP baseline
  entries. Audit passes with 43 known findings; it does not mean no vulnerabilities.
- Install the same universal lock in API/dashboard CI and Docker, with a static
  regression guard. Run SDK compatibility tests in both native image jobs.
- Surface escaped/bounded failure details in GitHub check annotations without
  changing failing exit codes. Fix two fake-browser scheduling assumptions in
  handoff tests; the original inaccessible pytest/frontend tracebacks remain
  unconfirmed, not retroactively attributed to these assumptions.
- Fresh local locked environment: 168 compatible packages; **1042 Python passed,
  8 skipped, 32 warnings; 68 frontend passed**. See
  `deploy/CI_FAILURE_REMEDIATION.md` for evidence, tradeoffs and current CI scope.
- No merge, deployment, live provider/ATS, CAPTCHA bypass or submission.

## 2026-10-15 — preserve slow review results instead of discarding them at 90s

- Replace the screenshot-less timeout stub with a bounded foreground wait
  (`APPLY_FILL_TIMEOUT`, default 180s, integer clamp 1–600) plus a durable
  SQLite review-run handoff. A slow request returns `review_pending`/run ID;
  authenticated status polling retrieves its real terminal result.
- Save late screenshot/confirmation/readback/material/actor evidence; only
  advertise the image URL after persistence. Queue and Regenerate wait/poll
  without repeating POST, and report status-read failures honestly.
- Heartbeat claims periodically across foreground timeout, retain duplicate
  blocking, fence package/artifact writes by ownership and reject stale run IDs.
  A 30-minute watchdog fences an over-deadline worker; it does not forcibly kill
  a Python/browser thread. New attempts invalidate old review evidence.
- Make concurrent screenshot filenames UUID-unique and log stage elapsed times.
  Exact live-board slowness and discarded metadata remain unconfirmed; no
  retroactive recovery by globbing screenshots or new submit permission.
- Add 20 real-thread/SQLite/route cases with fake browser/material boundaries
  plus 4 dashboard polling checks over a fake transport. Full local results:
  **1027 Python passed, 8 skipped, 32 warnings; 68 frontend passed**.
- Update docs/config. This repair is prepared for PR review, not deployed or
  live-Chrome/native-image verified. Earlier successful Docker CI applies to its
  recorded commit. Submit remains disabled; no live ATS/provider work performed.

## 2026-10-15 — native locked Docker CI executed and reviewed

- Commit/push the completed session work to `arena/393bb940-remote-job-agent`;
  no PR merge or deployment. CI run 38743655019 at code commit `0971322` passed
  all five jobs, including native x86-64 and ARM64 Docker builds/runtime checks.
- Both images passed active lock-pin/dependency checks, non-root API lifespan/
  liveness and real Chromium launch, selected API/auth suites and filesystem
  leak checks. Full API, frontend E2E and baseline audit jobs also passed.
- Fix review finding: image inventory no longer masks export/listing failures
  with `|| true`, and rejects empty output; cleanup is trapped. Three fake-tool
  failure-injection guards pass. Local preflight: 63 passed; full locked Linux
  pytest: 1007 passed, 8 skipped, 32 warnings. Prior local frontend: 64 passed.
- Record exact run/job links and reviewed step conclusions in
  `deploy/DOCKER_CI_VERIFICATION.md`. Raw-log archive download was blocked by the
  sandbox host allowlist; no raw CI counts or image digests are claimed.
- Review GitHub notice: `ubuntu-latest` begins migrating to Ubuntu 26 on
  2026-10-19. This is not a failure; pin/retest deliberately in a follow-up.
- Mark native CI complete, not Oracle deployment, dashboard-browser verification,
  CV upload or submit verification. Baseline vulnerabilities and mutable image/
  uv tags remain; no requirements, lock pins or audit baseline were changed.

## 2026-10-15 — record user-reported Democorp live fill-only smoke

- Record the supplied real-Chrome/Playwright report and screenshot: visible
  contact-field filling and resume/cover-letter attachment presence on the
  public Greenhouse demo. Do not copy personal field values or the image to Git.
- Keep the result partial: the API returned its 90-second fill timeout; a PNG
  reportedly existed, but the API screenshot record was missing and its URL
  returned 404. Exact slow step/root cause remains unconfirmed; add a diagnostic/
  artifact-persistence follow-up, not a timeout-only fix or success claim.
- Distinguish this from full-path submit dry-run, submission, or dashboard
  browser coverage. No intent/submit calls, submit click or captcha bypass
  reported; external AI provider keys were disabled for the run.
- Update PM, live run log, tester/backend/frontend guidance and README. This
  records user-supplied evidence, not an independently repeated live run. No
  runtime code changes, new test runs, submit enablement, push or merge.

## 2026-10-15 — retire stale E2E `.env`/auth warning with targeted evidence

- Add 6 environment checks over plain-token and blank/trailing-comment dummy
  `.env` files in disposable source copies. A synthetic cached CV guarantees
  the real CV parser/dotenv import runs, rather than a missing-CV early exit.
- Reproduce the documented failure with missing auth pins: stats 200 → cached
  CV profile 200 → stats 401. Confirm both dummy auth tokens load at import.
- Prove the existing empty-string pins prevent that failure under real uvicorn,
  inherited shell tokens and real dashboard boot. Login mode still rejects
  anonymous/dummy-token requests and accepts its isolated session. Apply-token
  probes fail authentication without creating intents; submit stays disarmed.
- Retire the pending warning/checklist item; no production auth/dotenv logic
  needed changing. Keep the empty-vs-missing rationale in the harness.
- Allow the harness to launch copied source with an explicit environment while
  keeping safety pins authoritative. Resolve relative interpreter paths against
  the real repo so disposable working directories cannot break RJA_PYTHON.
- Wire environment tests into canonical npm/shell/CI execution and guard the
  suite list. Use source-only copies, no real .env/CVs/credentials, and verify
  temporary DB cleanup. Negative controls report statuses/booleans only.
- Local Linux verification: **6 targeted checks passed; 64 total frontend E2E
  passed; 1004 pytest passed, 8 skipped, 32 warnings**. Native Windows/browser,
  Docker/ARM and deployment checks remain pending. No push or merge.

## 2026-10-15 — tracker/Kanban interaction coverage and persistence fixes

- Add 22 jsdom interactions over real dashboard scripts, tracker routes, cache
  resolution and tracker services, using an opt-in fake-Sheets subprocess. Cover
  transitions, all review/archive mappings, counts, notes preservation, reload,
  encoded URL keys, double clicks, HTTP/network/write/refresh failures, escaping
  and manual-add validation/save/retry. No personal Sheet or CV access.
- Add 22 Python HTTP/runner contracts for status whitelist/normalization, URL and
  fingerprint keys, notes, auth, errors, test-control isolation and CI wiring.
- First observe red regressions: a failed write moves a card locally, and a
  URL-only row appears moved while the server still has its old status.
- Remove local-success fallback; serialize each card's PATCH + refresh with a
  visible pending state; stop resending old append-only notes. Accept full URL
  keys with a path converter without changing auth or submit-reconciliation gates.
- Make tracker refresh errors opt-in throwable. Tracker Sync reports failures;
  confirmed writes followed by failed GETs report saved-but-not-refreshed. Close
  a successfully saved manual modal even when refresh fails to avoid resubmission.
- Run smoke + tracker from npm, shell runner and frontend CI; wait for fixture
  process exit before temporary DB cleanup. Test submit switches stay disarmed.
- Local locked Linux verification: **1004 pytest passed, 8 skipped, 32 warnings;
  58 frontend E2E passed**. Seven skips need optional FAISS; Lever confirmation
  copy remains deferred. `uv pip check` passed. Real-browser/live-Sheets,
  Docker/native ARM and deployment validation remain pending. No push or merge;
  submit stays disabled and CV upload stays deferred.

## 2026-10-15 — reconcile completion and remaining-work documentation

- Make `PM.md` §1 the current checked/unchecked status list. Mark semantic
  scoring and Docker lock installation implemented, while keeping native image/
  ARM checks, real-browser coverage and deployment verification pending.
- Record Windows fixes as reported complete on `phase 3`, not integrated here;
  distinguish the investigated flake from a confirmed root-cause fix.
- Keep form-structure snapshot comparison explicitly unchecked; typed-value
  readback/repair is a different, completed protection. Live submit stays gated.
- Remove duplicate/outdated top-level status entries and mock script guidance;
  reconcile test counts and label old submit specs/`CODEX_TASK.md` historical.
- Keep the documented tokenized-`.env` E2E caveat as a revalidation task rather
  than claiming a current failure or a fix without scenario-specific evidence.
- Documentation only; no new code, tests, native runtime validation or merge.

## 2026-10-15 — Docker installs the universal dependency lock

- Copy/install `requirements.lock.txt` before copying application source, and run
  `uv pip check --system`. No dependency pins or vulnerability baseline changed.
- Configure native x86-64/ARM64 Docker CI builds with active-pin checks, non-root
  API startup, Chromium launch, API/auth suites and existing image-leak checks.
  No image is pushed by these jobs. Native CI results are pending.
- Add offline Docker/CI regression guards and native ARM VM verification steps.
- Local fresh locked x86-64 environment: 179 active pins match; dependency checks
  pass; **982 pytest passed, 8 skipped; 36 frontend E2E passed**. Seven skips
  need optional FAISS (outside the lock); Lever confirmation-copy is deferred.
- `uv` dry-run dependency resolution passed for Linux x86-64 and ARM64. Docker is
  unavailable in the sandbox: no image build, Chromium launch inside an image or
  native ARM runtime check was performed. Do not label ARM deployment verified.
- Locking packages does not clear advisories or pin base/uv image digests and
  artifact hashes. Submit behavior, credentials and personal CV scope unchanged.

## 2026-10-15 — selected-CV semantic scoring and validated caches

- Replace primary-only semantic scoring with the embeddings for the CV selected
  by keyword matching; retain single-CV fallback. CV selection remains keyword-based.
- Add lazy per-file managed JSON caches with CV-content SHA-256, model and schema
  validation, atomic writes and in-run memoization. Source edits invalidate library
  profiles/picks and keyword matchers too. No cross-CV fallback on errors.
- Keep full keyword weight when semantics cannot run; distinguish unavailable
  from a genuine computed zero. Only compared sections contribute weight.
- Keep the legacy JSON loader/export interface for compatibility; curation does
  not trust bare-vector exports without source/model provenance.
- Add offline regression tests, including real FAISS calculations and DOCX text
  extraction using a deterministic encoder, not a downloaded transformer model.
- No frontend/API contract, upload, tenancy, dependency manifest or submit-safety
  changes. Existing saved scores are not rewritten.
- Verification in this working branch: **976 pytest passed, 2 skipped**;
  **36 frontend E2E passed**. The 52 new tests ran with FAISS and python-docx
  available; sentence-transformer model downloads/quality were not tested.

## 2026-10-15 — defer CV upload to the future user product (docs only)

- Supersede the short-term Phase 2.1a upload plan: personal `main` remains
  software-development-focused with its existing on-disk CV/Sheets configuration.
- Group CV upload with profession-aware matching, database-backed user ownership,
  user-supplied provider/Sheets credentials and frontend onboarding on a future
  `user` branch. No target date or planned merge of that redesign into `main`.
- Add `USER_PRODUCT.md` as the canonical deferred scope and design/release gates;
  align PM, architecture, backend, frontend, production and README guidance.
- Keep the cache seam independent and low priority. Existing Scenario A
  attribution and submit safety gates are unchanged.
- No code, DB migration, upload, branch creation or live submission performed.

## 2026-10-09 — resume CV fidelity + the PR #28 CI root cause (PR #29)

Two related things: the resume tailoring work landed on main, and the CI
failure that blocked its first merge attempt was traced to a test-harness
mistake rather than a product bug. **PR #28 could not merge** — its branch
was cut from a stale repo snapshot with no shared history, so a merge would
have reverted the PR #26 security work; PR #29 re-applied only its intended
8-file diff onto current main.

### Resume tailoring is now grounded in the actual CV

- **GROUNDING RULES + PROJECTS instruction** in the prompt (`resume_generator._build_smart_prompt`):
  only employers, titles, dates, education, projects and metrics that appear
  in the CV/profile are allowed; inventing or substituting any of them is
  prohibited. `include ALL of the candidate's ACTUAL projects` — a prior
  head-only truncation erased the PROJECTS section from the prompt, and the
  LLM invented replacements; truncation now keeps head **and** tail.
- **`_strip_llm_footer`** — `Keywords:` lines and stray `---` rules the models
  append after Education are removed before validation/rendering (the PDF
  engine draws its own section rules).
- **`_filter_cv_data`** — the operator-rejected pre-web history (the "Yarikul
  Infotech" internship and the "CRM Application"/"customer relationship
  management" project) is dropped from the profile and raw CV text **before
  the prompt is built**, for Shopify/frontend-targeted tailoring. Filtering
  happens programmatically, so it does not depend on the model obeying.
- **1-page pass sizes retuned** for the Arial/Liberation font (narrower than
  DejaVu, so pass 1 affords 10pt body); `---` lines are never rendered as
  literal text. `tools/font_utils.py` gained Arial/Liberation resolution +
  typographic Unicode normalization.
- **`out=` param** — `generate_resume_for_job` surfaces the generated
  markdown; `api/materials.py` threads it through and `POST /api/resume/{fp}`
  now returns `resume_markdown` alongside `filename`.
- **Live markdown preview** — Resume Studio renders the *actual* generated
  resume markdown in the preview pane (escaped first, so LLM output cannot
  inject HTML), in a taller scrollable pane; the stub demo sheet renders only
  when no real markdown exists.

### The PR #28 CI failure: a sys.modules foot-gun, not a resume bug

The three `TestGenerateOutParam` failures (real PDFs with timestamped
names instead of the mocked `r.pdf`, real Gemini calls in captured stdout)
looked like a filename-format change. They were not. An earlier "fix" for
`test_no_heavy_imports` did a bare `sys.modules.pop("tools.resume_generator")`
before asserting — which **permanently destroyed the module object** the rest
of the suite held references to. The next `import tools.resume_generator`
re-executed the file into a *fresh* module, so the tests' monkeypatches of
`generate_tailored_resume` / `save_resume_pdf` silently missed the functions
under test and the real pipeline ran. The loosened-filename-assertion variant
of that "fix" made the wrong behavior pass; both were discarded.

The merged fix (8961c62c3): the hygiene test pops the module **for the
duration of the request and restores the original object in `finally`**, and
`TestGenerateOutParam` imports and calls through the *same in-test module
reference* (`rg.generate_resume_for_job`), so patch and call can never
diverge. The strict `r.pdf` assertions are unchanged — the endpoints still
must not import the heavy module, and the rest of the suite keeps its module
identity.

### Known local gap (not CI)

The full suite is green in CI (Linux). On Windows, 13 `test_glm_client.py`
tests plus three other source-scanning tests fail on the cp1252 default
codec: `Path.read_text()` without `encoding=` reads UTF-8 sources as
cp1252. Fix scoped, not yet landed — see `PM.md` §3 Backlog.

## 2026-10-08 — actor attribution, CI, and a dependency conflict that had broken `docker build`

Three separate things landed together because the third was found while doing
the first two: Scenario A attribution was implemented, CI was created to run the
suites that existed but nobody executed, and writing that CI surfaced the reason
the project's Docker image could not be built at all.

**515 pytest tests + 29 e2e tests pass.**

### Scenario A — multi-operator attribution (`PM.md` §5, was "implementation not started")

- **`api/deps.py` gained `resolve_actor()` / `require_actor()` /
  `require_submit_actor()`.** Every write is now attributed: a session resolves
  to its `username`, a service Bearer to `"automation"`, and — checked *last*, so
  it can never mask a real identity — an unauthenticated request in open-access
  mode to `"local-dev"`. Nothing resolving at all is a `401`, never an
  unattributed row. When both a session and a token are present the **session
  wins**, for authorization as well as attribution; that was previously an
  accident of check order in `apply_access_ok()` and is now a documented, tested
  rule.
- **`actor TEXT` added to `apply_claims`, `apply_intents` and
  `apply_review_artifacts`**, plus `created_by` as column 13 of the Sheets
  APPLIED tab. All three SQLite tables upgrade **in place** via
  `_add_column_if_missing` (`PRAGMA table_info` → conditional `ALTER`) because
  SQLite has no `ADD COLUMN IF NOT EXISTS` and live deployments hold real apply
  history that must not be recreated; a test starts from the *oldest* artifact
  schema and asserts every later column arrives and the row survives. Rows
  predating attribution keep `actor = NULL` — the migration never invents one.
  The Sheets column is **best-effort**: if the header cannot be secured,
  attribution is dropped rather than the application row.
- **Roles (`admin` / `operator`)** on the users table, settable via
  `create_user.py --role`. The **first** user created is admin and later ones
  default to operator, so a bootstrapping mistake cannot lock the only operator
  out of the admin-only submit path.
- **`require_submit_actor`, not `require_admin_actor`.** The first
  implementation 403'd the documented server-to-server submit path: a service
  Bearer has *no role* (it is not a person), so demanding `admin` rejected it.
  Now a session must be admin, and with no session `APPLY_API_TOKEN` is accepted
  as `"automation"`. Kept as a separate dependency from the kill-switch so
  `SUBMIT_ENABLED=false` → `403` is still evaluated first.
- **`GET /api/activity?limit=N`** — merged, time-ordered, actor-attributed feed.
  Its login events carry client IPs and are therefore **admin-only**, decided
  from the caller's role rather than a query parameter; `includes_login_events`
  says why sign-in history is absent for a non-admin.
- **`GET /api/health/live`** — unauthenticated, exactly `{"status":"ok"}`,
  excluded from the OpenAPI schema, in its own router in `_OPEN_ROUTERS`.
  Gating `/api/health` behind login broke container/orchestrator probes, which
  have no session and would have restarted a healthy container in a loop.
  Un-gating the whole health router was rejected: it reports build/config/state.
- **Fixed: login audit events were always empty.** `api/activity.py` read
  `login_events` through `apply_state.connect()` — the wrong database. The
  auth tables live in `AUTH_DB_PATH` (defaulting to the apply-state file, but
  separable), and the tolerant `_rows` helper swallows `sqlite3.Error` by
  design, so the wrong-DB query returned `[]` silently instead of failing. It
  now opens `api.auth.connect()` explicitly.
- **Recorded as limits, not silently omitted:** attribution is *forensics, not
  enforcement*. `daily_apply_caps` is keyed on `cap_date` alone, so the apply
  budget is one global pool shared by every operator (with a second, per-browser
  cap in `localStorage`), and Sheets status changes are unattributed because the
  APPLIED tab keeps no change history. Both are documented in `PM.md` §5 and
  `ARCHITECTURE.md` §4 as Scenario B work.

### CI — `.github/workflows/ci.yml` (new)

Three jobs on every push and PR, with nothing allowed to fail: the full pytest
suite, the Node e2e suite against a real uvicorn, and a `docker build`. This
exists because the repo had 500+ passing tests and 29 passing e2e tests with
nothing running them, and because PR #25 merged documentation for
`require_actor` before any of it was implemented.

- **Lock-file drift check** that fails on a missing package *or* a disagreeing
  exact pin. Verified in both directions: green on the regenerated lock, and it
  reproduces the old failure (`fastapi`, `pytest` absent; `uvicorn` pinned to
  `0.53.0` against a `0.49.0` requirement).
- **Image-leak check** asserting no `.env`, `keys.json`, `*.db`, `.venv/` or
  `node_modules/` is baked into a layer. The container filesystem is listed
  once — the earlier per-pattern loop re-streamed the whole export per pattern.
- The ignore list and `continue-on-error` step were **removed** after
  establishing that all 515 tests are offline unit tests performing no HTTP
  calls and needing no Playwright binaries. Their only failures were missing
  dependencies in a minimal environment, so tolerating them would have hidden
  real regressions in the apply and scraper-timeout logic.

### Fixed: `requirements.txt` was unsatisfiable, so the image could not build

- **`zhipuai` removed.** It pins `pyjwt>=2.8.0,<2.9.0`; `crewai==1.14.7` pins
  `pyjwt>=2.13.0,<3`. The ranges do not intersect, so `pip install -r
  requirements.txt` died with `ResolutionImpossible` and `docker build` failed at
  the install step — on every commit, with nothing reporting it. The 143 KB
  UTF-16 build log that recorded it had been committed in PR #25 as
  `docker-build-error.txt`; it is deleted by this change, and the error is quoted
  here instead — a binary-encoded log cannot be diffed or reviewed, `git clone`
  put it on every production VM, and the failure is now prevented structurally by
  CI rather than merely documented. Every `zhipuai` 2.1.x release carries the same
  pin and the last shipped 2025-08-25, so waiting for upstream was not a fix.
- **New `tools/glm_client.py`** replaces the SDK for GLM (fallback rung 3),
  calling Zhipu's OpenAI-compatible endpoint over `requests` — already a
  dependency, and already how the Groq and Mistral rungs work. The SDK's
  non-obvious auth is reproduced exactly: it does *not* send the raw key, it
  splits `id.secret` and signs an HS256 JWT whose `exp`/`timestamp` are in
  **milliseconds**, with a non-standard `sign_type` header and `typ` sorted last
  because pyjwt merges its default after the caller's headers.
  `tests/test_glm_client.py` pins this with **golden vectors captured from
  `zhipuai==2.1.5.20250825`**, so equivalence is asserted without the SDK
  installed; the resulting token is byte-identical, all three segments included.
  Single-token keys (no dot) are passed through verbatim, matching the SDK with
  its token cache disabled.
- **`requirements.lock.txt` regenerated** — and it was worse than "missing
  argon2-cffi". It had been compiled on **Windows** with no environment markers,
  so it shipped an unmarked `pywin32==312` that cannot install on the Linux
  deployment VM, omitted `fastapi` and `pytest` entirely, and disagreed with
  `requirements.txt` on `uvicorn`. Rebuilt with
  `uv pip compile … --universal`, which keeps `pywin32` behind
  `sys_platform == 'win32'` and adds a correctly-marked `uvloop`; the header now
  records the flag so the next regeneration does not silently drop the markers.
  Verified installable on Linux with a dry-run resolve.
- **`.dockerignore` was missing `.venv/` and `node_modules/`** — it excluded only
  `venv/`. Since the Dockerfile ends in `COPY . .`, a developer's virtualenv and
  the e2e `jsdom` tree would have been baked into the production image. The
  `docker-build-error.txt` entry stays even though that file is now deleted: it
  is kept as a pattern, because `docker compose build 2>&1 | tee <log>` is
  precisely how a build log got committed in the first place.

### Test harness and e2e

- **`startApi()` is auth-isolated.** It always sets a throwaway `AUTH_DB_PATH`
  (removed on cleanup, `-wal`/`-shm` included). Previously the suite booted
  against the developer's real database, so the moment anyone ran the documented
  `python create_user.py <name>`, every `/api/*` route began answering `401` and
  `startApi()` spun for 30s before reporting "API did not start" — an error
  pointing at startup when the cause was auth. Mirrors `_isolate_auth_db` in
  `tests/conftest.py`.
- **New login-flow suite** (10 tests, port 8741, `auth: true`): dashboard
  redirects for `/` and `/index.html`, `/api/health` 401 vs `/api/health/live`
  200, wrong password renders an error and clears the field without navigating,
  correct credentials navigate exactly once, cookie flags
  `HttpOnly`/`SameSite=Lax`/`Path=/` asserted on the wire, session chip shows
  username and initial, and sign-out invalidates the old cookie (it 401s
  afterwards, not merely deletes it client-side).
- **jsdom cannot navigate and `location.replace` cannot be stubbed** — the
  property is non-writable and non-configurable, and redefining `window.location`
  throws. But jsdom emits a `jsdomError` for navigation attempts on the virtual
  console, so tests assert attempt *counts* plus the network calls recorded by
  the harness. This also required setting the document URL to the page being
  loaded: with `url: base + '/'`, `location.replace('/')` in `login.html` was a
  same-document no-op and the success path was indistinguishable from "never
  navigated".
- **The harness resolves relative URLs against the document base.** Node's
  `fetch` cannot take a relative URL, so `login.html`'s correct same-origin
  `fetch('/api/auth/login')` threw and the page rendered "Cannot reach the
  server"; `api.js` never hit this because `baseUrl()` builds absolute URLs.
- **`run.sh` accepts `.venv/` and the ambient interpreter**, matching the
  harness, and exports its choice as `RJA_PYTHON` so the script that fails fast
  and the harness that spawns uvicorn cannot disagree. It now preflights
  `import fastapi, uvicorn` and prints the exact `pip install` command — a
  missing dependency used to surface as a 30s startup timeout.
- **Fixed a pre-existing e2e failure:** the asset-integrity test's hardcoded
  inventory was missing `js/auth.js`, so `JobAgent.auth` (used at
  `frontend/js/app.js:13`) read as "referenced but never defined". The login
  feature shipped without updating the list that guards it.

### Documentation corrected

`PM.md` §5 said "implementation not started" while `BACKEND.md` §4 described
`require_actor` in the present tense and `ARCHITECTURE.md` listed attribution as
item 7 of the *current-state* decisions — two lines above the §4b "planned, not
yet built" boundary. The three disagreed with each other; all now describe what
is actually shipped, including the deviations from the plan and the two things
attribution deliberately does not do.

## 2026-10-07 — auth hardening: login is now safe to expose publicly

The username/password login (Argon2id + server-side sessions in SQLite,
HttpOnly cookie) was already cryptographically sound — 24/24 `/api/*` routes
gated, only SHA-256 of the token persisted, fail-closed on DB errors. Probing
the running app found the *abuse* and *deployment* paths were not. All seven
probes below were reproduced first, then fixed, then re-verified.

- **New `api/ratelimit.py`** — sliding-window limiter for
  `POST /api/auth/login`, the only unauthenticated write on the API. Two
  independent budgets are checked *before any Argon2 work*: per client IP
  (`LOGIN_RATE_LIMIT`, 12) and per username (`LOGIN_USER_RATE_LIMIT`, 6) over
  `LOGIN_RATE_WINDOW` (600s), answering `429` + `Retry-After`. Both are needed
  — per-IP alone lets one attacker lock out a NAT'd office, per-username alone
  lets an attacker spray one password across accounts from rotating IPs. A
  successful login clears the *username* budget only (one valid credential does
  not prove the address is benign). Memory is bounded: per-key history is
  trimmed to the window and the key set is capped, so rotating IPs cannot grow
  it without bound. Deliberately per-process, which is exact under the deployed
  `--workers 1`; scaling out needs a shared store first.
- **`/api/auth/login` is now `async def`** and awaits its failure penalty. The
  previous sync `def` + `time.sleep(0.5)` held a Starlette threadpool worker
  for the whole penalty, so ~40 concurrent bad passwords saturated the default
  40-thread pool and stalled every other sync route: measured **5.64s wall →
  1.40s**, with 34/40 answered `429` and zero hashing. Remaining blocking work
  (SQLite + Argon2) is dispatched via `run_in_threadpool` so the event loop is
  never held by a slow hash.
- **`purge_expired_sessions()` moved to the success path** — a failed attempt
  no longer earns an unauthenticated database write.
- **Bind guard now reads uvicorn's `--host` flag**, not just `API_HOST`. The
  documented `uvicorn api.app:app --host 0.0.0.0` bound on every interface with
  `API_HOST` unset and no `API_TOKEN`, which combined with `open_access()`
  (no users) meant a fully public API. Both are now checked.
- **Auth is attached at the router level** via
  `include_router(dependencies=[Depends(require_token)])`, in addition to the
  existing per-route dependency. Per-route auth fails OPEN — one forgotten
  `Depends` on a new endpoint ships it public. Note this **cannot** be done by
  appending to `router.dependencies`: this FastAPI version resolves included
  routers lazily (`_IncludedRouter`) and post-construction mutation is a silent
  no-op, which a test now pins in both directions.
- **New `_GateMiddleware`** covers what no router dependency can reach:
  `/docs` + `/openapi.json` were public (`401` now; a logged-in browser still
  gets Swagger, `API_DOCS_ENABLED=true` to publish), and `/index.html` was
  served straight from the `StaticFiles` mount, bypassing the `GET /` login
  redirect (`302` now). It also sets `X-Content-Type-Options`,
  `X-Frame-Options` and `Referrer-Policy` on every response so a bare-uvicorn
  deploy is not silently unprotected without Caddy. No CSP yet — the dashboard
  relies on inline `<script>`/`<style>` blocks, so a strict policy would break
  it rather than half-protect it.
- **A password reset now revokes every session for that user.** Previously a
  stolen `rja_session` cookie kept working for the rest of its 7-day TTL no
  matter how often the password was rotated, which defeated the point of
  resetting. `revoke_user_sessions()` is targeted — resetting one user does not
  sign out anyone else. `create_user.py` says so when it resets.
- **`LoginRequest` bounds `username` (≤64) and `password` (≤128)**, enforced in
  `api.auth.verify_login` too so non-HTTP callers cannot bypass it. A 200 KB
  password previously reached Argon2 (`422` now).
- **SQLite: schema DDL runs once per (process, db path)**, not on every
  authenticated request — `require_token` reads the sessions table per call and
  was rebuilding the schema each time (~3.6 ms/request, 50 connections for 50
  requests → 0 rebuilds). `journal_mode=WAL` is set at init so the per-request
  read is not blocked by a concurrent login/logout write. Added
  `idx_sessions_user` for the new revoke-by-user path, and `users.last_login_at`
  as an audit signal (with an idempotent `ALTER` so existing DBs upgrade in
  place).
- **CORS `allow_credentials=True`** — auth is a cookie now, so a cross-origin
  dashboard configured via `API_CORS_ORIGINS` could never have authenticated.
  Safe because `cors_origins()` always returns an explicit list, never `*`.
- **`open_access()` is announced at startup** with `warnings.warn`. "No users
  and no `API_TOKEN`" serves the entire API unauthenticated; it stays a
  deliberate localhost convenience, but a forgotten `create_user.py` on a
  public host is now shouted about in the log instead of failing silently.
- **`docker-compose.yml`**: uvicorn now runs `--proxy-headers
  --forwarded-allow-ips *` so `request.client.host` is the real client (rate
  limiting keyed on Caddy's container IP would have put every user in one
  shared bucket) and `request.url.scheme` is correct. `--workers 1` is now
  documented as a *requirement* of the in-process limiter.
- **`deploy/setup-vm.sh` no longer instructs the removed `?token=` flow.** Step
  4 told deployers to open `http://<VM_PUBLIC_IP>/?token=<API_TOKEN>` and let
  it persist to `localStorage` — that path was deleted and `api.js` now
  actively removes any legacy `rja_api_token` key. Replaced with the real flow
  (`docker compose exec api python create_user.py <username>`).
- **`requirements.lock.txt` regenerated for auth**: `argon2-cffi` was in
  `requirements.txt` but absent from the lock, so the pinned install was not
  reproducible. Added `argon2-cffi==25.1.0` + `argon2-cffi-bindings==26.1.0`
  and attributed the existing `cffi` to them.
- Docs synced: BACKEND.md §4 rewritten (its "`API_TOKEN` empty → open" bullet
  was false once a user exists), PRODUCTION.md §4 config table gained the seven
  new variables, `.env.example` documents each with its threat rationale,
  `deploy/Caddyfile` comment no longer claims "the app has no session cookies to
  protect".
- **New `tests/test_api_auth_hardening.py`** (31 tests), one per defect above,
  plus `tests/conftest.py` fixtures that reset the process-global limiter and
  the schema memo between tests. Full API suite: **304 passed, 1 skipped**.

### Still open (deliberately not in this change)

- **`require_actor` / multi-operator attribution is documented but not
  implemented.** BACKEND.md §4 and ARCHITECTURE.md §7 both specify
  `api.deps.require_actor(request, creds) -> str`, an `"automation"` sentinel,
  and an `actor`/`created_by` field on every write. None of it exists — the
  session `username` is available and currently discarded. Left out because it
  touches every write path and is a feature, not a security fix; bundling it
  would make this change hard to review and easy to revert.
- No Content-Security-Policy (needs every inline block extracted first).
- No account lockout or 2FA — acceptable for a single-operator tool, but the
  rate limiter is the only brute-force control.
- The rate limiter is per-process; a multi-worker deploy needs Redis/SQLite.

## 2026-10-03 — live-submit recon: Greenhouse Democorp demo board blocked pre-flight

- Ran the read-only Playwright recon against Greenhouse's public Democorp
  "Full Stack Engineer" demo posting (`job-boards.greenhouse.io/example/jobs/83446`).
  No fields were filled, no files uploaded, and no submit control was clicked.
- Result: `confirmation_metadata_found=false` (`confirmation_path` and
  `confirmation_message` were both absent), so `/intent` would fail closed
  with 502 before any browser fill or click. The page also exposed reCAPTCHA.
- The only required fields detected were First Name, Last Name, and Email;
  none were unhandled. Per the supervised-run procedure, dry-run and armed
  stages were not attempted and no submission occurred. Evidence:
  `recon-democorp.json` (local, removed before commit).

## Unreleased (2026-10-03 — Free deployment stack: Caddy + Oracle guide + token bootstrap)

- `docker-compose.yml` now ships the full public stack: `api` (dashboard +
  endpoints; container-internal `0.0.0.0` bind with a `127.0.0.1:8000` host
  escape hatch for SSH tunnels) and `caddy` (reverse proxy on 80/443 —
  automatic Let's Encrypt when `SITE_ADDRESS` is a real hostname; `:80`
  default serves plain HTTP on a bare IP). Secrets stay read-only mounts;
  Caddy config/certs live in `deploy/Caddyfile` + named volumes.
- New `deploy/` folder: `DEPLOY_ORACLE.md` ($0 deployment walkthrough on
  Oracle Cloud Always Free — 4 ARM OCPU / 24 GB / 200 GB, free DuckDNS
  hostname, VCN ingress, ops + troubleshooting tables), `setup-vm.sh`
  (Docker install, ufw/iptables fixups, runtime-file creation), `Caddyfile`.
- `frontend/js/auth-bootstrap.js` (+ script tag in `index.html`): opening the
  dashboard once as `/?token=<API_TOKEN>` stores it in
  `localStorage['rja_api_token']` and strips it from the address bar via
  `replaceState` — token-protected deploys need no manual header setup.
- `.env.example`: added `SITE_ADDRESS` (Caddy site address), surfaced
  `TIER_BATCH_MAX=75` / `TIER_DREAM_THRESHOLD=90` (auto-apply tier bounds in
  `agents/auto_applier.py`), bumped `AUTO_APPLY_THRESHOLD` default 70 → 75,
  and noted compose overrides `API_HOST` to `0.0.0.0` (token required).
- Docs synced: README (features, env vars, tree, Docker quick start), 
  PRODUCTION.md (§3 stack, §4 vars, §5 HTTPS, §7 rows), ARCHITECTURE.md,
  FRONTEND.md, AGENTS.md.
## 2026-10-03 — feat(safety): three-state submit switch + dry-run rehearsal (Stage 0/1)

The submit path could previously only be exercised two ways: not at all, or
by sending a real application to a real employer. That made every rehearsal
expensive, so none happened, so the first execution would also have been the
first test. Fixed.

- `api/safety.py` — `submit_enabled()` / `submit_dry_run()` / `submit_mode()`
  replace direct constant reads. Three states: `disarmed` (default, 403),
  `dry_run`, `armed`. `SUBMIT_ENABLED = False` stays in git; env can arm a
  single process so a live run needs no tracked code edit. `SUBMIT_DRY_RUN`
  alone can never open the path.
- `api/apply.py` — `_run_greenhouse_submit(dry_run=True)` runs the whole real
  path (navigate, fill, field readback, minimum-profile gate, attachment
  gate, confirmation-metadata comparison, submit-button lookup) and returns
  before `.click()`. `submit_greenhouse` branches to dry run **before**
  `claim_first`, so rehearsals never consume the intent, take the claim, or
  spend the daily cap.
- Instrumentation for the one run that counts: `SUBMIT_HEADLESS` (watch it),
  Playwright trace + video + HAR, and **unconditional post-click DOM capture
  before verification is judged** — so a 422 can be diagnosed as "Greenhouse
  accepted it and our expected copy was wrong" (false negative) versus "an
  inline validation error blocked it". Evidence: `data/submit_runs/<run>/`.
- `tools/submit_recon.py` — read-only scanner: confirmation metadata
  discoverability (if absent, `/intent` 502s and a live test is impossible),
  required fields vs. what the filler handles, captcha, submit control.
- `tools/seed_demo_job.py` — seeds Greenhouse's **own demo posting**
  (`job-boards.greenhouse.io/example/jobs/83446`, Democorp "Full Stack
  Engineer", fp `94bcd024022152dc3d0d3280d778c1dd`) so the rehearsal involves
  no real employer.
- `LIVE_SUBMIT.md` — supervised runbook with the operator screenshot gate and
  an outcome table. Records the verified finding that the demo form is
  **reCAPTCHA-protected**, and states plainly that a captcha block is a
  legitimate result to accept, not something to evade.
- Tests: +43 (`tests/test_submit_dryrun.py` 27, `tests/test_submit_recon.py`
  16) → **379 passed, 1 skipped**. Two are source-ordering guards, because
  "the click is unreachable in dry run" and "nothing mutates before the
  dry-run return" are ordering properties a refactor breaks silently.
  Mutations: removing the dry-run stop → 4 fails; letting `SUBMIT_DRY_RUN`
  open the path → 3; dry run falling through to claim/click → 2.
- `tests/conftest.py` scrubs `SUBMIT_ENABLED` / `SUBMIT_DRY_RUN` from every
  test process, so a developer's armed `.env` cannot turn a "must 403"
  assertion into a false pass.

`SUBMIT_ENABLED` remains `False`. No live submission has been performed.

## 2026-10-03 — docs: Phase 2.1 scheduled (CV-upload-first, cache seam)

Documentation only; no code change. Two backlog one-liners promoted to a
scheduled phase, targeted ~3–4 days out.

- **2.1a CV-upload-first flow** — upload PDF/DOCX from the dashboard → existing
  parse chain → that profile becomes the active matching profile → Resume
  Studio diffs job requirements against it and reports what the CV is missing.
  Explicitly *not* a replacement for `CV_DIR` multi-CV best-of-N selection.
  Flagged as the largest remaining item: upload path + parsing + Studio
  comparison logic + new UI.
- **2.1b Multi-worker cache** — the in-process 90s TTL cache means each uvicorn
  worker holds its own copy: at `--workers 4`, up to 4× Sheets calls and
  inconsistent data between workers. Deliverable is a **cache backend seam plus
  a startup warning**, not Redis; standing up Redis now would be infrastructure
  for a scale problem this single-user deployment does not have (same reasoning
  that deferred Celery and the Docker queue).

Recorded in `PM.md` §2.1 (spec + acceptance criteria, status table row),
`PRODUCTION.md` §8 (ops impact, uploaded-CV PII rules, pre-flight checklist
before raising worker count) with §2/§5 and the compose file cross-referenced,
`ARCHITECTURE.md` §4b (design intent), `BACKEND.md` (planned endpoints),
`FRONTEND.md` (planned UI + gap panel), `README.md` (roadmap table).

## Unreleased (2026-10-03 — source-name canonicalization: one provider, one name)

Closes the `by_source` naming backlog item. The ticket named one pair; the
config had five labels collapsing onto three providers:

| Board key | Actually | Why |
|---|---|---|
| `RemoteOKAPI` | `RemoteOK` | identical URL `remoteok.com/api` — fetched twice per run |
| `Remojobs-Frontend/Backend/Fullstack` | `Remotive` | `remotive.com/api` with a `?search=` param |
| `FounditIN` | `Naukri` | configured against `naukri.com/remote-developer-jobs` |

Symptoms: `/api/stats` `by_source` counted one provider twice, the dashboard
sources grid rendered duplicate cards competing for the same top-8 slots, and
the Job Desk source dropdown offered two entries each returning half the rows.

- `tools/sources.py` — explicit alias table + `canonical_source()`. No fuzzy
  matching: an unknown board passes through unchanged, so a genuinely new board
  can never be absorbed into an existing one (mutation-tested).
- **Write path:** `tools.sheet_writer.prepare_job_for_sheet` — the one choke
  point every board and parser already passes through, rather than patching the
  22 places `agents/scrapper.py` assigns `source`.
- **Read path:** `api.cache.get_tab_rows` — rows already in the Sheet were
  written under the old keys, so a write-only fix would stay visibly split
  until the sheet was rebuilt. This is what actually merges historical data.
- `GET /api/jobs?source=` canonicalizes the query too, so an old bookmark using
  `RemoteOKAPI` still returns the merged set instead of a half-empty page.
- **Duplicate fetches:** `scrape_all` now skips a board whose URL was already
  fetched this run, logging it as `skipped-duplicate`. Two HTTP round-trips plus
  their bot-protection sleeps were being spent per run on rows the deduplicator
  then discarded. Board entries are retained — PRODUCTION.md board-triage
  history refers to them by name.
- README corrected: it listed `Remojobs (×3)` and `RemoteOK` under
  "HTML (requests+BS4)". They are API boards.
- Tests: `tests/test_source_naming.py` (15) + 1 E2E assertion that the sources
  grid merges aliases and `by_source` still sums to `total_jobs`.
  Mutation-tested: dropping read-side normalization → 2 unit + 1 E2E failure;
  dropping write-side → 1 failure; over-normalizing unknown boards → 3 failures.
- Suites: **336 passed, 1 skipped** (pytest) and **19 passed** (E2E).

## Unreleased (2026-10-03 — frontend E2E smoke suite)

`tests/e2e/` — boots the real FastAPI app (seeded through a new `SNAPSHOT_FILE`
env override, so nothing is written into the project root) and loads the real
`index.html` + real `js/*` in jsdom over HTTP. 18 assertions: asset integrity,
happy path, API-unreachable. `./tests/e2e/run.sh`.

- Targets the failure mode the pytest suite structurally cannot see: a
  `<script>` that 404s, a guard on an undefined global, an unreachable error
  state, a widget that renders empty in every environment. All four shipped in
  this repo and none of them crashed.
- **Mutation-tested.** Each real past bug was reintroduced to confirm the suite
  fails: mockData.js 404 → 4 failures; dead `MOCK_SOURCES` guard → 2; role nouns
  in the skill cloud → 2; skill cloud guarded on an undefined global → 3; store
  swallowing the `/api/skills` error → 2.
- Two of those initially passed under mutation and required real fixes to the
  suite: the role-noun case needed a fixture row in the *pre-fix* producer
  format (`"back-end, Engineer, Developer, developer, Back-end"` — rows written
  by the old parser still exist in the Sheet), and the swallowed-error case
  needed an assertion that the cause reaches the DOM rather than just the word
  "unavailable".
- Fixture `tech_stack` values are real `top_techs()` output over verbatim live
  Remotive/WeWorkRemotely copy, not invented stacks.
- `cache._snapshot_paths()` adds the `SNAPSHOT_FILE` override (also useful for
  pointing ops at an archived scrape).
- Known gap, stated rather than papered over: no real browser. `playwright
  install chromium` cannot reach the browser CDN from this sandbox, so CSS,
  layout, visual regressions and real input events are uncovered. jsdom runs the
  same JS against the same API; it is not a substitute for a browser.
- Python suite unchanged: **321 passed, 1 skipped**. E2E: **18 passed**.

## Unreleased (2026-10-03 — skills aggregate verified against REAL board text; two real bugs)

The first `/api/skills` corpus was hand-written, so it tested text that looks
like `tech_stack` rather than what the pipeline actually writes. Re-checked
against verbatim copy pulled from live Remotive + WeWorkRemotely postings. It
failed, for reasons no invented fixture would have surfaced.

**What the column really contains.** `TECH_FILTER` (`agents/scrapper.py`)
deliberately matches ROLE words — `developer`, `engineer`, `software`, `web`,
`backend`, `front-end`, `full-stack` — because the same regex also decides
whether a posting is a dev job. The API parsers then did
`", ".join(re.findall(TECH_FILTER, combined_text)[:5])`: raw matches, **no
dedupe**. A real Golang + Python + Kubernetes posting produced
`"back-end, Engineer, Developer, developer, Back-end"` — five slots, zero
technologies, the stack pushed clean out of the window.

- **Producer fix:** the three `parse_json_*` parsers now call the existing
  `top_techs()` instead of raw `findall[:5]`, matching the RSS/HTML path
  (previously the two paths disagreed). `top_techs()` now also skips
  `ROLE_WORDS`, so the 5-item cap is spent on real technologies and a
  non-technical posting yields `""` instead of a cell full of job-title nouns.
  Same posting now writes `"python, react, java, php, vue"`.
- **Aggregator fix:** role nouns added to `_SKILL_STOPWORDS`, plus
  hyphen/underscore folding so `Back-end` / `backend` / `back end` resolve to
  one key. Without it the cloud ranked Web/Software/Backend at the top of every
  real scrape — and `Back-end` vs `Backend` rendered as two separate pills,
  which is exactly the alias-drift failure this endpoint was built to prevent,
  occurring on the single most common token in live data.
- Verified end to end on real copy: `Senior back-end Engineer` →
  `['Python','React','Java','PHP','Vue']`; `Staff Software Engineer` →
  `['API','Python','TypeScript','JavaScript','React']`; a content-review and a
  German customer-service posting → `[]` (previously both contributed "Web").
- Tests: `TestRealPipelineText` + `TestScraperProducerParity` (7 new) pin the
  real strings, the fold, and that the parsers can't regress to `findall[:5]`.
  Full suite: **321 passed, 1 skipped**.

Note on provenance: the sandbox has no direct egress (TLS blocked), so board
JSON/RSS was pulled through a proxied fetch and replayed through the real
parser code. Postings are real; the HTTP leg was not the scraper's own.

## Unreleased (2026-10-03 — the mock layer never existed: dead fallbacks removed)

Follow-up to the `MOCK_SKILLS` finding. The root cause is bigger than one
widget: **`frontend/js/data/mockData.js` has never existed in this repo** (no
git history, 404 on every page load), yet `index.html` loaded it and five
places branched on the globals it was supposed to define. Every
`JobAgent.MOCK_*` reference was `undefined`.

- `else if (JobAgent.MOCK_SOURCES)` in `dashboard.js` was permanently false, so
  a failed `/api/stats` left `"Loading live stats from /api/stats…"` on screen
  **forever** — and the amber API-error banner was unreachable inside that dead
  branch. A hard backend outage looked exactly like a slow load.
- `store.loadJobs` / `loadTracker` logged "fallback to mock" and set
  `dataSource = 'mock'` while actually producing `[]` via `|| []`.
  The Job Desk then rendered the suffix `(mock: 0)` and the banner line
  "Showing cached mock data." — both false.
- `jobDesk._allJobs()` and `tracker._cards()` had the same `|| []` dead tail.
- Fix: dropped the 404 `<script>` tag and every mock branch. Each section now
  renders explicit loading / error / empty states that name the failed
  endpoint. `dataSource` reports `unavailable` instead of `mock`.
- Docs corrected where they described the phantom layer as real: FRONTEND.md
  (file tree, script order, first-paint claim, state shape), README tree,
  PRODUCTION.md §6/§7, ARCHITECTURE.md failure-mode table.
- Verified: all 13 scripts `index.html` loads now return 200 (was 12/13 + one
  404), and a static sweep finds no `JobAgent.*` reference that is never
  assigned.

Same bug class as the two before it: a guard that looks like it checks
something real, is always false, and fails silently because nothing throws.

## Unreleased (2026-10-03 — GET /api/skills: live skill-demand aggregate)

- New read endpoint `GET /api/skills?tab=&limit=` (`api/routers/skills.py`,
  `cache.get_skills_snapshot`, `SkillsOut`/`SkillOut` schemas). Aggregates the
  free-text `tech_stack` column across one job tab and returns
  `{tab, total_jobs, jobs_with_stack, unique_skills, skills[{name,count,pct}]}`.
- Canonicalization (`cache.extract_skills`) collapses the alias drift the column
  actually contains — `js`/`javascript`, `node`/`nodejs`/`Node.js`, `k8s`,
  `postgres` — so one skill is one pill. Splits on `, ; |`/newline/bullets but
  **not** `/` (keeps `CI/CD`), drops stopwords/numeric/prose tokens, counts each
  skill once per job, and sorts count desc then name asc for stable output.
- `pct` is a share of `jobs_with_stack` (rows that list a stack), not of
  `total_jobs`, so empty-stack rows don't deflate every figure.
- Cache-backed (same TTL as `/api/jobs`), token-gated like every other read, and
  fails soft: a Sheets outage returns the zeroed shape, never a 500. A non-job
  tab (`APPLIED`/`STATS`) is a 400.
- Frontend: `api.getSkills()`, `store.loadSkills()` (+ `skills` state, wired into
  `loadAll`), and `dashboard._renderSkills()` replace the dead `MOCK_SKILLS`
  branch. The cloud now shows real percentages with a hover count, and
  distinguishes loading / API-error / "no tech_stack data yet" instead of
  rendering nothing. No mock fallback — invented demand figures would be worse
  than an empty state.
- Note: `JobAgent.MOCK_SKILLS` was never defined anywhere in the codebase, so the
  old guard `if (this.topSkillsCloud && JobAgent.MOCK_SKILLS)` silently rendered
  an empty cloud in every environment. The widget was dead UI, not stale mock UI.
- Fixed during live verification: `.NET` aggregated as **`Net`**. Edge-punctuation
  stripping (needed so `React.` and `(CSS)` normalize) ran *before* alias lookup,
  so the meaningful leading dot was discarded and the leftover `NET` was
  title-cased into a plausible-looking wrong answer. `_canonical_skill` now keeps
  two forms — wrappers-only (`.NET`, `C++` intact) and fully stripped — and tries
  the alias table against both, wrapper form first. Same silent-wrong-answer
  class as the `MOCK_SKILLS` guard: no crash, no error, just a quietly incorrect
  label. Caught only by eyeballing the full 47-row output, not by the tests.
- Tests: `tests/test_api_skills.py` — 23 cases (alias collapse, in-cell dupes,
  pct denominator, sort stability, `CI/CD` non-split, noise rejection, quote/
  bracket stripping, limit cap, tab filter, 400 on bad tab, 422 on bad limit,
  Sheets-failure soft landing, token gate, `.NET`/`C#`/`C++`/`ASP.NET` punctuation
  survival + `.NET`/`dotnet`/`NET` collapse). Full suite: **314 passed, 1 skipped**.
- Phase 2 endpoint work is now complete; the only remaining 2b item is the
  operator-held live submit run. `SUBMIT_ENABLED` stays `False`.

## Unreleased (2026-10-01 — Manual-application modal scroll fix)

- The Pipeline Tracker `+ Add Manual Application` modal clipped its
  Cancel/Save footer on short screens (the inner `<form>` grew past the
  box instead of letting the body scroll). The form is now a constrained
  flex column: the field body scrolls, the footer stays pinned, with
  tighter spacing under 700px height.

## Unreleased (2026-10-01 — Review honesty: needs_review status)

- `fill_review` (`api/apply.py`) maps Greenhouse `filled_ready` with
  unverified/missing required profile fields to `needs_review` (stored in
  `apply_review_artifacts.fill_status` + new `field_verification` /
  `profile_fields_verified` columns). Response exposes both fields and a
  `Required applicant fields missing/unverified` `fill_error`. Intent (409)
  and submit (410) already reject non-`filled_ready`, so the artifact can no
  longer overstate readiness. Lever keeps its raw filler status (no readback).
- Dashboard (`autoApply.js`) renders `needs_review` amber as
  `needs_review: required fields missing — review manually before any submit`,
  never counts it as filled. Tracker maps `needs_review` into Under Review.
  `SUBMIT_ENABLED` stays `False`.
- Tests: missing_required → `needs_review` + error; verified → `filled_ready`;
  `needs_review` artifact blocks intent 409. Full suite: 291 passed, 1 skipped.

## Unreleased (2026-10-01 — Pipeline Tracker review mapping)

- Professional manual tracker form: `+ Add Manual Application` now opens an
  in-app modal with required URL/title/company fields, optional source/salary/
  contact/follow-up/notes metadata, inline validation, URL normalization, and
  `POST /api/tracker` saving state instead of browser prompts.
- Tracker terminal archive behavior: `rejected`, `withdrawn`, and `ghosted`
  cards now remain terminal on click with an explanatory toast, while active
  cards still progress `applied/review→interviewing→offer→rejected`.
- Command Deck pipeline metrics now render from tracker rows instead of the
  old static sample counts, so empty/live API states stay honest.
- Sidebar count badges now render from live `/api/stats` totals (`ALL JOBS` and
  `TOP MATCHES`) instead of hardcoded demo values.
- Pipeline Tracker now preserves the auto-apply APPLIED-sheet header fork in
  `TrackerEntry` (`job_fingerprint`, `applied_at`, `scraped_at`, job context),
  so fill/review rows are not flattened by the API.
- Frontend tracker maps fill-only statuses (`filled_ready`, `package_only`,
  `custom_questions`, `email_draft`, `dream_manual`, etc.) into the Under
  Review column instead of Applied, preserves mock `review` cards offline, and
  cycles cards using backend-valid statuses only.
- Tracker PATCH now skips mock/local placeholder IDs instead of attempting a
  failing API call first; local cycling no longer gets stuck at `interview`.
- `POST /api/tracker` plus the existing `+ Add Manual Application` button now
  append manual APPLIED rows instead of leaving the button inert.
- Full suite: 288 passed, 1 skipped.

## Unreleased (2026-10-01 — Submit minimum-profile gate)

- `_fill_greenhouse_form` (`agents/auto_applier.py`) now emits
  `profile_fields_verified` and downgrades a vacuous `verified` (zero typed
  fields, selector drift) to `missing_required`, which fails closed.
- `_run_greenhouse_submit` (`api/apply.py`) requires name (`first_name` or
  `full_name`) + `email` in `profile_fields_verified` before any click.
- Tests: no-profile / no-email / no-name / missing_required → no click;
  `full_name`+email passes; filler vacuous case → `missing_required`.
  `jobDesk.js` sort now honors the `scraped_at` fallback from its comment.
  `PRODUCTION.md` free-form CV note folded into a `PM.md` backlog pointer.
- `SUBMIT_ENABLED` stays `False` — live submit still locked.
- Full suite: 286 passed, 1 skipped (+7 profile-gate tests).

## Unreleased (2026-10-01 — Submit field-readback hard gate)

- `_run_greenhouse_submit` (`api/apply.py`) now treats the filler's
  `field_verification` as a hard no-click gate: only `"verified"` (first-pass
  readback match) or `"repaired"` (re-typed, final readback match) proceed.
  `"mismatch"` (drift survived 3 repair passes), `"unavailable"` (no readback
  possible), or any other state fails closed before any submit click — even
  when attachments verify cleanly.
- Tests: `mismatch`/`unavailable` → no click; `verified`/`repaired` → proceed
  past the gate; existing attachment-gate tests now pass an explicit passing
  field state so each test still targets its own gate.
- `SUBMIT_ENABLED` stays `False` — live submit still locked.
- Full suite: 279 passed, 1 skipped (+4 field-gate tests).

## Unreleased (2026-10-01 — Sidebar Hot badge live)

- The sidebar `topMatchCountBadge` was hardcoded to `11 Hot` in `index.html`
  and never updated by any script, while Command Deck showed the live
  `TOP MATCHES` tab count (e.g. 24). `dashboard.js:_applyMetrics` now sets
  the badge from the same live `/api/stats` tabs on every render.

## Unreleased (2026-10-01 — Curated Jobs newest-first)

- `frontend/js/components/jobDesk.js:getFilteredJobs` sorts newest-first by
  `posted_date_iso` (desc, undated rows last). Sheet order is oldest-first
  (appends land at the bottom), so without this new jobs sat at the end of
  the Curated Jobs tab. Apply queue still ranks by score (unchanged).

## Unreleased (2026-10-01 — Review-queue screenshot 404 spam)

- `frontend/js/components/autoApply.js` fabricated a screenshot URL from the
  fingerprint even when the backend returned `screenshot_url: null`
  (package-only), causing GET 404 pairs (`<img>` + authenticated-fetch
  fallback) on every render for package-only results. The backend response is
  now the source of truth — no URL is built when it says `null`, so the
  honest empty state renders with zero requests.

## Unreleased (2026-10-01 — Submit blockers: intent immutability + dedicated token)

- Intent/material immutability (`api/apply.py:create_greenhouse_intent`):
  intent now REUSES the reviewed artifact's resume + cover letter verbatim —
  no regeneration, no package rebuild, no artifact rewrite. Reviewed ==
  submitted by construction; missing/stale materials fail closed (502).
- Duplicate intent while one is live is rejected (409) BEFORE any expensive
  work via a read-only pre-check (`live_intent_retry_after` in
  `api/apply_intents.py`), so a rejected request can no longer mutate the
  first token's artifact. Race path still 409s via `create_intent`.
- Apply auth is now dedicated: `require_apply_token` accepts ONLY
  `APPLY_API_TOKEN` (the `API_TOKEN` fallback is removed); unset token fails
  closed 401. New test proves `API_TOKEN`-only gets 401 on both routes.
- Frontend: Auto-Apply review-result posting link now goes through
  `JobAgent.safeHttpUrl` (was raw `applyUrl`), closing the last unescaped
  `javascript:`/`data:` link surface.
- Tests: intent suite rewritten to the reuse invariant (no-regeneration,
  stale-materials 502, duplicate-leaves-artifact-untouched) + dedicated-token
  401 test. `SUBMIT_ENABLED` stays `False` — live submit still locked.
- Full suite re-verified: 275 passed, 1 skipped (was 273; +2 net new tests).

- Curator match logging: fixed doubled sign (`(28++0)` → `(28+0)`) in
  `agents/curator.py` — a literal `+` plus a `:+d` value printed both signs.
- Arbeitnow company backfill: the API field is `company_name`, not `company`
  (`agents/scrapper.py:parse_json_arbeitnow`); older runs saved blank company.
  A minority of postings link to the company homepage (upstream `url` field);
  a slug-built `/jobs/<slug>` URL was verified to 404, so links stay as-is.
- Scrape-status polling: single-loop guard (`pollActive`) in
  `frontend/js/app.js` — a refresh-resume plus click/409 path could stack
  concurrent `GET /api/scrape/{id}` loops; interval stays 5s.
- `tools/sheet_writer.py:append_rows` validated the sample row before
  `prepare_job_for_sheet` auto-filled `scraped_at`/`status`/`job_fingerprint`,
  warning spuriously every run; validation now runs on the prepared copy.
- Scraper failures diagnosed as structural, not a regression (bot walls,
  generic-selector mismatch, duplicate board URLs, missing Adzuna keys, dead
  DNS); no earlier targeted fix found in history. Details: `PRODUCTION.md` §7.
- Full suite re-verified: 273 passed, 1 skipped.

- Kill switch enforced: `POST /api/apply/{fp}/intent` + `/submit` fail closed
  with 403 while `api/safety.py SUBMIT_ENABLED=False` (router + service level).
- Review fill carries the final tailored resume + cover letter (same files a
  submit would send); response reports `materials_note: final` or an honest
  `fallback-empty` reason. Submit refill refuses to click unless the resume +
  cover letter verify as attached (`files.length` readback).
- Legacy CLI blind submit permanently removed (`AUTO_APPLY_CONFIRM` ignored
  everywhere); score parsing coerces `"85.0"`/`""`/`None`/`"87%"` instead of
  crashing; consumed intents are replaceable and `failed_refunded` claims can
  retry; package HTML escaped with `rel="noopener noreferrer"`.
- Cockpit: daily cap enforced (persisted per-day count), in-browser screenshot
  preview (`GET /api/apply/{fp}/screenshot`), attachment-copy mismatch fixed,
  sidebar/dashboard cap numbers live, blob-URL leak fixed.
- Frontend XSS sweep: `JobAgent.escapeHtml` + `safeHttpUrl` (`js/escape.js`);
  drawer/toast/grid-table/tracker/cards/dashboard sources escaped; only
  `http(s)` posting URLs assigned. Full suite: 273 passed, 1 skipped.

## Unreleased (2026-09-29 — Auto-Apply cockpit fill-and-review)

- Connected the fill-only API to the existing Greenhouse/Lever form fillers.
  Each supported job opens a visible review window, fills supported fields,
  captures a pre-submit screenshot, and stays open for manual review/submission;
  the backend never clicks submit. Unsupported ATSs remain package-only.
- Auto-Apply Cockpit processes up to three eligible jobs sequentially, reports
  per-job fill/package outcomes without aborting later jobs, and shows actual
  latest-run results instead of a static screenshot mockup.
- Replaced placeholder Playwright telemetry with actual review-queue activity.
  Auto-Submit remains disabled and there are still no HTTP submit routes.
- Terminal messages render as text nodes so untrusted job titles and API errors
  cannot inject markup into the cockpit log.
- 2b submit remains gated: F1/F2 and independent test primitives are in place; Lever
  confirmation-copy observation is blocked on a legitimate isolated trial
  posting. Latest full suite: 222 passed, 1 expected xfail.

## Unreleased (2026-09-24 — Phase 2 actions + Studio fixes)

- Action API: `POST /api/scrape` + `GET /api/scrape[/{run_id}]` (single-active-run
  registry `api/runs.py`); `POST /api/resume/{fp}` + `POST /api/cover-letter/{fp}`
  with downloads (`api/materials.py`, fp-mapped files only); `PUT /api/cv/profile`
  (Studio edits into on-disk cache, no LLM per request).
- New tests: `test_api_cv.py`, `test_api_materials.py`, `test_api_freshness.py`,
  `test_api_jobs_contract.py` (+ `test_api_phase2.py`) — suite now **136 passed**.
- Resume Studio: live tailor flow (fingerprint select, progress steps, cover-letter
  preview), profile Edit/Save with local override + API sync, variant select/add;
  preview card starts hidden and the demo fallback renders dynamically from the
  selected job + profile (no hardcoded fixture); skills textarea fixed
  (full-width block layout, min-height 110px, auto-grow).
- Docs: BACKEND (×8 routers, new endpoints, PUT allow-method, test counts),
  FRONTEND (api.js fns, Studio live state), PM (Phase 2 status + next),
  TESTER (136/8 files), README (structure + endpoint table), AGENTS,
  ARCHITECTURE.
- Scrape robustness: per-board time budget (`SCRAPER_TIMEOUT`, default 300s)
  so a hung board is skipped instead of stalling the run; board-start
  "running" state for the monitor; poll loop resets to idle on
  404/unreachable instead of sticking on "Scraping…" (`tests/test_scraper_timeout.py`).
- JobSpy isolation: opt-in only (`ENABLE_JOBSPY`, default `false` →
  `skipped-disabled`); when enabled it runs in a `spawn` child process
  (`_run_jobspy_isolated`) so a native `tls-client` segfault fails just that
  board and the run still reaches summary/curate; scope via `JOBSPY_SITES` /
  `JOBSPY_TERMS` (defaults: `linkedin,indeed` × 1 term).

## 2026-09-23 — Phase 1e: docs + live Sheets

- New docs: `PRODUCTION.md`, `ARCHITECTURE.md`, `BACKEND.md`, `FRONTEND.md`,
  `PM.md`, `REVIEWER.md`, `TESTER.md`, `CONTRIBUTING.md`; README API section.
- `keys.json` wired; `/api/health` → `sheets_configured: true`, live Sheet
  (`LIVE Remote Jobs Tracker`: 12 ALL JOBS, 12 GOOD MATCHES).
- Fixed Windows cp1252 emoji crash in `tools/sheet_writer.py` (UTF-8 stdout
  reconfigure) — it was masking the Sheet connection as a failure.

## 2026-09-23 — Phase 1d: data honesty

- `ALL JOBS` snapshot fallback (`scraped_jobs.json` → `fresh_scrape.json`, 96 rows)
  with pipeline-MD5 fingerprints; `data_source` (`sheets|snapshot|empty`) on
  `/api/health`; UI source badges + score-gate auto-drop for unscored snapshots.

## 2026-09-23 — Phase 1c: frontend wiring

- New `frontend/js/api.js` (per-router client, token/base-URL support, coded errors).
- `store.js`: live loaders + normalization + per-section mock fallback.
- `jobDesk`/`dashboard`/`tracker`/`jobDrawer` live; `app.js` async boot
  (mock first paint → live re-render); Sync Sheets + global search wired.

## 2026-09-23 — Phase 1b: API split + same-origin UI

- `api/app.py` monolith → `deps.py`, `mappers.py`, `routers/{health,jobs,stats,tracker,system}.py`.
- `frontend/` mounted via `StaticFiles` (`GET /` → dashboard, zero CORS).
- `.env.example` + `requirements.txt`: `API_*` vars, fastapi/uvicorn/pydantic/httpx.

## 2026-09-23 — Phase 1: read API

- `api/` (app/cache/schemas) + `tests/test_api_phase1.py` (18 tests, faked Sheets):
  health, jobs list/search/get-one, stats, tracker list/patch, refresh.
- TTL cache (90s), curated enrichment join, Bearer auth + localhost-first bind rule.

## Pre-existing — Phase 0: pipeline

- 45+ board scrapers, curator (dedup/CV match/rank), Sheets 5-tab dashboard,
  LLM fallback chain (Gemini→Groq→Mistral→GLM→Ollama), auto-apply pipeline,
  tracker CLI, scheduler, Docker + compose.
