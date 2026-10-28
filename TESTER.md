# TESTER.md — Testing Guide

Mirrors the `tester` subagent (`.opencode/agents/tester.md`). Latest local Linux
lock-only verification (2026-10-16), including tracker/environment/review handoff regressions: **1042 pytest
passed, 8 skipped, 32 warnings** and **68 frontend E2E tests passed**. Skips:
seven optional FAISS-dependent cases and deferred Lever confirmation copy.
Earlier development/lock-only results below predate tracker coverage; optional
dependency availability changes skip counts. See `PM.md` §1. Native Docker
x86-64/ARM64 jobs and all other jobs passed in GitHub CI run 38743655019 at
`0971322`. GitHub job/step metadata and notices were reviewed; raw-log download
was blocked. Local numeric totals above are not inferred CI log counts.
Evidence: `deploy/DOCKER_CI_VERIFICATION.md`; historical counts: `CHANGELOG.md`.

2026-10-17 addition: two rate-limit boundary regression tests pin the
coarse-clock `Retry-After` fix (`api/ratelimit.py`, see `CHANGELOG.md`) — the
full rate-limit/auth/proxy/timing suites pass on Windows (**85 tests**,
including both new boundaries). The full Linux lock-only suite has not rerun
since; the 1042 figure below predates the fix by exactly those two tests.

2026-10-28 note (Windows): frontend E2E is **77 passed, 0 failed** — the 68
figure above predates the design-rebuild smoke additions and three new B1/B2
fake-success guard cases (`npm test --prefix tests/e2e`; all ten suites).
The e2e `environment.test.mjs` Windows-only EPERM cleanup flake was
reproduced on a clean-HEAD stash baseline (failing node moved between tests
on identical code — kill→handle-release race) and fixed in the e2e harness,
not in app code.

2026-10-28 follow-up (Option A run): frontend E2E is **80 passed, 0 failed**
— the 77 baseline plus three CV-upload guards (confirmed-upload contract,
wiring chain, outage fallback). A second EPERM cleanup site in
`environment.test.mjs` (negative-control `finally`) was fixed with the same
retry ladder used by `cleanup()`; the node that failed in the first full run
of the day (`30668ms`, timeout-wait on a locked throwaway dir) now passes in
~8s.

## Windows pytest disposition (2026-10-28) — evidence for PM.md §1a A2

Full local Windows run: **1102 passed, 8 failed, 4 skipped, 275s**. The 8
failures + 1 error are **pre-existing**: re-run against a stash baseline on
clean HEAD with every node ID identical, on a diff that touches no Python
(audit-fix B1/B2, frontend + e2e only). Classification:

- 5 × `tests/test_docker_locked_dependencies.py::test_docker_ci_shell_commands_and_python_heredoc_parse[*]`
  — parse/validate the CI Docker shell script; requires a POSIX `bash`, not
  available locally on Windows. Linux CI gates these.
- 2 × + 1 error `tests/test_crewai_security_compat.py`
  (`test_real_agent_task_and_crew_kickoff_use_only_offline_llm`,
  `test_installed_crewai_metadata_accepts_patched_mcp`) — offline CrewAI/MCP
  wiring against the deliberately rolled-back pinned stack; Linux CI gates.
- 1 × `tests/test_url_guard.py::test_the_scan_actually_finds_sinks`.

So the count supplied for A2's reconciliation: local Windows 1102 passed /
8 env-class failures; the Linux lock-only rerun at HEAD (A3) remains the
number that closes the release gate.

### Option A disposition (2026-10-28, cv-upload run)

Full Windows run with `POST /api/cv/upload` + `tests/test_cv_upload.py`
(23 new isolated cases): **1124 passed, 4 skipped** — +1102 baseline = the
new tests, and the failure set proved pre-existing:

- The 8 env-class failures + 1 error above reappeared **node-identical**.
- One first-run failure was self-inflicted and fixed in the test, not the
  app: `test_ingest_stays_off_the_heavy_pipeline` inspected global
  `sys.modules`, so it tripped when earlier files imported crewai. It now
  asserts the **delta** of modules introduced by the ingest itself, and an
  adversarial ordering run
  (`pytest tests/test_crewai_security_compat.py tests/test_cv_upload.py`)
  passes with crewai already loaded.
- Observed once across full runs, never in isolation:
  `test_action_rate_limit.py::test_a_denied_call_reports_how_long_to_wait`
  failed in one full-suite run while passing in two others (same app code)
  and passes isolated — file `32/32`, node twice consecutively. The
  assertion times a wait report, so full-suite load on Windows can starve
  it; recorded as a timing flake, not a behavior regression. Linux CI
  remains the arbiter.

### 2026-10-28 pip-audit wave (fpdf2/litellm upgrades + pillow re-key)

- `deploy/dependency_audit.py`: **OK — 82 findings, all in the baseline,
  nothing new** (run before and after the baseline restore edit). The wave:
  `fpdf2 2.7.9→2.8.8` + bounded direct `litellm==1.100.4` clear three real
  findings; the 11 pillow PYSEC entries (ten verified per-ID against OSV as
  re-keys of pruned CVEs, plus CVE-2026-112403 as new cover) are accepted
  with the decision trail in the baseline header. Lock recompiled
  (`uv pip compile --universal`); venv synced to both new pins and verified
  via import (`fpdf2 2.8.8`, `litellm 1.100.4`).
- `UnicodePDF` render smoke (the only fpdf2 consumer, `tools/font_utils.py`)
  passes on 2.8.8.
- Full Windows pytest with the upgraded pins: **1126 passed, 4 skipped,
  8 failed + 1 error** — the failure set again node-identical to the
  env-class baseline (5× docker heredoc, 2+1 crewai, 1 url_guard). The
  `test_action_rate_limit` timing node has now passed in both of the last
  two full runs.

### B4/B5/Q5 disposition (2026-10-28, frontend demo-honesty run)

Backend delta this slice is `api/cache.py` docstring text only; every other
change is frontend JS, `index.html` metadata (labels + `?v=10` stamps for the
edited store/dashboard/jobDrawer assets) and e2e material.

- **Frontend E2E: 85 passed / 0 failed, twice consecutively** with the
  B4/B5/Q5 diff applied — the 80 baseline plus five new guards (B4 ×3:
  persistent failure reason on the demo card with "unreachable"
  misattribution banned; drawer tailor-target effect with the phantom
  "bookmarked" copy banned; honest package-download refusal. B5:
  column-parity mapping incl. `needs_review → review`. Q5: "fallback to
  mock" banned from live-loader sources). One earlier 85-node run showed a
  single failure: `TypeError … getElementById` at `app.js:51` inside
  `environment.test.mjs`'s boot test — a jsdom window closed while app.js's
  `await store.loadAll()` continuation was still pending. Not reproduced on
  a clean-HEAD stash run (80/80); the harness now settles 300 ms before
  `ctx.window.close()`, and the two follow-up full runs went 85/85.
  Harness-only fix; app code untouched.
- **Windows pytest full run: 1125 passed, 4 skipped, 8 failed + 1 error** —
  the failure set is node-identical to the recorded env-class baseline (5×
  docker heredoc, 2+1 crewai, 1 url_guard). The `test_action_rate_limit`
  timing node passed this run, consistent with its flake classification
  above (failed 1 of 2 full runs, passes isolated and under load
  elsewhere). Linux CI remains the arbiter.

Security/CI remediation: `deploy/CI_FAILURE_REMEDIATION.md`. A fresh **168-package**
locked installation passes dependency consistency. CrewAI is deliberately rolled
back to 1.6.1 so patched MCP 1.30.0 satisfies its real metadata. Seven offline
SDK checks cover factory construction, kickoff, provider-adapter construction
and security pins; six failure-reporting checks preserve failed gates. The
existing JSON-repair advisory is retained on 0.25.2, not claimed fixed. Live
provider behavior is not verified by these offline checks.

Coverage includes `test_api_phase1.py`,
`test_api_phase2.py`, `test_api_cv.py`, `test_api_materials.py`,
`test_api_freshness.py`, `test_api_jobs_contract.py`, `test_auto_applier.py`,
`test_country_filter.py`, `test_api_apply.py`,
`test_apply_submit_primitives.py`, `test_resume_generator.py` (prompt
grounding, footer strip, out-param), `test_api_skills.py`,
`test_source_naming.py`, `test_submit_dryrun.py`, `test_submit_recon.py`,
`test_scraper_timeout.py`, `test_glm_client.py` (golden vectors +
consumer wiring), `test_action_rate_limit.py` (per-actor budgets and
coarse-clock `Retry-After` boundaries), `test_api_auth.py`,
`test_api_auth_hardening.py`,
`test_api_actor_attribution.py`, and the PR #26 security suites
(`test_content_security_policy.py`, `test_embedding_cache.py`,
`test_url_guard.py`, container-hardening, TLS-verification,
proxy-header-trust, session-idle-timeout, login-timing).

## Markdown extraction list-field regression coverage (2026-10-17)

A dashboard scrape died post-scrape with `AttributeError: 'list' object has no
attribute 'strip'`: the Gemini answer to `extract_jobs_from_markdown` carried
`"tech_stack": ["Python", ...]`-style arrays, and `is_valid_dev_job()` (then the
dedup fingerprint) called `.strip()` on the list. Fix is two layers:
`agents/gemini_tools.py` coerces every extracted field to text at the LLM
boundary (`_coerce_text`/`_normalize_extracted_job`), and
`agents/curator.py::sanitize_string_fields` flattens None/list/scalar values
in place before any consumer runs (previously None-only).

`tests/test_markdown_extraction.py`: **16 cases** covering coercion shapes,
schema normalization, monkeypatched LLM responses (fenced, non-array, empty
markdown) and the exact crash path through `is_valid_dev_job` +
`job_fingerprint`. Also two harness fixes: `test_glm_client.py` source-reading
tests now pass `encoding="utf-8"` (cp1252 default broke them on Windows —
verified failing on clean HEAD), and `test_api_phase1.py`'s
`test_no_heavy_imports_at_startup` asserts on modules *added* by the request
(snapshot) instead of absolute `sys.modules` absence, which any test importing
`agents.curator` at collection time would otherwise break by file order.
Touched suites: 164 passed, 7 skipped. Full local Windows run: 7 failed,
5 errors — identical on stashed HEAD, all environment-specific (Docker CI
parsing, CrewAI SDK, timing); Linux CI remains the gate.

`/health` liveness alias: an external poller (no repo code, current or
historical, calls it — the dashboard has always used `/api/health`) was
logging a 404 every few seconds. `api/routers/liveness.py` now serves the
identical `{"status": "ok"}` payload at both `/api/health/live` and
`/health` (same ungated router, same deliberately-empty disclosure), pinned
by `test_health_alias_serves_open_liveness`. Live-verified against a running
uvicorn: `/health` 200, `/api/health/live` 200, `/api/health` still 401.

## Review timeout and late-result regression coverage (2026-10-15)

`tests/test_review_handoff.py`: **20 cases** use real routes, worker threads,
SQLite ownership and screenshot serving over fake material/browser boundaries.
Event barriers force a foreground timeout without waiting 90/180 seconds. Tests
prove that pending completion later serves the correct image with preserved
confirmation/readback/material/actor metadata; duplicate/regenerate attempts
cannot double-fill; different jobs and attempts cannot mix evidence. They cover
claim renewal, stale/crashed runs, watchdog expiry/newer retry, persistence
failure, auth, unavailable required-field verification and timeout configuration.
Screenshot names use UUID suffixes to avoid simultaneous fills sharing a path.
A deterministic completion/release interleaving proves status reads use a single
SQLite snapshot (confirmed RED without the guard, GREEN with it), avoiding a
false "worker stopped" result at successful completion.

`tests/e2e/review.test.mjs`: **4 real-dashboard checks** over a fake review
transport prove queue/Regenerate waits for the same run ID, late screenshot
presentation, no automatic POST retry on polling failure, and bounded UI waits.
Real route/SQLite handoff is covered by the Python cases, not claimed for these
transport fakes. npm/shell/CI entrypoints include this file.

Current local full suites: 1042 Python passed, 8 skipped; 68 frontend passed.
No live ATS or native Docker rerun was performed for this local fix; previously
recorded image CI applies to its named earlier commit, not these new edits.
The reported original fill's exact slow step remains unknown. The demo board's
confirmation metadata has since been independently recovered; see the regression
record below.

## User-reported live fill-only check (2026-10-15)

A separate Playwright/real-Chrome run against Greenhouse's public Democorp demo
was reported by the user, with a supplied screenshot showing populated contact
fields and resume/cover-letter attachments. **Not submitted:** no intent/submit
calls, submit click or reCAPTCHA bypass reported; external AI keys were disabled.
The API nevertheless timed out after 90 seconds and its screenshot URL returned
404 despite a reported PNG on disk. This is partial live visual evidence, not
a passing API flow, automated browser suite, full submit-path dry run or proof
of deployed dashboard behavior. Exact timing/root cause remains unconfirmed.
See `LIVE_SUBMIT.md` run log and the open issue in `PM.md` §1. No live rerun or
runtime code change was made for this documentation update; test counts below
remain the preceding automated results.

> **Windows status:** the UTF-8/path fixes and flake investigation were reported
> completed on `phase 3`. They are not integrated into this checkout. Review and
> verify that patch on Windows after integration. The flake was not reproduced;
> its cause remains unconfirmed. See `PM.md` §1 and §3.

---

## Greenhouse confirmation regression (2026-10-16)

`tests/test_apply_submit_primitives.py` covers the actual HTML-formatted
confirmation message read from `tests/fixtures/greenhouse_remix_confirmation.html`
and rejects an empty normalized expected message. Before the verifier fix, the
new fixture and empty-message cases failed (**2 failed, 84 deselected**); after
the fix they passed (**2 passed, 84 deselected**). The targeted primitive +
recon suites passed **101 tests, 1 skipped**.

The full-suite result recorded above is the Linux lock-only baseline, not a
result for the current Windows checkout after these edits. A Windows run of
`venv\Scripts\python.exe -m pytest tests -q` reported **22 failed, 1028 passed,
4 skipped, 1 teardown error** in 281.18s. Failures include WSL `/bin/bash`
unavailability in five Docker shell tests, Windows path separator assumptions
in a URL-guard test, default-codepage `UnicodeDecodeError` in GLM consumer
tests, CrewAI network/version environment failures, and a rate-limit boundary
result of 601 seconds versus a 600-second assertion. PyArrow also emitted a
Windows fatal access violation during import. The rate-limit boundary failure
was subsequently fixed on 2026-10-17 (coarse-clock rounding in
`api/ratelimit.py`; see `CHANGELOG.md`) and is covered by two boundary
regression tests. These remaining environment failures were
not fixed or hidden; targeted regression/recon tests pass. No dry run, form
fill or live submission was performed. See `LIVE_SUBMIT.md` for the evidence
and remaining uncertainty about actual post-submit confirmation.

---

## Tracker/Kanban regression coverage (2026-10-15)

- `tests/e2e/tracker.test.mjs`: **22 interactions** against the real dashboard,
  FastAPI routes, cache resolver and `mark_applied`/`update_status`. Only the
  Sheets/personal-data boundaries are replaced in the opt-in
  `tests/e2e/tracker_api.py` subprocess. Synthetic rows are temporary/in-memory;
  the user's Sheet, credentials and CVs are never used by this fixture.
- Covers column/count/review mapping, terminal no-op, status transitions,
  notes preservation, fresh-page persistence, URL-only keys with both real header forks (including encoded
  URL components), pending/double-click protection, HTTP/network/write errors,
  Sync failures/recovery, escaping and manual-add validation/save/failure/retry.
  A confirmed write followed by a failed GET reports saved-but-not-refreshed;
  manual creation closes the modal rather than inviting a duplicate retry.
- `tests/test_api_tracker_contract.py`: **22 cases** for encoded URL/fingerprint
  routing, status whitelist/normalization, explicit notes, authentication and
  error contracts; also guards test-control isolation and all E2E entrypoints.
- Two regressions were observed failing before fixes: a refused write still
  moved a card locally, and a URL-keyed row appeared moved without saving.
- `npm test --prefix tests/e2e`, `./tests/e2e/run.sh` and frontend CI all run
  smoke + tracker suites. Fixture controls do not exist in the production app.

Focused runs:
```bash
python -m pytest tests/test_api_tracker_contract.py -q
node --test tests/e2e/tracker.test.mjs
```

This is jsdom + real HTTP/API coverage, not a native-browser, live-Sheets or
across-server-restart persistence test. Real input/layout/CSP and deployment
verification remain pending. Submit stays disabled.

## Per-CV semantic regression coverage (2026-10-15)

At semantic-feature completion (before Docker regression guards): **976 passed, 2 skipped**;
frontend E2E: **36 passed**. Skips: deferred Lever confirmation-copy test and
optional crawl4ai/playwright-stealth import check (neither installed locally).
FAISS and python-docx were installed for all 52 new regression cases.

`tests/test_multi_cv_semantic.py` runs the real selection/curation/cache logic
with local deterministic extraction/encoding boundaries, never Sheets, LLMs or
model downloads. It covers cross-CV routing, same-size edits, model/schema
invalidation, corrupt/legacy cache rejection, write failures, retry behavior,
keyword renormalization, genuine zero and existing single-CV behavior. Numerical
FAISS tests run when FAISS is installed; the real DOCX extraction test requires
python-docx. These optional checks skip explicitly when their dependencies are
absent. No claim is made about a live sentence-transformer model's match quality.

## Locked Docker verification (2026-10-15)

`tests/test_docker_locked_dependencies.py` guards lock installation, copy-before-
install ordering, exact pins/Windows markers and the native Docker CI matrix.
Static tests also parse the CI shell/Python probes; they do **not** build images.
CI builds on `ubuntu-latest` (x86-64) and `ubuntu-24.04-arm` (ARM64), then checks
installed pins and dependencies, non-root API startup, Chromium launch, API/auth
behavior and image leaks. Full source-scanning tests remain in the API CI job:
`.github` and `.git` are intentionally excluded from runtime images.

At Docker-lock completion, before tracker regressions, the fresh local lock-only
environment passed **982 pytest, 8 skipped; 36 frontend E2E**. All 179 active x86-64 pins match installed distributions. Seven skips
are optional FAISS checks (not installed by the lock), plus the deferred Lever
confirmation-copy test. These were pre-CI results. Native Docker x86-64 and
ARM64 build/pin/dependency/API/auth/Chromium/leak steps subsequently passed in
[GitHub run 38743655019](https://github.com/Mubashirahmad123/remote-job-agent/actions/runs/38743655019)
at `0971322`. The image inventory now fails closed on export/listing errors or
empty output; three injected-failure tests pass. Current local Docker-related
preflight at that review: 63 passed; then-full suite: 1007 passed, 8 skipped.
Raw CI logs could not
be downloaded; reviewed step metadata and scope/limits are recorded in
`deploy/DOCKER_CI_VERIFICATION.md`. Oracle VM deployment remains unverified.

## 1. Running tests

```powershell
$env:PYTHONIOENCODING = 'utf-8'   # required on Windows (emoji prints)
venv\Scripts\python.exe -m pytest tests/ -q            # full suite
venv\Scripts\python.exe -m pytest tests/test_api_phase1.py -q   # one file
```

Frontend syntax gate:
```powershell
node --check frontend\js\store.js; node --check frontend\js\api.js
```

Frontend E2E smoke + tracker (real `index.html` + real `js/*` in jsdom, driven against a
real uvicorn seeded with `SNAPSHOT_FILE`):
```bash
./tests/e2e/run.sh          # first run does `npm install` (jsdom) automatically
```
Ten suites — asset integrity, happy path, API-unreachable, login flow, header
layout contracts, three tracker suites (rendering/persistence, failures, manual
applications), and two environment-isolation suites, plus four standalone
review-polling checks. It catches the
class of bug the pytest suite structurally cannot: a `<script>` that 404s, a
guard on an undefined global, an error state that is unreachable, a widget that
renders empty everywhere. Mutation-tested against five real regressions from
this repo's history (table in FRONTEND.md); each one fails the suite.

Automated-suite gap: no real browser here (the Playwright browser CDN is
unreachable from this coding sandbox), so CSS/layout/visual and real input
coverage remain pending. The separate user-reported Chrome fill-only smoke
above does not close dashboard/browser-suite or API timeout/artifact gaps.

### E2E `.env`/authentication caveat — retired with evidence (2026-10-15)

`tests/e2e/environment.test.mjs` adds **6 targeted checks**: two dummy `.env`
styles (plain tokens and `API_TOKEN=  # trailing-comment`), each tested with a
historical negative control, current open-mode harness and current login mode.

| Scenario | Stats before CV import | Cached CV profile | Stats after CV import |
|---|---|---|---|
| Negative control: auth keys missing from environment | 200 | 200 | 401 |
| Current harness: auth keys explicitly empty | 200 | 200 | 200 |
| Current authenticated harness, using its login session | 200 | 200 | 200 |

The negative control proves the documented mechanism: `tools.cv_parser` is
initially absent, then the real `/api/cv/profile` cache reader imports it and
its module-level `load_dotenv()` loads dummy tokens, changing subsequent auth.
It is not a stats bug. The current harness already prevents this by setting
`API_TOKEN=''` and `APPLY_API_TOKEN=''` **before** bootstrap/server startup:
python-dotenv's default `override=False` preserves present-but-empty values.
Deleting those keys is not equivalent and reintroduces the failure.

The tests copy Python/frontend source into disposable projects and create a
dummy `.env`, synthetic CV cache anchor and fresh cached profile. A successful
profile read prevents a false green caused by the missing-CV early return.
They also test inherited dummy shell tokens, real dashboard boot/counts/no
login redirect, general/apply token refusal, required session login and DB
cleanup. Negative-control output is statuses/booleans, never credentials.
No real `.env`, personal CV, credentials, Sheet or LLM is used by these tests.

The protected scenarios use the real uvicorn harness, including its temporary
auth/apply DBs and pinned job snapshot. The negative control uses real API
routes through TestClient inside its disposable subprocess. All six checks
pass, including with a relative `RJA_PYTHON` interpreter path. They run from
npm, the shell runner and frontend CI; focused run:
```bash
node --test tests/e2e/environment.test.mjs
```

This retires the specific late-dotenv/auth warning, not every possible developer
configuration issue. Production auth and dotenv behavior are unchanged; never
copy test-only empty auth pins into an exposed deployment. Native Windows,
real-browser and deployment verification remain separate.

Live smoke (reads only, real app, no fakes):
```powershell
venv\Scripts\python.exe -m uvicorn api.app:app --host 127.0.0.1 --port 8000
# /api/health -> data_source, /api/jobs?limit=1, /api/stats, /api/tracker
```

## 2. Iron rules (no exceptions)

- **No live Sheets, LLM APIs, or real browsers in automated tests.** Supervised
  live smoke checks are separate, opt-in run-log evidence. Stub at the boundary:
  fake `api.cache._read_tab_values` / `_load_enrichment_map` (Phase 1 pattern),
  stub the LLM fallback chain, stub Playwright.
- Isolated units with temp dirs; scratch scripts only under
  `C:\Users\Mubashir1\AppData\Local\Temp\opencode`.
- Back up `data/job_agent.db` before any run touching SQLite.
- Never modify product code to make a test pass — send failures back.
- Never print `.env` values, keys, or sheet IDs (in tests or reports).

## 3. Writing tests (convention)

- Location/name: `tests/test_<module>.py`; classes `TestXxx`, methods `test_<behavior>`.
- Every new endpoint/helper gets **happy-path + failure-path** cases
  (see `test_api_phase1.py`: list + bad-tab-400, patch-ok + patch-400/404).
- API tests use `fastapi.testclient.TestClient(create_app())` with monkeypatched
  cache fakes; assert status codes + key fields, never live data.
- Current apply safety probes:
  `POST /api/apply` with `mode != "review"` → 400; kill-switch probes assert
  `/intent` + `/submit` → 403 while `api/safety.py SUBMIT_ENABLED=False`
   (flip via monkeypatch for the live-path tests). Attachment-gate probes prove
   the refill refuses to click without `resume_attached` + cover proof;
   field-readback probes (`mismatch`/`unavailable`/`missing_required` never
   click) and minimum-profile probes (no-profile/no-email/no-name never click,
   `full_name`+email passes) guard the submit gate, and fill-review probes prove
   `missing_required` maps to `needs_review` (which blocks intent with 409).
   Primitive tests include threaded duplicate
  claim and daily-cap races, consumed-intent replacement, and
  failed_refunded-claim retry. Auth is unconditional on both submit routes;
  no-browser-before-gate route tests guard the triple gate. The apply API tests
  stub the browser boundary; they do not launch actual ATS pages. PDFs verified
  1-page via pdfplumber.
- Report timings for anything >60s or touching network; cite `file:line`
  with actual vs expected.

## 4. Definition of Done (tester verdict)

Itemized per phase: suite result with counts, new tests added, slow/flaky/
env-dependent notes with `file:line`, then **GO / NO-GO**. One unexplained
failure = NO-GO, stated plainly. (Same checklist as `PM.md` §4.)
