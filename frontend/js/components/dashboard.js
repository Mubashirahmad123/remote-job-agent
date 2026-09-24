/**
 * DASHBOARD.JS — Command Deck Bento Grid & Telemetry Widgets
 * Live data: GET /api/stats (counts + by_source) with mock fallback.
 */

window.JobAgent = window.JobAgent || {};

JobAgent.dashboard = {
  init() {
    this.sourcesGrid = document.getElementById('sourcesGrid');
    this.topSkillsCloud = document.getElementById('topSkillsCloud');
    this.render();
    JobAgent.store.subscribe(() => this.render());
  },

  _applyMetrics(stats) {
    if (!stats) return;
    const set = (id, val) => {
      const el = document.getElementById(id);
      if (el) el.textContent = val;
    };
    set('metricTotalJobs', stats.total_jobs ?? '—');
    const tabs = stats.tabs || {};
    set('metricTopMatches', tabs['TOP MATCHES'] ?? '—');
    const applied = (stats.stats_rows || []).length;
    void applied;
  },

  render() {
    const { stats, loading, errors } = JobAgent.store.state;

    this._applyMetrics(stats);

    // 1. Scraper Sources Grid — live by_source, else mock.
    if (this.sourcesGrid) {
      if (loading.stats) {
        this.sourcesGrid.innerHTML = `<div style="color: var(--text-muted); font-size: 12.5px; padding: 12px;">Loading live stats from <code>/api/stats</code>…</div>`;
      } else if (stats && stats.by_source) {
        const entries = Object.entries(stats.by_source).sort((a, b) => b[1] - a[1]).slice(0, 8);
        this.sourcesGrid.innerHTML = entries.map(([name, count]) => `
          <div class="source-item-card">
            <div class="source-meta">
              <span class="source-meta-name">${name}</span>
              <span class="source-meta-status">Live • Online</span>
            </div>
            <span class="source-count-pill">${count} jobs</span>
          </div>
        `).join('') || `<div style="color: var(--text-muted); font-size: 12.5px;">No live sources yet.</div>`;
      } else if (JobAgent.MOCK_SOURCES) {
        const err = errors.stats ? `<div style="font-size:11.5px;color:#f59e0b;margin-bottom:8px;">API error: ${errors.stats} — showing mock.</div>` : '';
        this.sourcesGrid.innerHTML = err + JobAgent.MOCK_SOURCES.map(src => `
          <div class="source-item-card">
            <div class="source-meta">
              <span class="source-meta-name">${src.name}</span>
              <span class="source-meta-status">${src.badge} • ${src.status}</span>
            </div>
            <span class="source-count-pill">${src.jobs} jobs</span>
          </div>
        `).join('');
      }
    }

    // 2. Skills cloud — no backend endpoint yet, keep mock (Phase 2).
    if (this.topSkillsCloud && JobAgent.MOCK_SKILLS) {
      this.topSkillsCloud.innerHTML = JobAgent.MOCK_SKILLS.map(sk => `
        <div class="skill-pill">
          <span>${sk.name}</span>
          <span class="skill-pct">${sk.count}%</span>
        </div>
      `).join('');
    }
  }
};
