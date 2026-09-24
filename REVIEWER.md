# REVIEWER.md — Code Review Guide

Every change gets reviewed before merge. Verdict is binary: **APPROVE** or
**REQUEST-CHANGES** (the latter must list exactly what flips it).
Mirrors the `reviewer` subagent (`.opencode/agents/reviewer.md`) — humans and
the agent use the same lenses.

---

## 1. Lenses (check every diff against all six)

1. **Correctness** — gate logic, score math, off-by-ones, unreachable branches,
   early-return schema completeness.
2. **Stale state** — caches without invalidation (sheet TTL in `api/cache.py`,
   matcher caches, run registries); `force`/refresh paths that leave sibling
   caches stale.
3. **Input handling** — `None`/missing/`""` job fields; untrusted paths
   (`selected_cv_path`, filenames, fingerprints) reaching `open()`/`parse()`;
   coercion crashes (`int("")`, `float(None)`).
4. **Security** — secrets (`.env`, `keys.json`, sheet IDs, tokens) into logs,
   responses, files, or `frontend/`; CORS broadening; unauthenticated
   write/submit paths; new routes touching credentials.
5. **Contracts** — producer vs consumer fields across curator → sheet → API → UI;
   nullable enrichment; `COLUMNS` drops in `sheet_writer.py`; schema vs
   `store.normalize*` expectations; reason-string consumers.
6. **Failure behavior** — missing files/creds, LLM outage, empty sheets, bad JSON:
   degrade with fallback + warning, never crash, never silently blank output.

## 2. Area checklists

**Pipeline (`agents/`, `tools/`)**
- New scraper: board manually spot-checked? filter regressions (`test_country_filter.py` green)?
- Scoring change: keyword + semantic paths both covered? `curated_jobs.json` shape unchanged?
- Sheet write change: header/column order preserved? APPLIED fork vs tracker-header conflict (see `api/schemas.py` docstring)?

**API (`api/`)**
- Thin `app.py` kept thin (no handler logic)? One router file per group?
- Lazy-import rule intact (`agents.curator`/`main` absent from `sys.modules` after `/api/health` — test asserts this)?
- New endpoint: schema nullable + `""→null` validators, error codes (400/401/404/502) match BACKEND.md, faked tests added, `js/api.js` fn + README row?
- Auth: write paths require token off-localhost? No secret substrings in responses (health test pattern)?

**Frontend (`frontend/`)**
- Reads `store.state`, never `MOCK_*` (grep it)? `node --check` clean?
- Loading + error + data states for every live section? String fingerprints compared with `String()`?
- No secrets/token values hardcoded; token only via `localStorage`?

**Windows**
- New `print()` with emoji outside `sheet_writer.py`'s UTF-8 guard? (cp1252 crash — the LIVE incident that masked the Sheet connection.)
- Paths: no hardcoded `/` assumptions; PowerShell-safe commands in docs.

## 3. Severity & report format

- **P0** blocks the phase · **P1** must fix before merge · **P2** harden soon ·
  **NIT** style/duplication (flag drift, don't block).
- Each finding: `file:line` + evidence + concrete fix. Plus an explicit
  "verified OK" list for important non-findings. No soft verdicts.
