import os
import re
import datetime


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
    return element.inner_text().strip() if element else ""


def _with_base(url, base_url):
    if not url:
        return ""
    return url if url.startswith("http") else base_url + url


def scrape_stealth_boards(debug=False):
    """Scrape blocker-prone boards with Playwright stealth, if installed."""
    try:
        from playwright.sync_api import sync_playwright
        from playwright_stealth import stealth_sync
    except ImportError:
        print("Playwright stealth tools are not installed. Run: pip install playwright playwright-stealth")
        return []

    headless = os.getenv("PLAYWRIGHT_HEADLESS", "true").lower() != "false"
    jobs = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        )
        stealth_sync(page)

        jobs.extend(_scrape_weworkremotely(page, debug))
        jobs.extend(_scrape_remoteco(page, debug))
        jobs.extend(_scrape_wellfound(page, debug))
        jobs.extend(_scrape_nodesk(page, debug))

        browser.close()

    return jobs


def _scrape_weworkremotely(page, debug=False):
    jobs = []
    source = "WeWorkRemotely"
    try:
        page.goto("https://weworkremotely.com/categories/remote-programming-jobs", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_selector("section.jobs", timeout=15000)
        for el in page.query_selector_all("section.jobs li.feature"):
            title = _safe_text(el.query_selector("span.title"))
            company = _safe_text(el.query_selector("span.company"))
            link = el.query_selector('a[href^="/remote-jobs/"]')
            url = _with_base(link.get_attribute("href") if link else "", "https://weworkremotely.com")
            if title and url:
                jobs.append(_job(title, company, url, source, "WeWorkRemotely remote programming listing"))
    except Exception as exc:
        print(f"{source} Playwright scrape failed: {exc}")
    if debug:
        print(f"{source} Playwright returned {len(jobs)} jobs")
    return jobs


def _scrape_remoteco(page, debug=False):
    jobs = []
    source = "Remote.co"
    try:
        page.goto("https://remote.co/remote-jobs/developer/", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_selector("body", timeout=10000)
        for el in page.query_selector_all("a[href*='/job/'], a[href*='remote-jobs']"):
            title = re.sub(r"\s+", " ", _safe_text(el))
            href = el.get_attribute("href") or ""
            if len(title) < 5 or "developer" not in title.lower() and "engineer" not in title.lower():
                continue
            jobs.append(_job(title, "", _with_base(href, "https://remote.co"), source, "Remote.co developer listing"))
    except Exception as exc:
        print(f"{source} Playwright scrape failed: {exc}")
    if debug:
        print(f"{source} Playwright returned {len(jobs)} jobs")
    return jobs[:30]


def _scrape_wellfound(page, debug=False):
    jobs = []
    source = "Wellfound"
    try:
        page.goto("https://wellfound.com/role/r/remote/full-stack-developer", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_selector("body", timeout=10000)
        for el in page.query_selector_all("a[href*='/jobs/']"):
            title = re.sub(r"\s+", " ", _safe_text(el))
            href = el.get_attribute("href") or ""
            if len(title) < 5:
                continue
            jobs.append(_job(title, "", _with_base(href, "https://wellfound.com"), source, "Wellfound remote listing"))
    except Exception as exc:
        print(f"{source} Playwright scrape failed: {exc}")
    if debug:
        print(f"{source} Playwright returned {len(jobs)} jobs")
    return jobs[:30]


def _scrape_nodesk(page, debug=False):
    jobs = []
    source = "NoDesk"
    try:
        page.goto("https://nodesk.co/remote-jobs/engineering/", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_selector("body", timeout=10000)
        for el in page.query_selector_all("a[href*='/jobs/']"):
            title = re.sub(r"\s+", " ", _safe_text(el))
            href = el.get_attribute("href") or ""
            if len(title) < 5:
                continue
            jobs.append(_job(title, "", _with_base(href, "https://nodesk.co"), source, "NoDesk engineering listing"))
    except Exception as exc:
        print(f"{source} Playwright scrape failed: {exc}")
    if debug:
        print(f"{source} Playwright returned {len(jobs)} jobs")
    return jobs[:30]
