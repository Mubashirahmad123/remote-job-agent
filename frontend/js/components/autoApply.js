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
        const confirmed = confirm('⚠️ CAUTION: AUTO_APPLY_CONFIRM=true will submit live applications automatically via Playwright!\n\nAre you sure you want to activate live auto-submit mode?');
        if (confirmed) {
          this.btnModeSubmit.classList.add('active');
          this.btnModeReview.classList.remove('active');
          this.safetyStatusLabel.textContent = '⚡ LIVE AUTO-SUBMIT ACTIVE';
          this.safetyStatusLabel.className = 'badge-rose';
          JobAgent.store.setAutoApply('mode', 'submit');
          JobAgent.toast.show('WARNING: Live Auto-Submit mode engaged. Daily cap strictly enforced.');
        }
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

  triggerQueue() {
    this.appendTerminalLine('[QUEUE] Auto-apply batch triggered for candidate jobs scoring >= ' + JobAgent.store.state.autoApply.threshold + '%', 'term-indigo');

    setTimeout(() => {
      this.appendTerminalLine('[BROWSER] Launching Chromium (Playwright stealth headless)...', 'term-cyan');
    }, 600);

    setTimeout(() => {
      this.appendTerminalLine('[FILL] Navigating to Greenhouse ATS: KoboToolbox...', 'term-cyan');
    }, 1200);

    setTimeout(() => {
      this.appendTerminalLine('[FORM] Fields populated: Mubashir Ahmad, mubashir.dev@example.com', 'term-green');
    }, 1900);

    setTimeout(() => {
      this.appendTerminalLine('[SCREENSHOT] Verification captured: screenshots/kobo_review.png', 'term-amber');
      JobAgent.toast.show('Auto-apply batch finished. Screenshot saved for review.');
    }, 2600);
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
