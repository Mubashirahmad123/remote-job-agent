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

  _setText(id, val) {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
  },

  _applyMetrics(stats) {
    if (!stats) return;
    this._setText('metricTotalJobs', stats.total_jobs ?? '—');
    const tabs = stats.tabs || {};
    this._setText('metricTopMatches', tabs['TOP MATCHES'] ?? '—');
    // Sidebar "Hot" badge shows the same live TOP MATCHES count — it was
    // hardcoded in index.html and never updated, drifting from this metric.
    if (tabs['TOP MATCHES'] != null) {
      const hot = document.getElementById('topMatchCountBadge');
      if (hot) hot.textContent = tabs['TOP MATCHES'] + ' Hot';
    }
  },

  _trackerColumn(status) {
    const normalized = String(status || 'applied').trim().toLowerCase() || 'applied';
    const reviewStatuses = new Set([
      'review',
      'filled_ready',
      'filled_ready_submit_disabled',
      'custom_questions',
      'package_only',
      'email_draft',
      'playwright_not_installed',
      'playwright_failed',
      'dream_manual',
      'submit_unverified',
      'failed_refunded',
    ]);
    if (normalized === 'rejected' || normalized === 'withdrawn' || normalized === 'ghosted') return 'archived';
    if (reviewStatuses.has(normalized) || normalized.startsWith('filled_')) return 'review';
    if (normalized === 'interviewing' || normalized === 'interview') return 'interview';
    if (normalized === 'offer') return 'offer';
    return 'applied';
  },

  _applyPipelineMetrics(trackerRows) {
    const counts = { applied: 0, review: 0, interview: 0, offer: 0, archived: 0 };
    (trackerRows || []).forEach((row) => {
      const key = this._trackerColumn(row.status);
      counts[key] += 1;
    });

    this._setText('metricInterviews', counts.interview);
    this._setText('metricPipelineSub', counts.interview === 1 ? 'Interview Scheduled' : 'Interviews Scheduled');
    const offerLabel = counts.offer === 1 ? 'Offer' : 'Offers';
    this._setText(
      'metricPipelineFootnote',
      `${counts.applied + counts.review} Applied/Review • ${counts.offer} ${offerLabel} • ${counts.archived} Archived`,
    );

    const total = counts.applied + counts.review + counts.interview + counts.offer + counts.archived;
    const progress = total > 0 ? Math.round(((counts.interview + counts.offer) / total) * 100) : 0;
    const bar = document.getElementById('metricPipelineBar');
    if (bar) bar.style.width = progress + '%';
  },

  render() {
    const { stats, tracker, loading, errors } = JobAgent.store.state;

    this._applyMetrics(stats);
    this._applyPipelineMetrics(tracker);

    // 1. Scraper Sources Grid — live by_source, else mock.
    if (this.sourcesGrid) {
      if (loading.stats) {
        this.sourcesGrid.innerHTML = `<div style="color: var(--text-muted); font-size: 12.5px; padding: 12px;">Loading live stats from <code>/api/stats</code>…</div>`;
      } else if (stats && stats.by_source) {
        const esc = (JobAgent.escapeHtml || ((v) => String(v ?? '')));
        const entries = Object.entries(stats.by_source).sort((a, b) => b[1] - a[1]).slice(0, 8);
        this.sourcesGrid.innerHTML = entries.map(([name, count]) => `
          <div class="source-item-card">
            <div class="source-meta">
              <span class="source-meta-name">${esc(name)}</span>
              <span class="source-meta-status">Live • Online</span>
            </div>
            <span class="source-count-pill">${esc(count)} jobs</span>
          </div>
        `).join('') || `<div style="color: var(--text-muted); font-size: 12.5px;">No live sources yet.</div>`;
      } else if (JobAgent.MOCK_SOURCES) {
        const err = errors.stats ? `<div style="font-size:11.5px;color:#f59e0b;margin-bottom:8px;">API error: ${(JobAgent.escapeHtml || ((v) => String(v ?? '')))(errors.stats)} — showing mock.</div>` : '';
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
