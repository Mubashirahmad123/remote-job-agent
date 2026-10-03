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
    store.js            reactive state + normalization + loaders
    components/*.js     navigation, dashboard, jobDesk, jobDrawer,
                        resumeStudio, autoApply, tracker, toast
    app.js              bootstrapper (loads LAST)
```

`index.html` script order matters: `api → store → components → app`.

## Frontend E2E smoke (`tests/e2e/`)

`./tests/e2e/run.sh` — boots the real FastAPI app (seeded via `SNAPSHOT_FILE`
with `tests/e2e/fixtures/jobs.snapshot.json`) and loads the real `index.html`
plus the real `js/*` in jsdom over HTTP. 18 assertions across three suites:
asset integrity, happy path, and API-unreachable.

**Why jsdom, not Playwright:** `playwright install chromium` cannot reach the
browser CDN from this environment, so a real-browser run isn't reproducible
here. jsdom executes the same application code against the same API, which
covers the failure mode this project keeps hitting (dead guards, undefined
globals, states that never render). It does **not** cover CSS, layout,
visual regressions, or real pointer/keyboard input — that gap is open, and a
Playwright run is the way to close it wherever egress exists.

**The fixture is not hand-written.** `tech_stack` values are real
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
- Token: `localStorage rja_api_token` → `Authorization: Bearer` header.
- Errors carry `.code`: `UNREACHABLE` (server down), `UNAUTHORIZED` (bad token),
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
  `withdrawn/ghosted→rejected`; `review` is UI-only).
- **Loaders:** `loadAll()` = `loadJobs + loadTracker + loadStats` in parallel,
  each with a per-section error/empty state so one dead endpoint never blanks
  the UI silently (it says which endpoint failed).
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
| `tracker.js` | kanban + status cycling + professional manual-add modal | `GET/POST/PATCH /api/tracker`; fill-only/package statuses render in Review; active cards cycle via backend-valid statuses `applied/review→interviewing→offer→rejected`; terminal archive statuses (`rejected/withdrawn/ghosted`) stay archived on click; manual adds use an in-app validated modal | `kanbanColApplied/Review/Interview/Offer/Rejected`, `count*`, `btnSyncTrackerSheets`, `btnNewTrackedJob`, `manualApplicationModal` |
| `resumeStudio.js` | CV upload (local demo), tailor engine, profile edit + variants panels, Resume/Cover-Letter preview tabs + Open-PDF | `POST /api/resume` + `/api/cover-letter`, `GET` + `PUT /api/cv/profile`, `GET /api/cv/variants` (quiet fallback to dynamic demo preview when 404/501/unreachable) | `tailorJobSelect`, `btnGenerateTailored`, `cvVariantList`, `btnEditProfile`, `profSkills`, `generatedPreviewCard`, `tabPreviewResume`, `tabPreviewCover`, `btnOpenPdf` |
| `autoApply.js` | fill-and-review queue, safety lock, activity and latest results | API fills supported Greenhouse/Lever forms in visible windows and captures screenshot paths; unsupported ATSs remain package-only; `needs_review` fills render amber and are never counted as filled; per-job failures do not stop later jobs | `btnModeReview/Submit`, `autoApplyThreshold`, `dailyCapSlider` (enforced), `btnRunAutoApplyQueue`, `btnViewScreenshots`, `terminalLog`, `reviewQueueResults` |
| `toast.js` | notifications | `JobAgent.toast.show(msg)` | — |
| `app.js` | boot: `init()` all → `store.loadAll()` → wire Sync Sheets + global search | `/api/jobs/refresh` | `btnSyncSheets`, `globalSearchInput`, `btnScrapeNow` (Phase 2: scrape trigger) |

## 5. Conventions

- Read `store.state`; write via `store.set*` (never mutate + silent render).
- Every live section needs three visuals: loading, error banner, data
  (see `jobDesk._stateBanner()` as the pattern).
- `job.id` is a **string fingerprint**, not a number — compare with `String()`
  and escape it into `data-id` (fingerprints are hex-safe, URLs are not).
- Keep API-shape defense in the drawer/normalizers, not in templates.
- Resume Studio is live (profile/variants/tailor wired); its offline fallback is
  a *dynamic* preview built from the selected job + parsed profile — never
  hardcoded fixture HTML. The preview card starts hidden until first generate.
- Skills cloud is still a static demo until `GET /api/skills` lands — don't mistake it
  for live data. Auto-Apply opens visible review windows for supported ATS forms,
  leaves them open for manual submission, and never clicks submit. The daily-cap
  slider is enforced (per-day persisted count blocks the queue at the cap).
  Untrusted content (job fields, toasts, tracker cards, source names) is escaped
  via `JobAgent.escapeHtml`; only `http(s)` posting URLs are ever assigned.
