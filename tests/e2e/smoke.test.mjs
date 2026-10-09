/**
 * Frontend E2E smoke — real dashboard, real API, real data path.
 *
 * Every assertion here exists because something in this class of bug actually
 * shipped and went unnoticed:
 *   - a <script> that 404s (js/data/mockData.js was loaded for months)
 *   - a guard on an undefined global that is permanently false (MOCK_SKILLS,
 *     MOCK_SOURCES) and silently renders nothing
 *   - an error state that is unreachable, so an outage looks like a spinner
 *   - a widget rendering empty in every environment with no error anywhere
 *
 * Unit tests passed through all of it. These don't.
 */

import { test, before, after, describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { startApi, stopApi, loadDashboard, waitFor, text, REPO } from './harness.mjs';

let api;

before(async () => { api = await startApi({ port: 8731 }); }, { timeout: 60000 });
after(async () => { await stopApi(api); });

describe('asset integrity', () => {
  test('every <script src> in index.html returns 200', async () => {
    const html = readFileSync(resolve(REPO, 'frontend', 'index.html'), 'utf8');
    const srcs = [...html.matchAll(/<script[^>]+src="([^"]+)"/g)].map((m) => m[1]);
    assert.ok(srcs.length >= 10, `expected the full script list, got ${srcs.length}`);
    const bad = [];
    for (const src of srcs) {
      const res = await fetch(`${api.base}/${src.replace(/^\//, '')}`);
      if (!res.ok) bad.push(`${src} -> ${res.status}`);
    }
    assert.deepEqual(bad, [], `dead <script src> (this is how mockData.js hid): ${bad.join(', ')}`);
  });

  test('no script references a JobAgent global that is never assigned', async () => {
    const files = [
      'js/api.js', 'js/store.js', 'js/escape.js', 'js/app.js',
      // js/auth.js assigns JobAgent.auth, which js/app.js calls. It was missing
      // from this list when login shipped, so the suite reported "auth
      // referenced but never defined" — a real failure, caused by adding a file
      // here without adding it to the inventory this test scans.
      'js/auth.js',
      'js/components/toast.js', 'js/components/navigation.js',
      'js/components/scrapeMonitor.js', 'js/components/dashboard.js',
      'js/components/jobDesk.js', 'js/components/jobDrawer.js',
      'js/components/resumeStudio.js', 'js/components/autoApply.js',
      'js/components/tracker.js',
    ];
    let src = '';
    for (const f of files) src += readFileSync(resolve(REPO, 'frontend', f), 'utf8') + '\n';
    // Strip comments so prose about removed globals isn't counted as usage.
    const code = src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/.*$/gm, '$1');
    const assigned = new Set([...code.matchAll(/JobAgent\.(\w+)\s*=/g)].map((m) => m[1]));
    const used = new Set([...code.matchAll(/JobAgent\.(\w+)/g)].map((m) => m[1]));
    const external = new Set(['API_BASE']); // set by the host page/harness
    const missing = [...used].filter((u) => !assigned.has(u) && !external.has(u));
    assert.deepEqual(missing, [], `referenced but never defined: ${missing.join(', ')}`);
  });
});

describe('happy path — live API', () => {
  let ctx;
  before(async () => {
    ctx = await loadDashboard(api.base);
    await waitFor(() => ctx.window.JobAgent?.store?.state?.stats, { label: 'stats loaded' });
  }, { timeout: 60000 });

  test('page boots with no uncaught same-origin script errors', () => {
    assert.deepEqual(ctx.errors, [], `jsdom errors: ${ctx.errors.join(' | ')}`);
  });

  test('every same-origin asset the page requests resolves', () => {
    // External CDN failures (fonts) are sandbox egress, not an app defect —
    // asserted separately so they can never hide a real same-origin 404.
    const sameOriginFailures = ctx.errors.filter((e) => /Could not load/.test(e));
    assert.deepEqual(sameOriginFailures, []);
  });

  test('the UI actually calls the endpoints it claims to', () => {
    const joined = ctx.requests.join('\n');
    for (const ep of ['/api/jobs', '/api/stats', '/api/skills', '/api/tracker', '/api/health']) {
      assert.ok(joined.includes(ep), `never requested ${ep}. Requested:\n${joined}`);
    }
  });

  test('metrics render real counts, not placeholders', async () => {
    const total = await waitFor(() => {
      const v = text(ctx.window, 'metricTotalJobs');
      return v && v !== '—' ? v : null;
    }, { label: 'metricTotalJobs' });
    assert.equal(total, '7', 'fixture has 7 jobs');
    assert.equal(text(ctx.window, 'activeJobsBadge'), '7', 'sidebar badge must match');
  });

  test('skill cloud renders real pills from /api/skills', async () => {
    const cloud = await waitFor(() => {
      const el = ctx.window.document.getElementById('topSkillsCloud');
      return el && el.querySelectorAll('.skill-pill').length ? el : null;
    }, { label: 'skill pills' });

    const pills = [...cloud.querySelectorAll('.skill-pill')].map((p) => p.textContent.trim());
    assert.ok(pills.length >= 4, `expected several pills, got ${pills.length}`);
    // Regression: this widget rendered an empty div in every environment.
    assert.ok(cloud.innerHTML.trim().length > 0, 'skill cloud must never be silently empty');

    const names = pills.map((p) => p.replace(/\d+%$/, '').trim());
    assert.ok(names.includes('Python'), `Python missing from ${JSON.stringify(names)}`);
    assert.ok(names.includes('React'), `React missing from ${JSON.stringify(names)}`);

    // Role nouns from TECH_FILTER must never surface as skills. The fixture
    // carries a legacy row ("back-end, Engineer, Developer, developer,
    // Back-end") written by the old parser, so this assertion has something
    // real to bite on — a clean fixture would let the regression through.
    for (const junk of ['Developer', 'Engineer', 'Software', 'Web', 'Backend', 'Back-end', 'Full-Stack']) {
      assert.ok(!names.includes(junk), `role noun "${junk}" leaked into the skill cloud`);
    }
    // Percentages must be real numbers, not NaN/undefined.
    for (const p of pills) assert.match(p, /\d+%$/, `pill without a percentage: ${p}`);
  });

  test('skill percentages use the stack-bearing denominator', async () => {
    // Fixture: 7 jobs; 4 contribute skills (2 non-technical + 1 legacy
    // role-noun-only row contribute none); Python in all 4 -> 100%.
    const res = await fetch(`${api.base}/api/skills?limit=50`);
    const body = await res.json();
    assert.equal(body.total_jobs, 7);
    assert.equal(body.jobs_with_stack, 4);
    const python = body.skills.find((s) => s.name === 'Python');
    assert.equal(python.count, 4);
    assert.equal(python.pct, 100);
  });

  test('sources grid renders live boards', async () => {
    const grid = await waitFor(() => {
      const el = ctx.window.document.getElementById('sourcesGrid');
      return el && el.querySelectorAll('.source-item-card').length ? el : null;
    }, { label: 'source cards' });
    const names = [...grid.querySelectorAll('.source-meta-name')].map((n) => n.textContent.trim());
    assert.ok(names.includes('Remotive'), `expected Remotive in ${JSON.stringify(names)}`);
    assert.ok(!grid.textContent.includes('Loading live stats'), 'loading text must be replaced');
  });

  test('sources grid merges aliased board names', async () => {
    // The fixture carries RemoteOKAPI and Remojobs-Backend — historical labels
    // for RemoteOK and Remotive. Both must appear merged, never as separate
    // cards competing for the same top-8 slots.
    const grid = await waitFor(() => {
      const el = ctx.window.document.getElementById('sourcesGrid');
      return el && el.querySelectorAll('.source-item-card').length ? el : null;
    }, { label: 'source cards' });
    const names = [...grid.querySelectorAll('.source-meta-name')].map((n) => n.textContent.trim());
    for (const alias of ['RemoteOKAPI', 'Remojobs-Backend', 'Remojobs-Frontend', 'FounditIN']) {
      assert.ok(!names.includes(alias), `alias "${alias}" rendered as its own source card`);
    }
    assert.ok(names.includes('RemoteOK'), `expected merged RemoteOK in ${JSON.stringify(names)}`);
    assert.ok(names.includes('Remotive'), `expected merged Remotive in ${JSON.stringify(names)}`);
    assert.equal(new Set(names).size, names.length, 'duplicate source cards rendered');

    // Counts must survive the merge, not be halved or double-counted.
    const res = await fetch(`${api.base}/api/stats`);
    const stats = await res.json();
    assert.equal(
      Object.values(stats.by_source).reduce((a, b) => a + b, 0),
      stats.total_jobs,
      'by_source must still sum to total_jobs after alias merging',
    );
  });

  test('job cards render from /api/jobs', async () => {
    const cards = await waitFor(() => {
      const els = ctx.window.document.querySelectorAll('#jobsGridContainer .job-card');
      return els.length ? els : null;
    }, { label: 'job cards' });
    const titles = [...cards].map((c) => c.querySelector('.job-role-title')?.textContent.trim());
    assert.ok(titles.includes('Senior back-end Engineer'), `got ${JSON.stringify(titles)}`);
  });

  test('no "undefined" / "NaN" / "[object Object]" leaks into rendered text', () => {
    const body = ctx.window.document.body.textContent;
    for (const bad of ['undefined', 'NaN', '[object Object]']) {
      assert.ok(!body.includes(bad), `rendered text contains "${bad}"`);
    }
  });
});

describe('failure path — API unreachable', () => {
  let ctx;
  before(async () => {
    // Point the page at a port nothing listens on: the exact scenario where
    // dead mock guards used to leave a permanent "Loading…" on screen.
    ctx = await loadDashboard(api.base, { apiBase: 'http://127.0.0.1:9' });
    await waitFor(() => ctx.window.JobAgent?.store?.state?.errors?.stats, { label: 'stats error recorded' });
  }, { timeout: 60000 });

  test('page still boots without uncaught same-origin errors', () => {
    assert.deepEqual(ctx.errors, [], `jsdom errors: ${ctx.errors.join(' | ')}`);
  });

  test('sources grid shows an explicit failure, never a stuck spinner', async () => {
    const grid = await waitFor(() => {
      const el = ctx.window.document.getElementById('sourcesGrid');
      return el && !el.textContent.includes('Loading live stats') ? el : null;
    }, { label: 'sources grid to stop loading' });
    assert.match(grid.textContent, /unavailable|No live sources/i,
      `outage must be stated, got: ${grid.textContent.trim().slice(0, 160)}`);
  });

  test('the store records WHY each section failed', () => {
    // Mutation-tested: swallowing the message (errors.skills = '') still
    // renders a generic "unavailable", so asserting the rendered word alone
    // cannot tell a reported failure from a hidden one.
    const errs = ctx.window.JobAgent.store.state.errors;
    for (const key of ['jobs', 'stats', 'skills']) {
      assert.ok(errs[key] && errs[key].length > 0,
        `errors.${key} is empty — the cause was swallowed, not reported`);
    }
  });

  test('the failure reason reaches the DOM, not just the console', async () => {
    const cloud = await waitFor(() => {
      const el = ctx.window.document.getElementById('topSkillsCloud');
      return el && /unreachable|API/i.test(el.textContent) ? el : null;
    }, { label: 'skill cloud naming the cause' });
    assert.match(cloud.textContent, /unreachable|API \d{3}|API error/i,
      `expected the actual cause on screen, got: ${cloud.textContent.trim().slice(0, 160)}`);
  });

  test('skill cloud states why it is empty', async () => {
    const cloud = await waitFor(() => {
      const el = ctx.window.document.getElementById('topSkillsCloud');
      return el && el.textContent.trim() && !el.textContent.includes('Aggregating') ? el : null;
    }, { label: 'skill cloud terminal state' });
    assert.match(cloud.textContent, /unavailable|No active listings|No tech_stack/i,
      `expected an explanation, got: ${cloud.textContent.trim().slice(0, 160)}`);
    assert.equal(cloud.querySelectorAll('.skill-pill').length, 0, 'must not invent pills');
  });

  test('job desk surfaces the API error instead of silently empty', async () => {
    const container = await waitFor(() => {
      const el = ctx.window.document.getElementById('jobsGridContainer');
      return el && el.textContent.includes('API error') ? el : null;
    }, { label: 'job desk error banner' });
    assert.match(container.textContent, /API error/);
    // And it must not claim a fallback corpus that does not exist.
    assert.ok(!/cached mock data/i.test(container.textContent),
      'must not claim mock data that was never shipped');
  });

  test('no fabricated numbers appear anywhere during an outage', () => {
    const body = ctx.window.document.body.textContent;
    assert.ok(!/\b(147|24|1,?247)\b/.test(body),
      'legacy hardcoded demo figures must not reappear when live data is missing');
  });
});


// --- login flow (real API with auth enforced) --------------------------------
//
// Everything above runs against an OPEN api (no users), which is how the suite
// predates login. This block boots a second API with a real user in a throwaway
// store, because the sign-in path is the one flow the dashboard cannot work
// without and it had zero end-to-end coverage: grep for login/auth/cookie/401
// across this file previously returned nothing.

describe('login flow — auth enforced', () => {
  let authed;

  before(async () => { authed = await startApi({ port: 8741, auth: true }); }, { timeout: 60000 });
  after(async () => { await stopApi(authed); });

  test('the login page is reachable with no session', async () => {
    const r = await fetch(`${authed.base}/login.html`);
    assert.equal(r.status, 200);
  });

  test('the dashboard shell is NOT reachable with no session', async () => {
    // Both entry points: the `GET /` gate and the StaticFiles path that used to
    // bypass it by naming the file directly.
    for (const path of ['/', '/index.html']) {
      const r = await fetch(`${authed.base}${path}`, { redirect: 'manual' });
      assert.equal(r.status, 302, `${path} should redirect to the login page`);
      assert.match(r.headers.get('location') || '', /login\.html/);
    }
  });

  test('/api/health is gated but /api/health/live is not', async () => {
    assert.equal((await fetch(`${authed.base}/api/health`)).status, 401);
    assert.equal((await fetch(`${authed.base}/api/health/live`)).status, 200);
  });

  test('a wrong password renders an error and keeps the visitor on the page', async () => {
    const ctx = await loadDashboard(authed.base, { page: 'login.html' });
    const doc = ctx.window.document;
    doc.getElementById('loginUsername').value = authed.credentials.username;
    doc.getElementById('loginPassword').value = 'definitely-not-the-password';
    doc.getElementById('loginForm').dispatchEvent(
      new ctx.window.Event('submit', { bubbles: true, cancelable: true }),
    );

    const err = await waitFor(() => {
      const el = doc.getElementById('loginError');
      return el && el.textContent.trim() ? el : null;
    }, { label: 'login error message' });
    assert.match(err.textContent, /Invalid username or password/i);
    assert.equal(ctx.navigations.length, 0, 'must not navigate away on failure');
    assert.ok(
      ctx.requests.some((u) => u.endsWith('/api/auth/login')),
      'the form must actually POST to /api/auth/login',
    );
    assert.equal(doc.getElementById('loginPassword').value, '', 'password field must be cleared');
    assert.equal(doc.querySelector('button[type="submit"]').disabled, false, 'must re-enable to retry');
    assert.deepEqual(ctx.errors, [], `same-origin script errors: ${ctx.errors.join('; ')}`);
  });

  test('correct credentials set the cookie and navigate to the dashboard', async () => {
    const ctx = await loadDashboard(authed.base, { page: 'login.html' });
    const doc = ctx.window.document;
    doc.getElementById('loginUsername').value = authed.credentials.username;
    doc.getElementById('loginPassword').value = authed.credentials.password;
    doc.getElementById('loginForm').dispatchEvent(
      new ctx.window.Event('submit', { bubbles: true, cancelable: true }),
    );

    await waitFor(() => (ctx.navigations.length ? ctx.navigations : null),
      { label: 'post-login navigation' });
    // The target URL is not observable (jsdom cannot navigate and location is
    // non-configurable), so assert the attempt plus the call that caused it:
    // login.html has exactly one navigation site, `replace('/')` after a 200.
    assert.equal(ctx.navigations.length, 1, 'exactly one navigation on success');
    assert.ok(ctx.requests.some((u) => u.endsWith('/api/auth/login')));
    assert.equal(doc.getElementById('loginError').textContent.trim(), '',
      'no error should be rendered on a successful sign-in');
    assert.deepEqual(ctx.errors, [], `same-origin script errors: ${ctx.errors.join('; ')}`);
  });

  test('the session cookie the page receives is HttpOnly and SameSite=Lax', async () => {
    const cookie = await authed.login();
    assert.match(cookie, /^rja_session=/);
    // Re-fetch through HTTP to inspect the flags the browser would have stored.
    const r = await fetch(`${authed.base}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(authed.credentials),
    });
    const raw = (r.headers.getSetCookie?.() ?? []).join('\n').toLowerCase();
    assert.match(raw, /httponly/);
    assert.match(raw, /samesite=lax/);
    assert.match(raw, /path=\//);
  });

  test('an authenticated dashboard reveals the session chip with the username', async () => {
    const cookie = await authed.login();
    const ctx = await loadDashboard(authed.base, { cookie });

    const chip = await waitFor(() => {
      const el = ctx.window.document.getElementById('sessionChip');
      return el && !el.classList.contains('hidden') ? el : null;
    }, { label: 'session chip' });
    assert.equal(ctx.window.document.getElementById('sessionUsername').textContent,
      authed.credentials.username);
    assert.equal(ctx.window.document.getElementById('sessionInitial').textContent, 'E2');
    assert.ok(chip, 'chip must be revealed for a real session');
  });

  test('sign-out invalidates the session server-side, not just locally', async () => {
    const cookie = await authed.login();

    // The cookie must work before logout...
    assert.equal((await fetch(`${authed.base}/api/health`, { headers: { Cookie: cookie } })).status, 200);

    const ctx = await loadDashboard(authed.base, { cookie });
    await waitFor(() => {
      const el = ctx.window.document.getElementById('sessionChip');
      return el && !el.classList.contains('hidden') ? el : null;
    }, { label: 'session chip before sign-out' });

    ctx.window.document.getElementById('btnSignOut').click();
    await waitFor(() => (ctx.navigations.length ? ctx.navigations : null),
      { label: 'post-signout navigation' });
    assert.ok(
      ctx.requests.some((u) => u.endsWith('/api/auth/logout')),
      'sign-out must call the server, not just drop the cookie locally',
    );

    // ...and must be dead afterwards. This is the assertion that distinguishes a
    // real server-side revocation from clearing a cookie in the browser.
    await waitFor(async () => {
      const r = await fetch(`${authed.base}/api/health`, { headers: { Cookie: cookie } });
      return r.status === 401 ? true : null;
    }, { label: 'session invalidated server-side' });
  });

  test('an unauthenticated dashboard load is bounced to the login page', async () => {
    const ctx = await loadDashboard(authed.base);  // no cookie
    await waitFor(() => (ctx.navigations.length ? ctx.navigations : null),
      { label: '401 redirect' });
    // api.js sends every 401 to `baseUrl() + '/login.html'` via location.replace.
    assert.ok(ctx.navigations.length >= 1, 'a 401 must bounce the page to the login screen');
    assert.ok(
      ctx.requests.some((u) => u.includes('/api/')),
      'the dashboard must have attempted an authenticated API call first',
    );
  });

  test('the login response reports the role so the UI can gate admin affordances', async () => {
    const r = await fetch(`${authed.base}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(authed.credentials),
    });
    const body = await r.json();
    assert.equal(body.authenticated, true);
    assert.equal(body.username, authed.credentials.username);
    assert.equal(body.role, 'admin', 'the first user on a fresh store bootstraps as admin');
  });
});

// ---------------------------------------------------------------------------
// Header layout contract.
//
// The sign-out button used to be pushed off-screen: .quick-search-wrapper had a
// fixed `width: 420px`, .header-left and .header-center had no rule at all, and
// .header-right declared no flex behaviour. The header row's intrinsic minimum
// was therefore ~1350px, while .app-main only offers (viewport - the 256px
// fixed sidebar) — so it overflowed below roughly a 1610px window, i.e. on
// nearly every laptop. The buttons are `white-space: nowrap` and cannot shrink,
// so the last flex item (#btnSignOut) was the casualty.
//
// jsdom does no layout, so overflow cannot be asserted directly. What CAN be
// pinned is the contract that makes overflow impossible, which is what a future
// edit would most plausibly break.
// ---------------------------------------------------------------------------
describe('header layout contract', () => {
  const read = (rel) => readFileSync(resolve(REPO, 'frontend', rel), 'utf8');
  const stripComments = (css) => css.replace(/\/\*[\s\S]*?\*\//g, '');

  /** All declaration blocks for a selector, concatenated (media queries included). */
  function declarations(css, selector) {
    const clean = stripComments(css);
    const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const re = new RegExp(`${escaped}\\s*\\{([^}]*)\\}`, 'g');
    const out = [];
    let m;
    while ((m = re.exec(clean)) !== null) out.push(m[1]);
    return out.join('\n');
  }

  test('.header-right can never be squeezed', () => {
    const d = declarations(read('css/layout.css'), '.header-right');
    assert.match(
      d,
      /flex:\s*0 0 auto/,
      '.header-right holds the session controls and must not shrink; without flex: 0 0 auto the row overflow pushes #btnSignOut off-screen',
    );
  });

  test('.header-center absorbs the shrink instead', () => {
    const d = declarations(read('css/layout.css'), '.header-center');
    assert.match(d, /flex:\s*1 1 auto/, 'the search is the only compressible header region');
    assert.match(d, /min-width:\s*0/, 'a flex child defaults to min-width: auto and refuses to shrink below its content');
  });

  test('.header-left shrinks to an ellipsis rather than widening the row', () => {
    const css = read('css/layout.css');
    assert.match(declarations(css, '.header-left'), /min-width:\s*0/);
    const bc = declarations(css, '.breadcrumb-current');
    assert.match(bc, /text-overflow:\s*ellipsis/);
    assert.match(bc, /overflow:\s*hidden/);
  });

  test('the search wrapper has no fixed pixel width', () => {
    const d = declarations(read('css/layout.css'), '.quick-search-wrapper');
    assert.doesNotMatch(
      d,
      /(^|[^-])width:\s*\d+px/,
      'a fixed px width here is exactly what set the header minimum and pushed #btnSignOut off-screen',
    );
    assert.match(d, /max-width:\s*420px/, 'keep the 420px cap, just not as a floor');
    assert.match(d, /min-width:\s*0/);
  });

  test('#btnSignOut still has an icon and an accessible name at every tier', () => {
    const html = read('index.html');
    const btn = html.match(/<button[^>]*id="btnSignOut"[\s\S]*?<\/button>/);
    assert.ok(btn, 'no #btnSignOut button in index.html');
    assert.match(btn[0], /<svg/, 'the <=900px tier hides the label and shows the icon only; without an <svg> the button would render empty');
    assert.match(btn[0], /<span>Sign out<\/span>/, 'the visible label must exist at wide tiers');
    assert.match(btn[0], /aria-label="[^"]+"/, 'title= is not a reliable accessible name once the <span> is display:none');
  });

  test('every header button the tiers reduce is still named for assistive tech', () => {
    const html = read('index.html');
    for (const id of ['btnSyncSheets', 'btnScrapeNow', 'btnThemeToggle', 'btnSignOut']) {
      const tag = html.match(new RegExp(`<button[^>]*id="${id}"[^>]*>`));
      assert.ok(tag, `no #${id} in index.html`);
      assert.match(tag[0], /aria-label="[^"]+"/, `#${id} loses its accessible name when a tier hides its label`);
    }
  });

  test('#btnSignOut is the last item in .header-right', () => {
    // Documented because it is the reason this button was the one that vanished:
    // overflow ejects the LAST flex item first. Reordering the region changes
    // which control gets sacrificed, so the order is part of the contract.
    const html = read('index.html');
    const region = html.match(/<div class="header-right">([\s\S]*?)<\/header>/);
    assert.ok(region, 'no .header-right region before </header>');
    const ids = [...region[1].matchAll(/id="(btn[A-Za-z]+|sessionChip)"/g)].map((m) => m[1]);
    assert.ok(ids.length >= 4, `expected the full control set, found: ${ids.join(', ')}`);
    assert.equal(ids[ids.length - 1], 'btnSignOut', `order is: ${ids.join(', ')}`);
  });

  test('the responsive ladder is present and descending', () => {
    const css = stripComments(read('css/layout.css'));
    const widths = [...css.matchAll(/@media \(max-width:\s*(\d+)px\)/g)].map((m) => Number(m[1]));
    assert.ok(widths.length >= 6, `expected the graded ladder, found only: ${widths.join(', ')}`);
    for (let i = 1; i < widths.length; i += 1) {
      assert.ok(widths[i] < widths[i - 1], `breakpoints out of order: ${widths.join(', ')}`);
    }
    assert.ok(widths.includes(768), 'the sidebar-hiding 768px breakpoint must survive');
  });
});
