/**
 * Reproduce the old late-.env auth failure, then prove current harness pins
 * prevent it. Uses copied Python/frontend source, a synthetic cached CV and
 * dummy credentials in a temp project. Never reads/writes the owner's .env/CVs.
 */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { cpSync, existsSync, mkdirSync, mkdtempSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { basename, resolve } from 'node:path';
import { PYTHON, REPO, startApi, stopApi, loadDashboard, waitFor, text } from './harness.mjs';

function fixture(commentStyle) {
  const root = mkdtempSync(resolve(tmpdir(), 'rja-env-isolation-'));
  try {
    // Copy source only, never .env, keys, caches, DBs, CVs or __pycache__.
    for (const directory of ['api', 'tools']) {
      cpSync(resolve(REPO, directory), resolve(root, directory), {
        recursive: true,
        filter: (path) => statSync(path).isDirectory()
          ? basename(path) !== '__pycache__'
          : path.endsWith('.py'),
      });
    }
    cpSync(resolve(REPO, 'frontend'), resolve(root, 'frontend'), {
      recursive: true,
      filter: (path) => statSync(path).isDirectory() || /\.(html|css|js)$/.test(path),
    });
    cpSync(resolve(REPO, 'create_user.py'), resolve(root, 'create_user.py'));
    cpSync(resolve(REPO, 'tests/e2e/fixtures/env_probe.py'), resolve(root, 'env_probe.py'));
    cpSync(resolve(REPO, 'tests/e2e/fixtures/jobs.snapshot.json'), resolve(root, 'jobs.snapshot.json'));
    writeFileSync(resolve(root, 'environment-fixture.marker'), 'synthetic E2E environment only\n');
    writeFileSync(resolve(root, '.env'), commentStyle
      ? 'API_TOKEN=  # e2e-dummy-comment\nAPPLY_API_TOKEN=  # e2e-dummy-apply-comment\n'
      : 'API_TOKEN=e2e-dummy-dotenv-token\nAPPLY_API_TOKEN=e2e-dummy-dotenv-apply-token\n');

    // A cache anchor, not a parsed PDF. The real cheap cache reader hashes it;
    // this ensures /api/cv/profile REALLY imports cv_parser/load_dotenv instead
    // of returning early for an absent CV (which would be a false green test).
    const cv = Buffer.from('Synthetic E2E CV cache anchor. Not a real personal CV.\n');
    writeFileSync(resolve(root, 'my_cv.pdf'), cv);
    mkdirSync(resolve(root, 'cache'));
    const hash = createHash('md5').update(cv).digest('hex').slice(0, 16);
    writeFileSync(resolve(root, 'cache', `cv_profile_${hash}.json`), JSON.stringify({
      name: 'Environment Fixture', skills: ['Python', 'React'],
    }));
    // Allowlist OS necessities only. No developer provider credentials,
    // PYTHONPATH, dotenv-disable flag, cloud config or personal CV paths.
    const environment = {};
    for (const name of ['PATH', 'SystemRoot', 'SYSTEMROOT', 'WINDIR', 'LD_LIBRARY_PATH', 'LANG', 'LC_ALL']) {
      if (process.env[name] !== undefined) environment[name] = process.env[name];
    }
    Object.assign(environment, {
      HOME: root, USERPROFILE: root, PYTHONIOENCODING: 'utf-8',
      API_TOKEN: 'e2e-dummy-inherited-token', APPLY_API_TOKEN: 'e2e-dummy-inherited-apply-token',
      CV_PATH: 'my_cv.pdf', CV_DIR: 'cvs', JOBS_SOURCE: 'snapshot',
      SNAPSHOT_FILE: resolve(root, 'jobs.snapshot.json'),
      AUTH_DB_PATH: resolve(root, 'decoy-auth.db'),
      APPLY_STATE_DB_PATH: resolve(root, 'decoy-state.db'),
      SUBMIT_ENABLED: 'false', SUBMIT_DRY_RUN: 'false',
    });
    return { root, environment };
  } catch (error) {
    rmSync(root, { recursive: true, force: true });
    throw error;
  }
}

function assertRemoved(path) {
  for (const suffix of ['', '-wal', '-shm']) assert.equal(existsSync(path + suffix), false);
}

async function cleanup(api, root) {
  try {
    await stopApi(api);
    if (api) {
      // Windows handle-release race (verified on clean HEAD, 2026-10-28: the
      // EPERM/existence failure jumped between test nodes 101 and 140 on
      // identical code): a killed uvicorn / AV scanner can hold the throwaway
      // SQLite files for a moment after stopApi() returns. Wait them out
      // briefly; assertRemoved still fails the test if they never go away.
      for (const db of [api.authDb, api.stateDb]) {
        try {
          await waitFor(
            () => ['', '-wal', '-shm'].every((suffix) => !existsSync(db + suffix)),
            { timeout: 5000, interval: 100, label: `throwaway ${basename(db)} deleted` });
        } catch { /* assertRemoved records the truth */ }
      }
      assertRemoved(api.authDb); assertRemoved(api.stateDb);
    }
  } finally {
    // rmSync(root) can still hit EPERM even after the DBs are gone. Retry on
    // a short ladder; if a genuine lock survives ~2.5s, warn instead of
    // failing an otherwise-green behavior test over an unremovable temp dir.
    let lastErr = null;
    for (let attempt = 0; attempt < 4; attempt++) {
      try { rmSync(root, { recursive: true, force: true }); lastErr = null; break; }
      catch (error) {
        lastErr = error;
        await new Promise((r) => setTimeout(r, 250 * (attempt + 1)));
      }
    }
    if (lastErr) console.warn(`cleanup: temp dir ${root} could not be removed: ${lastErr.code || lastErr.message}`);
  }
}

for (const commentStyle of [false, true]) {
  describe(`environment isolation — ${commentStyle ? 'blank-value/trailing-comment' : 'plain token'} .env`, () => {
    test('negative control: omitting auth pins reproduces 200 → CV import → 401', async () => {
      const { root, environment } = fixture(commentStyle);
      try {
        const result = spawnSync(PYTHON, ['env_probe.py'], {
          cwd: root, env: environment, encoding: 'utf8', timeout: 30000,
        });
        assert.equal(result.status, 0, 'negative-control subprocess must complete');
        const line = result.stdout.split('\n').find((entry) => entry.startsWith('ENV_PROBE_RESULT '));
        assert.ok(line, 'negative control must report status-only evidence');
        assert.deepEqual(JSON.parse(line.slice('ENV_PROBE_RESULT '.length)), {
          stats_before: 200, profile: 200, stats_after: 401,
          parser_was_lazy: true, parser_from_fixture: true,
          api_token_loaded: true, apply_token_loaded: true,
        });
      } finally {
        // Same EPERM mitigation as cleanup(): on Windows a killed subprocess /
        // AV scan can hold the throwaway dir for a moment, and rmSync then
        // fails an otherwise-green test (seen on clean HEAD). Retry on the
        // short ladder; an unremovable temp dir warns instead of failing.
        let lastErr = null;
        for (let attempt = 0; attempt < 4; attempt++) {
          try { rmSync(root, { recursive: true, force: true }); lastErr = null; break; }
          catch (error) {
            lastErr = error;
            await new Promise((r) => setTimeout(r, 250 * (attempt + 1)));
          }
        }
        if (lastErr) {
          console.warn(`cleanup: temp dir ${root} could not be removed: ${lastErr.code || lastErr.message}`);
        }
      }
    });

    test('current harness stays unauthenticated through real CV import and dashboard boot', async () => {
      const { root, environment } = fixture(commentStyle);
      let api;
      let ctx;
      try {
        api = await startApi({ port: 8761, projectRoot: root, environment });
        assert.equal((await fetch(`${api.base}/api/stats`)).status, 200);
        const profile = await fetch(`${api.base}/api/cv/profile`);
        assert.equal(profile.status, 200, 'must execute real cached CV reader, not missing-CV early exit');
        assert.equal((await profile.json()).name, 'Environment Fixture');
        for (const endpoint of ['/api/stats', '/api/jobs', '/api/skills', '/api/tracker', '/api/health']) {
          assert.equal((await fetch(`${api.base}${endpoint}`)).status, 200, `${endpoint} after CV import`);
        }
        // Check APPLY_API_TOKEN independently too. This auth-only probe must
        // fail before creating an intent; submit is explicitly disarmed.
        for (const token of ['e2e-dummy-inherited-apply-token',
          commentStyle ? '# e2e-dummy-apply-comment' : 'e2e-dummy-dotenv-apply-token']) {
          assert.equal((await fetch(`${api.base}/api/apply/environment-fixture/intent`, {
            method: 'POST', headers: { Authorization: `Bearer ${token}` },
          })).status, 401, 'inherited/.env apply credentials must not enter the test server');
        }
        ctx = await loadDashboard(api.base);
        await waitFor(() => ctx.window.JobAgent?.store?.state?.stats
          && Object.values(ctx.window.JobAgent.store.state.loading).every((value) => !value), {
          label: 'dashboard boot under dummy tokenized .env',
        });
        assert.equal(text(ctx.window, 'metricTotalJobs'), '7');
        assert.deepEqual(ctx.errors, []);
        assert.deepEqual(ctx.navigations, [], 'no authentication redirect after dotenv import');
        assert.ok(ctx.requests.some((url) => url.endsWith('/api/cv/profile')));
        assert.equal((await fetch(`${api.base}/api/stats`)).status, 200);
        assertRemoved(environment.AUTH_DB_PATH);
        assertRemoved(environment.APPLY_STATE_DB_PATH);
      } finally {
        // Flush any pending boot continuation (app.js DOMContentLoaded
        // listeners awaiting loadAll()) before the jsdom window closes.
        // Closing mid-continuation races it against the torn-down global
        // and surfaced once as 'Cannot read properties of undefined
        // (reading getElementById)' in app.js under full-suite load (only
        // run of the day); a 300ms settle removes the race deterministically.
        await new Promise((r) => setTimeout(r, 300));
        ctx?.window.close();
        await cleanup(api, root);
      }
    }, { timeout: 60000 });

    test('auth mode still rejects dummy Bearer tokens and requires its isolated login session', async () => {
      const { root, environment } = fixture(commentStyle);
      let api;
      try {
        api = await startApi({ port: 8762, auth: true, projectRoot: root, environment });
        assert.equal((await fetch(`${api.base}/api/stats`)).status, 401);
        const cookie = await api.login();
        const headers = { Cookie: cookie };
        const profile = await fetch(`${api.base}/api/cv/profile`, { headers });
        assert.equal(profile.status, 200);
        assert.equal((await profile.json()).name, 'Environment Fixture');
        assert.equal((await fetch(`${api.base}/api/stats`, { headers })).status, 200);
        assert.equal((await fetch(`${api.base}/api/stats`)).status, 401);
        for (const token of ['e2e-dummy-inherited-token', commentStyle ? '# e2e-dummy-comment' : 'e2e-dummy-dotenv-token']) {
          assert.equal((await fetch(`${api.base}/api/stats`, {
            headers: { Authorization: `Bearer ${token}` },
          })).status, 401, 'neither shell nor .env token is an accepted test-server credential');
        }
        assertRemoved(environment.AUTH_DB_PATH);
        assertRemoved(environment.APPLY_STATE_DB_PATH);
      } finally {
        await cleanup(api, root);
      }
    }, { timeout: 60000 });
  });
}
