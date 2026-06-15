import hashlib
import json
from pathlib import Path


DEFAULT_SEEN_JOBS_PATH = Path(__file__).resolve().parents[1] / "seen_jobs.json"


def normalize_url(url: str) -> str:
    """Normalize URLs so tracking parameters do not create duplicate jobs."""
    return (url or "").split("?")[0].strip().lower()


def job_fingerprint(job: dict) -> str:
    """Create a stable fingerprint from title, company, and normalized URL."""
    key_parts = [
        (job.get("job_title") or "").strip().lower(),
        (job.get("company") or "").strip().lower(),
        normalize_url(job.get("apply_url") or ""),
    ]
    key = "|".join(key_parts)
    return hashlib.md5(key.encode("utf-8")).hexdigest()


def add_job_fingerprint(job: dict) -> dict:
    """Attach a fingerprint to a job if it does not already have one."""
    job.setdefault("job_fingerprint", job_fingerprint(job))
    return job


def load_seen_hashes(path=DEFAULT_SEEN_JOBS_PATH):
    """Load previously seen job fingerprints from disk."""
    seen_path = Path(path)
    if not seen_path.exists():
        return set()

    try:
        data = json.loads(seen_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set()

    if isinstance(data, list):
        return {str(item) for item in data if item}
    if isinstance(data, dict):
        return {str(item) for item in data.get("seen_hashes", []) if item}
    return set()


def save_seen_hashes(seen_hashes, path=DEFAULT_SEEN_JOBS_PATH) -> None:
    """Save seen job fingerprints to disk."""
    seen_path = Path(path)
    seen_path.write_text(
        json.dumps(sorted(seen_hashes), indent=2),
        encoding="utf-8",
    )


def filter_already_seen(jobs: list, seen_hashes: set[str]) -> list:
    """Return only jobs whose fingerprint is not already in seen_hashes."""
    new_jobs = []
    for job in jobs:
        fingerprint = job_fingerprint(job)
        if fingerprint in seen_hashes:
            continue

        job["job_fingerprint"] = fingerprint
        new_jobs.append(job)
        seen_hashes.add(fingerprint)

    return new_jobs
