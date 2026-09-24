"""On-demand materials: tailored resume PDF + cover letter (Phase 2).

Synchronous POSTs (LLM calls take ~30-90s; no timeout pressure on uvicorn
defaults). Lazy-import rule: generators imported inside functions only —
agents/gemini_tools and tools/resume_generator pull LLM/CV stacks.

Job resolution reuses the read cache (cache.get_job searches ALL JOBS first),
so the Studio can only generate for jobs the API already serves. Produced
files are recorded per fingerprint in an in-memory registry; downloads serve
only registry-recorded paths inside the project output dirs (no user-supplied
paths, no traversal).
"""

import os
import re
import threading
from pathlib import Path
from typing import Any, Dict, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESUMES_DIR = PROJECT_ROOT / "resumes"
COVER_LETTERS_DIR = PROJECT_ROOT / "cover_letters"

_lock = threading.Lock()
_registry: Dict[str, Dict[str, Any]] = {}  # fp -> {resume_pdf, cover_letter_file, ...}


def _slug(text: str, limit: int = 40) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "_", (text or "").strip().lower())
    return cleaned.strip("_")[:limit] or "job"


def resolve_job(job_fingerprint: str) -> Optional[Dict[str, Any]]:
    """Enriched job dict for a fingerprint, or None when unknown."""
    from api import cache

    return cache.get_job(job_fingerprint)


def generate_resume(job_fingerprint: str) -> Dict[str, Any]:
    """Run the 1-page tailor for one job. Returns record; raises on failure."""
    from tools.resume_generator import generate_resume_for_job

    job = resolve_job(job_fingerprint)
    if job is None:
        raise LookupError(f"No job found for '{job_fingerprint}'")
    pdf_path = generate_resume_for_job(job, skip_existing=False)
    if not pdf_path:
        raise RuntimeError("Resume generation returned no file")
    pdf_path = str(pdf_path)
    _record(job_fingerprint, resume_pdf=pdf_path)
    return {
        "status": "ok",
        "job_fingerprint": (job.get("job_fingerprint") or "").strip(),
        "job_title": job.get("job_title", ""),
        "company": job.get("company", ""),
        "filename": Path(pdf_path).name,
    }


def generate_cover_letter(job_fingerprint: str) -> Dict[str, Any]:
    """Run role-aware cover-letter generation; persists text; returns record."""
    from agents.gemini_tools import generate_cover_letter as _gen

    job = resolve_job(job_fingerprint)
    if job is None:
        raise LookupError(f"No job found for '{job_fingerprint}'")
    applicant = (os.getenv("APPLICANT_NAME") or "Mubashir").strip() or "Mubashir"
    text = _gen(
        job.get("job_title", "") or "Software Developer",
        job.get("company", "") or "Hiring Team",
        job.get("summary", "") or "",
        applicant,
    )
    if not text or len(text.strip()) < 20:
        raise RuntimeError("Cover letter generation returned no text")
    fp = (job.get("job_fingerprint") or job_fingerprint).strip()
    filename = f"{fp[:12]}_{_slug(job.get('company'))}_cover_letter.txt"
    COVER_LETTERS_DIR.mkdir(parents=True, exist_ok=True)
    path = COVER_LETTERS_DIR / filename
    path.write_text(text, encoding="utf-8")
    _record(fp, cover_letter_file=str(path))
    return {
        "status": "ok",
        "job_fingerprint": fp,
        "job_title": job.get("job_title", ""),
        "company": job.get("company", ""),
        "filename": filename,
        "cover_letter": text,
    }


def _record(fp: str, **fields: Any) -> None:
    with _lock:
        entry = _registry.setdefault(fp, {})
        entry.update(fields)


def _resolve_recorded_path(fp: str, key: str, base: Path) -> Optional[Path]:
    """Return the recorded file iff it stays inside base dir. Else None."""
    with _lock:
        entry = dict(_registry.get(fp, {}))
    raw = (entry.get(key) or "").strip()
    if not raw:
        return None
    try:
        path = Path(raw)
        if not path.is_absolute():
            path = base / path.name
        resolved = path.resolve()
        if resolved.parent != base.resolve() or not resolved.is_file():
            return None
        return resolved
    except Exception:
        return None


def get_resume_pdf(fp: str) -> Optional[Path]:
    return _resolve_recorded_path(fp, "resume_pdf", RESUMES_DIR)


def get_cover_letter_file(fp: str) -> Optional[Path]:
    return _resolve_recorded_path(fp, "cover_letter_file", COVER_LETTERS_DIR)


def reset_registry() -> None:
    """Test helper: clear the materials registry."""
    with _lock:
        _registry.clear()
