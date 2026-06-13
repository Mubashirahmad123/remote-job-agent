from tools.sheet_writer import append_rows, get_all_rows
from tools.cv_parser import parse_cv
from tools.cv_matcher import score_job
from tools.deduplicator import filter_already_seen, load_seen_hashes, save_seen_hashes
import json
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

CV_PROFILE = None
CV_MATCHING_ENABLED = False
MIN_SCORE = int(os.getenv("MIN_MATCH_SCORE", 70))

cv_path = os.getenv("CV_PATH", "").strip()
if cv_path:
    resolved_cv_path = Path(cv_path)
    if not resolved_cv_path.is_absolute():
        resolved_cv_path = Path(__file__).resolve().parents[1] / resolved_cv_path
    if resolved_cv_path.exists():
        try:
            CV_PROFILE = parse_cv(str(resolved_cv_path))
            CV_MATCHING_ENABLED = True
            print(f"CV matching enabled with minimum score {MIN_SCORE}")
        except Exception as e:
            print(f"Warning: CV matching disabled because CV parsing failed: {e}")
    else:
        print(f"Warning: CV matching disabled because CV_PATH was not found: {cv_path}")

def curate(raw_jobs):
    """
    Curates raw job data by removing duplicates and ranking jobs,
    then saves to Google Sheet
    """
    print(f"🔍 Curating {len(raw_jobs)} raw jobs...")

    if not raw_jobs:
        print("❌ No jobs found to curate.")
        return {
            "status": "error",
            "message": "No jobs to curate",
            "stats": {"original_jobs": 0, "unique_jobs_added": 0},
            "top_jobs": None
        }

    # Get all existing rows from Google Sheet
    print("📊 Checking existing jobs in Google Sheet...")
    existing_rows = get_all_rows()
    
    if not existing_rows:
        print("⚠️ Warning: Sheet is empty or fetch failed. All jobs will be added.")
        existing_urls = set()
    else:
        print(f"📋 Found {len(existing_rows)} existing rows in sheet")
        
        # Find the column index for apply_url
        header = existing_rows[0]
        try:
            url_idx = header.index("apply_url")
            print(f"🔍 Found apply_url column at index {url_idx}")
        except ValueError:
            print("⚠️ apply_url column not found in header, using fallback index")
            url_idx = 5  # Fallback: assume it's the 6th column
        
        # Build set of normalized URLs already present
        existing_urls = set()
        for row in existing_rows[1:]:  # Skip header row
            if row and len(row) > url_idx and row[url_idx]:
                normalized_url = row[url_idx].split("?")[0].strip()
                if normalized_url:
                    existing_urls.add(normalized_url)
        
        print(f"🔍 Found {len(existing_urls)} existing unique URLs")

    # Helper function to normalize URLs
    def normalize_url(url):
        """Remove query parameters and normalize URL"""
        return url.split("?")[0].strip() if url else ""

    # Remove duplicate jobs based on URL
    print("🔄 Removing duplicates...")
    unique_jobs = []
    seen_urls = set(existing_urls)
    duplicates_count = 0
    
    for i, job in enumerate(raw_jobs, 1):
        job_url = normalize_url(job.get("apply_url", ""))
        job_title = job.get("job_title", "No Title")
        
        if not job_url:
            print(f"⚠️ Job {i}: '{job_title}' - No URL, skipping")
            continue
            
        if job_url in seen_urls:
            print(f"⚠️ Job {i}: '{job_title}' - DUPLICATE")
            duplicates_count += 1
            continue
        
        unique_jobs.append(job)
        seen_urls.add(job_url)
        print(f"✅ Job {i}: '{job_title}' - UNIQUE")

    print(f"📊 Duplicate removal results:")
    print(f"   • Original jobs: {len(raw_jobs)}")
    print(f"   • Duplicates removed: {duplicates_count}")
    print(f"   • Unique jobs: {len(unique_jobs)}")

    if not unique_jobs:
        print("ℹ️ No unique jobs to add to Google Sheet.")
        return {
            "status": "warning",
            "message": "All jobs were duplicates - none added to sheet",
            "stats": {
                "original_jobs": len(raw_jobs),
                "duplicates_removed": duplicates_count,
                "unique_jobs_added": 0
            },
            "top_jobs": None
        }

    seen_hashes = load_seen_hashes()
    before_seen_filter = len(unique_jobs)
    unique_jobs = filter_already_seen(unique_jobs, seen_hashes)
    already_seen_count = before_seen_filter - len(unique_jobs)

    print(f"Fingerprint duplicate results:")
    print(f"   Already seen jobs skipped: {already_seen_count}")
    print(f"   New fingerprint jobs: {len(unique_jobs)}")

    if not unique_jobs:
        print("No new jobs after fingerprint duplicate detection.")
        return {
            "status": "warning",
            "message": "All jobs were already seen - none added to sheet",
            "stats": {
                "original_jobs": len(raw_jobs),
                "duplicates_removed": duplicates_count,
                "already_seen_removed": already_seen_count,
                "unique_jobs_added": 0
            },
            "top_jobs": None
        }

    match_rejected_count = 0
    if CV_MATCHING_ENABLED:
        print(f"Scoring jobs against CV profile with minimum score {MIN_SCORE}...")
        matched_jobs = []

        for i, job in enumerate(unique_jobs, 1):
            job_title = job.get("job_title", "No Title")
            try:
                match_score, match_reason = score_job(job, CV_PROFILE)
                job["match_score"] = match_score
                job["match_reason"] = match_reason

                if match_score >= MIN_SCORE:
                    matched_jobs.append(job)
                    print(f"Job {i}: '{job_title}' - MATCH {match_score}")
                else:
                    match_rejected_count += 1
                    print(f"Job {i}: '{job_title}' - LOW MATCH {match_score}")
            except Exception as e:
                match_rejected_count += 1
                job["match_score"] = ""
                job["match_reason"] = f"Matching failed: {e}"
                print(f"Job {i}: '{job_title}' - matching failed, skipping: {e}")

        unique_jobs = matched_jobs
        print(f"CV matching results: {len(unique_jobs)} matched, {match_rejected_count} rejected")

        if not unique_jobs:
            print("No jobs met the minimum CV match score.")
            return {
                "status": "warning",
                "message": "No jobs met the minimum CV match score",
                "stats": {
                    "original_jobs": len(raw_jobs),
                    "duplicates_removed": duplicates_count,
                    "match_rejected": match_rejected_count,
                    "unique_jobs_added": 0
                },
                "top_jobs": None
            }
    else:
        for job in unique_jobs:
            job.setdefault("match_score", "")
            job.setdefault("match_reason", "")

    # Rank jobs by quality factors
    print("🏆 Ranking jobs by quality...")
    
    def job_score(job):
        """Calculate job quality score"""
        score = 0
        
        # Salary information present
        if job.get("salary") and job.get("salary").strip():
            score += 10
            
        # Company name present
        if job.get("company") and job.get("company").strip() and job.get("company") != "Unknown":
            score += 5
            
        # Tech stack information
        if job.get("tech_stack") and job.get("tech_stack").strip():
            score += 5
            
        # Job title length (not too short, not too long)
        title_len = len(job.get("job_title", ""))
        if 10 <= title_len <= 80:
            score += 3
            
        # Summary/description present
        if job.get("summary") and len(job.get("summary", "")) > 20:
            score += 2
            
        return score
    
    # Sort by score (highest first)
    ranked_jobs = sorted(unique_jobs, key=job_score, reverse=True)
    top_jobs = ranked_jobs[0]

    
    # Show ranking results
    print(f"🏆 Top 3 ranked jobs:")
    for i, job in enumerate(ranked_jobs[:3], 1):
        score = job_score(job)
        title = job.get("job_title", "No Title")
        company = job.get("company", "Unknown")
        print(f"   {i}. {title} at {company} (Score: {score})")

    # Save to Google Sheet
    print(f"💾 Saving {len(ranked_jobs)} curated jobs to Google Sheet...")
    try:
        append_rows(ranked_jobs)
        save_seen_hashes(seen_hashes)
        
        success_msg = f"Successfully curated and added {len(ranked_jobs)} unique jobs to Google Sheet"
        print(f"✅ {success_msg}")
        
        # Return summary for CrewAI
        return {
            "status": "success",
            "message": success_msg,
            "stats": {
                "original_jobs": len(raw_jobs),
                "duplicates_removed": duplicates_count,
                "already_seen_removed": already_seen_count,
                "match_rejected": match_rejected_count,
                "unique_jobs_added": len(ranked_jobs),
                "existing_jobs_in_sheet": len(existing_urls)
            },
            "top_jobs": top_jobs
        }
        
    except Exception as e:
        error_msg = f"Failed to save jobs to Google Sheet: {str(e)}"
        print(f"❌ {error_msg}")
        return {
            "status": "error",
            "message": error_msg,
            "stats": {
                "original_jobs": len(raw_jobs),
                "duplicates_removed": duplicates_count,
                "already_seen_removed": already_seen_count,
                "match_rejected": match_rejected_count,
                "unique_jobs_found": len(ranked_jobs)
            }
        }

# Test function
def test_curator():
    """Test the curator with sample data"""
    sample_jobs = [
        {
            "job_title": "Test Frontend Developer",
            "company": "Test Company A",
            "salary": "$60,000",
            "tech_stack": "React, JavaScript",
            "timezone": "UTC",
            "apply_url": "https://test.com/job/1",
            "summary": "Great opportunity for frontend development",
            "posted_date_iso": "2024-01-01"
        },
        {
            "job_title": "Test Backend Developer", 
            "company": "Test Company B",
            "salary": "",
            "tech_stack": "Python, Django",
            "timezone": "UTC",
            "apply_url": "https://test.com/job/2",
            "summary": "Backend development role",
            "posted_date_iso": "2024-01-01"
        }
    ]
    
    print("🧪 Testing curator with sample data...")
    result = curate(sample_jobs)
    print(f"Test result: {result}")

if __name__ == "__main__":
    test_curator()
