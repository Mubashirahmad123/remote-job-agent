/**
 * E2E harness — boots the real API and loads the real dashboard in jsdom.
 *
 * Why jsdom and not Playwright: this sandbox has no egress to the Playwright
 * browser CDN (`playwright install chromium` fails), so a real-browser run is
 * not reproducible here. jsdom still executes the actual `frontend/js/*` files
 * against the actual FastAPI app over HTTP, which is where every bug this
 * suite targets lives (dead guards, undefined globals, states that never
 * render). It does NOT cover CSS, layout, or real input events — see
 * FRONTEND.md for that gap.
 */

import { spawn } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { JSDOM, VirtualConsole } from 'jsdom';

const HERE = dirname(fileURLToPath(import.meta.url));
export const REPO = resolve(HERE, '..', '..');
const PYTHON = resolve(REPO, 'venv', 'bin', 'python');
const INDEX_HTML = resolve(REPO, 'frontend', 'index.html');
const SNAPSHOT = resolve(HERE, 'fixtures', 'jobs.snapshot.json');

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** Boot uvicorn on a free port, seeded with the fixture snapshot. */
export async function startApi({ port = 8731 } = {}) {
  const proc = spawn(
    PYTHON,
    ['-m', 'uvicorn', 'api.app:app', '--host', '127.0.0.1', '--port', String(port), '--log-level', 'warning'],
    {
      cwd: REPO,
      env: { ...process.env, SNAPSHOT_FILE: SNAPSHOT, API_CACHE_TTL: '60' },
      stdio: ['ignore', 'pipe', 'pipe'],
    },
  );
  let log = '';
  proc.stdout.on('data', (d) => { log += d; });
  proc.stderr.on('data', (d) => { log += d; });

  const base = `http://127.0.0.1:${port}`;
  const deadline = Date.now() + 30000;
  while (Date.now() < deadline) {
    try {
      const r = await fetch(`${base}/api/health`);
      if (r.ok) return { proc, base, log: () => log };
    } catch { /* not up yet */ }
    await sleep(200);
  }
  proc.kill('SIGKILL');
  throw new Error(`API did not start within 30s. Log:\n${log}`);
}

export async function stopApi(api) {
  if (!api?.proc) return;
  api.proc.kill('SIGTERM');
  await sleep(300);
  if (!api.proc.killed) api.proc.kill('SIGKILL');
}

/**
 * Load the real index.html in jsdom, pointed at `base`.
 * Returns { dom, window, errors, externalErrors, consoleErrors, requests }.
 * `errors` is same-origin only — third-party CDN failures land in
 * `externalErrors` so a sandbox with no egress can't mask an app bug.
 */
export async function loadDashboard(base, { apiBase = base } = {}) {
  const html = readFileSync(INDEX_HTML, 'utf8');
  const errors = [];          // same-origin: app bugs, always fatal to a test
  const externalErrors = [];  // third-party CDNs: unreachable in this sandbox
  const consoleErrors = [];
  const requests = [];

  // A failed SAME-ORIGIN resource is exactly the mockData.js bug and must fail
  // the suite. A failed third-party resource (Google Fonts) only means this
  // sandbox has no egress, so it is recorded separately rather than ignored.
  const isExternal = (msg) => /https?:\/\//.test(msg) && !msg.includes('127.0.0.1') && !msg.includes('localhost');

  const virtualConsole = new VirtualConsole();
  virtualConsole.on('jsdomError', (e) => {
    const msg = e.message || String(e);
    (isExternal(msg) ? externalErrors : errors).push(msg);
  });
  virtualConsole.on('error', (...a) => consoleErrors.push(a.join(' ')));

  const dom = new JSDOM(html, {
    url: `${base}/`,
    runScripts: 'dangerously',
    resources: 'usable',          // actually fetches <script src> over HTTP
    pretendToBeVisual: true,
    virtualConsole,
    beforeParse(window) {
      // jsdom has no fetch; hand the page Node's. Record every call so a test
      // can assert which endpoints the UI really hit.
      window.fetch = (input, init) => {
        const url = typeof input === 'string' ? input : input.url;
        requests.push(url);
        return fetch(url, init);
      };
      // Same-origin by default; override lets us aim at a dead port.
      window.JobAgent = { API_BASE: apiBase };
    },
  });

  const window = dom.window;
  await new Promise((res) => {
    if (window.document.readyState === 'complete') res();
    else window.addEventListener('load', res, { once: true });
  });
  return { dom, window, errors, externalErrors, consoleErrors, requests };
}

/** Poll until `fn()` is truthy or timeout; returns the value or throws. */
export async function waitFor(fn, { timeout = 10000, interval = 50, label = 'condition' } = {}) {
  const deadline = Date.now() + timeout;
  let last;
  while (Date.now() < deadline) {
    try {
      last = await fn();
      if (last) return last;
    } catch (e) { last = e.message; }
    await sleep(interval);
  }
  throw new Error(`Timed out waiting for ${label} (last: ${JSON.stringify(last)?.slice(0, 200)})`);
}

export const text = (window, id) => (window.document.getElementById(id)?.textContent || '').trim();
