"""Per-tab Google Sheet cache with TTL + curator enrichment left-join.

Sheet reading
  tools.sheet_writer.get_all_rows() only reads the ALL JOBS tab today
  (tools/sheet_writer.py:504-524, returns list[list]), so this module builds
  its own per-tab reader for ALL JOBS / TOP MATCHES / GOOD MATCHES / APPLIED /
  STATS using the get_or_create_worksheet pattern
  (tools/sheet_writer.py:165-175, 191-206) plus header->dict mapping
  (dict(zip(header, padded_row))). All sheet access is lazy (inside functions)
  so importing this module never touches the network.

Enrichment
  Left-join on job_fingerprint from curated_jobs.json, following the
  main._load_curated_jobs pattern (main.py:512-529): payload dict with a
  "jobs" list (or a bare list); missing file / bad JSON -> empty map.
  Absent enrichment -> null fields, never crash.

TTL
  Measured cost: one get_all_values round-trip per tab is ~1-3s over gspread
  (5 tabs => up to ~10-15s cold), plus Sheets quota limits, so per-tab TTL
  defaults to 90s within the 60-120s window (override via API_CACHE_TTL,
  clamped to 60-120s). POST /api/jobs/refresh clears the cache on demand.
"""

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CURATED_JOBS_PATH = PROJECT_ROOT / "curated_jobs.json"

# --- TTL (60-120s window, default 90s; see module docstring) ------------------
_TTL_MIN = 60
_TTL_MAX = 120
_TTL_DEFAULT = 90


def _resolve_ttl() -> int:
    try:
        ttl = int(os.getenv("API_CACHE_TTL", str(_TTL_DEFAULT)).strip())
    except (TypeError, ValueError):
        return _TTL_DEFAULT
    return max(_TTL_MIN, min(_TTL_MAX, ttl))


CACHE_TTL_SECONDS = _resolve_ttl()

# --- Tabs --------------------------------------------------------------------
JOB_TABS = ("ALL JOBS", "TOP MATCHES", "GOOD MATCHES")
TRACKER_TAB = "APPLIED"
STATS_TAB = "STATS"
ALL_TABS = JOB_TABS + (TRACKER_TAB, STATS_TAB)

# Curator enrichment fields merged onto each job row (agents/curator.py).
ENRICHMENT_FIELDS = (
    "ranking_score",
    "keyword_score",
    "semantic_score",
    "freshness_boost",
    "semantic_computed",
    "selected_cv_path",
    "selected_cv",
    "location_tags",
    "location",
    "job_type",
)

# --- Caches ------------------------------------------------------------------
_lock = threading.Lock()
_tab_cache: Dict[str, Dict[str, Any]] = {}  # tab -> {"at": float, "rows": list[dict]}
_enrichment_cache: Dict[str, Any] = {"at": 0.0, "map": {}}


def _is_fresh(at: float) -> bool:
    # Resolve TTL per call so API_CACHE_TTL changes take effect without reimport.
    return (time.monotonic() - at) < _resolve_ttl()


# --- Sheet reading ------------------------------------------------------------

def _read_tab_values(tab: str) -> List[List[str]]:
    """Fetch raw values for one tab; [] on any error (never crash)."""
    try:
        from tools.sheet_writer import get_or_create_worksheet, get_sheet
    except Exception:
        return []
    try:
        spreadsheet = get_sheet()
        worksheet = get_or_create_worksheet(spreadsheet, tab)
        values = worksheet.get_all_values()
        return values if isinstance(values, list) else []
    except Exception:
        return []


def _rows_to_dicts(values: List[List[str]]) -> List[Dict[str, Any]]:
    """Map header row -> dict per row; pad short rows; skip fully-empty rows."""
    if not values:
        return []
    header = [(h or "").strip() for h in values[0]]
    if not any(header):
        return []
    rows: List[Dict[str, Any]] = []
    width = len(header)
    for raw in values[1:]:
        if not raw or not any((c or "").strip() for c in raw):
            continue
        padded = list(raw) + [""] * (width - len(raw))
        rows.append({header[i]: padded[i] for i in range(width)})
    return rows


def _normalize_sources(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Canonicalize the `source` column on rows read from the Sheet.

    The write path normalizes new rows (tools.sheet_writer), but rows already
    in the Sheet were written under board keys that alias the same provider
    (RemoteOKAPI/RemoteOK, Remojobs-*/Remotive). Normalizing on read too is
    what actually merges `by_source` counts, the sources grid, and the Job Desk
    source dropdown for historical data — a write-only fix stays split until
    the sheet is rebuilt. Unknown sources pass through untouched.
    """
    try:
        from tools.sources import canonical_source
    except Exception:
        return rows
    for row in rows:
        if "source" in row:
            row["source"] = canonical_source(row.get("source"))
    return rows


def get_tab_rows(tab: str, force: bool = False) -> List[Dict[str, Any]]:
    """Return cached header->dict rows for a tab (TTL-guarded).

    Returns shallow copies so callers mutating a dict can't pollute the cache.
    Falls back to the local scrape snapshot for ALL JOBS only when Sheets is
    unwired (sheets_configured() False) so offline UI shows real project
    data instead of nothing. When Sheets is configured, an empty read stays
    empty — never mask live-source trouble with days-old snapshot rows.
    TOP/GOOD MATCHES never fall back — without sheet scores there is
    nothing honest to put there.
    """
    if tab not in ALL_TABS:
        raise ValueError(f"Unknown tab '{tab}'. Choose from: {', '.join(ALL_TABS)}")
    with _lock:
        cached = _tab_cache.get(tab)
        if cached is not None and not force and _is_fresh(cached["at"]):
            return [dict(r) for r in cached["rows"]]
    rows = _rows_to_dicts(_read_tab_values(tab))
    if not rows and tab == "ALL JOBS" and not sheets_configured():
        # Offline-only fallback: Sheets unwired -> serve the local scrape
        # snapshot so the UI shows real project data. When Sheets IS the
        # configured source of truth, an empty read must stay empty —
        # otherwise a transient quota/network blip serves days-old
        # snapshot rows (stale Studio dropdown) for the full TTL window
        # while /api/health still reports data_source=sheets.
        rows = _local_snapshot_rows()
    rows = _normalize_sources(rows)
    now = time.monotonic()
    with _lock:
        _tab_cache[tab] = {"at": now, "rows": rows}
    return [dict(r) for r in rows]


# --- Local snapshot fallback -------------------------------------------------

# Checked in order; first file with a non-empty job list wins.
SNAPSHOT_FILES = ("scraped_jobs.json", "fresh_scrape.json")


def _snapshot_paths() -> List[Path]:
    """Snapshot files to try, honouring the SNAPSHOT_FILE override.

    The override exists so a harness (or an operator pointing at an archived
    scrape) can seed the API without writing into the project root.
    """
    override = (os.getenv("SNAPSHOT_FILE") or "").strip()
    if override:
        return [Path(override)]
    return [PROJECT_ROOT / name for name in SNAPSHOT_FILES]


def _local_snapshot_rows() -> List[Dict[str, Any]]:
    """Load real scraped jobs from a local snapshot file (no network).

    Returns sheet-shaped dicts for the ALL JOBS tab. Fingerprints reuse the
    pipeline MD5 scheme (tools/deduplicator.py:job_fingerprint) so the
    curated_jobs.json enrichment join and /api/jobs/{fp} keep working.
    Unscored fields stay "" (never invented). Missing/invalid files -> [].
    """
    for path in _snapshot_paths():
        try:
            if not path.exists():
                continue
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            jobs = payload.get("jobs", []) if isinstance(payload, dict) else payload
            if not isinstance(jobs, list) or not jobs:
                continue
            from tools.deduplicator import job_fingerprint

            rows: List[Dict[str, Any]] = []
            for job in jobs:
                if not isinstance(job, dict):
                    continue
                stack = job.get("tech_stack", "")
                if isinstance(stack, list):
                    stack = ", ".join(str(t) for t in stack)
                row = {
                    "job_title": job.get("job_title", ""),
                    "company": job.get("company", ""),
                    "salary": job.get("salary", ""),
                    "tech_stack": stack,
                    "timezone": job.get("timezone", ""),
                    "apply_url": job.get("apply_url", ""),
                    "summary": job.get("summary", ""),
                    "posted_date_iso": job.get("posted_date_iso", ""),
                    "source": job.get("source", ""),
                    "match_score": "",
                    "match_reason": "",
                    "scraped_at": "",
                    "status": "NEW",
                    "job_fingerprint": (job.get("job_fingerprint") or "").strip()
                    or job_fingerprint(job),
                }
                if not (row["job_title"] or row["apply_url"]):
                    continue
                rows.append(row)
            if rows:
                return rows
        except Exception:
            continue
    return []


def snapshot_available() -> bool:
    """True when a non-empty local snapshot file exists (offline fallback)."""
    for path in _snapshot_paths():
        try:
            if not path.exists():
                continue
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            jobs = payload.get("jobs", []) if isinstance(payload, dict) else payload
            if isinstance(jobs, list) and any(isinstance(j, dict) for j in jobs):
                return True
        except Exception:
            continue
    return False


def data_source() -> str:
    """Where ALL JOBS data would come from right now (no network calls).

    "sheets"   — service account + sheet ID wired (live source of truth).
    "snapshot" — Sheets unwired, but a local scrape snapshot exists.
    "empty"    — neither; API returns [] and UI shows mock fallback.
    """
    if sheets_configured():
        return "sheets"
    if snapshot_available():
        return "snapshot"
    return "empty"


def refresh(tab: Optional[str] = None) -> List[str]:
    """Invalidate cached tab(s) (+ enrichment map). Returns cleared tab names."""
    with _lock:
        if tab is None:
            cleared = sorted(_tab_cache.keys())
            _tab_cache.clear()
            _enrichment_cache["at"] = 0.0
            _enrichment_cache["map"] = {}
            return cleared
        if tab not in ALL_TABS:
            raise ValueError(f"Unknown tab '{tab}'. Choose from: {', '.join(ALL_TABS)}")
        _tab_cache.pop(tab, None)
        _enrichment_cache["at"] = 0.0
        _enrichment_cache["map"] = {}
        return [tab]


# --- Enrichment ---------------------------------------------------------------

def _load_enrichment_map(force: bool = False) -> Dict[str, Dict[str, Any]]:
    """Build {job_fingerprint: enrichment} from curated_jobs.json.

    Mirrors main._load_curated_jobs (main.py:512-529). Missing file or bad
    JSON -> {} (never crash).
    """
    with _lock:
        if not force and _is_fresh(_enrichment_cache["at"]):
            return dict(_enrichment_cache["map"])
    enriched: Dict[str, Dict[str, Any]] = {}
    try:
        if CURATED_JOBS_PATH.exists():
            with open(CURATED_JOBS_PATH, "r", encoding="utf-8") as f:
                payload = json.load(f)
            jobs = payload.get("jobs", []) if isinstance(payload, dict) else payload
            if isinstance(jobs, list):
                for job in jobs:
                    if not isinstance(job, dict):
                        continue
                    fp = (job.get("job_fingerprint") or "").strip()
                    if not fp:
                        continue
                    enriched[fp] = {
                        field: job.get(field) for field in ENRICHMENT_FIELDS if field in job
                    }
    except Exception:
        enriched = {}
    now = time.monotonic()
    with _lock:
        _enrichment_cache["at"] = now
        _enrichment_cache["map"] = enriched
    return enriched


def curated_count() -> int:
    """Number of curated jobs currently loadable (presence check helper)."""
    try:
        return len(_load_enrichment_map())
    except Exception:
        return 0


def _enrich_row(row: Dict[str, Any], enrichment: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Left-join one base row with its enrichment; absent -> null, never crash."""
    merged = dict(row)
    try:
        fp = (row.get("job_fingerprint") or "").strip()
        extra = enrichment.get(fp, {}) if fp else {}
        for field in ENRICHMENT_FIELDS:
            value = extra.get(field, None)
            if isinstance(value, str) and value.strip() == "":
                value = None
            merged[field] = value
        tags = merged.get("location_tags")
        if tags is not None and not isinstance(tags, list):
            merged["location_tags"] = [str(tags)] if str(tags).strip() else None
    except Exception:
        for field in ENRICHMENT_FIELDS:
            merged.setdefault(field, None)
    return merged


# --- Public read API ----------------------------------------------------------

def get_jobs(tab: str = "ALL JOBS", force: bool = False) -> List[Dict[str, Any]]:
    """Enriched job dicts for one job tab (tab stamped on each row)."""
    if tab not in JOB_TABS:
        raise ValueError(f"Unknown jobs tab '{tab}'. Choose from: {', '.join(JOB_TABS)}")
    enrichment = _load_enrichment_map(force=force)
    jobs = []
    for row in get_tab_rows(tab, force=force):
        merged = _enrich_row(row, enrichment)
        merged["tab"] = tab
        jobs.append(merged)
    return jobs


def get_job(job_fingerprint: str) -> Optional[Dict[str, Any]]:
    """Find one enriched job by fingerprint (searches ALL JOBS first)."""
    fp = (job_fingerprint or "").strip()
    if not fp:
        return None
    enrichment = _load_enrichment_map()
    for tab in JOB_TABS:
        for row in get_tab_rows(tab):
            if (row.get("job_fingerprint") or "").strip() == fp:
                merged = _enrich_row(row, enrichment)
                merged["tab"] = tab
                return merged
    return None


def get_stats_snapshot() -> Dict[str, Any]:
    """Aggregate counts from job tabs + raw STATS-tab rows. Never crashes."""
    try:
        tabs: Dict[str, int] = {}
        by_source: Dict[str, int] = {}
        total = 0
        for tab in JOB_TABS:
            rows = get_tab_rows(tab)
            tabs[tab] = len(rows)
            if tab == "ALL JOBS":
                total = len(rows)
                for row in rows:
                    source = (row.get("source") or "").strip() or "unknown"
                    by_source[source] = by_source.get(source, 0) + 1
        stats_rows = get_tab_rows(STATS_TAB)
        return {
            "total_jobs": total,
            "tabs": tabs,
            "by_source": by_source,
            "stats_rows": stats_rows,
            "curated_jobs": curated_count(),
        }
    except Exception:
        return {
            "total_jobs": 0,
            "tabs": {},
            "by_source": {},
            "stats_rows": [],
            "curated_jobs": 0,
        }


# --- Skill aggregation (GET /api/skills) -------------------------------------
# tech_stack is a free-text sheet column written by several producers
# (agents/scrapper.py TECH_FILTER joins, Gemini enrichment, manual rows), so the
# same skill arrives as "Node.js" / "nodejs" / "NODE". Aggregation therefore
# canonicalizes before counting, otherwise the cloud shows three Node entries.

# Separators actually observed in the column. "/" is deliberately NOT a
# separator: it would split CI/CD and TCP/IP into nonsense tokens.
_SKILL_SPLIT = re.compile(r"[,;|\n\r\t•·]+")
# Trim surrounding punctuation/quotes/brackets but keep inner . + # (Node.js,
# C++, C#) and inner - (Objective-C).
_SKILL_STRIP = " \t\"'`()[]{}<>*:•·-–—."
# Conservative pass: wrappers only, never meaningful leading/trailing
# punctuation. ".NET" and "C++" must come through this one intact.
_SKILL_QUOTES = " \t\"'`()[]{}<>"

# lowercase lookup key -> canonical display form.
_SKILL_ALIASES: Dict[str, str] = {
    "js": "JavaScript", "javascript": "JavaScript", "ecmascript": "JavaScript",
    "ts": "TypeScript", "typescript": "TypeScript",
    "node": "Node.js", "nodejs": "Node.js", "node js": "Node.js", "node.js": "Node.js",
    "react": "React", "reactjs": "React", "react.js": "React", "react js": "React",
    "next": "Next.js", "nextjs": "Next.js", "next.js": "Next.js",
    "nuxt": "Nuxt", "nuxtjs": "Nuxt", "nuxt.js": "Nuxt",
    "vue": "Vue", "vuejs": "Vue", "vue.js": "Vue",
    "angular": "Angular", "angularjs": "Angular",
    "svelte": "Svelte", "sveltekit": "SvelteKit",
    "py": "Python", "python": "Python", "python3": "Python",
    "golang": "Go", "go": "Go",
    "postgres": "PostgreSQL", "postgresql": "PostgreSQL", "psql": "PostgreSQL",
    "mysql": "MySQL", "mongodb": "MongoDB", "mongo": "MongoDB",
    "redis": "Redis", "elasticsearch": "Elasticsearch", "elastic": "Elasticsearch",
    "k8s": "Kubernetes", "kubernetes": "Kubernetes",
    "docker": "Docker", "terraform": "Terraform", "ansible": "Ansible",
    "aws": "AWS", "amazon web services": "AWS",
    "gcp": "GCP", "google cloud": "GCP", "azure": "Azure",
    "sql": "SQL", "nosql": "NoSQL", "graphql": "GraphQL", "rest": "REST",
    "restful": "REST", "rest api": "REST", "grpc": "gRPC",
    "html": "HTML", "html5": "HTML", "css": "CSS", "css3": "CSS",
    "sass": "Sass", "scss": "Sass", "tailwind": "Tailwind", "tailwindcss": "Tailwind",
    "django": "Django", "flask": "Flask", "fastapi": "FastAPI",
    "rails": "Rails", "ruby on rails": "Rails", "ruby": "Ruby",
    "spring": "Spring", "spring boot": "Spring Boot",
    "dotnet": ".NET", ".net": ".NET", "net": ".NET", "dot net": ".NET",
    "asp.net": "ASP.NET", "aspnet": "ASP.NET", "c#": "C#", "csharp": "C#",
    "c++": "C++", "cpp": "C++", "c": "C",
    "java": "Java", "kotlin": "Kotlin", "swift": "Swift", "scala": "Scala",
    "php": "PHP", "laravel": "Laravel", "rust": "Rust", "elixir": "Elixir",
    "react native": "React Native", "flutter": "Flutter",
    "ios": "iOS", "android": "Android",
    "ci/cd": "CI/CD", "cicd": "CI/CD", "ci cd": "CI/CD",
    "devops": "DevOps", "linux": "Linux", "git": "Git", "github": "GitHub",
    "gitlab": "GitLab", "jenkins": "Jenkins", "kafka": "Kafka",
    "rabbitmq": "RabbitMQ", "airflow": "Airflow", "spark": "Spark",
    "pandas": "Pandas", "numpy": "NumPy", "pytorch": "PyTorch",
    "tensorflow": "TensorFlow", "ml": "Machine Learning",
    "machine learning": "Machine Learning", "ai": "AI",
    "llm": "LLM", "llms": "LLM", "nlp": "NLP",
    "api": "API", "apis": "API", "microservices": "Microservices",
    "microservice": "Microservices", "graphite": "Graphite",
    "playwright": "Playwright", "selenium": "Selenium", "cypress": "Cypress",
    "jest": "Jest", "pytest": "pytest",
}

# Tokens that are noise rather than skills.
#
# The second block matters more than it looks. `agents/scrapper.py` builds
# tech_stack with TECH_FILTER, whose alternation deliberately includes ROLE
# words — developer, engineer, software, web, backend, back-end, frontend,
# front-end, full-stack — because the same regex is reused to decide whether a
# posting is a dev job at all. Those words therefore land in the column on
# nearly every row. Verified 2026-10-03 against live Remotive/WeWorkRemotely
# copy: a real cell reads "back-end, Engineer, Developer, developer, Back-end".
# Left in, the "High-Yield Skill Demand" cloud ranks Web/Software/Backend at
# the top of every scrape and buries the actual stack. Role is already derived
# separately (store.js `_deriveRole`), so these are dropped here.
_SKILL_STOPWORDS = frozenset({
    "", "n/a", "na", "none", "null", "-", "--", "etc", "and", "or", "the",
    "remote", "senior", "junior", "mid", "fulltime",
    "full time", "part time", "contract", "various", "other", "others",
    "tbd", "unknown", "not specified", "experience", "years", "plus",
    # Role / seniority / generic-industry nouns emitted by TECH_FILTER.
    "developer", "developers", "engineer", "engineers", "engineering",
    "programmer", "software", "web", "tech", "technology", "it",
    "backend", "back-end", "back end", "frontend", "front-end", "front end",
    "fullstack", "full-stack", "full stack", "development", "coding",
})

# Acronyms that must stay uppercase when no alias matched.
_SKILL_UPPER = frozenset({
    "aws", "gcp", "sql", "api", "css", "html", "php", "ios", "jwt", "orm",
    "oop", "saas", "ui", "ux", "cms", "crm", "etl", "qa", "ci", "cd", "ml",
    "ai", "bi", "erp", "sdk", "cli", "xml", "json", "yaml", "tcp", "http",
})

# Max words in a token before it's treated as prose, not a skill.
_SKILL_MAX_WORDS = 3
_SKILL_MAX_LEN = 32


def _canonical_skill(token: str) -> str:
    """Normalize one raw tech_stack token to a display name ('' = drop it)."""
    # Two forms, because punctuation stripping is lossy for a few real names:
    #   quoted  = only whitespace/quotes/brackets removed  -> ".NET" survives
    #   raw     = also edge punctuation removed            -> "React." -> "React"
    # Aliases are looked up against BOTH, quoted first, so a leading-dot or
    # trailing-plus name is matched before its punctuation is thrown away.
    # (Regression: ".NET" was stripped to "NET" and title-cased into "Net".)
    quoted = " ".join(str(token or "").strip(_SKILL_QUOTES).split())
    raw = " ".join(quoted.strip(_SKILL_STRIP).split())
    if not raw or len(raw) > _SKILL_MAX_LEN:
        return ""
    quoted_key = quoted.lower()
    key = raw.lower()
    # Fold hyphen/underscore to space so "back-end"/"back end"/"back_end" and
    # "react-native"/"react native" resolve to one key. Real scrapes contain
    # both spellings of the same token in a single cell.
    folded = re.sub(r"[-_]+", " ", key).strip()
    folded = " ".join(folded.split())
    if (
        key in _SKILL_STOPWORDS
        or quoted_key in _SKILL_STOPWORDS
        or folded in _SKILL_STOPWORDS
    ):
        return ""
    alias = (
        _SKILL_ALIASES.get(quoted_key)
        or _SKILL_ALIASES.get(key)
        or _SKILL_ALIASES.get(folded)
    )
    if alias:
        return alias
    if len(key.split()) > _SKILL_MAX_WORDS:
        return ""
    # Must contain a letter (drops "3", "5+", "2026").
    if not any(ch.isalpha() for ch in key):
        return ""
    if key in _SKILL_UPPER:
        return key.upper()
    # Preserve deliberate casing (Kubernetes, PostgreSQL, iOS typed by hand);
    # only fix obviously-unstyled all-lower / all-upper tokens.
    if raw.islower() or raw.isupper():
        return " ".join(w[:1].upper() + w[1:] for w in key.split())
    return raw


def extract_skills(raw: Any) -> List[str]:
    """Split one tech_stack cell into canonical, de-duplicated skill names."""
    if raw is None:
        return []
    if isinstance(raw, (list, tuple, set)):
        tokens: List[str] = [str(t) for t in raw]
    else:
        tokens = _SKILL_SPLIT.split(str(raw))
    out: List[str] = []
    seen = set()
    for token in tokens:
        name = _canonical_skill(token)
        if not name:
            continue
        dedupe_key = name.lower()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        out.append(name)
    return out


def get_skills_snapshot(tab: str = "ALL JOBS", limit: int = 12) -> Dict[str, Any]:
    """Aggregate `tech_stack` demand across a job tab. Never crashes.

    Counts each skill once per job (a row listing "React, React" counts once),
    so `pct` = share of stack-bearing jobs on the tab that mention the skill.
    Ties break alphabetically, keeping output stable across identical reads.
    """
    if tab not in JOB_TABS:
        raise ValueError(f"Unknown tab '{tab}'. Expected one of: {', '.join(JOB_TABS)}")
    try:
        rows = get_tab_rows(tab)
        counts: Dict[str, int] = {}
        display: Dict[str, str] = {}
        jobs_with_stack = 0
        for row in rows:
            names = extract_skills(row.get("tech_stack"))
            if not names:
                continue
            jobs_with_stack += 1
            for name in names:
                key = name.lower()
                counts[key] = counts.get(key, 0) + 1
                display.setdefault(key, name)
        ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        top = ranked[: max(0, limit)]
        skills = [
            {
                "name": display[key],
                "count": count,
                "pct": round(count * 100 / jobs_with_stack) if jobs_with_stack else 0,
            }
            for key, count in top
        ]
        return {
            "tab": tab,
            "total_jobs": len(rows),
            "jobs_with_stack": jobs_with_stack,
            "unique_skills": len(counts),
            "skills": skills,
        }
    except Exception:
        return {
            "tab": tab,
            "total_jobs": 0,
            "jobs_with_stack": 0,
            "unique_skills": 0,
            "skills": [],
        }


def get_tracker_rows(
    status: Optional[str] = None, force: bool = False
) -> List[Dict[str, Any]]:
    """APPLIED-tab rows (header-driven, works with either header fork)."""
    rows = get_tab_rows(TRACKER_TAB, force=force)
    if status is None:
        return rows
    wanted = status.strip().lower()
    return [r for r in rows if (r.get("status") or "").strip().lower() == wanted]


def _resolve_tracker_url(job_fingerprint: str) -> str:
    """Map a fingerprint (or raw apply_url) to the APPLIED-tab apply_url key."""
    key = (job_fingerprint or "").strip()
    if not key:
        raise LookupError("Empty tracker key")
    if key.startswith("http"):
        return key
    for row in get_tracker_rows():
        if (row.get("job_fingerprint") or "").strip() == key:
            url = (row.get("apply_url") or "").strip()
            if url:
                return url
    job = get_job(key)
    if job and (job.get("apply_url") or "").strip():
        return job["apply_url"].strip()
    raise LookupError(f"No application or job found for '{key}'")


def add_tracker_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Append one manual application to APPLIED and refresh tracker cache."""
    from tools.application_tracker import mark_applied
    from tools.sheet_writer import get_sheet

    apply_url = (entry.get("apply_url") or "").strip()
    if not apply_url:
        raise ValueError("apply_url is required")
    spreadsheet = get_sheet()
    created = mark_applied(
        spreadsheet,
        apply_url=apply_url,
        job_title=entry.get("job_title") or "",
        company=entry.get("company") or "",
        match_score=int(float(entry.get("match_score") or 0)),
        notes=entry.get("notes") or "",
        source=entry.get("source") or "",
        salary=entry.get("salary") or "",
        contact=entry.get("contact") or "",
        follow_up_days=int(entry.get("follow_up_days") if entry.get("follow_up_days") is not None else 7),
    )
    refresh(TRACKER_TAB)
    return {
        **entry,
        **created,
        "match_score": entry.get("match_score") or 0,
        "notes": entry.get("notes") or "",
        "source": entry.get("source") or "",
        "salary": entry.get("salary") or "",
        "contact": entry.get("contact") or "",
    }


def update_tracker_status(
    job_fingerprint: str, new_status: str, notes: str = ""
) -> bool:
    """Update one APPLIED row via tools.application_tracker.update_status.

    Raises LookupError when the fingerprint/URL resolves to nothing.
    Returns True on success, False when the row was not found.
    """
    from tools.application_tracker import update_status
    from tools.sheet_writer import get_sheet

    normalized = (new_status or "").strip().lower()
    apply_url = _resolve_tracker_url(job_fingerprint)
    spreadsheet = get_sheet()
    ok = update_status(spreadsheet, apply_url, normalized, notes or "")
    if ok:
        refresh(TRACKER_TAB)
    return bool(ok)


def update_tracker_and_get(
    job_fingerprint: str, new_status: str, notes: str = ""
) -> Optional[Dict[str, Any]]:
    """Resolve + update + re-fetch one APPLIED row in a single public call.

    Single entry point for PATCH /api/tracker/{fp} so handlers don't touch
    private resolvers or issue 3 separate sheet reads. Returns the fresh row
    dict, or None when the row was not found. Raises LookupError when the
    fingerprint/URL resolves to nothing.
    """
    normalized = (new_status or "").strip().lower()
    apply_url = _resolve_tracker_url(job_fingerprint)
    ok = update_tracker_status(job_fingerprint, normalized, notes or "")
    if not ok:
        return None
    for row in get_tracker_rows(force=True):
        if (row.get("apply_url") or "").strip() == apply_url:
            return row
    return {"apply_url": apply_url, "status": normalized}


# --- CV Studio reads ---------------------------------------------------------

# In-memory copy of the last cheap CV-profile read (no TTL — the on-disk
# cv_parser cache already expires entries >7 days; this just avoids
# re-reading the JSON file on every request). Never triggers LLM parsing.
_cv_profile_cache: Dict[str, Any] = {"profile": None, "source": None}


def _resolve_primary_cv_path() -> Optional[Path]:
    """Primary CV file (CV_PATH env, default my_cv.pdf). None on any error."""
    try:
        raw = (os.getenv("CV_PATH", "").strip() or "my_cv.pdf")
        path = Path(raw)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path
    except Exception:
        return None


def get_cv_profile(force: bool = False) -> Optional[Dict[str, Any]]:
    """Return the cached parsed-CV profile dict, or None when unavailable.

    Cheap path only: tools.cv_parser._load_cached_profile (reads
    cache/cv_profile_*.json when fresh, <7 days). Never calls parse_cv, so
    no LLM/network work happens per request. Missing CV file, missing/expired
    disk cache, or missing loader -> None (router maps to 501). Never crashes.
    """
    try:
        with _lock:
            cached = _cv_profile_cache.get("profile")
            if cached is not None and not force:
                return dict(cached)
        cv_path = _resolve_primary_cv_path()
        if cv_path is None:
            return None
        try:
            if not cv_path.exists():
                return None
        except Exception:
            return None
        try:
            from tools.cv_parser import _load_cached_profile
        except Exception:
            return None
        try:
            profile = _load_cached_profile(str(cv_path))
        except Exception:
            return None
        if not isinstance(profile, dict) or not profile:
            return None
        with _lock:
            _cv_profile_cache["profile"] = dict(profile)
            try:
                _cv_profile_cache["source"] = str(cv_path)
            except Exception:
                _cv_profile_cache["source"] = None
        return dict(profile)
    except Exception:
        return None


def reset_cv_profile_cache() -> None:
    """Test helper: clear the in-memory CV profile copy."""
    with _lock:
        _cv_profile_cache["profile"] = None
        _cv_profile_cache["source"] = None


def save_cv_profile(patch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Merge user edits into the on-disk cv_parser cache. Never crashes.

    Only whitelisted contact + skill fields are merged; empty strings clear
    a field (stored as "" on disk, read back as null via schemas). Returns
    the merged profile dict, or None when there is no CV file to anchor the
    cache to (router maps to 501). Never triggers LLM parsing.
    """
    try:
        if not isinstance(patch, dict):
            return None
        cv_path = _resolve_primary_cv_path()
        if cv_path is None:
            return None
        try:
            if not cv_path.exists():
                return None
        except Exception:
            return None
        try:
            from tools.cv_parser import _load_cached_profile, _save_cached_profile
        except Exception:
            return None
        try:
            current = _load_cached_profile(str(cv_path)) or {}
        except Exception:
            current = {}
        if not isinstance(current, dict):
            current = {}
        merged = dict(current)
        # Whitelist: contact fields (strings) + skills (list of strings).
        for key in ("name", "full_name", "email", "phone", "linkedin",
                    "linkedin_url", "location"):
            if key in patch:
                val = patch.get(key)
                if val is None:
                    merged[key] = ""
                elif isinstance(val, str):
                    merged[key] = val.strip()
                else:
                    merged[key] = str(val).strip()
        for key in ("skills", "core_skills"):
            if key in patch:
                val = patch.get(key)
                if val is None:
                    merged[key] = []
                elif isinstance(val, list):
                    merged[key] = [str(s).strip() for s in val if str(s).strip()]
                elif isinstance(val, str):
                    merged[key] = [s.strip() for s in val.replace("\n", ",").split(",") if s.strip()]
        # Keep name/full_name in sync so both readers see the edit.
        if "full_name" in patch and "name" not in patch:
            merged["name"] = merged.get("full_name", "")
        if "name" in patch and "full_name" not in patch:
            merged["full_name"] = merged.get("name", "")
        if "linkedin_url" in patch and "linkedin" not in patch:
            merged["linkedin"] = merged.get("linkedin_url", "")
        if "linkedin" in patch and "linkedin_url" not in patch:
            merged["linkedin_url"] = merged.get("linkedin", "")
        try:
            _save_cached_profile(str(cv_path), merged)
        except Exception:
            return None
        with _lock:
            _cv_profile_cache["profile"] = dict(merged)
            try:
                _cv_profile_cache["source"] = str(cv_path)
            except Exception:
                _cv_profile_cache["source"] = None
        return dict(merged)
    except Exception:
        return None


def list_cv_variants() -> List[Dict[str, Any]]:
    """List CV variants as [{name, tags}]. Missing dir/library -> [], never 500.

    Preferred path: tools.cv_library.CVLibrary() discovery (profiles stay
    lazy — no parsing here). Fallback: scan <CV_DIR or cvs/> for
    *.pdf/*.docx with safe basenames. Safe tags via
    cv_library._extract_domain_tags when present, else ["general"].
    """
    try:
        try:
            from tools import cv_library as _cvlib
        except Exception:
            _cvlib = None
        if _cvlib is not None and hasattr(_cvlib, "CVLibrary"):
            try:
                library = _cvlib.CVLibrary()
                entries = list(getattr(library, "cvs", []) or [])
                out: List[Dict[str, Any]] = []
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    raw_name = str(entry.get("name") or entry.get("path") or "")
                    if not raw_name.strip():
                        continue
                    name = Path(raw_name).name.strip()
                    if not name:
                        continue
                    tags = entry.get("tags") or ["general"]
                    if not isinstance(tags, list):
                        tags = [str(tags)]
                    tags = [str(t).strip() for t in tags if str(t).strip()]
                    out.append({"name": name, "tags": tags or ["general"]})
                return out
            except Exception:
                pass  # fall through to directory scan
        # Fallback: direct directory scan (no library).
        try:
            dir_raw = (os.getenv("CV_DIR", "").strip() or "cvs")
        except Exception:
            dir_raw = "cvs"
        try:
            directory = Path(dir_raw)
            if not directory.is_absolute():
                directory = PROJECT_ROOT / directory
            if not directory.is_dir():
                return []
            tag_fn = getattr(_cvlib, "_extract_domain_tags", None) if _cvlib else None
            exts = {".pdf", ".docx"}
            try:
                files = sorted(
                    f for f in directory.iterdir()
                    if f.is_file() and f.suffix.lower() in exts
                )
            except Exception:
                return []
            out = []
            for f in files:
                try:
                    tags = list(tag_fn(f.name)) if callable(tag_fn) else ["general"]
                except Exception:
                    tags = ["general"]
                if not tags:
                    tags = ["general"]
                out.append({"name": f.name, "tags": [str(t) for t in tags]})
            return out
        except Exception:
            return []
    except Exception:
        return []


def sheets_configured() -> bool:
    """Presence-only check for Sheets wiring (never reads secret values)."""
    service_account = (os.getenv("GOOGLE_SERVICE_ACCOUNT") or "").strip()
    sheets_id = (os.getenv("GOOGLE_SHEETS_ID") or "").strip()
    if not service_account or not sheets_id:
        return False
    try:
        return Path(service_account).exists()
    except Exception:
        return False
