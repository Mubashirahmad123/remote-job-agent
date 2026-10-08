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

import { spawn, spawnSync } from 'node:child_process';
import { readFileSync, rmSync } from 'node:fs';
import os from 'node:os';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { JSDOM, VirtualConsole } from 'jsdom';

const HERE = dirname(fileURLToPath(import.meta.url));
export const REPO = resolve(HERE, '..', '..');
import { existsSync } from 'node:fs';

// Both `venv/` (what run.sh documents) and `.venv/` (what most tooling creates
// by default) are honoured, then the ambient interpreter. Picking the wrong one
// fails confusingly: the API never imports fastapi, and startApi() reports
// "did not start within 30s" instead of "wrong interpreter".
const VENV_CANDIDATES = process.platform === 'win32'
  ? ['venv/Scripts/python.exe', '.venv/Scripts/python.exe']
  : ['venv/bin/python', '.venv/bin/python'];
// An explicit interpreter always wins. run.sh resolves the same candidate list
// and exports its choice, so the script that fails fast with a readable message
// and the harness that actually spawns uvicorn can never disagree.
const PYTHON = process.env.RJA_PYTHON
  || VENV_CANDIDATES
    .map((rel) => resolve(REPO, rel))
    .find((candidate) => existsSync(candidate))
  || (process.platform === 'win32' ? 'python' : 'python3');
const SNAPSHOT = resolve(HERE, 'fixtures', 'jobs.snapshot.json');

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/**
 * Boot uvicorn on a free port, seeded with the fixture snapshot.
 *
 * AUTH ISOLATION — this is load-bearing, not tidiness. The suite used to boot
 * with no AUTH_DB_PATH, so the API read the developer's real
 * `data/apply_submit.db`. The moment anyone ran the documented production step
 * (`python create_user.py <name>`), a user existed, every /api/* route started
 * answering 401, and `startApi()` spun for 30s before throwing "API did not
 * start" — an error that points at startup when the real cause is auth. Mirrors
 * the `_isolate_auth_db` fixture in tests/conftest.py, which the Python suite
 * already got right.
 *
 * `{ auth: true }` additionally creates a user in that throwaway store, so the
 * login flow can be driven end to end. Startup is detected via
 * /api/health/live (unauthenticated by design) precisely because /api/health is
 * 401 in that mode.
 */
export async function startApi({ port = 8731, auth = false } = {}) {
  const authDb = resolve(
    os.tmpdir(),
    `rja-e2e-auth-${port}-${Date.now()}-${Math.random().toString(36).slice(2)}.db`,
  );
  // Apply state needs its own throwaway file too. AUTH_DB_PATH only redirects the
  // users/sessions tables; without this the suite still opened — and would write
  // claims, intents and review artifacts into — the developer's real
  // data/apply_submit.db. Verified: an e2e run created that file's apply tables.
  const stateDb = resolve(
    os.tmpdir(),
    `rja-e2e-state-${port}-${Date.now()}-${Math.random().toString(36).slice(2)}.db`,
  );

  const env = {
    ...process.env,
    SNAPSHOT_FILE: SNAPSHOT,
    API_CACHE_TTL: '60',
    // Point auth at a throwaway file so the developer's real users/sessions are
    // neither read nor written.
    AUTH_DB_PATH: authDb,
    APPLY_STATE_DB_PATH: stateDb,
    // Never inherit a token from the developer's shell: a set API_TOKEN flips
    // open_access() off and would 401 every unauthenticated test.
    API_TOKEN: '',
    APPLY_API_TOKEN: '',
    // Keep the brute-force limiter out of the way of a suite that signs in
    // repeatedly from one address.
    LOGIN_RATE_LIMIT: '100000',
    LOGIN_USER_RATE_LIMIT: '100000',
  };

  let credentials = null;
  if (auth) {
    credentials = { username: 'e2e-operator', password: 'e2e-Secret-Pass-1' };
    // Create the user BEFORE booting the server: the first user on a fresh store
    // becomes admin, which is what the login-flow tests assume.
    const created = spawnSync(
      PYTHON,
      ['create_user.py', credentials.username, credentials.password, '--role', 'admin'],
      { cwd: REPO, env, encoding: 'utf8' },
    );
    if (created.status !== 0) {
      throw new Error(`create_user.py failed (${created.status}):\n${created.stderr || created.stdout}`);
    }
  }

  const proc = spawn(
    PYTHON,
    ['-m', 'uvicorn', 'api.app:app', '--host', '127.0.0.1', '--port', String(port), '--log-level', 'warning'],
    { cwd: REPO, env, stdio: ['ignore', 'pipe', 'pipe'] },
  );
  let log = '';
  proc.stdout.on('data', (d) => { log += d; });
  proc.stderr.on('data', (d) => { log += d; });

  const base = `http://127.0.0.1:${port}`;
  const deadline = Date.now() + 30000;
  while (Date.now() < deadline) {
    try {
      const r = await fetch(`${base}/api/health/live`);
      if (r.ok) {
        return {
          proc,
          base,
          log: () => log,
          credentials,
          authDb,
          stateDb,
          /** Sign in and return the session cookie header value. */
          login: async (username, password) => {
            const response = await fetch(`${base}/api/auth/login`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                username: username ?? credentials?.username,
                password: password ?? credentials?.password,
              }),
            });
            if (!response.ok) {
              throw new Error(`login failed: ${response.status} ${await response.text()}`);
            }
            const setCookie = response.headers.getSetCookie?.() ?? [response.headers.get('set-cookie')];
            const session = setCookie
              .map((c) => String(c || ''))
              .find((c) => c.startsWith('rja_session='));
            if (!session) throw new Error('login succeeded but set no rja_session cookie');
            return session.split(';')[0];
          },
          cleanup: () => {
            for (const db of [authDb, stateDb]) {
              for (const suffix of ['', '-wal', '-shm']) {
                try { rmSync(db + suffix, { force: true }); } catch { /* best effort */ }
              }
            }
          },
        };
      }
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
  // Remove the throwaway auth and apply-state stores (and their WAL/SHM
  // siblings) so repeated suite runs cannot accumulate temp databases.
  api.cleanup?.();
}

/**
 * Load the real index.html in jsdom, pointed at `base`.
 * Returns { dom, window, errors, externalErrors, consoleErrors, requests }.
 * `errors` is same-origin only — third-party CDN failures land in
 * `externalErrors` so a sandbox with no egress can't mask an app bug.
 */
export async function loadDashboard(base, { apiBase = base, page = 'index.html', cookie = '' } = {}) {
  const html = readFileSync(resolve(REPO, 'frontend', page), 'utf8');
  const errors = [];          // same-origin: app bugs, always fatal to a test
  const externalErrors = [];  // third-party CDNs: unreachable in this sandbox
  const consoleErrors = [];
  const requests = [];
  // jsdom cannot navigate, and `location.replace` is non-writable AND
  // non-configurable, so it cannot be stubbed either (verified: assigning
  // throws "Cannot assign to read only property", and Object.defineProperty on
  // window.location throws "Cannot redefine property"). What jsdom DOES emit is
  // a jsdomError, so a navigation attempt is observable even though its target
  // is not. Tests therefore assert on the attempt plus the network calls the
  // page made, which is the substantive behaviour anyway.
  const navigations = [];

  // A failed SAME-ORIGIN resource is exactly the mockData.js bug and must fail
  // the suite. A failed third-party resource (Google Fonts) only means this
  // sandbox has no egress, so it is recorded separately rather than ignored.
  const isExternal = (msg) => /https?:\/\//.test(msg) && !msg.includes('127.0.0.1') && !msg.includes('localhost');

  const virtualConsole = new VirtualConsole();
  virtualConsole.on('jsdomError', (e) => {
    const msg = e.message || String(e);
    if (/Not implemented: navigation/i.test(msg)) { navigations.push(msg); return; }
    (isExternal(msg) ? externalErrors : errors).push(msg);
  });
  virtualConsole.on('error', (...a) => consoleErrors.push(a.join(' ')));

  const dom = new JSDOM(html, {
    // Set the document URL to the page actually being loaded, not always "/".
    // This matters for navigation assertions: login.html ends a successful
    // sign-in with `location.replace('/')`, and when the document URL is already
    // "/" jsdom treats that as a same-document no-op and emits nothing — so the
    // success path looked identical to a path that never navigated at all.
    // Relative asset resolution is unaffected (base path is still "/").
    url: `${base}/${page}`,
    runScripts: 'dangerously',
    resources: 'usable',          // actually fetches <script src> over HTTP
    pretendToBeVisual: true,
    virtualConsole,
    beforeParse(window) {
      // jsdom has no fetch; hand the page Node's. Record every call so a test
      // can assert which endpoints the UI really hit.
      window.fetch = (input, init) => {
        const raw = typeof input === 'string' ? input : input.url;
        // Resolve relative URLs against the document base, exactly as a browser
        // would. Node's fetch requires an absolute URL and throws on '/api/...',
        // so without this any page using a relative fetch (login.html does —
        // correctly, for a same-origin form POST) reports "cannot reach the
        // server" instead of actually making the call. api.js never hit this
        // because it builds absolute URLs via baseUrl().
        const url = /^https?:\/\//i.test(raw) ? raw : new URL(raw, base).href;
        requests.push(url);
        const options = { ...(init || {}) };
        // jsdom has no cookie jar and Node's fetch will not carry one across
        // calls, so an authenticated page load has to attach it explicitly.
        if (cookie) {
          options.headers = { ...(options.headers || {}), Cookie: cookie };
        }
        return fetch(url, options);
      };
      window.__navigations = navigations;  // shared with the virtualConsole hook
      // Same-origin by default; override lets us aim at a dead port.
      window.JobAgent = { API_BASE: apiBase };
    },
  });

  const window = dom.window;
  await new Promise((res) => {
    if (window.document.readyState === 'complete') res();
    else window.addEventListener('load', res, { once: true });
  });
  return { dom, window, errors, externalErrors, consoleErrors, requests, navigations };
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
