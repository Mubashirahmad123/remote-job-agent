# CHANGELOG.md

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
