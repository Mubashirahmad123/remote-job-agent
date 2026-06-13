# 🚀 Remote Job Agent — Production Roadmap

Everything needed to go from "it scrapes jobs" to "it finds the RIGHT jobs for ME".

---

## 🚨 TOP PRIORITY — Do These First

### Priority 0A — CV Upload + Job Matching

**The Problem:**
Agent has no idea who you are. It saves every job regardless of fit.
You end up manually reading 200 jobs to find 5 relevant ones.

**The Fix:**
Upload your CV (PDF or DOCX) once → Gemini parses it → every scraped job
gets scored 0–100 against your actual skills → only high-score jobs saved to Sheets.

**Files to create:**
- `tools/cv_parser.py` — reads your CV file, extracts structured profile using Gemini
- `tools/cv_matcher.py` — scores each job against your CV profile

**Step 1 — Install CV reading library:**
```bash
pip install pdfplumber python-docx
```

**Step 2 — Add your CV to the project root:**
```
remote-job-agent/
├── my_cv.pdf        ← drop your CV here
├── main.py
├── run.py
...
```

**Step 3 — Add to `.env`:**
```env
CV_PATH=my_cv.pdf
MIN_MATCH_SCORE=70
```

**Step 4 — `tools/cv_parser.py`:**
```python
import pdfplumber
import docx
import google.generativeai as genai
import json
import os

def extract_cv_text(cv_path: str) -> str:
    """Extract raw text from PDF or DOCX CV"""
    if cv_path.endswith(".pdf"):
        with pdfplumber.open(cv_path) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages)
    elif cv_path.endswith(".docx"):
        doc = docx.Document(cv_path)
        return "\n".join(p.text for p in doc.paragraphs)
    else:
        raise ValueError("CV must be a .pdf or .docx file")

def parse_cv(cv_path: str) -> dict:
    """Parse CV into structured profile using Gemini"""
    text = extract_cv_text(cv_path)

    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    model = genai.GenerativeModel("gemini-2.0-flash")

    prompt = f"""
    Extract structured data from this CV. Return ONLY valid JSON, no explanation:
    {{
        "name": "",
        "years_experience": 0,
        "skills": [],
        "frameworks": [],
        "databases": [],
        "preferred_titles": [],
        "seniority": "junior or mid",
        "languages": []
    }}

    CV TEXT:
    {text[:4000]}
    """
    response = model.generate_content(prompt)
    raw = response.text.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)
```

**Step 5 — `tools/cv_matcher.py`:**
```python
import google.generativeai as genai
import json
import os

def score_job(job: dict, cv_profile: dict) -> tuple[int, str]:
    """Score a job 0-100 against the candidate CV profile"""
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    model = genai.GenerativeModel("gemini-2.0-flash")

    prompt = f"""
    Score this job listing from 0-100 based on fit with this candidate.

    CANDIDATE:
    - Skills: {', '.join(cv_profile.get('skills', []))}
    - Frameworks: {', '.join(cv_profile.get('frameworks', []))}
    - Experience: {cv_profile.get('years_experience', 0)} years
    - Seniority: {cv_profile.get('seniority', 'mid')}
    - Looking for: {', '.join(cv_profile.get('preferred_titles', []))}

    JOB:
    - Title: {job.get('job_title', '')}
    - Company: {job.get('company', '')}
    - Tech Stack: {job.get('tech_stack', '')}
    - Summary: {job.get('summary', '')[:400]}

    Scoring:
    - 90-100: Perfect match
    - 70-89:  Good match
    - 50-69:  Partial match
    - 0-49:   Poor match or too senior

    Return ONLY JSON: {{"score": 85, "reason": "Matches Node.js, React, mid-level remote"}}
    """
    response = model.generate_content(prompt)
    raw = response.text.replace("```json", "").replace("```", "").strip()
    result = json.loads(raw)
    return result["score"], result["reason"]
```

**Step 6 — Use in `agents/curator.py`:**
```python
from tools.cv_parser import parse_cv
from tools.cv_matcher import score_job
import os

# Parse CV once at startup
CV_PROFILE = parse_cv(os.getenv("CV_PATH", "my_cv.pdf"))
MIN_SCORE  = int(os.getenv("MIN_MATCH_SCORE", 70))

def curate_jobs(jobs: list) -> list:
    matched = []
    for job in jobs:
        score, reason = score_job(job, CV_PROFILE)
        job["match_score"]  = score
        job["match_reason"] = reason
        if score >= MIN_SCORE:
            matched.append(job)
    # Sort best first
    return sorted(matched, key=lambda x: x["match_score"], reverse=True)
```

**New Google Sheet columns after this change:**
```
job_title | company | salary | tech_stack | apply_url |
summary | posted_date | source | match_score | match_reason
```

---

### Priority 0B — Fix Job Filter (Only Dev Jobs, No Noise)

**The Problem:**
`agents/scrapper.py` saves ALL jobs — marketing, design, sales, support —
not just developer roles. You're wasting time filtering manually.

**The Fix — Strict tech-only filter in `agents/scrapper.py`:**

```python
import re

# ── Strict dev job title filter ───────────────────────────────────────────────
DEV_TITLE_FILTER = re.compile(r"""(?ix)
    (
        developer | engineer | programmer | backend | frontend | fullstack |
        full.stack | full\ stack | devops | sre | swe | software |
        node\.?js | django | react | python | typescript | javascript |
        api\ developer | web\ developer | mobile\ developer | cloud\ engineer |
        data\ engineer | ml\ engineer | platform\ engineer | site\ reliability
    )
""")

# ── Exclude non-dev roles entirely ───────────────────────────────────────────
NON_DEV_FILTER = re.compile(r"""(?ix)
    (
        marketing | sales | designer | copywriter | accountant | finance |
        recruiter | hr\ | human\ resources | customer\ success | customer\ support |
        content\ writer | seo | social\ media | product\ manager | project\ manager |
        data\ analyst | business\ analyst | operations\ manager | office\ manager |
        graphic\ design | ui\ designer | ux\ designer | illustrator
    )
""")

# ── Exclude senior/lead roles ─────────────────────────────────────────────────
SENIORITY_FILTER = re.compile(r"""(?ix)
    \b(
        senior | sr\. | lead | principal | staff | architect |
        director | manager | vp | head\ of | cto | ceo
    )\b
""")

def is_valid_dev_job(job: dict) -> bool:
    title = job.get("job_title", "").lower()
    stack = job.get("tech_stack", "").lower()
    combined = title + " " + stack

    # Must match a dev keyword
    if not DEV_TITLE_FILTER.search(title):
        return False

    # Must not be a non-dev role
    if NON_DEV_FILTER.search(title):
        return False

    # Must not be senior/lead
    if SENIORITY_FILTER.search(title):
        return False

    return True

# ── Use in your scrape_all() function ────────────────────────────────────────
def scrape_all() -> list:
    raw_jobs = []
    # ... your existing scraping calls ...

    # Apply filter before returning
    filtered = [job for job in raw_jobs if is_valid_dev_job(job)]
    print(f"Filtered: {len(raw_jobs)} total → {len(filtered)} dev jobs")
    return filtered
```

---

## 🏁 Updated Priority Order

| Priority | Feature | Impact | Effort |
|---|---|---|---|
| 🔴 0A | CV Upload + Job Matching | Finds jobs matched to YOU | Medium |
| 🔴 0B | Fix Job Filter (dev only) | Kills noise immediately | Low |
| 🔴 1 | Duplicate Detection | No repeat listings | Low |
| 🟡 2 | Telegram Notifications | Instant top-match alerts | Low |
| 🟡 3 | Smart Sheet Structure | Better visibility | Low |
| 🟡 4 | Smarter Cover Letters | Job-specific, not generic | Medium |
| 🟢 5 | Timezone Scoring | India-friendly async roles | Low |
| 🟢 6 | Smart Scheduler | Daily quick API checks | Low |
| 🟢 7 | Application Tracker | Track your pipeline | Medium |

---

## 🔑 How to Run (Any OS)

```bash
# First time setup
python run.py --setup

# Every time after
python run.py
```

Works on Windows, Mac, and Linux. No .bat files needed.

---

## 🧠 Feature 1 — CV-Based Job Matching (Most Important)

### The Problem Right Now
Your agent scrapes jobs and saves them all to Sheets — but it has no idea
what's actually relevant to YOU. You're manually reading 200 jobs to find 5 good ones.

### The Fix — CV Embeddings + Semantic Scoring

**How it works:**
1. Parse your CV once → extract skills, experience, titles, stack
2. For each scraped job → generate a match score (0–100) using Gemini
3. Only save jobs with score > 70 to Google Sheets
4. Add a `match_score` column so you see the best ones first

**What to build — `tools/cv_matcher.py`:**

```python
import google.generativeai as genai
import json

CV_TEXT = """
Name: Mubashir
Experience: 2.8 years
Stack: Node.js, Express, Django, PostgreSQL, MongoDB, React, TypeScript
Role: Full Stack / Backend Engineer
Seniority: Mid-level (NOT senior, NOT lead)
"""

def score_job(job: dict) -> int:
    model = genai.GenerativeModel("gemini-2.0-flash")
    prompt = f"""
    Score this job listing from 0-100 based on how well it matches this candidate.

    CANDIDATE:
    {CV_TEXT}

    JOB:
    Title: {job['job_title']}
    Company: {job['company']}
    Tech Stack: {job['tech_stack']}
    Summary: {job['summary'][:500]}

    Scoring rules:
    - 90-100: Perfect match (right stack, right level, remote, good salary)
    - 70-89:  Good match (most requirements met)
    - 50-69:  Partial match (some stack overlap)
    - 0-49:   Poor match (wrong stack, too senior, not remote)

    IMPORTANT: Return ONLY a JSON object like this:
    {{"score": 85, "reason": "Matches Node.js and React, mid-level, remote-first"}}
    """
    response = model.generate_content(prompt)
    result = json.loads(response.text)
    return result["score"], result["reason"]
```

**In your curator.py — only save jobs above threshold:**
```python
score, reason = score_job(job)
job["match_score"] = score
job["match_reason"] = reason
if score >= 70:
    save_to_sheets(job)
```

---

## 📄 Feature 2 — CV Parser (Auto-Update Skills from CV)

Instead of hardcoding your CV in the matcher, parse it dynamically.
This way if you update your CV, the matcher updates automatically.

**What to build — `tools/cv_parser.py`:**

```python
import pdfplumber  # pip install pdfplumber
import google.generativeai as genai
import json

def parse_cv(cv_path: str) -> dict:
    # Extract text from PDF CV
    with pdfplumber.open(cv_path) as pdf:
        text = "\n".join(page.extract_text() for page in pdf.pages)

    # Use Gemini to extract structured data
    model = genai.GenerativeModel("gemini-2.0-flash")
    prompt = f"""
    Extract structured data from this CV. Return ONLY JSON:
    {{
        "name": "",
        "years_experience": 0,
        "skills": [],
        "frameworks": [],
        "databases": [],
        "job_titles": [],
        "seniority": "junior/mid/senior",
        "languages": []
    }}

    CV TEXT:
    {text[:4000]}
    """
    response = model.generate_content(prompt)
    return json.loads(response.text)
```

**Usage:**
```python
# In main.py or config
CV_PROFILE = parse_cv("my_cv.pdf")  # parse once at startup
```

---

## 📊 Feature 3 — Smart Scoring Dashboard in Google Sheets

Right now you dump all jobs flat. Instead, structure the Sheet properly:

### Sheet Tabs to Create:

| Tab | Purpose |
|---|---|
| `TOP MATCHES` | Score ≥ 85, sorted by score desc |
| `GOOD MATCHES` | Score 70–84 |
| `ALL JOBS` | Everything scraped (archive) |
| `APPLIED` | Jobs you've applied to (manual) |
| `STATS` | Run history, counts, sources |

### Columns to Add:

```
job_title | company | salary | tech_stack | timezone | apply_url |
summary | posted_date | source | match_score | match_reason |
scraped_at | status (new/applied/rejected)
```

---

## ⏰ Feature 4 — Smart Scheduler (Not Just Mon/Thu)

### Current Problem
Hardcoded Monday/Thursday 9AM. If a hot job posts Tuesday, you miss it for 3 days.

### Better Approach

```python
# scheduler.py — smarter schedule
from apscheduler.schedulers.blocking import BlockingScheduler

scheduler = BlockingScheduler()

# Full scrape — twice a week (Mon + Thu)
scheduler.add_job(run_full_pipeline, "cron", day_of_week="mon,thu", hour=9)

# Quick API-only scrape (no Playwright) — every day
scheduler.add_job(run_quick_scrape, "cron", hour=8)

# Stats email — every Sunday
scheduler.add_job(send_weekly_summary, "cron", day_of_week="sun", hour=10)
```

### `run_quick_scrape` — fast daily check (APIs only, no browser):
```python
def run_quick_scrape():
    jobs = []
    jobs += scrape_remotive()    # ~30s
    jobs += scrape_himalayas()   # ~10s
    jobs += scrape_jobicy()      # ~10s
    jobs += scrape_with_jobspy() # ~60s
    # Skip Playwright (slow), skip Crawl4AI
    curate_and_save(jobs)
```

---

## 📧 Feature 5 — Email / Telegram Notification for Top Matches

When a job scores 85+, send yourself an instant notification.

### Option A — Email (Gmail SMTP, free)

```python
# tools/notifier.py
import smtplib
from email.mime.text import MIMEText
import os

def send_email_alert(jobs: list):
    top_jobs = [j for j in jobs if j.get("match_score", 0) >= 85]
    if not top_jobs:
        return

    body = "🔥 TOP JOB MATCHES TODAY\n\n"
    for job in top_jobs[:5]:
        body += f"[{job['match_score']}] {job['job_title']} at {job['company']}\n"
        body += f"  {job['apply_url']}\n"
        body += f"  Why: {job['match_reason']}\n\n"

    msg = MIMEText(body)
    msg["Subject"] = f"🎯 {len(top_jobs)} Top Job Matches Found"
    msg["From"] = os.getenv("GMAIL_FROM")
    msg["To"] = os.getenv("GMAIL_TO")

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(os.getenv("GMAIL_FROM"), os.getenv("GMAIL_APP_PASSWORD"))
        server.send_message(msg)
```

### Option B — Telegram Bot (even easier)

```python
import requests, os

def send_telegram_alert(jobs: list):
    top_jobs = [j for j in jobs if j.get("match_score", 0) >= 85]
    if not top_jobs:
        return

    for job in top_jobs[:5]:
        msg = (
            f"🎯 *{job['job_title']}* at {job['company']}\n"
            f"Score: {job['match_score']}/100\n"
            f"Why: {job['match_reason']}\n"
            f"[Apply Here]({job['apply_url']})"
        )
        requests.post(
            f"https://api.telegram.org/bot{os.getenv('TELEGRAM_BOT_TOKEN')}/sendMessage",
            json={
                "chat_id": os.getenv("TELEGRAM_CHAT_ID"),
                "text": msg,
                "parse_mode": "Markdown"
            }
        )
```

**Telegram setup (5 min, fully free):**
1. Message `@BotFather` on Telegram → `/newbot` → get token
2. Message `@userinfobot` → get your chat_id
3. Add both to `.env`

---

## 🔁 Feature 6 — Duplicate Detection (Across Runs)

Right now if the same job appears in run 1 and run 2, it gets saved twice.

```python
# tools/deduplicator.py
import hashlib

def job_fingerprint(job: dict) -> str:
    """Create unique hash from job title + company + url"""
    key = f"{job['job_title'].lower().strip()}{job['company'].lower().strip()}{job['apply_url']}"
    return hashlib.md5(key.encode()).hexdigest()

def filter_already_seen(jobs: list, seen_hashes: set) -> list:
    new_jobs = []
    for job in jobs:
        h = job_fingerprint(job)
        if h not in seen_hashes:
            new_jobs.append(job)
            seen_hashes.add(h)
    return new_jobs
```

Store `seen_hashes` in a local `seen_jobs.json` file. Load it at start,
save it at end of each run.

---

## 🌍 Feature 7 — Timezone Compatibility Scoring

As someone in India (UTC+5:30), async/overlap matters for remote work.

```python
def timezone_score(job: dict) -> int:
    description = (job.get("summary", "") + job.get("tech_stack", "")).lower()

    # Best — fully async, no overlap needed
    if any(x in description for x in ["async", "fully remote", "no overlap", "flexible hours"]):
        return 100

    # Good — European timezone overlap (IST overlaps well with CET)
    if any(x in description for x in ["europe", "cet", "gmt", "uk", "emea"]):
        return 80

    # Okay — some US overlap possible
    if any(x in description for x in ["est", "pst", "us only", "americas"]):
        return 40

    # Unknown — neutral
    return 60
```

Add `timezone_score` as a column in Sheets and factor it into overall match score.

---

## 📝 Feature 8 — Smarter Cover Letters

### Current Problem
Your cover letter is generic — same template for every job.

### Better Approach — Job-Specific Cover Letters

```python
def generate_cover_letter(job: dict, cv_profile: dict) -> str:
    model = genai.GenerativeModel("gemini-2.0-flash")
    prompt = f"""
    Write a SHORT, punchy cover letter (200 words max).

    CANDIDATE:
    - Name: {cv_profile['name']}
    - Stack: {', '.join(cv_profile['skills'][:8])}
    - Experience: {cv_profile['years_experience']} years

    JOB:
    - Title: {job['job_title']}
    - Company: {job['company']}
    - Requirements: {job['summary'][:400]}

    Rules:
    - First line must hook them immediately (no "I am writing to apply...")
    - Mention 2-3 specific skills that match the job
    - Reference the company by name
    - End with a clear CTA
    - NO generic filler phrases
    """
    response = model.generate_content(prompt)
    return response.text
```

Only generate cover letters for jobs with `match_score >= 75` — save tokens.

---

## 🗂️ Feature 9 — Application Tracker

Add a simple status tracker so you know what you've applied to.

**New Sheet tab: `APPLIED`**

```python
def mark_applied(job_url: str, notes: str = ""):
    """Call this manually when you apply to a job"""
    sheet = get_sheet("APPLIED")
    sheet.append_row([
        job_url,
        datetime.now().isoformat(),
        "applied",
        notes
    ])
```

Or build a tiny CLI:
```bash
python track.py --apply "https://job-url.com" --note "Good fit, applied via LinkedIn"
python track.py --status  # shows summary of applications
```

---

## 🔧 Updated .env (All Features)

```env
# Core
GOOGLE_SHEETS_ID=your_sheet_id
GOOGLE_SERVICE_ACCOUNT=keys.json
GEMINI_API_KEY=your_key
MODEL=gemini/gemini-2.0-flash
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

# Notifications (pick one)
GMAIL_FROM=your@gmail.com
GMAIL_TO=your@gmail.com
GMAIL_APP_PASSWORD=your_app_password

TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

---

## 🏁 Priority Order — What to Build First

| Priority | Feature | Impact | Effort |
|---|---|---|---|
| 🔴 1 | CV-Based Job Matching | Huge — finds right jobs | Medium |
| 🔴 2 | Duplicate Detection | Cleans up Sheets fast | Low |
| 🟡 3 | Telegram Notifications | Instant alerts | Low |
| 🟡 4 | Smart Sheet Structure | Better visibility | Low |
| 🟡 5 | Smarter Cover Letters | More personal | Medium |
| 🟢 6 | CV Parser (PDF) | Auto-updates matching | Medium |
| 🟢 7 | Timezone Scoring | India-relevant results | Low |
| 🟢 8 | Smart Scheduler | Daily quick checks | Low |
| 🟢 9 | Application Tracker | Tracks your pipeline | Medium |

---

*Start with Feature 1 (CV Matching) + Feature 2 (Deduplication) —
those two alone will transform the quality of results.*
