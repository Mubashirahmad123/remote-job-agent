# LIVE_SUBMIT.md — supervised live submit runbook

The one thing 379 passing tests cannot prove: that a real click on a real
Greenhouse form produces a real, verifiable submission. This runbook is how
that gets proven, once, under supervision.

**Target: Greenhouse's own public demo board.**
`https://job-boards.greenhouse.io/example/jobs/83446` — "Full Stack
Engineer" at Democorp. Not a real employer, not a real vacancy, nobody's
inbox. It is served by the same `job-boards.greenhouse.io` infrastructure
that hosts real postings, so the DOM, the embedded confirmation metadata and
the submit control are the real thing.

**This runbook is executed by the operator, on the operator's machine.** The
build sandbox has no browser binary and no network egress to job boards, so
Playwright cannot run there — every step below needs a real desktop.

---

## 0. Known facts about the target (verified 2026-10-03)

Read these before planning the run; two of them change what a "pass" means.

| Fact | Consequence |
|---|---|
| Required fields are **First Name, Last Name, Email** only | `_fill_greenhouse_form` already handles all three. No unhandled required questions — the most common cause of a post-click validation failure is absent here. |
| Optional: Phone, Resume/CV, Cover Letter, LinkedIn, Website, "How did you hear about this job?" | Resume + cover letter still get attached and still pass the attachment gate. |
| **The form is reCAPTCHA-protected** ("protected by reCAPTCHA" next to *Submit application*) | ⚠️ The headline risk. An automated click may be scored and blocked. See §5. |
| The page is Greenhouse-hosted, not an iframe embed | `_greenhouse_confirmation_data` has a real chance of finding the embedded JSON — but this is unverified until step 1. |

### What a live run is actually testing

1. Does `_greenhouse_confirmation_data` find `confirmation_path` +
   `confirmation_message` on a real page? (If not, `/intent` returns 502 and
   nothing else can happen.)
2. Does the post-submit page actually match those values? This is the
   **assumption nobody has ever checked**: the metadata is scraped from the
   *pre*-submit page and then asserted against the *post*-submit page. If it
   is wrong, the result is a **false negative** — Greenhouse accepts the
   application, `verified=False`, the claim finalizes as `submit_unverified`,
   and the API returns 422. Submitted, recorded as failed.
3. Does reCAPTCHA let an automated submission through at all?

---

## 1. Dry run first — zero consequences

Two independent rehearsals exist. Run both.

### 1a. Recon scan (seconds, no pipeline state needed)

```powershell
venv\Scripts\python.exe -m tools.submit_recon `
  https://job-boards.greenhouse.io/example/jobs/83446 `
  --json recon-democorp.json
```

Read-only — the tool contains no `.click()`, `.fill()` or
`.set_input_files()` call, and a test asserts it never grows one. It reports
confirmation metadata, required fields, unhandled required fields, captcha
presence, and a verdict.

**Stop here if `confirmation_metadata_found` is false.** `/intent` will 502
and there is nothing to test. That finding alone justifies the recon step.

### 1b. Full-path dry run (real browser, real fill, stops before the click)

Seed the posting into the pipeline, then rehearse the whole thing:

```powershell
venv\Scripts\python.exe -m tools.seed_demo_job
# -> fingerprint: 94bcd024022152dc3d0d3280d778c1dd

$env:APPLY_API_TOKEN = "<generate a long random string>"
$env:SUBMIT_ENABLED  = "true"
$env:SUBMIT_DRY_RUN  = "true"     # <- the click cannot happen
$env:SUBMIT_HEADLESS = "false"    # watch it
venv\Scripts\python.exe -m uvicorn api.app:app --host 127.0.0.1 --port 8000 --workers 1
```

Then fill/review → intent → submit, exactly as a real run would (see §3 for
the calls). The response comes back `status: "dry_run"`, `would_click: true`
— and **nothing was clicked, no intent consumed, no claim taken, no daily
cap spent**. Repeat it as often as you like.

Dry run still enforces every gate a real submit enforces (fingerprint echo,
typed title, score, field readback, attachment proof, confirmation metadata
match). A rehearsal that skipped the gates would prove nothing.

---

## 2. Arm — and know what you changed

`SUBMIT_ENABLED` is a **module constant that stays `False` in git**
(`api/safety.py`). As of this change it can also be armed by environment
variable for a single process, so arming never requires editing tracked
code and can never be accidentally committed.

> Historical note: before this change, `SUBMIT_ENABLED=true` in `.env` did
> **nothing** — the constant was read directly and the env was never
> consulted. A live run planned around setting it in `.env` would have hit a
> 403 and looked like a bug in the gate.

```powershell
$env:SUBMIT_ENABLED = "true"
Remove-Item Env:\SUBMIT_DRY_RUN     # <- armed for real now
$env:SUBMIT_HEADLESS = "false"
```

`api.safety.submit_mode()` reports `disarmed` / `dry_run` / `armed`. Confirm
it says `armed` before proceeding, and nothing else.

`SUBMIT_DRY_RUN` alone can never open the path — it is a modifier on an
already-armed switch, not a second door. There is a test for that.

---

## 3. The run

```powershell
$FP = "94bcd024022152dc3d0d3280d778c1dd"
$H  = @{ Authorization = "Bearer $env:APPLY_API_TOKEN" }

# 3.1 fill + review (real tailored resume + cover letter, real screenshot)
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/apply/$FP" `
  -Headers @{ Authorization = "Bearer $env:API_TOKEN" } `
  -ContentType "application/json" -Body '{"mode":"review"}'
```

### 🛑 STOP — operator review gate

Open the screenshot before anything else happens:

```
http://127.0.0.1:8000/api/apply/94bcd024022152dc3d0d3280d778c1dd/screenshot
```

Check with your own eyes: correct name and email, resume attached, cover
letter present, correct posting. **Nothing proceeds without your explicit
go-ahead.** This gate is the point of the whole exercise — the system is
designed so a human sees the filled form before any click exists as a
possibility.

```powershell
# 3.2 intent (one-use token, dedicated APPLY_API_TOKEN)
$intent = Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/api/apply/$FP/intent" `
  -Headers $H -ContentType "application/json" -Body '{"mode":"review"}'

# 3.3 submit — typed title must match exactly
$body = @{
  confirm         = $true
  job_fingerprint = $FP
  intent_token    = $intent.intent_token
  typed_title     = "Full Stack Engineer"
} | ConvertTo-Json

Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/apply/$FP/submit" `
  -Headers $H -ContentType "application/json" -Body $body
```

---

## 4. Disarm immediately

```powershell
Remove-Item Env:\SUBMIT_ENABLED
Remove-Item Env:\SUBMIT_DRY_RUN
# restart the API, then confirm:
#   api.safety.submit_mode() == "disarmed"
```

`api/safety.py` is unchanged in git throughout — `SUBMIT_ENABLED = False`
before and after. This is a one-time supervised test, not a standing-open
path.

---

## 5. Read the outcome honestly

Every run writes an evidence directory: `data/submit_runs/<timestamp>-<fp>/`
containing `trace.zip`, `video/`, `network.har`, `post_click.html`,
`post_click.txt`, `post_click.png`, and `attempt.json`. The post-click DOM is
captured **before** verification is judged, precisely so a failure can be
diagnosed rather than guessed at.

| API result | What happened | What to do |
|---|---|---|
| `200 status=submitted` | Clicked, and the real confirmation page matched the predicted path + message. **The verification assumption is validated.** | Save `post_click.html` as a test fixture. |
| `422 "could not be verified"` + `post_click.html` shows a confirmation page | **False negative.** Greenhouse took it; our expected copy was wrong. | Fix `verify_greenhouse_confirmation` against the captured copy. This is the bug the live run exists to find. |
| `422` + `post_click.html` shows the form with inline errors | A required field we did not fill, or **reCAPTCHA blocked it**. | Check the HAR for a captcha verification response. If reCAPTCHA is the blocker, see below. |
| `502` before any click | A gate fired pre-click. Cheapest outcome — nothing was sent. | Read `attempt.json`, fix, rerun dry run for free. |

### If reCAPTCHA blocks the submission

That is a **legitimate and important result**, not a failure of the project.
It would mean Greenhouse boards are not reliably automatable at the final
click, and the honest conclusion is that fill-and-review (where a human
clicks submit) is the correct terminal state — which is exactly how the
system is built today. Record it in `CHANGELOG.md` and `PM.md` and stop. Do
not attempt captcha evasion: it is against Greenhouse's terms, it is
fragile, and it would make every subsequent application legally and
ethically questionable.

---

## 6. One run proves one posting

A pass on the Democorp demo board proves the mechanism works on
`job-boards.greenhouse.io`. It does **not** prove embedded iframe boards or
custom-domain boards. Before any doc claims "the submit path is verified",
expect N=3 across different board types. Until then, say what was actually
tested: *the demo board, once, under supervision.*

Lever remains deferred — no trial account, documented skip.

---

## Run log

### 2026-10-03 — Democorp recon only (blocked)

- **Target:** Greenhouse public demo board, Full Stack Engineer, Democorp
  (`https://job-boards.greenhouse.io/example/jobs/83446`).
- **Mode reached:** read-only recon; neither `dry_run` nor `armed` was reached.
- **Outcome:** `confirmation_metadata_found` was `false`: both
  `confirmation_path` and `confirmation_message` were absent. The intended
  `/intent` call would therefore fail closed with 502 before any fill or
  click. reCAPTCHA was also detected. First Name, Last Name, and Email were
  the only required fields and none were unhandled.
- **Submission:** none. No fields were filled, files attached, or submit
  controls clicked.
- **Evidence:** `recon-democorp.json`; no `data/submit_runs/` evidence
  directory exists because the browser submission path was never entered.
