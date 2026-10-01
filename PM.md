# PM.md — Project Tracker (Phases, Status, Next)

Living plan for the remote-job-agent build. Status last reconciled 2026-10-01.

---

## 1. Status (2026-09-29)

| Phase | Scope | State |
|---|---|---|
| 0 — Pipeline | 45+ scrapers, curator, Sheets dashboard, tracker CLI, Docker | ✅ done (pre-existing) |
| 1 — Read API | `api/` factory+deps+cache+schemas+mappers+5 routers, 18 isolated tests | ✅ done, verified live (12 Sheet rows) |
| 1b — API split | monolith `app.py` → `deps/mappers/routers/*`, static UI mount | ✅ done, 18/18 green |
| 1c — Frontend wiring | `api.js` client, `store` normalization+fallback, jobDesk/dashboard/tracker/drawer live, source badges | ✅ done, verified via TestClient |
| 1d — Data honesty | snapshot fallback, `data_source`, cp1252 emoji-crash fix in `sheet_writer.py` | ✅ done, live Sheets confirmed |
| 1e — Docs | README API section, PRODUCTION/ARCHITECTURE/BACKEND/FRONTEND/PM | ✅ done |
| 2 — Action API | scrape ✅ + status card; resume/cover-letter ✅ (Studio wired); CV profile GET+PUT ✅ + variants ✅; fill-and-review API ✅; cockpit queue connected | 🟡 in progress — submit remains gated; skills endpoint pending |
| 3 — Polish | auto-apply telemetry wiring, E2E checks | 🟡 in progress — tracker review mapping done |

Full suite last verified 2026-10-01: **291 passed, 1 skipped** (`venv\Scripts\python.exe -m pytest tests/ -q`). The skip is the Lever exact confirmation-copy assertion, now a deliberate documented limitation (Lever submit deferred — no paid trial account; see 2b split below), not a temporary blocker. Scrape-log fixes landed the same day (curator sign format, Arbeitnow `company_name` backfill, single-loop poll guard, `scraped_at` warning ordering); details in `CHANGELOG.md` and `PRODUCTION.md` §7. Claim, intent, validation, and Greenhouse verification helpers are implemented; Greenhouse `/intent` + `/submit` routes exist, are kill-switch gated (403 while `SUBMIT_ENABLED=False`), and are tested. Lever has no submit path by design.

## 2. Next: Phase 2 — Action API (spec)

Goal: dashboard buttons do real work, behind the existing safety gates.

| Endpoint | Backend | Frontend | Safety |
|---|---|---|---|
| `POST /api/scrape` `{boards?, limit?}` | background run registry (no multi-scrape overlap), writes via curator → Sheets, `POST /api/jobs/refresh` after | `btnScrapeNow` → progress → refresh | ✅ done — cap boards/run, token required off-localhost |
| `POST /api/apply/{fp}` | Phase 2a fill-and-review: `mode:"review"` only (other modes → 400); dream tier → 422; `AUTO_APPLY_CONFIRM` ignored over HTTP. Greenhouse/Lever use a visible review browser with supported fields filled and pre-submit screenshot; unsupported ATSs get a package only. No submit click. | Cockpit fills up to 3 eligible jobs sequentially, leaves supported ATS windows open for manual review, and shows fill/package outcomes. Submit toggle stays disabled. | ✅ Fill-and-review API; 2b submit remains gated |
| `POST /api/resume/{fp}` | `resume_generator` 1-page tailor → serve PDF path/bytes | Resume Studio replaces static demo | ✅ done |
| `POST /api/cover-letter/{fp}` | `gemini_tools` role-aware letter → serve text/PDF | same package card | ✅ done |
| `PUT /api/cv/profile` | `cache.save_cv_profile` merges Studio edits into on-disk cache | profile Edit/Save panel | ✅ done |
| `GET /api/skills` | aggregate `tech_stack` over ALL JOBS | replaces `MOCK_SKILLS` cloud | ⬜ next |

Conventions (from BACKEND.md §6 / existing patterns): schema → `cache.py`
accessor (lazy imports, never crash) → `routers/<group>.py` → tests in
`tests/test_api_<group>.py` (fake `cache.*`, no live Sheets) → `js/api.js` fn →
README table row. Keep `app.py` thin; one router file per group.

### 2b submit gate — explicit rule (not informal)

A submit code path MUST NOT exist anywhere reachable over HTTP until **all
four** gates below are individually implemented and tested. There is no
partial unlock and no "three of four is enough" interpretation. The Auto-Submit
UI toggle remains `disabled`, the existing fill-only API rejects
`mode != "review"` with 400, and `api/safety.py: SUBMIT_ENABLED` remains
`False` until all four gates close.

1. **Verification protocol (2b split):** Greenhouse success requires the post-click URL
   to match the captured `confirmationPath` and the visible page message to
   match the captured `confirmation_message` (both read from public
   page-embedded JSON — no live observation was ever needed). A missing or
   failed verification after clicking is recorded as sticky
   `submit_unverified`, not as success or a retryable failure. Lever stays
   fill-only indefinitely: no Lever submit path exists, and a submit request
   for a Lever-sourced job returns the same 422 "not available for this ATS"
   response as Workday/Workable/Ashby/Breezy.
2. **Claim-first idempotency:** after all three request conditions pass, start
   `BEGIN IMMEDIATE` and insert a `submit_claims` row under the unique
   `job_fingerprint` before any browser work. A duplicate live claim rolls back
   and returns 409 with `retry_after`. A `submit_in_progress` claim older than
   N=15 minutes is lazily expired and its cap slot refunded inside the next
   claim transaction. Terminal states are `submitted` (verified),
   `submit_unverified` (sticky), and `failed_refunded` (pre-click failure only).
3. **Unconditional auth on the apply router:** both new routes require a valid
   Bearer token regardless of global `API_TOKEN` configuration or bind host.
   The manual PATCH reconciliation path for `submit_unverified` claims is
   protected by the same unconditional Bearer requirement.
4. **Triple-condition request gate:** every submit request must pass conditions
   (a), (b), and (c), in that order, in one server-side evaluation before any
   browser interaction. `AUTO_APPLY_CONFIRM` is not a substitute for any
   condition and cannot bypass them. The exact conditions are specified in §2b.3.

No gate is considered closed by documentation or a partial implementation:
each must have its §2b.7 tests passing before the endpoint code in execution
order step 4 is added. 2b has no target date.

### Current 2b execution status (2026-09-29)

| Step | State | Evidence / remaining work |
|---|---|---|
| 1. F1/F2 Lever fixes | ✅ Done | Posting-page resolution follows `a.show-page-apply` or the current `a.postings-btn[href]` anchor to a validated `/apply` URL; navigation uses `domcontentloaded` and waits for the form selector. Three real postings were fill-only tested with dummy details; all reached `/apply`, filled dummy fields, then exited for custom-question review. No submit click. Fill path unchanged by the 2b split. |
| 2. Lever confirmation observation | ➖ Deliberately out of scope | No Lever trial account will be purchased. Lever stays fill-only indefinitely (fill produces a real screenshot; no submit path). Exact-copy test is now `skip` with reason "Lever submit deferred — no live confirmation-text observation available without a paid account; revisit if a free path is found later". |
| 4. Submit endpoint code (Greenhouse only) | ✅ Done, hardened 2026-10-01 | `POST /api/apply/{fp}/intent` + `POST /api/apply/{fp}/submit` implemented in `api/routers/apply.py` → `api/apply.py:create_greenhouse_intent/submit_greenhouse` with Greenhouse URL+message verification (`verify_greenhouse_confirmation`). Intent REUSES the reviewed artifact's tailored resume + cover letter verbatim — it never regenerates materials and never rewrites the artifact, so reviewed == submitted by construction; missing/stale materials fail closed (502, no token). The submit refill reuses exactly those files, and submit fails closed (410) if the resume file is gone or cover text empty. A duplicate intent while one is live is rejected (409) before any expensive work via a read-only pre-check (`live_intent_retry_after`), so it can neither burn generation cost nor mutate the first token's artifact. Non-Greenhouse platforms raise 422 "Submit is not available for this ATS". `SUBMIT_ENABLED` remains `False`; cockpit Auto-Submit control remains disabled pending separate unlock decision. Intent requires the dedicated `APPLY_API_TOKEN` (`API_TOKEN` is never accepted); no live runs yet (held per operator decision). |

The Step 3 helper modules back the kill-switched submit pair. The dashboard
Auto-Apply Cockpit now uses visible Greenhouse/Lever review windows; each stays
open until its application tab closes (maximum 30 minutes), and the review fill
carries the final tailored materials. The legacy CLI blind submit is permanently
removed, so there is no unverified submit path left anywhere.

## 3. Backlog

- CV-upload-first flow (from operator notes): let the user upload their CV
  first, scrape/match on that basis, and have Resume Studio surface CV
  sections not yet added (projects, certifications).
- `POST /api/apply/{fp}/intent` and `/submit` are Greenhouse-only and implemented; Lever submit will not be built (fill-only indefinitely). UI toggle unlock stays a separate decision after review.
- **Field-drift guard gap (known limitation, not fixed):** `_run_greenhouse_submit` refills in a fresh page and the metadata-change guard compares only `confirmation_path/message` + requires `filled_ready`. The filler returns no per-field snapshot and the artifact stores none, so a same-shape posting change that keeps identical confirmation metadata and still fills cleanly would pass the guard. Narrowed 2026-09-29: attachments are no longer part of the gap — intent generates the tailored resume + cover letter and the submit refill reuses exactly those files (fail-closed if missing). Remaining gap is field-shape drift only. Accepted risk for supervised single runs with human screenshot review; unattended/high-volume submit use must wait for a field-snapshot diff fix. Any future toggle unlock carries this caveat.
- `GET /api/skills` aggregate → replace `MOCK_SKILLS` cloud.
- Kanban `review` column has no backend status — decide: map to `applied+notes`,
  add real status, or drop the column.
- `by_source` naming (`RemoteOK` vs `RemoteOKAPI`) — normalize at write or read.
- Multi-worker cache: in-process TTL means `--workers 1`; shared cache (Redis/file)
  if workers ever needed.
- Frontend E2E smoke (Playwright) against TestClient-seeded API.
- 2b submit stays kill-switched and the UI toggle stays disabled; submit is
  reachable only via the authenticated Greenhouse pair (Lever has no submit path).

## 4. Definition of Done (every phase)

1. `python -m pytest tests/` fully green.
2. `node --check` on touched frontend files.
3. Live check: `GET /api/health` + one real request per new endpoint.
4. Docs touched: README table (endpoints), plus BACKEND/FRONTEND/PM status.
5. No secrets committed; no generated artifacts committed (`apply_packages/`,
   `cover_letters/`, `resumes/`, `screenshots/`, `cache/`).

## 2b Submit Specification

### 0. Preconditions (must land before any 2b code)

- **F1:** the Lever filler resolves a posting URL to the real `/apply` page by
   following the posting's `a.show-page-apply` href before filling any fields.
- **F2:** navigation uses `wait_until="domcontentloaded"`, followed by an
   explicit wait for a known application-form selector. It must not rely on
   `networkidle`, which can remain pending because of third-party scripts.
- **Lever scope (deliberate):** Lever stays fill-only indefinitely — no trial
   account, no live observation, no submit path. The Lever filler (F1/F2)
   keeps working exactly as today. The exact-copy test is `skip`-flagged as
   a documented limitation, not a blocker.

### 1. Endpoints

- **`POST /api/apply/{fp}/intent`** is review-mode only and unconditionally
   Bearer-authenticated. It returns `{intent_token, expires_at}` only after the
   fill package and screenshot both exist for `{fp}`. Generate the opaque token
   with `secrets.token_urlsafe(32)`. Persist only its SHA-256 hash, together with
   the job fingerprint, `expires_at = now + 5 minutes`, and `consumed = false`.
   There may be only one unexpired intent for a fingerprint at a time; after it
   expires, a fresh intent may be issued for that fingerprint.
- **`POST /api/apply/{fp}/submit`** is unconditionally Bearer-authenticated
   and accepts `{confirm: true, job_fingerprint, intent_token, typed_title}`.
   Conditions §2b.3(a), (b), and (c) must all pass in one server-side
   evaluation, in that order, before any browser interaction. Any failure
   returns its specified status and leaves the browser untouched.

### 2. Claim-first idempotency

Only after §2b.3 passes, begin a `BEGIN IMMEDIATE` SQLite transaction and
insert `submit_claims(job_fingerprint, status='submit_in_progress',
claimed_at, intent_hash)`. `job_fingerprint` is unique. A UNIQUE violation
rolls back the transaction and returns 409 `{retry_after}`; it must not start
browser work. Next reserve a daily-cap slot as specified in §2b.4, then commit
the transaction, and only then begin browser work.

The terminal claim states are:

- `submitted`: ATS verification succeeded.
- `submit_unverified`: the click may have submitted, but success could not be
   verified. This state is sticky and consumes its daily-cap slot.
- `failed_refunded`: a failure occurred before the submit click, so the claim
   failed and its daily-cap slot was refunded.

A `submit_in_progress` claim older than N=15 minutes is lazily expired during
the next claim transaction. Expiry and its daily-cap refund occur in that same
transaction before the replacement claim is inserted.

### 3. Triple-condition request gate

All three conditions are mandatory on every submit request. Evaluate them
server-side in the listed order, in one evaluation, before any browser action.

- **(a) Explicit confirmation and fingerprint echo:** require
   `confirm === true` and exact equality between the body `job_fingerprint` and
   the path `{fp}`. A false/missing confirmation or fingerprint mismatch returns
   400. For every (a) rejection, log the actual ratio, expected value, and raw
   input as described in §2b.6 clarification 1.
- **(b) Intent token:** SHA-256 hash the submitted `intent_token` and compare it
   with the stored hash for this same fingerprint. The stored intent must be
   unconsumed and unexpired. A consumed token returns 409; a missing or expired
   intent returns 410. A token for another fingerprint must not authorize this
   request.
- **(c) Typed job-title confirmation:** compare the typed title against the
   cached job title after normalizing both strings: Unicode NFKD decomposition,
   remove combining marks, casefold, strip punctuation, and collapse
   whitespace. If the normalized expected title has fewer than 4 characters,
   require exact normalized equality. Otherwise accept only when the normalized
   input length is at least `max(4, ceil(len(expected) / 2))` **and**
   `difflib.SequenceMatcher` ratio between normalized input and expected title
   is at least `0.85`. A failed (c) check returns 422. For every (c) rejection,
   log the actual ratio, expected value, and raw input as described in
   §2b.6 clarification 1.

### 4. Daily cap

Reserve the daily-cap slot in the same `BEGIN IMMEDIATE` transaction as the
claim insert. If the current count is already `>=` the configured cap, roll
back the entire transaction, including the claim insert, and return 409 with
`retry_after`. Both `submitted` and `submit_unverified` consume the reserved
slot. Never refund an ambiguous outcome. Refund only `failed_refunded` claims
that failed before click, or stale `submit_in_progress` claims when they are
expired by a later claim transaction. If manual reconciliation determines
that a `submit_unverified` attempt actually failed, the slot is reconciled
through the authenticated manual-PATCH path in §2b.6 clarification 2.

### 5. Verification protocol

- **Greenhouse:** before clicking submit, capture `confirmationPath` and
   `confirmation_message`. After the click, assert that the URL matches the
   captured path and the confirmation message matches the captured message. On
   verified success, set claim status `submitted`; otherwise write sticky
   `submit_unverified`.
- **Lever:** fill-only, indefinitely. No `/submit` code path exists for
   Lever-tier jobs — a submit request for a Lever URL returns 422 "Submit is
   not available for this ATS", the same response as Workday/Workable/Ashby/
   Breezy. The `verify_lever_confirmation` selector/visibility helper remains
   for fill-path completeness only.
- **Dream tier:** always reject with 422; dream-tier jobs are never submitted.
- **Authentication:** Bearer auth is unconditional on both new routes,
   independent of `API_TOKEN` and bind host. The manual PATCH reconciliation
   path uses the same unconditional auth requirement.

### 6. Status codes

| Status | Meaning |
|---|---|
| 200 | Submission verified; claim is `submitted`. |
| 400 | Malformed request or confirmation/fingerprint echo mismatch. |
| 401 | Missing or invalid Bearer authentication. |
| 404 | Unknown job fingerprint. |
| 409 | Claim, active-intent, or daily-cap conflict; include `retry_after` where applicable. |
| 410 | Missing or expired intent. |
| 422 | Dream tier, typed-title rejection, or unverified terminal write. |
| 502 | ATS or verification infrastructure failure. |

### 7. Tests before ship (~35 tests)

All tests use boundary stubs (`FakePage`/`FakeLocator`), temporary SQLite
databases, and no network or real browser. They run before endpoint code is
added. The suite must include:

- Greenhouse and Lever fill matrices: happy path, custom-questions early exit,
   missing submit button, and form-selector timeout.
- Lever F1 regression: posting URL follows its apply anchor to `/apply` before
   waiting for the form or filling any field; direct `/apply` URLs do not need a
   second resolution.
- Greenhouse verification matrix: confirmation path plus message match
   succeeds; wrong/missing path or wrong/missing message fails.
- Lever verification matrix: `.confirmation-message` visible succeeds;
   absent/not-visible confirmation or error DOM fails. The exact success-copy
   assertion is explicitly TODO-flagged until the isolated Step 2 observation;
   it is not silently omitted or treated as passing.
- Claim-first ordering: the unique claim is inserted before any browser work;
   two concurrent claims for the same fingerprint have exactly one winner and
   one 409 conflict.
- Stale `submit_in_progress` claims older than 15 minutes expire lazily and
   refund their reserved slot in the same transaction. Claims at or below the
   15-minute boundary are still live.
- Daily cap: cap exhaustion rolls back both claim and counter; concurrent
   distinct claims cannot exceed the cap; `submitted` and `submit_unverified`
   consume a slot; only eligible pre-click failure and stale-claim expiration
   refund it; ambiguous outcomes do not.
- Every fill-path test asserts `click count == 0`, without exception.
- Set `AUTO_APPLY_CONFIRM=true` in the environment and prove that it changes
   nothing anywhere: the CLI ignores it (blind submit removed) and HTTP
   submit stays kill-switched until the unlock decision.
- Triple-condition tests cover strict boolean confirmation and exact
   fingerprint echo, token hash/fingerprint/consumed/expiry behavior, and typed
   title normalization, minimum-input-length, short-expected-title exact match,
   and the `difflib.SequenceMatcher` 0.85 boundary.
- Audit-log tests prove that every (a) and (c) rejection records actual ratio,
   expected value, and raw input, including requests that fail multiple checks.
- Intent tests prove only one unexpired intent exists per fingerprint, an
   expired intent can be replaced, and different fingerprints are independent.
- Dream-tier rejection is 422. Both new routes and manual-PATCH reconciliation
   require Bearer auth even when global `API_TOKEN` is unset and the server binds
   to localhost.
- Status-code tests cover 200, 400, 401, 404, 409 with `retry_after`, 410,
   422, and 502 outcomes, including that no browser work occurs before the
   triple-condition gate and claim transaction succeed.

The Lever exact confirmation-copy test remains `skip`-flagged as a deliberate
documented limitation (no paid account). All Greenhouse §2b tests must pass
— and do — before the UI toggle is reconsidered.

### Judgment Calls (approved as specced)

- **0.85 threshold**: submit is only permitted when the CV-match / good-fit score ≥ 0.85 (below this → 422, dream-tier manual-application only).
- **short-title equality**: the job title displayed on the ATS page must exactly match (case‑insensitive strip) the title stored in the cached job record; mismatch → rejection with ratio and expected value logged.
- **unverified-consumes-cap**: a `submit_unverified` attempt still consumes one daily‑cap slot; if the human PATCH later determines the claim failed, the slot is refunded only via the manual-PATCH reconciliation path.

### Three Clarifications (answered)

1. **Logging on (a)/(c) rejection:** record actual ratio, expected value, and
   raw input for every rejection, not merely the 422/400 status. If real usage
   later clusters near the 0.85 boundary, these records provide evidence to
   retune from.
2. **Manual-PATCH on `submit_unverified`:** the manual PATCH path is
   unconditionally Bearer-authenticated, the same as the submit route. If a
   human determines the attempt actually failed, this path reconciles/refunds
   the daily-cap slot. Do not refund an ambiguous outcome by another path.
3. **One live intent per fingerprint:** this means one **unexpired** intent at
   a time. A user can request a fresh token after the previous intent expires;
   this is not a hard lockout per fingerprint.

### Execution Order (strict, no shortcuts)

The 2b feature will be shipped in this exact order, with no shortcuts:

1. **F1/F2 Lever fixes** — done and verified with fill-only real-page checks; the current live apply anchor class is also supported. Unchanged by the split.
2. **Lever observation** — deliberately out of scope (no trial purchase). Skip-flagged, not blocking.
4. **Endpoint code (Greenhouse only)** — done: the two specified routes exist with full triple-gate + claim-first + verification. Keep the UI toggle disabled until the Greenhouse submit build is tested and reviewed — that unlock is a separate decision.

After all four close, the UI toggle becomes enabled and the submit opcode is reachable.
