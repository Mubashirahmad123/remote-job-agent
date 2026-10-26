/**
 * THEME.JS — the light/dark scheme, in one place.
 *
 * The scheme is a single attribute on <html> (`data-theme="dark|light"`),
 * because that is what css/variables.css keys its token sets off: `:root` is
 * the dark palette and `[data-theme="light"]` overrides it. The dashboard used
 * to toggle a *class on <body>* instead, which no stylesheet read — the switch
 * looked alive (the icons moved) while the page never changed, and a reload
 * forgot the choice because nothing stored it.
 *
 * This file is the only owner of that attribute. It is loaded in <head>, before
 * the stylesheets paint, so the stored scheme applies without a flash of the
 * other one, and it is external on purpose: the Content-Security-Policy allows
 * no inline script.
 *
 * The default is dark — the app's own identity (`:root` tokens, and <body
 * ships `class="theme-dark"`). It deliberately does NOT follow
 * prefers-color-scheme: someone whose OS is in light mode should not find the
 * product restyled on first visit, and a toggle that silently disagrees with
 * the operating system is a toggle nobody trusts.
 */
(function () {
  'use strict';

  var KEY = 'rja-theme';
  var DEFAULT_THEME = 'dark';
  var root = document.documentElement;

  function readStored() {
    try {
      var value = localStorage.getItem(KEY);
      return value === 'dark' || value === 'light' ? value : null;
    } catch (_) {
      return null; // private mode, or storage disabled
    }
  }

  function writeStored(theme) {
    try {
      localStorage.setItem(KEY, theme);
    } catch (_) {
      /* nothing to do: the choice simply will not survive a reload */
    }
  }

  /** The theme on screen right now. */
  function current() {
    var attr = root.getAttribute('data-theme');
    return attr === 'dark' || attr === 'light' ? attr : DEFAULT_THEME;
  }

  /**
   * Put a theme on screen and make everything that describes it agree: the
   * attribute the CSS reads, the body class, the toggle's icon, its label and
   * the status-bar colour.
   *
   * The first call happens in <head>, where <body> does not exist yet, so
   * everything below the attribute is guarded: a missing element must not stop
   * the rest of the page from being set up.
   */
  function apply(theme) {
    root.setAttribute('data-theme', theme);

    var body = document.body;
    if (body) {
      body.classList.toggle('theme-dark', theme === 'dark');
      body.classList.toggle('theme-light', theme === 'light');
    }

    // The icons show the theme the button would take you TO, so the button
    // always says what it is about to do.
    var toDark = document.getElementById('themeIconDark');
    var toLight = document.getElementById('themeIconLight');
    if (toDark) toDark.classList.toggle('hidden', theme === 'dark');
    if (toLight) toLight.classList.toggle('hidden', theme !== 'dark');

    var button = document.getElementById('btnThemeToggle');
    if (button) {
      var label = theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode';
      button.setAttribute('aria-label', label);
      button.setAttribute('title', label);
    }

    // The status bar belongs to the app, not to the OS. Read the resolved
    // canvas token instead of repeating it: a literal here would silently go
    // stale the next time the palette moves.
    var colour = getComputedStyle(document.documentElement)
      .getPropertyValue('--bg-canvas')
      .trim() || (theme === 'dark' ? '#0b0c0e' : '#f7f8fa');
    var metas = document.querySelectorAll('meta[name="theme-color"]');
    for (var i = 0; i < metas.length; i += 1) {
      metas[i].setAttribute('content', colour);
    }
  }

  function set(theme, remember) {
    if (theme !== 'dark' && theme !== 'light') return;
    apply(theme);
    if (remember !== false) writeStored(theme);
  }

  window.JobAgent = window.JobAgent || {};

  window.JobAgent.theme = {
    current: current,
    set: set,
    toggle: function () {
      set(current() === 'dark' ? 'light' : 'dark', true);
    },
  };

  // The stored choice, else the app's own default, before the first paint.
  apply(readStored() || DEFAULT_THEME);

  // The button lives in the header, which is parsed after this file. The wiring
  // waits for the document, and the theme is applied once more so the icon and
  // the label match what is on screen.
  document.addEventListener('DOMContentLoaded', function () {
    apply(current());
    var button = document.getElementById('btnThemeToggle');
    if (button && !button.dataset.wired) {
      button.dataset.wired = '1';
      button.addEventListener('click', function () {
        window.JobAgent.theme.toggle();
      });
    }
  });
})();
