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

def _log_page_state(page, source):
    """Debug helper: log title/URL/body size to distinguish blocks from selector misses."""
    try:
        logger.info(f"{source} page title={page.title()!r} url={page.url} html_len={len(page.content())}")
    except Exception as e:
        logger.info(f"{source} page-state log failed: {e}")


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
        import time as _time

        # NOTE: nothing removed — every board is still attempted, each in
        # isolation so one board failure never kills the rest.
        # NOTE: _scrape_arc / _scrape_lemon stay in this file as dormant fallbacks —
        # both boards are currently covered via requests (server-rendered cards).
        _scrapers = (
            _scrape_weworkremotely,
            _scrape_remoteco,
            _scrape_wellfound,
            _scrape_nodesk,
            _scrape_ycombinator,
            _scrape_gulftalent,
            _scrape_nofluffjobs,
            _scrape_justjoinit,
        )
        try:
            for _fn in _scrapers:
                try:
                    jobs.extend(_fn(page, debug, timeout))
                except Exception as e:
                    logger.error(f"{_fn.__name__} failed: {e}")
                # Small human-like pause between boards
                _time.sleep(random.uniform(1, 3))
        finally:
            try:
                browser.close()
            except Exception:
                pass

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

def _scrape_ycombinator(page, debug=False, timeout=30000):
    """Scrape YC Work at a Startup (JS-rendered). Only /jobs/<numeric-id> links
    are real jobs — /jobs/v2 and ?role= links are nav/filter pages (verified 2026-09-21:
    unfiltered anchors picked up 'Engineering |' -> /jobs/v2?role=eng junk)."""
    jobs = []
    source = "YCombinator"
    try:
        page.goto("https://www.workatastartup.com/jobs?remote=true&role=engineering",
                  wait_until="domcontentloaded", timeout=timeout)
        page.wait_for_timeout(3000)
        links = page.query_selector_all('a[href*="/jobs/"]')
        seen = set()
        for el in links[:100]:
            try:
                href = el.get_attribute("href") or ""
                if not re.search(r'/jobs/\d+', href):
                    continue
                url = _with_base(href, "https://www.workatastartup.com")
                if url in seen:
                    continue
                seen.add(url)
                # Anchor text lines = [Company, tagline, JOB TITLE, location/salary
                # meta] (verified 2026-09-21) — never use the whole blob as title.
                lines = [ln.strip() for ln in _safe_text(el).splitlines() if ln.strip()]
                if not lines:
                    continue
                company = _clean_text(lines[0])
                title = ""
                if len(lines) >= 3:
                    title = _clean_text(lines[2])
                else:
                    for ln in lines[1:]:
                        if _is_valid_job_title(_clean_text(ln)):
                            title = _clean_text(ln)
                            break
                    if not title:
                        title = _clean_text(lines[-1])
                if not title or not _is_valid_job_title(title):
                    continue
                salary = ""
                for ln in lines[3:]:
                    m = re.search(r'\$[\d,.K\-–\s]+(?:K|k)?', ln)
                    if m:
                        salary = _clean_text(m.group(0))
                        break
                jobs.append(_job(title, company, url, source, "YC-backed startup listing",
                                 salary=salary))
            except Exception:
                continue
    except Exception as exc:
        logger.error(f"{source} Playwright scrape failed: {exc}")
    if debug:
        logger.info(f"{source} Playwright returned {len(jobs)} jobs")
    return jobs[:30]


def _scrape_arc(page, debug=False, timeout=30000):
    """Scrape Arc.dev remote jobs (JS-rendered)."""
    jobs = []
    source = "Arc"
    try:
        page.goto("https://arc.dev/remote-jobs/full-stack-developer",
                  wait_until="domcontentloaded", timeout=timeout)
        page.wait_for_timeout(3000)
        links = page.query_selector_all('a[href*="/remote-jobs/"]')
        seen = set()
        for el in links[:80]:
            try:
                title = _clean_text(_safe_text(el))
                href = el.get_attribute("href") or ""
                # Category hubs read "<X> jobs" ("Data analyst jobs") — not jobs.
                if re.search(r'\bjobs\s*$', title, re.I):
                    continue
                if not title or not href or not _is_valid_job_title(title):
                    continue
                url = _with_base(href, "https://arc.dev")
                if url in seen:
                    continue
                seen.add(url)
                jobs.append(_job(title, "", url, source, "Arc.dev remote listing"))
            except Exception:
                continue
    except Exception as exc:
        logger.error(f"{source} Playwright scrape failed: {exc}")
    if debug:
        logger.info(f"{source} Playwright returned {len(jobs)} jobs")
    return jobs[:30]


def _scrape_gulftalent(page, debug=False, timeout=30000):
    """Scrape GulfTalent (JS-rendered + bot-protected)."""
    jobs = []
    source = "GulfTalent"
    try:
        page.goto("https://www.gulftalent.com/uae/jobs/search?q=developer",
                  wait_until="domcontentloaded", timeout=timeout)
        try:
            page.wait_for_selector("a[href]", timeout=15000)
        except Exception:
            pass
        page.wait_for_timeout(2000)
        if debug:
            _log_page_state(page, source)
        cards = page.query_selector_all('[class*="job-list"] a[href*="/jobs/"], a[href*="/jobs/"]')
        for el in cards[:50]:
            try:
                title = _clean_text(_safe_text(el))
                href = el.get_attribute("href") or ""
                if not title or not href or not _is_valid_job_title(title):
                    continue
                jobs.append(_job(title, "", _with_base(href, "https://www.gulftalent.com"),
                                 source, "GulfTalent listing"))
            except Exception:
                continue
    except Exception as exc:
        logger.error(f"{source} Playwright scrape failed: {exc}")
    if debug:
        logger.info(f"{source} Playwright returned {len(jobs)} jobs")
    return jobs[:30]


def _scrape_nofluffjobs(page, debug=False, timeout=30000):
    """Scrape NoFluffJobs (JS-rendered)."""
    jobs = []
    source = "NoFluffJobs"
    try:
        page.goto("https://nofluffjobs.com/pl/remote", wait_until="domcontentloaded", timeout=timeout)
        try:
            page.wait_for_selector("a[href]", timeout=15000)
        except Exception:
            pass
        page.wait_for_timeout(2000)
        if debug:
            _log_page_state(page, source)
        cards = page.query_selector_all('a[href*="/job/"]')
        for el in cards[:50]:
            try:
                title = _clean_text(_safe_text(el))
                href = el.get_attribute("href") or ""
                if not title or not href or not _is_valid_job_title(title):
                    continue
                jobs.append(_job(title, "", _with_base(href, "https://nofluffjobs.com"),
                                 source, "NoFluffJobs listing"))
            except Exception:
                continue
    except Exception as exc:
        logger.error(f"{source} Playwright scrape failed: {exc}")
    if debug:
        logger.info(f"{source} Playwright returned {len(jobs)} jobs")
    return jobs[:30]


def _scrape_lemon(page, debug=False, timeout=30000):
    """Scrape Lemon.io role pages (verified 2026-09-21: /for-developers/ is a
    marketing hub with no listings; real projects live on role pages like
    /for-developers/full-stack-developer-jobs). Project cards expose a heading
    plus an 'Apply now'/'See more details' link, so extract headings and pair
    each with its nearest link."""
    jobs = []
    source = "Lemon"
    role_pages = [
        "https://lemon.io/for-developers/full-stack-developer-jobs",
        "https://lemon.io/for-developers/back-end-engineer-jobs",
        "https://lemon.io/for-developers/front-end-developer-jobs",
    ]
    seen = set()
    try:
        for role_url in role_pages:
            try:
                page.goto(role_url, wait_until="domcontentloaded", timeout=timeout)
                page.wait_for_timeout(3000)
            except Exception as exc:
                logger.error(f"{source} goto failed for {role_url}: {exc}")
                continue
            heads = page.query_selector_all("h2, h3, h4")
            for h in heads[:60]:
                try:
                    title = _clean_text(_safe_text(h))
                    if not title or not _is_valid_job_title(title):
                        continue
                    # Nearest link: enclosing anchor, else following Apply/Details link
                    href = ""
                    try:
                        up = h.query_selector("xpath=ancestor::a[1]")
                        if up is not None:
                            href = up.get_attribute("href") or ""
                    except Exception:
                        pass
                    if not href:
                        try:
                            sib = h.query_selector(
                                "xpath=following::a[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'apply')"
                                " or contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'see more')][1]")
                            if sib is not None:
                                href = sib.get_attribute("href") or ""
                        except Exception:
                            pass
                    url = _with_base(href, "https://lemon.io") if href else role_url
                    if url in seen:
                        continue
                    seen.add(url)
                    jobs.append(_job(title, "", url, source, "Lemon.io project listing"))
                except Exception:
                    continue
            if len(jobs) >= 30:
                break
    except Exception as exc:
        logger.error(f"{source} Playwright scrape failed: {exc}")
    if debug:
        logger.info(f"{source} Playwright returned {len(jobs)} jobs")
    return jobs[:30]

def _scrape_justjoinit(page, debug=False, timeout=30000):
    """Scrape JustJoin.it remote listings (client-rendered MUI app; offer data
    arrives via bot-gated XHR, so a real browser render is required).
    Offer URLs are /job-offer/<slug>. Card anchor text is a blob — first
    non-empty line is assumed to be the title; confirm once with debug=True."""
    jobs = []
    source = "JustJoinIt"
    try:
        page.goto("https://justjoin.it/job-offers/remote", wait_until="domcontentloaded", timeout=timeout)
        page.wait_for_timeout(4000)
        cards = page.query_selector_all('a[href*="/job-offer/"]')
        for el in cards[:50]:
            try:
                href = el.get_attribute("href") or ""
                raw = _safe_text(el)
                lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
                title = _clean_text(lines[0]) if lines else ""
                if not title or not href or not _is_valid_job_title(title):
                    continue
                jobs.append(_job(title, "", _with_base(href, "https://justjoin.it"),
                                 source, "JustJoin.it remote listing"))
            except Exception:
                continue
    except Exception as exc:
        logger.error(f"{source} Playwright scrape failed: {exc}")
    if debug:
        logger.info(f"{source} Playwright returned {len(jobs)} jobs")
    return jobs[:30]

# Registry for single-board testing (python -m tools.playwright_scraper <Board>)
STEALTH_BOARD_FNS = {
    "WeWorkRemotely": _scrape_weworkremotely,
    "Remote.co": _scrape_remoteco,
    "Wellfound": _scrape_wellfound,
    "NoDesk": _scrape_nodesk,
    "YCombinator": _scrape_ycombinator,
    "Arc": _scrape_arc,
    "GulfTalent": _scrape_gulftalent,
    "NoFluffJobs": _scrape_nofluffjobs,
    "Lemon": _scrape_lemon,
    "JustJoinIt": _scrape_justjoinit,
}


def test_stealth_board(name, debug=True):
    """Run one Playwright board in isolation and print count + samples.
    On 0 results, also prints generic DOM stats to guide selector fixes."""
    if name not in STEALTH_BOARD_FNS:
        print(f"Unknown board '{name}'. Available: {sorted(STEALTH_BOARD_FNS)}")
        return []
    from playwright.sync_api import sync_playwright
    headless = os.getenv("PLAYWRIGHT_HEADLESS", "true").lower() != "false"
    timeout = int(os.getenv("PLAYWRIGHT_TIMEOUT", "30000"))
    fn = STEALTH_BOARD_FNS[name]
    jobs = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        try:
            page = browser.new_page(viewport={"width": 1920, "height": 1080})
            jobs = fn(page, debug=True, timeout=timeout)
            if not jobs or os.getenv("PW_DIAG_LINES", "false").lower() == "true":
                # Diagnostics for selector fixing: what does the DOM actually have?
                try:
                    anchors = page.query_selector_all("a[href]")
                    print(f"  DIAG: {len(anchors)} total <a> tags")
                    shown = 0
                    for a in anchors:
                        href = (a.get_attribute("href") or "")
                        if "job" in href.lower():
                            txt = _clean_text(_safe_text(a))[:100]
                            print(f"    job-href={href[:120]} | text={txt}")
                            shown += 1
                            if shown >= 15:
                                break
                    if shown == 0:
                        print("  DIAG: no href contains 'job'; first 10 anchors:")
                        for a in anchors[:10]:
                            href = (a.get_attribute("href") or "")[:100]
                            txt = _clean_text(_safe_text(a))[:80]
                            print(f"    href={href} | text={txt}")
                except Exception as e:
                    print(f"  DIAG failed: {e}")
        finally:
            try:
                browser.close()
            except Exception:
                pass
    print(f"\n{name}: {len(jobs)} jobs")
    for j in jobs[:3]:
        print(f"  - {j['job_title'][:90]} | {j['apply_url'][:100]}")
    return jobs


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


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    arg = sys.argv[1] if len(sys.argv) > 1 else "all"
    if arg == "all":
        all_jobs = scrape_stealth_boards(debug=True)
        print(f"\nTotal: {len(all_jobs)} jobs")
    else:
        test_stealth_board(arg, debug=True)