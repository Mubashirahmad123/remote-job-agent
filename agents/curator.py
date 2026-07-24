"""
agents/curator.py
Curates raw job data: dedup → filter → score → rank → save to sheet.
"""

import os
import json
import re
from datetime import datetime, date
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# =============================================================================
# IMPORTS
# =============================================================================

from tools.sheet_writer import append_rows, get_all_rows
from tools.cv_parser import parse_cv
from tools.cv_matcher import score_job
from tools.deduplicator import filter_already_seen, load_seen_hashes, save_seen_hashes

# Try to import semantic matcher (Phase 2 feature)
try:
    from tools.embedding_matcher import score_semantic, load_cv_embeddings
    SEMANTIC_AVAILABLE = True
except ImportError:
    SEMANTIC_AVAILABLE = False

# =============================================================================
# CONFIGURATION
# =============================================================================

MIN_SCORE = int(os.getenv("MIN_MATCH_SCORE", "70"))
SEMANTIC_WEIGHT = float(os.getenv("SEMANTIC_WEIGHT", "0.4"))
KEYWORD_WEIGHT = float(os.getenv("KEYWORD_WEIGHT", "0.6"))

# Rejection engine (Phase 1.1)
HARD_REJECT_TITLES = [
    "senior", "lead", "principal", "architect", "director",
    "manager", "vp", "head of", "staff", "cto", "ceo"
]

HARD_REJECT_DESCRIPTIONS = [
    "hybrid", "onsite", "on-site", "security clearance",
    "ts/sci", "relocation required", "must be located in"
]

SOFT_PENALTIES = {
    "contract": -10,
    "internship": -20,
    "part-time": -15,
    "temporary": -10,
}

# Freshness boost (Phase 1.2)
FRESHNESS_BOOST = {
    0: 20,    # Today
    1: 10,    # 1 day old
    2: 5,     # 2-3 days
    3: 5,
    4: 2,     # 4-7 days
    5: 2,
    6: 2,
    7: 0,     # 8-30 days
}

# =============================================================================
# CV PROFILE LOADING
# =============================================================================

CV_PROFILE = None
CV_MATCHING_ENABLED = False
CV_EMBEDDINGS = None

cv_path = os.getenv("CV_PATH", "").strip()
if cv_path:
    resolved_cv_path = Path(cv_path)
    if not resolved_cv_path.is_absolute():
        resolved_cv_path = Path(__file__).resolve().parents[1] / resolved_cv_path
    if resolved_cv_path.exists():
        try:
            CV_PROFILE = parse_cv(str(resolved_cv_path))
            CV_MATCHING_ENABLED = True
            print(f"✅ CV matching enabled (min score: {MIN_SCORE})")
            
            # Load semantic embeddings if available
            if SEMANTIC_AVAILABLE:
                try:
                    CV_EMBEDDINGS = load_cv_embeddings()
                    print("✅ Semantic matching enabled")
                except Exception as e:
                    print(f"⚠️ Semantic matching disabled: {e}")
                    
        except Exception as e:
            print(f"⚠️ CV matching disabled: {e}")
    else:
        print(f"⚠️ CV not found: {cv_path}")


# =============================================================================
# REJECTION ENGINE (Phase 1.1)
# =============================================================================

def _should_reject(job: dict) -> tuple:
    """
    Check if job should be rejected.
    Returns: (should_reject: bool, reason: str, penalty: int)
    """
    title = (job.get("job_title") or "").lower()
    description = (job.get("summary") or "").lower()
    combined = f"{title} {description}"
    
    # Hard reject: title
    for reject_term in HARD_REJECT_TITLES:
        if re.search(rf'\b{re.escape(reject_term)}\b', title):
            return True, f"Hard reject: title contains '{reject_term}'", 0
    
    # Hard reject: description
    for reject_term in HARD_REJECT_DESCRIPTIONS:
        if reject_term in description:
            return True, f"Hard reject: description contains '{reject_term}'", 0
    
    # Soft penalties
    penalty = 0
    penalty_reasons = []
    for term, pen in SOFT_PENALTIES.items():
        if term in combined:
            penalty += pen
            penalty_reasons.append(f"{term}({pen})")
    
    if penalty:
        return False, f"Soft penalty: {', '.join(penalty_reasons)}", penalty
    
    return False, "", 0


# =============================================================================
# FRESHNESS SCORING (Phase 1.2)
# =============================================================================

def _calculate_freshness_boost(posted_date_iso: str) -> int:
    """Calculate time-based score boost."""
    try:
        posted = datetime.strptime(posted_date_iso, "%Y-%m-%d").date()
        days_old = (date.today() - posted).days
        
        if days_old < 0:
            return 20  # Future date, treat as fresh
        
        if days_old == 0:
            return FRESHNESS_BOOST[0]
        elif days_old == 1:
            return FRESHNESS_BOOST[1]
        elif days_old <= 3:
            return FRESHNESS_BOOST[2]
        elif days_old <= 7:
            return FRESHNESS_BOOST[4]
        elif days_old <= 30:
            return FRESHNESS_BOOST[7]
        else:
            return -10  # Older than 30 days
            
    except (ValueError, TypeError):
        return 0  # Unknown date


# =============================================================================
# JOB FINGERPRINT
# =============================================================================

def _generate_fingerprint(job: dict) -> str:
    """Generate unique fingerprint for deduplication."""
    import hashlib
    key = f"{job.get('job_title', '')}|{job.get('company', '')}|{job.get('apply_url', '')}"
    return hashlib.md5(key.encode()).hexdigest()[:16]


# =============================================================================
# MAIN CURATION
# =============================================================================

def curate(raw_jobs: list) -> dict:
    """
    Curates raw job data: dedup → filter → score → rank → save.
    
    Returns:
        dict with status, message, stats, top_jobs
    """
    print(f"\n{'='*60}")
    print(f"🔍 CURATING {len(raw_jobs)} RAW JOBS")
    print(f"{'='*60}")

    if not raw_jobs:
        return {
            "status": "error",
            "message": "No jobs to curate",
            "stats": {"original_jobs": 0, "unique_jobs_added": 0},
            "top_jobs": []
        }

    # ── Step 1: Load existing data ──
    print("\n📊 Loading existing sheet data...")
    existing_rows = get_all_rows()
    
    existing_urls = set()
    if existing_rows and len(existing_rows) > 1:
        header = existing_rows[0]
        try:
            url_idx = header.index("apply_url")
        except ValueError:
            url_idx = 5  # Fallback
        
        for row in existing_rows[1:]:
            if row and len(row) > url_idx and row[url_idx]:
                existing_urls.add(row[url_idx].split("?")[0].strip())
        
        print(f"   Found {len(existing_urls)} existing URLs")
    else:
        print("   Sheet empty or fetch failed")

    # ── Step 2: URL deduplication ──
    print("\n🔄 URL deduplication...")
    seen_urls = set(existing_urls)
    unique_jobs = []
    duplicates = 0
    
    for job in raw_jobs:
        url = (job.get("apply_url") or "").split("?")[0].strip()
        if not url:
            continue
        if url in seen_urls:
            duplicates += 1
            continue
        seen_urls.add(url)
        unique_jobs.append(job)
    
    print(f"   Original: {len(raw_jobs)} | Duplicates: {duplicates} | Unique: {len(unique_jobs)}")

    # ── Step 3: Fingerprint deduplication ──
    print("\n🔄 Fingerprint deduplication...")
    seen_hashes = load_seen_hashes()
    before_fp = len(unique_jobs)
    unique_jobs = filter_already_seen(unique_jobs, seen_hashes)
    fp_duplicates = before_fp - len(unique_jobs)
    print(f"   Fingerprint duplicates: {fp_duplicates} | Remaining: {len(unique_jobs)}")

    if not unique_jobs:
        return {
            "status": "warning",
            "message": "All jobs were duplicates",
            "stats": {
                "original_jobs": len(raw_jobs),
                "url_duplicates": duplicates,
                "fp_duplicates": fp_duplicates,
                "unique_jobs_added": 0
            },
            "top_jobs": []
        }

    # ── Step 4: Rejection engine + scoring ──
    print(f"\n🔍 Rejection engine + CV scoring (min: {MIN_SCORE})...")
    
    rejected = 0
    low_match = 0
    scored_jobs = []
    
    for job in unique_jobs:
        # Add fingerprint
        job["job_fingerprint"] = _generate_fingerprint(job)
        job["status"] = "NEW"  # For sheet dropdown
        
        # Rejection check
        should_reject, reject_reason, penalty = _should_reject(job)
        if should_reject:
            rejected += 1
            print(f"   ❌ REJECTED: {job.get('job_title', '')} — {reject_reason}")
            continue
        
        # Freshness boost
        freshness = _calculate_freshness_boost(job.get("posted_date_iso", ""))
        
        # CV matching
        keyword_score = 0
        semantic_score = 0
        match_reason = ""
        
        if CV_MATCHING_ENABLED and CV_PROFILE:
            try:
                keyword_score, match_reason = score_job(job, CV_PROFILE)
                
                # Semantic scoring (Phase 2)
                if SEMANTIC_AVAILABLE and CV_EMBEDDINGS:
                    try:
                        semantic_score = score_semantic(job, CV_EMBEDDINGS)
                        match_reason += f" | Semantic: {semantic_score:.1f}"
                    except Exception as e:
                        semantic_score = 0
                
                # Combined score
                final_score = (KEYWORD_WEIGHT * keyword_score) + (SEMANTIC_WEIGHT * semantic_score) + freshness + penalty
                
                job["match_score"] = round(final_score, 1)
                job["keyword_score"] = round(keyword_score, 1)
                job["semantic_score"] = round(semantic_score, 1) if semantic_score else ""
                job["match_reason"] = match_reason
                job["freshness_boost"] = freshness
                
                if final_score < MIN_SCORE:
                    low_match += 1
                    print(f"   ⚠️ LOW MATCH ({final_score:.0f}): {job.get('job_title', '')}")
                    continue
                    
                print(f"   ✅ MATCH ({final_score:.0f}): {job.get('job_title', '')}")
                
            except Exception as e:
                print(f"   ⚠️ Scoring failed: {e}")
                job["match_score"] = ""
                job["match_reason"] = f"Error: {e}"
        else:
            # No CV matching — use freshness + quality only
            job["match_score"] = freshness + penalty
            job["match_reason"] = f"Freshness: {freshness}, Penalty: {penalty}"
        
        scored_jobs.append(job)
    
    print(f"\n📊 Scoring results:")
    print(f"   Rejected: {rejected} | Low match: {low_match} | Passed: {len(scored_jobs)}")

    if not scored_jobs:
        return {
            "status": "warning",
            "message": "No jobs passed filtering",
            "stats": {
                "original_jobs": len(raw_jobs),
                "url_duplicates": duplicates,
                "fp_duplicates": fp_duplicates,
                "rejected": rejected,
                "low_match": low_match,
                "unique_jobs_added": 0
            },
            "top_jobs": []
        }

    # ── Step 5: Ranking ──
    print("\n🏆 Ranking jobs...")
    
    def rank_score(job):
        """Composite ranking: CV match > freshness > quality signals."""
        score = 0
        
        # CV match score (highest priority)
        match = job.get("match_score")
        if match and isinstance(match, (int, float)):
            score += match * 2
        
        # Quality signals
        if job.get("salary") and str(job.get("salary")).strip():
            score += 10
        if job.get("company") and job.get("company") not in ["Unknown", ""]:
            score += 5
        if job.get("tech_stack") and str(job.get("tech_stack")).strip():
            score += 5
        
        # Title quality
        title = job.get("job_title", "")
        if 10 <= len(title) <= 80:
            score += 3
        
        return score
    
    ranked_jobs = sorted(scored_jobs, key=rank_score, reverse=True)
    
    print(f"   Top 3 jobs:")
    for i, job in enumerate(ranked_jobs[:3], 1):
        ms = job.get("match_score", "N/A")
        print(f"   {i}. {job.get('job_title', '')} at {job.get('company', '')} (Score: {ms})")

    # ── Step 6: Save to sheet ──
    print(f"\n💾 Saving {len(ranked_jobs)} jobs to Google Sheet...")
    try:
        append_rows(ranked_jobs)
        save_seen_hashes(seen_hashes)
        
        success_msg = f"Added {len(ranked_jobs)} jobs to sheet"
        print(f"✅ {success_msg}")
        
        return {
            "status": "success",
            "message": success_msg,
            "stats": {
                "original_jobs": len(raw_jobs),
                "url_duplicates": duplicates,
                "fp_duplicates": fp_duplicates,
                "rejected": rejected,
                "low_match": low_match,
                "unique_jobs_added": len(ranked_jobs)
            },
            "top_jobs": ranked_jobs[:5]  # Return top 5, not just 1
        }
        
    except Exception as e:
        print(f"❌ Save failed: {e}")
        return {
            "status": "error",
            "message": f"Save failed: {e}",
            "stats": {"original_jobs": len(raw_jobs), "unique_jobs_found": len(ranked_jobs)},
            "top_jobs": ranked_jobs[:5]
        }


# =============================================================================
# TEST
# =============================================================================

def test_curator():
    """Test curator with sample data."""
    sample_jobs = [
        {
            "job_title": "Junior Frontend Developer",
            "company": "TechCorp",
            "salary": "$60,000",
            "tech_stack": "React, JavaScript",
            "timezone": "Remote",
            "apply_url": "https://example.com/job/1",
            "summary": "Build UI components",
            "posted_date_iso": date.today().isoformat()
        },
        {
            "job_title": "Senior Lead Architect",  # Should be rejected
            "company": "BigCorp",
            "salary": "$150,000",
            "tech_stack": "Java, Spring",
            "timezone": "Remote",
            "apply_url": "https://example.com/job/2",
            "summary": "Lead the architecture team",
            "posted_date_iso": date.today().isoformat()
        },
        {
            "job_title": "Full Stack Developer",
            "company": "StartupXYZ",
            "salary": "",
            "tech_stack": "Node.js, React",
            "timezone": "Remote",
            "apply_url": "https://example.com/job/3",
            "summary": "Contract position — build MVP",
            "posted_date_iso": (date.today().replace(day=date.today().day-1)).isoformat()
        }
    ]
    
    print("🧪 Testing curator...")
    result = curate(sample_jobs)
    print(f"\nResult: {result['status']}")
    print(f"Stats: {result['stats']}")
    print(f"Top jobs: {len(result.get('top_jobs', []))}")


if __name__ == "__main__":
    test_curator()