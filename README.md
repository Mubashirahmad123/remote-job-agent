# Remote Job Agent

An automated system that scrapes 30+ remote job boards, matches jobs to your CV using AI, and saves curated results to Google Sheets — all running on a scheduled cron.

---

## Features

| Feature | Status | Description |
|---|---|---|
| Multi-source scraping | ✅ | 45+ job boards via APIs, HTML parsing, Playwright stealth, JobSpy, and Crawl4AI |
| Dev-only job filter | ✅ | Strips non-dev, senior/lead, and irrelevant roles automatically |
| CV-based job matching | ✅ | Parses your PDF/DOCX CV via Gemini, local keyword scoring (no API calls per job) |
| Duplicate detection | ✅ | MD5 fingerprinting prevents duplicate entries across runs |
| Smart Sheets dashboard | ✅ | Auto-creates tabs: ALL JOBS, TOP MATCHES (score ≥85), GOOD MATCHES (70–84), APPLIED, STATS |
| AI cover letters | ✅ | Generates job-specific cover letters with PDF export |
| Application tracker | ✅ | `track.py` CLI + `tools/application_tracker.py` — mark applied, update status, list, stats, follow-up reminders |
| Auto-cleanup old jobs | ✅ | Removes jobs older than 30 days from sheets automatically |
| Excel cleanup | ✅ | `clean_jobs.py` — extracts company from URLs, strips HTML, deduplicates tags, removes senior roles from xlsx exports |
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

---

## Project Structure

```
remote-job-agent/
├── agents/
│   ├── __init__.py
│   ├── scrapper.py           # 45+ job board scrapers (API, HTML, RSS)
│   ├── curator.py            # Dedup, CV matching, quality ranking, sheet save
│   └── gemini_tools.py       # Gemini cover letter generation, markdown extraction
├── tools/
│   ├── __init__.py
│   ├── cv_parser.py           # PDF/DOCX CV → structured profile via Gemini
│   ├── cv_matcher.py          # Local keyword job scoring (no API calls)
│   ├── deduplicator.py        # MD5 fingerprint duplicate detection
│   ├── sheet_writer.py        # Google Sheets dashboard (5 tabs) + 30-day auto-cleanup
│   ├── jobspy_scraper.py      # LinkedIn, Indeed, Glassdoor, Google Jobs, ZipRecruiter
│   ├── playwright_scraper.py  # Stealth browser scraping (WWR, Remote.co, Wellfound, NoDesk)
│   ├── crawl4ai_scraper.py    # AI-native Crawl4AI scraper for JustRemote
│   ├── scraper_utils.py       # Text cleaning, date parsing utilities
│   └── application_tracker.py # APPLIED sheet management (mark, update, list, stats)
├── clean_jobs.py             # Excel cleanup: extract company, strip HTML, dedup tags, remove senior roles
├── track.py                  # Application tracker CLI (mark applied, status, list, stats, followups)
├── cover_letters/            # Generated PDF cover letters
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
RUN_MODE=crewai

# Job Scraping
ADZUNA_APP_ID=your_id
ADZUNA_APP_KEY=your_key
JOBSPY_RESULTS_PER_SITE=20
JOBSPY_DELAY=3
PLAYWRIGHT_HEADLESS=true

# CV Matching
CV_PATH=my_cv.pdf
MIN_MATCH_SCORE=70
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
  agents/curator.py       ◄── Dedup → CV score (local) → quality rank → Sheets
     │                    ──   (called by merged Scraper+Curator agent)
     ├─ tools/deduplicator.py    (MD5 fingerprinting)
     ├─ tools/cv_parser.py       (Gemini CV → profile)
     ├─ tools/cv_matcher.py      (Local keyword scoring, no API calls)
     └─ tools/sheet_writer.py    (Google Sheets dashboard + 30-day cleanup)
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

## Excel Cleanup

Clean exported xlsx from Google Sheets (extract company from URLs, strip HTML, dedup tags, remove senior roles):

```bash
python clean_jobs.py
python clean_jobs.py --input "my_export.xlsx" --output "cleaned.xlsx" --keep-senior
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

# Test CV matching
python -c "from tools.cv_parser import parse_cv; profile = parse_cv('my_cv.pdf'); print(profile)"

# Test cover letter
python -c "from agents.gemini_tools import generate_cover_letter; cl = generate_cover_letter('Full Stack Developer', 'Acme Corp', 'Node.js React role', 'Mubashir'); print(cl[:200])"
```

---

## License

MIT
