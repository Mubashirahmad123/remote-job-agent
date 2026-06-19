"""
cv_matcher.py — Local job scoring engine (no API calls, no rate limits)

Scores jobs 0-100 against your CV profile using a weighted keyword algorithm.
Gemini is NOT used here — it's reserved for CV parsing (once/week) and cover letters (on demand).

Scoring breakdown:
  Title match        → 25 pts
  Skill match        → 30 pts  (scales with number of matched skills)
  Seniority check    → 20 pts  (full points if NOT senior/lead/etc)
  Remote confirmed   → 15 pts
  Salary listed      →  5 pts
  Timezone fit       →  5 pts
  ─────────────────────────────
  Max                → 100 pts
"""

import re
from typing import Optional

NON_DEV_TERMS = [
    "marketing",
    "sales",
    "accountant",
    "recruiter",
    "hr",
    "human resources",
    "designer",
    "graphic designer",
    "ui designer",
    "ux designer",
    "customer support",
    "customer success",
    "seo",
    "content writer",
    "copywriter",
    "social media",
    "product manager",
    "project manager",
    "business analyst",
]

# ─── Seniority terms that disqualify a role ───────────────────────────────────
SENIOR_TERMS = [
    "senior", "sr.", "sr ", "lead", "principal", "architect",
    "director", "manager", "head of", "vp ", "vice president",
    "chief", "cto", "ceo", "staff engineer", "distinguished",
]

# ─── Terms that confirm remote work ───────────────────────────────────────────
REMOTE_TERMS = [
    "remote", "work from home", "wfh", "fully remote", "100% remote",
    "distributed team", "anywhere",
]

# ─── Terms that disqualify remote (onsite/hybrid) ─────────────────────────────
ONSITE_TERMS = [
    "onsite", "on-site", "on site", "hybrid", "in-office", "in office",
    "relocation", "must be located", "must reside", "office required",
    "security clearance", "clearance required", "ts/sci",
]

# ─── Timezone keywords that suggest good overlap for India (UTC+5:30) ─────────
GOOD_TIMEZONE_TERMS = [
    "europe", "eu", "uk", "gmt", "cet", "utc", "worldwide", "global",
    "anywhere", "async", "flexible", "overlap not required",
]

BAD_TIMEZONE_TERMS = [
    "us only", "usa only", "north america only", "pst only", "est only",
    "must overlap us", "us hours",
]


def _normalize(text: str) -> str:
    """Lowercase, collapse whitespace."""
    return re.sub(r"\s+", " ", str(text or "").lower().strip())


def _all_text(job: dict) -> str:
    """Combine all relevant job fields into one searchable string."""
    fields = [
        job.get("job_title", ""),
        job.get("company", ""),
        job.get("tech_stack", ""),
        job.get("summary", ""),
        job.get("timezone", ""),
        job.get("salary", ""),
    ]
    return _normalize(" ".join(str(f) for f in fields))


def _score_title(job: dict, cv_profile: dict) -> tuple[int, Optional[str]]:
    """
    25 pts — Does the job title match what you're looking for?
    Full 25 if exact preferred title found, 12 if partial match.
    """
    title = _normalize(job.get("job_title", ""))
    preferred = [_normalize(t) for t in cv_profile.get("preferred_titles", [])]

    for pref in preferred:
        if pref in title:
            return 25, f"title match: {pref}"

    # Partial — generic dev terms
    generic_dev = ["developer", "engineer", "programmer", "dev "]
    for term in generic_dev:
        if term in title:
            return 12, "generic dev title"

    return 0, None



def _score_skills(job: dict, cv_profile: dict) -> tuple[int, Optional[str]]:
    full_text = _all_text(job)

    your_skills = (
        cv_profile.get("skills", []) +
        cv_profile.get("frameworks", []) +
        cv_profile.get("databases", []) +
        cv_profile.get("languages", [])
    )

    # Remove duplicates
    your_skills = list(dict.fromkeys(
    _normalize(s)
    for s in your_skills
    if s
))

    matched = []

    for skill in your_skills:
        pattern = r"(?<!\w)" + re.escape(skill) + r"(?!\w)"
        if re.search(pattern, full_text):
            matched.append(skill)

    count = len(matched)

    if count == 0:
        return 0, None
    elif count == 1:
        pts = 10
    elif count == 2:
        pts = 20
    elif count == 3:
        pts = 30
    elif count == 4:
        pts = 35
    else:
        pts = 40

    return pts, f"skills: {', '.join(matched[:4])}"   


def _score_seniority(job: dict) -> tuple[int, Optional[str]]:
    """
    20 pts — Is this NOT a senior/lead/manager role?
    Full points if no disqualifying terms found in title.
    0 pts if senior term found.
    """
    title = _normalize(job.get("job_title", ""))

    for term in SENIOR_TERMS:
        if term in title:
            return 0, f"seniority flag: {term}"

    return 20, "mid/junior level"


def _score_remote(job: dict) -> tuple[int, Optional[str]]:
    """
    15 pts — Is this genuinely remote?
    0 if onsite/hybrid terms found (hard penalty).
    15 if remote terms confirmed.
    7 if unclear (partial credit).
    """
    full_text = _all_text(job)

    for term in ONSITE_TERMS:
        if term in full_text:
            return 0, f"onsite/hybrid: {term}"

    for term in REMOTE_TERMS:
        if term in full_text:
            return 15, "remote confirmed"

    return 7, "remote unclear"


def _score_salary(job: dict) -> tuple[int, Optional[str]]:
    """
    5 pts — Is a salary range listed?
    Transparent salary = company is serious.
    """
    salary = str(job.get("salary", "") or "").strip()
    if salary and salary not in ("", "None", "N/A", "0"):
        return 5, f"salary: {salary[:30]}"
    return 0, None


def _score_timezone(job: dict) -> tuple[int, Optional[str]]:
    """
    5 pts — Does the timezone work for India (UTC+5:30)?
    Good: Europe, UK, UTC, async-friendly.
    Bad: US-only hard requirement.
    """
    full_text = _all_text(job)

    for term in BAD_TIMEZONE_TERMS:
        if term in full_text:
            return 0, f"timezone: {term}"

    for term in GOOD_TIMEZONE_TERMS:
        if term in full_text:
            return 5, f"timezone: {term}"

    return 2, "timezone: not specified"


def score_job(job: dict, cv_profile: dict) -> tuple[int, str]:
    title = _normalize(job.get("job_title", ""))

    if any(term in title for term in NON_DEV_TERMS):
        return 0, "non-dev role"

    components = [
        _score_title(job, cv_profile),
        _score_skills(job, cv_profile),
        _score_seniority(job),
        _score_remote(job),
        _score_salary(job),
        _score_timezone(job),
    ]

    total = 0
    reasons = []

    for pts, reason in components:
        total += pts
        if reason:
            reasons.append(reason)

    final_score = min(total, 100)
    reason_str = " | ".join(reasons) if reasons else "no strong match"

    return final_score, reason_str


def batch_score_jobs(jobs: list[dict], cv_profile: dict) -> list[dict]:
    """
    Score a list of jobs and attach score + reason back onto each job dict.
    Returns the same list sorted by score descending.

    Usage:
        scored_jobs = batch_score_jobs(scraped_jobs, cv_profile)
    """
    print(f"⚡ Scoring {len(jobs)} jobs locally (no API calls)...")

    for job in jobs:
        score, reason = score_job(job, cv_profile)
        job["match_score"] = score
        job["match_reason"] = reason

    scored = sorted(jobs, key=lambda j: int(j.get("match_score", 0)), reverse=True)

    top  = sum(1 for j in scored if int(j.get("match_score", 0)) >= 85)
    good = sum(1 for j in scored if 70 <= int(j.get("match_score", 0)) < 85)
    poor = sum(1 for j in scored if int(j.get("match_score", 0)) < 70)

    print(f"✅ Scoring complete:")
    print(f"   🔥 Top matches  (≥85):  {top}")
    print(f"   ✅ Good matches (70-84): {good}")
    print(f"   ❌ Poor matches (<70):   {poor}")

    return scored


# ─── Quick test ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    sample_profile = {
        "name": "Mubashir",
        "years_experience": 3,
        "skills": ["javascript", "typescript", "node.js", "express", "react", "redux", "postgresql", "mongodb", "python"],
        "frameworks": ["express.js", "django", "next.js"],
        "databases": ["postgresql", "mongodb"],
        "languages": ["javascript", "typescript", "python"],
        "preferred_titles": ["backend developer", "full stack developer", "node.js developer", "software engineer"],
        "seniority": "mid",
    }

    test_jobs = [
        {
            "job_title": "Backend Developer",
            "company": "Acme Remote",
            "tech_stack": "Node.js, Express, PostgreSQL, AWS",
            "summary": "We are looking for a mid-level backend developer to join our fully remote EU team.",
            "timezone": "Europe/UTC overlap",
            "salary": "$60,000 - $80,000",
        },
        {
            "job_title": "Senior Full Stack Engineer",
            "company": "Big Corp",
            "tech_stack": "React, Node.js, MongoDB",
            "summary": "Senior engineer needed. Must be located in US. Hybrid work.",
            "timezone": "EST",
            "salary": "",
        },
        {
            "job_title": "Full Stack Developer",
            "company": "Startup",
            "tech_stack": "React, Django, Python, PostgreSQL",
            "summary": "Remote-first company looking for a full stack developer. Async-friendly team.",
            "timezone": "Global",
            "salary": "$50,000",
        },
        {
            "job_title": "Marketing Manager",
            "company": "Brand Co",
            "tech_stack": "",
            "summary": "Looking for a marketing manager to lead our campaigns.",
            "timezone": "US only",
            "salary": "$45,000",
        },
    ]

    results = batch_score_jobs(test_jobs, sample_profile)
    print("\n─── Results ───")
    for job in results:
        print(f"  {job['match_score']:3d} | {job['job_title']:<35} | {job['match_reason']}")