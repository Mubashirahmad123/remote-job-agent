/**
 * TRACKER.JS — Application Pipeline Kanban Board & Status Management
 * Live data: GET /api/tracker + POST /api/tracker + PATCH /api/tracker/{fp}.
 * Backend statuses: applied|interviewing|offer|rejected|withdrawn|ghosted.
 * UI columns: applied / review (fill-only packages) / interview / offer / rejected.
 */

window.JobAgent = window.JobAgent || {};

JobAgent.tracker = {
  _reviewStatuses: new Set([
    'review',
    'filled_ready',
    'filled_ready_submit_disabled',
    'needs_review',
    'custom_questions',
    'package_only',
    'email_draft',
    'playwright_not_installed',
    'playwright_failed',
    'dream_manual',
    'submit_unverified',
    'failed_refunded',
  ]),

  _terminalStatuses: new Set(['rejected', 'withdrawn', 'ghosted']),

  _manualFieldIds: {
    apply_url: 'manualApplyUrl',
    job_title: 'manualJobTitle',
    company: 'manualCompany',
    source: 'manualSource',
    salary: 'manualSalary',
    contact: 'manualContact',
    follow_up_days: 'manualFollowUpDays',
    notes: 'manualNotes',
  },

  _pendingUpdates: new Set(),
  _syncing: false,
  _manualSaving: false,
  _manualModalOpen: false,
  _manualLastFocus: null,

  _status(status) {
    return String(status || 'applied').trim().toLowerCase() || 'applied';
  },

  _isTerminalStatus(status) {
    return this._terminalStatuses.has(this._status(status));
  },

  // backend/sheet status -> kanban column. Fill-only auto-apply outcomes are
  // not backend PATCH statuses, but they are real pipeline states and should
  // show in Under Review instead of being hidden under Applied.
  _colFor(status) {
    const s = this._status(status);
    if (this._terminalStatuses.has(s)) return 'rejected';
    if (this._reviewStatuses.has(s) || s.startsWith('filled_')) return 'review';
    if (s === 'applied' || s === 'submitted') return 'applied';
    if (s === 'interviewing' || s === 'interview') return 'interview';
    if (s === 'offer') return 'offer';
    return 'applied';
  },

  // Click cycle sends only backend-valid statuses. Review/fill-only cards move
  // to interviewing once the operator confirms progress. Archived terminal
  // statuses intentionally stop the cycle so rejected/withdrawn/ghosted cards
  // never jump back to Applied by accident.
  _nextBackendStatus(current) {
    if (this._isTerminalStatus(current)) return null;
    const col = this._colFor(current);
    if (col === 'applied' || col === 'review') return 'interviewing';
    if (col === 'interview') return 'offer';
    if (col === 'offer') return 'rejected';
    return null;
  },

  _statusLabel(status) {
    const s = this._status(status);
    const labels = {
      applied: 'Applied',
      submitted: 'Submitted',
      review: 'Review',
      filled_ready: 'Filled · Review',
      filled_ready_submit_disabled: 'Filled · Submit Disabled',
      needs_review: 'Needs Review',
      custom_questions: 'Needs Questions',
      package_only: 'Package Ready',
      email_draft: 'Email Draft',
      playwright_not_installed: 'Fill Unavailable',
      playwright_failed: 'Fill Failed',
      dream_manual: 'Dream · Manual',
      submit_unverified: 'Submit Unverified',
      failed_refunded: 'Retry Needed',
      interviewing: 'Interviewing',
      interview: 'Interviewing',
      offer: 'Offer',
      rejected: 'Rejected',
      withdrawn: 'Withdrawn',
      ghosted: 'Ghosted',
    };
    return labels[s] || s.replace(/_/g, ' ').replace(/\b\w/g, (m) => m.toUpperCase());
  },

  _patchKey(card) {
    return (card && card._raw && (card._raw.job_fingerprint || card._raw.apply_url))
      || (card && (card.job_fingerprint || card.apply_url || card.id))
      || '';
  },

  _canPatchKey(key) {
    const value = String(key || '').trim();
    if (!value || value === '#') return false;
    if (value.startsWith('tracker-') || value.startsWith('mock-')) return false;
    // Old mock IDs are small integers; real fingerprints/URLs are not.
    if (/^\d+$/.test(value)) return false;
    return true;
  },

  _normalizeApplyUrl(value) {
    const raw = String(value || '').trim();
    if (!raw) throw new Error('Application URL is required.');

    let cleaned = raw;
    const explicitScheme = cleaned.match(/^([a-z][a-z\d+.-]*):/i);
    const looksLikeHostPort = /^[a-z0-9.-]+:\d+(?:[/?#]|$)/i.test(cleaned);
    if (explicitScheme && !looksLikeHostPort) {
      const scheme = explicitScheme[1].toLowerCase();
      if (scheme !== 'http' && scheme !== 'https') {
        throw new Error('Only http(s) application URLs can be tracked.');
      }
    }

    if (/^\/\//.test(cleaned)) {
      cleaned = 'https:' + cleaned;
    } else if (!/^https?:/i.test(cleaned)) {
      cleaned = 'https://' + cleaned;
    }

    let parsed;
    try {
      parsed = new URL(cleaned);
    } catch (_) {
      throw new Error('Enter a valid application URL.');
    }
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
      throw new Error('Only http(s) application URLs can be tracked.');
    }
    if (!parsed.hostname) {
      throw new Error('Enter a valid application URL.');
    }
    return parsed.href;
  },

  init() {
    this.kanbanColApplied = document.getElementById('kanbanColApplied');
    this.kanbanColReview = document.getElementById('kanbanColReview');
    this.kanbanColInterview = document.getElementById('kanbanColInterview');
    this.kanbanColOffer = document.getElementById('kanbanColOffer');
    this.kanbanColRejected = document.getElementById('kanbanColRejected');
    this.btnSyncTrackerSheets = document.getElementById('btnSyncTrackerSheets');
    this.btnNewTrackedJob = document.getElementById('btnNewTrackedJob');

    this.manualApplicationModal = document.getElementById('manualApplicationModal');
    this.manualApplicationForm = document.getElementById('manualApplicationForm');
    this.btnCloseManualApplicationModal = document.getElementById('btnCloseManualApplicationModal');
    this.btnCancelManualApplication = document.getElementById('btnCancelManualApplication');
    this.btnSaveManualApplication = document.getElementById('btnSaveManualApplication');
    this.manualApplicationSaveLabel = document.getElementById('manualApplicationSaveLabel');
    this.manualApplicationStatus = document.getElementById('manualApplicationStatus');
    this.manualApplicationFields = {};
    for (const [name, id] of Object.entries(this._manualFieldIds)) {
      this.manualApplicationFields[name] = document.getElementById(id);
    }
    this.manualApplicationErrors = {};
    if (this.manualApplicationModal) {
      this.manualApplicationModal.querySelectorAll('[data-error-for]').forEach((node) => {
        this.manualApplicationErrors[node.dataset.errorFor] = node;
      });
    }

    this.bindEvents();
    this.render();
    JobAgent.store.subscribe(() => this.render());
  },

  bindEvents() {
    if (this.btnSyncTrackerSheets) {
      this.btnSyncTrackerSheets.addEventListener('click', async () => {
        if (this._syncing) return;
        this._syncing = true;
        this.btnSyncTrackerSheets.disabled = true;
        JobAgent.toast.show('Refreshing tracker from /api/tracker…');
        try {
          await JobAgent.api.refreshJobs('APPLIED');
          await JobAgent.store.loadTracker({ throwOnError: true });
          JobAgent.toast.show('Tracker synced with APPLIED sheet tab.');
        } catch (e) {
          JobAgent.toast.show('Sync failed: ' + e.message, 'error');
        } finally {
          this._syncing = false;
          this.btnSyncTrackerSheets.disabled = false;
        }
      });
    }

    if (this.btnNewTrackedJob) {
      this.btnNewTrackedJob.addEventListener('click', () => this.addManualApplication());
    }

    if (this.manualApplicationForm) {
      this.manualApplicationForm.addEventListener('submit', (event) => {
        event.preventDefault();
        this.submitManualApplication();
      });
    }

    if (this.btnCancelManualApplication) {
      this.btnCancelManualApplication.addEventListener('click', () => this.closeManualApplicationModal());
    }

    if (this.btnCloseManualApplicationModal) {
      this.btnCloseManualApplicationModal.addEventListener('click', () => this.closeManualApplicationModal());
    }

    if (this.manualApplicationModal) {
      this.manualApplicationModal.addEventListener('click', (event) => {
        if (event.target === this.manualApplicationModal) this.closeManualApplicationModal();
      });
    }

    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && this._manualModalOpen) {
        this.closeManualApplicationModal();
      }
    });

    Object.entries(this.manualApplicationFields || {}).forEach(([name, field]) => {
      if (!field) return;
      field.addEventListener('input', () => {
        this._setManualFieldError(name, '');
        if (this.manualApplicationStatus && this.manualApplicationStatus.classList.contains('is-error')) {
          this._setManualStatus('');
        }
      });
    });
  },

  addManualApplication() {
    if (!JobAgent.api || !JobAgent.api.createTracker) {
      JobAgent.toast.show('Manual tracker add needs the API to be online.');
      return;
    }
    this.openManualApplicationModal();
  },

  openManualApplicationModal() {
    if (!this.manualApplicationModal || !this.manualApplicationForm) {
      JobAgent.toast.show('Manual application form is unavailable.');
      return;
    }

    this._manualLastFocus = document.activeElement;
    this._setManualSaving(false);
    this.manualApplicationForm.reset();
    this._clearManualValidation();
    this._setManualStatus('');

    if (this.manualApplicationFields.source) this.manualApplicationFields.source.value = 'manual';
    if (this.manualApplicationFields.follow_up_days) this.manualApplicationFields.follow_up_days.value = '7';

    this.manualApplicationModal.classList.remove('hidden');
    this.manualApplicationModal.setAttribute('aria-hidden', 'false');
    this._manualModalOpen = true;

    window.setTimeout(() => {
      if (this.manualApplicationFields.apply_url) this.manualApplicationFields.apply_url.focus();
    }, 0);
  },

  closeManualApplicationModal() {
    if (this._manualSaving) return;
    if (!this.manualApplicationModal) return;
    this.manualApplicationModal.classList.add('hidden');
    this.manualApplicationModal.setAttribute('aria-hidden', 'true');
    this._manualModalOpen = false;
    if (this._manualLastFocus && typeof this._manualLastFocus.focus === 'function') {
      try { this._manualLastFocus.focus(); } catch (_) { /* ignore detached element */ }
    }
    this._manualLastFocus = null;
  },

  _manualValue(name) {
    const field = this.manualApplicationFields && this.manualApplicationFields[name];
    return field ? String(field.value || '').trim() : '';
  },

  _setManualStatus(message, type = '') {
    if (!this.manualApplicationStatus) return;
    this.manualApplicationStatus.textContent = message || '';
    this.manualApplicationStatus.className = 'manual-application-status';
    if (type) this.manualApplicationStatus.classList.add('is-' + type);
  },

  _setManualFieldError(name, message) {
    const field = this.manualApplicationFields && this.manualApplicationFields[name];
    const error = this.manualApplicationErrors && this.manualApplicationErrors[name];
    if (field) {
      field.classList.toggle('is-invalid', Boolean(message));
      field.setAttribute('aria-invalid', message ? 'true' : 'false');
    }
    if (error) error.textContent = message || '';
  },

  _clearManualValidation() {
    Object.keys(this._manualFieldIds).forEach((name) => this._setManualFieldError(name, ''));
  },

  _setManualSaving(saving) {
    this._manualSaving = Boolean(saving);
    if (this.manualApplicationSaveLabel) {
      this.manualApplicationSaveLabel.textContent = saving ? 'Saving…' : 'Save Application';
    }
    if (this.btnSaveManualApplication) {
      this.btnSaveManualApplication.classList.toggle('is-loading', Boolean(saving));
    }
    if (this.manualApplicationForm) {
      this.manualApplicationForm.querySelectorAll('input, textarea, button').forEach((control) => {
        control.disabled = Boolean(saving);
      });
    }
    if (this.btnCloseManualApplicationModal) {
      this.btnCloseManualApplicationModal.disabled = Boolean(saving);
    }
  },

  _validateManualApplication() {
    const errors = {};
    const payload = {};

    try {
      payload.apply_url = this._normalizeApplyUrl(this._manualValue('apply_url'));
    } catch (e) {
      errors.apply_url = e.message;
    }

    const jobTitle = this._manualValue('job_title');
    if (!jobTitle) errors.job_title = 'Job title is required.';
    payload.job_title = jobTitle;

    const company = this._manualValue('company');
    if (!company) errors.company = 'Company is required.';
    payload.company = company;

    payload.source = this._manualValue('source') || 'manual';
    payload.salary = this._manualValue('salary');
    payload.contact = this._manualValue('contact');
    payload.notes = this._manualValue('notes');

    const followUpRaw = this._manualValue('follow_up_days');
    const followUpDays = followUpRaw === '' ? 7 : Number(followUpRaw);
    if (!Number.isInteger(followUpDays) || followUpDays < 0 || followUpDays > 365) {
      errors.follow_up_days = 'Follow-up days must be a whole number from 0 to 365.';
    }
    payload.follow_up_days = Number.isInteger(followUpDays) ? followUpDays : 7;

    this._clearManualValidation();
    Object.entries(errors).forEach(([name, message]) => this._setManualFieldError(name, message));

    const errorOrder = [
      'apply_url',
      'job_title',
      'company',
      'source',
      'salary',
      'contact',
      'follow_up_days',
      'notes',
    ];
    const firstError = errorOrder.find((name) => errors[name]);
    if (firstError) {
      const field = this.manualApplicationFields && this.manualApplicationFields[firstError];
      if (field && typeof field.focus === 'function') field.focus();
      this._setManualStatus('Please fix the highlighted fields before saving.', 'error');
      return { valid: false, payload: null };
    }

    if (this.manualApplicationFields.apply_url) {
      this.manualApplicationFields.apply_url.value = payload.apply_url;
    }
    if (this.manualApplicationFields.source) {
      this.manualApplicationFields.source.value = payload.source;
    }
    if (this.manualApplicationFields.follow_up_days) {
      this.manualApplicationFields.follow_up_days.value = String(payload.follow_up_days);
    }

    return { valid: true, payload };
  },

  async submitManualApplication() {
    if (this._manualSaving) return;
    if (!JobAgent.api || !JobAgent.api.createTracker) {
      this._setManualStatus('Manual tracker add needs the API to be online.', 'error');
      JobAgent.toast.show('Manual tracker add needs the API to be online.');
      return;
    }

    const { valid, payload } = this._validateManualApplication();
    if (!valid) return;

    let saved = false;
    this._setManualSaving(true);
    this._setManualStatus('Saving manual application…', 'info');
    try {
      await JobAgent.api.createTracker(payload);
      saved = true; // POST committed even if the following GET fails.
      await JobAgent.store.loadTracker({ throwOnError: true });
      this._setManualStatus('Manual application saved.', 'success');
      JobAgent.toast.show('Manual application added to the APPLIED tracker.');
    } catch (e) {
      const message = e && e.message ? e.message : String(e);
      const detail = saved
        ? 'Application saved, but tracker refresh failed: ' + message + ' Use Sync to reload; do not resubmit.'
        : 'Add failed: ' + message;
      this._setManualStatus(detail, 'error');
      JobAgent.toast.show(detail, 'error');
    } finally {
      this._setManualSaving(false);
    }

    if (saved) this.closeManualApplicationModal();
  },

  _cards() {
    // Live tracker rows only. The former MOCK_KANBAN fallback referenced a
    // global that was never defined (mockData.js was never shipped), so it
    // always evaluated to [] — an empty board is what actually rendered.
    return JobAgent.store.state.tracker || [];
  },

  render() {
    const colMap = {
      applied: this.kanbanColApplied,
      review: this.kanbanColReview,
      interview: this.kanbanColInterview,
      offer: this.kanbanColOffer,
      rejected: this.kanbanColRejected,
    };

    Object.values(colMap).forEach(col => {
      if (col) col.innerHTML = '';
    });

    const { loading, errors } = JobAgent.store.state;
    const esc = (JobAgent.escapeHtml || ((v) => String(v ?? '')));
    if (loading.tracker && this.kanbanColApplied) {
      this.kanbanColApplied.innerHTML = `<div style="color:var(--text-muted);font-size:12px;padding:12px;">Loading <code>/api/tracker</code>…</div>`;
    }
    if (errors.tracker && this.kanbanColApplied) {
      this.kanbanColApplied.innerHTML += `<div style="font-size:11.5px;color:var(--accent-amber);padding:8px 12px;">API error: ${esc(errors.tracker)}</div>`;
    }

    const cards = this._cards();
    const counts = { applied: 0, review: 0, interview: 0, offer: 0, rejected: 0 };

    cards.forEach(card => {
      const colKey = this._colFor(card.status);
      counts[colKey] += 1;
      const container = colMap[colKey];
      if (!container) return;

      const fp = this._patchKey(card);
      const statusLabel = this._statusLabel(card.status);
      const nextStatus = this._nextBackendStatus(card.status);
      const cardEl = document.createElement('div');
      cardEl.className = 'kanban-card';
      if (!nextStatus) cardEl.classList.add('kanban-card-archived');
      cardEl.dataset.fp = fp;
      const updating = this._pendingUpdates.has(String(fp));
      cardEl.setAttribute('aria-busy', String(updating));
      cardEl.classList.toggle('kanban-card-updating', updating);
      cardEl.title = updating ? 'Saving status…' : nextStatus
        ? 'Click to move to ' + this._statusLabel(nextStatus)
        : 'Archived status: this application will not move back to Applied on click.';
      cardEl.innerHTML = `
        <div class="k-company">${esc(card.company || '')}</div>
        <div class="k-title">${esc(card.title || '')}</div>
        <div class="k-meta">
          <span>${esc(card.date || '')}</span>
          <span class="k-score">${esc(card.score || 0)}%</span>
        </div>
        <div style="font-size: 11px; color: var(--accent-cyan); margin-top: 6px;">
          ${esc(statusLabel)}${card.follow_up ? ' · ' + esc(card.follow_up) : ''}
        </div>
      `;

      cardEl.addEventListener('click', () => {
        this.cycleCardStatus(card);
      });

      container.appendChild(cardEl);
    });

    for (const [key, container] of Object.entries(colMap)) {
      if (container && !container.children.length && !loading.tracker) {
        const copy = {
          applied: 'No applications yet.',
          review: 'No packages waiting for review.',
          interview: 'No interviews scheduled.',
          offer: 'No offers yet.',
          archived: 'Nothing archived.',
        };
        const empty = document.createElement('p');
        empty.className = 'kanban-empty';
        empty.textContent = copy[key] || 'Nothing here yet.';
        container.appendChild(empty);
      }
    }

    if (document.getElementById('countApplied')) document.getElementById('countApplied').textContent = counts.applied;
    if (document.getElementById('countReview')) document.getElementById('countReview').textContent = counts.review;
    if (document.getElementById('countInterview')) document.getElementById('countInterview').textContent = counts.interview;
    if (document.getElementById('countOffer')) document.getElementById('countOffer').textContent = counts.offer;
    if (document.getElementById('countRejected')) document.getElementById('countRejected').textContent = counts.rejected;
  },

  async cycleCardStatus(card) {
    const fp = String(this._patchKey(card));
    // Each card is serialized through PATCH + reload. No optimistic/local-only
    // cycle: a real tracker row must never appear saved after a refused write.
    if (this._pendingUpdates.has(fp) || JobAgent.store.state.loading.tracker) return;
    const next = this._nextBackendStatus(card.status);
    if (!next) {
      JobAgent.toast.show('Archived status: this application will not move back to Applied on click.');
      return;
    }
    if (!this._canPatchKey(fp) || typeof JobAgent.api?.patchTracker !== 'function') {
      JobAgent.toast.show('Tracker update failed: a valid saved application and online API are required.', 'error');
      return;
    }

    let saved = false;
    this._pendingUpdates.add(fp);
    this.render();
    try {
      // Notes are append-only on the server. Resending the old notes on a
      // status-only click would duplicate them on every transition.
      const updated = await JobAgent.api.patchTracker(fp, next);
      saved = true;
      await JobAgent.store.loadTracker({ throwOnError: true });
      JobAgent.toast.show(`Updated ${card.company} status to: ${String(updated.status || next).toUpperCase()}`);
    } catch (e) {
      const message = e && e.message ? e.message : String(e);
      if (saved) {
        JobAgent.toast.show('Status saved, but tracker refresh failed: ' + message + ' Use Sync to reload.', 'error');
      } else {
        console.warn('[tracker] PATCH failed:', message);
        JobAgent.toast.show('Tracker update failed: ' + message + ' Use Sync to check the saved status.', 'error');
      }
    } finally {
      this._pendingUpdates.delete(fp);
      this.render();
    }
  },
};
