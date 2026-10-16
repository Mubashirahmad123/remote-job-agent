# FRONTEND.md — Dashboard Guide (`frontend/`)

Vanilla JS, no build step, no framework. Open via the API
(`http://127.0.0.1:8000/`) — never `file://`. Design tokens: `DESIGN.md`.

---

## 1. Structure & load order

```
frontend/
  index.html            shell: sidebar, header, 5 views, drawer, modal
  css/                  variables, base, layout, components, dashboard, jobs,
                        resume, autoapply, tracker (one file per concern)
  js/
    api.js              live client — must load before store.js
    auth.js             session identity + sign-out wiring
    store.js            reactive state + normalization + loaders
    components/*.js     navigation, dashboard, jobDesk, jobDrawer,
                        resumeStudio, autoApply, tracker, toast
    app.js              bootstrapper (loads LAST)
```

`index.html` script order matters: `api → auth → store → escape → components → app`.
The components include `scrapeMonitor.js`. There is no `mockData.js` or
`auth-bootstrap.js` in the current script chain; read normalized state from
`store`, not fabricated mock data.

## Per-CV semantic scoring (2026-10-15)

No new screen/control: the backend uses the keyword-selected CV for semantic
matching as well. Existing match-score displays and score-derived rankings or
metrics reflect new curation results after data refresh. Opening Studio or
refreshing the dashboard does not rescore previously saved jobs. Materials
already use the selected CV; this change does not add CV upload or a new
"Matched using" label. Optional semantic failures retain keyword-only scoring.

## Deferred — future user product (2026-10-15)

CV upload is **not the next personal-main feature**. The previous Phase 2.1a
proposal is superseded by `USER_PRODUCT.md`: a coordinated future `user` branch
for arbitrary-profession CVs, user-owned data and bring-your-own credentials.
No target date or implementation now; do not merge this redesign into `main`.

The future UI must include onboarding/setup readiness, profession-appropriate
filters and gap feedback, protected PDF/DOCX upload, visible active CV and
reset/delete controls. It must handle missing/invalid provider or optional
Sheets configuration without using the owner's resources. Credentials are
write-only inputs with masked status, never displayed back or stored in browser
localStorage. The deployment model and backend ownership contracts must be
agreed first.

Existing personal CV/profile editing and variant workflows remain unchanged;
the local demo dropzone is not a working backend upload. Scope and release gates:
`USER_PRODUCT.md`; product decision: `PM.md` §2.1a; future operational rules:
`PRODUCTION.md` §9.

## Frontend E2E smoke (`tests/e2e/`)

`./tests/e2e/run.sh` — boots the real FastAPI app (seeded via `SNAPSHOT_FILE`
with `tests/e2e/fixtures/jobs.snapshot.json`) and loads the real `index.html`
plus the real `js/*` in jsdom over HTTP. Latest local run (2026-10-15): **68 tests
passed**: 36 existing smoke tests, 22 tracker interactions, 6 environment-
isolation checks and 4 review-polling checks (ten suites plus standalone cases). `npm test --prefix tests/e2e`, the shell runner and frontend
CI use the same suite list. Layout contracts are static/jsdom checks, not a
real browser layout/visual pass.

`tracker.test.mjs` uses a separate opt-in server (`tracker_api.py`) with real
tracker routes/cache/services and an in-memory fake worksheet. Synthetic rows
cover status/review/count mapping, transitions/reload persistence, URL-only
keys, preserved notes, pending/double clicks, failures, Sync recovery, escaping
and manual-add validation/save/retry. It never accesses the user's Sheet or
CVs. `__test__` controls exist only in that fixture process, not production.
See `TESTER.md` for the 22 accompanying Python API/runner contract cases.

`environment.test.mjs` uses disposable source copies with dummy `.env` tokens
and a synthetic cached CV. Removing auth pins reproduces stats 200 → real CV
import → stats 401; current empty-string pins preserve 200s, and login mode
still requires its session. Both plain-token and trailing-comment cases pass.
The stale auth-isolation warning is retired; see `TESTER.md` for evidence and
why empty values must not be replaced by deleting the environment keys.

**Pending reviews:** queue and Regenerate now recognize `review_pending`, retain
its run ID and poll `GET /api/apply/{fp}/review-status` every two seconds. They
show a pending terminal line and keep controls busy until the final result;
a polling failure does not automatically issue another POST. Screenshot URLs
are used only from the completed, persisted result. UI polling is bounded at
35 minutes; the worker watchdog is 30 minutes. A stale run ID/auth/network error
warns that work may still be running rather than inviting blind resubmission.
`review.test.mjs` checks this over a fake review transport; Python tests exercise
real backend persistence. No live browser verification of the fix yet.

**Separate live evidence (2026-10-15):** the user supplied a real-Chrome
Democorp fill-only report/screenshot showing filled contact fields and attached
resume/cover letter. The API still hit its 90-second fill timeout, with a 404
screenshot URL despite a reported PNG on disk. This is not a passing cockpit
preview/API flow or responsive/layout/login/CSP browser test. No application
was submitted. See `LIVE_SUBMIT.md` run log; follow-up remains open in `PM.md`.

**Why jsdom, not Playwright:** `playwright install chromium` cannot reach the
browser CDN from this environment, so a real-browser run isn't reproducible
here. jsdom executes the same application code against the same API, which
covers the failure mode this project keeps hitting (dead guards, undefined
globals, states that never render). It does **not** cover CSS, layout,
visual regressions, or real pointer/keyboard input — that gap is open, and a
Playwright run is the way to close it wherever egress exists.

**The jobs snapshot fixture is not hand-written.** `tech_stack` values are real
`agents.scrapper.top_techs()` output over verbatim copy from live Remotive /
WeWorkRemotely postings, including one pre-fix legacy row
(`"back-end, Engineer, Developer, developer, Back-end"`) because rows written
by the old parser still exist in the Sheet.

**Mutation-tested** — the suite was validated by reintroducing each real bug
and confirming it fails:

| Reintroduced bug | Result |
|---|---|
| `mockData.js` `<script>` restored (404) | 4 tests fail |
| `else if (JobAgent.MOCK_SOURCES)` dead guard restored | 2 tests fail |
| Role nouns allowed back into the skill cloud | 2 tests fail |
| Skill cloud guarded on an undefined global (the original bug) | 3 tests fail |
| Store swallows the `/api/skills` error message | 2 tests fail |

The last two only fail because of fixes made *after* a first pass let them
through: the role-noun case needed the legacy fixture row, and the swallowed
error needed an assertion on the cause reaching the DOM rather than the word
"unavailable".

> **Removed 2026-10-03 — there is no mock layer.** `js/data/mockData.js` was
> referenced by `index.html` and by every `JobAgent.MOCK_*` fallback branch, but
> the file was never committed to this repo (no git history, 404 at runtime). So
> every mock global was `undefined`: `|| []` sites degraded to empty arrays and
> `else if (JobAgent.MOCK_SOURCES)` was permanently false — a failed `/api/stats`
> left the "Loading live stats…" text on screen forever with the error banner
> unreachable inside the dead branch. The script tag and all mock branches are
> gone; each section now renders an explicit loading / error / empty state. New code must read
`store.state`, never `MOCK_*` directly (grep before adding usages).
| `autoApply.js` | fill-and-review queue, safety lock, per-run results and activity log | up to three highest-scoring eligible jobs sequentially → `POST /api/apply/{fp}` `{mode:review}` → visible Greenhouse/Lever fill window or package-only fallback; submit toggle disabled | `btnModeReview/Submit`, `autoApplyThreshold`, `dailyCapSlider` (enforced: localStorage daily count blocks queue at cap), `btnRunAutoApplyQueue`, `btnViewScreenshots` (labelled View Review Results), `terminalLog`, `reviewQueueResults` |
| `scrapeMonitor.js` | scrape run monitor, board diagnostics, structured event stream, run history | `/api/scrape` polling | `scrapeMonitorStatus/Phase/Progress/Summary`, `scrapeMonitorBoards`, `scrapeMonitorEvents`, `scrapeMonitorHistory` |
- Scrape Monitor is live through the existing five-second run polling, with a
  single-loop guard (`pollActive` in `app.js`): a refresh-resume plus a Scrape
  Now click (or the 409 already-running path) never stacks concurrent
  `GET /api/scrape/{run_id}` loops. `GET /api/scrape/{run_id}` now includes additive `boards` and bounded `events` fields; scraper events stay separate from the Auto-Apply `terminalLog`.
- Board statuses include `running` (mid-board, so the monitor never goes silent), `ok` / `empty` / `error` (timeout message on `error`), `skipped-js`, and `skipped-disabled` (JobSpy when `ENABLE_JOBSPY != true`). A crashed/isolated JobSpy surfaces as `error` and the run still completes.
- `Scrape Now` has one authoritative handler in `app.js`; `navigation.js` only routes the sidebar status card to the Scrape Monitor.

## 2. API client (`js/api.js`)

- Base URL: `JobAgent.API_BASE` → `localStorage rja_api_base` → same-origin →
  `http://127.0.0.1:8000` (for `file://` accidents).
- Auth: the server sets an HttpOnly `rja_session` cookie at `/login.html`.
  Every request is same-origin with `credentials: 'same-origin'` so the cookie
  rides along automatically. **No token lives in the browser** — the old
  `?token=` / localStorage Bearer flow was removed. A 401 redirects to
  `/login.html`.
- Errors carry `.code`: `UNREACHABLE` (server down), `UNAUTHORIZED` (no session),
  `HTTP_nnn`. All throw — callers show banners/toasts, never silent-fail.
- One fn per backend router: `getHealth` / `getJobs/getJob` / `getStats` /
  `getTracker/patchTracker` / `refreshJobs` / `startScrape/getScrape/listScrapes` /
  `createResume/createCoverLetter` / `applyReview` (+ `screenshotUrl` /
  `fetchScreenshotBlob` for `GET /api/apply/{fp}/screenshot`) /
  `getCvProfile/updateCvProfile/getCvVariants`
  — mirror `api/routers/` when adding endpoints. The three `getCv*` fns
  swallow 404/501 into `{_unavailable: true}` (endpoint not ready / no cache);
  all other errors still throw.

## 3. Store (`js/store.js`)

State: `activeTab, viewMode, selectedJob, filters{search,role,minScore,location,
source,status}, autoApply{mode,threshold,dailyCap,appliedToday}`,
live: `jobs[], tracker[], stats, skills, health, usingLive, dataSource(sheets|snapshot|unavailable)`,
`loading{…}, errors{…}`. `subscribe(fn)` → `notify()` re-renders components.

- **Normalization:** backend `JobOut` (string `tech_stack`, fingerprint key) →
  UI shape (`id` = fingerprint, `tech_stack[]`, derived `role/location_key/
  posted_text`, `matched_skills` from stack, `missing_skills: []`).
  Backend tracker statuses + auto-apply fill statuses → kanban columns (`filled_ready/package_only/custom_questions→review`, `interviewing→interview`;
  `withdrawn/ghosted→rejected`; `review` is not a valid PATCH status).
- **Loaders:** `loadAll()` loads jobs, tracker, stats, skills and packages in
  parallel, with per-section error/empty states so endpoint failures are visible.
  `loadTracker({throwOnError: true})` lets tracker write/Sync callers distinguish
  a failed GET from a successful refresh; boot keeps its non-fatal default.
  Snapshot (all scores 0) auto-drops `minScore` to 0 and syncs the slider.
- **First paint:** components render a loading state, then re-render live
  via subscription — keep it that way (never `await` before `init`).

## 4. Components

| File | Owns | Live source | Element IDs |
|---|---|---|---|
| `navigation.js` | tab switching, theme toggle | — | `navDashboard…`, `currentViewTitle` |
| `dashboard.js` | bento metrics, sidebar count badges, sources grid, skills cloud | `/api/stats` (`by_source`, `tabs`) plus tracker counts for the pipeline card; skill cloud now live from `/api/skills` (`skills[].name/pct`, no mock fallback — empty renders an honest note) | `metricTotalJobs/TopMatches/DailyCap/Interviews`, `activeJobsBadge`, `topMatchCountBadge`, `metricPipelineFootnote`, `sourcesGrid`, `topSkillsCloud` |
| `jobDesk.js` | filters, grid/table views, count, newest-first ordering | `store.state.jobs` (client-side filter + `posted_date_iso` desc sort with `scraped_at` fallback, undated last; backend handles `q/source/tab/limit`) | `jobFilterSearch`, `rolePillGroup`, `scoreRange`, `location/source/statusFilter`, `jobsGridContainer/TableBody`, `filteredJobCount` (`(source: N)` suffix) |
| `jobDrawer.js` | slide-over detail | receives job object (defensive: string-or-array stack, missing skills/CV) | `jobDetailDrawer`, `drawerBody`, `btnDrawerApplyNow/Save` |
| `tracker.js` | persisted-only kanban status cycling + professional manual-add modal | `GET/POST/PATCH /api/tracker`; fill-only/package statuses render in Review; active cards cycle via backend-valid statuses `applied/review→interviewing→offer→rejected`; terminal archive statuses (`rejected/withdrawn/ghosted`) stay archived on click; manual adds use an in-app validated modal; per-card pending guard; failed writes never cycle locally; confirmed writes with failed GETs direct the user to Sync | `kanbanColApplied/Review/Interview/Offer/Rejected`, `count*`, `btnSyncTrackerSheets`, `btnNewTrackedJob`, `manualApplicationModal` |
| `resumeStudio.js` | CV upload (local demo), tailor engine, profile edit + variants panels, Resume/Cover-Letter preview tabs + Open-PDF | `POST /api/resume` (renders the returned `resume_markdown` — escaped first — in the scrollable preview pane; demo sheet only when no real markdown) + `/api/cover-letter`, `GET` + `PUT /api/cv/profile`, `GET /api/cv/variants` (quiet fallback to dynamic demo preview when 404/501/unreachable) | `tailorJobSelect`, `btnGenerateTailored`, `cvVariantList`, `btnEditProfile`, `profSkills`, `generatedPreviewCard`, `tabPreviewResume`, `tabPreviewCover`, `btnOpenPdf` |
| `autoApply.js` | fill-and-review queue, safety lock, activity and latest results | API fills supported Greenhouse/Lever forms in visible windows and captures screenshot paths; unsupported ATSs remain package-only; `needs_review` fills render amber and are never counted as filled; per-job failures do not stop later jobs | `btnModeReview/Submit`, `autoApplyThreshold`, `dailyCapSlider` (enforced), `btnRunAutoApplyQueue`, `btnViewScreenshots`, `terminalLog`, `reviewQueueResults` |
| `toast.js` | notifications | `JobAgent.toast.show(msg)` | — |
| `app.js` | boot: `init()` all → `store.loadAll()` → wire Sync Sheets | `/api/jobs/refresh` | `btnSyncSheets`, `btnScrapeNow` (Phase 2: scrape trigger) |

## 5. Conventions

- Read `store.state`; write via `store.set*` (never mutate + silent render).
- Every live section needs three visuals: loading, error banner, data
  (see `jobDesk._stateBanner()` as the pattern).
- `job.id` is a **string fingerprint**, not a number — compare with `String()`
  and escape it into `data-id` (fingerprints are hex-safe, URLs are not).
- Keep API-shape defense in the drawer/normalizers, not in templates.
- Resume Studio is live (profile/variants/tailor wired). After a live
  generate, the preview pane renders the **real resume markdown** the PDF
  was built from (every input character escaped before the markdown
  transforms, so LLM output can never inject markup; `Keywords:`/`---`
  footers dropped), inside a taller scrollable pane (`.doc-mock-preview`,
  max-height `min(600px, 70vh)`). Its offline fallback is a *dynamic*
  preview built from the selected job + parsed profile — never
  hardcoded fixture HTML. The preview card starts hidden until first generate.
- Skills cloud is still a static demo until `GET /api/skills` lands — don't mistake it
  for live data. Auto-Apply opens visible review windows for supported ATS forms,
  leaves them open for manual submission, and never clicks submit. The daily-cap
  slider is enforced (per-day persisted count blocks the queue at the cap).
  Untrusted content (job fields, toasts, tracker cards, source names) is escaped
  via `JobAgent.escapeHtml`; only `http(s)` posting URLs are ever assigned.
