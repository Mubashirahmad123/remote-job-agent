import os
import logging
import time
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

def scrape_with_jobspy(debug=False) -> List[Dict[str, Any]]:
    """
    Scrape major job boards through JobSpy.
    
    Args:
        debug: If True, print debug information
        
    Returns:
        List of job dictionaries
    """
    try:
        from jobspy import scrape_jobs
    except ImportError:
        logger.warning("JobSpy is not installed. Run: pip install python-jobspy")
        return []

    # Get configuration from environment
    results_per_site = int(os.getenv("JOBSPY_RESULTS_PER_SITE", "20"))
    delay = int(os.getenv("JOBSPY_DELAY", "3"))
    
    # Job sites to scrape
    sites = ["linkedin", "indeed", "glassdoor", "google", "zip_recruiter"]
    
    # Search terms for developer jobs
    search_terms = [
        "backend developer",
        "fullstack developer", 
        "node.js developer",
        "python developer",
        "react developer",
        "remote developer"
    ]
    
    all_jobs = []
    
    for site in sites:
        try:
            if debug:
                logger.info(f"Scraping {site} with JobSpy...")
            
            # Try different search terms if one fails
            for term in search_terms[:2]:  # Limit to 2 terms per site to avoid rate limits
                try:
                    jobs_df = scrape_jobs(
                        site_name=[site],
                        search_term=term,
                        location="remote",
                        results_wanted=results_per_site,
                        is_remote=True,
                        job_type="fulltime",
                    )
                    
                    if jobs_df is not None and not jobs_df.empty:
                        # Process the jobs
                        processed = _process_jobspy_results(jobs_df, site)
                        all_jobs.extend(processed)
                        if debug:
                            logger.info(f"Found {len(processed)} jobs from {site} for term '{term}'")
                        break  # Break if we found jobs with this term
                        
                except Exception as e:
                    if debug:
                        logger.debug(f"Term '{term}' failed for {site}: {e}")
                    continue
            
            # Add delay between sites to avoid rate limiting
            if site != sites[-1]:  # Don't sleep after the last site
                time.sleep(delay)
                
        except Exception as exc:
            logger.error(f"JobSpy failed for {site}: {exc}")
            continue
    
    # Remove duplicates based on job title and company
    unique_jobs = _deduplicate_jobs(all_jobs)
    
    if debug:
        logger.info(f"JobSpy returned {len(unique_jobs)} unique jobs from {len(all_jobs)} total")
    
    return unique_jobs


def _process_jobspy_results(jobs_df, site: str) -> List[Dict[str, Any]]:
    """Process JobSpy DataFrame into job dictionaries."""
    jobs = []
    
    for _, row in jobs_df.iterrows():
        title = str(row.get("title", "")).strip()
        company = str(row.get("company", "")).strip()
        description = str(row.get("description", "")).strip()
        location = str(row.get("location", "")).strip()
        job_url = str(row.get("job_url", "") or row.get("job_url_direct", "")).strip()
        
        # Skip if no title or company
        if not title or not company:
            continue
            
        # Parse salary
        min_amount = row.get("min_amount", "")
        max_amount = row.get("max_amount", "")
        salary = ""
        if min_amount and max_amount:
            salary = f"${min_amount} - ${max_amount}"
        elif min_amount:
            salary = f"${min_amount}+"
        elif max_amount:
            salary = f"Up to ${max_amount}"
        
        # Parse date
        date_posted = row.get("date_posted", "")
        if hasattr(date_posted, 'isoformat'):
            date_posted = date_posted.isoformat()
        elif date_posted:
            date_posted = str(date_posted)
        else:
            date_posted = ""
        
        # Extract tech stack from description (simple approach)
        tech_stack = _extract_tech_stack(description)
        
        job = {
            "job_title": title,
            "company": company,
            "salary": salary,
            "tech_stack": tech_stack[:200],  # Limit length
            "timezone": f"Remote ({location})" if "remote" in location.lower() else location,
            "apply_url": job_url,
            "summary": description[:500],  # Truncate for storage
            "posted_date_iso": date_posted,
            "source": f"JobSpy-{site}",
        }
        jobs.append(job)
    
    return jobs


def _extract_tech_stack(description: str) -> str:
    """Extract tech stack keywords from description."""
    tech_keywords = [
        "Python", "JavaScript", "TypeScript", "Java", "C#", "C++", "Go", "Rust",
        "React", "Vue", "Angular", "Node.js", "Django", "Flask", "FastAPI",
        "AWS", "Azure", "GCP", "Docker", "Kubernetes", "Terraform",
        "PostgreSQL", "MySQL", "MongoDB", "Redis", "Elasticsearch",
        "GraphQL", "REST", "API", "Microservices", "Serverless",
        "Git", "CI/CD", "Agile", "Scrum", "DevOps"
    ]
    
    found = []
    desc_lower = description.lower()
    for tech in tech_keywords:
        if tech.lower() in desc_lower:
            found.append(tech)
    
    return ", ".join(found[:10])  # Return top 10 techs


def _deduplicate_jobs(jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove duplicate jobs based on title and company."""
    seen = set()
    unique = []
    
    for job in jobs:
        key = f"{job['job_title'].lower()}|{job['company'].lower()}"
        if key not in seen:
            seen.add(key)
            unique.append(job)
    
    return unique