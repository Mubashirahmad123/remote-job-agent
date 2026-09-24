# TESTER.md — Testing Guide

Mirrors the `tester` subagent (`.opencode/agents/tester.md`). Suite is pytest,
currently **136 passed** across 8 files: `test_api_phase1.py`,
`test_api_phase2.py`, `test_api_cv.py`, `test_api_materials.py`,
`test_api_freshness.py`, `test_api_jobs_contract.py`, `test_auto_applier.py`,
`test_country_filter.py`.

---

## 1. Running tests

```powershell
$env:PYTHONIOENCODING = 'utf-8'   # required on Windows (emoji prints)
venv\Scripts\python.exe -m pytest tests/ -q            # full suite
venv\Scripts\python.exe -m pytest tests/test_api_phase1.py -q   # one file
```

Frontend (no test runner — syntax gate):
```powershell
node --check frontend\js\store.js; node --check frontend\js\api.js
```

Live smoke (reads only, real app, no fakes):
```powershell
venv\Scripts\python.exe -m uvicorn api.app:app --host 127.0.0.1 --port 8000
# /api/health -> data_source, /api/jobs?limit=1, /api/stats, /api/tracker
```

## 2. Iron rules (no exceptions)

- **No live Sheets, LLM APIs, or real browsers in tests.** Stub at the boundary:
  fake `api.cache._read_tab_values` / `_load_enrichment_map` (Phase 1 pattern),
  stub the LLM fallback chain, stub Playwright.
- Isolated units with temp dirs; scratch scripts only under
  `C:\Users\Mubashir1\AppData\Local\Temp\opencode`.
- Back up `data/job_agent.db` before any run touching SQLite.
- Never modify product code to make a test pass — send failures back.
- Never print `.env` values, keys, or sheet IDs (in tests or reports).

## 3. Writing tests (convention)

- Location/name: `tests/test_<module>.py`; classes `TestXxx`, methods `test_<behavior>`.
- Every new endpoint/helper gets **happy-path + failure-path** cases
  (see `test_api_phase1.py`: list + bad-tab-400, patch-ok + patch-400/404).
- API tests use `fastapi.testclient.TestClient(create_app())` with monkeypatched
  cache fakes; assert status codes + key fields, never live data.
- Phase 2 safety probes (mandatory when apply endpoints land):
  `POST /api/apply` with `mode != "review"` → 400; submit unreachable with
  `AUTO_APPLY_CONFIRM=true` in env; PDFs verified 1-page via pdfplumber.
- Report timings for anything >60s or touching network; cite `file:line`
  with actual vs expected.

## 4. Definition of Done (tester verdict)

Itemized per phase: suite result with counts, new tests added, slow/flaky/
env-dependent notes with `file:line`, then **GO / NO-GO**. One unexplained
failure = NO-GO, stated plainly. (Same checklist as `PM.md` §4.)
