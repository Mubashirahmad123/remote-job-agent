# CONTRIBUTING.md — How to Contribute

## 1. Setup

```bash
python -m venv venv && uv pip install -r requirements.txt
copy .env.example .env   # then fill secrets (strict UPPER_SNAKE=key, no spaces)
python Run.py --setup    # Chromium + Crawl4AI (first time only)
```

Need Sheets reads: place `keys.json` in root + share the Sheet with the
service account email. Verify: `GET /api/health` → `sheets_configured: true`.

## 2. Workflow

1. Branch from `main`: `feat/<area>-<short>` (e.g. `feat/api-scrape-trigger`).
2. Keep changes scoped; one router file per API group, one CSS/JS file per UI concern.
3. Follow `AGENTS.md` (style: 4-space, `snake_case`/`CamelCase`, banner comments)
   plus `BACKEND.md` §6 / `FRONTEND.md` §5 when touching those layers.
4. Commit style: concise lowercase, area prefix (`api: …`, `scrapper: …`, `frontend: …`).
5. Never commit secrets or generated output: `.env`, `keys.json`, `my_cv.pdf`,
   `scraped_jobs.json`, `apply_packages/`, `cover_letters/`, `resumes/`,
   `screenshots/`, `cache/` (all gitignored).

## 3. Before pushing (matches PM.md Definition of Done)

```bash
venv\Scripts\python -m pytest tests/ -q
node --check <any touched frontend file>
```

Then: reviewer pass per `REVIEWER.md` (expect APPROVE or a P0–P2 list),
tester verdict per `TESTER.md` (GO/NO-GO).

## 4. Pull requests

Describe the change, list any new `.env` variables, state verification
(tests run, boards affected, live endpoints hit). Note contract changes
(sheet columns, API schemas, `store` shape) explicitly — reviewers check
producer→consumer chains per `REVIEWER.md` lens 5.
