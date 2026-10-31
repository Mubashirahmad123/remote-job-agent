# TESTER.md — Testing Guide

## 2026-10-31 — scrape progress and fill-review regressions

The `feat/fix` report below is historical evidence from the user's Windows
run. Its `logs/realtest/` files are gitignored and were not available in this
checkout. The fixes below were tested on Linux with the locked Python packages
and an **offline synthetic Chromium form**, not on the live Greenhouse demo or
Windows. No live scrape, Sheets write, ATS request, or application was sent.

Validation on this checkout: **1,249 Python tests passed, 23 skipped** (15 of
those are the opt-in browser cases); **91 frontend/HTTP tests passed**; and
**15 offline Chromium tests passed** when opted in. `pip check`, bytecode
compilation and `git diff --check` also passed. The new Docker Chromium CI
step was not run locally because Docker is unavailable here.

- **B1:** API, CLI and scheduler harden stdout/stderr independently while
  preserving the parent stream encoding; non-encodable characters are escaped.
  Package/form diagnostics use logging. A subprocess regression exercises
  `PYTHONIOENCODING=cp1252:strict` with UTF-8 mode disabled, including a worker
  thread and the package error path. Docker explicitly enables Python UTF-8.
- **A1:** progress plans include configured board entries **and** the three
  synthetic JobSpy/Playwright/Crawl4AI work items. They are not three additional
  independent boards. The monitor snapshots tracker rows before iterating; a
  no-network `scrape_all` orchestration test checks emitted rows against the plan.
- **I2:** bounded fresh-DOM readback distinguishes matching file inputs from
  a visible, field-scoped filename/remove chip and from missing, mismatched or
  unreadable inputs. Success requires two consecutive observations 400ms apart;
  fields are checked again after file settling. API and CLI review outcomes
  apply the same policy, and the dashboard exposes the evidence; missing
  materials become `needs_review`. A chip is UI evidence **only**: the separate
  Greenhouse submit refill still requires a matching native file input or full
  cover-text readback before it may click. Ambiguous inputs are not selected.
- **Safety:** ATS detection now checks the actual hostname, not a lookalike host,
  URL path, query or user-info. Authenticated health and startup logs report
  the effective `disarmed` / `dry_run` / `armed` submit mode; the environment
  can arm it, so a false module constant alone is not evidence of disarming.
  TestClient and real-HTTP Uvicorn tests authenticate with dummy credentials
  and dynamically assert disarmed intent/submit return 403 before browser work.
- **Q1:** no upstream playwright-cli defect is asserted or changed; the Windows
  quote observation remains an unisolated harness issue.

Browser regression command (no external requests; Docker CI runs it with
`--network none`):

```bash
RUN_OFFLINE_BROWSER_TESTS=1 python -m pytest tests/test_attachment_browser.py -q
```

Chromium must be installed for that opt-in command; the ordinary pytest suite
skips those cases. Its fake form exercises input removal, visible/hidden/wrong
chips, wrong filename/size, a dropped input, ambiguous inputs, post-upload
field repair, attachment loss after repair, Lever cover truncation and the
no-click invariant. These fixtures do not prove the current live site's DOM or
server-side upload acceptance. Matching filename and size also does not prove
byte-for-byte file identity.

### Required supervised Windows follow-up (not performed here)

1. In a new process explicitly set `SUBMIT_ENABLED=false` and
   `SUBMIT_DRY_RUN=false`, then check authenticated `/api/health` reports
   `submit_mode: disarmed`. Probe `/intent` and `/submit` with the appropriate
   auth and confirm 403 before any form testing; recheck health after a fill
   because lazy `.env` imports can otherwise change unset environment values.
   Do not use live submission.
2. Start with `PYTHONUTF8=0` and `PYTHONIOENCODING=cp1252:strict`, redirect
   stdout/stderr, and exercise package creation and a fill-only review; confirm
   the run completes and logs are readable. Restore environment variables after.
3. With explicit permission, use the demo posting and isolated snapshot/data
   files (back up/restore any existing snapshot before seeding). Check the exact
   resume/cover verification states, screenshot, and `review-status` result.
   `ui_confirmed` is not native-input proof; keep submit disarmed. Restore live
   Sheets configuration and the original snapshot after the rehearsal.

Architectural follow-up: measure direct ATS-URL prevalence across scrape
cycles before changing sourcing; a single zero count is not proof of a scraper
bug. Redirect resolution needs SSRF and rate-limit review. The existing
30-minute review watchdog fences stale writes but cannot kill a hung browser
thread; true cancellation needs process isolation, not just a shorter wait.
Two-key submit arming is a separate compatibility-sensitive policy decision and
was not silently introduced in this fix.

## 2026-10-30 — real E2E scrape + fill + playwright validation (run fbd2c54f337c)

Live server on Windows (uvicorn + venv), scrape cycle `POST /api/scrape` run_id `fbd2c54f337c` completed 2026-10-30:
- fetched 481, scraped 178, boards_ok 26 / empty 20 / failed 0, phase done
- Sheets write verified: ALL JOBS grew from 54 → 74 (+20 new rows)
- Sources post-run: Arbeitnow 41, Shine 11, JustJoinIt 4, Jobicy 4, DailyRemote 5, WeWorkRemotely 2, NoFluffJobs 2, RemoteOK 1, WeAreDevelopers 1, Arc/Remotive/Adzuna 1 each
- Zero Greenhouse URLs found → demo seed used for fill path

Fill paths validated live:
- Package-only (Mistral.ai Arbeitnow 84): `package_only` with tailored resume/cover generated.
- Greenhouse demo (Democorp 83446 seeded via `tools/seed_demo_job.py`, JOBS_SOURCE=snapshot): `filled_ready`, field_verification verified (first/last/email/phone), screenshot captured. Resume generation fell back from Gemini 503 to Groq; the cover used Gemini directly. No submission was observed; 403 routes were not dynamically probed in that run.
- Independent playwright-cli cross-check on real Greenhouse form: core fields read back, resume + cover shown as attached, screenshot before-submit; two Greenhouse session-ping 401s, no page errors.

Artifacts: `logs/realtest/TEST_REPORT.md`, `logs/realtest/scraped_today_new_rows.csv` (20 new rows), `logs/realtest/curated_jobs_list.csv` (5 TOP MATCHES), `logs/realtest/screenshot_via_api.png`, `logs/realtest/gh_pwcli_before_submit.png`

Defects surfaced:
- B1 UnicodeEncodeError on emoji print in `agents/auto_applier.py:generate_apply_package` under cp1252 stdout; workaround PYTHONUTF8=1 applied, proper stdio hardening + logging migration required
- I2 Greenhouse file-attach readback `files.length=None` false negative (DOM attach succeeded)
- A1 boards_done 46 > boards_total 43 due to 3 synthetic tracker rows counted

See `logs/realtest/TEST_REPORT.md` for full logs, per-board counts, job lists, and 5-subagent reviews.

## 2026-10-29 — latest matching adversarial QA

Full locked Linux pytest: **1205 passed, 8 skipped, 32 warnings in 69.43s**.
Frontend: **88 passed, 0 failures/skips in 36.14s** (jsdom). Matching: **57
passed**, **97% branch-aware coverage across all four matching modules**.
`pip check` passes. Four RED-first defects fixed: incomplete essential rejection,
zero-overlap learnable eligibility, and profile/shadow string-collection coercion.
Seven skips are optional FAISS and one deferred Lever. See tests/MATCHING_QA.md
for acceptance gaps and operational risks. **NO-GO for live cutover**; ordinary
scraped evidence still needs extraction/enrichment and real labeled evaluation.
Global whitespace check has a pre-existing PM.md EOF blank-line warning.


## 2026-10-29 — matching runtime continuation

Latest full locked Linux Python suite: **1200 passed, 8 skipped, 32 warnings**
in 73.00s (`.venv/bin/python -m pytest tests/ -q -rs --tb=short`). New matching
suite now has **52 cases** (34 prior + 18 runtime/shadow cases). Seven skips are
optional FAISS; one is deferred Lever. No dependencies or frontend code changed;
the previous 88-test frontend run was not repeated in this continuation.
Coverage figures below describe the earlier foundation, not these runtime additions.
Relocation/sponsorship, learnable/essential gaps, ranking, temporary SQLite cache/
review persistence, operator profile loading and non-mutating shadow execution
have regression tests. Live adoption remains NO-GO pending extraction/enrichment,
real labels, preference calibration and shadow evidence. The optional curator hook
is default-off; no live scraping, migration, deployment or submission executed.


## 2026-10-29 — matching foundation QA follow-up

Fresh Linux Python 3.11.2 venv installed from requirements.lock.txt.
Full `pytest tests/ -q -rs --tb=short`: **1182 passed, 8 skipped, 32 warnings**
in 71.67s. Skips: seven optional FAISS cases and one deferred Lever case.
Frontend `npm test --prefix tests/e2e`: **88 passed**, no skips/failures,
43.74s (jsdom, not Chrome). `pip check` passes. New matching tests: **34 passed**;
branch-aware coverage for the two new modules: **100%** (not product accuracy).
Three QA regressions reproduced RED then fixed: contradictory location evidence,
over-broad support title exclusion, numeric weight overflow. See
`tests/MATCHING_QA.md` for implementation gaps and acceptance audit.
Verdict: foundation checks pass; **NO-GO for live matcher adoption** until
extraction/enrichment, essential-gap semantics, shadow integration and labeled
evaluation exist. No full-system/browser/deployment verification inferred.


## 2026-10-29 — matching foundation, targeted verification only

`python -m unittest tests.test_matching_policy tests.test_matching_score -v`:
**28 passed** (14 eligibility + 14 requirement-scoring contracts).
`git diff --check`: clean. These synthetic fixtures establish behavior, not
historical matching accuracy. No network calls, live pipeline rollout, full
pytest run or frontend rerun. New unittest cases are also pytest-collectable.
No claim of release-wide GO; live adoption awaits extraction/enrichment,
confirmed candidate policy, labeled evaluation, and shadow comparison.


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
  env-class baseline (5× docker heredoc, 2+1 crewai, 1 url_guard).
- Two further full runs on the same commit (`68821559c`), run at the
  reviewer's request — **1125 passed each time**, with the baseline set plus
  exactly one alternating timing-flake failure: run 1
  (`2:52`) tripped
  `test_review_handoff.py::test_regeneration_hides_previous_evidence_and_rejects_stale_run_id`,
  run 2 (`3:40`) tripped the known
  `test_action_rate_limit.py::test_a_denied_call_reports_how_long_to_wait`.
  Each node passes in isolation (review-handoff: file `20/20` + the node
  twice; rate-limit: file `32/32` + the node twice, earlier the same day),
  and neither failure survives a solo rerun — full-suite load on Windows
  can starve their wait/heartbeat windows, and the two never failed in the
  same run. Linux CI remains the arbiter for both.

### A3/A4 evidence + runner decision (2026-10-28, at `ce9018d84`)

- **A3 — CI green at the bundled commit, observed via the GitHub REST API**
  (no `gh` on this host; endpoint verified working):
  `actions/runs/40691999221` → **completed / success** — all five jobs
  (`API + auth + attribution (pytest) (3.11)`, `Dashboard e2e (real API in
  jsdom)`, `Locked image (x86_64)`, `Locked image (aarch64)`,
  `Dependency vulnerabilities (pip-audit)`) passed. Per-job pass counts were
  NOT ingested: job-level log download requires an authenticated token that
  this host does not have, and counting from a partial view would be
  invention. Job-level success is the CI gate itself; recorded local counts
  elsewhere in this file remain the only locally-observed numbers, and the
  expectation that Linux runs MORE test nodes than many Windows-classified
  skips (the 5× + 3× Bash skips run for real on Linux) is satisfied by
  construction of those skips' conditions.
- **A4 — runner decision recorded AND implemented in `ci.yml`:** before the
  change, the run's labels were 4 × `ubuntu-latest` + 1 × `ubuntu-24.04-arm`
  (queried from the same API call above). GitHub's `ubuntu-latest` rides the
  26.04 migration that started 2026-10-19, so every `runs-on` was pinned to
  `ubuntu-24.04` for the release window (matrix x86_64 likewise, with the
  rationale in a comment at the matrix; ARM stays `ubuntu-24.04-arm` as
  before). This is PO recommendation #3 turned into config, not just prose.
  The first CI run after this change is itself the verification that the
  pinned runner ships the full toolchain.

### B10 pdfminer wave (2026-10-28, pdfplumber 0.11.9)

- **Constraint that shaped the choice:** `pdfminer.six` is pinned by its only
  consumer `pdfplumber` (hard `==` pin), and the fix versions are
  `20251230` (PYSEC-2026-1761) / `20251107` (PYSEC-2026-1762). The newest
  pdfplumber (0.11.10) pins `pdfminer.six==20260107` BUT requires
  `Pillow>=12.2.0`, which has an empty intersection with crawl4ai's
  `pillow~=10.4` — taking it would reproduce the ResolutionImpossible docker
  failure class recorded on 2026-10-08 (`zhipuai`/pyjwt). **pdfplumber 0.11.9**
  is the newest release still accepting `Pillow>=9.1` and it pins
  `pdfminer.six==20251230`, past BOTH fix lines.
- `requirements.txt`: `pdfplumber==0.11.4 → ==0.11.9` (exact pin, bounded);
  lock recompiled with `--universal` — the diff is exactly two package lines
  (`pdfminer-six 20231228→20251230`, `pdfplumber 0.11.4→0.11.9`), nothing else
  moved. Venv re-synced and verified: `pdfplumber 0.11.9 | pdfminer-six
  20251230`.
- Behavior-compatibility check: pdfplumber consumers are
  `tools/resume_generator.py` (1-page check) and `tools/cv_parser.py` (text
  extraction); `test_resume_generator` + `test_cv_upload` pass on 0.11.9
  (84/84 together with the hygiene suite).
- **Audit ratchet, in order:** `deploy/dependency_audit.py` first reported
  `FIXED — 2 baseline entries no longer reproduce` + `OK — 80 findings, all in
  the baseline; nothing new`; only then were the two
  `pdfminer-six==20231228 PYSEC-2026-1761/1762` lines pruned from the
  baseline; re-audit **OK — 80 findings, nothing new** (a pruned entry cannot
  return silently — the audit now fails if it did).
- **lxml stays accepted, not forgotten:** PYSEC-2026-87 (local file read via
  `resolve_entities`) is fixed only in lxml 6.1.0, but `crawl4ai==0.3.74`
  requires `lxml~=5.3`, so 6.x is unsatisfiable until the B11 crawl4ai
  migration — same blockers as pillow.
- **Full Windows pytest with the bumped pins: 1145 passed / 9 skipped /
  0 failed** (221s) — identical to the pre-wave count at `ce9018d84`, i.e.
  the pin bump introduced no drift; same 9 skips, all accounted for above.

### e2e flake: review.test.mjs boot-hook overrun (2026-10-28, at `aae372658`)

- CI run `40693708819` failed ONLY in `Dashboard e2e` (pytest/docker×2/
  pip-audit all green — which also certifies the pdfplumber bump on Linux).
  Node-free reproduction locally matched it: in full-suite run #1,
  `review.test.mjs` failed at FILE level (its 4 inner nodes all passed) with
  the harness signal `Test hook "beforeEach" ... generated asynchronous
  activity after the test ended` + a teardown `TypeError` — the stats-boot
  `waitFor` (default 10s) overran under six concurrently booting suite
  processes (jsdom + uvicorn each). Solo run: 4/4 pass. Run #2 of the same
  full suite: 88/0 pass. Zero code delta in review paths between the
  passing `ce9018d84` run and the failing `aae372658` run — load timing,
  not the pdfplumber bump.
- Class fix: the three BOOT-path waits (review.test.mjs stats boot,
  environment.test.mjs boot, smoke.test.mjs stats loaded) now carry explicit
  `timeout: 30000` (aligned with startApi's own 30s boot budget). The
  `waitFor` DEFAULT stays 10s on purpose — it also budget-limits negative
  tests, which must not lengthen silently. Verified with a full local e2e
  run: **88 passed / 0 failed** post-hardening.

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

### A1+A2+B6+B9 disposition (2026-10-28, portability + PUT cv-profile run)

**A1 — portability hunks of `40e5fc1ab` applied by hand (4 utf-8 `read_text`
fixes + url_guard path normalization).** Acceptance verified: with
`PYTHONIOENCODING` unset, `tests/test_url_guard.py::test_the_scan_actually_finds_sinks`
is RED→GREEN on Windows — the persistent env-class failure was a dict-key
mismatch (`'agents\auto_applier.py'` vs the asserted `'agents/auto_applier.py'`; the
report printer kept raw relpaths). Touched files suite: `test_url_guard +
test_dependency_hygiene + test_embedding_cache + test_suite_hermeticity`
= **172/172 passed**.

**A2 — diagnosed before any skip (all previously-failing Windows nodes now
green or justified skips):**

- CrewAI pair was two distinct, verifyable causes, not an env-class unknown:
  1. `offline_sdk`'s blanket `socket.connect` denial fired on a **Windows-only
     false positive**: crewai's first event-bus emit lazily builds
     `asyncio.new_event_loop()`; the Proactor self-pipe goes through stdlib
     `socket.socketpair()`, which (no `AF_UNIX` pairs on Windows) binds,
     listens and connects one ephemeral 127.0.0.1 pair to itself inside that
     helper. The guard now exempts only calls whose immediate caller frame is
     stdlib `socket.socketpair` (forwarded to the real connect; every other
     connection, loopback included, stays denied + recorded). File after fix:
     **7/7** (~57s).
  2. `test_installed_crewai_metadata_accepts_patched_mcp` failed on **venv
     drift**, not a pin problem: the lock is consistent (`crewai==1.6.1` +
     `mcp==1.30.0`, both committed), but the local venv had crewai 1.14.7
     whose `mcp~=1.26.0` dragged mcp to 1.26.0 during a partial sync. Full
     re-sync to the lock (`uv pip install -r requirements.lock.txt`) restores
     crewai 1.6.1 / mcp 1.30.0 / litellm 1.100.4 / fpdf2 2.8.8.
- Docker heredoc ×5: root cause exact — `shutil.which("bash")` finds
  `C:\Windows\system32\bash.EXE`, the WSL launcher stub (no distro installed),
  which dies at `execvpe(/bin/bash)`. The guard is now a **functional probe**
  (`bash -n` on `exit 0` must return 0): 8 passed / **5 justified skips**
  with that reason on this host; Linux CI runs the check for real.
- Two more full runs (background), tracking each backend increment:
  - **1129 passed / 9 skipped** with A1+A2 only (pre-B6).
  - **1140 passed / 9 skipped / 0 failed** with B6 included.
  - **Final: 1145 passed / 9 skipped / 0 failed** (226s) with B6 + all of
    B9 (wedged-run recovery, bad-tab-400s, screenshot content-sniff) — the
    definitive local Windows count for this bundle. Every skip accounted
    for below.

**B6 — `tests/test_api_cv.py::TestPutCvProfile`, 11 new tests** (route
contract + real-merge semantics of `cache.save_cv_profile`): file
**21/21 passed** alone; the full-suite runs above include them.

**B9 — bundle:** `test_api_phase2.py` wedged-run recovery
(`test_wedged_run_blocks_then_restart_recovered`), bad-tab-400 for
`/api/jobs` + `/api/apply/queue`, screenshot content-type honesty
(text-named-.png → octet-stream; real PNG → image/png) in
`test_error_disclosure.py`; touched-suite run **52/52 passed**.

**Skip accounting for the 9 (zero unexplained):**
5 × `test_docker_locked_dependencies.py::test_docker_ci_shell_commands_and_python_heredoc_parse[*]`
— functional-Bash probe justification above;
3 × `tests/test_image_leak_check.py:243` — Docker CI shell failure-injection
requires POSIX Bash (env-conditional, pre-existing);
1 × `tests/test_apply_submit_primitives.py:413` — Lever submit deferred, no
live confirmation-text observation without a paid account (deliberate,
documented).

**Frontend E2E after B5-table/B3-401 additions: 88 passed / 0 failed** (85
baseline + 3 new guards: outage table error row, empty-filter state in BOTH
views, mid-action 401 bounce).

The old env-class baseline (5 docker + 2+1 crewai + 1 url_guard as FAILURES)
is retired by this section: those nodes are now green or justified skips.

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
