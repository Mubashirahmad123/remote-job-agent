/**
 * NAVIGATION.JS — Sidebar Navigation, Breadcrumbs & ⌘K Search Bar
 */

window.JobAgent = window.JobAgent || {};

JobAgent.navigation = {
  titles: {
    dashboard: 'Command Deck',
    scrape: 'Scrape Monitor',
    jobs: 'Curated Jobs Matrix',
    resume: 'CV & Resume Studio',
    autoapply: 'Auto-Apply Cockpit',
    tracker: 'Pipeline Tracker'
  },

  init() {
    this.navItems = document.querySelectorAll('.nav-item');
    this.viewPanels = document.querySelectorAll('.view-panel');
    this.currentViewTitle = document.getElementById('currentViewTitle');
    this.btnSyncSheets = document.getElementById('btnSyncSheets');
    this.btnScrapeNow = document.getElementById('btnScrapeNow');
    this.scrapeStatusCard = document.getElementById('scrapeStatusCard');
    // The sidebar's own brand row is the control: click the panel to fold it
    // to the rail, click the rail to open it. There is no separate button.
    this.sidebarBrand = document.getElementById('sidebarBrand');

    // Off-canvas nav drawer (phones). The sidebar is a 256px rail beside a
    // desktop window and a third of a phone screen, so below the 768px tier
    // it slides in from the left instead — and it is the only way to reach a
    // view other than the one the app opened on.
    this.btnMobileNav = document.getElementById('btnMobileNav');
    this.sidebar = document.getElementById('appSidebar');
    this.sidebarScrim = document.getElementById('sidebarScrim');
    this.navOpen = false;
    this.navClosing = false;
    this.navCloseTimer = null;

    this.bindEvents();
  },

  bindEvents() {
    // The theme toggle is owned by js/theme.js (loaded in <head> so the stored
    // scheme applies before first paint). Wiring it here as well attached a
    // second click listener, and because both read `data-theme` at click time
    // the second one flipped the theme straight back — one click, no change.
    this.navItems.forEach(item => {
      item.addEventListener('click', () => {
        this.switchTab(item.dataset.tab);
      });
    });

    if (this.btnMobileNav) {
      this.btnMobileNav.addEventListener('click', () => {
        this.toggleMobileNav(!this.navOpen);
      });
    }

    if (this.sidebarScrim) {
      this.sidebarScrim.addEventListener('click', () => this.closeMobileNav());
    }

    // The sidebar mode (expanded labelled column / icon rail) is a persisted
    // UI preference. js/theme.js applies the stored value before first paint;
    // this owns the click, the ARIA state and the value that gets stored.
    this.syncSidebarAffordance();
    if (this.sidebarBrand) {
      this.sidebarBrand.addEventListener('click', (ev) => {
        ev.stopPropagation();
        this.toggleSidebarFromSurface();
      });
      this.sidebarBrand.addEventListener('keydown', (ev) => {
        if (ev.key !== 'Enter' && ev.key !== ' ') return;
        ev.preventDefault();
        this.toggleSidebarFromSurface();
      });
    }

    // Clicking the panel's own surface is the same gesture. Destinations
    // (nav items, the live-run card) and real controls keep their click.
    if (this.sidebar) {
      this.sidebar.addEventListener('click', (ev) => {
        if (ev.target.closest('.nav-item, .scrape-status-box, .sidebar-brand, button, a, input, select, textarea')) {
          return;
        }
        this.toggleSidebarFromSurface();
      });
    }

    // The drawer can be pushed away with a swipe, and it inherits the
    // velocity of the release: a flick closes it even if it barely moved.
    if (this.sidebar && JobAgent.gestures) {
      JobAgent.gestures.swipeToDismiss(this.sidebar, {
        axis: 'x',
        direction: -1, // pushing it back to the left dismisses
        dismissThreshold: 0.3,
        canStart: () => (this.navOpen || this.navClosing)
          && window.matchMedia('(max-width: 768px)').matches,
        // Caught on its way out: cancel the dismissal and let the finger take
        // over from wherever the drawer happens to be. The thought and the
        // gesture happen in parallel.
        onGrab: () => {
          if (!this.navClosing || this.navOpen) return;
          this.navOpen = true;
          this.navClosing = false;
          this.sidebar.classList.add('is-open');
          if (this.sidebarScrim) this.sidebarScrim.classList.add('is-open');
          document.body.classList.add('nav-open');
        },
        onProgress: (ratio) => {
          if (this.sidebarScrim) this.sidebarScrim.style.opacity = String(Math.max(0, 1 - ratio));
        },
        onDismiss: () => this.closeMobileNav(),
      });
    }

    // A drawer left open across a rotation into desktop width would leave the
    // page locked (body.nav-open) with no visible way to unlock it.
    if (typeof window.matchMedia === 'function') {
      const wide = window.matchMedia('(min-width: 769px)');
      const onChange = (e) => {
        if (e && e.matches) this.closeMobileNav();
        // Crossing either way changes what the brand row is: a collapse
        // control above 768px, a plain product mark in the drawer below it.
        this.syncSidebarAffordance();
      };
      if (typeof wide.addEventListener === 'function') {
        wide.addEventListener('change', onChange);
      } else if (typeof wide.addListener === 'function') {
        wide.addListener(onChange); // Safari < 14
      }
    }

    // Escape closes drawer/modals
    window.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        if (this.navOpen) {
          this.closeMobileNav();
          return;
        }
        if (JobAgent.jobDrawer) JobAgent.jobDrawer.close();
        if (JobAgent.autoApply) JobAgent.autoApply.closeModal();
      }
    });

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

    if (this.scrapeStatusCard) {
      this.scrapeStatusCard.addEventListener('click', () => this.switchTab('scrape'));
    }
  },

  /**
   * Open or close the off-canvas nav drawer.
   *
   * Focus moves into the drawer when it opens and back to the trigger when it
   * closes, so the control that opened it is never a keyboard trap.
   */
  toggleMobileNav(open) {
    if (!this.sidebar) return;
    this.navOpen = Boolean(open);

    this.sidebar.classList.toggle('is-open', this.navOpen);
    if (this.sidebarScrim) {
      this.sidebarScrim.classList.toggle('is-open', this.navOpen);
      // The drag gesture may have left an inline opacity behind.
      this.sidebarScrim.style.opacity = '';
    }
    document.body.classList.toggle('nav-open', this.navOpen);
    // A drag in flight must not survive a programmatic open/close.
    this.sidebar.style.transform = '';
    if (this.btnMobileNav) {
      this.btnMobileNav.setAttribute('aria-expanded', this.navOpen ? 'true' : 'false');
      this.btnMobileNav.setAttribute(
        'aria-label',
        this.navOpen ? 'Close navigation menu' : 'Open navigation menu'
      );
    }

    if (!this.navOpen) {
      // The drawer is on its way out; it stays grabbable until it lands.
      this.navClosing = true;
      clearTimeout(this.navCloseTimer);
      this.navCloseTimer = setTimeout(() => { this.navClosing = false; }, 400);
    } else {
      this.navClosing = false;
      clearTimeout(this.navCloseTimer);
    }

    if (this.navOpen) {
      const first = this.sidebar.querySelector('.nav-item');
      if (first && typeof first.focus === 'function') first.focus();
    } else if (this.btnMobileNav && typeof this.btnMobileNav.focus === 'function') {
      this.btnMobileNav.focus();
    }
  },

  closeMobileNav() {
    if (!this.navOpen) return;
    this.toggleMobileNav(false);
  },

  currentSidebarMode() {
    return document.documentElement.getAttribute('data-sidebar') === 'collapsed'
      ? 'collapsed'
      : 'expanded';
  },

  /**
   * The brand row is a control only on the desktop/tablet column. Below 768px
   * the panel is the drawer, so the row goes back to being a plain mark: no
   * role, no tab stop, no tooltip, and no ARIA naming a mode it cannot set.
   */
  syncSidebarAffordance() {
    if (!this.sidebarBrand) return;
    const mobile = typeof window.matchMedia === 'function'
      && window.matchMedia('(max-width: 768px)').matches;
    if (mobile) {
      this.sidebarBrand.removeAttribute('role');
      this.sidebarBrand.removeAttribute('tabindex');
      this.sidebarBrand.removeAttribute('aria-controls');
      this.sidebarBrand.removeAttribute('aria-expanded');
      this.sidebarBrand.removeAttribute('aria-label');
      this.sidebarBrand.removeAttribute('title');
      return;
    }
    this.sidebarBrand.setAttribute('role', 'button');
    this.sidebarBrand.setAttribute('tabindex', '0');
    this.sidebarBrand.setAttribute('aria-controls', 'appSidebar');
    this.syncSidebarToggle();
  },

  /** Make the brand row describe the mode that is actually on screen. */
  syncSidebarToggle() {
    if (!this.sidebarBrand) return;
    const collapsed = this.currentSidebarMode() === 'collapsed';
    const label = collapsed ? 'Expand sidebar' : 'Collapse sidebar';
    this.sidebarBrand.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    this.sidebarBrand.setAttribute('aria-label', label);
    this.sidebarBrand.setAttribute('title', label);
  },

  /** A click on the panel is only a mode change on the desktop/tablet column;
   *  below 768px the panel is the drawer, and the drawer stays labelled. */
  toggleSidebarFromSurface() {
    if (typeof window.matchMedia === 'function'
        && window.matchMedia('(max-width: 768px)').matches) {
      return;
    }
    this.toggleSidebar();
  },

  /**
   * Switch the sidebar between the labelled column and the icon rail.
   * The phone drawer ignores this: a drawer is always labelled.
   */
  setSidebarMode(mode, remember) {
    const next = mode === 'collapsed' ? 'collapsed' : 'expanded';
    document.documentElement.setAttribute('data-sidebar', next);
    if (remember !== false) {
      try {
        localStorage.setItem('rja-sidebar', next);
      } catch (_) {
        /* storage disabled: the choice lasts for this page only */
      }
    }
    this.syncSidebarToggle();
  },

  toggleSidebar() {
    this.setSidebarMode(
      this.currentSidebarMode() === 'collapsed' ? 'expanded' : 'collapsed',
      true
    );
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

    // Changing views from the drawer closes it — the drawer is the phone's
    // menu, and the menu is done once something has been picked.
    this.closeMobileNav();

    // A new view starts at the top. On a phone the last view could have been
    // scrolled a long way down, and arriving halfway into the next one reads as
    // a rendering bug. `scrollingElement` rather than window.scrollTo(): the
    // e2e suite runs jsdom, which implements no scrolling and reports
    // window.scrollTo() as an error.
    const scroller = document.scrollingElement;
    if (scroller) scroller.scrollTop = 0;

    // Refresh specific view if needed
    if (tabKey === 'jobs' && JobAgent.jobDesk) {
      // Entering the view is the one moment the cards animate in; filter
      // changes later re-render without replaying the entrance.
      JobAgent.jobDesk.playEntrance();
    } else if (tabKey === 'tracker' && JobAgent.tracker) {
      JobAgent.tracker.render();
    }
  }
};
