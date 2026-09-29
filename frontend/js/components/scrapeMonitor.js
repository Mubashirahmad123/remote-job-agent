/**
 * SCRAPE MONITOR — Live scrape diagnostics and structured run history.
 */

window.JobAgent = window.JobAgent || {};

JobAgent.scrapeMonitor = {
  init() {
    this.view = document.getElementById('view-scrape');
    this.status = document.getElementById('scrapeMonitorStatus');
    this.phase = document.getElementById('scrapeMonitorPhase');
    this.progress = document.getElementById('scrapeMonitorProgress');
    this.summary = document.getElementById('scrapeMonitorSummary');
    this.boards = document.getElementById('scrapeMonitorBoards');
    this.events = document.getElementById('scrapeMonitorEvents');
    this.history = document.getElementById('scrapeMonitorHistory');
    this.activeRun = null;
    if (this.history) {
      this.history.addEventListener('click', async (event) => {
        const item = event.target.closest('[data-run-id]');
        if (!item || !JobAgent.api) return;
        try {
          const run = await JobAgent.api.getScrape(item.dataset.runId);
          this.render(run);
        } catch (error) {
          if (JobAgent.toast) JobAgent.toast.show('Unable to load scrape run: ' + error.message, 'warning');
        }
      });
    }
    this.loadHistory();
  },

  escape(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, (char) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[char]));
  },

  statusLabel(run) {
    if (!run) return 'Waiting for a scrape';
    if (run.status === 'done' && run.boards_failed > 0) return 'Complete with board failures';
    if (run.status === 'done') return 'Complete';
    if (run.status === 'error') return 'Failed';
    if (run.phase === 'curating') return 'Curating jobs';
    if (run.phase === 'scraping') return 'Scanning boards';
    return run.status === 'queued' ? 'Queued' : 'Starting';
  },

  render(run) {
    if (!run) return;
    this.activeRun = run;
    const total = Number(run.boards_total || 0);
    const done = Number(run.boards_done || 0);
    const percent = run.status === 'done' || run.status === 'error'
      ? 100
      : run.phase === 'curating' ? 80 : total ? Math.round((done / total) * 70) : 8;
    const statusClass = run.status === 'error'
      ? 'is-danger'
      : run.status === 'done' && run.boards_failed > 0 ? 'is-warning'
      : run.status === 'done' ? 'is-success' : 'is-running';

    if (this.status) {
      this.status.className = `scrape-monitor-status ${statusClass}`;
      this.status.textContent = this.statusLabel(run);
    }
    if (this.phase) {
      this.phase.textContent = `${run.phase || run.status} · ${run.run_id}`;
    }
    if (this.progress) {
      this.progress.style.width = `${Math.max(4, Math.min(100, percent))}%`;
    }
    if (this.summary) {
      this.summary.innerHTML = [
        ['Fetched', run.fetched || run.scraped || 0],
        ['Curated', run.curated || 0],
        ['Boards', `${done}/${total || '—'}`],
        ['Failures', run.boards_failed || 0]
      ].map(([label, value]) => `<div class="scrape-stat"><span>${label}</span><strong>${this.escape(value)}</strong></div>`).join('');
    }
    this.renderBoards(run.boards || {});
    this.renderEvents(run.events || []);
    this.renderHistoryItem(run, true);
  },

  renderBoards(boards) {
    if (!this.boards) return;
    const entries = Object.entries(boards);
    if (!entries.length) {
      this.boards.innerHTML = '<div class="scrape-empty">Board diagnostics will appear as the run progresses.</div>';
      return;
    }
    this.boards.innerHTML = entries.sort(([a], [b]) => a.localeCompare(b)).map(([name, board]) => {
      const state = board.status || 'pending';
      const stateClass = state === 'error' ? 'is-danger' : state === 'ok' ? 'is-success' : state === 'empty' ? 'is-warning' : '';
      return `<div class="scrape-board-row ${stateClass}">
        <span class="scrape-board-dot"></span>
        <strong>${this.escape(name)}</strong>
        <span>${this.escape(state)}</span>
        <b>${this.escape(board.fetched || 0)}</b>
      </div>`;
    }).join('');
  },

  renderEvents(events) {
    if (!this.events) return;
    if (!events.length) {
      this.events.innerHTML = '<div class="scrape-empty">Waiting for structured scraper events...</div>';
      return;
    }
    const shouldStick = this.events.scrollHeight - this.events.scrollTop - this.events.clientHeight < 48;
    this.events.innerHTML = events.map((event) => {
      const time = String(event.timestamp || '').slice(11, 19);
      const prefix = event.board ? `[${event.board}]` : `[${event.type || 'RUN'}]`;
      return `<div class="scrape-event level-${this.escape(event.level || 'info')}">
        <time>${this.escape(time)}</time><span class="scrape-event-prefix">${this.escape(prefix)}</span><span>${this.escape(event.message)}</span>
      </div>`;
    }).join('');
    if (shouldStick) this.events.scrollTop = this.events.scrollHeight;
  },

  async loadHistory() {
    if (!this.history || !JobAgent.api) return;
    try {
      const runs = await JobAgent.api.listScrapes();
      this.history.innerHTML = runs.length
        ? runs.map((run) => this.historyMarkup(run)).join('')
        : '<div class="scrape-empty">No scrape runs recorded yet.</div>';
    } catch (_) {
      this.history.innerHTML = '<div class="scrape-empty">Run history is unavailable while the API is offline.</div>';
    }
  },

  historyMarkup(run, active = false) {
    const state = run.status === 'error' ? 'Failed' : run.status === 'done' ? 'Complete' : 'Running';
    return `<button class="scrape-history-item ${active ? 'active' : ''}" data-run-id="${this.escape(run.run_id)}">
      <span><strong>${this.escape(state)}</strong><small>${this.escape(run.run_id)}</small></span>
      <span class="scrape-history-count">${this.escape(run.curated || run.scraped || 0)} jobs</span>
    </button>`;
  },

  renderHistoryItem(run, active) {
    if (!this.history) return;
    const existing = this.history.querySelector(`[data-run-id="${CSS.escape(run.run_id)}"]`);
    if (existing) {
      existing.outerHTML = this.historyMarkup(run, active);
    } else {
      this.history.insertAdjacentHTML('afterbegin', this.historyMarkup(run, active));
    }
  }
};
