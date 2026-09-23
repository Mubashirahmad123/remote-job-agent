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


def get_tab_rows(tab: str, force: bool = False) -> List[Dict[str, Any]]:
    """Return cached header->dict rows for a tab (TTL-guarded).

    Returns shallow copies so callers mutating a dict can't pollute the cache.
    Falls back to the local scrape snapshot for ALL JOBS when Sheets is
    unreachable (see _local_snapshot_rows) so the UI shows real project
    data instead of nothing. TOP/GOOD MATCHES never fall back — without
    sheet scores there is nothing honest to put there.
    """
    if tab not in ALL_TABS:
        raise ValueError(f"Unknown tab '{tab}'. Choose from: {', '.join(ALL_TABS)}")
    now = time.monotonic()
    with _lock:
        cached = _tab_cache.get(tab)
        if cached is not None and not force and _is_fresh(cached["at"]):
            return [dict(r) for r in cached["rows"]]
    rows = _rows_to_dicts(_read_tab_values(tab))
    if not rows and tab == "ALL JOBS":
        rows = _local_snapshot_rows()
    with _lock:
        _tab_cache[tab] = {"at": now, "rows": rows}
    return [dict(r) for r in rows]


# --- Local snapshot fallback -------------------------------------------------

# Checked in order; first file with a non-empty job list wins.
SNAPSHOT_FILES = ("scraped_jobs.json", "fresh_scrape.json")


def _local_snapshot_rows() -> List[Dict[str, Any]]:
    """Load real scraped jobs from a local snapshot file (no network).

    Returns sheet-shaped dicts for the ALL JOBS tab. Fingerprints reuse the
    pipeline MD5 scheme (tools/deduplicator.py:job_fingerprint) so the
    curated_jobs.json enrichment join and /api/jobs/{fp} keep working.
    Unscored fields stay "" (never invented). Missing/invalid files -> [].
    """
    for name in SNAPSHOT_FILES:
        path = PROJECT_ROOT / name
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
    for name in SNAPSHOT_FILES:
        try:
            path = PROJECT_ROOT / name
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
    now = time.monotonic()
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
