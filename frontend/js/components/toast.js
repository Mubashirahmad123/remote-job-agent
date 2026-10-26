/**
 * TOAST.JS — Toast Notification UI Component
 *
 * The toast is a transition, not a keyframe: toasts arrive in bursts (a
 * scrape start, a sync, a save) and a keyframe restarts from zero whenever
 * one interrupts another, which reads as a stutter. The entry state comes
 * from `@starting-style` in components.css, so the element animates from the
 * moment it enters the DOM without a class flip or a frame of jank.
 */

window.JobAgent = window.JobAgent || {};

JobAgent.toast = {
  // How long a toast stays before it leaves. Long enough to read a server
  // message, short enough that it never becomes furniture.
  TTL: 3200,

  show(message, type = 'success') {
    const existing = document.querySelector('.app-toast');
    if (existing) existing.remove();

    // Placement lives in components.css (.app-toast), not inline: the same
    // anchor that reads correctly on a desktop puts half the toast off-screen
    // on a phone, where it has to sit above the home-indicator inset instead.
    const toast = document.createElement('div');
    toast.className = 'app-toast';

    // Glyph constants, not user data: set once via innerHTML so the toast can
    // carry an SVG mark instead of a text character.
    const iconSvg = type === 'success'
      ? '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="20 6 9 17 4 12"></polyline></svg>'
      : '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="9"></circle><line x1="12" y1="8" x2="12" y2="12.5"></line><line x1="12" y1="16.5" x2="12.01" y2="16.5"></line></svg>';
    // Message is rendered via textContent (never innerHTML): toast callers
    // pass through server error details and job titles, which are untrusted.
    const iconSpan = document.createElement('span');
    iconSpan.className = `toast-icon ${type === 'success' ? 'is-success' : 'is-warn'}`;
    iconSpan.innerHTML = iconSvg;
    const messageSpan = document.createElement('span');
    messageSpan.textContent = String(message ?? '');
    toast.append(iconSpan, messageSpan);
    document.body.appendChild(toast);

    let timer = null;
    let remaining = JobAgent.toast.TTL;
    let startedAt = 0;

    const dismiss = () => {
      if (toast.dataset.leaving) return;
      toast.dataset.leaving = '1';
      toast.classList.add('is-leaving');
      clearTimeout(timer);
      timer = null;
      document.removeEventListener('visibilitychange', onVisibility);
      // Removed after the exit transition. The timeout is the fallback for the
      // case where the transition never fires (a backgrounded tab, a browser
      // that drops animations), so the toast can never get stuck on screen.
      setTimeout(() => toast.remove(), 260);
    };

    const start = () => {
      startedAt = Date.now();
      timer = setTimeout(dismiss, remaining);
    };

    // A toast must not expire while the tab is in the background: the user
    // has not had a chance to read it, and coming back to an empty screen is
    // worse than no toast at all.
    const pause = () => {
      if (!timer) return;
      clearTimeout(timer);
      timer = null;
      remaining = Math.max(0, remaining - (Date.now() - startedAt));
    };

    const onVisibility = () => {
      if (document.hidden) {
        pause();
      } else if (!timer) {
        start();
      }
    };

    document.addEventListener('visibilitychange', onVisibility);
    if (document.hidden) {
      remaining = JobAgent.toast.TTL; // it has not been on screen yet
    } else {
      start();
    }
  }
};
