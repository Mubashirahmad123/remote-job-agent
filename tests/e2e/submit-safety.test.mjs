/** Real HTTP regression for disarmed submit endpoints. No ATS is contacted. */
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { startApi, stopApi } from './harness.mjs';

let api;
let cookie;
before(async () => {
  // Throwaway auth/state DBs, fixture snapshot, and false safety flags are
  // enforced by startApi. The first synthetic user is an admin.
  api = await startApi({ port: 8781, auth: true });
  cookie = await api.login();
}, { timeout: 60000 });
after(async () => { await stopApi(api); });

test('authenticated HTTP intent and submit fail closed when disarmed', async () => {
  const health = await fetch(`${api.base}/api/health`, { headers: { Cookie: cookie } });
  assert.equal(health.status, 200);
  assert.equal((await health.json()).submit_mode, 'disarmed');

  for (const [route, body] of [
    ['intent', { mode: 'review' }],
    ['submit', { confirm: true, job_fingerprint: 'synthetic-fingerprint' }],
  ]) {
    const response = await fetch(`${api.base}/api/apply/synthetic-fingerprint/${route}`, {
      method: 'POST',
      headers: { Cookie: cookie, 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    assert.equal(response.status, 403, `${route} must be disarmed`);
    assert.match((await response.json()).detail, /kill-switch/i);
  }
});
