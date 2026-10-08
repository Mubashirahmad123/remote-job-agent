# Repository Guidelines

## Project Structure & Module Organization

- `agents/` — pipeline modules: `scrapper.py` (45+ job-board scrapers), `curator.py` (dedup, CV matching, ranking), `gemini_tools.py` (LLM cover letters with fallback), `auto_applier.py` (auto-apply).
- `api/` — FastAPI backend (reads + actions): `app.py` (thin factory + `_GateMiddleware`), `deps.py` (auth/CORS + `resolve_actor`/`require_actor`), `auth.py` (Argon2id users + sessions in SQLite), `ratelimit.py` (login throttling), `activity.py` (audit feed), `cache.py` (Sheets TTL cache + snapshot fallback + CV profile/variants), `schemas.py`, `mappers.py`, `materials.py` + `runs.py` (registries), `routers/` (one file per group: auth, liveness, health, jobs, stats, tracker, system, runs, materials, cv, apply, activity).
- `frontend/` — vanilla-JS dashboard, no build step: `js/api.js` (one fn per endpoint group), `js/store.js` (state + normalization + mock fallback), `js/components/` (dashboard, jobDesk, jobDrawer, tracker, resumeStudio, autoApply).
- `tests/` — pytest suites mirroring the modules they test (e.g., `test_auto_applier.py`, `test_api_phase1.py` — faked Sheets, no network).
- `tools/` — reusable utilities: `cv_parser.py`, `cv_matcher.py`, `deduplicator.py`, `sheet_writer.py`, `resume_generator.py`, `application_tracker.py` (Sheets APPLIED tab), `glm_client.py` (Zhipu GLM over HTTP), and scraper helpers.
- `deploy/` — free-cloud deployment: `DEPLOY_ORACLE.md` (Oracle Always Free $0 walkthrough), `setup-vm.sh` (VM bootstrap), `Caddyfile` (compose `caddy` reverse proxy).
- LLM fallback chain (shared by `gemini_tools.py`, `resume_generator.py`, `cv_parser.py`): Gemini → Groq → Mistral → GLM → Ollama Cloud. Mistral, Groq **and GLM** all use OpenAI-compatible endpoints via `requests`, so none of them needs an extra SDK. GLM needs `GLM_API_KEY` (model via `GLM_MODEL`, default `glm-4`) and is implemented in `tools/glm_client.py`; Ollama sends `Authorization: Bearer` only when `OLLAMA_API_KEY` is set (empty = local server).
  - **Do not add `zhipuai` back.** It pins `pyjwt>=2.8.0,<2.9.0` while `crewai` pins `pyjwt>=2.13.0,<3`; the ranges do not intersect, so the dependency set becomes unsatisfiable and `docker build` fails with `ResolutionImpossible` (the failure and its resolution are recorded in `CHANGELOG.md`, 2026-10-08). `tools/glm_client.py` reproduces the SDK's HS256 key signing byte-for-byte and is pinned by golden vectors in `tests/test_glm_client.py`.
- Top-level entry points: `main.py` (CrewAI pipeline), `Run.py` (setup/run), `scheduler.py` (cron), `track.py` (application tracker), `clean_jobs.py` and `format_jobs_xlsx.py` (Excel tooling).
- Generated artifacts (`apply_packages/`, `cover_letters/`, `resumes/`, `screenshots/`, `cache/`) are gitignored — never commit them.

## Build, Test, and Development Commands

```bash
# Local development
python -m venv venv && uv pip install -r requirements.txt   # install deps (.venv/ also works)
python Run.py --setup                                       # first-time setup (Chromium, Crawl4AI)
python Run.py                                               # run pipeline (CrewAI)
python main.py simple                                       # direct scrape → Sheets, no LLM
python scheduler.py                                         # scheduled scraping
python -m pytest tests/                                     # run all tests (514, all offline)

# Dashboard e2e (boots a real uvicorn; needs Node 20+ and a venv the harness can find)
cd tests/e2e && npm ci && node --test smoke.test.mjs        # or: ./tests/e2e/run.sh

# Docker workflow
docker compose up -d --build                                 # full stack: api + scheduler + caddy (needs API_TOKEN)
docker compose up -d scheduler                              # run 24/7 scheduler daemon only
docker compose run --rm runner python main.py simple        # run scrape on-demand via container
docker compose run --rm runner python -m pytest tests/      # run test suite in container
```

Copy `.env.example` to `.env` and fill in secrets before running. See README for per-mode CLI flags (`apply`, `resume`, `test`).

`.github/workflows/ci.yml` runs all of the above on every push and PR: the pytest
suite, the lock-file drift check, the Node e2e suite, a `docker build` plus an
assertion that no `.env`, `keys.json`, `*.db`, `.venv/` or `node_modules/` is baked
into the image, and a `pip-audit` vulnerability scan. Nothing in it is allowed to
fail.

**After changing `requirements.txt`, regenerate the lock and commit both:**

```bash
uv pip compile requirements.txt -o requirements.lock.txt --universal
```

`--universal` is required, not cosmetic: without it uv resolves for the host OS
only, which produces an unmarked `pywin32` line that cannot install on the Linux
deployment VM and drops `uvloop`. CI fails if a package or an exact pin in
`requirements.txt` disagrees with the lock.

**Every pin needs an upper bound.** `==` is exact; `>=1.0.0,<2` and `~=2.26` are
bounded; a bare `pytest` or a lone `>=1.0.0` is not, and lets an upstream major
release break the build on a commit that changed nothing here.
`tests/test_dependency_hygiene.py` fails on an unbounded or malformed specifier.

**Vulnerability scanning** runs in the `dependency-audit` CI job:

```bash
python -m pip install pip-audit
python deploy/dependency_audit.py                    # what CI runs
python deploy/dependency_audit.py --update-baseline  # record the current state
```

It audits `requirements.lock.txt` — the full transitive resolution, which is
where every real finding lives — and compares against `deploy/audit-baseline.txt`,
failing only on findings **new** since the baseline was recorded. The first run
found 48 distinct advisories across 8 packages, and clearing them is not a bump:
`crawl4ai` fixes start at 0.8.0 (five minors on, and it drives the JS-rendered
scraper), `pillow` fixes start at 12.1.1 (two majors on), and `chromadb` has no
fixed version published at all. A job red from day one is a job that gets
switched off, so this one ratchets instead. On a failure there are two honest
options and both are a commit: upgrade past it, or add the line to the baseline
and own the decision in review. Fixed advisories are reported as FIXED so the
baseline gets pruned, and a pruned entry cannot come back silently.

One gap worth knowing about: **nothing currently installs from the lock** — the
`Dockerfile` installs `requirements.txt`, so transitive versions float between
builds and the audit is checking the best available *record* of what ships rather
than a byte-exact manifest. Switching the image to install from the lock is the
real fix; it has to be verified on the ARM deployment VM, which CI does not run,
so it was not done as a drive-by.

## Coding Style & Naming Conventions

- Python 3.11+, 4-space indentation, `snake_case` for functions/variables, `CamelCase` for classes.
- Use descriptive docstrings and section-banner comments (`# ====`).
- No linter/formatter is configured; match the surrounding file's style and keep functions focused.

## Testing Guidelines

- Framework: pytest (already in `requirements.txt`). No coverage threshold is enforced.
- Place files in `tests/` named `test_<module>.py`; classes as `TestXxx`, methods as `test_<behavior>`.
- Avoid tests that hit live APIs, Google Sheets, or real browsers; prefer isolated units with temp dirs.

## Commit & Pull Request Guidelines

- History is informal and short (e.g., `Fix urls and points`). Use concise lowercase summaries that describe the change; prefix with the area when useful (e.g., `scrapper: ...`).
- Never commit secrets or generated artifacts: `.env`, `keys.json`, `my_cv.pdf`, `scraped_jobs.json` are gitignored.
- PRs should describe the change, note any `.env` variables added, and mention how it was verified (tests run, boards affected).

## Security & Configuration Tips

- Keep `.env` and `keys.json` local only; add new variables to `.env.example` when you introduce a setting.
- `.env` format is strict dotenv: exact `UPPER_SNAKE=key` with no spaces around `=` (e.g., `GROQ_API_KEY=gsk_...` — not `Groq = ...`). A wrong name means `os.getenv` silently returns empty.
- In Docker, never bake `.env`, `keys.json`, or `my_cv.pdf` into images (`.dockerignore` enforces this). Always mount them as read-only volumes via `docker-compose.yml`.
- Mount `./data`, `./logs`, `./apply_packages`, and `./resumes` as host volumes in Docker so mutable state and output artifacts persist across container recreation.
- Treat dashboard apply and CLI Playwright as separate flows: the API opens visible Greenhouse/Lever fill-and-review windows (other ATSs get packages); Greenhouse `/intent` + `/submit` routes exist but fail closed with 403 while `api/safety.py SUBMIT_ENABLED=False`. The legacy CLI blind submit is permanently disabled (no click); `AUTO_APPLY_CONFIRM` is ignored everywhere.
- Edit the country allowlist via `ALLOWED_COUNTRY_TERMS` in `agents/scrapper.py` — the `ALLOWED_COUNTRIES` env var is obsolete.
