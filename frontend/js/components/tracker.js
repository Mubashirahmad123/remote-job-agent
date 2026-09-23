/**
 * TRACKER.JS — Application Pipeline Kanban Board & Status Management
 * Live data: GET /api/tracker + PATCH /api/tracker/{fp}.
 * Backend statuses: applied|interviewing|offer|rejected|withdrawn|ghosted.
 * UI columns: applied / review(UI-only) / interview / offer / rejected.
 */

window.JobAgent = window.JobAgent || {};

JobAgent.tracker = {
  // backend status -> kanban column
  _colFor(status) {
    const s = (status || '').toLowerCase();
    if (s === 'applied') return 'applied';
    if (s === 'interviewing') return 'interview';
    if (s === 'offer') return 'offer';
    if (s === 'rejected' || s === 'withdrawn' || s === 'ghosted') return 'rejected';
    return 'applied';
  },

  // kanban cycle order (review is UI-only; PATCH only sends backend statuses)
  _nextBackendStatus(current) {
    const order = ['applied', 'interviewing', 'offer', 'rejected'];
    const idx = order.indexOf((current || '').toLowerCase());
    return order[(idx + 1) % order.length] || 'applied';
  },

  init() {
    this.kanbanColApplied = document.getElementById('kanbanColApplied');
    this.kanbanColReview = document.getElementById('kanbanColReview');
    this.kanbanColInterview = document.getElementById('kanbanColInterview');
    this.kanbanColOffer = document.getElementById('kanbanColOffer');
    this.kanbanColRejected = document.getElementById('kanbanColRejected');
    this.btnSyncTrackerSheets = document.getElementById('btnSyncTrackerSheets');

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
      status: c.status,
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
    if (loading.tracker && this.kanbanColApplied) {
      this.kanbanColApplied.innerHTML = `<div style="color:var(--text-muted);font-size:12px;padding:12px;">Loading <code>/api/tracker</code>…</div>`;
    }
    if (errors.tracker && this.kanbanColApplied) {
      this.kanbanColApplied.innerHTML += `<div style="font-size:11.5px;color:#f59e0b;padding:8px 12px;">API error: ${errors.tracker}</div>`;
    }

    const cards = this._cards();
    cards.forEach(card => {
      const colKey = card.status === 'review' ? 'review' : this._colFor(card.status);
      const container = colMap[colKey];
      if (!container) return;

      const fp = (card._raw && (card._raw.job_fingerprint || card._raw.apply_url)) || card.apply_url || card.id;
      const cardEl = document.createElement('div');
      cardEl.className = 'kanban-card';
      cardEl.dataset.fp = fp;
      cardEl.innerHTML = `
        <div class="k-company">${card.company || ''}</div>
        <div class="k-title">${card.title || ''}</div>
        <div class="k-meta">
          <span>${card.date || ''}</span>
          <span class="k-score">${card.score || 0}%</span>
        </div>
        <div style="font-size: 11px; color: var(--accent-cyan); margin-top: 6px;">
          📅 ${card.follow_up || ''}
        </div>
      `;

      cardEl.addEventListener('click', () => {
        this.cycleCardStatus(card);
      });

      container.appendChild(cardEl);
    });

    // Update Kanban Counters
    const counts = {
      applied: cards.filter(c => this._colFor(c.status) === 'applied').length,
      review: cards.filter(c => c.status === 'review').length,
      interview: cards.filter(c => this._colFor(c.status) === 'interview').length,
      offer: cards.filter(c => this._colFor(c.status) === 'offer').length,
      rejected: cards.filter(c => this._colFor(c.status) === 'rejected').length
    };

    if (document.getElementById('countApplied')) document.getElementById('countApplied').textContent = counts.applied;
    if (document.getElementById('countReview')) document.getElementById('countReview').textContent = counts.review;
    if (document.getElementById('countInterview')) document.getElementById('countInterview').textContent = counts.interview;
    if (document.getElementById('countOffer')) document.getElementById('countOffer').textContent = counts.offer;
    if (document.getElementById('countRejected')) document.getElementById('countRejected').textContent = counts.rejected;
  },

  async cycleCardStatus(card) {
    const next = card.status === 'review' ? 'interviewing' : this._nextBackendStatus(card.status);
    // Live PATCH when we have a resolvable key (fingerprint or apply_url).
    const fp = (card._raw && (card._raw.job_fingerprint || card._raw.apply_url)) || card.apply_url || card.id;
    const canPatch = fp && !String(fp).startsWith('tracker-') && Number.isNaN(Number(String(fp).slice(0, 4)));
    if (JobAgent.store.state.usingLive && fp && JobAgent.api) {
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
    card.status = next === 'interviewing' && card.status === 'applied' ? 'interviewing' : next;
    // Map backend statuses back onto kanban columns for mock mode.
    if (card.status === 'interviewing') card.status = 'interview';
    this.render();
    JobAgent.toast.show(`Updated ${card.company} status to: ${String(card.status).toUpperCase()}`);
  }
};
