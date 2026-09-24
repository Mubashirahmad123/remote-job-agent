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
    data/mockData.js    OFFLINE FALLBACK ONLY (MOCK_JOBS/SOURCES/SKILLS/KANBAN)
    api.js              live client — must load before store.js
    store.js            reactive state + normalization + loaders
    components/*.js     navigation, dashboard, jobDesk, jobDrawer,
                        resumeStudio, autoApply, tracker, toast
    app.js              bootstrapper (loads LAST)
```

`index.html` script order matters: `mockData → api → store → components → app`.
`mockData.js` is fallback paint, not the data model — new code must read
`store.state`, never `MOCK_*` directly (grep before adding usages).

## 2. API client (`js/api.js`)

- Base URL: `JobAgent.API_BASE` → `localStorage rja_api_base` → same-origin →
  `http://127.0.0.1:8000` (for `file://` accidents).
- Token: `localStorage rja_api_token` → `Authorization: Bearer` header.
- Errors carry `.code`: `UNREACHABLE` (server down), `UNAUTHORIZED` (bad token),
  `HTTP_nnn`. All throw — callers show banners/toasts, never silent-fail.
- One fn per backend router: `getHealth` / `getJobs/getJob` / `getStats` /
  `getTracker/patchTracker` / `refreshJobs` / `startScrape/getScrape/listScrapes` /
  `createResume/createCoverLetter` / `getCvProfile/updateCvProfile/getCvVariants`
  — mirror `api/routers/` when adding endpoints. The three `getCv*` fns
  swallow 404/501 into `{_unavailable: true}` (endpoint not ready / no cache);
  all other errors still throw.

## 3. Store (`js/store.js`)

State: `activeTab, viewMode, selectedJob, filters{search,role,minScore,location,
source,status}, autoApply{mode,threshold,dailyCap,appliedToday}`,
live: `jobs[], tracker[], stats, health, usingLive, dataSource(sheets|snapshot|mock)`,
`loading{…}, errors{…}`. `subscribe(fn)` → `notify()` re-renders components.

- **Normalization:** backend `JobOut` (string `tech_stack`, fingerprint key) →
  UI shape (`id` = fingerprint, `tech_stack[]`, derived `role/location_key/
  posted_text`, `matched_skills` from stack, `missing_skills: []`).
  Backend tracker statuses → kanban columns (`interviewing→interview`;
  `withdrawn/ghosted→rejected`; `review` is UI-only).
- **Loaders:** `loadAll()` = `loadJobs + loadTracker + loadStats` in parallel,
  each with per-section mock fallback so one dead endpoint never blanks the UI.
  Snapshot (all scores 0) auto-drops `minScore` to 0 and syncs the slider.
- **First paint:** components render from mock instantly, then re-render live
  via subscription — keep it that way (never `await` before `init`).

## 4. Components

| File | Owns | Live source | Element IDs |
|---|---|---|---|
| `navigation.js` | tab switching, theme toggle | — | `navDashboard…`, `currentViewTitle` |
| `dashboard.js` | bento metrics, sources grid, skills cloud | `/api/stats` (`by_source`, `tabs`); skills still mock (no endpoint yet) | `metricTotalJobs/TopMatches/DailyCap/Interviews`, `sourcesGrid`, `topSkillsCloud` |
| `jobDesk.js` | filters, grid/table views, count | `store.state.jobs` (client-side filter; backend handles `q/source/tab/limit`) | `jobFilterSearch`, `rolePillGroup`, `scoreRange`, `location/source/statusFilter`, `jobsGridContainer/TableBody`, `filteredJobCount` (`(source: N)` suffix) |
| `jobDrawer.js` | slide-over detail | receives job object (defensive: string-or-array stack, missing skills/CV) | `jobDetailDrawer`, `drawerBody`, `btnDrawerApplyNow/Save` |
| `tracker.js` | kanban + status cycling | `GET/PATCH /api/tracker`; click cycles `applied→interviewing→offer→rejected`, sync button refreshes APPLIED tab | `kanbanColApplied/Review/Interview/Offer/Rejected`, `count*`, `btnSyncTrackerSheets` |
| `resumeStudio.js` | CV upload (local demo), tailor engine, profile edit + variants panels, Resume/Cover-Letter preview tabs + Open-PDF | `POST /api/resume` + `/api/cover-letter`, `GET` + `PUT /api/cv/profile`, `GET /api/cv/variants` (quiet fallback to dynamic demo preview when 404/501/unreachable) | `tailorJobSelect`, `btnGenerateTailored`, `cvVariantList`, `btnEditProfile`, `profSkills`, `generatedPreviewCard`, `tabPreviewResume`, `tabPreviewCover`, `btnOpenPdf` |
| `autoApply.js` | safety cockpit, telemetry | static demo (Phase 2: wire to apply endpoints) | `btnModeReview/Submit`, `autoApplyThreshold`, `dailyCapSlider`, `terminalLog` |
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
- Skills cloud and auto-apply telemetry are still static demos until their
  endpoints land (`GET /api/skills`, apply endpoints) — don't mistake them
  for live data.
