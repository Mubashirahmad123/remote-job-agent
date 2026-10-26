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
    this.btnDrawerRegenerate = document.getElementById('btnDrawerRegenerate');

    this.bindEvents();
    this.bindSheetGesture();
  },

  /**
   * The drawer is a bottom sheet on a phone and a side panel on a desktop,
   * so the drag gesture only exists in sheet mode. Below 600px the sheet is
   * pulled down to dismiss; above it, the surface is a fixed panel and a drag
   * would fight the page.
   */
  bindSheetGesture() {
    if (!this.jobDetailDrawer || !JobAgent.gestures) return;
    const sheetOnly = () => window.matchMedia('(max-width: 600px)').matches;

    JobAgent.gestures.swipeToDismiss(this.jobDetailDrawer, {
      axis: 'y',
      direction: 1, // pulling down dismisses
      dismissThreshold: 0.32,
      // The sheet is dragged by its grabber. The browser latches touch-action
      // when the gesture starts, so the region the finger lands on has to be
      // the one that opted out of the browser's scroll handling — and the
      // grabber is also the affordance that says the sheet can be moved.
      handle: this.jobDetailDrawer.querySelector('.drawer-header'),
      canStart: (delta) => {
        if (!sheetOnly()) return false;
        // The content owns the gesture while it is scrolled: a downward drag
        // there is a scroll, not a dismissal.
        const body = this.drawerBody;
        const scrolled = body && body.scrollTop > 0;
        return !(scrolled && delta > 0);
      },
      // Continuous feedback: the scrim lifts with the sheet, so the gesture
      // reads as one continuous motion rather than a drag plus an animation.
      onProgress: (ratio) => {
        if (!this.drawerOverlay) return;
        this.drawerOverlay.style.opacity = String(Math.max(0, 1 - ratio));
      },
      onDismiss: () => this.close(),
    });
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

    // Deliberate per-job rebuild. Only visible for a job that already has a
    // package (see open()), and it is the sole path that regenerates one — the
    // bulk Fill & Review button skips packaged jobs entirely.
    if (this.btnDrawerRegenerate) {
      this.btnDrawerRegenerate.addEventListener('click', () => {
        const job = JobAgent.store.state.selectedJob;
        if (!job) return;
        if (JobAgent.autoApply && JobAgent.autoApply.regeneratePackage) {
          JobAgent.autoApply.regeneratePackage(job);
        }
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
            <span>${esc(job.timezone)}</span>
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
            <span class="badge-emerald">Auto-picked</span>
          </div>
        </div>

        <div>
          <div class="drawer-section-title">Skills Overlap Analysis</div>
          <div class="skills-overlap-box">
            <div style="margin-bottom: 8px;">
              <span style="font-size: 12px; color: var(--text-muted); display: block; margin-bottom: 4px;">Direct Matched Competencies:</span>
              ${matched.map(s => `<span class="skill-match-tag matched">${esc(s)}</span>`).join('')}
            </div>
            ${missing.length > 0 ? `
              <div>
                <span style="font-size: 12px; color: var(--text-muted); display: block; margin-bottom: 4px;">Skills to Emphasize / Bridge:</span>
                ${missing.map(s => `<span class="skill-match-tag missing">${esc(s)}</span>`).join('')}
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

    if (this.btnDrawerRegenerate) {
      const fp = job.job_fingerprint || job.id || '';
      const packaged = JobAgent.store.isPackaged ? JobAgent.store.isPackaged(fp) : false;
      this.btnDrawerRegenerate.classList.toggle('hidden', !packaged);
      this.btnDrawerRegenerate.title = packaged
        ? "This job already has a package. Rebuild it with a fresh tailored resume and cover letter."
        : '';
    }

    this.drawerOverlay.classList.add('open');
    this.jobDetailDrawer.classList.add('open');
  },

  close() {
    if (this.drawerOverlay) {
      this.drawerOverlay.classList.remove('open');
      // Clear any inline opacity left by the drag gesture, so the overlay
      // returns to the state its class describes.
      this.drawerOverlay.style.opacity = '';
    }
    if (this.jobDetailDrawer) {
      this.jobDetailDrawer.classList.remove('open');
      this.jobDetailDrawer.style.transform = '';
    }
    JobAgent.store.setSelectedJob(null);
  }
};
