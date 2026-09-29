# PM.md — Project Tracker (Phases, Status, Next)

Living plan for the remote-job-agent build. Update the Status section as phases land.

---

## 1. Status (2026-09-24)

| Phase | Scope | State |
|---|---|---|
| 0 — Pipeline | 45+ scrapers, curator, Sheets dashboard, tracker CLI, Docker | ✅ done (pre-existing) |
| 1 — Read API | `api/` factory+deps+cache+schemas+mappers+5 routers, 18 isolated tests | ✅ done, verified live (12 Sheet rows) |
| 1b — API split | monolith `app.py` → `deps/mappers/routers/*`, static UI mount | ✅ done, 18/18 green |
| 1c — Frontend wiring | `api.js` client, `store` normalization+fallback, jobDesk/dashboard/tracker/drawer live, source badges | ✅ done, verified via TestClient |
| 1d — Data honesty | snapshot fallback, `data_source`, cp1252 emoji-crash fix in `sheet_writer.py` | ✅ done, live Sheets confirmed |
| 1e — Docs | README API section, PRODUCTION/ARCHITECTURE/BACKEND/FRONTEND/PM | ✅ done |
| 2 — Action API | scrape ✅ + status card; resume/cover-letter ✅ (Studio wired); CV profile GET+PUT ✅ + variants ✅ (panels live, edit mode); dynamic demo preview ✅, skills-edit sizing ✅ | 🟡 in progress — left: apply endpoint, skills endpoint |
| 3 — Polish | tracker `review` mapping, auto-apply telemetry wiring, E2E checks | ⬜ backlog |

Full suite: **154 passed** (`venv\Scripts\python.exe -m pytest tests/ -q`).

## 2. Next: Phase 2 — Action API (spec)

Goal: dashboard buttons do real work, behind the existing safety gates.

| Endpoint | Backend | Frontend | Safety |
|---|---|---|---|
| `POST /api/scrape` `{boards?, limit?}` | background run registry (no multi-scrape overlap), writes via curator → Sheets, `POST /api/jobs/refresh` after | `btnScrapeNow` → progress → refresh | ✅ done — cap boards/run, token required off-localhost |
| `POST /api/apply/{fp}` | Phase 2a fill-only: `mode:"review"` only (any other mode → 400); dream tier → 422; `AUTO_APPLY_CONFIRM` ignored over HTTP — no submit opcode reachable (see `api/safety.py`) | cockpit queue + package path + terminal log | ✅ 2a done — fill-only; 2b submit stays gated (verification + claim-first idempotency + auth + triple-gate), no target date |
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
four** of these are individually shipped **and** tested — no partial unlock,
no subset, no "three of four is enough":

1. **Verification protocol** — post-submit success/failure detection per ATS
   (Greenhouse `confirmationPath` + message assert; Lever
   `.confirmation-message` visibility), `submit_unverified` sticky status.
2. **Claim-first idempotency** — `INSERT` under `UNIQUE(job_fingerprint)`
   before any browser work; concurrent second claim → 409; stale claim (>N
   min, N=15 per measured fill times) → retryable with `retry_after`.
3. **Unconditional auth on the apply router** — Bearer required on that
   router regardless of global `API_TOKEN` state.
4. **Triple-condition gate** — three independent confirmations must all hold
   on every submit request (see proposal below; env flag alone is not one).

Until then: UI toggle stays `disabled`, API rejects `mode != "review"` with
400, `api/safety.py: SUBMIT_ENABLED=False`. 2b has no target date.

## 3. Backlog

- `POST /api/apply/{fp}` 2b submit stays gated (verification + claim-first idempotency + auth + triple-gate) — no submit path until all four close.
- `GET /api/skills` aggregate → replace `MOCK_SKILLS` cloud.
- Kanban `review` column has no backend status — decide: map to `applied+notes`,
  add real status, or drop the column.
- `by_source` naming (`RemoteOK` vs `RemoteOKAPI`) — normalize at write or read.
- Multi-worker cache: in-process TTL means `--workers 1`; shared cache (Redis/file)
  if workers ever needed.
- Frontend E2E smoke (Playwright) against TestClient-seeded API.
- Uncommitted work (modified + 7 untracked: `api/materials.py`, `api/routers/cv.py`,
  `api/routers/materials.py`, `tests/test_api_cv.py`,
  `tests/test_api_freshness.py`, `tests/test_api_jobs_contract.py`,
  `tests/test_api_materials.py`) — review + commit before starting apply/skills.

## 4. Definition of Done (every phase)

1. `python -m pytest tests/` fully green.
2. `node --check` on touched frontend files.
3. Live check: `GET /api/health` + one real request per new endpoint.
4. Docs touched: README table (endpoints), plus BACKEND/FRONTEND/PM status.
5. No secrets committed; no generated artifacts committed (`apply_packages/`,
   `cover_letters/`, `resumes/`, `screenshots/`, `cache/`).

## 2b Submit Specification

### Judgment Calls (approved as specced)

- **0.85 threshold**: submit is only permitted when the CV-match / good-fit score ≥ 0.85 (below this → 422, dream-tier manual-application only).
- **short-title equality**: the job title displayed on the ATS page must exactly match (case‑insensitive strip) the title stored in the cached job record; mismatch → rejection with ratio and expected value logged.
- **unverified-consumes-cap**: a `submit_unverified` attempt still consumes one daily‑cap slot; if the human PATCH later determines the claim failed, the slot is refunded only via the manual-PATCH reconciliation path.

### Three Clarifications (answered)

1. **Logging on (a)/(c) rejection**: actual ratio, expected value, and raw input are recorded for every rejection, not just the 422/400 status. If real usage later clusters near the 0.85 boundary, we want evidence to retune from, not a guess.
2. **Manual-PATCH on submit_unverified path**: is auth-gated the same as the submit route, and does resolving a claim manually reconcile the daily‑cap slot (e.g. if a human determines it actually failed, does the slot get refunded)? Needs the same rigor as everything else here since it's the one human-override path in the whole design.
3. **"One live intent per fp"**: means one unexpired intent at a time (a user can re-request a fresh token after the first expires) and not a hard lockout per fp.

### Execution Order (strict, no shortcuts)

The 2b feature will be shipped in this exact order, with no shortcuts:

1. **F1/F2 Lever fixes** — already in the working tree (uncommitted): F1 follows the `a.show-page-apply` anchor to the `/apply` sub-page; F2 switches from `networkidle` to `domcontentloaded` + explicit selector wait.
2. **Live Lever `.confirmation-message` copy observation** — record the exact copy rendered on the Lever confirmation screen for audit and UX consistency reviews.
3. **~35 tests from §7** — the full test suite covering the three judgment calls, rejection logging, manual-PATCH path, and one live intent per fp; all must pass on CI before merge.
4. **Endpoint code** — implement `POST /api/apply/{fp}` submit path per the full spec (verification protocol, claim-first idempotency, auth, triple-gate).

After all four close, the UI toggle becomes enabled and the submit opcode is reachable.
