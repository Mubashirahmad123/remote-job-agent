# TESTER.md — Testing Guide

Mirrors the `tester` subagent (`.opencode/agents/tester.md`). Latest local Linux
lock-only verification (2026-10-15), including tracker and environment regressions: **1007 pytest
passed, 8 skipped, 32 warnings** and **64 frontend E2E tests passed**. Skips:
seven optional FAISS-dependent cases and deferred Lever confirmation copy.
Earlier development/lock-only results below predate tracker coverage; optional
dependency availability changes skip counts. See `PM.md` §1. Native Docker
x86-64/ARM64 jobs and all other jobs passed in GitHub CI run 38743655019 at
`0971322`. GitHub job/step metadata and notices were reviewed; raw-log download
was blocked. Local numeric totals above are not inferred CI log counts.
Evidence: `deploy/DOCKER_CI_VERIFICATION.md`; historical counts: `CHANGELOG.md`.

Coverage includes `test_api_phase1.py`,
`test_api_phase2.py`, `test_api_cv.py`, `test_api_materials.py`,
`test_api_freshness.py`, `test_api_jobs_contract.py`, `test_auto_applier.py`,
`test_country_filter.py`, `test_api_apply.py`,
`test_apply_submit_primitives.py`, `test_resume_generator.py` (prompt
grounding, footer strip, out-param), `test_api_skills.py`,
`test_source_naming.py`, `test_submit_dryrun.py`, `test_submit_recon.py`,
`test_scraper_timeout.py`, `test_glm_client.py` (golden vectors +
consumer wiring), `test_api_auth.py`, `test_api_auth_hardening.py`,
`test_api_actor_attribution.py`, and the PR #26 security suites
(`test_content_security_policy.py`, `test_embedding_cache.py`,
`test_url_guard.py`, container-hardening, TLS-verification,
proxy-header-trust, session-idle-timeout, login-timing).

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
preflight: 63 passed; full suite: 1007 passed, 8 skipped. Raw CI logs could not
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
applications), and two environment-isolation suites. It catches the
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
