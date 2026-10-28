# PM.md — Project Tracker (Phases, Status, Next)

Living plan for the remote-job-agent build. Status reconciled 2026-10-17. Section 1 is the current checklist; dated historical specifications below are not new work orders.

---

## 1. Current status and checklist (2026-10-17)

**Legend:** checked = implementation exists, not necessarily merged or deployed.
Pending verification is listed separately. The published baseline on
`arena/393bb940-remote-job-agent` passed CI; the fill-timeout/result-handoff
fix shipped in PR #31 (merged). The live-browser rerun remains pending. The
2026-10-16 dependency remediation uses
CrewAI 1.6.1 with patched MCP 1.30.0 (a deliberate compatibility rollback);
see `deploy/CI_FAILURE_REMEDIATION.md`. **Merged into `main` (verified in git
2026-10-17; `main` == `feat/test2`, 0 commits apart): PR #31
(`arena/393bb940`, Docker locked-dependency work + remediation), PR #32
(`arena/58ad20f5`, confirmation-metadata investigation brief) and PR #33
(`feat/test`). Nothing is deployed.** `phase 3` work is user-reported and has not been integrated
or independently checked in this checkout.

### Done / implemented

- [x] Core scraper, dev-role filtering, deduplication, CV scoring/ranking, Sheets
      output, scheduler and tracker CLI.
- [x] Read/action APIs, live dashboard/Job Desk, Scrape Monitor, skills aggregate,
      tracker status mapping, CV profile editing/variants and tailored materials.
- [x] Authentication, roles, documented security hardening and Scenario A actor
      attribution (shared data, not per-user isolation).
- [x] Greenhouse/Lever fill-and-review; unsupported ATS package generation.
- [x] Real-Chrome Democorp fill-only smoke **reported by the user on 2026-10-15**:
      supplied screenshot shows applicant fields filled and resume/cover letter
      listed as attached. No submission reported. Partial verification only:
      API fill timed out after 90 seconds and screenshot endpoint returned 404.
      See `LIVE_SUBMIT.md` run log; no live rerun performed in this session.
- [x] Fill timeout/result-handoff fix implemented locally: configurable foreground
      wait (default 180s), durable pending/result polling, periodic claim renewal,
      late screenshot/metadata persistence and stale-worker fencing. 20 Python
      handoff cases and 4 UI-polling cases pass. This is not a new live fill pass.
- [x] Greenhouse intent/submit code and safety gates. **No verified live submit;
      kill-switch and UI submit toggle remain disabled.** Lever has no submit path.
- [x] Resume CV-fidelity improvements and actual generated-markdown preview.
- [x] Per-CV semantic scoring, content/model/schema cache invalidation, safe
      keyword-only fallback and regression tests (current working branch).
- [x] Docker installation from the existing universal lock, dependency consistency
      check and regression guards. **Native x86-64/ARM64 image builds/runtime
      checks passed in GitHub CI run 38743655019 at code commit `0971322`.**
      Job/step metadata reviewed; raw log download blocked in this sandbox.
      Evidence/limits: `deploy/DOCKER_CI_VERIFICATION.md`.
- [x] Docker/Compose/Caddy and Oracle deployment preparation; this is not proof
      of an actual live VM deployment.
- [x] Tracker/Kanban interaction coverage: 22 jsdom tests over real routes and
      tracker services with isolated fake Sheets, plus 22 API/runner contracts.
      Failed-write/local-success, URL-key routing, repeated notes, double-clicks
      and false-success refresh handling fixed. Manual final review unchanged.
- [x] Targeted E2E `.env`/auth revalidation: 6 dummy-credential checks reproduce
      the historical missing-pin failure and prove current empty-string pins
      prevent it, including trailing-comment values and isolated login. Stale
      warning retired with evidence; production auth unchanged (see `TESTER.md`).
- [x] Existing automated suites: latest recorded local results below.
- [x] Rate-limit `Retry-After` boundary overflow fixed locally (2026-10-17):
      the sliding-window limiter's `int(remaining) + 1` reported window+1
      (601 for a 600s window) whenever the denial landed in the same
      ~15.6ms `GetTickCount64` tick as the first hit — a Windows-only flake
      the Linux CI clock cannot reproduce. Now `max(1, math.ceil(remaining))`,
      matching the pattern in `fill_claims.py`/`apply_claims.py`. Two boundary
      regression tests added RED-first (601 observed against the old formula);
      85 targeted rate-limit/auth/proxy/timing tests pass. See `CHANGELOG.md`.
- [x] Windows UTF-8/path fixes and flake investigation **reported complete on
      `phase 3`**. The flake was not reproduced; the timeout change is only a
      possible explanation, not a confirmed root cause.
- [x] Future `user` product decision documented in `USER_PRODUCT.md`; CV upload
      is explicitly removed from the immediate personal-main roadmap.

### Not done — integration and personal-agent work

- [x] Review and merge the published working-branch changes — done: PRs #31,
      #32 and #33 are merged into `main` (verified in git 2026-10-17).
      Hosted CI status for the merged head should be checked on GitHub before
      release; the live-browser rerun below is still open.
- [ ] Review `phase 3` separately; verify its portability patch on the
      integrated revision rather than duplicating it.
- [ ] Validate the new handoff fix in an authorized live Chrome fill-only rerun
      and fresh image CI before release. Use Regenerate for the previously
      packaged demo, retain step timings, confirm final status and screenshot
      GET 200. The exact slow ATS operation remains unmeasured; do not infer
      confirmation metadata or readback results from the original PNG. No
      intent/submit calls or CAPTCHA bypass authorized by this task.
- [ ] Run real-browser application checks for responsive layout, keyboard/pointer
      behavior, login and enforced CSP. The configured Docker Chromium launch
      smoke is not full application/browser coverage.
- [ ] Verify actual Oracle VM deployment and operational behavior. Prep docs and
      a passing container smoke do not prove the deployed services work.
- [ ] Reduce the recorded vulnerability baseline through tested upgrades. Lock
      installation does not clear existing advisories.
- [ ] Add the cache-backend seam and multi-worker warning (§2.1b), low priority
      while running one worker. Redis is not required now.

### Not done — only before expanding automated submission

- [ ] **Form-structure snapshot comparison:** compare the reviewed form's field
      schema with the fresh submission form and require review again on relevant
      changes. Typed-value readback/repair is already implemented; this is a
      different check. Existing gates catch many changes, but do not explicitly
      compare a structure change that preserves confirmation metadata and still
      fills cleanly. Needed before unattended/high-volume use.
- [ ] **Greenhouse submit-path live verification:** the 2026-10-03 recon was
      initially reported absent confirmation metadata due to a selector/runtime
      blind spot; a read-only 2026-10-16 check found it in Greenhouse's Remix
      loader state, and the extractor now reads it. A strict HTML-to-visible-
      text confirmation comparison was also fixed and fixture-tested. reCAPTCHA
      remains present. Neither the full-path dry run nor any submission was
      performed in that session; the post-submit page has never been observed.
      Continue to follow `LIVE_SUBMIT.md`, human approvals and fail-closed
      gates. This report does not authorize enabling submit or bypassing a
      captcha.

### Deferred / not in the current personal-main scope

CV upload, active-upload switching, profession-aware matching/gap analysis,
user-owned configuration/credentials and database-backed user isolation belong
on the future `user` product track, with no target date. See `USER_PRODUCT.md`.
Lever submit remains deliberately out of scope. No branch creation is authorized
by this checklist.

### Latest recorded verification (2026-10-15)

| Environment | Pytest | Frontend E2E |
|---|---|---|
| Current local lock-only Linux x86-64, including review handoff/polling fix | 1042 passed, 8 skipped | 68 passed |
| GitHub CI run 38743655019, code commit 0971322 | Full API suite passed; raw counts not downloaded | Job passed |
| Native Docker CI in that run, x86-64 + ARM64 | Build/pins/API/auth/Chromium/leak steps passed | Not a dashboard-browser pass |
| Earlier development, before tracker tests, with optional FAISS available | 988 passed, 2 skipped | 36 passed |
| Earlier lock-only Linux x86-64, before tracker tests | 982 passed, 8 skipped | 36 passed |

Current local full run: 1042 passed, 8 skipped, 32 warnings; frontend 68 passed
(36 existing + 22 tracker + 6 environment + 4 review polling tests). Lock-only skips: Lever confirmation copy and
seven optional FAISS-dependent cases. Earlier development skips: Lever and the
optional crawl4ai/playwright-stealth import check. `uv pip check` passes in the
current locked environment. Earlier pin auditing and x86-64/ARM64 dry-run
resolution passed. Docker is unavailable locally, but both native Docker jobs
now passed on GitHub at `0971322`; all five CI jobs are green. Step conclusions
and runner notices were reviewed via the API; raw-log download was blocked.
Oracle deployment remains unverified. Evidence: `deploy/DOCKER_CI_VERIFICATION.md`.
Earlier counts in dated sections below are historical.
2026-10-17 addition: the two new rate-limit boundary regression tests plus the
full rate-limit/auth/proxy/timing suites pass on Windows (85 tests); the full
Linux lock-only suite has not rerun since, so the 1042 figure predates that
fix by exactly those two added tests.

## 1a. Phased roadmap — five-role team audit (2026-10-18)

On 2026-10-18 a read-only audit (software architect, senior dev, software
engineer, junior-dev repo sweep, QA; PM consolidation) reviewed everything
still open against clean `main` @ `dae0f3863`. This section schedules that
audit's output: it adds owners, effort and acceptance criteria to §1's
checklist without contradicting it. **Verdict:** ship-ready after Phases A+B;
production-live after C; submit expansion only through D's gate chain — which
may legitimately dead-end at reCAPTCHA (recorded, never bypassed).

### Key audit findings (evidence for traceability)

- **P0 — live-login landmine:** `docker-compose.yml:152` hardcodes
  `SESSION_COOKIE_SECURE=true` while the documented first deployment is
  bare-IP HTTP (`deploy/DEPLOY_ORACLE.md:86`); browsers refuse `Secure`
  cookies over plain http, so the documented login silently fails live.
  Fix: drop the hardcoded env, rely on auto-detect via `X-Forwarded-Proto`
  (`api/auth.py:850-858`; `deploy/Caddyfile:30` already sets the header and
  the trusted subnet is configured). The TestClient smoke cannot catch this
  (no browser cookie semantics).
- **P0 — dashboard misleads twice:** `frontend/js/navigation.js:67-78`
  double-wires `btnSyncSheets` (fake 800ms spinner + unconditional
  "sync complete" toast beside the real handler at `app.js:51-64`);
  `frontend/js/resumeStudio.js:587-596` claims "Uploaded & Parsed" although
  no upload endpoint exists.
- **P0 — verification debt:** hosted CI green is pinned to commit `0971322`,
  predating the rate-limit, markdown-extraction and `/health` fixes; the
  Linux lock-only figure (1042) is stale by the same fixes; the Windows full
  run's exact failure node IDs were never captured; `ubuntu-latest` begins
  its 26.04 migration on 2026-10-19.
- **P1 — `PUT /api/cv/profile` has zero tests** (`api/routers/cv.py:35-60`;
  `tests/test_api_cv.py` covers only the GETs).
- **P1 — submit claims lack heartbeat/fencing** (`api/apply_claims.py` uses
  a fixed 15-min staleness vs the fill path's heartbeats + 30-min watchdog):
  a hung browser >15 min could allow a second concurrent submission.
- **P1 — ops hardening absent:** no compose healthchecks
  (`/api/health/live` is the intended probe), no log rotation
  (`logs/scraper.log` unbounded + docker json-file defaults), no automated
  `data/apply_submit.db` backup (credential store — loss = lockout), no
  monitoring.
- **P1 — demo fallbacks can mislead:** corrupt demo artifacts served under
  real-looking filenames (`resumeStudio.js:525-560`), `generate()` silently
  falls back to the demo shrink engine on any API error, drawer "Save"
  toasts a bookmark it never saves, `jobDesk` table view has no
  loading/error/empty states, dashboard `_trackerColumn` omits
  `needs_review` (drift vs `tracker.js`).
- **Code stubs:** `agents/scrapper.py:176-178` `days_ago()` returns 0 "to
  bypass filtering for now" (date filtering non-functional); ~12 env vars
  read by code are missing from `.env.example`; obsolete `ALLOWED_COUNTRIES`
  still listed there.
- **Audit-confirmed clean:** mock-data leak paths in `store.js` (none
  shipped), safety-gate architecture (fail-closed, defense-in-depth holds,
  no structural fragility), endpoint test coverage generally excellent.

### Quick wins (≤1h each; land in Phase B unless noted)

| # | Task | Owner |
|---|---|---|
| Q1 | Drop hardcoded `SESSION_COOKIE_SECURE` from compose → auto-detect via `X-Forwarded-Proto` (verified live in Phase C) | Senior Dev |
| Q2 | Multi-worker startup warning in `create_app` (`--workers>1` / `WEB_CONCURRENCY>1`) — the §2.1b seam itself stays unbuilt | Senior Dev |
| Q3 | `.env.example` sync: add `SEMANTIC_WEIGHT`, `KEYWORD_WEIGHT`, `AUTO_APPLY_DAILY_CAP`, `SCRAPER_TIMEOUT`, `SUBMIT_ARTIFACT_DIR`, `SUBMIT_HEADLESS`, `SNAPSHOT_FILE`, `PW_DIAG_LINES`, `JOBSPY_COUNTRY_INDEED/LOCATION/PROXIES`; delete obsolete `ALLOWED_COUNTRIES`; document why `SUBMIT_ENABLED`/`SUBMIT_DRY_RUN` are intentionally absent (armed only via `LIVE_SUBMIT.md`) | Junior Dev |
| Q4 | `hmac.compare_digest` in `api/deps.py:137,361` (unify with `_bearer_matches`) | Senior Dev |
| Q5 | Dead/stale frontend sweep: `store.js:41,242,295`, `tracker.js:437-438`, `resumeStudio.js:226-228`; stop labeling live snapshot data "mock" | Junior Dev |
| Q6 | `api/runs.py:264` raw exception text → `api/errors.py` incident-id pattern | Senior Dev |
| Q7 | `api/review_worker.py` catch `Exception`, not `BaseException` (thread death currently → KeyError → 500) | Senior Dev |
| Q8 | Resolve the `LIVE_SUBMIT.md` 90s-timeout open item (doc reconciliation) | Junior Dev |

**Status update 2026-10-21:** Q1–Q4 and Q6–Q8 are implemented and tested
(`CHANGELOG.md` 2026-10-21 entries; `tests/test_audit_fixes.py` plus updated
contract tests). Q5 (frontend dead-code sweep) remains open. The same pass
implemented the AUDIT.md 2026-10-18 findings: C1 (decision documented, gate
mode logged), C2 (sqrt coverage credit + capped no-core-stack path), C3 (all
nine stub summaries replaced with real card text), C4 (match_reason printed),
C5 (no double-scoring), Bugs 1–5, §6 circuit breaker + board drops + cached
gspread client + yield-per-LLM-call accounting, B8 (functional `days_ago()`
behind `SCRAPER_MAX_AGE_DAYS`, default 0), PM-1 (configurable tier bars) and
PM-2's backend (opt-in `MAYBE MATCHES` tab).
Open from that audit: PM-2 dashboard UI, PM-5 manual review, and the B3
demo-leak e2e suite. **PM-3 is closed (2026-10-28):** real CV variants ship
through `POST /api/cv/upload` into `CV_DIR` (Option A — the existing
CVLibrary machinery is activated; see `CHANGELOG.md` 2026-10-28).

**Status update 2026-10-28:** B1 and B2 are fixed (`CHANGELOG.md`
2026-10-28) — the dashboard's two fake-success claims (double-wired Sync
Sheets toast; "Uploaded & Parsed" for a file that is never uploaded) were
removed at source without building any upload feature, and the first three
concrete B3 demo-leak guard cases landed in `tests/e2e/smoke.test.mjs`.
Frontend E2E is **77 passed, 0 failed** on Windows. During that run the
`environment.test.mjs` Windows EPERM cleanup flake was reproduced on a
clean-HEAD stash baseline (its failing node moved between tests on identical
code — a kill→handle-release race, not app behavior) and fixed in the test
fix in the test harness. Q5, B4, the remaining B3 scope and B5 stay open.
Windows pytest disposition for A2 recorded in `TESTER.md` (2026-10-28):
**1102 passed / 8 env-class failures**, all reproduced on a clean-HEAD
baseline with identical node IDs (no Python touched by this diff); the Linux
lock-only rerun at HEAD (A3) remains the closing gate.

**Review follow-up 2026-10-21 (second review of the same run) — all five
items closed:** title keywords are now derived from the CV's experience
titles when `preferred_titles` is empty (the cached profile carries
`['Software Engineer', 'Full Stack Developer']` today, so the bonus is
live; the hardening covers the empty case); incomplete-description
zero-scores are capped into the maybe range instead of dying at 0;
`\bintegration engineer\b` was removed from the title rejection patterns
(enterprise tool patterns — Mulesoft/SAP/ERP/D365/ETL — retained, so
"Backend Integration Engineer (APIs)" now scores while "Mulesoft
Integration Engineer" is still rejected); `rank_score` is stored on each
job and documented as distinct from `match_score` (CV fit, the gate) and
`ranking_score` (match + freshness); and `CVMatcher.score` returns a
per-job `breakdown` dict so any explanation is checkable against the
numbers that produced it — which also resolved the review's inconsistency
flag (the "title bonus always zero" claim was true only for the
audit-time empty-titles snapshot). No semantic dependencies and no scoring
weight changes, matching the review's own recommendation and the C1
decision above.

### Phase A — Release gate

Goal: `main` provably release-ready — all suites green at HEAD on all
platforms, live fill fix verified, HTTP login fixed.

| # | Task | Owner | Eff | Acceptance | Depends |
|---|---|---|---|---|---|
| A1 | Integrate phase-3 portability: cherry-pick the code hunks of `40e5fc1ab` (nine `utf-8` fixes + url_guard path normalization), drop its stale doc hunks; fix the four latent bare `read_text()` calls | Senior Dev | M | url_guard case RED→GREEN on Windows with `PYTHONIOENCODING` unset; no doc churn | — |
| A2 | Windows full-run disposition: `bash -n` probe guard in `test_docker_locked_dependencies.py`; diagnose CrewAI SDK failures before any skip (they guard the deliberate rollback); rerun with `-rf` capturing exact node IDs | QA | M | Full Windows run classified pass/fixed/justified-skip with node-ID evidence; zero unexplained skips | A1 |
| A3 | Linux lock-only full rerun on current `main` | QA | S | Green; count reconciled (1042 + 2 rate-limit + 16 markdown cases) and explained in TESTER.md | A1 |
| A4 | Fresh hosted CI at HEAD, all five jobs; record the Ubuntu-runner pin-or-ride decision | QA | S | All jobs green at HEAD; decision recorded | PO #3 |
| A5 | Live Chrome fill-only rerun of the handoff fix (runbook in `LIVE_SUBMIT.md`: DB backup, disarmed check, 180s default, Regenerate the packaged demo, stage timings, pending→terminal polling, screenshot GET 200, zero intent/submit calls) | QA | M | Run log with stage timings + screenshot 200; slow step identified; no submission | — |
| A6 | Cookie-secure fix + regression test (Q1): plain-HTTP login sets a non-Secure cookie; proxied HTTPS sets Secure | Senior Dev | S | Test green; compose carries no hardcoded secure env | — |

Exit: A1–A6 done, reviewer APPROVE on the diff, §4 DoD green.

### Phase B — Harden & fix

Goal: the UI stops lying, the highest-value test gaps close, the vuln
baseline ratchets.

| # | Task | Owner | Eff | Acceptance | Depends |
|---|---|---|---|---|---|
| B1 | ✅ 2026-10-28 — Fix double-wired `btnSyncSheets` (`navigation.js:146-157` at fix time): the fake 800ms spinner + unconditional success toast removed; app.js's live handler is the only wiring | Software Engineer | S | Exactly one handler; toast reflects the real outcome — static + behavioral guard in smoke.test.mjs | — |
| B2 | ✅ 2026-10-28 — Fix fake upload success (`resumeStudio.js:587-596` at fix time): no "Uploaded & Parsed"/extraction claims; renders "Selected locally — no upload" and an honest toast | Software Engineer | S | Honest state for a pick without an endpoint; caught by the new B2 guard case | — |
| B3 | Demo-leak e2e suite (+ double-wiring + 401-mid-action recovery cases) — partial 2026-10-28: the 3 fake-success guard cases landed (single-wiring, no-fake-sync-toast, CV-pick honesty); 401-mid-action recovery and the remaining demo surfaces still open | Software Engineer | M | Suite fails on any success-claim without a real API success; runs in CI | B1, B2 |
| B4 | Honest-demo pass: non-real filenames + explicit demo toast for corrupt demo artifacts; no silent `runShrinkEngine` fallback; Save toast, drawer boilerplate and identity panel labeled demo | Software Engineer | M | Every demo path visibly labeled; B3 extended | B3 |
| B5 | Table parity + taxonomy: jobDesk TABLE loading/error/empty states; `_trackerColumn` includes `needs_review`; remove dead `appliedPackagesList` | Software Engineer | S | Table- and taxonomy-parity e2e green | B3 |
| B6 | Tests for `PUT /api/cv/profile` (currently zero) | Senior Dev | S | Happy/invalid/partial-merge cases in `test_api_cv.py` | — |
| B7 | Submit-claim heartbeat/fencing parity with the fill path — or a documented single-supervised-run assumption | Senior Dev | M | Concurrent-claim rejection tested, or sign-off note in `LIVE_SUBMIT.md` before any dry run | A5 |
| B8 | `days_ago()` stub (`agents/scrapper.py:176-178`): restore date filtering per PO #4 | Junior Dev | S | Date filter functional + tested, or bypass documented as deliberate | PO #4 |
| B9 | Backend test/fix bundle: runs-registry watchdog (or documented restart caveat), bad-tab-400 + non-PNG-screenshot tests; `ApplyOut` response_model only after verifying UI review-polling fields survive (PO #5) | Senior Dev | M | Targeted tests green; decision recorded | — |
| B10 | Vuln ratchet wave 1: lxml, pdfminer, then pillow→12.1.1 — one at a time: bounded pin → `uv pip compile --universal` → full suites → docker CI → audit → prune FIXED-only baseline lines | QA | M | Baseline shrinks only via FIXED lines; suites + docker CI green each step | A4 |
| B11 | Vuln ratchet wave 2: crawl4ai→0.8.0 (drives the JS scraper; highest regression risk) | QA | L | JS-rendered scraper smoke passes post-bump; audit rerun | B10 |

Exit: B1–B9 done (B10/B11 may trail), demo-leak suite green, reviewer APPROVE.

### Phase C — Deploy & verify live

Goal: first real Oracle VM deployment, healthy and observed.

| # | Task | Owner | Eff | Acceptance | Depends |
|---|---|---|---|---|---|
| C1 | Compose hardening: `/api/health/live` healthchecks, log rotation (scraper.log + json-file caps), automated `data/apply_submit.db` backup + restore drill, healthchecks.io ping after `run_scraper`, external uptime probe | Senior Dev | M | `compose ps` healthy; restore drill passes; logs capped | A |
| C2 | Oracle deployment + assertion checklist: compose ps healthy; `/api/health/live` 200 in+out; `data_source:sheets`; cookie login over HTTP (validates A6); one Scrape Now e2e; Caddy cert; restart persistence; Chromium launch; no secrets in image | QA | M | Checklist fully green, recorded in §1; deployment status moves "prepared" → "verified" | C1, A6 |
| C3 | Real-browser Playwright matrix: 375/768/1440 viewports, keyboard-only pass, login/idle flow, CSP violation capture (the jsdom blind spot) | Software Engineer | L | Suite green; zero CSP violations; evidence recorded | B4, B5 |
| C4 | Scheduler soak: overlap, exception-survival, `seen_jobs` corruption tests + 24–48h soak on the VM | QA | M | No stuck runs; corruption recovers; soak log archived | C2 |
| C5 | Reconcile §1 + TESTER.md counts and statuses after all verification | PM | S | §1 reflects live-verified state; stale figures replaced | C2–C4 |

Exit: C1–C5 done → production use authorized.

### Phase D — Submit expansion (gated, in order, fail-closed)

| # | Task | Owner | Eff | Acceptance | Depends |
|---|---|---|---|---|---|
| D1 | Greenhouse full-path DRY RUN (`SUBMIT_DRY_RUN=true`, stops pre-click, immediate disarm after) — never executed to date | QA | M | Runbook log: fill→review→metadata-guard→stop-before-click; `SUBMIT_ENABLED` still False | A5, B7 |
| D2 | Form-structure snapshot gate: field-schema hash captured at fill time (`agents/auto_applier.py`), recomputed at submit refill (`api/apply.py`) beside the existing metadata guard; mismatch → 409 `SubmitRejected` → fresh review | Senior Dev (spec: Architect) | M | Shape-only-drift case RED→GREEN; gates unattended use only; supervised path unchanged | D1 |
| D3 | Armed-run decision + post-submit observation: separately-approved armed run; reCAPTCHA outcome recorded honestly — may close the track | PM + QA | S | Decision recorded; zero captcha evasion; post-submit page observed or track closed | D2, PO #2 |
| D4 | Expand to N=3 boards + UI submit-toggle decision | PM | S | Only after D3; toggle decision documented with the field-snapshot caveat | D3 |

### Backlog additions (audit, 2026-10-18)

- a11y bundle (kanban keyboard access, dialog semantics/focus traps,
  `aria-live` toasts, theme persistence, toast queue) — real debt; nothing
  gates on it.
- Orphan-element inventory e2e (would have caught `appliedPackagesList`).
- Sheets quota/backoff fake-gspread tests (429/403 backoff, partial-batch
  resume).
- Idle-timeout e2e (login → expire → 401 → redirect → re-login; modal input
  loss on redirect).
- `api/apply_state.py` DDL-per-connect cleanup — perf nit at this scale.
- Mutable base/uv image tags — accepted; hash-pinning is heavy for a
  personal deploy.
- Lever confirmation-copy test — stays deferred (no paid Lever account).

### Decisions needed from the product owner

1. **Hot badge threshold** — ≥85 (documented) vs ≥70. Recommend: keep 85.
2. **Armed submit at all?** — if D3 confirms reCAPTCHA blocks, close the
   automatable-submit track permanently (keep fill-and-review only).
   Recommend: decide on D1/D2 evidence; default close.
3. **Ubuntu runner** — pin `ubuntu-24.04` for the release window (26.04
   migration starts 2026-10-19), re-ride later. Recommend: pin for Phase A.
4. **`days_ago()` date filtering** — restore, or keep the bypass as
   documented deliberate config.
5. **`ApplyOut` response_model** — recommend leaving the raw dict on
   personal `main`; revisit for the future `user` product.
6. **Submit-claim concurrency** — fund the heartbeat/fencing work (B7) only
   if D3 keeps the track open; otherwise document the single-supervised-run
   assumption.

### Deliberately not doing (audit-confirmed)

No Redis/Celery/cache-backend seam (Q2 warning only), no per-actor rate caps,
no runs-registry persistence; no CV upload or active-upload switching (future
`user` track); no Lever submit path; no `AUTO_APPLY_CONFIRM` revival or blind
CLI submit; no `zhipuai` SDK (`tools/glm_client.py` stays); no captcha bypass
ever; no Scenario B multi-tenancy. Tests never touch live Sheets, LLM APIs or
real browsers; secrets stay out of logs and images.

## 2. Implemented Phase 2 — Action API reference

Goal: dashboard buttons do real work, behind the existing safety gates.

| Endpoint | Backend | Frontend | Safety |
|---|---|---|---|
| `POST /api/scrape` (no params) | background run registry in the API process (single active run → 409 on overlap), writes via curator → Sheets, `POST /api/jobs/refresh` after | `btnScrapeNow` → Scrape Monitor progress → refresh | ✅ done — token required off-localhost |
| `POST /api/apply/{fp}` | Phase 2a fill-and-review: `mode:"review"` only (other modes → 400); dream tier → 422; `AUTO_APPLY_CONFIRM` ignored over HTTP. Greenhouse/Lever use a visible review browser with supported fields filled and pre-submit screenshot; unsupported ATSs get a package only. No submit click. | Cockpit fills up to 3 eligible jobs sequentially, leaves supported ATS windows open for manual review, and shows fill/package outcomes. Submit toggle stays disabled. | ✅ Fill-and-review API; 2b submit remains gated |
| `POST /api/resume/{fp}` | `resume_generator` 1-page tailor → serve PDF path/bytes | Resume Studio replaces static demo | ✅ done |
| `POST /api/cover-letter/{fp}` | `gemini_tools` role-aware letter → serve text/PDF | same package card | ✅ done |
| `PUT /api/cv/profile` | `cache.save_cv_profile` merges Studio edits into on-disk cache | profile Edit/Save panel | ✅ done |
| `GET /api/skills` | aggregate `tech_stack` over a job tab (alias-canonicalized, count-per-job, `pct` of stack-bearing rows) | live skill cloud; `MOCK_SKILLS` path removed | ✅ done 2026-10-03 |

Conventions (from BACKEND.md §6 / existing patterns): schema → `cache.py`
accessor (lazy imports, never crash) → `routers/<group>.py` → tests in
`tests/test_api_<group>.py` (fake `cache.*`, no live Sheets) → `js/api.js` fn →
README table row. Keep `app.py` thin; one router file per group.

### 2b submit gate — explicit rule (not informal)

A submit code path MUST NOT exist anywhere reachable over HTTP until **all
four** gates below are individually implemented and tested. There is no
partial unlock and no "three of four is enough" interpretation. The Auto-Submit
UI toggle remains `disabled`, the existing fill-only API rejects
`mode != "review"` with 400, and `api/safety.py: SUBMIT_ENABLED` remains
`False` until all four gates close.

1. **Verification protocol (2b split):** Greenhouse success requires the post-click URL
   to match the captured `confirmationPath` and the visible page message to
   match the captured `confirmation_message` (both read from public
   page-embedded JSON — no live observation was ever needed). A missing or
   failed verification after clicking is recorded as sticky
   `submit_unverified`, not as success or a retryable failure. Lever stays
   fill-only indefinitely: no Lever submit path exists, and a submit request
   for a Lever-sourced job returns the same 422 "not available for this ATS"
   response as Workday/Workable/Ashby/Breezy.
2. **Claim-first idempotency:** after all three request conditions pass, start
   `BEGIN IMMEDIATE` and insert a `submit_claims` row under the unique
   `job_fingerprint` before any browser work. A duplicate live claim rolls back
   and returns 409 with `retry_after`. A `submit_in_progress` claim older than
   N=15 minutes is lazily expired and its cap slot refunded inside the next
   claim transaction. Terminal states are `submitted` (verified),
   `submit_unverified` (sticky), and `failed_refunded` (pre-click failure only).
3. **Unconditional auth on the apply router:** both new routes require a valid
   Bearer token regardless of global `API_TOKEN` configuration or bind host.
   The manual PATCH reconciliation path for `submit_unverified` claims is
   protected by the same unconditional Bearer requirement.
4. **Triple-condition request gate:** every submit request must pass conditions
   (a), (b), and (c), in that order, in one server-side evaluation before any
   browser interaction. `AUTO_APPLY_CONFIRM` is not a substitute for any
   condition and cannot bypass them. The exact conditions are specified in §2b.3.

No gate is considered closed by documentation or a partial implementation:
each must have its §2b.7 tests passing before the endpoint code in execution
order step 4 is added. 2b has no target date.

### Historical 2b execution status (2026-10-01)

| Step | State | Evidence / remaining work |
|---|---|---|
| 1. F1/F2 Lever fixes | ✅ Done | Posting-page resolution follows `a.show-page-apply` or the current `a.postings-btn[href]` anchor to a validated `/apply` URL; navigation uses `domcontentloaded` and waits for the form selector. Three real postings were fill-only tested with dummy details; all reached `/apply`, filled dummy fields, then exited for custom-question review. No submit click. Fill path unchanged by the 2b split. |
| 2. Lever confirmation observation | ➖ Deliberately out of scope | No Lever trial account will be purchased. Lever stays fill-only indefinitely (fill produces a real screenshot; no submit path). Exact-copy test is now `skip` with reason "Lever submit deferred — no live confirmation-text observation available without a paid account; revisit if a free path is found later". |
| 3. §7 tests | ✅ Done for Greenhouse | Primitives + Greenhouse route suite green: fill matrices, Greenhouse verification matrix, claim-first ordering incl. threaded exactly-one-winner concurrent test, stale-claim expiry, failed_refunded-claim retry, consumed-intent replacement, daily-cap, kill-switch 403s, attachment-gate refusals, score-coercion params, no-click-before-gate, triple-gate (a)/(b)/(c) incl. per-rejection audit-log tests, intent lifecycle, field-readback gate (verified/repaired proceed; mismatch/unavailable/error/missing_required never click) + minimum-profile gate (name first_name/full_name + email required) + review-honesty mapping (missing_required → needs_review blocks intent 409), dream-422, unconditional auth on both new routes + manual-PATCH, full status-code matrix. Last full suite: 291 passed, 1 skipped (Lever documented limitation). |
| 4. Submit endpoint code (Greenhouse only) | ✅ Done, hardened 2026-10-01 | `POST /api/apply/{fp}/intent` + `POST /api/apply/{fp}/submit` implemented in `api/routers/apply.py` → `api/apply.py:create_greenhouse_intent/submit_greenhouse` with Greenhouse URL+message verification (`verify_greenhouse_confirmation`). Intent REUSES the reviewed artifact's tailored resume + cover letter verbatim — it never regenerates materials and never rewrites the artifact, so reviewed == submitted by construction; missing/stale materials fail closed (502, no token). The submit refill reuses exactly those files, requires typed-field readback `verified`/`repaired` plus minimum profile (name + email) plus attachment proof before any click, and fails closed (410) if the resume file is gone or cover text empty. A duplicate intent while one is live is rejected (409) before any expensive work via a read-only pre-check (`live_intent_retry_after`), so it can neither burn generation cost nor mutate the first token's artifact. A Greenhouse fill with missing/unverified required fields is stored/reported as `needs_review` (with `field_verification` + `profile_fields_verified`), never `filled_ready`. Non-Greenhouse platforms raise 422 "Submit is not available for this ATS". `SUBMIT_ENABLED` remains `False`; cockpit Auto-Submit control remains disabled pending separate unlock decision. Intent requires the dedicated `APPLY_API_TOKEN` (`API_TOKEN` is never accepted); no live runs yet (held per operator decision). |

The Step 3 helper modules back the kill-switched submit pair. The dashboard
Auto-Apply Cockpit now uses visible Greenhouse/Lever review windows; each stays
open until its application tab closes (maximum 30 minutes), and the review fill
carries the final tailored materials. The legacy CLI blind submit is permanently
removed, so there is no unverified submit path left anywhere.

## 2.1 Scope decision — personal main vs future user product (2026-10-15)

The previous 3–4 day CV-upload plan is **superseded**. CV upload is not the
next feature for personal `main`. Keep the owner's software-development filters,
on-disk CV workflow, Sheets setup and environment-supplied credentials intact.

### 2.1a CV-upload-first — deferred to the future `user` product

CV upload, active-profile selection and gap analysis move together with
profession-agnostic matching and Scenario B user isolation. Other users may work
in any profession and must supply their own LLM keys and optional Sheets
configuration; they must never silently use the owner's CV, Sheet or API quota.
This requires coordinated backend, frontend, database/storage and secret-handling
work, not a standalone upload button.

**Destination:** a future branch named `user`, not a merge into personal `main`.
**Status:** deferred, no target date; no branch creation or implementation now.
The present documentation work does not change the session branch.

**PO decision 2026-10-28 — §2.1a amended by Option A (shipped).** The all-or-
nothing deferral is reversed for Scenario A only: the personal dashboard
needed a working upload more than it needed the full user lifecycle, and the
library machinery to host uploaded variants already existed, tested. Shipped:
`POST /api/cv/upload` (raw body, no multipart dependency), `CV_UPLOAD_MAX_MB`
server cap, magic-byte + extractability validation ("stored ⇒ readable" —
unreadable input is deleted, never registered), tags-in-filename registration
via the existing `tools/cv_library` extractor, `cvs/` gitignored and mounted
rw in compose, default `my_cv.pdf` untouched. Not shipped (stays with the
`user` branch): per-user ownership, retention/deletion policy, bring-your-own
credentials, profession-agnostic matching. `USER_PRODUCT.md` remains the
canonical future scope.

`USER_PRODUCT.md` is the canonical future scope: deployment-model decisions,
profession-aware matching, ownership-aware persistence, per-user credentials,
onboarding, safe upload/retention, tests and release gates. The old single shared
profile upload acceptance criteria are replaced by that plan. Existing
`CV_PATH`/`CV_DIR`, profile editing and variant behavior remain unchanged.

The cache work below is independent and remains low priority.

### 2.1b Multi-worker cache (small, and only if we ever need it)

**What it is:** the API holds the Sheet cache (90s TTL) in process memory. With
`--workers 1` — what PRODUCTION.md tells you to run — that is correct and
efficient. Start it with `--workers 4` and you get four processes each holding
its **own** copy: up to 4× the Google Sheets calls (quota risk), and two users
hitting the dashboard in the same moment can see **different data** depending
on which worker answers.

**The fix** is moving the cache out of process memory into something shared —
Redis, or a shared file/SQLite — so all workers read and write one cache.

**Do we need it? Almost certainly not right now.** It only matters at
`--workers > 1`, and nothing about current usage (one person, their own
dashboard) requires that. This is a flag for *if* this is ever deployed for
multiple simultaneous users — the same "don't build infrastructure for a scale
problem you don't have" reasoning that correctly deferred Celery and the
Docker queue items.

So the Phase 2.1 deliverable is deliberately **not** "add Redis". It is:

- [ ] A cache backend seam in `api/cache.py` (the TTL store behind a small
      interface) so a shared backend can be dropped in without touching every
      accessor. In-process stays the default.
- [ ] A startup guard: if `--workers > 1` (or `WEB_CONCURRENCY > 1`) is
      detected with the in-process backend, log a loud warning naming the
      consequence (duplicate Sheet reads, cross-worker inconsistency). Failing
      silently into 4× quota burn is the actual risk.
- [ ] Documented in PRODUCTION.md §9b — including that Redis is intentionally
      *not* added until someone needs multi-worker.

Explicit non-goal: standing up Redis now. If that changes, the seam makes it a
contained change rather than a refactor.

### Multi-CV semantic scoring — implemented in working branch (2026-10-15)

Keyword selection, semantic scoring and downstream materials now use the same
selected CV. `CV_DIR`-only and single-`CV_PATH` flows are supported. Embeddings
are cached per resolved CV path with source-content/model/schema invalidation;
CV edits also invalidate parsed-library/pick/keyword-matcher caches. Missing
semantics retain full keyword weight, with no fallback to another CV. Existing
saved scores are not automatically rescored. No CV upload, tenancy, credential
redesign or submit change is included.

Regression coverage: `tests/test_multi_cv_semantic.py` (routing, content/model
invalidation, malformed caches, failure recovery, single-CV fallback, genuine
zero, numerical FAISS and real DOCX extraction with a deterministic encoder).
Sentence-transformer model download/live model quality is not validated here.
At semantic-feature completion: **976 pytest passed, 2 skipped; 36 frontend E2E passed**. Later Docker guards brought development verification to **988 passed, 2 skipped**; see §1.

### Docker locked dependencies — native CI passed (2026-10-15)

Docker now installs `requirements.lock.txt` and checks dependency consistency.
Native x86-64/ARM64 CI matrix builds the image, verifies active installed pins,
non-root API startup, Chromium launch, API/auth behavior and image leaks.
No requirements or lock pins were regenerated for this switch.

Local checks: a fresh Linux x86-64 locked Python environment installed all 179
active pins and passed `uv pip check`; **982 pytest passed, 8 skipped; 36 frontend
E2E passed**. Seven skips require optional FAISS, absent from the lock; one is
Lever's deliberate confirmation-copy skip. `uv` dry-run resolution passed for
Linux x86-64 and ARM64. Those were pre-CI results. Native image builds,
lock/dependency checks, non-root API/Chromium, API/auth suites and leak checks
subsequently passed on both architectures in GitHub run 38743655019 at `0971322`.
The leak inventory now fails closed, with three additional local guards. Oracle
VM operational verification remains pending. See `deploy/DOCKER_CI_VERIFICATION.md`
for exact scope, raw-log limitations and the Ubuntu runner migration notice.

## 3. Backlog

- **Future user product — deferred, no target date:** domain-agnostic matching,
  CV upload, database-backed user isolation, user-owned LLM/Sheets credentials
  and frontend onboarding belong together on a future `user` branch, not in
  personal `main`. No implementation or branch creation now. See
  `USER_PRODUCT.md` and §2.1a for the revised scope.

- **Windows portability — reported complete on `phase 3`, integration pending:**
  explicit UTF-8 reads and Windows path normalization are reported fixed there.
  No matching test-file patch is present in this checkout. Review/integrate that
  branch's changes and verify Windows after integration. The historical
  `test_get_one_and_list` flake passed five isolated runs and the reported full
  suite; its root cause is unconfirmed, so do not label the earlier timeout
  extension a proven fix.

- **CV-upload-first flow — deferred with the user product**, not a scheduled
  personal-agent feature. See §2.1a and `USER_PRODUCT.md`.

- `POST /api/apply/{fp}/intent` and `/submit` are Greenhouse-only and implemented; Lever submit will not be built (fill-only indefinitely). UI toggle unlock stays a separate decision after review.
- **Field-drift guard gap (known limitation, narrowed 2026-10-01):** `_run_greenhouse_submit` refills in a fresh page and the metadata-change guard compares only `confirmation_path/message` + requires `filled_ready`. The refill now verifies typed-field readback (`verified`/`repaired`), minimum profile (name + email), and attachment proof, and the artifact stores `field_verification` + `profile_fields_verified` — so a same-shape posting change that drops/renames fields fails closed instead of passing silently. What remains is pure field-shape drift that keeps identical confirmation metadata *and* still fills cleanly. Accepted risk for supervised single runs with human screenshot review; unattended/high-volume submit use must wait for a field-snapshot diff fix. Any future toggle unlock carries this caveat.
- Kanban `review` column is now backed by fill-only/package statuses (`filled_ready`, `needs_review`, `package_only`, `custom_questions`, …) mapped in `tracker.js` — done 2026-10-01. Tracker interaction/persistence/failure coverage added 2026-10-15 (see §1).
- ~~`by_source` naming (`RemoteOK` vs `RemoteOKAPI`)~~ — **done 2026-10-03**:
  canonicalized at write *and* read (`tools/sources.py`). Scope was wider than
  the ticket: `Remojobs-Frontend/Backend/Fullstack` are Remotive API calls and
  `FounditIN` is configured against naukri.com, so five labels collapsed to
  three providers. Duplicate URLs now fetch once per run
  (`skipped-duplicate`). 15 tests + 1 E2E assertion, mutation-tested.
- **Multi-worker cache → promoted to Phase 2.1b** (see §2.1). In-process TTL
  means `--workers 1`; the Phase 2.1 deliverable is a backend seam + a loud
  startup warning, *not* standing up Redis. Only matters if this is ever
  deployed for multiple simultaneous users.
- ~~Frontend E2E smoke against a seeded API~~ — **done 2026-10-03**: `tests/e2e/`
  (jsdom + real uvicorn, 18 assertions, mutation-tested against 5 real past
  regressions). Playwright/real-browser coverage (CSS, layout, input events)
  remains open — the browser CDN is unreachable from the build sandbox.
- 2b submit stays kill-switched and the UI toggle stays disabled; submit is
  reachable only via the authenticated Greenhouse pair (Lever has no submit path).
  The 2026-10-03 read-only recon's "metadata absent" result was superseded by
  the 2026-10-16 read-only probe: metadata is in Greenhouse's short-lived
  bootstrap script and persistent `window.__remixContext`. The extractor now
  reads the live runtime state, with an all-script fallback. Confirmation
  verification now normalizes HTML/entity/whitespace while preserving strict
  case-sensitive full-message and exact-path checks; mutation-tested fixtures
  cover the regression. Recon found the metadata and submit button, no
  unhandled required fields, and reCAPTCHA. No dry run, armed run, or submission
  was performed in this session. The post-submit page therefore remains
  unobserved and the submit path is not live-verified. The separate user-
  reported 2026-10-15 Chrome fill reached visible attachments but timed out
  before producing an API screenshot record and 404ed at the screenshot URL;
  it made no intent/submit call. Details: `LIVE_SUBMIT.md`.

## 4. Definition of Done (every phase)

1. `python -m pytest tests/` fully green.
2. `node --check` on touched frontend files.
3. Live check: `GET /api/health` + one real request per new endpoint.
4. Docs touched: README table (endpoints), plus BACKEND/FRONTEND/PM status.
5. No secrets committed; no generated artifacts committed (`apply_packages/`,
   `cover_letters/`, `resumes/`, `screenshots/`, `cache/`).

## 5. Scenario A — Multi-Operator Attribution (IMPLEMENTED 2026-10-07)

**Scope:** Shared data, multiple trusted human operators, actions attributed to whoever did them. **Explicitly NOT Scenario B** (no per-user CV, no per-user Sheet/data isolation, no per-user dedup — that's a deliberately deferred future redesign).

**Status:** **Shipped.** All 7 planned steps are implemented and covered by
`tests/test_api_actor_attribution.py` (35 tests). The Step 1 audit table below is
kept as the *before* picture — read it as history, not as current state.

### Step 1 Audit Findings (2026-10-06) — superseded, kept for provenance

| Aspect | State at audit time | State now |
|---|---|---|
| Session identity | `session_user(request)` returns `{"user_id", "username", "expires_at"}` — username **is available** | unchanged; `resolve_actor()` consumes it |
| Apply-gated auth | Checks session cookie **OR** `APPLY_API_TOKEN` (never general `API_TOKEN`). `apply_access_ok()` returns `bool` only — **discards identity** | `require_actor()` / `require_submit_actor()` return the actor string alongside the auth decision |
| Actor columns in DB | **None** — `apply_claims`, `apply_intents`, `apply_review_artifacts`, tracker entries (Sheets) all lack actor/created_by | `actor TEXT` on all three SQLite tables (in-place ALTER, existing history preserved); `created_by` column 13 on the Sheets APPLIED tab |
| Token auth identity | No username — needs sentinel value (`"automation"` or `"api-token"`) | `AUTOMATION_ACTOR = "automation"` for a presented service token; `OPEN_ACCESS_ACTOR = "local-dev"` for open-access mode |
| Precedence (session vs token) | Session checked first in `apply_access_ok()` — **accidental**, not documented | documented and tested: **session wins**, in both `resolve_actor()` and `require_submit_actor()` |

### Implementation Plan — outcome

1. ✅ **`actor` column** added to `apply_claims`, `apply_intents`, `apply_review_artifacts` (SQLite) and `created_by` on the Sheets APPLIED tab. All three SQLite tables upgrade **in place** via `_add_column_if_missing` (`PRAGMA table_info` → conditional `ALTER`); SQLite has no `ADD COLUMN IF NOT EXISTS` and existing deployments hold real apply history that must not be recreated. Tested from the oldest schema.
2. ✅ **`require_actor(request)`** in `api/deps.py`, backed by `resolve_actor()`. Returns `str`.
3. ✅ **Populated on write** at every claim, intent, artifact and tracker create. Service-layer defaults are `AUTOMATION_ACTOR` (the only non-HTTP callers are the CLI and scheduler); **HTTP routes always pass the actor explicitly** so a default can never silently mask a missing identity.
4. ✅ **Precedence documented** in BACKEND.md §4 and ARCHITECTURE.md §4: human session → `username`; service token → `"automation"`; both present → **session wins**.
5. ✅ **`GET /api/activity?limit=N`** — merged, time-ordered, actor-attributed feed.
6. ✅ **Role flag** (`admin` / `operator`) on the users table, settable via `create_user.py --role`. **First user is admin, later users default to operator** — chosen so a mistake in role bootstrapping cannot lock the only operator out of the admin-only submit path.
7. ✅ **Tests**: both auth paths populate an actor; unknown/unauthenticated actor fails closed; the role check is enforced at route level even while the kill-switch still 403s the submit itself.

### Deviations from the plan (all deliberate, all tested)

| Plan said | Built instead | Why |
|---|---|---|
| Gate `/submit` to `admin` via one dependency | **`require_submit_actor`**, not `require_admin_actor` | A service Bearer token has **no role**, so demanding `admin` broke the documented server-to-server submit path with a 403. Rule now: if a session is present it must be admin (**the session wins for authorization too**, matching the attribution precedence); if there is no session, `APPLY_API_TOKEN` yields `"automation"`. Kept separate from the kill-switch dependency so `safety.submit_enabled()` → 403 is still evaluated first. |
| Actor = username or `"automation"` | plus **`OPEN_ACCESS_ACTOR = "local-dev"`** | With no auth configured, `require_token` admits a fresh clone but `require_actor` resolved to `""` and 401'd every write. Checked **last** in `resolve_actor`, and distinct from `"automation"` — the latter means a real service token was presented. |
| Step 5: feed includes tracker changes | **Sheets tracker changes are excluded** | The APPLIED tab stores `created_by` but keeps **no change history**, so "who flipped this row to rejected, and when" is unrecoverable. Recording `created_by` on create is honest; implying the feed shows status changes would not be. |
| — | **`/api/activity` login events are admin-only**, decided from the caller's role (not a query param) | They carry client IPs. `includes_login_events` in the response says why sign-in history is absent for a non-admin. |
| — | Added **`GET /api/health/live`** (unauthenticated, `{"status":"ok"}`, `include_in_schema=False`) | Not in the original plan. Gating `/api/health` for login broke container/orchestrator probes that have no session. A separate router in `_OPEN_ROUTERS` — un-gating the whole health router would leak build/config/state to anonymous callers. |
| Step 1 implied per-operator visibility | **Per-operator daily caps remain impossible** | `daily_apply_caps` is keyed on `cap_date` alone: one **global** budget shared by every operator. There is also a second, per-browser cap in `localStorage['rja_daily_usage']` (`frontend/js/store.js`). Attribution is for **forensics, not enforcement** — recorded in the `claim_first` docstring. Per-operator caps are Scenario B work. |

### Explicitly Deferred — Scenario B (True Multi-Tenancy)

As of 2026-10-15, this is part of the future `user` product together with CV
upload and profession-agnostic matching (`USER_PRODUCT.md`), not an extension
to personal `main`. Shared-data Scenario A remains shipped and unchanged.

| Scenario B Item | Status |
|---|---|
| Per-user CV / CV_DIR isolation | ⬜ Deferred — separate redesign |
| Per-user Sheet/data partitioning | ⬜ Deferred — separate redesign |
| Per-user deduplication (`seen_jobs.json`) | ⬜ Deferred — separate redesign |
| Per-user cache/profile isolation | ⬜ Deferred — separate redesign |
| Per-operator daily apply caps | ⬜ Deferred — needs `daily_apply_caps` re-keyed on `(cap_date, actor)` **and** the browser-local cap removed, or one operator can still exhaust another's budget |

Same gating discipline as Docker/Celery/ML-classifier elsewhere in this doc — not built until explicitly scoped and approved.

## 2b Submit Specification — historical implementation plan

The following preserves the original design/execution order, not current
permission to unlock submit. Current status is §1. Current route authorization
is documented in `BACKEND.md` §4: session or dedicated `APPLY_API_TOKEN`, with an
admin session required for submit and session precedence. Older Bearer-only
wording below is historical. The kill-switch and explicit human approval remain
independent gates; completing helper tests does not authorize enabling the UI.

### 0. Preconditions (must land before any 2b code)

- **F1:** the Lever filler resolves a posting URL to the real `/apply` page by
   following the posting's `a.show-page-apply` href before filling any fields.
- **F2:** navigation uses `wait_until="domcontentloaded"`, followed by an
   explicit wait for a known application-form selector. It must not rely on
   `networkidle`, which can remain pending because of third-party scripts.
- **Lever scope (deliberate):** Lever stays fill-only indefinitely — no trial
   account, no live observation, no submit path. The Lever filler (F1/F2)
   keeps working exactly as today. The exact-copy test is `skip`-flagged as
   a documented limitation, not a blocker.

### 1. Endpoints

- **`POST /api/apply/{fp}/intent`** is review-mode only and unconditionally
   Bearer-authenticated. It returns `{intent_token, expires_at}` only after the
   fill package and screenshot both exist for `{fp}`. Generate the opaque token
   with `secrets.token_urlsafe(32)`. Persist only its SHA-256 hash, together with
   the job fingerprint, `expires_at = now + 5 minutes`, and `consumed = false`.
   There may be only one unexpired intent for a fingerprint at a time; after it
   expires, a fresh intent may be issued for that fingerprint.
- **`POST /api/apply/{fp}/submit`** is unconditionally Bearer-authenticated
   and accepts `{confirm: true, job_fingerprint, intent_token, typed_title}`.
   Conditions §2b.3(a), (b), and (c) must all pass in one server-side
   evaluation, in that order, before any browser interaction. Any failure
   returns its specified status and leaves the browser untouched.

### 2. Claim-first idempotency

Only after §2b.3 passes, begin a `BEGIN IMMEDIATE` SQLite transaction and
insert `submit_claims(job_fingerprint, status='submit_in_progress',
claimed_at, intent_hash)`. `job_fingerprint` is unique. A UNIQUE violation
rolls back the transaction and returns 409 `{retry_after}`; it must not start
browser work. Next reserve a daily-cap slot as specified in §2b.4, then commit
the transaction, and only then begin browser work.

The terminal claim states are:

- `submitted`: ATS verification succeeded.
- `submit_unverified`: the click may have submitted, but success could not be
   verified. This state is sticky and consumes its daily-cap slot.
- `failed_refunded`: a failure occurred before the submit click, so the claim
   failed and its daily-cap slot was refunded.

A `submit_in_progress` claim older than N=15 minutes is lazily expired during
the next claim transaction. Expiry and its daily-cap refund occur in that same
transaction before the replacement claim is inserted.

### 3. Triple-condition request gate

All three conditions are mandatory on every submit request. Evaluate them
server-side in the listed order, in one evaluation, before any browser action.

- **(a) Explicit confirmation and fingerprint echo:** require
   `confirm === true` and exact equality between the body `job_fingerprint` and
   the path `{fp}`. A false/missing confirmation or fingerprint mismatch returns
   400. For every (a) rejection, log the actual ratio, expected value, and raw
   input as described in §2b.6 clarification 1.
- **(b) Intent token:** SHA-256 hash the submitted `intent_token` and compare it
   with the stored hash for this same fingerprint. The stored intent must be
   unconsumed and unexpired. A consumed token returns 409; a missing or expired
   intent returns 410. A token for another fingerprint must not authorize this
   request.
- **(c) Typed job-title confirmation:** compare the typed title against the
   cached job title after normalizing both strings: Unicode NFKD decomposition,
   remove combining marks, casefold, strip punctuation, and collapse
   whitespace. If the normalized expected title has fewer than 4 characters,
   require exact normalized equality. Otherwise accept only when the normalized
   input length is at least `max(4, ceil(len(expected) / 2))` **and**
   `difflib.SequenceMatcher` ratio between normalized input and expected title
   is at least `0.85`. A failed (c) check returns 422. For every (c) rejection,
   log the actual ratio, expected value, and raw input as described in
   §2b.6 clarification 1.

### 4. Daily cap

Reserve the daily-cap slot in the same `BEGIN IMMEDIATE` transaction as the
claim insert. If the current count is already `>=` the configured cap, roll
back the entire transaction, including the claim insert, and return 409 with
`retry_after`. Both `submitted` and `submit_unverified` consume the reserved
slot. Never refund an ambiguous outcome. Refund only `failed_refunded` claims
that failed before click, or stale `submit_in_progress` claims when they are
expired by a later claim transaction. If manual reconciliation determines
that a `submit_unverified` attempt actually failed, the slot is reconciled
through the authenticated manual-PATCH path in §2b.6 clarification 2.

### 5. Verification protocol

- **Greenhouse:** before clicking submit, capture `confirmationPath` and
   `confirmation_message`. After the click, assert that the URL matches the
   captured path and the confirmation message matches the captured message. On
   verified success, set claim status `submitted`; otherwise write sticky
   `submit_unverified`.
- **Lever:** fill-only, indefinitely. No `/submit` code path exists for
   Lever-tier jobs — a submit request for a Lever URL returns 422 "Submit is
   not available for this ATS", the same response as Workday/Workable/Ashby/
   Breezy. The `verify_lever_confirmation` selector/visibility helper remains
   for fill-path completeness only.
- **Dream tier:** always reject with 422; dream-tier jobs are never submitted.
- **Authentication:** Bearer auth is unconditional on both new routes,
   independent of `API_TOKEN` and bind host. The manual PATCH reconciliation
   path uses the same unconditional auth requirement.

### 6. Status codes

| Status | Meaning |
|---|---|
| 200 | Submission verified; claim is `submitted`. |
| 400 | Malformed request or confirmation/fingerprint echo mismatch. |
| 401 | Missing or invalid Bearer authentication. |
| 404 | Unknown job fingerprint. |
| 409 | Claim, active-intent, or daily-cap conflict; include `retry_after` where applicable. |
| 410 | Missing or expired intent. |
| 422 | Dream tier, typed-title rejection, or unverified terminal write. |
| 502 | ATS or verification infrastructure failure. |

### 7. Tests before ship (~35 tests)

All tests use boundary stubs (`FakePage`/`FakeLocator`), temporary SQLite
databases, and no network or real browser. They run before endpoint code is
added. The suite must include:

- Greenhouse and Lever fill matrices: happy path, custom-questions early exit,
   missing submit button, and form-selector timeout.
- Lever F1 regression: posting URL follows its apply anchor to `/apply` before
   waiting for the form or filling any field; direct `/apply` URLs do not need a
   second resolution.
- Greenhouse verification matrix: confirmation path plus message match
   succeeds; wrong/missing path or wrong/missing message fails.
- Lever verification matrix: `.confirmation-message` visible succeeds;
   absent/not-visible confirmation or error DOM fails. The exact success-copy
   assertion is explicitly TODO-flagged until the isolated Step 2 observation;
   it is not silently omitted or treated as passing.
- Claim-first ordering: the unique claim is inserted before any browser work;
   two concurrent claims for the same fingerprint have exactly one winner and
   one 409 conflict.
- Stale `submit_in_progress` claims older than 15 minutes expire lazily and
   refund their reserved slot in the same transaction. Claims at or below the
   15-minute boundary are still live.
- Daily cap: cap exhaustion rolls back both claim and counter; concurrent
   distinct claims cannot exceed the cap; `submitted` and `submit_unverified`
   consume a slot; only eligible pre-click failure and stale-claim expiration
   refund it; ambiguous outcomes do not.
- Every fill-path test asserts `click count == 0`, without exception.
- Set `AUTO_APPLY_CONFIRM=true` in the environment and prove that it changes
   nothing anywhere: the CLI ignores it (blind submit removed) and HTTP
   submit stays kill-switched until the unlock decision.
- Triple-condition tests cover strict boolean confirmation and exact
   fingerprint echo, token hash/fingerprint/consumed/expiry behavior, and typed
   title normalization, minimum-input-length, short-expected-title exact match,
   and the `difflib.SequenceMatcher` 0.85 boundary.
- Audit-log tests prove that every (a) and (c) rejection records actual ratio,
   expected value, and raw input, including requests that fail multiple checks.
- Intent tests prove only one unexpired intent exists per fingerprint, an
   expired intent can be replaced, and different fingerprints are independent.
- Dream-tier rejection is 422. Both new routes and manual-PATCH reconciliation
   require Bearer auth even when global `API_TOKEN` is unset and the server binds
   to localhost.
- Status-code tests cover 200, 400, 401, 404, 409 with `retry_after`, 410,
   422, and 502 outcomes, including that no browser work occurs before the
   triple-condition gate and claim transaction succeed.

The Lever exact confirmation-copy test remains `skip`-flagged as a deliberate
documented limitation (no paid account). All Greenhouse §2b tests must pass
— and do — before the UI toggle is reconsidered.

### Judgment Calls (approved as specced)

- **0.85 threshold**: submit is only permitted when the CV-match / good-fit score ≥ 0.85 (below this → 422, dream-tier manual-application only).
- **short-title equality**: the job title displayed on the ATS page must exactly match (case‑insensitive strip) the title stored in the cached job record; mismatch → rejection with ratio and expected value logged.
- **unverified-consumes-cap**: a `submit_unverified` attempt still consumes one daily‑cap slot; if the human PATCH later determines the claim failed, the slot is refunded only via the manual-PATCH reconciliation path.

### Three Clarifications (answered)

1. **Logging on (a)/(c) rejection:** record actual ratio, expected value, and
   raw input for every rejection, not merely the 422/400 status. If real usage
   later clusters near the 0.85 boundary, these records provide evidence to
   retune from.
2. **Manual-PATCH on `submit_unverified`:** the manual PATCH path is
   unconditionally Bearer-authenticated, the same as the submit route. If a
   human determines the attempt actually failed, this path reconciles/refunds
   the daily-cap slot. Do not refund an ambiguous outcome by another path.
3. **One live intent per fingerprint:** this means one **unexpired** intent at
   a time. A user can request a fresh token after the previous intent expires;
   this is not a hard lockout per fingerprint.

### Execution Order (strict, no shortcuts)

The 2b feature will be shipped in this exact order, with no shortcuts:

1. **F1/F2 Lever fixes** — done and verified with fill-only real-page checks; the current live apply anchor class is also supported. Unchanged by the split.
2. **Lever observation** — deliberately out of scope (no trial purchase). Skip-flagged, not blocking.
3. **§7 tests (Greenhouse)** — done and green (291 passed, 1 skipped). Includes route-level kill-switch/auth/attachment-gate/field-readback/minimum-profile/review-honesty/manual-PATCH/no-browser assertions for the Greenhouse intent/submit pair.
4. **Endpoint code (Greenhouse only)** — done: the two specified routes exist with full triple-gate + claim-first + verification + refill field-readback/minimum-profile/attachment gates. Keep the UI toggle disabled until the Greenhouse submit build is tested and reviewed — that unlock is a separate decision.

After all four close, the UI toggle becomes enabled and the submit opcode is reachable.
