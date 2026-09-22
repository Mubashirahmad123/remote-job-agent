/**
 * TRACKER.JS — Application Pipeline Kanban Board & Status Management
 */

window.JobAgent = window.JobAgent || {};

JobAgent.tracker = {
  init() {
    this.kanbanColApplied = document.getElementById('kanbanColApplied');
    this.kanbanColReview = document.getElementById('kanbanColReview');
    this.kanbanColInterview = document.getElementById('kanbanColInterview');
    this.kanbanColOffer = document.getElementById('kanbanColOffer');
    this.kanbanColRejected = document.getElementById('kanbanColRejected');
    this.btnSyncTrackerSheets = document.getElementById('btnSyncTrackerSheets');

    this.bindEvents();
    this.render();
  },

  bindEvents() {
    if (this.btnSyncTrackerSheets) {
      this.btnSyncTrackerSheets.addEventListener('click', () => {
        JobAgent.toast.show('Synchronized 13 applications with Google Sheets APPLIED tab.');
      });
    }
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

    (JobAgent.MOCK_KANBAN || []).forEach(card => {
      const container = colMap[card.status];
      if (!container) return;

      const cardEl = document.createElement('div');
      cardEl.className = 'kanban-card';
      cardEl.innerHTML = `
        <div class="k-company">${card.company}</div>
        <div class="k-title">${card.title}</div>
        <div class="k-meta">
          <span>${card.date}</span>
          <span class="k-score">${card.score}%</span>
        </div>
        <div style="font-size: 11px; color: var(--accent-cyan); margin-top: 6px;">
          📅 ${card.follow_up}
        </div>
      `;

      cardEl.addEventListener('click', () => {
        this.cycleCardStatus(card);
      });

      container.appendChild(cardEl);
    });

    // Update Kanban Counters
    const counts = {
      applied: JobAgent.MOCK_KANBAN.filter(c => c.status === 'applied').length,
      review: JobAgent.MOCK_KANBAN.filter(c => c.status === 'review').length,
      interview: JobAgent.MOCK_KANBAN.filter(c => c.status === 'interview').length,
      offer: JobAgent.MOCK_KANBAN.filter(c => c.status === 'offer').length,
      rejected: JobAgent.MOCK_KANBAN.filter(c => c.status === 'rejected').length
    };

    if (document.getElementById('countApplied')) document.getElementById('countApplied').textContent = counts.applied;
    if (document.getElementById('countReview')) document.getElementById('countReview').textContent = counts.review;
    if (document.getElementById('countInterview')) document.getElementById('countInterview').textContent = counts.interview;
    if (document.getElementById('countOffer')) document.getElementById('countOffer').textContent = counts.offer;
    if (document.getElementById('countRejected')) document.getElementById('countRejected').textContent = counts.rejected;
  },

  cycleCardStatus(card) {
    const order = ['applied', 'review', 'interview', 'offer', 'rejected'];
    const currIdx = order.indexOf(card.status);
    const nextIdx = (currIdx + 1) % order.length;
    card.status = order[nextIdx];
    this.render();
    JobAgent.toast.show(`Updated ${card.company} status to: ${card.status.toUpperCase()}`);
  }
};
