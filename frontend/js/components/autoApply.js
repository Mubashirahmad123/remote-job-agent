/**
 * AUTOAPPLY.JS — Safety Submission Toggles, Sliders, Live Telemetry & Proof Lightbox
 */

window.JobAgent = window.JobAgent || {};

JobAgent.autoApply = {
  init() {
    this.safetyStatusLabel = document.getElementById('safetyStatusLabel');
    this.btnModeReview = document.getElementById('btnModeReview');
    this.btnModeSubmit = document.getElementById('btnModeSubmit');
    this.autoApplyThreshold = document.getElementById('autoApplyThreshold');
    this.autoApplyThresholdVal = document.getElementById('autoApplyThresholdVal');
    this.dailyCapSlider = document.getElementById('dailyCapSlider');
    this.dailyCapVal = document.getElementById('dailyCapVal');
    this.btnRunAutoApplyQueue = document.getElementById('btnRunAutoApplyQueue');
    this.btnViewScreenshots = document.getElementById('btnViewScreenshots');
    this.terminalLog = document.getElementById('terminalLog');
    this.screenshotModal = document.getElementById('screenshotModal');
    this.btnCloseModal = document.getElementById('btnCloseModal');
    this.modalScreenshotImg = document.getElementById('modalScreenshotImg');

    this.bindEvents();
  },

  bindEvents() {
    // Safety Mode Toggles
    if (this.btnModeReview && this.btnModeSubmit) {
      this.btnModeReview.addEventListener('click', () => {
        this.btnModeReview.classList.add('active');
        this.btnModeSubmit.classList.remove('active');
        this.safetyStatusLabel.textContent = '🛡️ FILL & REVIEW (SAFE)';
        this.safetyStatusLabel.className = 'badge-emerald';
        JobAgent.store.setAutoApply('mode', 'review');
        JobAgent.toast.show('Safety Mode: Form filling only. Auto-submit disabled.');
      });

      this.btnModeSubmit.addEventListener('click', () => {
        // Phase 2a: submit is locked at three layers — disabled attribute
        // (index.html, no click events fire), this toast (defense in depth
        // if re-enabled), and the API rejects mode != review with 400.
        // No HTTP submit path exists (api/safety.py SUBMIT_ENABLED=False).
        JobAgent.toast.show('Locked: submit unlocks only when all four 2b gates close (see PM.md). No application was sent.');
      });
    }

    // Threshold Slider
    if (this.autoApplyThreshold) {
      this.autoApplyThreshold.addEventListener('input', (e) => {
        const val = e.target.value;
        this.autoApplyThresholdVal.textContent = `${val}%`;
        JobAgent.store.setAutoApply('threshold', parseInt(val));
      });
    }

    // Daily Cap Slider
    if (this.dailyCapSlider) {
      this.dailyCapSlider.addEventListener('input', (e) => {
        const val = e.target.value;
        this.dailyCapVal.textContent = `${val} / Day`;
        JobAgent.store.setAutoApply('dailyCap', parseInt(val));
      });
    }

    // Run Auto-Apply Queue Simulation
    if (this.btnRunAutoApplyQueue) {
      this.btnRunAutoApplyQueue.addEventListener('click', () => {
        this.triggerQueue();
      });
    }

    // Screenshot Lightbox Modal
    if (this.btnViewScreenshots) {
      this.btnViewScreenshots.addEventListener('click', () => {
        this.openModal();
      });
    }

    if (this.btnCloseModal) {
      this.btnCloseModal.addEventListener('click', () => this.closeModal());
    }

    if (this.screenshotModal) {
      this.screenshotModal.addEventListener('click', (e) => {
        if (e.target === this.screenshotModal) this.closeModal();
      });
    }
  },

  async triggerQueue() {
    const threshold = JobAgent.store.state.autoApply.threshold;
    const jobs = (JobAgent.store.state.jobs || []).filter(
      (j) => (j.match_score || 0) >= threshold
    );
    if (!jobs.length) {
      this.appendTerminalLine('[QUEUE] No candidate jobs scoring >= ' + threshold + '% — nothing to fill.', 'term-amber');
      JobAgent.toast.show('Auto-apply queue: no candidates at current threshold.');
      return;
    }
    const job = jobs[0];
    this.appendTerminalLine('[QUEUE] Fill-only review for: ' + job.job_title + ' @ ' + job.company, 'term-indigo');
    this.appendTerminalLine('[FILL] POST /api/apply/' + job.id + ' {mode: review} — submit unreachable by design', 'term-cyan');
    try {
      const res = await JobAgent.api.applyReview(job.id || job.job_fingerprint);
      this.appendTerminalLine('[READY] tier=' + (res.tier || '?') + ' status=' + (res.status || 'filled_ready'), 'term-green');
      this.appendTerminalLine('[PACKAGE] ' + (res.package_path || '(no path)'), 'term-amber');
      JobAgent.toast.show('Fill ready for review: ' + (res.job_title || job.job_title) + '. Package saved — open the job site to submit manually.');
    } catch (e) {
      this.appendTerminalLine('[ERROR] ' + (e && e.message ? e.message : e), 'term-rose');
      JobAgent.toast.show('Fill failed: ' + (e && e.message ? e.message : e));
    }
  },

  appendTerminalLine(text, cssClass) {
    if (!this.terminalLog) return;
    const time = new Date().toTimeString().split(' ')[0];
    const div = document.createElement('div');
    div.className = 'term-line timestamp';
    div.innerHTML = `[${time}] <span class="${cssClass}">${text}</span>`;
    this.terminalLog.appendChild(div);
    this.terminalLog.scrollTop = this.terminalLog.scrollHeight;
  },

  openModal() {
    if (this.screenshotModal) {
      this.screenshotModal.classList.remove('hidden');
      if (this.modalScreenshotImg) {
        this.modalScreenshotImg.src = "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='800' height='500' viewBox='0 0 800 500'><rect width='800' height='500' fill='%23111827'/><rect x='40' y='30' width='720' height='60' rx='8' fill='%231e293b'/><text x='60' y='68' fill='%2310b981' font-family='monospace' font-size='18' font-weight='bold'>Greenhouse Application — KoboToolbox (Review Mode)</text><rect x='40' y='110' width='340' height='45' rx='6' fill='%231e293b'/><text x='55' y='138' fill='%2394a3b8' font-family='sans-serif' font-size='14'>First Name: Mubashir</text><rect x='420' y='110' width='340' height='45' rx='6' fill='%231e293b'/><text x='435' y='138' fill='%2394a3b8' font-family='sans-serif' font-size='14'>Last Name: Ahmad</text><rect x='40' y='170' width='720' height='45' rx='6' fill='%231e293b'/><text x='55' y='198' fill='%2394a3b8' font-family='sans-serif' font-size='14'>Email: mubashir.dev@example.com</text><rect x='40' y='230' width='720' height='45' rx='6' fill='%231e293b'/><text x='55' y='258' fill='%2394a3b8' font-family='sans-serif' font-size='14'>Resume Attached: resume.pdf (1-page ATS Tailored)</text><rect x='40' y='290' width='720' height='120' rx='6' fill='%231e293b'/><text x='55' y='320' fill='%2394a3b8' font-family='sans-serif' font-size='13'>Cover Letter: I am writing to express my strong interest in the Frontend Web Application Developer role...</text><rect x='40' y='430' width='220' height='40' rx='6' fill='%2310b981'/><text x='85' y='455' fill='%23090d16' font-family='sans-serif' font-size='14' font-weight='bold'>Form Ready to Submit</text></svg>";
      }
    }
  },

  closeModal() {
    if (this.screenshotModal) {
      this.screenshotModal.classList.add('hidden');
    }
  }
};
