/**
 * STORE.JS — Central Application Reactive State Manager
 */

window.JobAgent = window.JobAgent || {};

JobAgent.store = {
  state: {
    activeTab: 'dashboard',
    viewMode: 'grid', // 'grid' | 'table'
    selectedJob: null,
    filters: {
      search: '',
      role: 'all',
      minScore: 70,
      location: 'all',
      source: 'all',
      status: 'all'
    },
    autoApply: {
      mode: 'review', // 'review' | 'submit'
      threshold: 75,
      dailyCap: 5,
      appliedToday: 3
    }
  },

  listeners: [],

  subscribe(listener) {
    this.listeners.push(listener);
  },

  notify() {
    this.listeners.forEach(fn => fn(this.state));
  },

  setTab(tab) {
    this.state.activeTab = tab;
    this.notify();
  },

  setViewMode(mode) {
    this.state.viewMode = mode;
    this.notify();
  },

  setSelectedJob(job) {
    this.state.selectedJob = job;
    this.notify();
  },

  setFilter(key, value) {
    this.state.filters[key] = value;
    this.notify();
  },

  setAutoApply(key, value) {
    this.state.autoApply[key] = value;
    this.notify();
  }
};
