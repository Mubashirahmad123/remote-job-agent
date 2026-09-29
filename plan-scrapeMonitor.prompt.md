## Plan: Scrape Monitor And Console UX

The best direction is a dedicated **Scrape Monitor** tab, separate from the Auto-Apply Cockpit. Scraping and auto-apply have different workflows, risks, and telemetry, so they should not share one terminal.

**Recommended experience**

1. Clicking `Scrape Now` starts the run and opens the Scrape Monitor.
2. The monitor shows:
   - Current phase: queued, scraping, curating, complete, partial, or failed
   - Run ID, elapsed time, fetched jobs, curated jobs
   - Overall progress bar
   - Board-by-board status grid
   - Failed and empty boards
   - A dark terminal-style structured event feed
   - Recent scrape history
3. The sidebar status card remains as a compact global indicator and links to the monitor.
4. Use the existing five-second polling first. It is already implemented and is sufficient for this workflow.
5. Keep the Auto-Apply terminal separate and limited to auto-apply telemetry.

**Implementation phases**

1. Add the Scrape Monitor tab and responsive layout in [frontend/index.html](frontend/index.html).
2. Create `frontend/js/components/scrapeMonitor.js` to own:
   - Polling
   - Event rendering
   - Board diagnostics
   - Run history
   - Auto-scroll behavior
   - Loading, error, partial-success, and completed states
3. Extend [api/runs.py](api/runs.py) with additive structured fields:
   - Lifecycle events
   - Timestamps
   - Severity
   - Board details
   - Bounded event retention
4. Keep existing API endpoints backward-compatible:
   - `POST /api/scrape`
   - `GET /api/scrape`
   - `GET /api/scrape/{run_id}`
5. Remove the competing fake scrape handler in [frontend/js/components/navigation.js](frontend/js/components/navigation.js), leaving one authoritative scrape flow in [frontend/js/app.js](frontend/js/app.js) and the new monitor component.
6. Add dedicated styling in a new `frontend/css/scrape-monitor.css`; keep Auto-Apply styles scoped separately.
7. Update [FRONTEND.md](FRONTEND.md) with the new ownership and polling behavior.

**Terminal design**

The scraper terminal should show curated messages such as:

- `[SCRAPE] Starting board scan`
- `[BOARD] RemoteOK completed: 42 jobs`
- `[BOARD] LinkedIn returned an error`
- `[CURATE] Scoring 384 jobs`
- `[DONE] 86 jobs curated`

Raw scraper stdout should stay server-side. Structured events are safer, clearer, and easier to evolve toward SSE later.

**Verification**

- Run `python -m pytest tests/test_api_phase2.py`.
- Test normal completion, partial board failures, worker errors, and page refresh during an active run.
- Confirm sidebar status and monitor remain synchronized.
- Confirm Auto-Apply telemetry never appears in the scraper terminal.
- Check desktop and mobile layouts for overflow and readable terminal lines.

## Overall Frontend Design Direction

The application should feel like one focused **Remote Job Command Center**, not a collection of unrelated dashboards. The primary workflow is:

`Scrape -> Curate -> Inspect -> Tailor materials -> Apply safely -> Track outcome`

Every screen should support that workflow and preserve the current design language from [DESIGN.md](DESIGN.md): neutral zinc/slate surfaces, crisp borders, high-contrast text, restrained status colors, compact density, and dark/light theme support.

### 1. Persistent application shell

- Keep the left navigation for desktop and convert it into a compact bottom or slide-out navigation on mobile.
- Keep the top command bar persistent with global search, `Scrape Now`, Sheets sync, theme toggle, and profile state.
- Add a visible active-run indicator whenever scraping or auto-apply is in progress.
- Use one consistent status vocabulary across the product: `Running`, `Ready`, `Partial`, `Needs review`, `Complete`, and `Failed`.
- Use icons for compact actions, but keep text labels for consequential commands such as scraping, applying, syncing, and submitting.
- Keep the shell quiet and operational; avoid marketing-style hero sections, oversized decorative panels, and excessive animation.

### 2. Command Deck dashboard

- Make the dashboard an actionable daily briefing rather than a collection of decorative KPI cards.
- Prioritize four metrics: fresh jobs, high-match jobs, applications remaining, and interviews or offers.
- Make the live scraper health widget clickable so it opens the Scrape Monitor.
- Add a `Next best action` area driven by current state, such as reviewing high-match jobs, fixing a missing CV field, or checking a paused application.
- Keep source health and skill demand as supporting diagnostic widgets below the primary action area.

### 3. Curated Jobs Desk

- Use a dense table as the default view for scanning and comparison; retain the card grid as an alternate view.
- Keep filters visible: search, role, score, location, source, and status.
- Make match score, salary, location, source, posting age, and application state immediately scannable.
- Open job details in the existing right-side drawer so the user can inspect a job without losing filter context.
- In the drawer, order information as: match summary, matched and missing skills, job facts, description, tailored materials, and apply actions.
- Make the primary next step explicit: `Tailor resume`, `Review package`, or `Apply on site`.

### 4. CV and Resume Studio

- Treat the studio as a preparation workspace, not just a file upload form.
- Organize it into profile completeness, selected job, generation controls, and output preview.
- Show missing profile data before generation so the user understands why a result may be incomplete.
- Use tabs for resume and cover letter previews, with clear version labels and timestamps.
- Keep generated artifacts visually close to the selected job and expose the match rationale beside the preview.
- Use a strong review state before download or application; generated output should never imply that it was submitted.

### 5. Auto-Apply Cockpit

- Keep this as the safety center for automation, with the mode and daily cap visible before any action.
- Separate controls, queue summary, execution telemetry, screenshots, and recent packages into distinct areas.
- Make `Fill & Review` the visually safer default and make live auto-submit visually explicit and difficult to activate accidentally.
- Keep its terminal strictly scoped to browser/application events; scraper events must never appear here.
- Add clear pause, review, and completion states when real apply endpoints are connected.

### 6. Application Tracker

- Keep the Kanban board focused on outcomes rather than raw scraper data.
- Use consistent status transitions and show the next follow-up action on each application card.
- Make cards compact but useful: company, role, applied date, current status, score, and next event.
- Support a detail drawer for notes, package links, interview dates, and status history without leaving the board.
- Keep manual additions and Sheets synchronization visible but secondary to the pipeline itself.

### 7. Shared interaction and visual rules

- Prefer progressive disclosure: summary first, diagnostics and full descriptions on demand.
- Use drawers for inspection, modals only for confirmation or image/document preview, and full views for long-running workflows.
- Use blue for active controls, emerald for successful or safe states, amber for review or partial states, and red only for failure or live-submit risk.
- Make loading, empty, unavailable, partial, and error states explicit for every live section.
- Avoid putting cards inside cards; use full-width sections for page structure and cards only for repeated records or genuinely framed tools.
- Keep numbers and timestamps aligned using the existing mono font, but use the expressive sans font for hierarchy and labels.
- Use short transitions for navigation, drawer entry, state changes, and event arrival; do not animate every metric continuously.

### 8. Responsive behavior

- Desktop: persistent sidebar, command bar, dense two-column operational layouts, and right-side detail drawers.
- Tablet: collapsible sidebar, two-column widgets where space permits, and full-width drawers.
- Mobile: stacked sections, sticky primary actions, horizontally scrollable tables only where comparison requires it, and no clipped terminal or status text.
- Preserve the same action order across breakpoints so the product does not feel like a separate mobile application.

### 9. Frontend ownership

- `navigation.js` owns navigation, theme state, and shell status links.
- `dashboard.js` owns daily briefing metrics and health widgets.
- `jobDesk.js` and `jobDrawer.js` own discovery and inspection.
- `resumeStudio.js` owns profile preparation and generated materials.
- `autoApply.js` owns automation safety and application telemetry.
- `scrapeMonitor.js` owns scrape runs, board diagnostics, event history, and polling.
- `tracker.js` owns application outcomes and status transitions.
- `store.js` remains the shared normalized state layer; components do not reach directly into backend response quirks.

**Scope decisions**

- Polling first; SSE/WebSockets later.
- No cancellation or retry controls in the first version.
- Keep the current in-memory run registry and one-active-run rule.
- Do not change auto-submit safety behavior.
