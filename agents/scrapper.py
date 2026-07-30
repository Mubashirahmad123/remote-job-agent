import os
import requests
import json
import re
import datetime
from dateutil import parser as date_parser
import time
import random
from bs4 import BeautifulSoup
import html as _html


# ---- feedparser for RSS ----
try:
    import feedparser
    print("✅ feedparser is available")
except ImportError:
    feedparser = None


# =============================================================================
# RSS PARSER
# =============================================================================

def fetch_authentic_jobs_rss(feed_url="https://authenticjobs.com/rss?category=Developer"):
    if feedparser is None:
        print("  feedparser not installed; falling back to HTML parser for AuthenticJobs")
        return []
    d = feedparser.parse(feed_url)
    out = []
    for e in d.entries:
        title = e.title or ""
        if EXCLUDE_FILTER.search(title) or not re.search(TECH_FILTER, title):
            continue
        out.append({
            "job_title": title,
            "company": "",
            "salary": "",
            "tech_stack": top_techs(title),
            "timezone": "Remote",
            "apply_url": e.link,
            "summary": clean_html(getattr(e, 'summary', ""))[:200],
            "posted_date_iso": normalize_date(getattr(e, 'published', None), "AuthenticJobs"),
            "source": "AuthenticJobs"
        })
    return out


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def normalize_date(date_value, source="unknown"):
    """Normalize any date format to ISO (YYYY-MM-DD)."""
    try:
        ts = None
        if isinstance(date_value, (int, float)):
            ts = float(date_value)
        elif isinstance(date_value, str):
            s = date_value.strip()
            if len(s) >= 10 and s[4] == '-' and s[7] == '-':
                return s[:10]
            try:
                ts = float(s)
            except ValueError:
                ts = None
        if ts is not None:
            if ts > 10_000_000_000:
                ts /= 1000
            return datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).strftime('%Y-%m-%d')

        if date_value:
            return date_parser.parse(str(date_value)).strftime('%Y-%m-%d')
    except Exception as e:
        print(f"  Warning: Could not parse date '{date_value}' from {source}: {e}")
    return datetime.date.today().isoformat()


def clean_html(raw_html):
    if not raw_html:
        return ""
    cleaned = re.sub(r'<.*?>', '', str(raw_html))
    return _html.unescape(cleaned).strip()


def top_techs(text, limit=5):
    """Extract up to N unique, normalized tech keywords from text."""
    found = re.findall(TECH_FILTER, text or "")
    seen, out = set(), []
    for w in (t.lower() for t in found):
        if w not in seen:
            seen.add(w)
            out.append(w)
            if len(out) == limit:
                break
    return ", ".join(out)


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


# =============================================================================
# CONFIGURATION
# =============================================================================

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
    "Himalayas": {
        "url": "https://himalayas.app/api/jobs?limit=100",
        "type": "api"
    },
    "Jobicy": {
        "url": "https://jobicy.com/api/v0/remote-jobs?count=50&tag=developer",
        "type": "api"
    },
    "TheMuse": {
        "url": "https://www.themuse.com/api/public/jobs?page=1&level=Entry%20Level&level=Mid%20Level",
        "type": "api"
    },
    "Adzuna": {
        "url": "https://api.adzuna.com/v1/api/jobs/gb/search/1",
        "type": "api"
    },
    # --- HTML Boards ---
    "RemoteOK": {
        "url": "https://remoteok.com/remote-dev-jobs",
        "type": "html"
    },
    "Jobspresso": {
        "url": "https://jobspresso.co/?s=full+stack",
        "type": "html"
    },
    "WorkingNomads": {
        "url": "https://www.workingnomads.co/api/exposed_jobs",
        "type": "api"
    },
    "EU Remote Jobs": {
        "url": "https://euremotejobs.com/jobs/remote-full-stack",
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
    "JustRemote": {
        "url": "https://justremote.co/remote-developer-jobs?exp=junior,mid",
        "type": "html"
    },
    # --- NEW VERIFIED SITES ---
    "RemoteTech": {
        "url": "https://remotetech.io/remote-jobs/developer/",
        "type": "html"
    },
    "GoRemote": {
        "url": "https://goremote.io/remote-jobs/software-development/",
        "type": "html"
    },
        "YCombinator": {
        "url": "https://www.workatastartup.com/jobs?remote=true&role=engineering",
        "type": "html"
    },
}

ADDITIONAL_BOARDS = {
    # —— High-yield dev/remote (global) ——
    "Remote4me": {"url": "https://remote4me.com/developer-jobs", "type": "html"},
    "DailyRemote": {"url": "https://dailyremote.com/remote-developer-jobs", "type": "html"},
    "AuthenticJobs": {"url": "https://authenticjobs.com/?category=Developer", "type": "html"},
    "Remojobs-Frontend": {"url": "https://remojobs.com/remote-frontend-jobs", "type": "html"},
    "Remojobs-Backend": {"url": "https://remojobs.com/remote-backend-jobs", "type": "html"},
    "Remojobs-Fullstack": {"url": "https://remojobs.com/remote-full-stack-jobs", "type": "html"},
    "RemoteFrontendJobs": {"url": "https://remotefrontendjobs.com", "type": "html"},
    "FindBacon": {"url": "https://findbacon.com/jobs", "type": "html"},

    # —— Europe & UK specialists ——
    "LandingJobs": {"url": "https://landing.jobs/jobs?work_model=remote", "type": "html"},
    "WeAreDevelopers": {"url": "https://www.wearedevelopers.com/jobs", "type": "html"},
    "NoFluffJobs": {"url": "https://nofluffjobs.com/pl/remote", "type": "html"},
    "JustJoinIt": {"url": "https://justjoin.it/all-locations/remote", "type": "html"},
    "CWJobs": {"url": "https://www.cwjobs.co.uk/jobs/remote", "type": "html"},
    "WorkInStartups": {"url": "https://workinstartups.com/remote-jobs", "type": "html"},

    # —— US / Americas ——
    "BuiltIn": {"url": "https://builtin.com/jobs/remote", "type": "html"},
    "Dice": {"url": "https://www.dice.com/jobs/q-remote+developer-jobs", "type": "html"},

    # —— Middle East / India ——
    "GulfTalent": {"url": "https://www.gulftalent.com/remote-jobs", "type": "html"},
    "Naukri": {"url": "https://www.naukri.com/remote-developer-jobs", "type": "html"},
    "NaukriGulf": {"url": "https://www.naukrigulf.com/remote-jobs", "type": "html"},
    "FounditIN": {"url": "https://www.foundit.in/srp/results?query=remote%20developer", "type": "html"},
    "Shine": {"url": "https://www.shine.com/job-search/remote-developer-jobs", "type": "html"},
    "TimesJobs": {"url": "https://www.timesjobs.com/candidate/job-search.html?from=submit&searchType=personalizedSearch&txtKeywords=remote%20developer", "type": "html"},

    # —— Aggregators / niche ——
    "TrueUp": {"url": "https://www.trueup.io/remote-jobs", "type": "html"},
    "RemoteRocketship": {"url": "https://www.remoterocketship.com/remote-jobs", "type": "html"},
    "RemoteJobsCom": {"url": "https://remotejobs.com/jobs", "type": "html"},
    "Remotees": {"url": "https://remotees.com/remote-jobs", "type": "html"}
}
MASTER_BOARDS.update(ADDITIONAL_BOARDS)


# =============================================================================
# FILTERS
# =============================================================================

TECH_FILTER = r"(?i)(node|django|react|mysql|express|backend|back[- ]?end|frontend|front[- ]?end|full[- ]?stack|javascript|python|php|java|angular|vue|typescript|mongodb|postgresql|sql|html|css|api|rest|graphql|docker|aws|git|web|software|developer|engineer)"

EXP_FILTER = re.compile(r"\b(junior|entry.*level|mid.*level|1-3\s?yr|early.*career|0-2\s?yr|developer|engineer|programmer|intern|graduate|associate|trainee|jr)\b", re.I)

EXCLUDE_FILTER = re.compile(r"\b(senior.*(?:engineer|developer|architect)|lead.*(?:engineer|developer)|principal.*(?:engineer|developer|architect)|engineering.*manager|head.*of.*engineering|staff.*engineer|director.*engineering)\b", re.I)

DEV_TITLE_FILTER = re.compile(r"""(?ix)
    (
        developer | engineer | programmer | backend | back[-\s]?end |
        frontend | front[-\s]?end | fullstack | full[-\s]?stack |
        software | node\.?js | django | react |
        python | typescript | javascript | api\ developer | web\ developer |
        mobile\ developer
    )
""")

NON_DEV_FILTER = re.compile(r"""(?ix)
    (
        # Support / IT
        service\ desk | help\ desk | technical\ support | it\ support |
        desktop\ support | customer\ support |
        
        # Infrastructure / Ops
        network\ engineer | network\ administrator |
        systems\ engineer(?!.*software) | system\ engineer(?!.*software) |
        platform\ engineer(?!.*software) | production\ engineer(?!.*software) |
        
        # Security
        cybersecurity | infosec | penetration\ tester |
        security\ engineer(?!.*software|application) |
        
        # Data / ML / AI
        data\ scientist | data\ analyst | data\ engineer(?!.*software) |
        ml\ engineer | machine\ learning | deep\ learning |
        ai\ engineer | ai\ researcher | nlp\ engineer | computer\ vision |
        data\ science | ai\ ml |
        
        # QA / Testing
        qa\ engineer | qa\ tester | test\ engineer | automation\ tester |
        manual\ tester | quality\ assurance | qa\ automation | test\ automation |
        
        # Business / CRM / ERP
        salesforce | sap | netsuite | dynamics\s*365 | d365 |
        servicenow | workday | sharepoint | mulesoft |
        
        # Integration / ETL / Legacy
        etl\ engineer | mainframe | cobol | as400 | rpg\ developer |
        
        # Non-software engineering
        manufacturing | fabrication | welding | aeronautical |
        aerospace\ engineer | civil\ engineer | mechanical\ engineer |
        electrical\ engineer(?!.*software) | comint | cesm | cecm |
        
        # Non-dev roles
        marketing | sales | designer | copywriter | accountant | finance |
        recruiter | human\ resources | customer\ success |
        content\ writer | seo | social\ media | product\ manager |
        project\ manager | business\ analyst | operations\ manager |
        office\ manager | graphic\ design | ui\ designer | ux\ designer |
        illustrator | virtual\ assistant | community\ manager |
        account\ executive | business\ development |
        scrum\ master | product\ owner | technical\ writer | documentation |
        tutor | instructor | teacher | lecturer |
        
        # Game / Embedded / Hardware
        game\ developer | game\ designer | unity\ developer | unreal\ engine |
        embedded | firmware | hardware\ engineer | chip\ design | vlsi |
        
        # Blockchain
        blockchain | solidity | smart\ contract |
        
        # DevOps / SRE
        devops | sre | site\ reliability | cloud\ architect |
        
        # Vague / low-quality
        volunteer | internship(?!.*developer)
    )
""", re.I)

SENIORITY_FILTER = re.compile(r"""(?ix)
    \b(
        senior | sr\.? | lead | principal | staff | architect |
        director | manager | vp | head\ of | cto | ceo
    )\b
""")


# =============================================================================
# LOCATION / COUNTRY FILTER — COMPREHENSIVE
# =============================================================================

# Your whitelist (what you WANT to see)
ALLOWED_COUNTRY_TERMS = [
    # Region keywords
    "worldwide", "global", "anywhere", "anywhere in the world",
    "remote", "fully remote", "remote first", "distributed team",
    "eu timezone", "europe", "eu", "european union", "emea", "emea remote",
    "cet", "cest", "eet", "gmt", "utc",
    "apac", "asia pacific", "latam", "latin america",
    "north america", "na remote", "us timezone", "est", "pst", "cst", "mst",
    
    # UK & Ireland
    "uk", "united kingdom", "london", "england", "scotland", "wales", "britain", 
    "ireland", "ireland republic", "dublin", "northern ireland",
    
    # Tier 1: High-volume English-friendly EU
    "germany", "deutschland", "berlin", "munich", "hamburg", "cologne",
    "netherlands", "nederland", "amsterdam", "rotterdam", "the hague",
    "sweden", "sverige", "stockholm", "gothenburg",
    "denmark", "danmark", "copenhagen",
    "norway", "norge", "oslo",
    "finland", "suomi", "helsinki",
    "poland", "polska", "warsaw", "krakow", "wroclaw", "poznan", "gdansk",
    "portugal", "lisbon", "porto",
    "estonia", "eesti", "tallinn",
    "spain", "espana", "barcelona", "madrid", "valencia", "seville",
    
    # Tier 2: Good but smaller / language barriers
    "france", "frankreich", "paris", "lyon", "marseille",
    "belgium", "belgie", "brussels", "antwerp",
    "italy", "italia", "milan", "rome", "turin", "bologna",
    "czech republic", "czechia", "prague", "brno",
    "romania", "românia", "bucharest", "cluj", "timisoara",
    "lithuania", "lietuva", "vilnius",
    "latvia", "latvija", "riga",
    "slovenia", "ljubljana",
    "croatia", "zagreb",
    "serbia", "belgrade",
    "hungary", "budapest",
    "slovakia", "bratislava",
    "bulgaria", "sofia",
    "greece", "athens",
    
    # Tier 3: High salary, low volume
    "switzerland", "swiss", "schweiz", "zurich", "geneva", "basel", "bern",
    "austria", "österreich", "vienna", "graz", "linz",
    "luxembourg",
    
    # India
    "india", "indian", "bangalore", "bengaluru", "mumbai", "delhi",
    "hyderabad", "chennai", "pune", "kolkata", "gurgaon", "noida",
    "ahmedabad", "jaipur",
    
    # APAC
    "australia", "sydney", "melbourne", "brisbane", "perth", "adelaide",
    "new zealand", "nz", "auckland", "wellington", "christchurch",
    "singapore",
    
    # United States
    "usa", "united states", "america", "american", "us",
    "new york", "nyc", "san francisco", "bay area", "silicon valley",
    "los angeles", "la", "chicago", "seattle", "austin", "boston",
    "denver", "atlanta", "miami", "dallas", "houston", "phoenix",
    "philadelphia", "portland", "san diego", "washington dc",
    
    # Americas
    "canada", "toronto", "vancouver", "montreal", "ottawa", "calgary",
    "mexico", "mexico city", "guadalajara",
    "brazil", "brasil", "sao paulo", "rio de janeiro",
    "argentina", "buenos aires",
    "chile", "santiago",
    "colombia", "bogota", "medellin",
    
    # Middle East / Africa
    "uae", "dubai", "united arab emirates", "abu dhabi",
    "saudi arabia", "riyadh",
    "qatar", "doha",
    "kuwait",
    "bahrain",
    "oman",
    "south africa", "cape town", "johannesburg",
    
    # Turkey (your home base)
    "turkey", "türkiye", "istanbul", "ankara", "izmir",
]

# Comprehensive list of ALL countries and common aliases for detection
# This is used to detect "India" even if India is NOT in your allowlist
ALL_COUNTRY_NAMES = {
    # Major non-allowed countries (common in remote job spam)
    "india", "indian", "bangalore", "bengaluru", "mumbai", "delhi", "hyderabad", "chennai", "pune", "kolkata",
    "gurgaon", "noida", "ahmedabad", "jaipur",
    "pakistan", "karachi", "lahore", "islamabad",
    "bangladesh", "dhaka",
    "philippines", "manila", "cebu",
    "china", "chinese", "beijing", "shanghai", "shenzhen", "guangzhou",
    "russia", "russian", "moscow", "st. petersburg", "saint petersburg",
    "ukraine", "ukrainian", "kyiv", "kiev", "kharkiv", "lviv", "odesa",
    "belarus", "minsk",
    "nigeria", "lagos", "abuja",
    "kenya", "nairobi",
    "egypt", "cairo",
    "morocco", "casablanca", "rabat",
    "vietnam", "vietnamese", "hanoi", "ho chi minh",
    "indonesia", "jakarta", "bali",
    "thailand", "bangkok",
    "malaysia", "kuala lumpur",
    "sri lanka", "colombo",
    "nepal", "kathmandu",
    
    # US & Americas (if not in your allowlist, these block)
    "usa", "us", "united states", "america", "american", 
    "new york", "san francisco", "los angeles", "chicago", "seattle", "austin", "boston", "denver",
    "atlanta", "miami", "dallas", "houston", "phoenix", "philadelphia",
    "silicon valley", "bay area", "sf", "nyc", "la",
    "san diego", "portland", "washington dc",
    
    # UK & Ireland
    "uk", "united kingdom", "london", "england", "scotland", "wales", "britain", 
    "northern ireland", "ireland", "ireland republic", "dublin", "galway", "cork", "limerick", "belfast",
    "edinburgh", "glasgow", "manchester", "birmingham", "leeds", "liverpool", "bristol",
    
    # EU - Western
    "germany", "deutschland", "berlin", "munich", "hamburg", "cologne", "frankfurt", "stuttgart", "dusseldorf",
    "netherlands", "nederland", "amsterdam", "rotterdam", "the hague", "utrecht", "eindhoven",
    "france", "frankreich", "paris", "lyon", "marseille", "toulouse", "nice", "nantes", "strasbourg",
    "belgium", "belgie", "brussels", "antwerp", "ghent", "bruges",
    "austria", "österreich", "vienna", "graz", "linz", "salzburg", "innsbruck",
    "switzerland", "swiss", "schweiz", "zurich", "geneva", "basel", "bern", "lausanne",
    "luxembourg",
    
    # EU - Nordic
    "sweden", "sverige", "stockholm", "gothenburg", "malmo", "uppsala",
    "denmark", "danmark", "copenhagen", "aarhus", "odense",
    "norway", "norge", "oslo", "bergen", "trondheim", "stavanger",
    "finland", "suomi", "helsinki", "espoo", "tampere", "vantaa", "turku",
    "iceland", "reykjavik",
    
    # EU - Central & Eastern
    "poland", "polska", "warsaw", "krakow", "wroclaw", "poznan", "gdansk", "lodz", "katowice",
    "czech republic", "czechia", "prague", "brno", "ostrava", "plzen",
    "hungary", "budapest", "debrecen", "szeged",
    "slovakia", "bratislava", "kosice",
    "slovenia", "ljubljana", "maribor",
    "croatia", "zagreb", "split", "rijeka",
    "estonia", "eesti", "tallinn", "tartu",
    "latvia", "latvija", "riga",
    "lithuania", "lietuva", "vilnius", "kaunas",
    "romania", "românia", "bucharest", "cluj", "timisoara", "iasi", "brasov",
    "bulgaria", "sofia", "plovdiv", "varna",
    "serbia", "belgrade", "novi sad", "nis",
    "bosnia", "sarajevo", "banja luka",
    "north macedonia", "skopje",
    "albania", "tirana",
    "montenegro", "podgorica",
    "moldova", "chisinau",
    "greece", "athens", "thessaloniki", "patras",
    
    # EU - Southern
    "spain", "espana", "barcelona", "madrid", "valencia", "seville", "malaga", "bilbao",
    "portugal", "lisbon", "porto", "braga", "coimbra", "faro",
    "italy", "italia", "milan", "rome", "turin", "bologna", "florence", "naples", "genoa", "venice",
    "malta", "valletta",
    "cyprus", "nicosia", "limassol",
    
    # Other Europe
    "turkey", "türkiye", "istanbul", "ankara", "izmir", "antalya", "bursa",
    
    # APAC
    "australia", "sydney", "melbourne", "brisbane", "perth", "adelaide", "canberra",
    "new zealand", "nz", "auckland", "wellington", "christchurch", "hamilton",
    "singapore",
    "japan", "tokyo", "osaka", "yokohama", "nagoya", "sapporo", "fukuoka",
    "south korea", "korea", "seoul", "busan", "incheon",
    "taiwan", "taipei", "kaohsiung",
    "hong kong",
    
    # Americas
    "canada", "toronto", "vancouver", "montreal", "ottawa", "calgary", "edmonton", "quebec",
    "mexico", "mexico city", "guadalajara", "monterrey", "tijuana",
    "brazil", "brasil", "sao paulo", "rio de janeiro", "brasilia", "salvador", "fortaleza", "belo horizonte",
    "argentina", "buenos aires", "cordoba", "rosario",
    "chile", "santiago", "valparaiso",
    "colombia", "bogota", "medellin", "cali", "cartagena",
    "peru", "lima",
    "uruguay", "montevideo",
    "costa rica", "san jose",
    
    # Middle East / Africa
    "uae", "dubai", "abu dhabi", "sharjah", "ajman",
    "united arab emirates",
    "saudi arabia", "riyadh", "jeddah", "mecca", "medina",
    "qatar", "doha",
    "kuwait", "kuwait city",
    "bahrain", "manama",
    "oman", "muscat",
    "israel", "tel aviv", "jerusalem", "haifa",
    "jordan", "amman",
    "lebanon", "beirut",
    "south africa", "cape town", "johannesburg", "durban", "pretoria", "port elizabeth",
    "egypt", "cairo", "alexandria",
    "morocco", "casablanca", "rabat", "marrakesh", "fes", "tangier",
    "tunisia", "tunis",
    "algeria", "algiers",
    "ghana", "accra",
    "ethiopia", "addis ababa",
    "tanzania", "dar es salaam",
    "uganda", "kampala",
    "zimbabwe", "harare",
    
    # South Asia
    "afghanistan", "kabul",
    "iran", "tehran", "isfahan", "mashhad",
    "iraq", "baghdad",
    "syria", "damascus",
    "yemen", "sanaa",
    "uzbekistan", "tashkent",
    "kazakhstan", "almaty", "astana",
    "azerbaijan", "baku",
    "georgia", "tbilisi",
    "armenia", "yerevan",
    
    # Southeast Asia
    "indonesia", "jakarta", "surabaya", "bandung", "bali", "medan",
    "malaysia", "kuala lumpur", "george town", "johor bahru",
    "thailand", "bangkok", "chiang mai", "phuket",
    "vietnam", "hanoi", "ho chi minh city", "saigon", "da nang",
    "philippines", "manila", "cebu", "davao",
    "myanmar", "yangon",
    "cambodia", "phnom penh",
    "laos", "vientiane",
}

# Location signals that mean "no specific country restriction"
LOCATION_POSITIVE_SIGNALS = {
    "worldwide", "global", "anywhere", "anywhere in the world",
    "remote", "fully remote", "100% remote", "remote first", "distributed team",
    "distributed", "location independent", "digital nomad",
    "eu timezone", "europe", "eu", "european union", "emea", "emea remote",
    "apac", "asia pacific", "latam", "latin america",
    "north america", "na remote", "us timezone", "est", "pst", "cst", "mst",
    "cet", "cest", "eet", "gmt", "utc",
    "no timezone", "any timezone", "timezone flexible", "flexible timezone",
    "work from anywhere", "work from home", "wfh",
}


def _extract_countries_from_text(text: str) -> set:
    """Extract all country/city mentions from text using comprehensive dictionary."""
    if not text:
        return set()
    text_lower = text.lower()
    found = set()
    for country in ALL_COUNTRY_NAMES:
        pattern = r'(?<![a-z])' + re.escape(country) + r'(?![a-z])'
        if re.search(pattern, text_lower):
            found.add(country)
    return found


def is_allowed_location(job: dict) -> bool:
    """
    Location filter with proper blocking logic.
    
    Rules:
    1. If job has positive remote signals and NO explicit country → ALLOW
    2. If job mentions specific countries:
       - If ANY mentioned country is in ALLOWED_COUNTRY_TERMS → ALLOW
       - If ALL mentioned countries are NOT in ALLOWED_COUNTRY_TERMS → BLOCK
    3. If no country info at all → ALLOW (can't determine, don't block)
    """
    # Combine all text fields that might contain location info
    text = f"{job.get('timezone', '')} {job.get('summary', '')} {job.get('job_title', '')} {job.get('company', '')}"
    text_lower = text.lower()
    
    # Check for explicit positive remote signals
    has_positive_signal = any(signal in text_lower for signal in LOCATION_POSITIVE_SIGNALS)
    
    # Extract ALL country mentions (using comprehensive dictionary)
    detected_countries = _extract_countries_from_text(text)
    
    # If no countries detected, rely on positive signals or pass through
    if not detected_countries:
        return True  # Can't determine location, don't block
    
    # Check which detected countries are in our allowlist
    allowed_detected = {c for c in detected_countries if c in ALLOWED_COUNTRY_TERMS}
    blocked_detected = detected_countries - allowed_detected
    
    # If we found explicit countries and NONE are allowed → BLOCK
    if detected_countries and not allowed_detected:
        return False
    
    # At least one allowed country was found → ALLOW
    return True


def extract_location_tags(job):
    """Extract location tags from job text for logging/sorting."""
    text = f"{job.get('timezone','')} {job.get('summary','')} {job.get('job_title','')}".lower()
    found = []
    for term in ALLOWED_COUNTRY_TERMS:
        if term.lower() in text:
            found.append(term)
    # Deduplicate while preserving order
    seen = set()
    unique = []
    for item in found:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def is_valid_dev_job(job):
    """Return True only for non-senior software/developer roles."""
    title = (job.get("job_title") or "").strip().lower()
    tech_stack = (job.get("tech_stack") or "").strip().lower()

    if not title:
        return False
    if not DEV_TITLE_FILTER.search(title):
        return False
    if NON_DEV_FILTER.search(title):
        return False
    if SENIORITY_FILTER.search(title):
        return False
    if tech_stack and NON_DEV_FILTER.search(tech_stack):
        return False

    return True


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


# =============================================================================
# RETRY LOGIC
# =============================================================================

def fetch_with_retry(url, headers=None, timeout=30, max_retries=3):
    """Fetch URL with retry logic and random delays"""
    for attempt in range(max_retries):
        try:
            time.sleep(random.uniform(1, 3))
            response = requests.get(url, headers=headers or HEADERS, timeout=timeout)
            response.raise_for_status()
            return response
        except requests.exceptions.Timeout:
            print(f"  Timeout on attempt {attempt + 1}")
            if attempt < max_retries - 1:
                time.sleep(random.uniform(2, 5))
                continue
            raise
        except Exception as e:
            print(f"  Error on attempt {attempt + 1}: {e}")
            if attempt < max_retries - 1:
                time.sleep(random.uniform(1, 3))
                continue
            raise


# =============================================================================
# API PARSERS
# =============================================================================

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
            
        if not re.search(TECH_FILTER, combined_text):
            filtered_out["tech"] += 1
            if debug: print(f"    ❌ No tech match: {title}")
            continue
            
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
            "tech_stack": ", ".join(re.findall(TECH_FILTER, combined_text)[:5]),
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
        if not isinstance(j, dict) or not j.get("id") or not j.get("position"):
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

        results.append({
            "job_title": title,
            "company": j.get("company", ""),
            "salary": j.get("salary", ""),
            "tech_stack": ", ".join(re.findall(TECH_FILTER, combined_text)[:5]),
            "timezone": j.get("location", "Worldwide"),
            "apply_url": j.get("url", ""),
            "summary": clean_html(description)[:200] + "..." if len(clean_html(description)) > 200 else clean_html(description),
            "posted_date_iso": normalize_date(j.get("date") or j.get("epoch"), board),
            "source": board
        })
    
    return results


def parse_json_arbeitnow(board, data, debug=False):
    results = []
    
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


def _accept_job(title, description=""):
    combined_text = f"{title} {description}"
    if not is_valid_dev_job({"job_title": title, "tech_stack": combined_text}):
        return False
    return bool(
        EXP_FILTER.search(combined_text)
        or any(word in title.lower() for word in ["developer", "engineer", "programmer"])
    )


def parse_json_himalayas(board, data, debug=False):
    results = []
    jobs = data.get("jobs", []) if isinstance(data, dict) else []

    for j in jobs:
        title = j.get("title", "") or ""
        description = j.get("description", "") or ""
        tags = j.get("tags", []) or []
        tag_text = " ".join(tags) if isinstance(tags, list) else str(tags)
        if not _accept_job(title, f"{description} {tag_text}"):
            continue

        company = j.get("company", {})
        results.append({
            "job_title": title,
            "company": company.get("name", "") if isinstance(company, dict) else "",
            "salary": j.get("salary", "") or "",
            "tech_stack": ", ".join(tags[:5]) if isinstance(tags, list) else top_techs(f"{title} {description}"),
            "timezone": "Remote",
            "apply_url": j.get("url", "") or "",
            "summary": clean_html(description)[:300],
            "posted_date_iso": normalize_date(j.get("createdAt") or j.get("created_at"), board),
            "source": board
        })

    if debug:
        print(f"  Himalayas API results: {len(results)}")
    return results


def parse_json_jobicy(board, data, debug=False):
    results = []
    jobs = data.get("jobs", []) if isinstance(data, dict) else []

    for j in jobs:
        title = j.get("jobTitle", "") or j.get("title", "") or ""
        description = j.get("jobDescription", "") or j.get("jobExcerpt", "") or ""
        industries = j.get("jobIndustry", []) or []
        if isinstance(industries, str):
            industries = [industries]
        if not _accept_job(title, f"{description} {' '.join(industries)}"):
            continue

        salary_min = j.get("annualSalaryMin", "") or ""
        salary_max = j.get("annualSalaryMax", "") or ""
        salary = f"{salary_min} - {salary_max}".strip(" -")
        results.append({
            "job_title": title,
            "company": j.get("companyName", "") or "",
            "salary": salary,
            "tech_stack": ", ".join(industries[:5]) or top_techs(f"{title} {description}"),
            "timezone": j.get("jobGeo", "") or "Remote",
            "apply_url": j.get("url", "") or "",
            "summary": clean_html(description)[:300],
            "posted_date_iso": normalize_date(j.get("pubDate"), board),
            "source": board
        })

    if debug:
        print(f"  Jobicy API results: {len(results)}")
    return results


def parse_json_themuse(board, data, debug=False):
    results = []
    jobs = data.get("results", []) if isinstance(data, dict) else []

    for j in jobs:
        title = j.get("name", "") or ""
        contents = j.get("contents", "") or ""
        categories = [c.get("name", "") for c in j.get("categories", []) if isinstance(c, dict)]
        if not _accept_job(title, f"{contents} {' '.join(categories)}"):
            continue

        company = j.get("company", {})
        locations = [loc.get("name", "") for loc in j.get("locations", []) if isinstance(loc, dict)]
        results.append({
            "job_title": title,
            "company": company.get("name", "") if isinstance(company, dict) else "",
            "salary": "",
            "tech_stack": ", ".join(categories[:5]) or top_techs(f"{title} {contents}"),
            "timezone": ", ".join(locations) or "Remote",
            "apply_url": j.get("refs", {}).get("landing_page", "") if isinstance(j.get("refs"), dict) else "",
            "summary": clean_html(contents)[:300],
            "posted_date_iso": normalize_date(j.get("publication_date"), board),
            "source": board
        })

    if debug:
        print(f"  The Muse API results: {len(results)}")
    return results


def parse_json_adzuna(board, data, debug=False):
    results = []
    jobs = data.get("results", []) if isinstance(data, dict) else []

    for j in jobs:
        title = j.get("title", "") or ""
        description = j.get("description", "") or ""
        if not _accept_job(title, description):
            continue

        salary_min = j.get("salary_min", "") or ""
        salary_max = j.get("salary_max", "") or ""
        salary = f"{salary_min} - {salary_max}".strip(" -")
        company = j.get("company", {})
        results.append({
            "job_title": title,
            "company": company.get("display_name", "") if isinstance(company, dict) else "",
            "salary": salary,
            "tech_stack": top_techs(f"{title} {description}"),
            "timezone": j.get("location", {}).get("display_name", "Remote") if isinstance(j.get("location"), dict) else "Remote",
            "apply_url": j.get("redirect_url", "") or "",
            "summary": clean_html(description)[:300],
            "posted_date_iso": normalize_date(j.get("created"), board),
            "source": board
        })

    if debug:
        print(f"  Adzuna API results: {len(results)}")
    return results


# =============================================================================
# HTML PARSERS
# =============================================================================

def parse_html_ycombinator(html, base_url=None, board_name="YCombinator"):
    """Parse YC Work at a Startup job board."""
    soup = BeautifulSoup(html, "html.parser")
    results = []
    
    # YC uses a modern React-rendered layout — try multiple selectors
    selectors = [
        'div[class*="JobCard"]',
        'div[class*="job-card"]',
        'div[class*="JobListing"]',
        'div[class*="job-listing"]',
        '[class*="Job"]',  # fallback
    ]
    
    job_elements = []
    for selector in selectors:
        job_elements = soup.select(selector)
        if job_elements:
            print(f"  Found {len(job_elements)} YC elements with selector: {selector}")
            break
    
    # If React hydration fails, try JSON embedded in script tags
    if not job_elements:
        scripts = soup.find_all("script", type="application/json")
        for script in scripts:
            try:
                data = json.loads(script.string)
                # YC embeds jobs in nested JSON under __APOLLO_STATE__ or similar
                jobs_data = _extract_yc_jobs_from_json(data)
                if jobs_data:
                    return jobs_data
            except (json.JSONDecodeError, AttributeError):
                continue
    
    for element in job_elements[:50]:
        try:
            title_selectors = ['h3', 'h2', 'a[class*="title"]', '[class*="title"]', 'a[href*="/jobs/"]']
            title = ""
            link = ""
            
            for ts in title_selectors:
                title_elem = element.select_one(ts)
                if title_elem:
                    title = clean_text(title_elem)
                    if title_elem.name == 'a' and title_elem.get('href'):
                        link = title_elem['href']
                    break
            
            if not title or len(title) < 3:
                continue
                
            if EXCLUDE_FILTER.search(title):
                continue
                
            if not re.search(TECH_FILTER, title):
                continue
                
            if not (EXP_FILTER.search(title) or 
                    any(word in title.lower() for word in ['developer', 'engineer', 'programmer'])):
                continue
            
            # Company name
            company = "Unknown"
            company_elem = element.select_one('[class*="company"], [class*="startup"]')
            if company_elem:
                company = clean_text(company_elem)
            
            # Location / remote tag
            location = "Remote"
            loc_elem = element.select_one('[class*="location"], [class*="remote"]')
            if loc_elem:
                location = clean_text(loc_elem)
            
            # Fix relative links
            if link and not link.startswith('http'):
                link = "https://www.workatastartup.com" + link
            
            results.append({
                "job_title": title,
                "company": company,
                "salary": "",
                "tech_stack": ", ".join(re.findall(TECH_FILTER, title)[:5]),
                "timezone": location,
                "apply_url": link or "",
                "summary": f"YC-backed startup via Work at a Startup",
                "posted_date_iso": normalize_date(None),
                "source": board_name
            })
            
        except Exception as e:
            continue
    
    print(f"  ✅ YCombinator: Extracted {len(results)} jobs")
    return results


def _extract_yc_jobs_from_json(data):
    """Fallback: extract jobs from YC's embedded JSON state."""
    results = []
    try:
        # Traverse nested dicts looking for job objects
        def traverse(obj):
            if isinstance(obj, dict):
                if obj.get("title") and obj.get("companyName"):
                    title = obj.get("title", "")
                    if not EXCLUDE_FILTER.search(title) and re.search(TECH_FILTER, title):
                        results.append({
                            "job_title": title,
                            "company": obj.get("companyName", "Unknown"),
                            "salary": obj.get("salary", "") or "",
                            "tech_stack": ", ".join(re.findall(TECH_FILTER, title)[:5]),
                            "timezone": obj.get("location", "Remote") or "Remote",
                            "apply_url": "https://www.workatastartup.com" + obj.get("slug", ""),
                            "summary": obj.get("description", "YC startup")[:200],
                            "posted_date_iso": normalize_date(obj.get("createdAt")),
                            "source": "YCombinator"
                        })
                for v in obj.values():
                    traverse(v)
            elif isinstance(obj, list):
                for item in obj:
                    traverse(item)
        
        traverse(data)
    except Exception:
        pass
    
    return results

def parse_html_weworkremotely(html):
    soup = BeautifulSoup(html, "html.parser")
    results = []
    
    job_elements = soup.select('section.jobs li')
    print(f"  Found {len(job_elements)} potential job elements with selector: section.jobs li")
    
    for element in job_elements:
        if not element.select_one('span.company'):
            continue
            
        try:
            title_elem = element.select_one('span.title')
            title = clean_text(title_elem)

            company_elem = element.select_one('span.company')
            company = clean_text(company_elem)

            link_elem = element.select_one('a[href^="/remote-jobs/"]')
            if not link_elem:
                continue

            link = "https://weworkremotely.com" + link_elem['href']
            
            if EXCLUDE_FILTER.search(title):
                print(f"    - Filtering out (Senior/Lead): '{title}'")
                continue
            
            if not re.search(TECH_FILTER, title):
                print(f"    - Filtering out (No Tech Match): '{title}'")
                continue
            
            print(f"    + Found Job: '{title}' at {company}")
            results.append({
                "job_title": title,
                "company": company,
                "salary": clean_text(element.select_one('span.salary')),
                "tech_stack": ", ".join(re.findall(TECH_FILTER, title)[:5]),
                "timezone": clean_text(element.select_one('span.region')),
                "apply_url": link,
                "summary": f"Full-Time listing from WeWorkRemotely.",
                "posted_date_iso": datetime.date.today().isoformat(),
                "source": "WeWorkRemotely"
            })
            
        except Exception as e:
            print(f"    - Error parsing one element: {e}")
            continue
    
    return results


def parse_html_wellfound(html):
    soup = BeautifulSoup(html, "html.parser")
    results = []
    
    job_containers = soup.select('div[class*="styles_component__dBicB"]')
    print(f"  Found {len(job_containers)} job containers")
    
    for container in job_containers:
        try:
            title_elem = container.select_one('span[class*="styles_title__xpQDw"]')
            if not title_elem:
                continue
                
            title = clean_text(title_elem)
            if not title:
                continue
            
            if EXCLUDE_FILTER.search(title):
                continue
                
            if not re.search(TECH_FILTER, title):
                continue
                
            if not (EXP_FILTER.search(title) or 
                    any(word in title.lower() for word in ['developer', 'engineer', 'programmer'])):
                continue
            
            link_elem = container.select_one('a[href*="/jobs/"]')
            link = ""
            if link_elem:
                link = link_elem.get('href', '')
                if link and not link.startswith('http'):
                    link = 'https://wellfound.com' + link
            
            location_elem = container.select_one('span[class*="styles_location__"]')
            location = clean_text(location_elem) if location_elem else "Remote"
            
            compensation_elem = container.select_one('span[class*="styles_compensation__"]')
            salary = clean_text(compensation_elem) if compensation_elem else ""
            
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
    soup = BeautifulSoup(html, "html.parser")
    results = []
    
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
            
            if EXCLUDE_FILTER.search(title):
                continue
                
            if not re.search(TECH_FILTER, title):
                continue
                
            if not (EXP_FILTER.search(title) or 
                    any(word in title.lower() for word in ['developer', 'engineer', 'programmer'])):
                continue
            
            company_selectors = ['.company', '.employer', '.company-name']
            company = ""
            for cs in company_selectors:
                company_elem = element.select_one(cs)
                if company_elem:
                    company = clean_text(company_elem)
                    break
            
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
    soup = BeautifulSoup(html, "html.parser")
    results = []
    
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
            
            if EXCLUDE_FILTER.search(title):
                continue
                
            if not re.search(TECH_FILTER, title):
                continue
                
            if not (EXP_FILTER.search(title) or 
                    any(word in title.lower() for word in ['developer', 'engineer', 'programmer'])):
                continue
            
            company_selectors = ['.company', '.employer', '.company-name']
            company = ""
            for cs in company_selectors:
                company_elem = element.select_one(cs)
                if company_elem:
                    company = clean_text(company_elem)
                    break
            
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
                "source": "Himalayas"
            })
            
        except Exception as e:
            continue
    
    return results


def parse_html_generic(html, board_name, base_url):
    """Generic HTML parser for most job sites"""
    soup = BeautifulSoup(html, "html.parser")
    results = []
    
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
    
    for element in job_elements[:50]:
        try:
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
            
            if EXCLUDE_FILTER.search(title):
                continue
                
            if not re.search(TECH_FILTER, title):
                continue
                
            if not (EXP_FILTER.search(title) or 
                    any(word in title.lower() for word in ['developer', 'engineer', 'programmer'])):
                continue
            
            company_selectors = ['.company', '.employer', '.company-name', 'h3', 'h4']
            company = ""
            for cs in company_selectors:
                company_elem = element.select_one(cs)
                if company_elem and clean_text(company_elem) != title:
                    company = clean_text(company_elem)
                    break
            
            if not link:
                link_elem = element.select_one('a[href]')
                if link_elem:
                    link = link_elem['href']
            
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
    results = []
    if not isinstance(data, list):
        print(f"  Unexpected data format for {board}, expected a list.")
        return results

    for j in data:
        title = j.get("position", "") or ""
        description = j.get("description", "") or ""
        tags = j.get("tags") or []
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        combined_text = f"{title} {description} {' '.join(tags)}"

        if EXCLUDE_FILTER.search(title):
            if debug: print(f"    - Filtering out (Senior/Lead): '{title}'")
            continue
        if not re.search(TECH_FILTER, combined_text):
            if debug: print(f"    - Filtering out (No Tech Match): '{title}'")
            continue

        results.append({
            "job_title": title,
            "company": j.get("company_name", "") or "",
            "salary": "",
            "tech_stack": ", ".join(tags[:5]) or top_techs(combined_text),
            "timezone": "Remote",
            "apply_url": j.get("url", "") or "",
            "summary": clean_html(description)[:200] + "..." if len(clean_html(description)) > 200 else clean_html(description),
            "posted_date_iso": normalize_date(j.get("pub_date"), board),
            "source": board
        })
    return results


# =============================================================================
# JUSTREMOTE PRELOADED STATE PARSER
# =============================================================================

def _extract_preloaded_state(html: str):
    """Brace-counting JSON extraction (regex breaks on nested '};' in text fields)."""
    marker = "window.__PRELOADED_STATE__"
    start_idx = html.find(marker)
    if start_idx == -1:
        return None

    eq_idx = html.find("=", start_idx)
    brace_start = html.find("{", eq_idx)
    if brace_start == -1:
        return None

    depth = 0
    in_string = False
    escape = False
    i = brace_start

    while i < len(html):
        ch = html[i]
        if escape:
            escape = False
        elif ch == "\\" and in_string:
            escape = True
        elif ch == '"' and not escape:
            in_string = not in_string
        elif not in_string:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    json_str = html[brace_start:i + 1]
                    try:
                        return json.loads(json_str)
                    except json.JSONDecodeError:
                        return None
        i += 1
    return None


def _parse_relative_date(date_str: str) -> str:
    """Convert JustRemote's '21 Jun' style date to ISO format (assumes current year)."""
    try:
        parsed = datetime.datetime.strptime(f"{date_str} {datetime.date.today().year}", "%d %b %Y")
        return parsed.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return datetime.date.today().isoformat()


def parse_html_justremote(html, base_url, board):
    state = _extract_preloaded_state(html)
    if not state:
        print(f"  ⚠️ {board}: __PRELOADED_STATE__ not found — site structure may have changed")
        return []

    jobs_list = state.get("jobsState", {}).get("entity", {}).get("all", [])
    if not jobs_list:
        print(f"  ⚠️ {board}: No jobs found in preloaded state")
        return []

    DEV_CATEGORIES = {"developer", "devopsandsysadmin"}

    results = []
    for j in jobs_list:
        if not j.get("is_active", True):
            continue

        category = (j.get("category") or "").lower()
        title = j.get("title", "") or ""

        if category not in DEV_CATEGORIES:
            continue

        href = j.get("href", "") or ""
        link = f"{base_url}/{href}" if href and not href.startswith("http") else href

        location_restrictions = j.get("location_restrictions") or []
        timezone = ", ".join(location_restrictions) if location_restrictions else "Remote"

        print(f"    + Found Job: '{title}' at {j.get('company_name', '')}")
        results.append({
            "job_title": title,
            "company": j.get("company_name", "") or "",
            "salary": "",
            "tech_stack": category,
            "timezone": timezone,
            "apply_url": link,
            "summary": f"{j.get('job_type', 'Remote')} position via JustRemote",
            "posted_date_iso": _parse_relative_date(j.get("date", "")),
            "source": board,
        })

    print(f"  ✅ {board}: Extracted {len(results)} developer jobs from preloaded state ({len(jobs_list)} total listed)")
    return results


# =============================================================================
# MAIN FETCH LOGIC
# =============================================================================

def fetch_jobs_from_board(name, info, debug=False):
    url = info['url']
    typ = info['type']
    
    try:
        if typ == "api":
            print(f"Fetching (API): {name}")
            if name == "Adzuna":
                app_id = os.getenv("ADZUNA_APP_ID")
                app_key = os.getenv("ADZUNA_APP_KEY")
                if not app_id or not app_key:
                    print("  Missing ADZUNA_APP_ID or ADZUNA_APP_KEY, skipping Adzuna")
                    return []
                url = (
                    f"{url}?app_id={app_id}&app_key={app_key}"
                    "&what=developer+remote&results_per_page=50&content-type=application/json"
                )
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
            elif name == "Himalayas":
                return parse_json_himalayas(name, data, debug)
            elif name == "Jobicy":
                return parse_json_jobicy(name, data, debug)
            elif name == "TheMuse":
                return parse_json_themuse(name, data, debug)
            elif name == "Adzuna":
                return parse_json_adzuna(name, data, debug)
            else:
                print(f"  No specific parser for {name}, skipping")
                return []
                
        elif typ == "html":
            print(f"Fetching (HTML): {name}")
            if name == "AuthenticJobs":
                rss = fetch_authentic_jobs_rss()
                if rss:
                    return rss
            response = fetch_with_retry(url, timeout=40)
            html = response.text
            print(f"  HTML length: {len(html)}")
            
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
                return parse_html_generic(html, name, base_url)
            elif name == "JustRemote":
               return parse_html_justremote(html, base_url, name)
            elif name == "YCombinator":
                return parse_html_ycombinator(html, base_url, name)
            else:
                return parse_html_generic(html, name, base_url)
        else:
            print(f"  Unknown type for {name}")
            return []
            
    except Exception as e:
        print(f"  {name} scrape error: {e}")
        import traceback
        traceback.print_exc()
        return []


def _run_optional_scraper(label, scrape_func, jobs, working_scrapers, failed_scrapers, debug=False):
    print(f"\n--- Processing {label} ---")
    try:
        scraped = scrape_func(debug=debug)
        if scraped:
            print(f"✅ Parsed {len(scraped)} jobs from {label}")
            jobs.extend(scraped)
            working_scrapers.append(label)
        else:
            print(f"⚠️  No jobs found from {label}")
            failed_scrapers.append(label)
    except Exception as e:
        print(f"❌ {label} completely failed: {e}")
        import traceback
        traceback.print_exc()
        failed_scrapers.append(label)


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
            import traceback
            traceback.print_exc()
            failed_scrapers.append(name)
        
        time.sleep(random.uniform(2, 4))

    try:
        from tools.jobspy_scraper import scrape_with_jobspy
        _run_optional_scraper("JobSpy", scrape_with_jobspy, jobs, working_scrapers, failed_scrapers, debug)
    except Exception as e:
        print(f"❌ JobSpy setup failed: {e}")
        failed_scrapers.append("JobSpy")

    try:
        from tools.playwright_scraper import scrape_stealth_boards
        _run_optional_scraper("PlaywrightStealth", scrape_stealth_boards, jobs, working_scrapers, failed_scrapers, debug)
    except Exception as e:
        print(f"❌ Playwright stealth setup failed: {e}")
        failed_scrapers.append("PlaywrightStealth")

    try:
        from tools.crawl4ai_scraper import scrape_justremote_with_crawl4ai
        _run_optional_scraper("Crawl4AI-JustRemote", scrape_justremote_with_crawl4ai, jobs, working_scrapers, failed_scrapers, debug)
    except Exception as e:
        print(f"❌ Crawl4AI setup failed: {e}")
        failed_scrapers.append("Crawl4AI-JustRemote")

    total_before_filter = len(jobs)
    jobs = [job for job in jobs if is_valid_dev_job(job)]
    
    # === COUNTRY FILTER ===
    country_before = len(jobs)
    jobs = [job for job in jobs if is_allowed_location(job)]
    country_blocked = country_before - len(jobs)
    print(f"🌍 Country filter: blocked {country_blocked} jobs | remaining: {len(jobs)}")
    
    # Add location tags for all jobs
    for job in jobs:
        job["location_tags"] = extract_location_tags(job)

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
    jobs = scrape_all(debug=False)
    jobs.sort(key=lambda x: x['posted_date_iso'], reverse=True)
    
    if jobs:
        print(f"\n=== SAMPLE RESULTS ===")
        for i, job in enumerate(jobs[:3]):
            print(f"\nJob {i+1}:")
            print(f"Title: {job['job_title']}")
            print(f"Company: {job['company']}")
            print(f"Tech: {job['tech_stack']}")
            print(f"Location Tags: {job.get('location_tags', [])}")
            print(f"URL: {job['apply_url']}")
        print(f"Total jobs found: {len(jobs)}")