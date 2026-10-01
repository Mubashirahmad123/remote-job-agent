/**
 * JOBDRAWER.JS — Linear-Style Slide-Over Detail Drawer
 */

window.JobAgent = window.JobAgent || {};

JobAgent.jobDrawer = {
  init() {
    this.drawerOverlay = document.getElementById('drawerOverlay');
    this.jobDetailDrawer = document.getElementById('jobDetailDrawer');
    this.btnDrawerClose = document.getElementById('btnDrawerClose');
    this.drawerBody = document.getElementById('drawerBody');
    this.btnDrawerApplyNow = document.getElementById('btnDrawerApplyNow');
    this.btnDrawerSave = document.getElementById('btnDrawerSave');

    this.bindEvents();
  },

  bindEvents() {
    if (this.btnDrawerClose) {
      this.btnDrawerClose.addEventListener('click', () => this.close());
    }

    if (this.drawerOverlay) {
      this.drawerOverlay.addEventListener('click', () => this.close());
    }

    if (this.btnDrawerSave) {
      this.btnDrawerSave.addEventListener('click', () => {
        JobAgent.toast.show('Job bookmarked in your saved list.');
      });
    }
  },

  open(job) {
    JobAgent.store.setSelectedJob(job);

    const stack = Array.isArray(job.tech_stack)
      ? job.tech_stack
      : String(job.tech_stack || '').split(/[,;|]/).map(s => s.trim()).filter(Boolean);
    const matched = Array.isArray(job.matched_skills) && job.matched_skills.length
      ? job.matched_skills
      : stack.slice(0, 6);
    const missing = Array.isArray(job.missing_skills) ? job.missing_skills : [];
    const cvName = job.matched_cv || job.selected_cv || (job._raw && job._raw.selected_cv) || 'Default CV';
    const score = job.match_score ?? 0;
    // Scraped job fields are untrusted — escape everything interpolated below.
    const esc = (JobAgent.escapeHtml || ((v) => String(v ?? '')));
    const safeScore = Number.isFinite(Number(score)) ? Number(score) : 0;

    if (this.drawerBody) {
      this.drawerBody.innerHTML = `
        <div class="drawer-job-header">
          <h2>${esc(job.job_title)}</h2>
          <div class="drawer-company-row">
            <strong>${esc(job.company)}</strong>
            <span>•</span>
            <span>📍 ${esc(job.timezone)}</span>
            <span>•</span>
            <span class="text-cyan" style="color: var(--accent-cyan);">${esc(job.salary || 'Competitive')}</span>
          </div>
        </div>

        <div class="drawer-score-banner">
          <div class="score-big-pill">${safeScore}%</div>
          <div class="score-explanation-text">
            <strong>AI Match Rationale:</strong>
            <p>${esc(job.match_reason || 'No rationale recorded.')}</p>
          </div>
        </div>

        <div>
          <div class="drawer-section-title">Selected CV Variant</div>
          <div class="cv-variant-card selected" style="margin-top: 0;">
            <div class="variant-info">
              <span class="variant-name">${esc(cvName)}</span>
              <span class="variant-meta">Matched by Keyword Overlap & FAISS Cosine Vector</span>
            </div>
            <span class="badge-emerald">AUTO-PICKED</span>
          </div>
        </div>

        <div>
          <div class="drawer-section-title">Skills Overlap Analysis</div>
          <div class="skills-overlap-box">
            <div style="margin-bottom: 8px;">
              <span style="font-size: 11px; color: var(--text-muted); display: block; margin-bottom: 4px;">Direct Matched Competencies:</span>
              ${matched.map(s => `<span class="skill-match-tag matched">✓ ${esc(s)}</span>`).join('')}
            </div>
            ${missing.length > 0 ? `
              <div>
                <span style="font-size: 11px; color: var(--text-muted); display: block; margin-bottom: 4px;">Skills to Emphasize / Bridge:</span>
                ${missing.map(s => `<span class="skill-match-tag missing">⚠ ${esc(s)}</span>`).join('')}
              </div>
            ` : ''}
          </div>
        </div>

        <div>
          <div class="drawer-section-title">Full Job Description</div>
          <div class="drawer-description-text">${esc(job.summary || '')}

Role Requirements:
• 3+ years of professional software engineering experience.
• Hands-on familiarity building production grade applications with ${esc(stack.join(', ') || 'modern tooling')}.
• Proven track record working with distributed remote teams across asynchronous workflows.
• Clean code principles, unit testing coverage, and collaborative git practices.
          </div>
        </div>
      `;
    }

    if (this.btnDrawerApplyNow) {
      // Only http(s) posting URLs are ever assigned; anything else (e.g.
      // javascript:, data:) degrades to a disabled dead link.
      const rawUrl = String(job.apply_url || '').trim();
      if (/^https?:\/\//i.test(rawUrl)) {
        this.btnDrawerApplyNow.href = rawUrl;
        this.btnDrawerApplyNow.removeAttribute('aria-disabled');
        this.btnDrawerApplyNow.title = '';
      } else {
        this.btnDrawerApplyNow.href = '#';
        this.btnDrawerApplyNow.setAttribute('aria-disabled', 'true');
        this.btnDrawerApplyNow.title = 'Posting link unavailable';
      }
    }

    this.drawerOverlay.classList.add('open');
    this.jobDetailDrawer.classList.add('open');
  },

  close() {
    if (this.drawerOverlay) this.drawerOverlay.classList.remove('open');
    if (this.jobDetailDrawer) this.jobDetailDrawer.classList.remove('open');
    JobAgent.store.setSelectedJob(null);
  }
};
