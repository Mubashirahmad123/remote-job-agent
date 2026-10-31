/** Real dashboard polling/rendering; fake review transport, no ATS/LLM calls.
 * Real route/worker/SQLite late-result coverage is in test_review_handoff.py.
 */
import { test, before, after, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { startApi, stopApi, loadDashboard, waitFor } from './harness.mjs';

let api;
let ctx;
let work;
let release;
const job = { job_fingerprint: 'review-ui-job', job_title: 'Fixture Developer', company: 'Fixture', match_score: 76 };
const pending = { status: 'review_pending', review_run_id: 'ui-run', screenshot_url: null, submit_enabled: false };
const ready = { status: 'filled_ready', job_title: job.job_title, company: job.company,
  screenshot_url: '/api/apply/review-ui-job/screenshot', package_path: 'fixture-package', submit_enabled: false };
let posts;
let reads;
let originalAwait;

before(async () => { api = await startApi({ port: 8771, tracker: true }); }, { timeout: 60000 });
after(async () => { await stopApi(api); });
beforeEach(async () => {
  ctx = await loadDashboard(api.base);
  // Boot path, not an assertion: under `node --test` parallelism six suites
  // boot jsdom + uvicorn at once, and this budget is what makes a slow stats
  // boot a 2s delay instead of a hook failure that sinks the whole file unit
  // (observed: CI/local full-suite hit exactly this at 10s default).
  await waitFor(() => ctx.window.JobAgent?.store?.state?.stats
    && Object.values(ctx.window.JobAgent.store.state.loading).every((value) => !value),
    { timeout: 30000, label: 'stats boot' });
  posts = 0;
  reads = [];
  work = null;
  release = () => {};
  const agent = ctx.window.JobAgent;
  agent.api.getApplyQueue = async () => ({ jobs: [job] });
  agent.api.applyReview = async () => { posts++; return { ...pending }; };
  const original = agent.autoApply.awaitReview;
  originalAwait = original;
  agent.autoApply.awaitReview = function(fp, response) {
    return original.call(this, fp, response, { interval: 1, maxWait: 5000 });
  };
});
afterEach(async () => {
  release();
  if (work) await work;
  ctx?.window.close();
});

function holdStatus() {
  const gate = new Promise((resolve) => { release = resolve; });
  ctx.window.JobAgent.api.getReviewStatus = async (fp, id) => {
    reads.push([fp, id]);
    await gate;
    return { ...ready };
  };
}

test('queue stays pending until its owned result arrives, then shows the late screenshot without reposting', async () => {
  holdStatus();
  const component = ctx.window.JobAgent.autoApply;
  work = component.triggerQueue();
  await waitFor(() => reads.length === 1);
  assert.equal(component.btnRunAutoApplyQueue.disabled, true);
  assert.equal(component.latestQueueResults.length, 0, 'not prematurely reported as successful or failed');
  assert.match(component.terminalLog.textContent, /PENDING/);
  assert.deepEqual(reads, [[job.job_fingerprint, 'ui-run']]);
  release();
  await work;
  assert.equal(posts, 1);
  assert.equal(component.latestQueueResults[0].status, 'filled_ready');
  assert.equal(component.latestQueueResults[0].screenshotUrl, ready.screenshot_url);
  assert.equal(component.btnRunAutoApplyQueue.disabled, false);
  assert.equal(ctx.window.document.getElementById('btnModeSubmit').disabled, true);
});

test('deliberate Regenerate waits for the same run instead of treating pending as a completed package', async () => {
  holdStatus();
  const component = ctx.window.JobAgent.autoApply;
  work = component.regeneratePackage(job);
  await waitFor(() => reads.length === 1);
  assert.equal(component.btnRunAutoApplyQueue.disabled, true);
  release();
  await work;
  assert.equal(posts, 1);
  assert.equal(component.latestQueueResults[0].status, 'filled_ready');
  assert.equal(component.latestQueueResults[0].screenshotUrl, ready.screenshot_url);
});

test('a status-read error warns that work may still run and never automatically repeats POST', async () => {
  ctx.window.JobAgent.api.getReviewStatus = async () => { throw new Error('network failure'); };
  const component = ctx.window.JobAgent.autoApply;
  work = component.triggerQueue();
  await work;
  assert.equal(posts, 1);
  assert.equal(component.latestQueueResults[0].status, 'failed');
  assert.match(component.latestQueueResults[0].error, /may still be running.*do not resubmit/i);
  assert.equal(component.latestQueueResults[0].screenshotUrl, '');
  assert.equal(component.btnRunAutoApplyQueue.disabled, false);
});

test('polling requires a run identity, stops at its UI deadline and passes through normal results', async () => {
  const component = ctx.window.JobAgent.autoApply;
  assert.equal(await originalAwait.call(component, job.job_fingerprint, ready), ready);
  await assert.rejects(originalAwait.call(component, job.job_fingerprint, { status: 'review_pending' }), /no run ID/);
  await assert.rejects(originalAwait.call(component, job.job_fingerprint, pending, { maxWait: 0 }), /check its status before retrying/);
  assert.equal(posts, 0);
});

test('attachment verification survives polling and explains needs-review', async () => {
  ctx.window.JobAgent.api.getReviewStatus = async () => ({
    ...ready,
    status: 'needs_review',
    fill_error: 'Resume attachment missing or unverified. Review the form and package manually.',
    resume_attached: false,
    resume_verify: 'unavailable',
    cover_letter_pasted: true,
    cover_letter_verify: 'verified',
  });
  const component = ctx.window.JobAgent.autoApply;
  work = component.triggerQueue();
  await work;
  const card = component.reviewQueueResults.querySelector('.review-result-item');
  assert.equal(component.latestQueueResults[0].resumeVerification, 'unavailable');
  assert.match(card.querySelector('.review-result-status').textContent, /Resume attachment missing or unverified/);
  assert.ok(card.querySelector('.review-result-status').classList.contains('is-warning'));
  assert.match(card.querySelector('.review-result-documents').textContent, /Resume: verification unavailable/);
  assert.match(card.querySelector('.review-result-documents').textContent, /Cover letter: text verified/);
  assert.equal(ctx.window.document.getElementById('btnModeSubmit').disabled, true);
});

test('a visible attachment chip is not presented as native file-input proof', async () => {
  ctx.window.JobAgent.api.getReviewStatus = async () => ({
    ...ready,
    resume_attached: true,
    resume_verify: 'ui_confirmed',
    cover_letter_attached: true,
    cover_letter_verify: 'files_present',
  });
  const component = ctx.window.JobAgent.autoApply;
  work = component.triggerQueue();
  await work;
  const documents = component.reviewQueueResults.querySelector('.review-result-documents');
  assert.match(documents.textContent, /Resume: visible in form; input unverified/);
  assert.match(documents.textContent, /Cover letter: file name\/size verified in input/);
});
