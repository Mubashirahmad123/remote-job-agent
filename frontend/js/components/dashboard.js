/**
 * DASHBOARD.JS — Command Deck Bento Grid & Telemetry Widgets
 * Live data: GET /api/stats (counts + by_source) and GET /api/skills.
 * No mock fallback: unavailable sections render an explicit empty/error note.
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

  _count(value, fallback = 0) {
    if (value === undefined || value === null || value === '') return fallback;
    const numeric = Number(value);
    return Number.isFinite(numeric) ? Math.max(0, numeric) : fallback;
  },

  _formatCount(value) {
    if (value === undefined || value === null || value === '') return '—';
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return '—';
    return Math.max(0, numeric).toLocaleString();
  },

  _applyMetrics(stats) {
    if (!stats) {
      this._setText('activeJobsBadge', '—');
      this._setText('topMatchCountBadge', '— Hot');
      return;
    }
    const tabs = stats.tabs || {};
    const totalJobs = this._count(stats.total_jobs, this._count(tabs['ALL JOBS'], 0));
    const topMatches = this._count(tabs['TOP MATCHES'], 0);

    this._setText('metricTotalJobs', this._formatCount(totalJobs));
    this._setText('metricTopMatches', this._formatCount(topMatches));
    // Sidebar badges use the same live /api/stats counts as the dashboard
    // metrics, so they never drift back to the old static demo values.
    this._setText('activeJobsBadge', this._formatCount(totalJobs));
    this._setText('topMatchCountBadge', this._formatCount(topMatches) + ' Hot');
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

  _skillNote(text, color) {
    const style = `color: ${color || 'var(--text-muted)'}; font-size: 12.5px; padding: 12px;`;
    return `<div style="${style}">${text}</div>`;
  },

  // Live skill demand. Honest empty states: the sheet genuinely having no
  // tech_stack data must not look identical to the API being down.
  _renderSkills(skills, isLoading, error) {
    if (!this.topSkillsCloud) return;
    const esc = (JobAgent.escapeHtml || ((v) => String(v ?? '')));

    if (isLoading && !skills) {
      this.topSkillsCloud.innerHTML = this._skillNote('Aggregating <code>tech_stack</code> from <code>/api/skills</code>…');
      return;
    }
    if (!skills) {
      this.topSkillsCloud.innerHTML = this._skillNote(
        error ? `Skill demand unavailable: ${esc(error)}` : 'Skill demand unavailable.',
        error ? '#f59e0b' : undefined,
      );
      return;
    }
    const list = Array.isArray(skills.skills) ? skills.skills : [];
    if (!list.length) {
      const total = this._count(skills.total_jobs, 0);
      this.topSkillsCloud.innerHTML = this._skillNote(
        total > 0
          ? `No <code>tech_stack</code> data on ${total} active listing${total === 1 ? '' : 's'} yet — run a scrape with enrichment.`
          : 'No active listings yet — run a scrape to populate skill demand.',
      );
      return;
    }
    this.topSkillsCloud.innerHTML = list.map(sk => `
      <div class="skill-pill" title="${esc(sk.name)} — ${esc(sk.count)} of ${esc(skills.jobs_with_stack)} listings with a stack">
        <span>${esc(sk.name)}</span>
        <span class="skill-pct">${esc(sk.pct)}%</span>
      </div>
    `).join('');
  },

  render() {
    const { stats, tracker, skills, loading, errors } = JobAgent.store.state;

    this._applyMetrics(stats);
    this._applyPipelineMetrics(tracker);

    // 1. Scraper Sources Grid — live by_source, else an honest note.
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
      } else {
        // No mock fallback exists (mockData.js was never shipped), so say what
        // actually happened instead of leaving the loading text on screen.
        const esc = (JobAgent.escapeHtml || ((v) => String(v ?? '')));
        this.sourcesGrid.innerHTML = errors.stats
          ? `<div style="font-size:12.5px;color:#f59e0b;padding:12px;">Source stats unavailable: ${esc(errors.stats)}</div>`
          : `<div style="color: var(--text-muted); font-size: 12.5px; padding: 12px;">No live sources yet — run a scrape.</div>`;
      }
    }

    // 2. Skills cloud — live GET /api/skills aggregate over tech_stack.
    this._renderSkills(skills, loading.skills, errors.skills);
  }
};
