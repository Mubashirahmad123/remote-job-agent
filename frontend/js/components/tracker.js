/**
 * TRACKER.JS — Application Pipeline Kanban Board & Status Management
 * Live data: GET /api/tracker + PATCH /api/tracker/{fp}.
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

  _status(status) {
    return String(status || 'applied').trim().toLowerCase() || 'applied';
  },

  // backend/sheet status -> kanban column. Fill-only auto-apply outcomes are
  // not backend PATCH statuses, but they are real pipeline states and should
  // show in Under Review instead of being hidden under Applied.
  _colFor(status) {
    const s = this._status(status);
    if (this._reviewStatuses.has(s) || s.startsWith('filled_')) return 'review';
    if (s === 'applied' || s === 'submitted') return 'applied';
    if (s === 'interviewing' || s === 'interview') return 'interview';
    if (s === 'offer') return 'offer';
    if (s === 'rejected' || s === 'withdrawn' || s === 'ghosted') return 'rejected';
    return 'applied';
  },

  // Click cycle sends only backend-valid statuses. Review/fill-only cards move
  // to interviewing once the operator confirms progress.
  _nextBackendStatus(current) {
    const col = this._colFor(current);
    if (col === 'applied' || col === 'review') return 'interviewing';
    if (col === 'interview') return 'offer';
    if (col === 'offer') return 'rejected';
    return 'applied';
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

  init() {
    this.kanbanColApplied = document.getElementById('kanbanColApplied');
    this.kanbanColReview = document.getElementById('kanbanColReview');
    this.kanbanColInterview = document.getElementById('kanbanColInterview');
    this.kanbanColOffer = document.getElementById('kanbanColOffer');
    this.kanbanColRejected = document.getElementById('kanbanColRejected');
    this.btnSyncTrackerSheets = document.getElementById('btnSyncTrackerSheets');
    this.btnNewTrackedJob = document.getElementById('btnNewTrackedJob');

    this.bindEvents();
    this.render();
    JobAgent.store.subscribe(() => this.render());
  },

  bindEvents() {
    if (this.btnSyncTrackerSheets) {
      this.btnSyncTrackerSheets.addEventListener('click', async () => {
        JobAgent.toast.show('Refreshing tracker from /api/tracker…');
        try {
          await JobAgent.api.refreshJobs('APPLIED');
          await JobAgent.store.loadTracker();
          JobAgent.toast.show('Tracker synced with APPLIED sheet tab.');
        } catch (e) {
          JobAgent.toast.show('Sync failed: ' + e.message);
        }
      });
    }

    if (this.btnNewTrackedJob) {
      this.btnNewTrackedJob.addEventListener('click', () => this.addManualApplication());
    }
  },

  async addManualApplication() {
    if (!JobAgent.api || !JobAgent.api.createTracker) {
      JobAgent.toast.show('Manual tracker add needs the API to be online.');
      return;
    }
    const applyUrl = window.prompt('Application URL to track?');
    if (!applyUrl || !applyUrl.trim()) return;
    const jobTitle = window.prompt('Job title?', 'Untitled role') || 'Untitled role';
    const company = window.prompt('Company?', 'Unknown') || 'Unknown';
    const notes = window.prompt('Notes? (optional)', '') || '';
    try {
      await JobAgent.api.createTracker({
        apply_url: applyUrl.trim(),
        job_title: jobTitle.trim(),
        company: company.trim(),
        notes: notes.trim(),
      });
      await JobAgent.store.loadTracker();
      JobAgent.toast.show('Manual application added to the APPLIED tracker.');
    } catch (e) {
      JobAgent.toast.show('Add failed: ' + e.message);
    }
  },

  _cards() {
    const live = JobAgent.store.state.tracker || [];
    if (live.length) return live;
    // Legacy mock shape -> normalized shape (store.loadTracker already maps,
    // but keep direct fallback for first paint before loadAll finishes).
    return (JobAgent.MOCK_KANBAN || []).map((c) => ({
      id: c.apply_url || String(c.id),
      title: c.title,
      company: c.company,
      score: c.score,
      date: c.date,
      follow_up: c.follow_up,
      status: c.status || 'applied',
      apply_url: c.apply_url || '',
    }));
  },

  render() {
    const colMap = {
      applied: this.kanbanColApplied,
      review: this.kanbanColReview,
      interview: this.kanbanColInterview,
      offer: this.kanbanColOffer,
      rejected: this.kanbanColRejected
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
      this.kanbanColApplied.innerHTML += `<div style="font-size:11.5px;color:#f59e0b;padding:8px 12px;">API error: ${esc(errors.tracker)}</div>`;
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
      const cardEl = document.createElement('div');
      cardEl.className = 'kanban-card';
      cardEl.dataset.fp = fp;
      cardEl.title = 'Click to move to ' + this._statusLabel(this._nextBackendStatus(card.status));
      cardEl.innerHTML = `
        <div class="k-company">${esc(card.company || '')}</div>
        <div class="k-title">${esc(card.title || '')}</div>
        <div class="k-meta">
          <span>${esc(card.date || '')}</span>
          <span class="k-score">${esc(card.score || 0)}%</span>
        </div>
        <div style="font-size: 11px; color: var(--accent-cyan); margin-top: 6px;">
          ${esc(statusLabel)}${card.follow_up ? ' · 📅 ' + esc(card.follow_up) : ''}
        </div>
      `;

      cardEl.addEventListener('click', () => {
        this.cycleCardStatus(card);
      });

      container.appendChild(cardEl);
    });

    for (const [key, container] of Object.entries(colMap)) {
      if (container && !container.children.length && !loading.tracker) {
        const empty = document.createElement('div');
        empty.style.cssText = 'color:var(--text-muted);font-size:12px;padding:12px;border:1px dashed var(--border-subtle);border-radius:10px;';
        empty.textContent = key === 'review' ? 'No fill-review packages waiting.' : 'No applications here.';
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
    const next = this._nextBackendStatus(card.status);
    const fp = this._patchKey(card);
    if (JobAgent.store.state.usingLive && this._canPatchKey(fp) && JobAgent.api) {
      try {
        const updated = await JobAgent.api.patchTracker(fp, next, card.notes || '');
        await JobAgent.store.loadTracker();
        JobAgent.toast.show(`Updated ${card.company} status to: ${String(updated.status || next).toUpperCase()}`);
        return;
      } catch (e) {
        // Fall through to local update so the UI never dead-ends offline.
        console.warn('[tracker] PATCH failed, local cycle:', e.message);
        JobAgent.toast.show('API update failed (' + e.message + ') — cycled locally.');
      }
    }
    card.status = next;
    this.render();
    JobAgent.toast.show(`Updated ${card.company} status to: ${this._statusLabel(card.status).toUpperCase()}`);
  }
};
