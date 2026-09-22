/**
 * JOBDESK.JS — Curated Jobs Matrix, Advanced Multi-Filters & Dual View Switch
 */

window.JobAgent = window.JobAgent || {};

JobAgent.jobDesk = {
  init() {
    this.jobFilterSearch = document.getElementById('jobFilterSearch');
    this.rolePills = document.querySelectorAll('.role-pill');
    this.scoreRange = document.getElementById('scoreRange');
    this.scoreRangeValue = document.getElementById('scoreRangeValue');
    this.locationFilter = document.getElementById('locationFilter');
    this.sourceFilter = document.getElementById('sourceFilter');
    this.statusFilter = document.getElementById('statusFilter');
    this.filteredJobCount = document.getElementById('filteredJobCount');

    this.btnViewGrid = document.getElementById('btnViewGrid');
    this.btnViewTable = document.getElementById('btnViewTable');
    this.jobsGridContainer = document.getElementById('jobsGridContainer');
    this.jobsTableContainer = document.getElementById('jobsTableContainer');
    this.jobsTableBody = document.getElementById('jobsTableBody');

    this.bindEvents();
    this.render();

    // Subscribe to store changes
    JobAgent.store.subscribe((state) => {
      this.render();
    });
  },

  bindEvents() {
    // Search input
    if (this.jobFilterSearch) {
      this.jobFilterSearch.addEventListener('input', (e) => {
        JobAgent.store.setFilter('search', e.target.value.toLowerCase());
      });
    }

    // Role Pills
    this.rolePills.forEach(pill => {
      pill.addEventListener('click', () => {
        this.rolePills.forEach(p => p.classList.remove('active'));
        pill.classList.add('active');
        JobAgent.store.setFilter('role', pill.dataset.role);
      });
    });

    // Score Range Slider
    if (this.scoreRange) {
      this.scoreRange.addEventListener('input', (e) => {
        const val = parseInt(e.target.value);
        this.scoreRangeValue.textContent = `${val}%`;
        JobAgent.store.setFilter('minScore', val);
      });
    }

    // Location Filter
    if (this.locationFilter) {
      this.locationFilter.addEventListener('change', (e) => {
        JobAgent.store.setFilter('location', e.target.value);
      });
    }

    // Source Filter
    if (this.sourceFilter) {
      this.sourceFilter.addEventListener('change', (e) => {
        JobAgent.store.setFilter('source', e.target.value);
      });
    }

    // Status Filter
    if (this.statusFilter) {
      this.statusFilter.addEventListener('change', (e) => {
        JobAgent.store.setFilter('status', e.target.value);
      });
    }

    // View Switcher (Grid vs Table)
    if (this.btnViewGrid && this.btnViewTable) {
      this.btnViewGrid.addEventListener('click', () => {
        this.btnViewGrid.classList.add('active');
        this.btnViewTable.classList.remove('active');
        this.jobsGridContainer.classList.remove('hidden');
        this.jobsTableContainer.classList.add('hidden');
        JobAgent.store.setViewMode('grid');
      });

      this.btnViewTable.addEventListener('click', () => {
        this.btnViewTable.classList.add('active');
        this.btnViewGrid.classList.remove('active');
        this.jobsGridContainer.classList.add('hidden');
        this.jobsTableContainer.classList.remove('hidden');
        JobAgent.store.setViewMode('table');
      });
    }
  },

  getFilteredJobs() {
    const filters = JobAgent.store.state.filters;
    return (JobAgent.MOCK_JOBS || []).filter(job => {
      // Search
      if (filters.search) {
        const query = filters.search;
        const inTitle = job.job_title.toLowerCase().includes(query);
        const inCompany = job.company.toLowerCase().includes(query);
        const inStack = job.tech_stack.some(t => t.toLowerCase().includes(query));
        if (!inTitle && !inCompany && !inStack) return false;
      }

      // Role
      if (filters.role !== 'all' && job.role !== filters.role) {
        return false;
      }

      // Score
      if (job.match_score < filters.minScore) {
        return false;
      }

      // Location
      if (filters.location !== 'all') {
        if (filters.location === 'worldwide' && !job.timezone.toLowerCase().includes('worldwide')) return false;
        if (filters.location === 'usa' && !job.timezone.toLowerCase().includes('usa')) return false;
        if (filters.location === 'uk' && !job.timezone.toLowerCase().includes('uk')) return false;
        if (filters.location === 'europe' && !job.timezone.toLowerCase().includes('europe')) return false;
      }

      // Source
      if (filters.source !== 'all' && job.source !== filters.source) {
        return false;
      }

      // Status
      if (filters.status !== 'all' && job.status !== filters.status) {
        return false;
      }

      return true;
    });
  },

  getScoreTierClass(score) {
    if (score >= 85) return 'top-tier';
    if (score >= 70) return 'good-tier';
    return 'low-tier';
  },

  getScorePillClass(score) {
    if (score >= 85) return 'top';
    if (score >= 70) return 'good';
    return 'low';
  },

  render() {
    const jobs = this.getFilteredJobs();

    if (this.filteredJobCount) {
      this.filteredJobCount.textContent = jobs.length;
    }

    // 1. Render Card Grid
    if (this.jobsGridContainer) {
      if (jobs.length === 0) {
        this.jobsGridContainer.innerHTML = `
          <div style="grid-column: 1 / -1; padding: 48px; text-align: center; color: var(--text-muted); background: var(--bg-card); border-radius: var(--radius-lg); border: 1px dashed var(--border-subtle);">
            <p style="font-size: 15px; font-weight: 600; color: var(--text-primary); margin-bottom: 6px;">No remote jobs match current filters</p>
            <p style="font-size: 12.5px;">Try lowering the minimum score slider or clearing role/location filters.</p>
          </div>
        `;
      } else {
        const selectedId = JobAgent.store.state.selectedJob ? JobAgent.store.state.selectedJob.id : null;
        this.jobsGridContainer.innerHTML = jobs.map(job => `
          <div class="job-card ${selectedId === job.id ? 'is-selected' : ''}" data-id="${job.id}">
            <div class="job-card-top">
              <div class="job-title-group">
                <h3 class="job-role-title">${job.job_title}</h3>
                <div class="job-company-name">
                  <span>${job.company}</span>
                  <span>•</span>
                  <span class="text-muted" style="font-size: 11.5px;">${job.posted_text}</span>
                </div>
              </div>
              <div class="match-score-badge ${this.getScoreTierClass(job.match_score)}" title="ATS Match Score">
                <span class="score-val">${job.match_score}</span>
                <span class="score-unit">%</span>
              </div>
            </div>

            <div class="job-meta-chips">
              <span class="meta-chip">📍 ${job.timezone}</span>
              ${job.salary ? `<span class="meta-chip salary">💰 ${job.salary}</span>` : ''}
              <span class="meta-chip">🏷️ ${job.role.toUpperCase()}</span>
            </div>

            <p class="job-summary-snippet">${job.summary}</p>

            <div class="job-tech-pills">
              ${job.tech_stack.map(t => `<span class="tech-tag">${t}</span>`).join('')}
            </div>

            <div class="job-card-footer">
              <span class="job-source-tag">${job.source}</span>
              <div class="card-action-group">
                <button class="action-btn secondary small btn-tailor-job" data-id="${job.id}" title="Tailor 1-page ATS resume">
                  ✨ Tailor
                </button>
                <button class="action-btn primary small btn-open-drawer" data-id="${job.id}">
                  Inspect
                </button>
              </div>
            </div>
          </div>
        `).join('');
      }
    }

    // 2. Render Table View
    if (this.jobsTableBody) {
      this.jobsTableBody.innerHTML = jobs.map(job => `
        <tr data-id="${job.id}">
          <td>
            <span class="score-cell-pill ${this.getScorePillClass(job.match_score)}">${job.match_score}%</span>
          </td>
          <td>
            <strong style="color: #fff; display: block;">${job.job_title}</strong>
            <span style="color: var(--text-muted); font-size: 11.5px;">${job.company}</span>
          </td>
          <td style="color: var(--text-secondary); font-size: 12px;">${job.timezone}</td>
          <td>
            <div style="display: flex; gap: 4px; flex-wrap: wrap; max-width: 220px;">
              ${job.tech_stack.slice(0, 3).map(t => `<span class="tech-tag">${t}</span>`).join('')}
              ${job.tech_stack.length > 3 ? `<span class="tech-tag">+${job.tech_stack.length - 3}</span>` : ''}
            </div>
          </td>
          <td style="font-family: var(--font-mono); font-size: 12px; color: var(--accent-cyan);">
            ${job.salary || '—'}
          </td>
          <td style="color: var(--text-muted); font-size: 12px;">${job.source}</td>
          <td style="color: var(--text-muted); font-size: 12px;">${job.posted_text}</td>
          <td style="text-align: right;">
            <button class="action-btn secondary small btn-open-drawer" data-id="${job.id}">Inspect</button>
          </td>
        </tr>
      `).join('');
    }

    // Bind item click interactions
    document.querySelectorAll('.job-card, .jobs-table tbody tr').forEach(el => {
      el.addEventListener('click', (e) => {
        // Direct tailor action
        if (e.target.closest('.btn-tailor-job')) {
          e.stopPropagation();
          const id = parseInt(e.target.closest('.btn-tailor-job').dataset.id);
          const job = JobAgent.MOCK_JOBS.find(j => j.id === id);
          if (job && JobAgent.navigation) {
            JobAgent.navigation.switchTab('resume');
            const tailorSelect = document.getElementById('tailorJobSelect');
            if (tailorSelect) tailorSelect.value = id;
          }
          return;
        }

        const id = parseInt(el.dataset.id);
        const job = JobAgent.MOCK_JOBS.find(j => j.id === id);
        if (job && JobAgent.jobDrawer) {
          JobAgent.jobDrawer.open(job);
        }
      });
    });
  }
};
