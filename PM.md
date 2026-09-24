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

Full suite: **136 passed** (`venv\Scripts\python.exe -m pytest tests/ -q`).

## 2. Next: Phase 2 — Action API (spec)

Goal: dashboard buttons do real work, behind the existing safety gates.

| Endpoint | Backend | Frontend | Safety |
|---|---|---|---|
| `POST /api/scrape` `{boards?, limit?}` | background run registry (no multi-scrape overlap), writes via curator → Sheets, `POST /api/jobs/refresh` after | `btnScrapeNow` → progress → refresh | ✅ done — cap boards/run, token required off-localhost |
| `POST /api/apply/{fp}` | `auto_applier` in fill-review default; submit only if `AUTO_APPLY_CONFIRM=true` + explicit `confirm:true` body | cockpit queue + screenshots | ⬜ next — double-gate: env flag AND body flag; daily cap enforced |
| `POST /api/resume/{fp}` | `resume_generator` 1-page tailor → serve PDF path/bytes | Resume Studio replaces static demo | ✅ done |
| `POST /api/cover-letter/{fp}` | `gemini_tools` role-aware letter → serve text/PDF | same package card | ✅ done |
| `PUT /api/cv/profile` | `cache.save_cv_profile` merges Studio edits into on-disk cache | profile Edit/Save panel | ✅ done |
| `GET /api/skills` | aggregate `tech_stack` over ALL JOBS | replaces `MOCK_SKILLS` cloud | ⬜ next |

Conventions (from BACKEND.md §6 / existing patterns): schema → `cache.py`
accessor (lazy imports, never crash) → `routers/<group>.py` → tests in
`tests/test_api_<group>.py` (fake `cache.*`, no live Sheets) → `js/api.js` fn →
README table row. Keep `app.py` thin; one router file per group.

## 3. Backlog

- `POST /api/apply/{fp}` + cockpit wiring (double-gated submit, daily cap).
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
