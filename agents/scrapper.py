import requests, json
import re
import datetime
from dateutil import parser as date_parser
import time
import random
from bs4 import BeautifulSoup

def normalize_date(date_value, source="unknown"):
    """Normalize any date format to ISO (YYYY-MM-DD)."""
    if not date_value:
        return datetime.date.today().isoformat()
    try:
        # Handle Unix timestamps (both seconds and milliseconds)
        if isinstance(date_value, (int, float)) or (isinstance(date_value, str) and date_value.replace('.', '').isdigit()):
            timestamp = float(date_value)
            # Check for milliseconds
            if timestamp > 10000000000:
                timestamp /= 1000
            return datetime.datetime.utcfromtimestamp(timestamp).strftime('%Y-%m-%d')
        
        # Handle string dates
        if isinstance(date_value, str):
            # Handle ISO date format (just take first 10 chars)
            if len(date_value) >= 10 and date_value[4] == '-' and date_value[3] == '-':  # FIXED LINE
                return date_value[:10]
            # Parse other formats
            return date_parser.parse(date_value).strftime('%Y-%m-%d')
            
    except Exception as e:
        print(f"  Warning: Could not parse date '{date_value}' from {source}: {e}")
        return datetime.date.today().isoformat()
    
    return datetime.date.today().isoformat()

def clean_html(raw_html):
    """Remove HTML tags from text"""
    if not raw_html:
        return ""
    cleanr = re.compile('<.*?>')
    cleaned = re.sub(cleanr, '', str(raw_html))  # FIXED LINE
    # Decode common HTML entities
    cleaned = cleaned.replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&').replace('&quot;', '"')  # FIXED LINE
    return cleaned.strip()



# === UTILITY FUNCTIONS ===
def clean_text(element):
    """Clean text from HTML element or string"""
    if element is None:
        return ""
    if hasattr(element, 'get_text'):
        return element.get_text(strip=True)
    return str(element).strip()

def days_ago(date_str):
    """Simple date check - returns 0 to bypass filtering for now"""
    return 0

# === CONFIGURATION ===

# Updated Master Boards List - Including all new sites
MASTER_BOARDS = {
    # --- API Boards ---
    "Remotive": {
        "url": "https://remotive.com/api/remote-jobs?category=software-dev",
        "type": "api"
    },
    "RemoteOKAPI": {
        "url": "https://remoteok.com/api",
        "type": "api"
    },
    "Arbeitnow": {
        "url": "https://www.arbeitnow.com/api/job-board-api",
        "type": "api"
    },
    # --- HTML Boards ---
    "WeWorkRemotely": {
        "url": "https://weworkremotely.com/remote-full-time-jobs",
        "type": "html"
    },
    "RemoteOK": {
        "url": "https://remoteok.com/remote-dev-jobs",
        "type": "html"
    },
    "Jobspresso": {
        "url": "https://jobspresso.co/?s=full+stack",
        "type": "html"
    },
    "WorkingNomads": {
        "url": "https://www.workingnomads.co/api/exposed_jobs", # <-- Use this new API URL
        "type": "api"  # <-- Change this to "api"
    },
    "EU Remote Jobs": {
        "url": "https://euremotejobs.com/jobs/remote-full-stack",
        "type": "html"
    },
    "Wellfound": {
        "url": "https://wellfound.com/role/r/remote/full-stack-developer",
        "type": "html"
    },
    "Arc": {
        "url": "https://arc.dev/remote-jobs/full-stack-developer",
        "type": "html"
    },
    "Lemon": {
        "url": "https://lemon.io/developers/remote-jobs",
        "type": "html"
    },
    "FlexJobs": {
        "url": "https://www.flexjobs.com/search?remote=yes&experience=entry,mid",
        "type": "html"
    },
    "Remote.co": {
        "url": "https://remote.co/remote-jobs/developer/",
        "type": "html"
    },
    "JustRemote": {
        "url": "https://justremote.co/remote-developer-jobs?exp=junior,mid",
        "type": "html"
    },
    # --- NEW VERIFIED SITES ---
    "NoDesk": {
        "url": "https://nodesk.co/remote-jobs/engineering/",
        "type": "html"
    },
    "RemoteTech": {
        "url": "https://remotetech.io/remote-jobs/developer/",
        "type": "html"
    },
    "Himalayas": {
        "url": "https://himalayas.app/jobs/remote-software-engineering",
        "type": "html"
    },
    "GoRemote": {
        "url": "https://goremote.io/remote-jobs/software-development/",
        "type": "html"
    }
}

# More comprehensive and lenient filters
TECH_FILTER = r"(?i)(node|django|react|mysql|express|backend|back[- ]?end|frontend|front[- ]?end|full[- ]?stack|javascript|python|php|java|angular|vue|typescript|mongodb|postgresql|sql|html|css|api|rest|graphql|docker|aws|git|web|software|developer|engineer)"

EXP_FILTER = re.compile(r"\b(junior|entry.*level|mid.*level|1-3\s?yr|early.*career|0-2\s?yr|developer|engineer|intern|graduate|associate|trainee|jr)\b", re.I)

# More specific exclusion filter
EXCLUDE_FILTER = re.compile(r"\b(senior.*(?:engineer|developer|architect)|lead.*(?:engineer|developer)|principal.*(?:engineer|developer|architect)|engineering.*manager|head.*of.*engineering|staff.*engineer|director.*engineering)\b", re.I)

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0.0.0 Safari/537.36'
    ),
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'Accept-Encoding': 'gzip, deflate',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1'
}

# === RETRY LOGIC ===

def fetch_with_retry(url, headers=None, timeout=30, max_retries=3):
    """Fetch URL with retry logic and random delays"""
    for attempt in range(max_retries):
        try:
            # Add random delay to avoid rate limiting
            time.sleep(random.uniform(1, 3))
            
            response = requests.get(url, headers=headers or HEADERS, timeout=timeout)
            response.raise_for_status()
            return response
        except requests.exceptions.Timeout:
            print(f"  Timeout on attempt {attempt + 1}")
            if attempt < max_retries - 1:
                time.sleep(random.uniform(2, 5))  # Wait longer between retries
                continue
            raise
        except Exception as e:
            print(f"  Error on attempt {attempt + 1}: {e}")
            if attempt < max_retries - 1:
                time.sleep(random.uniform(1, 3))
                continue
            raise

# === API PARSERS ===

def parse_json_remotive(board, data, debug=False):
    results = []
    total_jobs = len(data.get("jobs", []))
    filtered_out = {"exclude": 0, "exp": 0, "tech": 0}
    
    for j in data.get("jobs", []):
        title = j.get("title", "")
        description = j.get("description", "")
        combined_text = f"{title} {description}"
        
        if debug:
            print(f"  Checking: {title}")
        
        if EXCLUDE_FILTER.search(title):
            filtered_out["exclude"] += 1
            if debug: print(f"    ❌ Excluded (senior): {title}")
            continue
            
        # Check tech stack in both title and description
        if not re.search(TECH_FILTER, combined_text):
            filtered_out["tech"] += 1
            if debug: print(f"    ❌ No tech match: {title}")
            continue
            
        # Make experience filter more lenient - check description too
        if not (EXP_FILTER.search(title) or EXP_FILTER.search(description) or 
                any(word in title.lower() for word in ['developer', 'engineer', 'programmer'])):
            filtered_out["exp"] += 1
            if debug: print(f"    ❌ No experience match: {title}")
            continue
            
        if debug: print(f"    ✅ Accepted: {title}")
        
        results.append({
            "job_title": title,
            "company": j.get("company_name", ""),
            "salary": j.get("salary", ""),
            "tech_stack": ", ".join(re.findall(TECH_FILTER, combined_text)[:5]),  # Limit to 5 matches
            "timezone": j.get("candidate_required_location", "Worldwide"),
            "apply_url": j.get("url", ""),
            "summary": clean_html(description)[:200] + "..." if len(clean_html(description)) > 200 else clean_html(description),
            "posted_date_iso": normalize_date(j.get("publication_date")),
            "source": board
        })
    
    if debug:
        print(f"  Total jobs: {total_jobs}")
        print(f"  Filtered out - Exclude: {filtered_out['exclude']}, Experience: {filtered_out['exp']}, Tech: {filtered_out['tech']}")
        print(f"  Final results: {len(results)}")
    
    return results

def parse_json_remoteokapi(board, data, debug=False):
    results = []
    if not isinstance(data, list):
        print(f"  Unexpected data format for {board}")
        return results
        
    for j in data:
        if not isinstance(j, dict):
            continue
            
        title = j.get("position", "")
        description = j.get("description", "")
        tags = j.get("tags", [])
        combined_text = f"{title} {description} {' '.join(tags) if isinstance(tags, list) else ''}"
        
        if EXCLUDE_FILTER.search(title):
            continue
            
        if not re.search(TECH_FILTER, combined_text):
            continue
            
        if not (EXP_FILTER.search(combined_text) or 
                any(word in title.lower() for word in ['developer', 'engineer', 'programmer'])):
            continue
        
        # Fix the timestamp conversion
        # posted_date = datetime.date.today().isoformat()
        # if j.get("date"):
        #     try:
        #         if isinstance(j["date"], (int, float)):
        #             posted_date = datetime.datetime.fromtimestamp(j["date"]).strftime("%Y-%m-%d")
        #         elif isinstance(j["date"], str):
        #             posted_date = j["date"][:10]
        #     except (ValueError, TypeError, OSError):
        #         pass  # Keep default date

        results.append({
            "job_title": title,
            "company": j.get("company", ""),
            "salary": j.get("salary", ""),
            "tech_stack": ", ".join(re.findall(TECH_FILTER, combined_text)[:5]),
            "timezone": j.get("location", "Worldwide"),
            "apply_url": j.get("url", ""),
            "summary": clean_html(description)[:200] + "..." if len(clean_html(description)) > 200 else clean_html(description),
            "posted_date_iso": normalize_date(j.get("publication_date")),
            "source": board
        })
    
    return results

def parse_json_arbeitnow(board, data, debug=False):
    results = []
    
    # Handle different response formats
    jobs = []
    if isinstance(data, dict):
        jobs = data.get("data", [])
    elif isinstance(data, list):
        jobs = data
    else:
        print(f"  Unexpected data format for {board}: {type(data)}")
        return results
    
    if not isinstance(jobs, list):
        print(f"  Jobs data is not a list for {board}")
        return results
    
    for j in jobs:
        if not isinstance(j, dict):
            continue
            
        title = j.get("title", "")
        description = j.get("description", "")
        tags = j.get("tags", [])
        combined_text = f"{title} {description} {' '.join(tags) if isinstance(tags, list) else ''}"
        
        if EXCLUDE_FILTER.search(title):
            continue
            
        if not re.search(TECH_FILTER, combined_text):
            continue
            
        if not (EXP_FILTER.search(combined_text) or 
                any(word in title.lower() for word in ['developer', 'engineer', 'programmer'])):
            continue
        
        # Safe date handling
        # posted_date = datetime.date.today().isoformat()
        # if j.get("created_at"):
        #     try:
        #         posted_date = str(j["created_at"])[:10]
        #     except (ValueError, TypeError):
        #         pass
        
        results.append({
            "job_title": title,
            "company": j.get("company", ""),
            "salary": j.get("salary", ""),
            "tech_stack": ", ".join(re.findall(TECH_FILTER, combined_text)[:5]),
            "timezone": j.get("location", "Worldwide"),
            "apply_url": j.get("url", ""),
            "summary": clean_html(description)[:200] + "..." if len(clean_html(description)) > 200 else clean_html(description),
            "posted_date_iso": normalize_date(j.get("created_at")),
            "source": board
        })
    
    return results

# === HTML PARSERS ===

def parse_html_weworkremotely(html):
    """
    A new, updated parser specifically for WeWorkRemotely's current HTML structure.
    """
    soup = BeautifulSoup(html, "html.parser")
    results = []
    
    # This selector correctly finds the container for each job.
    job_elements = soup.select('section.jobs li')
    print(f"  Found {len(job_elements)} potential job elements with selector: section.jobs li")
    
    for element in job_elements:
        # We need to skip some empty or ad-related list items.
        # A real job listing will have a 'company' span.
        if not element.select_one('span.company'):
            continue
            
        try:
            # The title is in a 'title' span.
            title_elem = element.select_one('span.title')
            title = clean_text(title_elem)

            # The company is in a 'company' span.
            company_elem = element.select_one('span.company')
            company = clean_text(company_elem)

            # The link is in an 'a' tag with a href starting with /remote-jobs/
            link_elem = element.select_one('a[href^="/remote-jobs/"]')
            if not link_elem:
                continue # Skip if it's not a job link

            link = "https://weworkremotely.com" + link_elem['href']
            
            # --- Now, apply your filters ---
            if EXCLUDE_FILTER.search(title):
                print(f"    - Filtering out (Senior/Lead): '{title}'")
                continue
            
            if not re.search(TECH_FILTER, title):
                print(f"    - Filtering out (No Tech Match): '{title}'")
                continue
            
            # If it passes all checks, add it to the results
            print(f"    + Found Job: '{title}' at {company}")
            results.append({
                "job_title": title,
                "company": company,
                "salary": clean_text(element.select_one('span.salary')), # Adding salary
                "tech_stack": ", ".join(re.findall(TECH_FILTER, title)[:5]),
                "timezone": clean_text(element.select_one('span.region')),
                "apply_url": link,
                "summary": f"Full-Time listing from WeWorkRemotely.",
                "posted_date_iso": datetime.date.today().isoformat(),
                "source": "WeWorkRemotely"
            })
            
        except Exception as e:
            # This prevents one bad job listing from crashing the whole parser
            print(f"    - Error parsing one element: {e}")
            continue
    
    return results

def parse_html_wellfound(html):
    soup = BeautifulSoup(html, "html.parser")
    results = []
    
    # Based on the HTML structure from your screenshot
    # Look for job listing containers
    job_containers = soup.select('div[class*="styles_component__dBicB"]')
    print(f"  Found {len(job_containers)} job containers")
    
    for container in job_containers:
        try:
            # Extract title from the specific class structure
            title_elem = container.select_one('span[class*="styles_title__xpQDw"]')
            if not title_elem:
                continue
                
            title = clean_text(title_elem)
            if not title:
                continue
            
            # Apply filters
            if EXCLUDE_FILTER.search(title):
                continue
                
            if not re.search(TECH_FILTER, title):
                continue
                
            if not (EXP_FILTER.search(title) or 
                    any(word in title.lower() for word in ['developer', 'engineer', 'programmer'])):
                continue
            
            # Extract job URL from the main link
            link_elem = container.select_one('a[href*="/jobs/"]')
            link = ""
            if link_elem:
                link = link_elem.get('href', '')
                if link and not link.startswith('http'):
                    link = 'https://wellfound.com' + link
            
            # Extract location from styles_location class
            location_elem = container.select_one('span[class*="styles_location__"]')
            location = clean_text(location_elem) if location_elem else "Remote"
            
            # Extract salary/compensation
            compensation_elem = container.select_one('span[class*="styles_compensation__"]')
            salary = clean_text(compensation_elem) if compensation_elem else ""
            
            # Extract company name (might be in parent or sibling elements)
            company = ""
            company_selectors = [
                'span[class*="company"]',
                'div[class*="company"]',
                '.company-name'
            ]
            for selector in company_selectors:
                company_elem = container.select_one(selector)
                if company_elem:
                    company = clean_text(company_elem)
                    break
            
            results.append({
                "job_title": title,
                "company": company or "Unknown",
                "salary": salary,
                "tech_stack": ", ".join(re.findall(TECH_FILTER, title)[:5]),
                "timezone": location,
                "apply_url": link,
                "summary": f"Wellfound listing - {location}" + (f" - {salary}" if salary else ""),
                "posted_date_iso": normalize_date(None),
                "source": "Wellfound"
            })
            
        except Exception as e:
            continue
    
    return results

def parse_html_nodesk(html):
    """Parser for NoDesk jobs"""
    soup = BeautifulSoup(html, "html.parser")
    results = []
    
    # NoDesk uses various selectors for job listings
    selectors = [
        '.job-listing',
        '.remote-job',
        'article',
        '.job',
        '[class*="job"]'
    ]
    
    job_elements = []
    for selector in selectors:
        job_elements = soup.select(selector)
        if job_elements:
            print(f"  Found {len(job_elements)} NoDesk elements with selector: {selector}")
            break
    
    for element in job_elements[:30]:
        try:
            # Find title
            title_selectors = ['.title', 'h1', 'h2', 'h3', '.position', '.job-title', 'a[href]']
            title = ""
            link = ""
            
            for ts in title_selectors:
                title_elem = element.select_one(ts)
                if title_elem:
                    title = clean_text(title_elem)
                    if title and title_elem.name == 'a' and title_elem.get('href'):
                        link = title_elem['href']
                    if title:
                        break
            
            if not title or len(title) < 3:
                continue
            
            # Apply filters
            if EXCLUDE_FILTER.search(title):
                continue
                
            if not re.search(TECH_FILTER, title):
                continue
                
            if not (EXP_FILTER.search(title) or 
                    any(word in title.lower() for word in ['developer', 'engineer', 'programmer'])):
                continue
            
            # Get company
            company_selectors = ['.company', '.employer', '.company-name']
            company = ""
            for cs in company_selectors:
                company_elem = element.select_one(cs)
                if company_elem:
                    company = clean_text(company_elem)
                    break
            
            # Fix relative URLs
            if link and not link.startswith('http'):
                if link.startswith('/'):
                    link = "https://nodesk.co" + link
                else:
                    link = "https://nodesk.co/" + link
            
            results.append({
                "job_title": title,
                "company": company or "Unknown",
                "salary": "",
                "tech_stack": ", ".join(re.findall(TECH_FILTER, title)[:5]),
                "timezone": "Remote",
                "apply_url": link or "",
                "summary": "NoDesk remote listing",
                "posted_date_iso": normalize_date(None),
                "source": "NoDesk"
            })
            
        except Exception as e:
            continue
    
    return results

def parse_html_himalayas(html):
    """Parser for Himalayas jobs"""
    soup = BeautifulSoup(html, "html.parser")
    results = []
    
    # Himalayas job selectors
    selectors = [
        '[data-testid*="job"]',
        '.job-card',
        '.job-listing',
        'article',
        '[class*="job"]'
    ]
    
    job_elements = []
    for selector in selectors:
        job_elements = soup.select(selector)
        if job_elements:
            print(f"  Found {len(job_elements)} Himalayas elements with selector: {selector}")
            break
    
    for element in job_elements[:30]:
        try:
            # Find title
            title_selectors = ['.title', 'h1', 'h2', 'h3', '.position', '.job-title', 'a[href*="jobs"]']
            title = ""
            link = ""
            
            for ts in title_selectors:
                title_elem = element.select_one(ts)
                if title_elem:
                    title = clean_text(title_elem)
                    if title and title_elem.name == 'a' and title_elem.get('href'):
                        link = title_elem['href']
                    if title:
                        break
            
            if not title or len(title) < 3:
                continue
            
            # Apply filters
            if EXCLUDE_FILTER.search(title):
                continue
                
            if not re.search(TECH_FILTER, title):
                continue
                
            if not (EXP_FILTER.search(title) or 
                    any(word in title.lower() for word in ['developer', 'engineer', 'programmer'])):
                continue
            
            # Get company
            company_selectors = ['.company', '.employer', '.company-name']
            company = ""
            for cs in company_selectors:
                company_elem = element.select_one(cs)
                if company_elem:
                    company = clean_text(company_elem)
                    break
            
            # Fix relative URLs
            if link and not link.startswith('http'):
                if link.startswith('/'):
                    link = "https://himalayas.app" + link
                else:
                    link = "https://himalayas.app/" + link
            
            results.append({
                "job_title": title,
                "company": company or "Unknown",
                "salary": "",
                "tech_stack": ", ".join(re.findall(TECH_FILTER, title)[:5]),
                "timezone": "Remote",
                "apply_url": link or "",
                "summary": "Himalayas remote listing",
                "posted_date_iso": normalize_date(None),
                "board": "Himalayas"

            })
            
        except Exception as e:
            continue
    
    return results

def parse_html_generic(html, board_name, base_url):
    """Generic HTML parser for most job sites"""
    soup = BeautifulSoup(html, "html.parser")
    results = []
    
    # Common job listing selectors
    selectors = [
        '.job',
        '.job-card',
        '.listing',
        '.position',
        'article',
        '.job-item',
        '[class*="job"]',
        'li[class*="job"]',
        '.vacancy'
    ]
    
    job_elements = []
    for selector in selectors:
        job_elements = soup.select(selector)
        if job_elements:
            print(f"  Found {len(job_elements)} elements with selector: {selector}")
            break
    
    for element in job_elements[:50]:  # Limit to first 50
        try:
            # Find title
            title_selectors = ['.title', 'h1', 'h2', 'h3', '.position', '.job-title', 'a[href]']
            title = ""
            link = ""
            
            for ts in title_selectors:
                title_elem = element.select_one(ts)
                if title_elem:
                    title = clean_text(title_elem)
                    if title and title_elem.name == 'a' and title_elem.get('href'):
                        link = title_elem['href']
                    if title:
                        break
            
            if not title or len(title) < 3:
                continue
            
            # Apply filters
            if EXCLUDE_FILTER.search(title):
                continue
                
            if not re.search(TECH_FILTER, title):
                continue
                
            if not (EXP_FILTER.search(title) or 
                    any(word in title.lower() for word in ['developer', 'engineer', 'programmer'])):
                continue
            
            # Get other details
            company_selectors = ['.company', '.employer', '.company-name', 'h3', 'h4']
            company = ""
            for cs in company_selectors:
                company_elem = element.select_one(cs)
                if company_elem and clean_text(company_elem) != title:
                    company = clean_text(company_elem)
                    break
            
            # Get link if not found yet
            if not link:
                link_elem = element.select_one('a[href]')
                if link_elem:
                    link = link_elem['href']
            
            # Fix relative URLs
            if link and not link.startswith('http'):
                if link.startswith('/'):
                    link = base_url + link
                else:
                    link = base_url + '/' + link
            
            results.append({
                "job_title": title,
                "company": company or "Unknown",
                "salary": "",
                "tech_stack": ", ".join(re.findall(TECH_FILTER, title)[:5]),
                "timezone": "Remote",
                "apply_url": link or "",
                "summary": f"Listing from {board_name}",
                "posted_date_iso": normalize_date(None),
                "source": board_name

            })
            
        except Exception as e:
            continue
    
    return results

def parse_json_workingnomads(board, data, debug=False):
    """
    A new parser for the Working Nomads JSON API endpoint.
    """
    results = []
    if not isinstance(data, list):
        print(f"  Unexpected data format for {board}, expected a list.")
        return results

    for j in data:
        title = j.get("position", "")
        description = j.get("description", "")
        tags = j.get("tags", "")
        combined_text = f"{title} {description} {tags}"

        # Apply your existing filters
        if EXCLUDE_FILTER.search(title):
            if debug: print(f"    - Filtering out (Senior/Lead): '{title}'")
            continue
            
        if not re.search(TECH_FILTER, combined_text):
            if debug: print(f"    - Filtering out (No Tech Match): '{title}'")
            continue
            
        # Add the job to results
        if debug: print(f"    + Found Job: '{title}'")
        
        results.append({
            "job_title": title,
            "company": j.get("company_name", ""),
            "salary": "", # Salary is not provided in this API endpoint
            "tech_stack": tags,
            "timezone": "Remote",
            "apply_url": j.get("url", ""),
            "summary": clean_html(description)[:200] + "..." if len(clean_html(description)) > 200 else clean_html(description),
            "posted_date_iso": normalize_date(j.get("pub_date")),
            "source": board

        })
    
    return results

# In scrapper.py, add this new function alongside your other parsers

def parse_html_justremote(html, base_url, board):
    """
    A new, dedicated parser for JustRemote's current HTML structure.
    """
    soup = BeautifulSoup(html, "html.parser")
    results = []
    
    # The new main selector for each job posting
    job_elements = soup.select('div.job-card__container')
    print(f"  Found {len(job_elements)} potential job elements with selector: div.job-card__container")

    for element in job_elements:
        try:
            # The title and link are in the same element
            title_elem = element.select_one('a.job-card__title')
            if not title_elem:
                continue

            title = clean_text(title_elem)
            link = title_elem.get('href', '')
            if link and not link.startswith('http'):
                link = base_url + link

            # Get the company name
            company_elem = element.select_one('div.job-card__company-name')
            company = clean_text(company_elem)
            
            # --- Apply your filters ---
            if EXCLUDE_FILTER.search(title):
                continue
            if not re.search(TECH_FILTER, title):
                continue
            
            print(f"    + Found Job: '{title}' at {company}")
            results.append({
                "job_title": title,
                "company": company,
                "salary": "", # Salary info is not easily accessible on the main page
                "tech_stack": ", ".join(re.findall(TECH_FILTER, title)[:5]),
                "timezone": "Remote",
                "apply_url": link,
                "summary": f"Full-Time listing from JustRemote.",
                "posted_date_iso": normalize_date(None),
                "source": board

            })
        except Exception as e:
            print(f"    - Error parsing one element: {e}")
            continue
            
    return results


# === MAIN FETCH LOGIC ===

def fetch_jobs_from_board(name, info, debug=False):
    url = info['url']
    typ = info['type']
    
    try:
        if typ == "api":
            print(f"Fetching (API): {name}")
            response = fetch_with_retry(url, timeout=30)
            data = response.json()
            
            if name == "Remotive":
                return parse_json_remotive(name, data, debug)
            elif name == "RemoteOKAPI":
                return parse_json_remoteokapi(name, data, debug)
            elif name == "Arbeitnow":
                return parse_json_arbeitnow(name, data, debug)
            elif name == "WorkingNomads":
                return parse_json_workingnomads(name, data, debug)
            else:
                print(f"  No specific parser for {name}, skipping")
                return []
                
        elif typ == "html":
            print(f"Fetching (HTML): {name}")
            response = fetch_with_retry(url, timeout=40)
            html = response.text
            print(f"  HTML length: {len(html)}")
            
            # Get base URL for relative links
            base_url = f"https://{url.split('/')[2]}"
            
            if name == "WeWorkRemotely":
                return parse_html_weworkremotely(html)
            elif name == "Wellfound":
                return parse_html_wellfound(html)
            elif name == "NoDesk":
                return parse_html_nodesk(html)
            elif name == "Himalayas":
                return parse_html_himalayas(html)
            elif name == "RemoteTech" or name == "GoRemote":
                # Use generic parser for RemoteTech and GoRemote
                return parse_html_generic(html, name, base_url)
            elif name == "JustRemote":
               return parse_html_justremote(html, base_url , name)
            else:
                # Use generic parser for other HTML sites
                return parse_html_generic(html, name, base_url)
        else:
            print(f"  Unknown type for {name}")
            return []
            
    except Exception as e:
        print(f"  {name} scrape error: {e}")
        return []

def scrape_all(debug=False):
    """Main scraping function"""
    jobs = []
    working_scrapers = []
    failed_scrapers = []
    
    print("🚀 Starting job scraping...")
    
    for name, info in MASTER_BOARDS.items():
        print(f"\n--- Processing {name} ---")
        try:
            jobs_from_board = fetch_jobs_from_board(name, info, debug)
            count = len(jobs_from_board)
            
            if count > 0:
                print(f"✅ Parsed {count} jobs from {name}")
                working_scrapers.append(name)
                jobs.extend(jobs_from_board)
            else:
                print(f"⚠️  No jobs found from {name}")
                failed_scrapers.append(name)
                
        except Exception as e:
            print(f"❌ {name} completely failed: {e}")
            failed_scrapers.append(name)
        
        # Add delay between requests to avoid rate limiting
        time.sleep(random.uniform(2, 4))

        if jobs:
         jobs.sort(key=lambda x: x['posted_date_iso'], reverse=True)
        print(f"✅ Sorted {len(jobs)} jobs by date (newest first)")
    
    print(f"\n=== SCRAPING SUMMARY ===")
    print(f"✅ Working scrapers ({len(working_scrapers)}): {working_scrapers}")
    print(f"❌ Failed scrapers ({len(failed_scrapers)}): {failed_scrapers}")
    print(f"📊 Total jobs scraped: {len(jobs)}")
    
    return jobs

def test_individual_scraper(name, debug=True):
    """Test a single scraper with debug info"""
    if name not in MASTER_BOARDS:
        print(f"Scraper {name} not found")
        return []
        
    print(f"\n=== Testing {name} ===")
    info = MASTER_BOARDS[name]
    
    try:
        jobs = fetch_jobs_from_board(name, info, debug)
        print(f"Results: {len(jobs)} jobs")
        
        if jobs:
            print("\nSample job:")
            print(f"Title: {jobs[0]['job_title']}")
            print(f"Company: {jobs[0]['company']}")
            print(f"URL: {jobs[0]['apply_url']}")
        
        return jobs
        
    except Exception as e:
        print(f"❌ Error testing {name}: {e}")
        return []

if __name__ == "__main__":
    # Test mode - uncomment to test individual scrapers
    # test_individual_scraper("NoDesk")
    # test_individual_scraper("Himalayas")
    # test_individual_scraper("RemoteTech")
    # test_individual_scraper("GoRemote")
    # test_individual_scraper("Remotive", debug=True)

    
    # Full scraping
    jobs = scrape_all(debug=False)

    # Sort by date (newest first)
    jobs.sort(key=lambda x: x['posted_date_iso'], reverse=True)

    
    # Print sample results
    if jobs:
        print(f"\n=== SAMPLE RESULTS ===")
        for i, job in enumerate(jobs[:3]):  # Show first 3 jobs
            print(f"\nJob {i+1}:")
            print(f"Title: {job['job_title']}")
            print(f"Company: {job['company']}")
            print(f"Tech: {job['tech_stack']}")
            print(f"URL: {job['apply_url']}")
        print(f"Total jobs found: {len(jobs)}")