/**
 * STORE.JS — Central Application Reactive State Manager
 * Now owns LIVE backend data (Phase 1 reads) with mock fallback.
 * Backend contract: api/schemas.py JobOut / TrackerEntry via js/api.js.
 */

window.JobAgent = window.JobAgent || {};

JobAgent.store = {
  state: {
    activeTab: 'dashboard',
    viewMode: 'grid', // 'grid' | 'table'
    selectedJob: null,
    filters: {
      search: '',
      role: 'all',
      minScore: 70,
      location: 'all',
      source: 'all',
      status: 'all'
    },
    autoApply: {
      mode: 'review', // 'review' | 'submit'
      threshold: 75,
      dailyCap: 5,
      appliedToday: 3
    },
    // ---- live data (populated by loadAll) ----
    jobs: [],
    tracker: [],
    stats: null,
    health: null,
    usingLive: false,
    dataSource: 'mock', // sheets|snapshot|mock (from GET /api/health)
    loading: { jobs: false, tracker: false, stats: false },
    errors: { jobs: '', tracker: '', stats: '' },
  },

  listeners: [],

  subscribe(listener) {
    this.listeners.push(listener);
  },

  notify() {
    this.listeners.forEach(fn => {
      try { fn(this.state); } catch (e) { console.error('[store] listener failed', e); }
    });
  },

  setTab(tab) {
    this.state.activeTab = tab;
    this.notify();
  },

  setViewMode(mode) {
    this.state.viewMode = mode;
    this.notify();
  },

  setSelectedJob(job) {
    this.state.selectedJob = job;
    this.notify();
  },

  setFilter(key, value) {
    this.state.filters[key] = value;
    this.notify();
  },

  setAutoApply(key, value) {
    this.state.autoApply[key] = value;
    this.notify();
  },

  // ---------- backend -> UI normalization ----------

  _deriveRole(title = '') {
    const t = (title || '').toLowerCase();
    if (/mobile|ios|android|react native|flutter/.test(t)) return 'mobile';
    if (/frontend|front-end|front end|react|vue|angular|ui\b/.test(t)) return 'frontend';
    if (/backend|back-end|back end|python|fastapi|django|microservice|api\b/.test(t)) return 'backend';
    if (/fullstack|full-stack|full stack/.test(t)) return 'fullstack';
    return 'fullstack';
  },

  _deriveLocationKey(timezone = '', location = '') {
    const s = ((timezone || '') + ' ' + (location || '')).toLowerCase();
    if (s.includes('worldwide') || s.includes('anywhere') || s.includes('global')) return 'worldwide';
    if (/\busa\b|united states|north america|\b us \b/.test(s)) return 'usa';
    if (/\buk\b|united kingdom|london/.test(s)) return 'uk';
    if (/europe|berlin|eu\b/.test(s)) return 'europe';
    return 'worldwide';
  },

  _postedText(iso = '') {
    if (!iso) return '';
    const d = new Date(iso);
    if (isNaN(d.getTime())) return String(iso).slice(0, 10);
    const days = Math.floor((Date.now() - d.getTime()) / 86400000);
    if (days <= 0) return 'Today';
    if (days === 1) return 'Yesterday';
    if (days < 7) return days + ' days ago';
    return d.toISOString().slice(0, 10);
  },

  _splitStack(raw) {
    if (Array.isArray(raw)) return raw.filter(Boolean).map(String);
    if (typeof raw !== 'string') return [];
    return raw.split(/[,;|]/).map(s => s.trim()).filter(Boolean);
  },

  normalizeJob(row = {}, idx = 0) {
    const fp = row.job_fingerprint || row.apply_url || ('row-' + idx);
    const stack = this._splitStack(row.tech_stack);
    const tz = row.timezone || row.location || 'Worldwide';
    return {
      id: fp, // fingerprint is the stable key (backend has no numeric id)
      job_fingerprint: row.job_fingerprint || '',
      job_title: row.job_title || 'Untitled role',
      company: row.company || 'Unknown',
      role: this._deriveRole(row.job_title),
      salary: row.salary || '',
      tech_stack: stack,
      timezone: tz,
      location_key: this._deriveLocationKey(row.timezone, row.location),
      apply_url: row.apply_url || '#',
      posted_date_iso: row.posted_date_iso || row.scraped_at || '',
      posted_text: this._postedText(row.posted_date_iso || row.scraped_at),
      source: row.source || 'unknown',
      match_score: typeof row.match_score === 'number' ? row.match_score : (parseFloat(row.match_score) || 0),
      status: (row.status || 'new').toLowerCase(),
      matched_cv: row.selected_cv || (row.selected_cv_path || '').split('/').pop() || '',
      matched_skills: stack.slice(0, 6),
      missing_skills: [],
      match_reason: row.match_reason || '',
      summary: row.summary || '',
      tab: row.tab || 'ALL JOBS',
      _raw: row,
    };
  },

  normalizeTracker(row = {}, idx = 0) {
    const status = (row.status || 'applied').toLowerCase();
    return {
      id: row.apply_url || ('tracker-' + idx),
      title: row.job_title || 'Untitled',
      company: row.company || 'Unknown',
      score: parseFloat(row.match_score) || 0,
      date: row.applied_date ? ('Applied ' + String(row.applied_date).slice(0, 10)) : '',
      follow_up: row.follow_up_date || '',
      status: ['applied', 'interviewing', 'offer', 'rejected', 'withdrawn', 'ghosted'].includes(status) ? status : 'applied',
      apply_url: row.apply_url || '',
      notes: row.notes || '',
      source: row.source || '',
      _raw: row,
    };
  },

  // ---------- loaders (live with mock fallback) ----------

  async loadJobs() {
    this.state.loading.jobs = true;
    this.state.errors.jobs = '';
    this.notify();
    try {
      const rows = await JobAgent.api.getJobs({ limit: 200 });
      this.state.jobs = rows.map((r, i) => this.normalizeJob(r, i));
      this.state.usingLive = true;
      // Snapshot rows are unscored (score 0) — drop the score gate so they
      // actually display, and sync the slider UI. Sheet rows keep minScore.
      const allUnscored = this.state.jobs.length > 0
        && this.state.jobs.every(j => !(j.match_score > 0));
      if (allUnscored) {
        this.state.dataSource = 'snapshot';
        this.state.filters.minScore = 0;
        const slider = document.getElementById('scoreRange');
        const label = document.getElementById('scoreRangeValue');
        if (slider) slider.value = '0';
        if (label) label.textContent = '0%';
      } else if (this.state.jobs.length > 0) {
        this.state.dataSource = this.state.dataSource === 'mock' ? 'sheets' : this.state.dataSource;
      }
    } catch (e) {
      this.state.errors.jobs = e.message;
      this.state.dataSource = 'mock';
      this.state.jobs = (JobAgent.MOCK_JOBS || []).map((j) => ({ ...j }));
      console.warn('[store] jobs fallback to mock:', e.message);
    } finally {
      this.state.loading.jobs = false;
      this.notify();
    }
  },

  async loadTracker() {
    this.state.loading.tracker = true;
    this.state.errors.tracker = '';
    this.notify();
    try {
      const rows = await JobAgent.api.getTracker();
      this.state.tracker = rows.map((r, i) => this.normalizeTracker(r, i));
      this.state.usingLive = this.state.usingLive || this.state.tracker.length > 0;
    } catch (e) {
      this.state.errors.tracker = e.message;
      // Map legacy MOCK_KANBAN shape to normalized tracker shape.
      this.state.tracker = (JobAgent.MOCK_KANBAN || []).map((c) => ({
        id: c.apply_url || String(c.id),
        title: c.title,
        company: c.company,
        score: c.score,
        date: c.date,
        follow_up: c.follow_up,
        status: c.status === 'review' ? 'applied' : c.status, // kanban 'review' is UI-only
        apply_url: c.apply_url || '',
        notes: '',
        source: '',
        _raw: c,
      }));
      console.warn('[store] tracker fallback to mock:', e.message);
    } finally {
      this.state.loading.tracker = false;
      this.notify();
    }
  },

  async loadStats() {
    this.state.loading.stats = true;
    this.state.errors.stats = '';
    this.notify();
    try {
      const [stats, health] = await Promise.all([
        JobAgent.api.getStats(),
        JobAgent.api.getHealth().catch(() => null),
      ]);
      this.state.stats = stats;
      this.state.health = health;
      if (health && health.data_source) this.state.dataSource = health.data_source;
      this.state.usingLive = true;
    } catch (e) {
      this.state.errors.stats = e.message;
      this.state.stats = null;
      console.warn('[store] stats fallback to mock:', e.message);
    } finally {
      this.state.loading.stats = false;
      this.notify();
    }
  },

  async loadAll() {
    await Promise.all([this.loadJobs(), this.loadTracker(), this.loadStats()]);
  },
};
