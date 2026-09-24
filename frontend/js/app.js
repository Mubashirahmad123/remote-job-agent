/**
 * APP.JS — Application Orchestrator & Bootstrapper
 * Initializes all modular components, then loads LIVE backend data.
 * Components render instantly from mock fallback, then re-render
 * automatically when store.loadAll() resolves (store.subscribe).
 */

document.addEventListener('DOMContentLoaded', async () => {
  // Initialize Global Navigation & Shell
  if (JobAgent.navigation) JobAgent.navigation.init();

  // Initialize Dashboard Overview Widgets
  if (JobAgent.dashboard) JobAgent.dashboard.init();

  // Initialize Curated Jobs Desk & Filtering
  if (JobAgent.jobDesk) JobAgent.jobDesk.init();

  // Initialize Slide-Over Detail Drawer
  if (JobAgent.jobDrawer) JobAgent.jobDrawer.init();

  // Initialize CV Studio & 3-Pass ATS Generator
  if (JobAgent.resumeStudio) JobAgent.resumeStudio.init();

  // Initialize Auto-Apply Safety Cockpit
  if (JobAgent.autoApply) JobAgent.autoApply.init();

  // Initialize Application Kanban Tracker
  if (JobAgent.tracker) JobAgent.tracker.init();

  console.log('⚡ Remote Job Agent Command Center initialized (mock first paint).');

  // Load live backend (Phase 1 reads). Falls back to mock per-section on error.
  if (JobAgent.store && typeof JobAgent.store.loadAll === 'function') {
    try {
      await JobAgent.store.loadAll();
      const mode = JobAgent.store.state.usingLive ? 'LIVE API' : 'mock fallback (API unreachable)';
      console.log('⚡ Data load complete — mode: ' + mode);
    } catch (e) {
      console.warn('[app] loadAll failed:', e && e.message);
    }
  }

  // Wire header actions to live endpoints (graceful when API is down).
  const btnSync = document.getElementById('btnSyncSheets');
  if (btnSync && !btnSync.dataset.wired) {
    btnSync.dataset.wired = '1';
    btnSync.addEventListener('click', async () => {
      if (JobAgent.toast) JobAgent.toast.show('Refreshing sheet cache…');
      try {
        await JobAgent.api.refreshJobs();
        await JobAgent.store.loadAll();
        if (JobAgent.toast) JobAgent.toast.show('Sheets cache refreshed from live API.');
      } catch (e) {
        if (JobAgent.toast) JobAgent.toast.show('Refresh failed: ' + e.message);
      }
    });
  }

  const searchInput = document.getElementById('globalSearchInput');
  if (searchInput && !searchInput.dataset.wired) {
    searchInput.dataset.wired = '1';
    searchInput.addEventListener('input', (e) => {
      if (JobAgent.store) JobAgent.store.setFilter('search', e.target.value.toLowerCase());
      if (JobAgent.navigation) JobAgent.navigation.switchTab('jobs');
    });
  }

  // Scrape Now -> POST /api/scrape, poll run status, reload on done.
  // Status is mirrored to the sidebar card (dot/title/sub/progress) so the
  // user always sees run state, plus the button disables while scraping.
  const btnScrape = document.getElementById('btnScrapeNow');
  const scrapeDot = document.getElementById('scrapeDot');
  const scrapeTitle = document.getElementById('scrapeTitle');
  const scrapeSub = document.getElementById('scrapeSub');
  const scrapeFill = document.getElementById('scrapeFill');

  function boardLine(run) {
    const total = run.boards_total || 0;
    const done = run.boards_done || 0;
    const failed = run.boards_failed || 0;
    const fetched = run.fetched || run.scraped || 0;
    const boards = total ? `${done}/${total} boards` : `${done} boards`;
    const fail = failed ? ` • ${failed} failed` : '';
    return `${boards} • ${fetched} fetched${fail}`;
  }

  function renderRunState(run) {
    const label = btnScrape ? btnScrape.querySelector('span') : null;
    const setDot = (cls) => {
      if (!scrapeDot) return;
      scrapeDot.classList.remove('pulse-emerald', 'pulse-amber', 'pulse-red');
      scrapeDot.classList.add(cls);
    };
    const setFill = (width, color) => {
      if (!scrapeFill) return;
      scrapeFill.style.width = width;
      scrapeFill.style.background = color || '';
    };
    if (!run || (run.status === 'done' && !(run.boards_failed > 0))) {
      if (btnScrape) {
        btnScrape.disabled = false;
        btnScrape.removeAttribute('aria-busy');
        if (label) label.textContent = 'Scrape Now';
      }
      setDot('pulse-emerald');
      if (scrapeTitle) scrapeTitle.textContent = run && run.status === 'done'
        ? `Last scrape: ${run.scraped} jobs`
        : 'Scraper 45+ Active';
      if (scrapeSub) scrapeSub.textContent = run && run.status === 'done'
        ? `${run.curated} curated • ${String(run.finished_at || '').slice(0, 16).replace('T', ' ')}`
        : 'Next run: Mon 09:00 UTC';
      setFill('60%');
      return;
    }
    if (run.status === 'done' && run.boards_failed > 0) {
      // Partial success: sheets updated, but some boards failed. Amber, not red.
      if (btnScrape) {
        btnScrape.disabled = false;
        btnScrape.removeAttribute('aria-busy');
        if (label) label.textContent = 'Scrape Now';
      }
      setDot('pulse-amber');
      if (scrapeTitle) scrapeTitle.textContent = `Scrape done — ${run.boards_failed} boards failed`;
      if (scrapeSub) scrapeSub.textContent = `${run.scraped} scraped, ${run.curated} curated • partial`;
      setFill('100%', 'var(--accent-amber)');
      return;
    }
    if (run.status === 'error') {
      if (btnScrape) {
        btnScrape.disabled = false;
        btnScrape.removeAttribute('aria-busy');
        if (label) label.textContent = 'Scrape Now';
      }
      setDot('pulse-red');
      if (scrapeTitle) scrapeTitle.textContent = 'Scrape failed';
      if (scrapeSub) scrapeSub.textContent = String(run.error || 'unknown error').slice(0, 80);
      setFill('100%', 'var(--accent-danger, #ef4444)');
      return;
    }
    // queued | running — scraping (blue) vs curating (amber) are visually distinct.
    const curating = run.phase === 'curating';
    if (btnScrape) {
      btnScrape.disabled = true;
      if (label) label.textContent = curating
        ? `Scoring ${run.scraped || 0} jobs…`
        : `Scraping ${run.boards_done || 0}/${run.boards_total || '…'}…`;
      btnScrape.setAttribute('aria-busy', 'true');
    }
    setDot('pulse-amber');
    if (scrapeTitle) scrapeTitle.textContent = curating ? 'Scoring & saving…' : 'Fetching boards…';
    if (scrapeSub) scrapeSub.textContent = curating
      ? `Run ${run.run_id} • ${run.scraped || 0} jobs to score`
      : `Run ${run.run_id} • ${boardLine(run)}`;
    setFill(curating ? '80%' : '30%', curating ? 'var(--accent-amber)' : 'var(--primary-blue)');
  }

  if (btnScrape && !btnScrape.dataset.wired) {
    btnScrape.dataset.wired = '1';
    const poll = async (runId) => {
      let last = null;
      for (let i = 0; i < 360; i++) { // up to ~30 min at 5s intervals
        await new Promise(r => setTimeout(r, 5000));
        try {
          const run = await JobAgent.api.getScrape(runId);
          last = run;
          renderRunState(run);
          if (run.status === 'done') {
            const partial = run.boards_failed > 0 ? ` (${run.boards_failed} boards failed)` : '';
            if (JobAgent.toast) JobAgent.toast.show(`Scrape done: ${run.scraped} scraped, ${run.curated} curated${partial}.`);
            await JobAgent.store.loadAll();
            if (!(run.boards_failed > 0)) setTimeout(() => renderRunState(null), 30000);
            return;
          }
          if (run.status === 'error') {
            if (JobAgent.toast) JobAgent.toast.show('Scrape failed: ' + (run.error || 'unknown error'));
            return;
          }
        } catch (e) {
          if (JobAgent.toast) JobAgent.toast.show('Scrape poll failed: ' + e.message);
          return;
        }
      }
      // Poll window expired: re-sync once from the server so the button/card
      // never stick in a busy state on a stale local assumption.
      try {
        const run = await JobAgent.api.getScrape(runId);
        renderRunState(run);
        if (run.status === 'done' || run.status === 'error') await JobAgent.store.loadAll();
        else if (JobAgent.toast) JobAgent.toast.show('Scrape still running — check back later.');
      } catch (_) {
        if (last) renderRunState(last);
      }
    };
    btnScrape.addEventListener('click', async () => {
      try {
        const run = await JobAgent.api.startScrape();
        if (JobAgent.toast) JobAgent.toast.show('Scrape started (' + run.run_id + '). Polling…');
        renderRunState(run);
        await poll(run.run_id);
      } catch (e) {
        const msg = (e.status === 409)
          ? 'A scrape is already running — see the sidebar status card.'
          : 'Scrape start failed: ' + e.message;
        if (JobAgent.toast) JobAgent.toast.show(msg);
        // Refresh card in case another client started the run (409).
        try {
          const runs = await JobAgent.api.listScrapes();
          const active = (runs || []).find(r => r.status === 'queued' || r.status === 'running');
          if (active) { renderRunState(active); await poll(active.run_id); }
        } catch (_) { /* keep idle card */ }
      }
    });
    // Resume: if a run is active on page load (e.g. refresh mid-scrape),
    // pick up polling so the card/button reflect reality.
    (async () => {
      try {
        const runs = await JobAgent.api.listScrapes();
        const active = (runs || []).find(r => r.status === 'queued' || r.status === 'running');
        if (active) {
          renderRunState(active);
          await poll(active.run_id);
        }
      } catch (_) { /* API down — mock fallback already painted */ }
    })();
  }
});
