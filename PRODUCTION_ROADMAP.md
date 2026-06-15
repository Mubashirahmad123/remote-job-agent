# 🚀 Remote Job Agent — Production Roadmap

## Build Order
`Phase 1 → Phase 2 → Phase 3 → Phase 4`

---

## Phase 1 — Core Filters & Alerts (Do First)

### ✅ Feature 1: Intelligent Job Rejection Engine
**Priority:** Critical — saves Gemini API calls on every run  
**Complexity:** Low

Reject jobs *before* AI scoring using a config-driven keyword filter.

**Auto-reject if title/description contains:**
- Seniority: `Senior`, `Lead`, `Principal`, `Architect`, `Director`, `Manager`, `VP`, `Head of`
- Location: `Hybrid`, `Onsite`, `On-site`, `In-office`, `Relocation`
- Clearance: `Security Clearance`, `TS/SCI`, `Clearance Required`

**Implementation:**
- Store reject keywords in `config.yaml` — no code changes needed to extend
- Run filter before any Gemini call
- Log rejected jobs to a separate `REJECTED` sheet tab with reason

```yaml
# config.yaml
rejection_keywords:
  title:
    - senior
    - lead
    - principal
    - architect
    - director
    - manager
  description:
    - hybrid
    - onsite
    - on-site
    - security clearance
```

---

### ✅ Feature 2: Job Freshness Score Boost
**Priority:** High — improves result quality with zero API cost  
**Complexity:** Low

Apply a score multiplier based on how recently the job was posted.

| Age | Bonus |
|-----|-------|
| Today (0 days) | +20 |
| 1 day old | +10 |
| 2–3 days old | +5 |
| 4–7 days old | +2 |
| 8–30 days old | 0 |
| 30+ days old | −10 (deprioritize) |

**Implementation:**
- Parse `posted_date_iso` from existing sheet column
- Add `freshness_bonus` to `match_score` before writing to sheet
- No new columns needed

---

### ✅ Feature 3: Telegram Real-Time Alerts
**Priority:** High — eliminates manual terminal monitoring  
**Complexity:** Low (~30 lines with `python-telegram-bot`)

Send instant Telegram messages for jobs scoring above a threshold.

**Alert format:**
```
🔥 Backend Developer @ Acme Corp
Score: 94 | Posted: Today
Stack: Node.js, PostgreSQL, AWS
Timezone: US/EU overlap
💰 $80K–$110K

Apply → https://...
```

**Config:**
```yaml
telegram:
  bot_token: ${TELEGRAM_BOT_TOKEN}
  chat_id: ${TELEGRAM_CHAT_ID}
  alert_threshold: 80        # Only alert for score >= 80
  alert_on_top_match: true   # Always alert for TOP MATCHES sheet
```

---

## Phase 2 — Data Quality

### ✅ Feature 4: Auto Cleanup (Job Retention)
**Priority:** Medium  
**Complexity:** Low

Automatically delete old rows from the `ALL JOBS` sheet.

**Rules:**
- Delete rows where `scraped_at` is older than `JOB_RETENTION_DAYS` (default: 30)
- **Never delete** rows where `status` = `INTERVIEW`, `OFFER`, or `APPLIED`
- Run cleanup at the end of every pipeline execution
- Log count of deleted rows to `STATS` sheet

```yaml
retention:
  days: 30
  protected_statuses:
    - INTERVIEW
    - OFFER
    - APPLIED
```

---

### ✅ Feature 5: Apply Status Tracker
**Priority:** Medium  
**Complexity:** Low

A proper status lifecycle so cleanup and filters respect your pipeline.

**Status values:**
| Status | Meaning |
|--------|---------|
| `NEW` | Just scraped, not reviewed |
| `REVIEWED` | Looked at, not applied |
| `APPLIED` | Application sent |
| `INTERVIEW` | Interview scheduled |
| `OFFER` | Offer received |
| `REJECTED` | Company rejected or ghosted |
| `SKIP` | Manually marked to ignore |

**Implementation:**
- Add dropdown validation to `status` column in Google Sheets
- Auto-set `NEW` on insert
- Rejection engine sets `SKIP` with `match_reason` = rejection keyword

---

### ✅ Feature 6: Duplicate Detection (Pre-Scoring)
**Priority:** Medium  
**Complexity:** Low

You already have `job_fingerprint` — make sure deduplication happens *before* the Gemini call, not after writing to the sheet.

**Current risk:** If dedup runs after scoring, you're wasting API credits on jobs already in the sheet.

**Fix:**
1. On startup, load all existing fingerprints from sheet into a Python set
2. Filter scraped jobs against the set before any processing
3. Log count of skipped duplicates to `STATS`

---

## Phase 3 — Multi-CV & Intelligence

### ✅ Feature 7: Multi-CV Matching Engine
**Priority:** Medium  
**Complexity:** Medium

Support multiple resumes; let Gemini pick the best one per job.

**Supported CVs:**
```
/cvs/backend_cv.pdf
/cvs/fullstack_cv.pdf
/cvs/python_cv.pdf
```

**How it works:**
1. Pre-parse all CVs once at startup using `parse_cv()` (not per-job)
2. Pass job description + list of CV summaries to Gemini
3. Gemini returns: `{ "best_cv": "backend_cv.pdf", "reason": "..." }`
4. Use chosen CV for match scoring
5. Log `cv_used` as a new sheet column

**No need for a complex engine — one Gemini call per job handles the decision.**

---

### ✅ Feature 8: Market Intelligence Dashboard (Deferred)
**Priority:** Low — needs 3–6 months of data first  
**Complexity:** Medium

Analyze trends from your accumulated job data.

**Metrics to track:**
- Most requested skills (count from `tech_stack` column)
- Average salary by role
- Countries/timezones with most openings
- Score distribution over time
- Best sources (which job board sends highest-scoring jobs)

**Implementation:**
- Python script reads `ALL JOBS` sheet
- Aggregates into `STATS` sheet weekly
- Optional: export to a simple HTML dashboard

**⚠️ Don't build until you have 500+ rows of data.**

---

## Phase 4 — Research & Outreach (V2)

### 🔮 Feature 9: Company Quality Scoring
**Status:** Defer — fragile to build  
**Reason:** Glassdoor/Crunchbase scraping gets rate-limited fast

**Simpler alternative for now:**
- Flag companies with < 50 Glassdoor reviews as `UNVERIFIED`
- Store company metadata in a separate `COMPANIES` sheet tab
- Populate manually or via a one-off research script

---

### 🔮 Feature 10: Recruiter Intelligence Database
**Status:** Defer — data sourcing is the bottleneck  
**Reason:** Most job boards don't expose recruiter contact info

**Build when:** You're doing active cold outreach campaigns.

**Schema (for future):**
| Field | Type |
|-------|------|
| `recruiter_name` | text |
| `email` | text |
| `linkedin_url` | text |
| `company` | text |
| `last_contact_date` | date |
| `response_status` | enum |

---

### 🔮 Feature 11: AI Company Research Reports
**Status:** Defer to V2  
**Reason:** Requires agentic web scraping — complex and brittle

**When ready, generate per top match:**
- Funding stage & investors
- Team size estimate
- Tech stack from job listings
- Culture signals from reviews
- Interview prep notes from Glassdoor

---

## Summary Table

| # | Feature | Phase | Effort | Impact |
|---|---------|-------|--------|--------|
| 1 | Rejection Engine | 1 | Low | 🔴 Critical |
| 2 | Freshness Boost | 1 | Low | 🟠 High |
| 3 | Telegram Alerts | 1 | Low | 🟠 High |
| 4 | Auto Cleanup | 2 | Low | 🟡 Medium |
| 5 | Status Tracker | 2 | Low | 🟡 Medium |
| 6 | Duplicate Dedup | 2 | Low | 🟡 Medium |
| 7 | Multi-CV Matching | 3 | Medium | 🟡 Medium |
| 8 | Market Dashboard | 3 | Medium | 🟢 Low (needs data) |
| 9 | Company Scoring | 4 | High | 🟢 Low |
| 10 | Recruiter DB | 4 | High | 🟢 Low |
| 11 | AI Research Reports | 4 | High | 🟢 Low |

---

## Environment Variables (Full Reference)

```env
# Existing
GEMINI_API_KEY=
GOOGLE_SHEETS_ID=
GOOGLE_SERVICE_ACCOUNT_PATH=keys.json

# Phase 1 additions
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
ALERT_SCORE_THRESHOLD=80

# Phase 2 additions
JOB_RETENTION_DAYS=30

# Phase 3 additions
CV_DIR=./cvs
```