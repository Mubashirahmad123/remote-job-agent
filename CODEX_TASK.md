# Task brief for Codex

Two jobs, **in this order**:

- **Part A** — run the supervised live submit test (needs a real browser).
- **Part B** — record what was found, then merge the branch into `main`.

Order matters. Part A may uncover a real bug; if it does, the fix goes in
*before* the merge, not after.

Repo: `remote-job-agent`. Branch: `arena/01a10070-remote-job-agent`
(10 commits ahead of `main`, no conflicts, no CI configured).

**Hard rules for the whole task:**
- There are **three STOP points**. Stop at each one and wait for a human.
  Do not use your own judgment to continue past them.
- Never bypass, solve, or evade a captcha.
- Never edit `api/safety.py`. Arming is done with environment variables
  only, so `SUBMIT_ENABLED = False` stays in git at all times.
- Never force-push. Never push to any branch other than
  `arena/01a10070-remote-job-agent`.
- Report raw output, including failures. Do not summarise errors away.

---

# PART A — live submit test

## A0. Setup

```bash
git checkout arena/01a10070-remote-job-agent
git pull
pip install playwright
playwright install chromium
```

> If `pip install -r requirements.txt` fails with a `crewai` dependency
> resolution error, that is a known pre-existing issue and is unrelated to
> this task. The API and tests only need: `fastapi uvicorn pytest httpx
> python-dotenv gspread google-auth pydantic python-dateutil requests
> beautifulsoup4 feedparser pandas openpyxl`.

Confirm the suite is green before touching anything:

```bash
python -m pytest tests/ -q          # expect: 379 passed, 1 skipped
./tests/e2e/run.sh                  # expect: 19 passed
```

## A1. Recon scan — read-only, nothing is clicked

Target is Greenhouse's **own public demo board**: Democorp, "Full Stack
Engineer", job 83446. Not a real employer, not a real vacancy, nobody
receives this application.

```bash
python -m tools.submit_recon \
  https://job-boards.greenhouse.io/example/jobs/83446 \
  --json recon-democorp.json
```

Reports: `confirmation_metadata_found`, `required_fields`,
`unhandled_required_fields`, `captcha`, `submit_button_found`, `verdict`.

### 🛑 STOP 1 — post the full console output and `recon-democorp.json`. Wait.

**If `confirmation_metadata_found` is `false`: stop Part A permanently.**
The intent endpoint will return 502 and a live submit is impossible. That
is a valid and useful result. Skip to Part B and record it there.

## A2. Dry run — real browser, real fill, the click is unreachable

```bash
python -m tools.seed_demo_job
# prints fingerprint: 94bcd024022152dc3d0d3280d778c1dd

export APPLY_API_TOKEN="$(python -c 'import secrets;print(secrets.token_urlsafe(32))')"
export API_TOKEN="$APPLY_API_TOKEN"
export SUBMIT_ENABLED=true
export SUBMIT_DRY_RUN=true      # dry run: the click cannot be reached
export SUBMIT_HEADLESS=false    # watch the browser work
export PYTHONPATH=.

python -m uvicorn api.app:app --host 127.0.0.1 --port 8000 --workers 1
```

Second terminal, same token values:

```bash
FP=94bcd024022152dc3d0d3280d778c1dd

# A2a — fill + review: real tailored resume, real cover letter, real screenshot
curl -s -X POST "http://127.0.0.1:8000/api/apply/$FP" \
  -H "Authorization: Bearer $API_TOKEN" -H "Content-Type: application/json" \
  -d '{"mode":"review"}' | python -m json.tool

# A2b — intent (one-use token)
curl -s -X POST "http://127.0.0.1:8000/api/apply/$FP/intent" \
  -H "Authorization: Bearer $APPLY_API_TOKEN" -H "Content-Type: application/json" \
  -d '{"mode":"review"}' | python -m json.tool

# A2c — dry-run submit: returns "dry_run", submits nothing
curl -s -X POST "http://127.0.0.1:8000/api/apply/$FP/submit" \
  -H "Authorization: Bearer $APPLY_API_TOKEN" -H "Content-Type: application/json" \
  -d "{\"confirm\":true,\"job_fingerprint\":\"$FP\",\"intent_token\":\"<TOKEN FROM A2b>\",\"typed_title\":\"Full Stack Engineer\"}" \
  | python -m json.tool

# A2d — save the review screenshot for human inspection
curl -s "http://127.0.0.1:8000/api/apply/$FP/screenshot" \
  -H "Authorization: Bearer $API_TOKEN" -o review-screenshot.png
```

Expected: `"status": "dry_run"`, `"would_click": true`. No intent is
consumed and no claim is taken, so this is safely repeatable.

### 🛑 STOP 2 — post all three JSON responses, attach `review-screenshot.png`, and paste the newest `data/submit_runs/*/attempt.json`. Wait for an explicit human "go".

The human is checking the screenshot: right name, right email, resume
attached, cover letter present, right posting. Do not arm anything until
they say so.

## A3. Armed run — only after a human approves

```bash
unset SUBMIT_DRY_RUN      # now armed for real
# restart the API, then repeat A2a -> A2b -> A2c
```

Immediately after, disarm:

```bash
unset SUBMIT_ENABLED
unset SUBMIT_DRY_RUN
# restart the API
python -c "from api import safety; print(safety.submit_mode())"   # must print: disarmed
```

Then collect the evidence directory
`data/submit_runs/<newest-timestamp>-<fp>/` — `attempt.json`,
`post_click.html`, `post_click.txt`, `post_click.png`, `trace.zip`.

Classify the outcome honestly:

| Result | Meaning |
|---|---|
| `200 status=submitted` | Clicked and verified against the real confirmation page. The verification assumption is proven. |
| `422` + `post_click.html` shows a confirmation page | **False negative.** Greenhouse accepted it; our expected copy was wrong. Report the actual copy found. |
| `422` + `post_click.html` shows the form with inline errors | A required field, or **reCAPTCHA**, blocked it. Check `network.har`. |
| `502` before any click | A safety gate fired. Nothing was sent. Report which gate. |

A reCAPTCHA block is a **legitimate result**, not a failure of the project.
Report it and stop. If that happens, the correct conclusion is that
fill-and-review with a human clicking submit is the right terminal state —
which is how the system already works.

---

# PART B — record findings, then merge to `main`

## B1. Write down what actually happened

Update these files with the real outcome — not an optimistic reading of it:

- **`CHANGELOG.md`** — new dated entry at the top: what was run, against
  what, and the exact result. If nothing was submitted, say so plainly.
- **`PM.md`** — update the live-submit line in the status table and §3
  Backlog. If the submit path is still unproven, it must still say so.
- **`LIVE_SUBMIT.md`** — add a "Run log" section at the bottom: date,
  target, mode reached (`dry_run` / `armed`), outcome, and the evidence
  directory name.
- **`PRODUCTION.md` §8** — if anything about the three-state switch behaved
  differently from what is documented there, correct it.

**Accuracy rules.** Do not write that the submit path is "verified" unless
a real submission was confirmed received. One run on the demo board proves
the demo board only — not embedded iframe boards, not custom-domain boards.
Say exactly what was tested.

If Part A found a bug (most likely: wrong expected confirmation copy), fix
it and add a regression test using the **captured real** `post_click.html`
as the fixture — not a hand-written one.

## B2. Clean up before merging

```bash
# remove the local demo scaffolding row — it must not reach main
git checkout -- scraped_jobs.json 2>/dev/null || true
rm -f recon-democorp.json review-screenshot.png

git status --porcelain      # evidence dirs are gitignored; nothing stray should appear
```

Verify these are true:

```bash
grep -n "SUBMIT_ENABLED = False" api/safety.py     # must still be False
python -m pytest tests/ -q                         # 379 passed, 1 skipped (or more, if you added tests)
./tests/e2e/run.sh                                 # 19 passed
```

### 🛑 STOP 3 — post the test results, `git status`, and the diff of your doc changes. Wait for approval to merge.

## B3. Merge

Only after approval. Commit and push to the session branch — **never** any
other branch:

```bash
git add -A
git commit -m "docs: record live submit test outcome on Greenhouse demo board"
git push origin arena/01a10070-remote-job-agent
```

Open the PR:

```bash
gh pr create --base main --head arena/01a10070-remote-job-agent \
  --title "Skills aggregate, frontend E2E, source canonicalization, submit dry-run + live test" \
  --body "See CHANGELOG.md. Includes: /api/skills aggregate and real-text fix, phantom mock layer removal, frontend E2E smoke suite (19 assertions), by_source canonicalization, Phase 2.1 planning docs, three-state submit kill switch with dry-run rehearsal, recon tooling, and the live submit test outcome. SUBMIT_ENABLED remains False."
```

Then merge it:

```bash
gh pr merge --merge        # ask the human first if they prefer squash
```

Confirm afterwards:

```bash
git fetch origin main
git log --oneline origin/main -3
grep -n "SUBMIT_ENABLED = False" api/safety.py
```

---

## Background you need

- The target is Greenhouse's **own demo board** — no real employer involved.
- Its required fields are First Name, Last Name, Email, all already handled
  by `_fill_greenhouse_form`.
- The form **is reCAPTCHA-protected**. A3 may be blocked. That is fine.
- The submit switch is three-state: `disarmed` / `dry_run` / `armed`, via
  `api.safety.submit_mode()`. Dry run runs the entire real path and stops
  before `.click()`, without consuming the intent or taking the claim.
- Full detail: `LIVE_SUBMIT.md`. Architecture: `ARCHITECTURE.md`.
  Ops: `PRODUCTION.md`.
