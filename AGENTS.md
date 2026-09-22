# Repository Guidelines

## Project Structure & Module Organization

- `agents/` — pipeline modules: `scrapper.py` (45+ job-board scrapers), `curator.py` (dedup, CV matching, ranking), `gemini_tools.py` (LLM cover letters with fallback), `auto_applier.py` (auto-apply).
- `tools/` — reusable utilities: `cv_parser.py`, `cv_matcher.py`, `deduplicator.py`, `sheet_writer.py`, `resume_generator.py`, and scraper helpers.
- LLM fallback chain (shared by `gemini_tools.py`, `resume_generator.py`, `cv_parser.py`): Gemini → Groq → Mistral → GLM → Ollama Cloud. Mistral/Groq use OpenAI-compatible endpoints via `requests` (no extra SDK deps); GLM needs `GLM_API_KEY` + `zhipuai` package (model via `GLM_MODEL`, default `glm-4`); Ollama sends `Authorization: Bearer` only when `OLLAMA_API_KEY` is set (empty = local server).
- `tests/` — pytest suites mirroring the modules they test (e.g., `test_auto_applier.py`).
- Top-level entry points: `main.py` (CrewAI pipeline), `Run.py` (setup/run), `scheduler.py` (cron), `track.py` (application tracker), `clean_jobs.py` and `format_jobs_xlsx.py` (Excel tooling).
- Generated artifacts (`apply_packages/`, `cover_letters/`, `resumes/`, `screenshots/`, `cache/`) are gitignored — never commit them.

## Build, Test, and Development Commands

```bash
# Local development
python -m venv venv && uv pip install -r requirements.txt   # install deps
python Run.py --setup                                       # first-time setup (Chromium, Crawl4AI)
python Run.py                                               # run pipeline (CrewAI)
python main.py simple                                       # direct scrape → Sheets, no LLM
python scheduler.py                                         # scheduled scraping
python -m pytest tests/                                     # run all tests

# Docker workflow
docker compose up -d scheduler                              # run 24/7 scheduler daemon
docker compose run --rm runner python main.py simple        # run scrape on-demand via container
docker compose run --rm runner python -m pytest tests/      # run test suite in container
```

Copy `.env.example` to `.env` and fill in secrets before running. See README for per-mode CLI flags (`apply`, `resume`, `test`).

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
- Respect the auto-apply safety flags: `AUTO_APPLY_CONFIRM=false` (fill & review) vs `true` (submit).
- Edit the country allowlist via `ALLOWED_COUNTRY_TERMS` in `agents/scrapper.py` — the `ALLOWED_COUNTRIES` env var is obsolete.
