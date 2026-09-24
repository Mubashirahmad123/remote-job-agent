# Remote Job Agent

An automated system that scrapes 45+ remote job boards, matches jobs to your CV using AI, and saves curated results to Google Sheets — all running on a scheduled cron.

---

## Features

| Feature | Status | Description |
|---|---|---|---|---|
| Multi-source scraping | ✅ | 45+ job boards via APIs, HTML parsing, Playwright stealth, JobSpy, and Crawl4AI |
| **Smart job filters** | ✅ | Only web/software dev roles — excludes ML, AI, Network, DevOps, SRE, Security, QA, Game, Blockchain, Embedded, Salesforce, and senior/lead roles |
| CV-based job matching | ✅ | Parses your PDF/DOCX CV via LLM fallback chain, local keyword scoring (no API calls per job) |
| **Multi-CV matching** | 🟡 Partial | `CV_DIR=cvs/` — auto-picks the best CV per job (keyword-based); pick recorded as `selected_cv`/`selected_cv_path` per job and used for scoring, resume + cover-letter generation. Semantic scoring still uses the primary CV only |
| **ATS 1-page resume + cover letter** | ✅ | Multi-pass shrink engine guarantees exactly 1 page; slate/navy styled header, section rules, hanging-indent bullets (verified with pdfplumber) |
| **Semantic job matching** | ✅ | Optional FAISS + sentence-transformers for cosine-similarity scoring (catches synonyms) — `pip install sentence-transformers faiss-cpu`, then build the index with `python -m tools.embedding_matcher` (required — without `cv_embeddings.pkl` scoring silently stays keyword-only) |
| Duplicate detection | ✅ | MD5 fingerprinting prevents duplicate entries across runs |
| Smart Sheets dashboard | ✅ | Auto-creates tabs: ALL JOBS, TOP MATCHES (score ≥85), GOOD MATCHES (70–84), APPLIED, STATS — with colored score bands, hyperlinks, frozen headers |
| **AI cover letters with role detection** | ✅ | Detects backend/frontend/fullstack/mobile role from job title and tailors tone, skills, and experience accordingly |
| **LLM fallback chain** | ✅ | Gemini → Groq → Mistral → GLM → Ollama Cloud — pipeline never crashes from API quota errors |
| **Auto-apply pipeline** | ✅ | Generates tailored resume + cover letter, opens apply URL in browser or auto-fills Greenhouse/Lever via Playwright, tracks in APPLIED sheet |
| **Tailored resume generation** | ✅ | Generates ATS-optimized resume PDF matched to each job's tech stack `python main.py resume` |
| **Country/location filter** | ✅ | 452-country detection — blocks jobs from non-whitelisted countries, allows 198 whitelisted terms |
| **Cross-platform Unicode PDFs** | ✅ | Auto-downloads DejaVu fonts — works on Windows/macOS/Linux; covers accents, Arabic, Cyrillic |
| Application tracker | ✅ | `track.py` CLI + `tools/application_tracker.py` — mark applied, update status, list, stats, follow-up reminders |
| Auto-cleanup old jobs | ✅ | Removes jobs older than 30 days from all sheets (including legacy `LIVE Remote Jobs Tracker`) |
| Sheet formatting (Google Sheets) | ✅ | Auto-applies colored score bands, clickable hyperlinks, wrapped text, column widths via Google Sheets API |
| Sheet formatting (xlsx export) | ✅ | `format_jobs_xlsx.py` — professional Excel formatting with same visual style |
| Standalone cleanup CLI | ✅ | `python tools/sheet_writer.py --cleanup [days]` — run cleanup + formatting anytime |
| Excel cleanup + format | ✅ | `clean_jobs.py` — extracts company from URLs, strips HTML, deduplicates tags, removes senior roles; `format_jobs_xlsx.py` — professional xlsx formatting |
| Playwright stealth scraper | ✅ | Scrapes JS-rendered/bot-gated boards (WeWorkRemotely, Remote.co, Wellfound, NoDesk, YCombinator, Arc, GulfTalent, NoFluffJobs, Lemon, JustJoinIt — verified live 2026-09-22, 19 jobs) |
| Crawl4AI scraper | ✅ | AI-native crawler for JustRemote |
| JobSpy integration | ✅ | Scrapes LinkedIn, Indeed, Glassdoor, Google Jobs, ZipRecruiter |
| Scheduled automation | ✅ | Cron-based scheduler (Mon/Thu full scrape, daily quick checks) |
| Universal run script | ✅ | `Run.py` works on Windows / Mac / Linux with `--setup` flag |
| Docker support | ✅ | Production-grade Docker + docker-compose with Playwright, persistent volumes & secrets isolation |
| FastAPI backend (reads + actions) | ✅ | `api/` — jobs, stats, tracker, refresh, scrape runs, tailored materials, CV profile endpoints over the Sheets cache (see below) |
| Command Center dashboard | ✅ | `frontend/` — live UI served same-origin at `http://127.0.0.1:8000/` (no CORS issues) |

---

## Prerequisites

- Python 3.11+
- A Google Cloud service account (for Sheets API) → save as `keys.json`
- At least one LLM API key: `GEMINI_API_KEY`, `GROQ_API_KEY`, `MISTRAL_API_KEY`, `GLM_API_KEY`, or `OLLAMA_API_KEY` (Ollama Cloud)
- (Optional) Adzuna free API credentials

---

## Quick Start

```bash
# First time setup (creates venv, installs deps, sets up Chromium and Crawl4AI)
python Run.py --setup

# Open .env and fill in your API keys
# Then run:
python Run.py
```

Or step by step with `uv` (recommended — avoids dependency resolution conflicts with Crawl4AI/CrewAI):

```bash
# 1. Install uv (if not already installed)
pip install uv

# 2. Create and activate virtual environment
python -m venv venv
.\venv\Scripts\activate    # Windows
# source venv/bin/activate  # Mac/Linux

# 3. Fast, conflict-free install of dependencies
uv pip install -r requirements.txt

# 4. Install Chromium browser for scraping & auto-apply
playwright install chromium

# 5. Run the agent
python main.py
```

---

## Usage

```bash
python Run.py                 # Full CrewAI pipeline
python Run.py --setup         # First-time environment setup
```

You can also set `RUN_MODE` in `.env`:
- `crewai` (default) — CrewAI pipeline: scrape + curate → cover letter (2 agents)
- `simple` — Direct scrape → sheets without CrewAI
- `test` — Test individual tools
- `apply` — Auto-apply to top matching jobs
- `resume` — Generate tailored resumes for top jobs

### Auto-Apply

The auto-apply agent generates a tailored resume + cover letter, then applies in one of two modes:

**Simple mode** (default) — opens the apply URL in your browser and creates an apply package:
```bash
python main.py apply
```

**Playwright mode** — automatically fills Greenhouse/Lever application forms:
```bash
# Fill forms + take screenshots (review before submitting)
AUTO_APPLY_PLAYWRIGHT=true python main.py apply

# Full auto-submit (confirms — use with caution)
AUTO_APPLY_PLAYWRIGHT=true AUTO_APPLY_CONFIRM=true python main.py apply
```

The Playwright mode:
- Detects the ATS platform (Greenhouse, Lever, Workday, Workable, Ashby, Breezy)
- Fills name, email, phone, LinkedIn, portfolio
- Uploads generated resume PDF
- Pastes tailored cover letter
- Takes a screenshot before submission
- Optionally submits the form (with `AUTO_APPLY_CONFIRM=true`)

An **apply package** is always created in `apply_packages/` with:
- `resume.pdf` — tailored resume
- `cover_letter.txt` — tailored cover letter
- `form_data.json` — all application data
- `index.html` — helper page with copy-to-clipboard buttons

---

## Project Structure

```
remote-job-agent/
├── agents/
│   ├── __init__.py
│   ├── scrapper.py           # 45+ job board scrapers (API, HTML, RSS)
│   ├── curator.py            # Dedup, CV matching, quality ranking, sheet save
│   ├── gemini_tools.py       # Cover letters with LLM fallback (Gemini→Groq→Mistral→GLM→Ollama); ATS 1-page cover-letter PDF
│   └── auto_applier.py       # Auto-apply: resume + cover letter + Playwright form fill (fill-and-review while AUTO_APPLY_CONFIRM=false; never auto-submits)
├── tools/
│   ├── __init__.py
│   ├── cv_library.py          # Multi-CV library: CV_DIR discovery, per-job pick_best(), single-CV fallback
│   ├── cv_parser.py           # PDF/DOCX CV → structured profile via LLM fallback chain
│   ├── cv_matcher.py          # Local keyword job scoring (no API calls)
│   ├── deduplicator.py        # MD5 fingerprint duplicate detection
│   ├── embedding_matcher.py   # Optional FAISS semantic scoring (Phase 2; primary CV only)
│   ├── font_utils.py          # UnicodePDF ATS layout engine (headers, sections, bullets, page_count) + DejaVu resolution
│   ├── sheet_writer.py        # Google Sheets dashboard (5 tabs) + 30-day auto-cleanup
│   ├── resume_generator.py    # AI-tailored ATS 1-page resume PDF per job (3-pass shrink fit)
│   ├── jobspy_scraper.py      # LinkedIn, Indeed, Glassdoor, Google Jobs, ZipRecruiter
│   ├── playwright_scraper.py  # Stealth browser scraping (10 boards incl. JustJoinIt) — `python -m tools.playwright_scraper <Board>`
│   ├── crawl4ai_scraper.py    # AI-native Crawl4AI scraper for JustRemote
│   ├── scraper_utils.py       # Text cleaning, date parsing utilities
│   └── application_tracker.py # APPLIED sheet management (mark, update, list, stats)
├── api/                      # FastAPI backend (reads + actions)
│   ├── app.py                # Thin factory: CORS + router includes + static UI mount
│   ├── deps.py               # CORS origins + Bearer auth (`API_TOKEN`)
│   ├── cache.py              # Per-tab Sheets cache (TTL) + curated enrichment + snapshot fallback + CV profile/variants
│   ├── schemas.py            # `JobOut`, `TrackerEntry`, `HealthOut`, `CvProfileOut`, `CvVariant` response models
│   ├── mappers.py            # Sheet-row → schema converters
│   ├── materials.py          # Resume/cover-letter generation registry (fp-mapped files)
│   ├── runs.py               # Background scrape-run registry (single active run)
│   └── routers/              # One file per group: health, jobs, stats, tracker, system, runs, materials, cv
├── frontend/                 # Command Center dashboard (no build step, vanilla JS)
│   ├── index.html            # Shell + all views (deck, jobs, resume, auto-apply, tracker)
│   ├── css/                  # Per-component stylesheets (see DESIGN.md tokens)
│   └── js/
│       ├── api.js            # Live FastAPI client (one fn per endpoint group)
│       ├── store.js          # Reactive state + backend→UI normalization + mock fallback
│       └── components/       # dashboard, jobDesk, jobDrawer, tracker, resumeStudio, autoApply
├── tests/
│   └── test_api_*.py etc.   # 136 isolated API tests (faked Sheets, no network) + auto_applier + country_filter
├── apply_packages/           # Auto-generated apply packages (resume + cover letter + form data)
├── cover_letters/            # Generated PDF cover letters
├── resumes/                  # Generated tailored PDF resumes
├── screenshots/              # Playwright screenshots before form submission
├── clean_jobs.py             # Excel cleanup: extract company, strip HTML, dedup tags, remove senior roles
├── format_jobs_xlsx.py       # Professional Excel formatter (colored bands, hyperlinks, frozen header)
├── track.py                  # Application tracker CLI (mark applied, status, list, stats, followups)
├── main.py                   # CrewAI pipeline entry point
├── Run.py                    # Universal start script (Win/Mac/Linux)
├── scheduler.py              # Cron-based scheduler (Mon/Thu)
├── .env                      # Configuration + API keys
├── .env.example              # Example env file with all variables
├── .gitignore
├── requirements.txt
├── Dockerfile
├── scraped_jobs.json         # Cached scrape output
├── keys.json                 # Google service account key
└── my_cv.pdf                 # Your CV (for CV matching)
```

---

## Environment Variables (`.env`)

```env
# Core
GOOGLE_SHEETS_ID=your_sheet_id
GOOGLE_SERVICE_ACCOUNT=keys.json
GEMINI_API_KEY=your_key
MODEL=gemini/gemini-2.5-flash  # CrewAI model; groq/... and mistral/... also work (uses matching key)
RUN_MODE=crewai          # crewai | simple | test | apply | resume

# Job Scraping
ADZUNA_APP_ID=your_id
ADZUNA_APP_KEY=your_key
JOBSPY_RESULTS_PER_SITE=20
JOBSPY_DELAY=3
PLAYWRIGHT_HEADLESS=true
PLAYWRIGHT_TIMEOUT=30000

# CV Matching
CV_PATH=my_cv.pdf
CV_DIR=  # optional: folder of CV variants (cvs/); when set, best CV is picked per job, CV_PATH is the fallback
MIN_MATCH_SCORE=70
CLEANUP_DAYS=30

# Location / Country Filter (OBSOLETE — use hardcoded ALLOWED_COUNTRY_TERMS in agents/scrapper.py:330)
# The code ignores this env var. Edit ALLOWED_COUNTRY_TERMS in scrapper.py to change allowed countries.
ALLOWED_COUNTRIES=uk,united kingdom,new zealand,nz,usa,united states

# LLM Fallback (need at least one key — chain is Gemini → Groq → Mistral → GLM → Ollama)
GEMINI_API_KEY=
GROQ_API_KEY=
GROQ_MODEL=openai/gpt-oss-120b
MISTRAL_API_KEY=
MISTRAL_MODEL=mistral-medium-latest
GLM_API_KEY=
GLM_MODEL=glm-4
OLLAMA_API_KEY=  # required only for Ollama Cloud; leave empty for a local server
OLLAMA_URL=http://localhost:11434  # local server; use https://ollama.com for cloud
OLLAMA_MODEL=llama3.1  # local model; cloud model in use: gpt-oss:120b

# Auto-Apply
AUTO_APPLY_ENABLED=false  # auto-apply after pipeline
AUTO_APPLY_THRESHOLD=70   # minimum match score
AUTO_APPLY_LIMIT=5        # max jobs per run
AUTO_APPLY_PLAYWRIGHT=false  # true = fill forms; false = open browser
AUTO_APPLY_CONFIRM=false     # true = submit (DANGER); false = fill & review

# Your Profile (for auto-fill)
APPLICANT_NAME=Your Name
APPLICANT_EMAIL=your@email.com
APPLICANT_PHONE=+1234567890
APPLICANT_LINKEDIN=https://linkedin.com/in/yourprofile
APPLICANT_PORTFOLIO=https://yourportfolio.com
APPLICANT_GITHUB=https://github.com/yourprofile

# Embedding Matcher (optional — install sentence-transformers + faiss-cpu)
EMBEDDING_MODEL=all-MiniLM-L6-v2
CV_EMBEDDINGS_PATH=cv_embeddings.pkl
```

---

## How It Works

```
45+ Job Boards
     │
     ▼
  agents/scrapper.py     ◄── API calls, HTML parse, Playwright, JobSpy, Crawl4AI
     │                   ──   (called by merged Scraper+Curator agent)
     ▼
  agents/curator.py       ◄── Dedup → CV score (local + optional semantic) → quality rank → Sheets
     │                    ──   (called by merged Scraper+Curator agent)
     ├─ tools/deduplicator.py    (MD5 fingerprinting)
     ├─ tools/cv_parser.py       (LLM fallback chain CV → profile)
     ├─ tools/cv_matcher.py      (Local keyword scoring, no API calls)
     ├─ tools/embedding_matcher.py  (Optional FAISS semantic scoring, Phase 2)
      └─ tools/sheet_writer.py    (Google Sheets dashboard + cleanup + formatting)
     │
     ▼
  Google Sheets Dashboard
     ├─ ALL JOBS          (everything scraped)
     ├─ TOP MATCHES       (score ≥ 85)
     ├─ GOOD MATCHES      (score 70–84)
     ├─ APPLIED           (track applications)
     └─ STATS             (run history)
```

---

## Job Boards Scraped

| Type | Sources |
|---|---|
| Free APIs | Remotive, RemoteOK, Arbeitnow, Himalayas, Jobicy, The Muse, Adzuna, WorkingNomads, AuthenticJobs (RSS) |
| HTML (requests+BS4) | RemoteOK, Jobspresso, EU Remote Jobs, Arc, Lemon, FlexJobs, Remote.co, JustRemote, NoDesk, RemoteTech, GoRemote, Remote4me, DailyRemote, Remojobs (×3), RemoteFrontendJobs, FindBacon, LandingJobs, WeAreDevelopers, NoFluffJobs, JustJoinIt, CWJobs, WorkInStartups, BuiltIn, Dice, GulfTalent, Naukri, NaukriGulf, FounditIN, Shine, TimesJobs, TrueUp, RemoteRocketship, RemoteJobsCom, Remotees |
| Playwright stealth | WeWorkRemotely, Remote.co, Wellfound, NoDesk, YCombinator, Arc, GulfTalent, NoFluffJobs, Lemon, JustJoinIt |
| JobSpy | LinkedIn, Indeed, Glassdoor, Google Jobs, ZipRecruiter |
| Crawl4AI | JustRemote |

---

## Scheduling

```bash
# Run the scheduler (Mon & Thu at 9 AM)
python scheduler.py
```

The scheduler logs all output to `logs/scraper.log` automatically.

---

## Application Tracker CLI

Track jobs you've applied to directly from the terminal:

```bash
# Mark a job as applied
python track.py --apply "https://job.url" --title "Backend Dev" --company "Acme" --score 85

# Update application status
python track.py --status "https://job.url" interviewing --note "Phone screen next week"

# List all applications (or filter by status)
python track.py --list
python track.py --list --filter interviewing

# Show pipeline stats (total, by status, response rate, weekly count)
python track.py --stats

# Show jobs due for follow-up
python track.py --followups
```

---

## API + Command Center Dashboard

The FastAPI backend exposes the Sheets pipeline as read endpoints, and the
dashboard UI is served same-origin so there are never CORS issues.

```bash
# Run the API + dashboard (http://127.0.0.1:8000/ — open this, not index.html directly)
venv\Scripts\python -m uvicorn api.app:app --host 127.0.0.1 --port 8000
# Interactive docs: http://127.0.0.1:8000/docs
```

| Endpoint | Description |
|---|---|
| `GET /api/health` | `{status, sheets_configured, curated_jobs_loaded, data_source}` — `data_source` is `sheets` \| `snapshot` \| `empty` |
| `GET /api/jobs?tab=&q=&source=&limit=&offset=` | Enriched jobs from `ALL JOBS` / `TOP MATCHES` / `GOOD MATCHES` |
| `GET /api/jobs/{fingerprint}` | One job by MD5 fingerprint |
| `GET /api/stats` | `{total_jobs, tabs, by_source, stats_rows, curated_jobs}` |
| `GET /api/tracker?status=` | APPLIED-tab rows |
| `PATCH /api/tracker/{fp}` | `{status, notes}` — status whitelist: applied, interviewing, offer, rejected, withdrawn, ghosted |
| `POST /api/jobs/refresh` | `{tab?}` — invalidate the sheet cache on demand |
| `POST /api/scrape` | Start a background scrape run → `202 {run_id, status}` (409 if one is active) |
| `GET /api/scrape` / `GET /api/scrape/{run_id}` | List runs / poll `{status, phase, scraped, curated, error}` |
| `POST /api/resume/{fp}` | Tailor 1-page resume PDF → `{status, filename}` + `GET …/download` |
| `POST /api/cover-letter/{fp}` | Role-aware cover letter → `{status, filename, cover_letter}` + `GET …/download` |
| `GET /api/cv/profile` | Cached parsed-CV profile → `CvProfileOut` (501 when no fresh `cache/cv_profile_*.json`; per-request LLM parsing disabled) |
| `PUT /api/cv/profile` | Persist Resume Studio edits (contact + skills) into the profile cache → `CvProfileOut` (501 when uncached; never triggers LLM parsing) |
| `GET /api/cv/variants` | CV variants `[{name, tags}]` via `CV_DIR`/`cvs/` discovery (missing dir → `[]`) |

Notes:

- Sheet cache TTL is 90s (override `API_CACHE_TTL`, clamped 60–120s).
- If Sheets is unreachable, `ALL JOBS` falls back to the local scrape snapshot
  (`scraped_jobs.json` → `fresh_scrape.json`); `data_source` reports `snapshot`
  and the UI badges row counts as `(snapshot: N)`. Snapshot rows are unscored,
  so the dashboard drops the score gate to 0% automatically.
- Binding is `127.0.0.1` by default; a non-local bind refuses to start unless
  `API_TOKEN` is set (then every `/api/*` needs `Authorization: Bearer <token>`).
- `file://` origins are blocked by design — always open the dashboard via the URL above.
- See `PRODUCTION.md` for Docker deployment and `DESIGN.md` for the UI design system.

---

## Excel Cleanup & Formatting

Clean exported xlsx from Google Sheets (extract company from URLs, strip HTML, dedup tags, remove senior roles), then apply professional formatting:

```bash
python clean_jobs.py
python clean_jobs.py --input "my_export.xlsx" --output "cleaned.xlsx" --keep-senior
```

Format a raw xlsx (colored score bands, clickable hyperlinks, frozen header, wrapped text):

```bash
python format_jobs_xlsx.py input.xlsx output.xlsx
python format_jobs_xlsx.py input.xlsx              # overwrites in place
```

---

## Docker Deployment

The application includes a production-grade container setup with pre-installed Playwright Chromium dependencies, Crawl4AI, and persistent volume mounts.

### Why Use Docker?
- **Zero Browser Setup Issues:** Automatically installs all 30+ Debian shared libraries required by headless Chromium.
- **Fast & Conflict-Free Builds:** Uses Astral `uv` for 10x faster package installation without resolver conflicts.
- **24/7 Unattended Scheduling:** Deploy to any Linux cloud VM (e.g. Hetzner, DigitalOcean, AWS) without keeping your personal computer running.
- **Strict Security:** Secrets (`.env`, `keys.json`, `my_cv.pdf`) are never baked into image layers; they are excluded via `.dockerignore` and mounted as read-only at runtime.
- **Data Persistence:** Scraped job caches, deduplication hashes (`seen_jobs.json`), the application tracker database (`data/job_agent.db`), logs, and generated resumes persist across container restarts via host volume bindings.

### Quick Start with Docker Compose

1. **Ensure your configuration files are ready in the project root:**
   - `.env` (API keys and configuration)
   - `keys.json` (Google Cloud Service Account)
   - `my_cv.pdf` (Your CV)
   - `seen_jobs.json`, `scraped_jobs.json` and `curated_jobs.json` must exist as **files** (all are gitignored, so a fresh clone won't have them — Docker would otherwise create directories at those paths and the app would crash):
   ```bash
   # Linux / Mac
   touch seen_jobs.json scraped_jobs.json curated_jobs.json && echo '{}' > seen_jobs.json && echo '[]' > scraped_jobs.json && echo '[]' > curated_jobs.json
   # Windows (PowerShell)
   '{}' | Out-File -Encoding utf8 seen_jobs.json; '[]' | Out-File -Encoding utf8 scraped_jobs.json; '[]' | Out-File -Encoding utf8 curated_jobs.json
   ```

2. **Run the 24/7 background scheduler daemon:**
   ```bash
   # Build image and start scheduler in background
   docker compose up -d scheduler

   # View live logs
   docker compose logs -f scheduler

   # Stop scheduler
   docker compose down
   ```

3. **Run on-demand CLI tasks via Docker:**
   ```bash
   # Run direct scrape without LLM
   docker compose run --rm runner python main.py simple

   # Run full CrewAI pipeline
   docker compose run --rm runner python main.py crewai

   # Run auto-apply on top matching jobs
   docker compose run --rm runner python main.py apply

   # Run auto-apply with automated Playwright form filling
   docker compose run --rm runner python main.py apply --playwright

   # Run application tracker CLI
   docker compose run --rm runner python track.py --stats

   # Run pytest test suite inside container
   docker compose run --rm runner python -m pytest tests/
   ```

---

## Quick Test Commands

```bash
# Test scraper
python -c "from agents.scrapper import scrape_all; jobs = scrape_all(debug=False); print(f'{len(jobs)} jobs found')"

# Test sheet connection
python -c "from tools.sheet_writer import test_connection; test_connection()"

# Run cleanup + formatting on all sheets
python tools/sheet_writer.py --cleanup
python tools/sheet_writer.py --cleanup 60   # custom age threshold

# Test CV matching
python -c "from tools.cv_parser import parse_cv; profile = parse_cv('my_cv.pdf'); print(profile)"

# Test cover letter
python -c "from agents.gemini_tools import generate_cover_letter; cl = generate_cover_letter('Full Stack Developer', 'Acme Corp', 'Node.js React role', 'Mubashir'); print(cl[:200])"

# Build CV embeddings for semantic matching (correct PDF text extraction)
python -m tools.embedding_matcher
# or: python -c "from tools.embedding_matcher import build_cv_index_from_file; build_cv_index_from_file('my_cv.pdf')"
```

---

## License

MIT
