# Remote Job Agent

An automated system that scrapes 30+ remote job boards, matches jobs to your CV using AI, and saves curated results to Google Sheets — all running on a scheduled cron.

---

## Features

| Feature | Status | Description |
|---|---|---|---|---|
| Multi-source scraping | ✅ | 45+ job boards via APIs, HTML parsing, Playwright stealth, JobSpy, and Crawl4AI |
| **Smart job filters** | ✅ | Only web/software dev roles — excludes ML, AI, Network, DevOps, SRE, Security, QA, Game, Blockchain, Embedded, Salesforce, and senior/lead roles |
| CV-based job matching | ✅ | Parses your PDF/DOCX CV via Gemini, local keyword scoring (no API calls per job) |
| **Semantic job matching** | ✅ | Optional FAISS + sentence-transformers for cosine-similarity scoring (catches synonyms) — `pip install sentence-transformers faiss-cpu` |
| Duplicate detection | ✅ | MD5 fingerprinting prevents duplicate entries across runs |
| Smart Sheets dashboard | ✅ | Auto-creates tabs: ALL JOBS, TOP MATCHES (score ≥85), GOOD MATCHES (70–84), APPLIED, STATS — with colored score bands, hyperlinks, frozen headers |
| **AI cover letters with role detection** | ✅ | Detects backend/frontend/fullstack/mobile role from job title and tailors tone, skills, and experience accordingly |
| **LLM fallback chain** | ✅ | Gemini → GLM-4 (Zhipu) → Ollama (local) — pipeline never crashes from API quota errors |
| **Auto-apply pipeline** | ✅ | Generates tailored resume + cover letter, opens apply URL in browser or auto-fills Greenhouse/Lever via Playwright, tracks in APPLIED sheet |
| **Tailored resume generation** | ✅ | Generates ATS-optimized resume PDF matched to each job's tech stack `python main.py resume` |
| **Country/location logging** | ✅ | 386-country location tracking with non-blocking allows all regions |
| **Cross-platform Unicode PDFs** | ✅ | Auto-downloads DejaVu fonts — works on Windows/macOS/Linux; covers accents, Arabic, Cyrillic |
| Application tracker | ✅ | `track.py` CLI + `tools/application_tracker.py` — mark applied, update status, list, stats, follow-up reminders |
| Auto-cleanup old jobs | ✅ | Removes jobs older than 30 days from all sheets (including legacy `LIVE Remote Jobs Tracker`) |
| Sheet formatting (Google Sheets) | ✅ | Auto-applies colored score bands, clickable hyperlinks, wrapped text, column widths via Google Sheets API |
| Sheet formatting (xlsx export) | ✅ | `format_jobs_xlsx.py` — professional Excel formatting with same visual style |
| Standalone cleanup CLI | ✅ | `python tools/sheet_writer.py --cleanup [days]` — run cleanup + formatting anytime |
| Excel cleanup + format | ✅ | `clean_jobs.py` — extracts company from URLs, strips HTML, deduplicates tags, removes senior roles; `format_jobs_xlsx.py` — professional xlsx formatting |
| Playwright stealth scraper | ✅ | Scrapes Cloudflare-protected boards (WeWorkRemotely, Remote.co, Wellfound, NoDesk) |
| Crawl4AI scraper | ✅ | AI-native crawler for JustRemote |
| JobSpy integration | ✅ | Scrapes LinkedIn, Indeed, Glassdoor, Google Jobs, ZipRecruiter |
| Scheduled automation | ✅ | Cron-based scheduler (Mon/Thu full scrape, daily quick checks) |
| Universal run script | ✅ | `Run.py` works on Windows / Mac / Linux with `--setup` flag |
| Docker support | 🛠️ | Basic Dockerfile included (requires Playwright + Crawl4AI setup) |

---

## Prerequisites

- Python 3.11+
- A Google Cloud service account (for Sheets API) → save as `keys.json`
- A Gemini API key
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

Or step by step:

```bash
python -m venv venv
.\venv\Scripts\activate    # Windows
# source venv/bin/activate  # Mac/Linux
uv pip install -r requirements.txt
playwright install chromium
python -m crawl4ai.install
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
│   ├── gemini_tools.py       # Cover letters with LLM fallback (Gemini→GLM→Ollama)
│   └── auto_applier.py       # Auto-apply: resume + cover letter + Playwright form fill
├── tools/
│   ├── __init__.py
│   ├── cv_parser.py           # PDF/DOCX CV → structured profile via Gemini
│   ├── cv_matcher.py          # Local keyword job scoring (no API calls)
│   ├── deduplicator.py        # MD5 fingerprint duplicate detection
│   ├── embedding_matcher.py   # Optional FAISS semantic scoring (Phase 2)
│   ├── font_utils.py          # Cross-platform Unicode PDF font resolution (auto-downloads DejaVu)
│   ├── sheet_writer.py        # Google Sheets dashboard (5 tabs) + 30-day auto-cleanup
│   ├── resume_generator.py    # AI-tailored resume PDF per job
│   ├── jobspy_scraper.py      # LinkedIn, Indeed, Glassdoor, Google Jobs, ZipRecruiter
│   ├── playwright_scraper.py  # Stealth browser scraping (WWR, Remote.co, Wellfound, NoDesk)
│   ├── crawl4ai_scraper.py    # AI-native Crawl4AI scraper for JustRemote
│   ├── scraper_utils.py       # Text cleaning, date parsing utilities
│   └── application_tracker.py # APPLIED sheet management (mark, update, list, stats)
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
MODEL=gemini/gemini-2.5-flash
RUN_MODE=crewai          # crewai | simple | test | apply | resume

# Job Scraping
ADZUNA_APP_ID=your_id
ADZUNA_APP_KEY=your_key
JOBSPY_RESULTS_PER_SITE=20
JOBSPY_DELAY=3
PLAYWRIGHT_HEADLESS=true

# CV Matching
CV_PATH=my_cv.pdf
MIN_MATCH_SCORE=70

# Location / Country Filter
ALLOWED_COUNTRIES=uk,united kingdom,new zealand,nz,usa,united states

# LLM Fallback (optional — GLM-4 and Ollama for when Gemini hits rate limits)
GLM_API_KEY=
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=llama3.1

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
30+ Job Boards
     │
     ▼
  agents/scrapper.py     ◄── API calls, HTML parse, Playwright, JobSpy, Crawl4AI
     │                   ──   (called by merged Scraper+Curator agent)
     ▼
  agents/curator.py       ◄── Dedup → CV score (local + optional semantic) → quality rank → Sheets
     │                    ──   (called by merged Scraper+Curator agent)
     ├─ tools/deduplicator.py    (MD5 fingerprinting)
     ├─ tools/cv_parser.py       (Gemini CV → profile)
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
| Playwright stealth | WeWorkRemotely, Remote.co, Wellfound, NoDesk |
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

## Docker

```bash
docker build -t remote-job-agent .
docker run --env-file .env remote-job-agent
```

> **Note:** The Dockerfile is a starting point. You may need to install Playwright browsers (`playwright install chromium`) and run `crawl4ai.install` inside the container for full functionality.

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

# Build CV embeddings for semantic matching
python -c "from tools.embedding_matcher import build_cv_index; build_cv_index(open('my_cv.pdf','rb').read().decode('utf-8','ignore'))"
```

---

## License

MIT
