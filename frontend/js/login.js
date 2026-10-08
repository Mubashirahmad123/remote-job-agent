/*
 * frontend/js/login.js — sign-in form behaviour.
 *
 * This was an inline <script> block in login.html. It is a file now for one
 * reason: it was the ONLY inline script left in the frontend, and while it
 * existed the Content-Security-Policy had to carry `script-src 'unsafe-inline'`,
 * which means an injected inline payload would still execute. With this
 * extracted, script-src is 'self' and no inline script can run anywhere in the
 * app — that is the difference between a CSP that limits what a successful XSS
 * can do and one that prevents the injection from starting.
 *
 * Behaviour is unchanged: the block sat at the end of <body>, so a plain
 * <script src> in the same position parses and runs at the same point. It is
 * still an IIFE, still 'use strict', and still touches nothing global.
 *
 * tests/e2e loads login.html in jsdom with resources:'usable', so this file is
 * really fetched and really executed by the e2e login-flow tests — the
 * extraction is covered, not just assumed.
 */
(function () {
  'use strict';
  var form = document.getElementById('loginForm');
  var user = document.getElementById('loginUsername');
  var pass = document.getElementById('loginPassword');
  var errorEl = document.getElementById('loginError');
  var btn = form.querySelector('button[type="submit"]');
  var cooldownTimer = null;

  function enable() { btn.disabled = false; }

  function humanWait(seconds) {
    if (seconds < 60) return seconds + 's';
    var m = Math.ceil(seconds / 60);
    return m + (m === 1 ? ' minute' : ' minutes');
  }

  // 429 = the server's brute-force limiter (api/ratelimit.py) tripped.
  // Retry-After is authoritative, so count down against it rather than
  // guessing: submitting again early just burns another rejected request.
  function startCooldown(retryAfter) {
    var left = parseInt(retryAfter, 10);
    if (!isFinite(left) || left <= 0) left = 60;
    btn.disabled = true;
    pass.value = '';
    if (cooldownTimer) clearInterval(cooldownTimer);
    var paint = function () {
      errorEl.textContent = 'Too many sign-in attempts. Try again in ' + humanWait(left) + '.';
    };
    paint();
    cooldownTimer = setInterval(function () {
      left -= 1;
      if (left <= 0) {
        clearInterval(cooldownTimer);
        cooldownTimer = null;
        errorEl.textContent = '';
        enable();
        user.focus();
        return;
      }
      paint();
    }, 1000);
  }

  form.addEventListener('submit', async function (e) {
    e.preventDefault();
    if (cooldownTimer) return;           // still counting down
    errorEl.textContent = '';
    btn.disabled = true;
    try {
      var res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ username: user.value.trim(), password: pass.value }),
      });
      if (res.status === 429) {
        startCooldown(res.headers.get('Retry-After'));
        return;                          // button stays disabled until then
      }
      if (res.status === 401) {
        errorEl.textContent = 'Invalid username or password.';
        pass.value = '';
        pass.focus();
        enable();
        return;
      }
      if (!res.ok) {
        var detail = 'Sign in failed (HTTP ' + res.status + ').';
        try {
          var body = await res.json();
          if (body && body.detail) detail = String(body.detail);
        } catch (_) { /* keep generic message */ }
        errorEl.textContent = detail;
        enable();
        return;
      }
      window.location.replace('/');
    } catch (_) {
      errorEl.textContent = 'Cannot reach the server — is it running?';
      enable();
    }
  });
})();
