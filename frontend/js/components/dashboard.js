/**
 * DASHBOARD.JS — Command Deck Bento Grid & Telemetry Widgets
 */

window.JobAgent = window.JobAgent || {};

JobAgent.dashboard = {
  init() {
    this.sourcesGrid = document.getElementById('sourcesGrid');
    this.topSkillsCloud = document.getElementById('topSkillsCloud');
    this.render();
  },

  render() {
    // 1. Scraper Sources Grid
    if (this.sourcesGrid && JobAgent.MOCK_SOURCES) {
      this.sourcesGrid.innerHTML = JobAgent.MOCK_SOURCES.map(src => `
        <div class="source-item-card">
          <div class="source-meta">
            <span class="source-meta-name">${src.name}</span>
            <span class="source-meta-status">${src.badge} • ${src.status}</span>
          </div>
          <span class="source-count-pill">${src.jobs} jobs</span>
        </div>
      `).join('');
    }

    // 2. High-Yield Skills Demanded Cloud
    if (this.topSkillsCloud && JobAgent.MOCK_SKILLS) {
      this.topSkillsCloud.innerHTML = JobAgent.MOCK_SKILLS.map(sk => `
        <div class="skill-pill">
          <span>${sk.name}</span>
          <span class="skill-pct">${sk.count}%</span>
        </div>
      `).join('');
    }
  }
};
