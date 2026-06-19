import os
import re
import datetime
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

def _job(title, company, url, source, summary="", salary="", timezone="Remote"):
    return {
        "job_title": title,
        "company": company,
        "salary": salary,
        "tech_stack": "",
        "timezone": timezone or "Remote",
        "apply_url": url,
        "summary": summary,
        "posted_date_iso": datetime.date.today().isoformat(),
        "source": source,
    }

def _safe_text(element):
    """Safely get text from an element."""
    return element.inner_text().strip() if element else ""

def _with_base(url, base_url):
    """Ensure URL has a base if relative."""
    if not url:
        return ""
    return url if url.startswith("http") else base_url + url

def _clean_text(text):
    """Clean text by removing extra whitespace and newlines."""
    if not text:
        return ""
    return re.sub(r'\s+', ' ', text).strip()

def _is_valid_job_title(title: str) -> bool:
    """Check if title looks like a valid job title."""
    if not title or len(title) < 5:
        return False
    
    # Keywords that indicate it's a job
    job_keywords = ['developer', 'engineer', 'architect', 'lead', 'senior', 
                   'junior', 'full-stack', 'frontend', 'backend', 'devops',
                   'sre', 'qa', 'analyst', 'scientist', 'manager']
    
    title_lower = title.lower()
    return any(keyword in title_lower for keyword in job_keywords)

def scrape_stealth_boards(debug=False):
    """Scrape blocker-prone boards with Playwright stealth, if installed."""
    try:
        from playwright.sync_api import sync_playwright
        # playwright_stealth import may vary
        try:
            from playwright_stealth import stealth_sync
            has_stealth = True
        except ImportError:
            logger.warning("playwright-stealth not installed, using standard Playwright")
            has_stealth = False
    except ImportError:
        logger.warning("Playwright is not installed. Run: pip install playwright && playwright install chromium")
        return []

    headless = os.getenv("PLAYWRIGHT_HEADLESS", "true").lower() != "false"
    timeout = int(os.getenv("PLAYWRIGHT_TIMEOUT", "30000"))
    jobs = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        
        # Create context with realistic viewport
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            timezone_id="America/New_York",
            geolocation={"longitude": -74.006, "latitude": 40.7128},
            permissions=["geolocation"],
            device_scale_factor=1,
        )
        
        page = context.new_page()
        
        # Apply stealth if available
        if has_stealth:
            try:
                stealth_sync(page)
            except Exception as e:
                logger.warning(f"Stealth apply failed: {e}")
        
        # Add random delays to mimic human behavior
        import random
        
        # Scrape each site
        jobs.extend(_scrape_weworkremotely(page, debug, timeout))
        jobs.extend(_scrape_remoteco(page, debug, timeout))
        jobs.extend(_scrape_wellfound(page, debug, timeout))
        jobs.extend(_scrape_nodesk(page, debug, timeout))
        
        browser.close()

    if debug:
        logger.info(f"Playwright stealth returned {len(jobs)} total jobs")
    
    return jobs

def _scrape_weworkremotely(page, debug=False, timeout=30000):
    """Scrape WeWorkRemotely with Playwright."""
    jobs = []
    source = "WeWorkRemotely"
    
    try:
        url = "https://weworkremotely.com/categories/remote-programming-jobs"
        logger.debug(f"Scraping {source}: {url}")
        
        page.goto(url, wait_until="domcontentloaded", timeout=timeout)
        page.wait_for_selector("section.jobs", timeout=15000)
        
        # Get all job listings
        job_elements = page.query_selector_all("section.jobs li")
        
        for el in job_elements:
            try:
                # Updated selectors for current WWR HTML structure
                title_el = el.query_selector("span.new-listing__header__title__text")
                link_el = el.query_selector('a[href^="/remote-jobs/"]')
                
                title = _clean_text(_safe_text(title_el))
                
                if not link_el:
                    continue
                
                href = link_el.get_attribute("href")
                job_url = _with_base(href, "https://weworkremotely.com")
                
                if not title or not job_url or not _is_valid_job_title(title):
                    continue
                
                # Company name: try visible text first, then extract from URL
                company = ""
                for sel in ["span.tooltip--flag-logo__tooltiptext", 'a[href^="/company/"]']:
                    ce = el.query_selector(sel)
                    if ce:
                        company = _clean_text(_safe_text(ce))
                    if company:
                        break
                if not company:
                    cl = el.query_selector('a[href^="/company/"]')
                    if cl:
                        href = cl.get_attribute("href") or ""
                        company = href.replace("/company/", "").replace("-", " ").title()
                
                # Get summary if available
                summary_el = el.query_selector("p")
                summary = _clean_text(_safe_text(summary_el))[:300]
                
                jobs.append(_job(
                    title, company, job_url, source, 
                    summary or "WeWorkRemotely remote programming listing"
                ))
            except Exception as e:
                logger.debug(f"Error parsing element in {source}: {e}")
                continue
                
    except Exception as exc:
        logger.error(f"{source} Playwright scrape failed: {exc}")
    
    if debug:
        logger.info(f"{source} Playwright returned {len(jobs)} jobs")
    return jobs

def _scrape_remoteco(page, debug=False, timeout=30000):
    """Scrape Remote.co with Playwright."""
    jobs = []
    source = "Remote.co"
    
    try:
        url = "https://remote.co/remote-jobs/developer/"
        logger.debug(f"Scraping {source}: {url}")
        
        page.goto(url, wait_until="domcontentloaded", timeout=timeout)
        page.wait_for_selector("body", timeout=10000)
        
        # Wait a bit for dynamic content
        page.wait_for_timeout(2000)
        
        # Find job card containers first, then extract links within them
        card_selectors = [".card", ".job-card", "article", ".listing", ".job-listing"]
        cards = []
        for sel in card_selectors:
            cards = page.query_selector_all(sel)
            if cards:
                break

        if not cards:
            # Fallback: look for job links directly
            cards = page.query_selector_all("a[href*='/job/']")

        for card in cards:
            try:
                # Get the link element — either the card itself or a nested link
                link_el = card if card.tag_name == "a" else card.query_selector("a[href*='/job/']")
                if not link_el:
                    continue

                title = _clean_text(_safe_text(link_el))
                href = link_el.get_attribute("href") or ""

                if not title or not href or not _is_valid_job_title(title):
                    continue

                # Try to extract company name from the card
                company = ""
                for cs in [".company", ".employer", ".org-name", ".name", "h4", "h5"]:
                    ce = card.query_selector(cs)
                    if ce:
                        company = _clean_text(_safe_text(ce))
                        break

                jobs.append(_job(
                    title, company, _with_base(href, "https://remote.co"),
                    source, "Remote.co developer listing"
                ))
            except Exception as e:
                continue
                
    except Exception as exc:
        logger.error(f"{source} Playwright scrape failed: {exc}")
    
    if debug:
        logger.info(f"{source} Playwright returned {len(jobs)} jobs")
    return jobs[:30]

def _scrape_wellfound(page, debug=False, timeout=30000):
    """Scrape Wellfound with Playwright."""
    jobs = []
    source = "Wellfound"
    
    try:
        url = "https://wellfound.com/role/r/remote/full-stack-developer"
        logger.debug(f"Scraping {source}: {url}")
        
        page.goto(url, wait_until="domcontentloaded", timeout=timeout)
        page.wait_for_selector("body", timeout=10000)
        
        # Wait for content to load
        page.wait_for_timeout(3000)
        
        # Try different selectors for job cards
        selectors = [
            "a[href*='/jobs/']",
            "div.job-card a[href*='/jobs/']",
            "div[data-job-id] a",
            "div.job-listing a"
        ]
        
        job_links = []
        for selector in selectors:
            links = page.query_selector_all(selector)
            if links:
                job_links = links
                break
        
        # If no links found, try a broader approach
        if not job_links:
            job_links = page.query_selector_all("a[href*='/jobs/']")
        
        for el in job_links:
            try:
                title = _clean_text(_safe_text(el))
                href = el.get_attribute("href") or ""
                
                # Get company name from parent
                parent = el.query_selector("xpath=..")
                company = ""
                if parent:
                    company_el = parent.query_selector(".company-name, .company, .org")
                    if company_el:
                        company = _clean_text(_safe_text(company_el))
                
                if title and href and _is_valid_job_title(title):
                    jobs.append(_job(
                        title, company, _with_base(href, "https://wellfound.com"),
                        source, "Wellfound remote listing"
                    ))
            except Exception as e:
                continue
                
    except Exception as exc:
        logger.error(f"{source} Playwright scrape failed: {exc}")
    
    if debug:
        logger.info(f"{source} Playwright returned {len(jobs)} jobs")
    return jobs[:30]

def _scrape_nodesk(page, debug=False, timeout=30000):
    """Scrape NoDesk with Playwright."""
    jobs = []
    source = "NoDesk"
    
    try:
        url = "https://nodesk.co/remote-jobs/engineering/"
        logger.debug(f"Scraping {source}: {url}")
        
        page.goto(url, wait_until="domcontentloaded", timeout=timeout)
        page.wait_for_selector("body", timeout=10000)
        page.wait_for_timeout(2000)
        
        # NoDesk lists jobs as links: /remote-jobs/company-job-title/
        # alongside category links like /remote-jobs/engineering/
        # Job links have a hyphenated slug with company prefix + title
        all_links = page.query_selector_all("a[href^='/remote-jobs/']")
        
        for el in all_links:
            try:
                href = el.get_attribute("href") or ""
                title = _clean_text(_safe_text(el))
                
                if not title or not href or not _is_valid_job_title(title):
                    continue
                
                # Skip category-only links (no hyphen = single word category like "engineering")
                slug = href.replace("/remote-jobs/", "").rstrip("/").split("/")[0]
                if "-" not in slug:
                    continue
                
                # Extract company name from the URL slug (first part before first hyphen)
                company = slug.split("-")[0].title()
                
                jobs.append(_job(
                    title, company, _with_base(href, "https://nodesk.co"),
                    source, "NoDesk engineering listing"
                ))
            except Exception as e:
                continue
                
    except Exception as exc:
        logger.error(f"{source} Playwright scrape failed: {exc}")
    
    if debug:
        logger.info(f"{source} Playwright returned {len(jobs)} jobs")
    return jobs[:30]

# Optional: Add retry logic
def scrape_stealth_boards_with_retry(debug=False, max_retries=3):
    """Scrape with retry logic."""
    for attempt in range(max_retries):
        try:
            jobs = scrape_stealth_boards(debug)
            if jobs:
                return jobs
            if attempt < max_retries - 1:
                logger.info(f"Retry {attempt + 1}/{max_retries} for stealth boards...")
                import time
                time.sleep(5 * (attempt + 1))
        except Exception as e:
            logger.error(f"Stealth scrape attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                import time
                time.sleep(5 * (attempt + 1))
    return []