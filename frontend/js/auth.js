/**
 * AUTH.JS — session identity chip + sign-out wiring (dashboard page only).
 *
 * The browser authenticates purely through the HttpOnly `rja_session` cookie
 * set by POST /api/auth/login (see api/routers/auth.py). No credentials are
 * stored in JavaScript or localStorage. When the session is missing/expired,
 * api.js already redirects to /login.html on a 401.
 */
(function () {
  'use strict';
  if (!window.JobAgent) return;

  JobAgent.auth = {
    init: function () {
      var chip = document.getElementById('sessionChip');
      var nameEl = document.getElementById('sessionUsername');
      var initialEl = document.getElementById('sessionInitial');

      // Reveal the chip only for a real session (open local dev has no user).
      JobAgent.api.getMe().then(function (me) {
        if (!me || !me.authenticated || !me.username) return;
        if (nameEl) nameEl.textContent = me.username;
        if (initialEl) initialEl.textContent = me.username.slice(0, 2).toUpperCase();
        if (chip) chip.classList.remove('hidden');
      }).catch(function () {
        /* 401 already redirected to /login.html — nothing to render */
      });

      var btn = document.getElementById('btnSignOut');
      if (!btn) return;
      btn.addEventListener('click', async function () {
        btn.disabled = true;
        try {
          await JobAgent.api.logout(); // invalidates the session server-side
        } catch (_) { /* unreachable server — still leave the page */ }
        window.location.replace('/login.html');
      });
    },
  };
})();
