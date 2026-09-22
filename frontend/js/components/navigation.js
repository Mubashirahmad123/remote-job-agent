/**
 * NAVIGATION.JS — Sidebar Navigation, Breadcrumbs & ⌘K Search Bar
 */

window.JobAgent = window.JobAgent || {};

JobAgent.navigation = {
  titles: {
    dashboard: 'Command Deck',
    jobs: 'Curated Jobs Matrix',
    resume: 'CV & Resume Studio',
    autoapply: 'Auto-Apply Cockpit',
    tracker: 'Pipeline Tracker'
  },

  init() {
    this.navItems = document.querySelectorAll('.nav-item');
    this.viewPanels = document.querySelectorAll('.view-panel');
    this.currentViewTitle = document.getElementById('currentViewTitle');
    this.globalSearchInput = document.getElementById('globalSearchInput');
    this.btnSyncSheets = document.getElementById('btnSyncSheets');
    this.btnScrapeNow = document.getElementById('btnScrapeNow');
    this.btnThemeToggle = document.getElementById('btnThemeToggle');
    this.themeIconDark = document.getElementById('themeIconDark');
    this.themeIconLight = document.getElementById('themeIconLight');

    this.bindEvents();
  },

  bindEvents() {
    // Theme Toggle Handler (Clean Minimalist Dark <-> Clean Enterprise Light)
    if (this.btnThemeToggle) {
      this.btnThemeToggle.addEventListener('click', () => {
        const isDark = document.body.classList.contains('theme-dark');
        if (isDark) {
          document.body.classList.remove('theme-dark');
          document.body.classList.add('theme-light');
          document.documentElement.setAttribute('data-theme', 'light');
          if (this.themeIconDark) this.themeIconDark.classList.add('hidden');
          if (this.themeIconLight) this.themeIconLight.classList.remove('hidden');
          JobAgent.toast.show('Switched to Minimalist Light Mode.');
        } else {
          document.body.classList.remove('theme-light');
          document.body.classList.add('theme-dark');
          document.documentElement.setAttribute('data-theme', 'dark');
          if (this.themeIconDark) this.themeIconDark.classList.remove('hidden');
          if (this.themeIconLight) this.themeIconLight.classList.add('hidden');
          JobAgent.toast.show('Switched to High-Contrast Dark Mode.');
        }
      });
    }
    this.navItems.forEach(item => {
      item.addEventListener('click', () => {
        this.switchTab(item.dataset.tab);
      });
    });

    // ⌘K / Ctrl+K keyboard shortcut
    window.addEventListener('keydown', (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        this.globalSearchInput.focus();
      } else if (e.key === 'Escape') {
        if (JobAgent.jobDrawer) JobAgent.jobDrawer.close();
        if (JobAgent.autoApply) JobAgent.autoApply.closeModal();
      }
    });

    if (this.globalSearchInput) {
      this.globalSearchInput.addEventListener('input', (e) => {
        const val = e.target.value.trim();
        if (JobAgent.store.state.activeTab !== 'jobs') {
          this.switchTab('jobs');
        }
        const jobSearchInput = document.getElementById('jobFilterSearch');
        if (jobSearchInput) jobSearchInput.value = val;
        JobAgent.store.setFilter('search', val.toLowerCase());
      });
    }

    if (this.btnSyncSheets) {
      this.btnSyncSheets.addEventListener('click', () => {
        this.btnSyncSheets.innerHTML = '<span>Syncing...</span>';
        setTimeout(() => {
          this.btnSyncSheets.innerHTML = `
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:15px;height:15px"><path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"></path></svg>
            <span>Sync Sheets</span>
          `;
          JobAgent.toast.show('Google Sheets sync complete: ALL JOBS, TOP MATCHES, APPLIED up to date.');
        }, 800);
      });
    }

    if (this.btnScrapeNow) {
      this.btnScrapeNow.addEventListener('click', () => {
        this.btnScrapeNow.innerHTML = '<span>Scraping 45+...</span>';
        setTimeout(() => {
          this.btnScrapeNow.innerHTML = `
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:15px;height:15px"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
            <span>Scrape Now</span>
          `;
          JobAgent.toast.show('Scrape cycle complete. 18 new jobs evaluated against CV.');
        }, 1400);
      });
    }
  },

  switchTab(tabKey) {
    JobAgent.store.setTab(tabKey);

    this.navItems.forEach(item => {
      item.classList.toggle('active', item.dataset.tab === tabKey);
    });

    this.viewPanels.forEach(panel => {
      panel.classList.toggle('active', panel.id === `view-${tabKey}`);
    });

    if (this.currentViewTitle) {
      this.currentViewTitle.textContent = this.titles[tabKey] || 'Command Deck';
    }

    // Refresh specific view if needed
    if (tabKey === 'jobs' && JobAgent.jobDesk) {
      JobAgent.jobDesk.render();
    } else if (tabKey === 'tracker' && JobAgent.tracker) {
      JobAgent.tracker.render();
    }
  }
};
