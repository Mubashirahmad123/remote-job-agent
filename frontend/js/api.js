/**
 * API.JS — Live FastAPI client for Phase 1 reads.
 * One function per endpoint group (mirrors api/routers/):
 *   health  -> GET /api/health
 *   jobs    -> GET /api/jobs, GET /api/jobs/{fp}
 *   stats   -> GET /api/stats
 *   tracker -> GET /api/tracker, PATCH /api/tracker/{fp}
 *   system  -> POST /api/jobs/refresh
 *   runs    -> POST /api/scrape, GET /api/scrape[/{run_id}]
 * Backend contract: api/schemas.py (JobOut, TrackerEntry, HealthOut).
 */

window.JobAgent = window.JobAgent || {};

JobAgent.api = (() => {
  // Same-origin by default; override via window.JobAgent.API_BASE or
  // localStorage 'rja_api_base' (e.g. http://127.0.0.1:8000 for file:// dev).
  function baseUrl() {
    if (window.JobAgent.API_BASE) return window.JobAgent.API_BASE.replace(/\/$/, '');
    try {
      const saved = localStorage.getItem('rja_api_base');
      if (saved && saved.trim()) return saved.trim().replace(/\/$/, '');
    } catch (_) { /* storage unavailable */ }
    if (window.location.protocol.startsWith('http')) return window.location.origin.replace(/\/$/, '');
    return 'http://127.0.0.1:8000';
  }

  function authHeaders() {
    let token = '';
    try {
      token = localStorage.getItem('rja_api_token') || '';
    } catch (_) { /* ignore */ }
    token = (token || '').trim();
    return token ? { Authorization: 'Bearer ' + token } : {};
  }

  async function request(path, options = {}) {
    const url = baseUrl() + path;
    let res;
    try {
      res = await fetch(url, {
        ...options,
        headers: {
          'Content-Type': 'application/json',
          ...authHeaders(),
          ...(options.headers || {}),
        },
      });
    } catch (e) {
      const err = new Error('API unreachable at ' + baseUrl() + ' — is uvicorn running?');
      err.code = 'UNREACHABLE';
      err.cause = e;
      throw err;
    }
    if (res.status === 401) {
      const err = new Error('Unauthorized — check API_TOKEN (localStorage rja_api_token).');
      err.code = 'UNAUTHORIZED';
      err.status = 401;
      throw err;
    }
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const body = await res.json();
        detail = body.detail || JSON.stringify(body);
      } catch (_) { /* keep statusText */ }
      const err = new Error('API ' + res.status + ': ' + detail);
      err.code = 'HTTP_' + res.status;
      err.status = res.status;
      throw err;
    }
    return res.json();
  }

  function query(params = {}) {
    const sp = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v === undefined || v === null || v === '') continue;
      sp.append(k, String(v));
    }
    const s = sp.toString();
    return s ? '?' + s : '';
  }

  // ---- endpoint groups (one per backend router file) ----

  async function getHealth() {
    return request('/api/health');
  }

  async function getJobs({ tab = 'ALL JOBS', q = '', source = '', limit = 200, offset = 0 } = {}) {
    return request('/api/jobs' + query({ tab, q, source, limit, offset }));
  }

  async function getJob(fingerprint) {
    return request('/api/jobs/' + encodeURIComponent(fingerprint));
  }

  async function getStats() {
    return request('/api/stats');
  }

  async function getTracker(status = '') {
    return request('/api/tracker' + query({ status: status || undefined }));
  }

  async function patchTracker(fingerprint, status, notes = '') {
    return request('/api/tracker/' + encodeURIComponent(fingerprint), {
      method: 'PATCH',
      body: JSON.stringify({ status, notes }),
    });
  }

  async function refreshJobs(tab = '') {
    return request('/api/jobs/refresh', {
      method: 'POST',
      body: JSON.stringify(tab ? { tab } : {}),
    });
  }

  async function startScrape() {
    return request('/api/scrape', { method: 'POST', body: JSON.stringify({}) });
  }

  async function getScrape(runId) {
    return request('/api/scrape/' + encodeURIComponent(runId));
  }

  async function listScrapes() {
    return request('/api/scrape');
  }

  return {
    baseUrl,
    getHealth,
    getJobs,
    getJob,
    getStats,
    getTracker,
    patchTracker,
    refreshJobs,
    startScrape,
    getScrape,
    listScrapes,
  };
})();
