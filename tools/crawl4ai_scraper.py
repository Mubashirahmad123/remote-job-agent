import asyncio


async def _fetch_markdown(url):
    from crawl4ai import AsyncWebCrawler

    async with AsyncWebCrawler(verbose=False) as crawler:
        result = await crawler.arun(
            url=url,
            word_count_threshold=10,
            bypass_cache=True,
        )
        return result.markdown or ""


def scrape_justremote_with_crawl4ai(debug=False):
    """Fetch JustRemote as markdown and extract jobs with Gemini, if available."""
    try:
        import crawl4ai  # noqa: F401
    except ImportError:
        print("Crawl4AI is not installed. Run: pip install crawl4ai")
        return []

    try:
        from agents.gemini_tools import extract_jobs_from_markdown
    except Exception as exc:
        print(f"Gemini markdown extraction unavailable: {exc}")
        return []

    try:
        markdown = asyncio.run(_fetch_markdown("https://justremote.co/remote-developer-jobs"))
        if debug:
            print(f"Crawl4AI scraped {len(markdown)} markdown characters from JustRemote")
        jobs = extract_jobs_from_markdown(markdown)
    except Exception as exc:
        print(f"Crawl4AI JustRemote scrape failed: {exc}")
        return []

    normalized = []
    for job in jobs:
        if not isinstance(job, dict):
            continue
        normalized.append({
            "job_title": job.get("job_title", ""),
            "company": job.get("company", ""),
            "salary": job.get("salary", ""),
            "tech_stack": job.get("tech_stack", ""),
            "timezone": job.get("timezone", "Remote") or "Remote",
            "apply_url": job.get("apply_url", ""),
            "summary": job.get("summary", ""),
            "posted_date_iso": job.get("posted_date_iso", ""),
            "source": "JustRemote",
        })

    return normalized
