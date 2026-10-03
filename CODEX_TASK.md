# Task brief for Codex — live submit test (run in order, stop where told)

You are working in the `remote-job-agent` repo on branch
`arena/01a10070-remote-job-agent`. A real browser is required; everything
here needs Playwright + Chromium.

**Hard rules:**
- Do **not** skip ahead. There are two STOP points. Stop at them.
- Do **not** attempt to bypass, solve, or evade any captcha.
- Do **not** edit `api/safety.py`. Arming is done with environment
  variables only.
- Report raw output. Do not summarise away errors.

---

## Step 0 — setup

```bash
git checkout arena/01a10070-remote-job-agent
git pull
pip install playwright
playwright install chromium
```

---

## Step 1 — recon scan (read-only, no clicking)

```bash
python -m tools.submit_recon \
  https://job-boards.greenhouse.io/example/jobs/83446 \
  --json recon-democorp.json
```

This only reads the page. It reports:
- `confirmation_metadata_found` — whether the data the verification step
  depends on exists on the page
- `required_fields` / `unhandled_required_fields`
- `captcha`
- `submit_button_found`

### 🛑 STOP 1 — report the full output and `recon-democorp.json`, then wait.

**If `confirmation_metadata_found` is `false`, stop permanently.** The
intent endpoint will return 502 and a live submit is impossible. That is a
valid, useful result — report it and stop.

---

## Step 2 — dry run (real browser, real fill, cannot click)

Only after Step 1 comes back clear.

```bash
python -m tools.seed_demo_job
# prints fingerprint: 94bcd024022152dc3d0d3280d778c1dd

export APPLY_API_TOKEN="$(python -c 'import secrets;print(secrets.token_urlsafe(32))')"
export API_TOKEN="$APPLY_API_TOKEN"
export SUBMIT_ENABLED=true
export SUBMIT_DRY_RUN=true      # the click is unreachable in this mode
export SUBMIT_HEADLESS=false    # watch the browser
export PYTHONPATH=.

python -m uvicorn api.app:app --host 127.0.0.1 --port 8000 --workers 1
```

In a second terminal (reuse the same `APPLY_API_TOKEN` value):

```bash
FP=94bcd024022152dc3d0d3280d778c1dd

# 2a. fill + review — real tailored resume + cover letter, real screenshot
curl -s -X POST "http://127.0.0.1:8000/api/apply/$FP" \
  -H "Authorization: Bearer $API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"mode":"review"}' | python -m json.tool

# 2b. intent
curl -s -X POST "http://127.0.0.1:8000/api/apply/$FP/intent" \
  -H "Authorization: Bearer $APPLY_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"mode":"review"}' | python -m json.tool

# 2c. dry-run submit — returns status "dry_run", clicks nothing
curl -s -X POST "http://127.0.0.1:8000/api/apply/$FP/submit" \
  -H "Authorization: Bearer $APPLY_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"confirm\":true,\"job_fingerprint\":\"$FP\",\"intent_token\":\"<TOKEN FROM 2b>\",\"typed_title\":\"Full Stack Engineer\"}" \
  | python -m json.tool
```

Expected: `"status": "dry_run"`, `"would_click": true`, and **no
submission**. No intent is consumed and no claim is taken, so this is
repeatable.

Also fetch the review screenshot and save it:

```bash
curl -s "http://127.0.0.1:8000/api/apply/$FP/screenshot" \
  -H "Authorization: Bearer $API_TOKEN" -o review-screenshot.png
```

### 🛑 STOP 2 — report all three JSON responses, `review-screenshot.png`, and the contents of the newest `data/submit_runs/*/attempt.json`. Then wait for explicit human approval.

Do not arm the real submit on your own judgment.

---

## Step 3 — armed run (ONLY after a human says go)

```bash
unset SUBMIT_DRY_RUN     # now armed
# restart the API, then repeat 2a -> 2b -> 2c
```

Immediately afterwards:

```bash
unset SUBMIT_ENABLED
# restart the API
```

Report the final JSON plus the full contents of the newest
`data/submit_runs/<timestamp>-<fp>/` directory — especially
`post_click.html`, `post_click.txt` and `attempt.json`.

**Expect any of these, and report honestly which one happened:**

| Result | Meaning |
|---|---|
| `status: submitted` | Clicked and verified against the real confirmation page. |
| `422` + post_click shows a confirmation page | False negative — Greenhouse accepted it, the expected copy was wrong. Report the actual copy. |
| `422` + post_click shows the form with errors | A required field or **reCAPTCHA** blocked it. |
| `502` before click | A safety gate fired. Nothing was sent. |

A reCAPTCHA block is a legitimate result. Report it and stop — do not try
to work around it.

---

## Context you need

- Target is Greenhouse's own public **demo** board (Democorp, job 83446).
  Not a real employer, not a real vacancy. Nobody receives this application.
- The form's required fields are First Name, Last Name, Email — all already
  handled by the filler.
- The form is reCAPTCHA-protected. This may block Step 3 entirely.
- Full background: `LIVE_SUBMIT.md` in this repo.
