/**
 * AUTH-BOOTSTRAP.JS — one-time API token capture for token-protected deploys.
 *
 * A public deployment runs the API with API_TOKEN set, so every /api/* call
 * needs a Bearer token. Open the dashboard once as:
 *
 *     https://<host>/?token=<API_TOKEN>
 *
 * This stores it in localStorage['rja_api_token'] (the key api.js reads on
 * every request) and strips it from the address bar via replaceState so it is
 * not left in browser history. No-op when there is no ?token= parameter.
 */
(function () {
  'use strict';
  try {
    var params = new URLSearchParams(window.location.search);
    var token = (params.get('token') || '').trim();
    if (!token) return;
    window.localStorage.setItem('rja_api_token', token);
    params.delete('token');
    var qs = params.toString();
    var clean = window.location.pathname + (qs ? '?' + qs : '') + window.location.hash;
    window.history.replaceState({}, document.title, clean);
  } catch (_) { /* storage/history unavailable — token simply stays unset */ }
})();
