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
    this.reviewQueueResults = document.getElementById('reviewQueueResults');
    this.latestQueueResults = [];
    this._objectUrls = [];

    try {
      if (JobAgent.store.restoreAutoApplyPrefs) JobAgent.store.restoreAutoApplyPrefs();
    } catch (_) { /* ignore */ }
    this.syncCapUI();

    this.bindEvents();
  },

  syncCapUI() {
    try {
      const cap = parseInt(JobAgent.store.state.autoApply.dailyCap, 10) || 0;
      const used = JobAgent.store.getDailyUsage ? JobAgent.store.getDailyUsage() : 0;
      const remaining = Math.max(0, cap - used);
      const pct = cap > 0 ? Math.min(100, Math.round((used / cap) * 100)) : 0;
      if (this.dailyCapSlider) this.dailyCapSlider.value = String(cap);
      if (this.dailyCapVal) this.dailyCapVal.textContent = `${used}/${cap} today`;
      const sidebar = document.getElementById('sidebarCapVal');
      if (sidebar) sidebar.innerHTML = `Daily Apply Cap: <strong>${used} / ${cap}</strong>`;
      const metric = document.getElementById('metricDailyCap');
      if (metric) metric.textContent = `${used} / ${cap}`;
      const sub = document.getElementById('metricDailyCapSub');
      if (sub) sub.textContent = `Remaining: ${remaining} slot${remaining === 1 ? '' : 's'}`;
      const bar = document.getElementById('metricDailyCapBar');
      if (bar) bar.style.width = pct + '%';
    } catch (_) { /* ignore */ }
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
        // Greenhouse /intent + /submit routes exist but fail closed with 403
        // while api/safety.py SUBMIT_ENABLED=False (plus APPLY_API_TOKEN auth).
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
        JobAgent.store.setAutoApply('dailyCap', parseInt(val));
        this.syncCapUI();
      });
    }

    // Prepare fill-only review packages.
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
    const cap = parseInt(JobAgent.store.state.autoApply.dailyCap, 10) || 0;
    const used = JobAgent.store.getDailyUsage ? JobAgent.store.getDailyUsage() : 0;
    const remaining = Math.max(0, cap - used);
    if (remaining <= 0) {
      const msg = `[CAP] Daily cap reached (${used}/${cap} today) — no further fills. Raise the cap slider or try again tomorrow.`;
      this.appendTerminalLine(msg, 'term-rose');
      JobAgent.toast.show(`Daily cap reached: ${used}/${cap} today. No fills started.`);
      this.syncCapUI();
      return;
    }
    let jobs = (JobAgent.store.state.jobs || []).filter(
      (job) => (job.match_score || 0) >= threshold && (job.id || job.job_fingerprint)
    ).sort((left, right) => (right.match_score || 0) - (left.match_score || 0)).slice(0, 3);
    if (!jobs.length) {
      this.appendTerminalLine('[QUEUE] No candidate jobs scoring >= ' + threshold + '% — nothing to fill.', 'term-amber');
      JobAgent.toast.show('Auto-apply queue: no candidates at current threshold.');
      return;
    }
    if (jobs.length > remaining) {
      this.appendTerminalLine(`[CAP] ${jobs.length} candidate(s) but only ${remaining} left of ${used}/${cap} today — running the top ${remaining}.`, 'term-amber');
      jobs = jobs.slice(0, remaining);
    }
    this.latestQueueResults = [];
    if (this.btnRunAutoApplyQueue) this.btnRunAutoApplyQueue.disabled = true;
    this.appendTerminalLine('[QUEUE] Preparing review packages for ' + jobs.length + ' job(s) scoring >= ' + threshold + '%. (' + used + '/' + cap + ' used today)', 'term-indigo');

    try {
      for (const [index, job] of jobs.entries()) {
        const fingerprint = job.id || job.job_fingerprint;
        this.appendTerminalLine('[PACKAGE ' + (index + 1) + '/' + jobs.length + '] ' + (job.job_title || 'Untitled') + ' @ ' + (job.company || 'Unknown company'), 'term-cyan');
        try {
          const response = await JobAgent.api.applyReview(fingerprint);
          const result = {
            fingerprint,
            jobTitle: response.job_title || job.job_title || 'Untitled job',
            company: response.company || job.company || 'Unknown company',
            status: response.status || 'filled_ready',
            tier: response.tier || 'unknown',
            packagePath: response.package_path || '',
            applyUrl: response.apply_url || job.apply_url || '',
            screenshotPath: response.screenshot_path || '',
            screenshotUrl: response.screenshot_url
              || (JobAgent.api.screenshotUrl ? JobAgent.api.screenshotUrl(fingerprint) : ''),
            browserOpened: response.browser_opened === true,
            error: response.fill_error || '',
          };
          this.latestQueueResults.push(result);
          const lineClass = result.error || result.status === 'error' ? 'term-rose' : (result.status === 'filled_ready' ? 'term-green' : 'term-amber');
          this.appendTerminalLine('[' + result.status.toUpperCase() + '] (' + result.tier + ') — ' + result.jobTitle + (result.error ? ': ' + result.error : ''), lineClass);
          if (result.packagePath) this.appendTerminalLine('[PACKAGE] ' + result.packagePath, 'term-amber');
        } catch (error) {
          const message = error && error.message ? error.message : String(error);
          this.latestQueueResults.push({
            fingerprint,
            jobTitle: job.job_title || 'Untitled job',
            company: job.company || 'Unknown company',
            status: 'failed',
            tier: '',
            packagePath: '',
            screenshotPath: '',
            screenshotUrl: '',
            error: message,
          });
          this.appendTerminalLine('[ERROR] ' + (job.job_title || 'Job') + ': ' + message, 'term-rose');
        }
      }

      const attempted = this.latestQueueResults.length;
      if (attempted > 0 && JobAgent.store.consumeDailyQuota) JobAgent.store.consumeDailyQuota(attempted);
      this.syncCapUI();
      const packageCount = this.latestQueueResults.filter((result) => result.packagePath).length;
      const filledCount = this.latestQueueResults.filter((result) => result.status === 'filled_ready').length;
      const failedCount = this.latestQueueResults.filter((result) => result.error || result.status === 'error' || result.status === 'playwright_not_installed').length;
      const reviewWindowCount = this.latestQueueResults.filter((result) => result.browserOpened).length;
      this.renderQueueResults();
      JobAgent.toast.show('Review queue finished: ' + packageCount + ' package(s), ' + filledCount + ' form(s) filled, ' + reviewWindowCount + ' review window(s) open, ' + failedCount + ' fill failure(s). Nothing was submitted.');
    } finally {
      if (this.btnRunAutoApplyQueue) this.btnRunAutoApplyQueue.disabled = false;
    }
  },

  appendTerminalLine(text, cssClass) {
    if (!this.terminalLog) return;
    const time = new Date().toTimeString().split(' ')[0];
    const div = document.createElement('div');
    div.className = 'term-line timestamp';
    div.append(`[${time}] `);
    const message = document.createElement('span');
    message.className = cssClass;
    message.textContent = text;
    div.appendChild(message);
    this.terminalLog.appendChild(div);
    this.terminalLog.scrollTop = this.terminalLog.scrollHeight;
  },

  renderQueueResults() {
    if (!this.reviewQueueResults) return;
    // Revoke prior preview blob URLs before re-rendering so re-running the
    // queue without closing the modal does not leak object URLs.
    try {
      if (this._objectUrls && this._objectUrls.length) {
        for (const url of this._objectUrls) URL.revokeObjectURL(url);
      }
      this._objectUrls = [];
    } catch (_) { /* ignore */ }
    this.reviewQueueResults.replaceChildren();

    if (!this.latestQueueResults.length) {
      const empty = document.createElement('p');
      empty.className = 'review-results-empty';
      empty.textContent = 'No review packages have been prepared in this session.';
      this.reviewQueueResults.appendChild(empty);
      return;
    }

    for (const result of this.latestQueueResults) {
      const item = document.createElement('article');
      item.className = 'review-result-item';
      const heading = document.createElement('h4');
      heading.textContent = result.jobTitle + ' @ ' + result.company;
      const status = document.createElement('p');
      const failed = Boolean(result.error) || result.status === 'error' || result.status === 'playwright_not_installed';
      status.className = failed ? 'review-result-status is-error' : 'review-result-status';
      status.textContent = result.error
        ? result.status + ': ' + result.error
        : result.browserOpened
          ? 'Form filled in open browser · Review and submit manually if ready'
          : result.status + ' · ' + result.tier;
      item.append(heading, status);
      if (result.applyUrl && !result.browserOpened) {
        const applyLink = document.createElement('a');
        applyLink.className = 'review-result-link';
        applyLink.href = result.applyUrl;
        applyLink.target = '_blank';
        applyLink.rel = 'noopener noreferrer';
        applyLink.textContent = 'Open posting';
        item.appendChild(applyLink);
      }
      if (result.packagePath) {
        const path = document.createElement('p');
        path.className = 'review-result-path';
        path.textContent = 'Package saved on server: ' + result.packagePath;
        item.appendChild(path);
      }
      if (result.screenshotUrl || result.screenshotPath) {
        this.appendScreenshotPreview(item, result);
      } else {
        const emptyShot = document.createElement('p');
        emptyShot.className = 'review-result-path';
        emptyShot.textContent = 'No screenshot yet — package-only (no form fill ran for this ATS).';
        item.appendChild(emptyShot);
      }
      this.reviewQueueResults.appendChild(item);
    }
  },

  appendScreenshotPreview(item, result) {
    const wrap = document.createElement('div');
    wrap.className = 'screenshot-preview';
    const caption = document.createElement('p');
    caption.className = 'review-result-path';
    caption.textContent = result.screenshotPath
      ? 'Pre-submit screenshot: ' + result.screenshotPath
      : 'Pre-submit screenshot preview';
    const img = document.createElement('img');
    img.className = 'screenshot-preview-img';
    img.alt = 'Pre-submit screenshot for ' + (result.jobTitle || 'job');
    img.loading = 'lazy';
    const fallback = document.createElement('p');
    fallback.className = 'review-result-path screenshot-preview-fallback hidden';
    wrap.append(caption, img, fallback);
    item.appendChild(wrap);

    const directUrl = result.screenshotUrl
      || (result.fingerprint && JobAgent.api.screenshotUrl
        ? JobAgent.api.screenshotUrl(result.fingerprint)
        : '');
    if (!directUrl) {
      img.classList.add('hidden');
      fallback.classList.remove('hidden');
      fallback.textContent = 'No screenshot yet — package-only (no form fill ran for this ATS).';
      return;
    }
    // Direct <img> works on open local-dev (no API_TOKEN). If the API is
    // token-protected, <img> cannot send Authorization, so fall back to an
    // authenticated fetch -> blob URL. Either way never show a broken icon.
    img.src = directUrl;
    img.onerror = async () => {
      img.onerror = null;
      if (!result.fingerprint || !JobAgent.api.fetchScreenshotBlob) {
        img.classList.add('hidden');
        fallback.classList.remove('hidden');
        fallback.textContent = 'Screenshot unavailable — open the file path on the server.';
        return;
      }
      try {
        const blob = await JobAgent.api.fetchScreenshotBlob(result.fingerprint);
        const objectUrl = URL.createObjectURL(blob);
        if (this._objectUrls) this._objectUrls.push(objectUrl);
        img.src = objectUrl;
      } catch (e) {
        img.classList.add('hidden');
        fallback.classList.remove('hidden');
        fallback.textContent = (e && e.code === 'NO_SCREENSHOT')
          ? 'No screenshot yet — package-only (no form fill ran for this ATS).'
          : 'Screenshot unavailable: ' + ((e && e.message) || 'fetch failed');
      }
    };
  },

  openModal() {
    if (this.screenshotModal) {
      this.renderQueueResults();
      this.screenshotModal.classList.remove('hidden');
    }
  },

  closeModal() {
    if (this.screenshotModal) {
      this.screenshotModal.classList.add('hidden');
    }
    try {
      if (this._objectUrls) {
        for (const url of this._objectUrls) URL.revokeObjectURL(url);
        this._objectUrls = [];
      }
    } catch (_) { /* ignore */ }
  }
};
