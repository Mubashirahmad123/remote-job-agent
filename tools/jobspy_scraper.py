import os


def scrape_with_jobspy(debug=False):
    """Scrape major job boards through JobSpy, if installed."""
    try:
        from jobspy import scrape_jobs
    except ImportError:
        print("JobSpy is not installed. Run: pip install python-jobspy")
        return []

    results_per_site = int(os.getenv("JOBSPY_RESULTS_PER_SITE", "20"))
    delay = int(os.getenv("JOBSPY_DELAY", "3"))
    sites = ["linkedin", "indeed", "glassdoor", "google", "zip_recruiter"]

    try:
        jobs_df = scrape_jobs(
            site_name=sites,
            search_term="backend developer OR fullstack developer OR node.js developer",
            location="remote",
            results_wanted=results_per_site,
            is_remote=True,
            job_type="fulltime",
            delay_between_requests=delay,
        )
    except Exception as exc:
        print(f"JobSpy scrape failed: {exc}")
        return []

    jobs = []
    for _, row in jobs_df.iterrows():
        description = str(row.get("description", "") or "")
        min_amount = row.get("min_amount", "")
        max_amount = row.get("max_amount", "")
        salary = ""
        if min_amount or max_amount:
            salary = f"{min_amount} - {max_amount}".strip(" -")

        jobs.append({
            "job_title": row.get("title", "") or "",
            "company": row.get("company", "") or "",
            "salary": salary,
            "tech_stack": description[:100],
            "timezone": row.get("location", "") or "Remote",
            "apply_url": row.get("job_url", "") or row.get("job_url_direct", "") or "",
            "summary": description[:300],
            "posted_date_iso": str(row.get("date_posted", "") or ""),
            "source": row.get("site", "JobSpy") or "JobSpy",
        })

    if debug:
        print(f"JobSpy returned {len(jobs)} jobs")
    return jobs
