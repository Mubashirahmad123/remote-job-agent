# 🚀 Remote Job Agent — Upgrade Guide

A complete guide to upgrading your scraper from basic `requests + BeautifulSoup` to a
multi-source, anti-block system using free tools.

---

## 📋 Table of Contents

1. [What's Changing & Why](#whats-changing--why)
2. [Prerequisites](#prerequisites)
3. [Step 1 — Install All Tools](#step-1--install-all-tools)
4. [Step 2 — Free Job APIs (No Crawling Needed)](#step-2--free-job-apis-no-crawling-needed)
5. [Step 3 — JobSpy Setup](#step-3--jobspy-setup)
6. [Step 4 — Playwright + Stealth Setup](#step-4--playwright--stealth-setup)
7. [Step 5 — Crawl4AI Setup](#step-5--crawl4ai-setup)
8. [Step 6 — Adzuna API Key (Free)](#step-6--adzuna-api-key-free)
9. [Full Source Map](#full-source-map)
10. [Updated .env](#updated-env)
11. [Folder Structure After Upgrade](#folder-structure-after-upgrade)
12. [Quick Test Commands](#quick-test-commands)
13. [Troubleshooting](#troubleshooting)

---

## ❓ What's Changing & Why

### Current Problem
Your existing `scrapper.py` uses `requests` + `BeautifulSoup` on sites like
WeWorkRemotely, Remote.co, Wellfound, and NoDesk. These sites use Cloudflare and
similar anti-bot systems that block plain HTTP scrapers instantly — which is why
jobs are not being found reliably.

### The Fix — 3 Layers

| Layer | Tools | Sources |
|---|---|---|
| **Layer 1** — Free APIs | `requests` | Remotive, RemoteOK, Arbeitnow, Himalayas, Jobicy, The Muse, Adzuna |
| **Layer 2** — Job Library | `JobSpy` | LinkedIn, Indeed, Glassdoor, Google Jobs, ZipRecruiter |
| **Layer 3** — Stealth Browser | `Playwright + stealth` | WeWorkRemotely, Remote.co, Wellfound, NoDesk |
| **Layer 4** — AI Crawler | `Crawl4AI` | JustRemote + any new sites |

---

## ✅ Prerequisites

Make sure you have these already:
- Python 3.11+
- Virtual environment activated (`venv\Scripts\activate` on Windows)
- Existing `.env` file with your keys
- Node.js (only needed if you use docx generation elsewhere)

---

## Step 1 — Install All Tools

Run these commands one by one inside your activated virtual environment:

```bash
# Layer 1 — already installed, keep as is
pip install requests beautifulsoup4

# Layer 2 — JobSpy (LinkedIn, Indeed, Glassdoor, Google Jobs, ZipRecruiter)
pip install python-jobspy

# Layer 3 — Playwright stealth browser
pip install playwright
pip install playwright-stealth

# Install the actual Chromium browser (one-time, ~150MB)
playwright install chromium

# Layer 4 — Crawl4AI (AI-native crawler)
pip install crawl4ai

# Run Crawl4AI setup (downloads models, one-time)
crawl4ai-setup
```

### ✅ Verify Installations

```bash
python -c "from jobspy import scrape_jobs; print('JobSpy OK')"
python -c "from playwright.sync_api import sync_playwright; print('Playwright OK')"
python -c "import crawl4ai; print('Crawl4AI OK')"
```

---

## Step 2 — Free Job APIs (No Crawling Needed)

These require zero API keys and will never block you. Use them as your primary sources.

### Already in your project (keep):

| Source | Endpoint |
|---|---|
| Remotive | `https://remotive.com/api/remote-jobs?category=software-dev&limit=100` |
| RemoteOK | `https://remoteok.com/api` |
| Arbeitnow | `https://www.arbeitnow.com/api/job-board-api` |

### New ones to add:

| Source | Endpoint | Auth |
|---|---|---|
| **Himalayas** | `https://himalayas.app/api/jobs?limit=100` | None |
| **Jobicy** | `https://jobicy.com/api/v0/remote-jobs?count=50&tag=developer` | None |
| **The Muse** | `https://www.themuse.com/api/public/jobs?page=1&level=Entry+Level&level=Mid+Level` | None |
| **Adzuna** | `https://api.adzuna.com/v1/api/jobs/gb/search/1?app_id=YOUR_ID&app_key=YOUR_KEY&what=developer+remote` | Free key (see Step 6) |

### Example — Adding Himalayas API

```python
import requests

def scrape_himalayas():
    url = "https://himalayas.app/api/jobs?limit=100"
    response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
    data = response.json()
    jobs = []
    for job in data.get("jobs", []):
        jobs.append({
            "job_title": job.get("title"),
            "company": job.get("company", {}).get("name"),
            "salary": job.get("salary", ""),
            "tech_stack": ", ".join(job.get("tags", [])),
            "timezone": "Remote",
            "apply_url": job.get("url"),
            "summary": job.get("description", "")[:300],
            "posted_date_iso": job.get("createdAt", ""),
            "source": "Himalayas"
        })
    return jobs
```

### Example — Adding Jobicy API

```python
def scrape_jobicy():
    url = "https://jobicy.com/api/v0/remote-jobs?count=50&tag=developer"
    response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
    data = response.json()
    jobs = []
    for job in data.get("jobs", []):
        jobs.append({
            "job_title": job.get("jobTitle"),
            "company": job.get("companyName"),
            "salary": job.get("annualSalaryMin", ""),
            "tech_stack": ", ".join(job.get("jobIndustry", [])),
            "timezone": "Remote",
            "apply_url": job.get("url"),
            "summary": job.get("jobExcerpt", ""),
            "posted_date_iso": job.get("pubDate", ""),
            "source": "Jobicy"
        })
    return jobs
```

---

## Step 3 — JobSpy Setup

JobSpy scrapes LinkedIn, Indeed, Glassdoor, Google Jobs, and ZipRecruiter in one call.
These are major job boards your current project is NOT hitting at all.

### Basic Usage

```python
from jobspy import scrape_jobs
import pandas as pd

def scrape_with_jobspy():
    jobs_df = scrape_jobs(
        site_name=["linkedin", "indeed", "glassdoor", "google", "zip_recruiter"],
        search_term="backend developer OR fullstack developer OR node.js developer",
        location="remote",
        results_wanted=30,          # per site
        is_remote=True,
        job_type="fulltime",
        delay_between_requests=3,   # IMPORTANT: avoid 429 blocks
    )

    jobs = []
    for _, row in jobs_df.iterrows():
        jobs.append({
            "job_title": row.get("title", ""),
            "company": row.get("company", ""),
            "salary": f"{row.get('min_amount', '')} - {row.get('max_amount', '')}",
            "tech_stack": row.get("description", "")[:100],
            "timezone": "Remote",
            "apply_url": row.get("job_url", ""),
            "summary": row.get("description", "")[:300],
            "posted_date_iso": str(row.get("date_posted", "")),
            "source": row.get("site", "JobSpy")
        })
    return jobs
```

### Notes
- If you get `429 Too Many Requests`, increase `delay_between_requests` to `5` or `10`
- Run JobSpy scrapes at different times than your API scrapes
- LinkedIn is the most aggressive blocker — set `results_wanted=15` for LinkedIn specifically

---

## Step 4 — Playwright + Stealth Setup

Use this for HTML-based sites that block plain requests:
WeWorkRemotely, Remote.co, Wellfound, NoDesk

### Basic Template

```python
from playwright.sync_api import sync_playwright
from playwright_stealth import stealth_sync
import time

def scrape_weworkremotely():
    jobs = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Apply stealth patches — makes the browser undetectable
        stealth_sync(page)

        page.goto("https://weworkremotely.com/categories/remote-programming-jobs")

        # Wait for jobs to load
        page.wait_for_selector("section.jobs", timeout=10000)

        job_elements = page.query_selector_all("li.feature")
        for el in job_elements:
            title = el.query_selector("span.title")
            company = el.query_selector("span.company")
            link = el.query_selector("a")

            jobs.append({
                "job_title": title.inner_text() if title else "",
                "company": company.inner_text() if company else "",
                "salary": "",
                "tech_stack": "",
                "timezone": "Remote",
                "apply_url": "https://weworkremotely.com" + link.get_attribute("href") if link else "",
                "summary": "",
                "posted_date_iso": "",
                "source": "WeWorkRemotely"
            })

        browser.close()
    return jobs
```

### Important Tips for Playwright
- Always use `headless=True` in production
- Add `time.sleep(2)` between page navigations
- Use `page.wait_for_selector()` instead of fixed sleeps where possible
- Rotate User-Agent if you get blocked repeatedly

---

## Step 5 — Crawl4AI Setup

Crawl4AI is an AI-native crawler that returns clean markdown — perfect for
feeding into your Gemini agent for extraction.

### Basic Usage

```python
import asyncio
from crawl4ai import AsyncWebCrawler

async def scrape_justremote():
    async with AsyncWebCrawler(verbose=False) as crawler:
        result = await crawler.arun(
            url="https://justremote.co/remote-developer-jobs",
            word_count_threshold=10,
            bypass_cache=True
        )
        # result.markdown contains clean text ready for Gemini
        return result.markdown

# Run it
markdown_content = asyncio.run(scrape_justremote())

# Then pass markdown_content to Gemini for extraction
```

### Using with Gemini (in your gemini_tools.py)

```python
import google.generativeai as genai

def extract_jobs_from_markdown(markdown: str) -> list:
    model = genai.GenerativeModel("gemini-2.5-flash")
    prompt = f"""
    Extract all job listings from the following content.
    Return a JSON array with fields: job_title, company, salary, tech_stack, apply_url, summary.
    Only include software/developer jobs. Skip senior/lead/manager roles.

    Content:
    {markdown[:8000]}

    Return ONLY valid JSON, no explanation.
    """
    response = model.generate_content(prompt)
    import json
    return json.loads(response.text)
```

---

## Step 6 — Adzuna API Key (Free)

Adzuna gives 250 free requests/day — no credit card required.

1. Go to: `https://developer.adzuna.com/signup`
2. Sign up for a free account
3. Get your `app_id` and `app_key`
4. Add to your `.env`:

```env
ADZUNA_APP_ID=your_app_id_here
ADZUNA_APP_KEY=your_app_key_here
```

### Usage

```python
import os, requests

def scrape_adzuna():
    app_id = os.getenv("ADZUNA_APP_ID")
    app_key = os.getenv("ADZUNA_APP_KEY")
    url = (
        f"https://api.adzuna.com/v1/api/jobs/gb/search/1"
        f"?app_id={app_id}&app_key={app_key}"
        f"&what=developer+remote&results_per_page=50&content-type=application/json"
    )
    response = requests.get(url)
    data = response.json()
    jobs = []
    for job in data.get("results", []):
        jobs.append({
            "job_title": job.get("title"),
            "company": job.get("company", {}).get("display_name"),
            "salary": f"{job.get('salary_min', '')} - {job.get('salary_max', '')}",
            "tech_stack": "",
            "timezone": "Remote",
            "apply_url": job.get("redirect_url"),
            "summary": job.get("description", "")[:300],
            "posted_date_iso": job.get("created"),
            "source": "Adzuna"
        })
    return jobs
```

---

## 🗺️ Full Source Map

| # | Source | Method | Free | Auth Needed |
|---|---|---|---|---|
| 1 | Remotive | Free API | ✅ | None |
| 2 | RemoteOK | Free API | ✅ | None |
| 3 | Arbeitnow | Free API | ✅ | None |
| 4 | Himalayas | Free API | ✅ | None |
| 5 | Jobicy | Free API | ✅ | None |
| 6 | The Muse | Free API | ✅ | None |
| 7 | Adzuna | Free API | ✅ | Free key |
| 8 | LinkedIn | JobSpy | ✅ | None |
| 9 | Indeed | JobSpy | ✅ | None |
| 10 | Glassdoor | JobSpy | ✅ | None |
| 11 | Google Jobs | JobSpy | ✅ | None |
| 12 | ZipRecruiter | JobSpy | ✅ | None |
| 13 | WeWorkRemotely | Playwright + stealth | ✅ | None |
| 14 | Remote.co | Playwright + stealth | ✅ | None |
| 15 | Wellfound | Playwright + stealth | ✅ | None |
| 16 | NoDesk | Playwright + stealth | ✅ | None |
| 17 | JustRemote | Crawl4AI | ✅ | None |

**Total: 17 sources, all free, ~500–800 jobs per run**

---

## 🔧 Updated .env

Add these new variables to your existing `.env` file:

```env
# --- Existing ---
GOOGLE_SHEETS_ID=your_google_sheet_id
GOOGLE_SERVICE_ACCOUNT=keys.json
GEMINI_API_KEY=your_gemini_api_key
MODEL=gemini/gemini-2.5-flash
RUN_MODE=crewai

# --- New ---
ADZUNA_APP_ID=your_adzuna_app_id
ADZUNA_APP_KEY=your_adzuna_app_key

# Scraper settings
JOBSPY_RESULTS_PER_SITE=20
JOBSPY_DELAY=3
PLAYWRIGHT_HEADLESS=true
```

---

## 📁 Folder Structure After Upgrade

```
remote-job-agent/
├── agents/
│   ├── __init__.py
│   ├── scrapper.py          # UPDATED — now uses all 17 sources
│   ├── curator.py           # unchanged
│   └── gemini_tools.py      # UPDATED — added extract_jobs_from_markdown()
├── tools/
│   ├── sheet_writer.py      # unchanged
│   ├── scraper_utils.py     # unchanged
│   ├── jobspy_scraper.py    # NEW — JobSpy wrapper
│   ├── playwright_scraper.py # NEW — Stealth browser scraper
│   └── crawl4ai_scraper.py  # NEW — AI-native crawler
├── cover_letters/
├── logs/
├── main.py
├── scheduler.py
├── requirements.txt         # UPDATED — see below
├── .env
├── .env.example
├── keys.json
└── scraped_jobs.json
```

---

## 📦 Updated requirements.txt

Replace your `requirements.txt` with this:

```
# Core
requests==2.31.0
beautifulsoup4==4.12.3
python-dotenv==1.0.0

# AI / CrewAI
crewai==0.28.0
google-generativeai==0.5.4
litellm==1.35.0

# Job Scraping — NEW
python-jobspy==1.1.4
playwright==1.44.0
playwright-stealth==1.0.6
crawl4ai==0.3.74

# Google Sheets
gspread==6.1.0
google-auth==2.29.0

# PDF generation
reportlab==4.1.0
fpdf2==2.7.9

# Scheduling
apscheduler==3.10.4
```

After updating, run:
```bash
pip install -r requirements.txt
playwright install chromium
crawl4ai-setup
```

---

## ⚡ Quick Test Commands

Test each layer individually before running the full pipeline:

```bash
# Test JobSpy
python -c "
from jobspy import scrape_jobs
jobs = scrape_jobs(site_name=['indeed'], search_term='python developer', location='remote', results_wanted=5, is_remote=True)
print(f'JobSpy found: {len(jobs)} jobs')
print(jobs[['title','company','location']].head())
"

# Test Himalayas API
python -c "
import requests
r = requests.get('https://himalayas.app/api/jobs?limit=5')
data = r.json()
print(f'Himalayas found: {len(data[\"jobs\"])} jobs')
"

# Test Jobicy API
python -c "
import requests
r = requests.get('https://jobicy.com/api/v0/remote-jobs?count=5&tag=developer')
data = r.json()
print(f'Jobicy found: {len(data[\"jobs\"])} jobs')
"

# Test Playwright
python -c "
from playwright.sync_api import sync_playwright
from playwright_stealth import stealth_sync
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    stealth_sync(page)
    page.goto('https://weworkremotely.com')
    print('Playwright OK — page title:', page.title())
    browser.close()
"

# Test Crawl4AI
python -c "
import asyncio
from crawl4ai import AsyncWebCrawler
async def test():
    async with AsyncWebCrawler() as c:
        r = await c.arun(url='https://justremote.co/remote-developer-jobs')
        print('Crawl4AI OK — chars scraped:', len(r.markdown))
asyncio.run(test())
"
```

---

## 🐛 Troubleshooting

### JobSpy returns 0 jobs
- Add `delay_between_requests=5`
- Try one site at a time: `site_name=["indeed"]`
- Check your internet connection

### Playwright crashes or times out
- Make sure `playwright install chromium` was run
- Increase timeout: `page.wait_for_selector("...", timeout=20000)`
- Try `headless=False` to see what's happening visually

### Crawl4AI setup fails
- Run `crawl4ai-setup` separately after install
- If it fails, try: `python -m crawl4ai.install`

### Himalayas / Jobicy return empty
- Check the API URL is correct — these APIs occasionally change structure
- Add `print(data.keys())` to debug the response shape

### Getting blocked on WeWorkRemotely
- Add `time.sleep(3)` between page loads
- Rotate User-Agent in the Playwright page context:
  ```python
  page = browser.new_page(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
  ```

---

## 🧠 Next Steps After Setup

Once all tools are installed and tested:

1. **Rewrite `scrapper.py`** — combine all 17 sources into one unified function
2. **Update the Curator agent** — add timezone scoring for India-friendly jobs (UTC+5:30)
3. **Improve Gemini ranking** — pass job summaries to Gemini and score 1–10 for fit
4. **Add salary filter** — skip jobs with no salary or clearly US-local only pay

---

*Last updated: June 2026 | Author: Mubashir*