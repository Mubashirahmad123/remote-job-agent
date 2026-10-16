# Task brief — resolve why Greenhouse confirmation metadata is "not found"

> **Status (2026-10-16):** This was a historical investigation brief, not a
> current execution checklist. The metadata was found in the demo board's
> `window.__remixContext`; extraction and HTML confirmation-text normalization
> have since been fixed and fixture-tested. The full submit path was not run:
> no fill, dry run, intent, click or submission occurred. reCAPTCHA remains
> present and post-submit confirmation is still unobserved. See
> `LIVE_SUBMIT.md`, `CHANGELOG.md`, and `TESTER.md` for the actual evidence.

## Where to run this

**Part 1A needs real network egress to `job-boards.greenhouse.io`.** A cloud
build sandbox (the kind that can reach only package registries and GitHub)
**cannot run it** — do not attempt Part 1A there and do not report a network
failure as a finding. Run it on the operator's desktop, or from any shell with
real internet access.

If the agent has no egress: do **Part 1B** (offline) only, and hand the operator
the exact command from Part 1A to run and paste back. Then continue from the
returned HTML.

The build sandbox also has no Chromium binary. `pip install playwright && playwright install chromium`
is required for anything that touches a real page.

---

## Why this task exists

`LIVE_SUBMIT.md` says the supervised live submit is blocked because the
2026-10-03 read-only recon of Greenhouse's own demo board
(`https://job-boards.greenhouse.io/example/jobs/83446`, Democorp "Full Stack
Engineer") returned `confirmation_metadata_found=false`, so `/intent` would
502 before anything could happen.

That conclusion is **weaker than it looks**, for three reasons found by reading
the code:

1. **The verdict is circular.** `tools/submit_recon.py:inspect_posting` calls
   `_greenhouse_confirmation_data(page)` — *the same function* the filler uses
   (`agents/auto_applier.py:255`). If that function has a blind spot, recon
   reports "absent" for a reason that has nothing to do with the page.
2. **The evidence was not kept.** Recon writes only derived booleans
   (`--json`). No HTML is saved. `recon-democorp.json` was deleted before
   commit (see `CHANGELOG.md`, 2026-10-03). The finding cannot be re-checked.
3. **The scraper looks in narrow places.** `_greenhouse_confirmation_data`
   only reads these selectors:

   ```
   script[type="application/json"], script#__NEXT_DATA__, script[data-page]
   ```

   Its `find_values` recursion is tolerant of key naming (`confirmation_path`,
   `confirmationPath`, `confirmationmessage` all normalize), so the likely
   failure mode is **where it looks**, not **what it matches**. Separately,
   recon waits a fixed `page.wait_for_timeout(2500)` after `domcontentloaded` —
   metadata injected by a later XHR would be missed by timing alone.

### Three hypotheses, all cheap to separate

- **H1 — genuinely absent.** The `example` demo board does not serve the
  embedded JSON at all. Then the live test needs a different target, and that
  is an operator decision.
- **H2 — present, but not in a covered script form.** The data lives in a bare
  `<script>` (e.g. `window.__INITIAL_STATE__ = {...}`), a `data-*` attribute, or
  some other shape the selector does not match. **This is a fixable scraper
  bug**, and if it is the cause, the live test may be viable without touching a
  real employer.
- **H3 — present, but injected later than the probe waits.** A timing bug, not
  a selector bug.

Do not guess between them. Dump the page and look.

---

## PART 1A — the probe (read-only, no click, no fill)

Write `tools/confirmation_metadata_probe.py`. It is a **diagnostic**, not a
replacement for recon. It must:

1. Navigate to the demo URL (`domcontentloaded`, as the filler does).
2. **Poll** for the metadata for up to ~20s instead of a single fixed wait —
   this alone separates H3.
3. Save the **rendered** HTML (`page.content()`) to a file.
4. **Enumerate every `<script>` tag** on the page: index, `type`, `id`, any
   `data-*` attributes, and the first ~120 characters of its text. Also save
   the **raw HTTP** response body (plain `urllib`/`requests`, no browser) for
   comparison — server-rendered vs client-injected is a different question
   from which selector matches.
5. Grep both copies of the HTML, case-insensitively, for `confirmation` and
   print surrounding context.
6. **Reproduce the negative**: call `_greenhouse_confirmation_data(page)` on
   the loaded page and print the result. It must still print
   `confirmation_path: None`.
7. **Run the decisive experiment**: take the *same* page and run the same
   `find_values` recursion over the text of **every** `<script>` tag (not just
   the three covered selectors), plus over any `data-*` attribute values that
   parse as JSON. If a widened search finds the values on the same page where
   the narrow one did not, **H2 is confirmed** — and the exact winning location
   is the fix.

Print raw output. Save the HTML evidence somewhere recoverable.

### STOP 1

Before changing `_greenhouse_confirmation_data`, stop and report:

- which hypothesis the evidence supports, with the raw output pasted;
- if H2: the exact script/attribute that holds the values, and the proposed
  selector change;
- if H3: the measured time at which the values appeared.

A widened selector must be justified as **reading the real metadata** — same
keys, same values, correct for the posting. "The test went green" is not
justification.

---

## PART 2 — act on the verdict

### If H2 or H3 (fixable)

- Widen the selector / fix the timing in `agents/auto_applier.py`.
- Commit a **trimmed HTML fixture** (the relevant `<script>` block, not the
  whole page) under `tests/fixtures/` and add a test that parses it and asserts
  the metadata is extracted. The test must fail against the old selector.
- `submit_recon.py` calls the same function, so recon should now report the
  metadata too. Re-run it and confirm — but note recon's verdict is advisory
  (`tools/submit_recon.py` says so explicitly); it says whether a run is worth
  arranging, never whether one is safe.
- Re-check the other blockers recon listed (`submit_button_found`, unhandled
  required fields). Captcha presence is **expected and recorded, never a gate,
  never bypassed**.

### If H1 (genuinely absent)

**Do not invent a workaround.** Do not fabricate confirmation copy. Do not
hardcode a confirmation path. Do not weaken the verification protocol to make
the path testable. Stop and report; the choice between (a) accepting
fill-and-review as the permanent terminal state and (b) redefining verification
to depend on something other than pre-scraped metadata is the operator's
decision, not the agent's.

---

## Hard rules

- **No `.click()` on any submit control, ever.** This task cannot submit
  anything. If the agent believes a click is needed, it has misunderstood the
  task: stop and report instead.
- **Never bypass, solve, or evade a captcha.** reCAPTCHA's presence is a
  finding to record, not an obstacle to defeat. This is already the project's
  position (`LIVE_SUBMIT.md` §5) and it does not change.
- **Never edit `api/safety.py`.** `SUBMIT_ENABLED = False` stays `False` in git
  at all times. Arming is environment-only, and arming is **out of scope here**.
- **Never weaken or delete a test to make it pass.** In particular
  `tests/test_submit_recon.py::test_recon_module_contains_no_click_or_fill_calls`
  asserts recon contains no `.click(`/`.fill(`/`.set_input_files(`/`.type(`
  call. It must keep passing **as written** — if the probe needs to be exempt,
  it goes in a separate module, not by narrowing that test.
- **No force-push.** Push only the assigned branch.
- **Report raw output, including failures.** Do not summarise an error away.
- **Do not commit generated artifacts** (`apply_packages/`, `resumes/`,
  `cover_letters/`, `screenshots/`, `cache/`) or full-page HTML dumps — the
  trimmed fixture is the exception.
- **Keep CI green.** `python -m pytest tests/`, `./tests/e2e/run.sh`, and the
  lock-drift check must all pass. If `requirements.txt` changes, regenerate
  with `uv pip compile requirements.txt -o requirements.lock.txt --universal`
  and commit both.

## Explicitly out of scope

- The armed live submit run, in any form. It requires the operator's own
  machine, a human at the screenshot gate, and a separate decision. Part A of
  `CODEX_TASK.md` is still operator-held and remains so after this task.
- Any real application to any employer.
- Enabling the dashboard Auto-Submit toggle. Fixing a scraper bug makes the
  path **testable**; it does not make it **unlocked**, and those are different
  decisions.
- Changing the verification protocol itself.
- Making recon report `clear`. That is not the goal and would be evidence of
  the opposite if achieved by weakening a check.

## Report format

1. Which hypothesis (H1/H2/H3) and the raw evidence that decided it.
2. The exact command(s) run and their raw output.
3. What changed (files, and why each change is correct rather than merely
   green).
4. Test results before and after, verbatim.
5. What is still unknown, stated plainly.

## Context

- Target: `https://job-boards.greenhouse.io/example/jobs/83446` — Greenhouse's
  **own public demo board**. Democorp "Full Stack Engineer", fingerprint
  `94bcd024022152dc3d0d3280d778c1dd`. Not a real employer, not a real vacancy,
  nobody's inbox. This is the only safe rehearsal target known.
- Relevant code: `agents/auto_applier.py` (`_greenhouse_confirmation_data`,
  `_fill_greenhouse_form`), `api/apply.py` (`create_greenhouse_intent` 502 gate
  at ~line 615, `_run_greenhouse_submit`), `api/apply_verification.py`
  (`verify_greenhouse_confirmation`), `tools/submit_recon.py`.
- The failure this guards against, from `LIVE_SUBMIT.md`: the metadata is
  scraped from the **pre**-submit page and then asserted against the
  **post**-submit page. If that assumption is wrong, Greenhouse accepts the
  application while `verified=False`, the claim finalizes as
  `submit_unverified`, and the API returns 422 — **submitted, recorded as
  failed.** That assumption has never been checked, which is what the live run
  exists to test.
