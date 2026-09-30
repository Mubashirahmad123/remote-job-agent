"""Phase 2a fill-only apply service (no submit opcode anywhere).

Job resolution reuses the read cache (cache.get_job searches ALL JOBS first),
so the cockpit can only fill for jobs the API already serves. Tier comes from
agents.auto_applier.classify_tier (lazy import — agents/curator.py parses the
CV at import time, so pipeline modules are never imported at app startup).

What this does:
  - dream tier -> DreamTierForbidden (router maps to 422: well-formed but
    forbidden, never auto-touch a dream job).
  - good_fit / batch -> local apply package via
    agents.auto_applier.generate_apply_package (form_data.json + index.html,
    no browser, no sheet write, no submit click).

What this NEVER does (by construction, not by flag):
  - no Playwright launch, no submit click, no status:"submitted" write.
  - never reads AUTO_APPLY_CONFIRM — env cannot re-enable submit over HTTP.
"""

from typing import Any, Dict


class DreamTierForbidden(Exception):
    """Raised when a fill is requested for a dream-tier job (422)."""


def fill_review(job_fingerprint: str) -> Dict[str, Any]:
    """Build a fill-and-review package for one job. Raises on failure."""
    from api import cache

    job = cache.get_job(job_fingerprint)
    if job is None:
        raise LookupError(f"No job found for '{job_fingerprint}'")

    # Lazy pipeline import (lazy-import rule: api/* must never import
    # agents.* at startup).
    from agents.auto_applier import classify_tier, generate_apply_package

    tier = classify_tier(job)
    if tier == "dream":
        raise DreamTierForbidden(
            f"Job '{job_fingerprint}' is dream tier — manual application only"
        )

    package_path = generate_apply_package(job, None, "")
    if not package_path:
        raise RuntimeError("Apply package generation returned no path")

    return {
        "status": "filled_ready",
        "mode": "review",
        "job_fingerprint": (job.get("job_fingerprint") or job_fingerprint).strip(),
        "job_title": job.get("job_title", ""),
        "company": job.get("company", ""),
        "tier": tier,
        "package_path": str(package_path),
        "screenshot_path": None,
        "submit_enabled": False,
    }
