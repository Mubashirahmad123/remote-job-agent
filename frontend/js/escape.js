/**
 * ESCAPE.JS — Untrusted-data helpers (scraped job content is attacker-controlled).
 * Load BEFORE components (see index.html script order).
 */

window.JobAgent = window.JobAgent || {};

JobAgent.escapeHtml = function (value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
};

JobAgent.safeHttpUrl = function (url) {
  const cleaned = String(url || '').trim();
  return /^https?:\/\//i.test(cleaned) ? cleaned : '#';
};
