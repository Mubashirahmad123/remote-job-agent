/** Tracker interactions: real dashboard + routes/cache/service, fake Sheets only. */
import { test, describe, before, after, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { startApi, stopApi, loadDashboard, waitFor, text } from './harness.mjs';

const REVIEW = [
  'review', 'filled_ready', 'filled_ready_submit_disabled', 'needs_review',
  'custom_questions', 'package_only', 'email_draft', 'playwright_not_installed',
  'playwright_failed', 'dream_manual', 'submit_unverified', 'failed_refunded', 'filled_future',
];
const TERMINAL = ['rejected', 'withdrawn', 'ghosted'];
const COLS = {
  applied: 'kanbanColApplied', review: 'kanbanColReview', interview: 'kanbanColInterview',
  offer: 'kanbanColOffer', rejected: 'kanbanColRejected',
};
const COUNTS = { applied: 3, review: REVIEW.length, interview: 2, offer: 1, rejected: 3 };
let api;
let ctx;

async function control(changes) {
  const response = await fetch(`${api.base}/__test__/tracker/control`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(changes),
  });
  assert.equal(response.status, 200);
}
async function serverState() {
  const response = await fetch(`${api.base}/__test__/tracker/state`);
  assert.equal(response.status, 200);
  return response.json();
}
async function trackerRows() {
  const response = await fetch(`${api.base}/api/tracker`);
  assert.equal(response.status, 200);
  return response.json();
}
function card(key, column = '') {
  const parent = column ? ctx.window.document.getElementById(COLS[column]) : ctx.window.document;
  return [...parent.querySelectorAll('.kanban-card')].find((node) => node.dataset.fp === key);
}
const key = (status) => `e2e-${status}`;
const toast = () => ctx.window.document.querySelector('.app-toast')?.textContent || '';
const agent = () => ctx.window.JobAgent;
async function ready() {
  await waitFor(() => agent()?.tracker?.kanbanColApplied
    && Object.values(agent().store.state.loading).every((value) => !value)
    && agent().store.state.tracker.length > 0, { label: 'tracker and dashboard loaded' });
  ctx.window.document.getElementById('navTracker').click();
}
async function finishedPatch() {
  await waitFor(() => /Updated .* status to:|update failed|Status saved/i.test(toast())
    && !agent().store.state.loading.tracker, { label: 'tracker update settled' });
}
async function settleTracker() {
  // A card may render before the click handler's finally block finishes.
  // Closing jsdom at that point destroys document while that handler still
  // has a pending render, creating an unrelated unhandled rejection.
  await waitFor(() => agent()?.tracker?._pendingUpdates.size === 0
    && !agent().tracker._manualSaving && !agent().tracker._syncing
    && !agent().store.state.loading.tracker, { label: 'tracker handlers settled' });
}
async function openManual(values = {}) {
  ctx.window.document.getElementById('btnNewTrackedJob').click();
  await waitFor(() => agent().tracker._manualModalOpen, { label: 'manual modal open' });
  for (const [name, value] of Object.entries({
    apply_url: 'example.invalid/manual/new-role', job_title: 'Frontend Developer',
    company: 'Manual Fixture', notes: 'Follow up with recruiter', ...values,
  })) {
    const field = agent().tracker.manualApplicationFields[name];
    field.value = value;
    field.dispatchEvent(new ctx.window.Event('input', { bubbles: true }));
  }
}
function submitManual() {
  agent().tracker.manualApplicationForm.dispatchEvent(new ctx.window.Event('submit', {
    bubbles: true, cancelable: true,
  }));
}

before(async () => { api = await startApi({ port: 8751, tracker: true }); }, { timeout: 60000 });
after(async () => { await stopApi(api); });
beforeEach(async () => {
  const response = await fetch(`${api.base}/__test__/tracker/reset`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
  });
  assert.equal(response.status, 200);
  ctx = await loadDashboard(api.base);
  await ready();
}, { timeout: 30000 });
afterEach(async () => {
  try {
    await control({ hold_patch: false });
    if (ctx?.window?.document) await settleTracker();
  } finally {
    ctx?.window.close();
  }
});

describe('tracker — rendering and persisted transitions', () => {
  test('maps every fill/review and terminal status to the correct column and count', () => {
    for (const status of REVIEW) assert.ok(card(key(status), 'review'), status);
    for (const status of TERMINAL) assert.ok(card(key(status), 'rejected'), status);
    for (const status of ['applied', 'submitted']) assert.ok(card(key(status), 'applied'), status);
    for (const status of ['interviewing', 'interview']) assert.ok(card(key(status), 'interview'), status);
    assert.ok(card(key('offer'), 'offer'));
    for (const [column, expected] of Object.entries(COUNTS)) {
      assert.equal(ctx.window.document.getElementById(COLS[column]).querySelectorAll('.kanban-card').length, expected);
      assert.equal(text(ctx.window, 'count' + column[0].toUpperCase() + column.slice(1)), String(expected));
    }
    assert.deepEqual(ctx.errors, []);
  });

  test('clicks applied → interviewing → offer → rejected, saves each move and preserves notes', async () => {
    const transitions = [['interviewing', 'interview'], ['offer', 'offer'], ['rejected', 'rejected']];
    for (const [status, column] of transitions) {
      card(key('applied')).click();
      await waitFor(() => card(key('applied'), column), { label: `persisted ${status} column` });
      const row = (await trackerRows()).find((entry) => entry.job_fingerprint === key('applied'));
      assert.equal(row.status, status);
      assert.equal(row.notes, 'Original note', 'status-only clicks must not append the old notes again');
    }
    const mutations = (await serverState()).requests.filter((r) => r.method === 'PATCH');
    assert.deepEqual(mutations.map((r) => r.body.status), ['interviewing', 'offer', 'rejected']);
    assert.ok(mutations.every((r) => !r.body.notes));
    card(key('applied')).click();
    assert.equal((await serverState()).requests.filter((r) => r.method === 'PATCH').length, 3);
    await settleTracker();
    ctx.window.close();
    ctx = await loadDashboard(api.base);
    await ready();
    assert.ok(card(key('applied'), 'rejected'), 'fresh page reads saved state, not local-only mutation');
    assert.equal(text(ctx.window, 'countRejected'), '4');
  });

  test('a review package advances using interviewing, never a backend-invalid review status', async () => {
    card(key('filled_ready'), 'review').click();
    await waitFor(() => card(key('filled_ready'), 'interview'), { label: 'review package advanced' });
    const patches = (await serverState()).requests.filter((r) => r.method === 'PATCH');
    assert.equal(patches.length, 1);
    assert.equal(patches[0].body.status, 'interviewing');
    assert.equal(text(ctx.window, 'countReview'), String(REVIEW.length - 1));
    assert.equal(text(ctx.window, 'countInterview'), '3');
  });

  test('all archived terminal cards stay archived and make no PATCH request', async () => {
    for (const status of TERMINAL) {
      const node = card(key(status), 'rejected');
      assert.ok(node.classList.contains('kanban-card-archived'));
      node.click();
      assert.match(toast(), /Archived/);
    }
    assert.equal((await serverState()).requests.filter((r) => r.method === 'PATCH').length, 0);
  });

  test('updates URL-keyed rows with both real header forks, preserving encoded URL components', async () => {
    const row = (await trackerRows()).find((entry) => entry.company === 'URL-only fixture');
    assert.equal(row.job_fingerprint, null);
    for (const headerMode of ['compact', 'autoapply']) {
      const response = await fetch(`${api.base}/__test__/tracker/reset`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rows: [row], header_mode: headerMode }),
      });
      assert.equal(response.status, 200);
      await agent().store.loadTracker();
      card(row.apply_url, 'applied').click();
      await waitFor(() => card(row.apply_url, 'interview'), { label: `${headerMode} URL-only row updated` });
      const updated = (await trackerRows()).find((entry) => entry.apply_url === row.apply_url);
      assert.equal(updated.status, 'interviewing');
      assert.equal(updated.notes, 'Keep this note');
    }
  });

  test('rapid duplicate clicks send only one PATCH and show a pending state until refresh completes', async () => {
    await control({ hold_patch: true });
    const node = card(key('applied'));
    node.click();
    node.click();
    await waitFor(async () => (await serverState()).requests.some((r) => r.method === 'PATCH'), {
      label: 'first PATCH held on server',
    });
    assert.equal(card(key('applied')).getAttribute('aria-busy'), 'true');
    card(key('applied')).click();
    assert.equal((await serverState()).requests.filter((r) => r.method === 'PATCH').length, 1);
    assert.equal((await serverState()).rows.find((r) => r.job_fingerprint === key('applied')).status, 'applied');
    await control({ hold_patch: false });
    await waitFor(() => card(key('applied'), 'interview')?.getAttribute('aria-busy') !== 'true'
      && card(key('applied'), 'interview'), { label: 'one completed transition' });
    assert.equal((await serverState()).requests.filter((r) => r.method === 'PATCH').length, 1);
  });

  test('renders empty column states and zero counts after a successful empty reload', async () => {
    await fetch(`${api.base}/__test__/tracker/reset`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{"rows":[]}',
    });
    await agent().store.loadTracker();
    for (const column of Object.keys(COLS)) {
      const container = ctx.window.document.getElementById(COLS[column]);
      assert.equal(container.querySelectorAll('.kanban-card').length, 0);
      // Each lane has its own empty copy now, so assert the state, not the wording.
      const empty = container.querySelector('.kanban-empty');
      assert.ok(empty && empty.textContent.trim().length > 0, `${column} shows an empty-state line`);
      assert.equal(text(ctx.window, 'count' + column[0].toUpperCase() + column.slice(1)), '0');
    }
  });

  test('escapes untrusted titles/company names instead of inserting HTML into cards', async () => {
    const company = '<img src=x onerror="window.trackerInjected=true">';
    const title = '<script>window.trackerInjected=true</script>';
    await fetch(`${api.base}/__test__/tracker/reset`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rows: [{ job_fingerprint: 'safe-html', company, job_title: title, status: 'applied' }] }),
    });
    await agent().store.loadTracker();
    const node = card('safe-html');
    assert.equal(node.querySelector('.k-company').textContent, company);
    assert.equal(node.querySelector('.k-title').textContent, title);
    assert.equal(node.querySelectorAll('img,script').length, 0);
    assert.equal(ctx.window.trackerInjected, undefined);
  });
});

describe('tracker — failures must never fabricate saved progress', () => {
  test('a real Sheets-boundary write failure keeps the original card/count and permits retry', async () => {
    await control({ fail_write: true });
    card(key('applied')).click();
    await finishedPatch();
    assert.ok(card(key('applied'), 'applied'));
    assert.equal(text(ctx.window, 'countApplied'), String(COUNTS.applied));
    assert.match(toast(), /update failed/i);
    assert.doesNotMatch(toast(), /cycled locally|Updated .* status to:/i);
    assert.equal((await trackerRows()).find((r) => r.job_fingerprint === key('applied')).status, 'applied');
    await control({ fail_write: false });
    card(key('applied')).click();
    await waitFor(() => card(key('applied'), 'interview'), { label: 'retry succeeds' });
  });

  for (const code of [401, 403, 404, 409]) {
    test(`HTTP ${code} does not mutate local/server status or display success`, async () => {
      await control({ fail_patch_status: code });
      card(key('applied')).click();
      await finishedPatch();
      assert.ok(card(key('applied'), 'applied'));
      assert.match(toast(), /update failed/i);
      assert.doesNotMatch(toast(), /Updated .* status to:|cycled locally/i);
      assert.equal((await serverState()).rows.find((r) => r.job_fingerprint === key('applied')).status, 'applied');
      if (code === 401) assert.ok(ctx.navigations.length > 0, 'expired login triggers navigation');
    });
  }

  test('network failure never changes a real tracker card locally', async () => {
    const originalFetch = ctx.window.fetch;
    ctx.window.fetch = () => Promise.reject(new Error('network disconnected'));
    card(key('applied')).click();
    await finishedPatch();
    assert.ok(card(key('applied'), 'applied'));
    assert.match(toast(), /update failed/i);
    ctx.window.fetch = originalFetch;
    assert.equal((await serverState()).requests.filter((r) => r.method === 'PATCH').length, 0);
  });

  test('a saved PATCH followed by failed GET reports saved-but-not-refreshed, then Sync restores it', async () => {
    await control({ fail_get: true });
    card(key('applied')).click();
    await finishedPatch();
    assert.match(toast(), /Status saved.*refresh failed/i);
    assert.match(text(ctx.window, 'kanbanColApplied'), /API error/);
    assert.equal((await serverState()).rows.find((r) => r.job_fingerprint === key('applied')).status, 'interviewing');
    assert.equal((await serverState()).requests.filter((r) => r.method === 'PATCH').length, 1);
    await control({ fail_get: false });
    ctx.window.document.getElementById('btnSyncTrackerSheets').click();
    await waitFor(() => card(key('applied'), 'interview') && /synced/.test(toast()), { label: 'sync recovers saved status' });
    assert.equal((await serverState()).requests.filter((r) => r.method === 'PATCH').length, 1);
  });

  test('Sync reports a tracker-read failure instead of claiming successful synchronization', async () => {
    await control({ fail_get: true });
    ctx.window.document.getElementById('btnSyncTrackerSheets').click();
    await waitFor(() => /Sync failed/.test(toast()), { label: 'sync failure visible' });
    assert.doesNotMatch(toast(), /Tracker synced/);
    assert.match(text(ctx.window, 'kanbanColApplied'), /API error/);
  });

  test('Sync refresh-endpoint failure preserves existing cards and shows failure', async () => {
    await control({ fail_refresh: true });
    ctx.window.document.getElementById('btnSyncTrackerSheets').click();
    await waitFor(() => /Sync failed/.test(toast()), { label: 'refresh failure visible' });
    assert.ok(card(key('applied'), 'applied'));
    assert.doesNotMatch(toast(), /Tracker synced/);
  });

  test('unpatchable placeholder keys and missing API client cannot fabricate local transitions', async () => {
    for (const fp of ['tracker-0', 'mock-1', '123', '#', '']) {
      const row = { id: fp, status: 'applied', company: 'Invalid fixture' };
      await agent().tracker.cycleCardStatus(row);
      assert.equal(row.status, 'applied');
    }
    const savedApi = agent().api;
    const row = agent().store.state.tracker.find((r) => r.id === key('applied'));
    agent().api = null;
    try {
      await agent().tracker.cycleCardStatus(row);
      assert.equal(row.status, 'applied');
    } finally { agent().api = savedApi; }
    assert.equal((await serverState()).requests.filter((r) => r.method === 'PATCH').length, 0);
  });
});

describe('tracker — manual application form', () => {
  test('validates required fields, unsafe URL schemes and follow-up bounds without posting', async () => {
    await openManual({ apply_url: '', job_title: '', company: '', follow_up_days: '366' });
    submitManual();
    for (const name of ['apply_url', 'job_title', 'company', 'follow_up_days']) {
      assert.equal(agent().tracker.manualApplicationFields[name].getAttribute('aria-invalid'), 'true', name);
    }
    agent().tracker.manualApplicationFields.apply_url.value = 'javascript:alert(1)';
    submitManual();
    assert.match(agent().tracker.manualApplicationErrors.apply_url.textContent, /http\(s\)/);
    assert.equal((await serverState()).requests.filter((r) => r.method === 'POST').length, 0);
  });

  test('creates once on repeated submit, normalizes URL, reloads and persists after a new page', async () => {
    const response = await fetch(`${api.base}/__test__/tracker/reset`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rows: [], header_mode: 'compact' }),
    });
    assert.equal(response.status, 200);
    await agent().store.loadTracker();
    await openManual();
    submitManual();
    assert.equal(agent().tracker.btnSaveManualApplication.disabled, true);
    submitManual();
    await waitFor(() => !agent().tracker._manualModalOpen, { label: 'saved modal closes' });
    const created = (await trackerRows()).find((r) => r.company === 'Manual Fixture');
    assert.equal(created.apply_url, 'https://example.invalid/manual/new-role');
    assert.equal(created.status, 'applied');
    assert.equal(created.source, 'manual');
    assert.equal(created.notes, 'Follow up with recruiter');
    assert.equal(created.created_by, 'local-dev');
    assert.ok(created.follow_up_date);
    assert.ok(card(created.apply_url, 'applied'));
    assert.equal((await serverState()).requests.filter((r) => r.method === 'POST').length, 1);
    await settleTracker();
    ctx.window.close();
    ctx = await loadDashboard(api.base);
    await ready();
    assert.ok(card(created.apply_url, 'applied'));
    card(created.apply_url).click();
    await waitFor(() => card(created.apply_url, 'interview'), { label: 'new manual row advances' });
    assert.equal((await trackerRows()).find((r) => r.apply_url === created.apply_url).notes, 'Follow up with recruiter');
  });

  test('failed creation keeps entered values and modal open, reenables saving and allows retry', async () => {
    await control({ fail_write: true });
    await openManual();
    submitManual();
    await waitFor(() => /Add failed/.test(text(ctx.window, 'manualApplicationStatus'))
      && !agent().tracker._manualSaving, { label: 'create failure visible' });
    assert.equal(agent().tracker._manualModalOpen, true);
    assert.equal(agent().tracker.manualApplicationFields.company.value, 'Manual Fixture');
    assert.equal(agent().tracker.btnSaveManualApplication.disabled, false);
    assert.ok(!(await trackerRows()).some((r) => r.company === 'Manual Fixture'));
    await control({ fail_write: false });
    submitManual();
    await waitFor(() => !agent().tracker._manualModalOpen, { label: 'retry saved' });
    assert.equal((await trackerRows()).filter((r) => r.company === 'Manual Fixture').length, 1);
  });

  test('saved creation with failed reload is not reported as fully refreshed or left open for duplicate retry', async () => {
    await openManual();
    await control({ fail_get: true });
    submitManual();
    await waitFor(() => !agent().tracker._manualSaving && !agent().tracker._manualModalOpen, { label: 'saved-but-refresh-failed create' });
    assert.match(toast(), /saved.*refresh failed/i);
    assert.doesNotMatch(toast(), /added to the APPLIED/);
    assert.equal((await serverState()).rows.filter((r) => r.company === 'Manual Fixture').length, 1);
    await control({ fail_get: false });
    ctx.window.document.getElementById('btnSyncTrackerSheets').click();
    await waitFor(() => [...ctx.window.document.querySelectorAll('.k-company')]
      .some((node) => node.textContent === 'Manual Fixture'), { label: 'manual row recovered' });
    assert.equal((await serverState()).requests.filter((r) => r.method === 'POST').length, 1);
  });
});
