"""
agents/curator.py
Curates raw job data: dedup → filter → score → rank → save to sheet.
"""

import os
import json
import re
from datetime import datetime, date, timedelta
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# =============================================================================
# IMPORTS
# =============================================================================

from agents.scrapper import is_allowed_location
from tools.sheet_writer import append_rows, get_all_rows, get_sheet, get_or_create_worksheet
from tools.cv_parser import parse_cv
from tools.deduplicator import load_seen_hashes, save_seen_hashes
from tools.yield_tracker import YieldTracker, count_by_source
from tools.cv_library import get_library as _get_cv_library

# Try to import semantic matcher (Phase 2 feature)
try:
    from tools.embedding_matcher import score_semantic, load_cv_embeddings, CV_EMBEDDINGS_PATH
    SEMANTIC_AVAILABLE = True
except ImportError:
    SEMANTIC_AVAILABLE = False
    CV_EMBEDDINGS_PATH = None

# =============================================================================
# CONFIGURATION
# =============================================================================

MIN_SCORE = int(os.getenv("MIN_MATCH_SCORE", "70"))
SEMANTIC_WEIGHT = float(os.getenv("SEMANTIC_WEIGHT", "0.4"))
KEYWORD_WEIGHT = float(os.getenv("KEYWORD_WEIGHT", "0.6"))
CLEANUP_DAYS = int(os.getenv("CLEANUP_DAYS", "30"))

# Freshness boost
FRESHNESS_BOOST = {
    0: 20, 1: 10, 2: 5, 3: 5,
    4: 2, 5: 2, 6: 2, 7: 0,
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
            if SEMANTIC_AVAILABLE:
                try:
                    CV_EMBEDDINGS = load_cv_embeddings()
                    if CV_EMBEDDINGS:
                        print("✅ Semantic matching enabled")
                    else:
                        print(f"⚠️ Semantic matching disabled: no embeddings file at {CV_EMBEDDINGS_PATH}")
                except Exception as e:
                    print(f"⚠️ Semantic matching disabled: {e}")
        except Exception as e:
            print(f"⚠️ CV matching disabled: {e}")
    else:
        print(f"⚠️ CV not found: {cv_path}")

# ------------------------------------------------------------------
# Multi-CV library (Feature 3: Personalisation)
# Activated when CV_DIR is set; falls back to single CV_PATH otherwise.
# ------------------------------------------------------------------
print("\n✨ Loading CV library...")
_CV_LIBRARY = _get_cv_library()
if not _CV_LIBRARY.is_empty:
    _CV_LIBRARY.summary()

# If CV_DIR provided CVs but no single CV_PATH gave a primary profile,
# use the first registered CV as the backward-compat CV_PROFILE.
if not CV_MATCHING_ENABLED and not _CV_LIBRARY.is_empty:
    _CV_LIBRARY._ensure_parsed(_CV_LIBRARY.cvs[0])
    _primary = _CV_LIBRARY.cvs[0]["profile"]
    if _primary:
        CV_PROFILE = _primary
        CV_MATCHING_ENABLED = True
        print(f"✅ CV matching enabled via CV_DIR (min score: {MIN_SCORE})")


# =============================================================================
# REJECTION ENGINE (delegated to cv_matcher.py)
# =============================================================================

# Reusable matcher instance (initialized once when CV is available)
_CV_MATCHER = None

# Per-profile scorer cache: CVMatcher construction (skill extraction) is
# deterministic per profile, so reuse instances across jobs. Keyed by the
# selected CV path (or "primary" for the single-CV fallback). This removes
# the per-job construction cost in single-CV setups while staying correct
# for multi-CV routing (each picked profile gets its own cached matcher).
_MATCHER_CACHE = {}

def _get_cv_matcher():
    global _CV_MATCHER
    if _CV_MATCHER is None and CV_MATCHING_ENABLED and CV_PROFILE:
        from tools.cv_matcher import CVMatcher
        _CV_MATCHER = CVMatcher(CV_PROFILE)
    return _CV_MATCHER


def _get_matcher_for_profile(scoring_profile, cache_key):
    """Return a cached CVMatcher for the given profile (keyed by CV path)."""
    matcher = _MATCHER_CACHE.get(cache_key)
    if matcher is None:
        from tools.cv_matcher import CVMatcher as _CVMatcher
        matcher = _CVMatcher(scoring_profile)
        _MATCHER_CACHE[cache_key] = matcher
    return matcher


def _should_reject(job: dict) -> tuple:
    """
    Delegate rejection check to cv_matcher.py's robust engine.
    Returns: (should_reject: bool, reason: str)
    """
    matcher = _get_cv_matcher()
    if not matcher:
        return False, ""
    return matcher.should_reject(job)


# =============================================================================
# FRESHNESS SCORING
# =============================================================================

def _calculate_freshness_boost(posted_date_iso: str) -> int:
    """Calculate time-based score boost."""
    if not posted_date_iso:
        return 0
    
    try:
        for fmt in ["%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%m/%d/%Y", "%d/%m/%Y"]:
            try:
                posted = datetime.strptime(str(posted_date_iso)[:10], fmt).date()
                break
            except ValueError:
                continue
        else:
            return 0
        
        days_old = (date.today() - posted).days
        
        if days_old < 0:
            return 20
        elif days_old == 0:
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
            return -10
            
    except (ValueError, TypeError):
        return 0


# =============================================================================
# SHEET CLEANUP
# =============================================================================

def cleanup_sheet(days: int = 30):
    """Remove jobs older than N days from ALL JOBS sheet."""
    try:
        sheet = get_sheet()
        worksheet = get_or_create_worksheet(sheet, "ALL JOBS")
        
        all_values = worksheet.get_all_values()
        if len(all_values) <= 1:
            return 0
        
        header = all_values[0]
        rows = all_values[1:]
        
        # Find date column
        date_col = None
        for idx, col_name in enumerate(header):
            if col_name.lower() in ["posted_date_iso", "date", "posted", "scraped_at", "created_at"]:
                date_col = idx
                break
        
        if date_col is None:
            print("   ⚠️ No date column found for cleanup")
            return 0
        
        cutoff = date.today() - timedelta(days=days)
        kept = [header]
        removed = 0
        
        for row in rows:
            if len(row) <= date_col:
                kept.append(row)
                continue
            
            date_str = row[date_col].strip()
            if not date_str:
                kept.append(row)
                continue
            
            try:
                parsed = None
                for fmt in ["%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y", "%d/%m/%Y"]:
                    try:
                        parsed = datetime.strptime(date_str[:10], fmt).date()
                        break
                    except ValueError:
                        continue
                
                if parsed and parsed >= cutoff:
                    kept.append(row)
                else:
                    removed += 1
            except Exception:
                kept.append(row)
        
        if removed > 0:
            worksheet.clear()
            worksheet.append_rows(kept)
            print(f"🧹 Cleaned up {removed} old jobs (> {days} days)")
            return removed
        
        return 0
        
    except Exception as e:
        print(f"⚠️ Cleanup error: {e}")
        return 0


# =============================================================================
# JOB FINGERPRINT
# =============================================================================

def _generate_fingerprint(job: dict) -> str:
    """Generate unique fingerprint for deduplication.

    Single source of truth: delegates to tools.deduplicator.job_fingerprint
    (lowercased, URL-normalized, full MD5). Kept as a wrapper so existing
    imports keep working.
    """
    from tools.deduplicator import job_fingerprint as _dedup_fp
    return _dedup_fp(job)


# =============================================================================
# MAIN CURATION
# =============================================================================

def curate(raw_jobs: list, tracker=None) -> dict:
    """
    Curates raw job data: dedup → filter → score → rank → save.
    Pass a YieldTracker to share per-board yield data with scrape_all().
    """
    own_tracker = tracker is None
    if own_tracker:
        tracker = YieldTracker()
    tracker.stage("curated_in", count_by_source(raw_jobs))
    print(f"\n{'='*60}")
    print(f"🔍 CURATING {len(raw_jobs)} RAW JOBS")
    print(f"{'='*60}")

        # === SANITIZE: Convert None values to empty strings ===
    STRING_FIELDS = [
        "job_title", "company", "summary", "timezone", "tech_stack",
        "apply_url", "salary", "posted_date_iso", "source", "location",
        "job_type", "match_reason"
    ]
    for job in raw_jobs:
        for field in STRING_FIELDS:
            if job.get(field) is None:
                job[field] = ""

    if not raw_jobs:
        return {
            "status": "error",
            "message": "No jobs to curate",
            "stats": {"original_jobs": 0, "unique_jobs_added": 0},
            "top_jobs": []
        }

    # ── Step 0: Cleanup old jobs ──
    print(f"\n🧹 Running cleanup (>{CLEANUP_DAYS} days)...")
    cleanup_sheet(CLEANUP_DAYS)

    # ── Step 1: Load existing data ──
    print("\n📊 Loading existing sheet data...")
    existing_rows = get_all_rows()
    
    existing_urls = set()
    existing_fingerprints = set()
    
    if existing_rows and len(existing_rows) > 1:
        header = existing_rows[0]
        try:
            url_idx = header.index("apply_url")
        except ValueError:
            url_idx = 5
        
        fp_idx = None
        for i, h in enumerate(header):
            if "fingerprint" in h.lower():
                fp_idx = i
                break
        
        for row in existing_rows[1:]:
            if row and len(row) > url_idx and row[url_idx]:
                existing_urls.add(row[url_idx].split("?")[0].strip())
            if fp_idx and len(row) > fp_idx and row[fp_idx]:
                existing_fingerprints.add(row[fp_idx])
        
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
    # NOTE: non-mutating check here. seen_hashes is only updated for jobs
    # that actually pass scoring (Step 6), so rejected/low-match jobs can
    # be re-scored on a later run after matcher improvements.
    print("\n🔄 Fingerprint deduplication...")
    from tools.deduplicator import job_fingerprint
    seen_hashes = load_seen_hashes()
    before_fp = len(unique_jobs)
    still_new = []
    for job in unique_jobs:
        fp = job.get("job_fingerprint") or job_fingerprint(job)
        if fp in seen_hashes or fp in existing_fingerprints:
            continue
        job["job_fingerprint"] = fp
        still_new.append(job)
    unique_jobs = still_new
    fp_duplicates = before_fp - len(unique_jobs)
    print(f"   Fingerprint duplicates: {fp_duplicates} | Remaining: {len(unique_jobs)}")
    tracker.stage("post_dedup", count_by_source(unique_jobs))

    # ── Country / Location filter ──
    print("\n🌍 Country filter...")
    before_country = len(unique_jobs)
    unique_jobs = [job for job in unique_jobs if is_allowed_location(job)]
    country_filtered = before_country - len(unique_jobs)
    print(f"   Filtered by country: {country_filtered} | Remaining: {len(unique_jobs)}")
    tracker.stage("post_country", count_by_source(unique_jobs))

    if not unique_jobs:
        return {
            "status": "warning",
            "message": "All jobs were duplicates or filtered by country",
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
    rejected_reasons = {}
    low_match = 0
    scored_jobs = []
    
    for job in unique_jobs:
        if not job.get("job_fingerprint"):
            job["job_fingerprint"] = _generate_fingerprint(job)
        job["status"] = "NEW"
        
        # === REJECTION CHECK (uses cv_matcher.py) ===
        should_reject, reject_reason = _should_reject(job)
        if should_reject:
            rejected += 1
            key = reject_reason.split(":")[0] if ":" in reject_reason else "other"
            rejected_reasons[key] = rejected_reasons.get(key, 0) + 1
            print(f"   ❌ REJECTED: {job.get('job_title', '')[:50]} — {reject_reason[:60]}")
            continue
        
        # === CV SCORING (uses cv_matcher.py) ===
        keyword_score = 0
        semantic_score = 0
        semantic_computed = False
        match_reason = "No CV matching"

        # --- Multi-CV: pick the best CV for this specific job ---
        selected_cv_path = ""
        selected_cv_name = ""
        scoring_profile = CV_PROFILE  # fallback to global primary profile

        if not _CV_LIBRARY.is_empty:
            picked_path, picked_profile, _ = _CV_LIBRARY.pick_best(job)
            if picked_path and picked_profile:
                selected_cv_path = picked_path
                selected_cv_name = Path(picked_path).name
                scoring_profile = picked_profile

        if CV_MATCHING_ENABLED and scoring_profile:
            scorer = _get_matcher_for_profile(scoring_profile, selected_cv_path or "primary")
            score_result = scorer.score(job)
            keyword_score = score_result.get("score", 0)
            match_reason = score_result.get("match_reason", "")

            # Semantic scoring (Phase 2) — always uses the primary CV embeddings
            if SEMANTIC_AVAILABLE and CV_EMBEDDINGS:
                try:
                    semantic_score = score_semantic(job, CV_EMBEDDINGS)
                    semantic_computed = True
                except Exception as e:
                    print(f"   ⚠️ Semantic scoring failed for {job.get('job_title', '')[:40]}: {e}")

        # Freshness boost (ranking only — never gates the threshold)
        freshness = _calculate_freshness_boost(job.get("posted_date_iso", ""))

        # Combine scores with renormalization: when semantic didn't run
        # (disabled, no embeddings, or exception), keyword score carries
        # full weight instead of being dragged down by 0.4 * 0. A real
        # computed 0.0 still blends in — it's informative, not missing.
        semantic_active = bool(SEMANTIC_AVAILABLE and CV_EMBEDDINGS and semantic_computed)
        if semantic_active:
            total_w = KEYWORD_WEIGHT + SEMANTIC_WEIGHT
            base_score = ((KEYWORD_WEIGHT * keyword_score) + (SEMANTIC_WEIGHT * semantic_score)) / total_w if total_w else keyword_score
        else:
            base_score = keyword_score

        final_score = base_score + freshness

        job["match_score"] = round(base_score, 1)
        job["ranking_score"] = round(final_score, 1)
        job["keyword_score"] = round(keyword_score, 1)
        job["semantic_score"] = round(semantic_score, 1) if semantic_computed else ""
        job["semantic_computed"] = semantic_computed
        job["match_reason"] = match_reason
        job["freshness_boost"] = freshness
        # Attach selected CV so downstream steps (auto_applier, gemini_tools) can use it
        job["selected_cv_path"] = selected_cv_path
        job["selected_cv"] = selected_cv_name

        if base_score < MIN_SCORE:
            low_match += 1
            print(f"   ⚠️ LOW MATCH ({base_score:.0f}+{freshness:+d}): {job.get('job_title', '')[:50]}")
            continue

        print(f"   ✅ MATCH ({base_score:.0f}+{freshness:+d}): {job.get('job_title', '')[:50]}")
        scored_jobs.append(job)
    
    print(f"\n📊 Scoring results:")
    print(f"   Rejected: {rejected} | Low match: {low_match} | Passed: {len(scored_jobs)}")
    
    if rejected_reasons:
        print(f"\n🚫 Rejection breakdown:")
        for reason, count in sorted(rejected_reasons.items(), key=lambda x: -x[1])[:5]:
            print(f"   {reason}: {count}")

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
        score = 0
        match = job.get("ranking_score", job.get("match_score"))
        if match and isinstance(match, (int, float)):
            score += match * 2
        if job.get("salary") and str(job.get("salary")).strip():
            score += 10
        if job.get("company") and job.get("company") not in ["Unknown", ""]:
            score += 5
        if job.get("tech_stack") and str(job.get("tech_stack")).strip():
            score += 5
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
        for job in ranked_jobs:
            if job.get("job_fingerprint"):
                seen_hashes.add(job["job_fingerprint"])
        save_seen_hashes(seen_hashes)
        tracker.stage("saved", count_by_source(ranked_jobs))
        if own_tracker:
            tracker.save()
            tracker.print_table()

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
            "top_jobs": ranked_jobs[:5]
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
    """Test curator with realistic sample data."""
    sample_jobs = [
        {
            "job_title": "Junior Frontend Developer",
            "company": "TechCorp",
            "salary": "$60,000",
            "tech_stack": "React, JavaScript",
            "timezone": "Remote",
            "apply_url": "https://example.com/job/1",
            "summary": "Build UI components with React",
            "posted_date_iso": date.today().isoformat()
        },
        {
            "job_title": "Tier III Service Desk Engineer",
            "company": "Unio Digital",
            "salary": "$50,000",
            "tech_stack": "Windows, Active Directory",
            "timezone": "Remote",
            "apply_url": "https://example.com/job/2",
            "summary": "Provide technical support",
            "posted_date_iso": date.today().isoformat()
        },
        {
            "job_title": "Senior Lead Architect",
            "company": "BigCorp",
            "salary": "$150,000",
            "tech_stack": "Java, Spring",
            "timezone": "Remote",
            "apply_url": "https://example.com/job/3",
            "summary": "Lead the architecture team",
            "posted_date_iso": date.today().isoformat()
        },
        {
            "job_title": "Full Stack Developer",
            "company": "StartupXYZ",
            "salary": "",
            "tech_stack": "Node.js, React, PostgreSQL",
            "timezone": "Remote",
            "apply_url": "https://example.com/job/4",
            "summary": "Build web applications",
            "posted_date_iso": (date.today() - timedelta(days=2)).isoformat()
        },
        {
            "job_title": "Backend Developer",
            "company": "GoodCo",
            "salary": "$80,000",
            "tech_stack": "Python, Django, AWS",
            "timezone": "Remote",
            "apply_url": "https://example.com/job/5",
            "summary": "API development",
            "posted_date_iso": date.today().isoformat()
        },
        {
            "job_title": "Salesforce Developer",
            "company": "CRM Inc",
            "salary": "$70,000",
            "tech_stack": "Apex, Visualforce",
            "timezone": "Remote",
            "apply_url": "https://example.com/job/6",
            "summary": "Customize Salesforce",
            "posted_date_iso": date.today().isoformat()
        },
        {
            "job_title": "Manufacturing Engineer",
            "company": "FactoryCo",
            "salary": "$65,000",
            "tech_stack": "CAD, SolidWorks",
            "timezone": "Remote",
            "apply_url": "https://example.com/job/7",
            "summary": "Welding and fabrication",
            "posted_date_iso": date.today().isoformat()
        }
    ]
    
    print("🧪 Testing curator with realistic data...")
    result = curate(sample_jobs)
    print(f"\n{'='*60}")
    print(f"RESULT: {result['status']}")
    print(f"Stats: {result['stats']}")
    print(f"Top jobs ({len(result.get('top_jobs', []))}):")
    for j in result.get('top_jobs', []):
        print(f"   ✅ {j['job_title']} (Score: {j.get('match_score', 'N/A')})")


if __name__ == "__main__":
    test_curator()