"""Fill-and-review apply service + Greenhouse-only submit (2b split).

Job resolution reuses the read cache (cache.get_job searches ALL JOBS first),
so the cockpit can only fill for jobs the API already serves. Tier comes from
agents.auto_applier.classify_tier (lazy import — agents/curator.py parses the
CV at import time, so pipeline modules are never imported at app startup).

What this does:
  - dream tier -> DreamTierForbidden (router maps to 422: well-formed but
    forbidden, never auto-touch a dream job).
    - good_fit / batch -> local apply package plus a visible review-window fill
        for Greenhouse/Lever using the existing fill-only helpers.
    - unsupported ATS -> local apply package only.
  - Greenhouse-only submit: create_greenhouse_intent / submit_greenhouse
    implement the 2b split (intent + claim-first + triple gate + daily cap +
    URL/message verification). Lever and all other ATSs raise
    SubmitUnavailable ("Submit is not available for this ATS") — no submit
    code path exists for them.

What this NEVER does (by construction, not by flag):
    - no call to auto_apply(), no Lever submit click.
  - never reads AUTO_APPLY_CONFIRM — env cannot re-enable or bypass submit over HTTP.
"""

import hashlib
from typing import Any, Dict
from queue import Queue
from threading import Event, Thread
from datetime import datetime, timezone
from datetime import timedelta
from pathlib import Path
import os
import sqlite3
import time
from urllib.parse import urlparse


class DreamTierForbidden(Exception):
    """Raised when a fill is requested for a dream-tier job (422)."""


class SubmitRejected(Exception):
    def __init__(self, status_code: int, detail: str, retry_after: int | None = None):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.retry_after = retry_after


class SubmitUnavailable(Exception):
    """Raised when submit is intentionally unsupported for this ATS."""


def _fill_ats_form(job: Dict[str, Any]) -> Dict[str, Any] | None:
    """Fill a supported ATS form in a review window; never click submit."""
    from agents.auto_applier import (
        APPLICANT_EMAIL,
        APPLICANT_LINKEDIN,
        APPLICANT_NAME,
        APPLICANT_PHONE,
        APPLICANT_PORTFOLIO,
        _fill_greenhouse_form,
        _fill_lever_form,
        _get_playwright,
        _is_container,
        detect_ats_platform,
    )

    apply_url = job.get("apply_url", "")
    platform = detect_ats_platform(apply_url) if apply_url else "unknown"
    if platform not in {"greenhouse", "lever"}:
        return None

    sync_playwright = _get_playwright()
    if sync_playwright is None:
        return {
            "status": "playwright_not_installed",
            "screenshot_path": None,
            "error": "Playwright is not installed",
        }

    profile = {
        "name": APPLICANT_NAME,
        "email": APPLICANT_EMAIL,
        "phone": APPLICANT_PHONE,
        "linkedin": APPLICANT_LINKEDIN,
        "portfolio": APPLICANT_PORTFOLIO,
    }

    container = _is_container()
    completed = Event()
    results: Queue[Dict[str, Any]] = Queue(maxsize=1)

    def run_review_session() -> None:
        browser = None
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=container)
                page = browser.new_page(viewport={"width": 1280, "height": 900})
                filler = _fill_greenhouse_form if platform == "greenhouse" else _fill_lever_form
                result = filler(page, apply_url, None, "", profile)
                result["browser_opened"] = not container
                results.put(result)
                completed.set()

                if not container:
                    try:
                        page.wait_for_event("close", timeout=30 * 60 * 1000)
                    except Exception:
                        pass
        except Exception as error:
            if not completed.is_set():
                results.put({
                    "status": "error",
                    "screenshot_path": None,
                    "error": str(error),
                    "browser_opened": False,
                })
                completed.set()
        finally:
            if browser is not None:
                try:
                    browser.close()
                except Exception:
                    pass

    Thread(target=run_review_session, name="apply-review-browser", daemon=True).start()
    if not completed.wait(timeout=90):
        return {
            "status": "error",
            "screenshot_path": None,
            "error": "Timed out waiting for ATS review form to fill",
            "browser_opened": False,
        }
    return results.get_nowait()


def fill_review(job_fingerprint: str) -> Dict[str, Any]:
    """Build a review package and fill supported ATS fields, never submit."""
    from api import cache

    job = cache.get_job(job_fingerprint)
    if job is None:
        raise LookupError(f"No job found for '{job_fingerprint}'")

    # Lazy pipeline import (lazy-import rule: api/* must never import
    # agents.* at startup).
    from agents.auto_applier import classify_tier, detect_ats_platform, generate_apply_package

    tier = classify_tier(job)
    if tier == "dream":
        raise DreamTierForbidden("Dream-tier jobs require manual application")

    package_path = generate_apply_package(job, None, "")
    if not package_path:
        raise RuntimeError("Apply package generation returned no path")

    fill_result = _fill_ats_form(job)
    apply_url = job.get("apply_url", "")
    platform = detect_ats_platform(apply_url) if apply_url else "unknown"
    if platform in {"greenhouse", "lever"} and fill_result and fill_result.get("screenshot_path"):
        from api.apply_state import save_review_artifact

        score = float(job.get("match_score", job.get("score", 0)) or 0)
        match_ratio = score / 100 if score > 1 else score
        save_review_artifact({
            "job_fingerprint": (job.get("job_fingerprint") or job_fingerprint).strip(),
            "platform": platform,
            "job_title": job.get("job_title", ""),
            "apply_url": apply_url,
            "package_path": str(package_path),
            "screenshot_path": fill_result["screenshot_path"],
            "confirmation_path": fill_result.get("confirmation_path"),
            "confirmation_message": fill_result.get("confirmation_message"),
            "match_ratio": match_ratio,
            "fill_status": fill_result["status"],
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

    return {
        "status": fill_result["status"] if fill_result else "package_only",
        "mode": "review",
        "job_fingerprint": (job.get("job_fingerprint") or job_fingerprint).strip(),
        "job_title": job.get("job_title", ""),
        "company": job.get("company", ""),
        "apply_url": job.get("apply_url", ""),
        "tier": tier,
        "package_path": str(package_path),
        "screenshot_path": fill_result.get("screenshot_path") if fill_result else None,
        "screenshot_url": (
            f"/api/apply/{(job.get('job_fingerprint') or job_fingerprint).strip()}/screenshot"
            if fill_result and fill_result.get("screenshot_path")
            else None
        ),
        "fill_error": fill_result.get("error") if fill_result else None,
        "confirmation_metadata_available": bool(
            fill_result
            and fill_result.get("confirmation_path")
            and fill_result.get("confirmation_message")
        ),
        "browser_opened": fill_result.get("browser_opened", False) if fill_result else False,
        "submit_enabled": False,
    }


def _get_cached_job(job_fingerprint: str) -> Dict[str, Any]:
    from api import cache

    job = cache.get_job(job_fingerprint)
    if job is None:
        raise LookupError(f"No job found for '{job_fingerprint}'")
    return job


def get_review_screenshot_path(job_fingerprint: str) -> Path:
    """Resolve the stored before-submit screenshot for a fingerprint.

    Lookup is by artifact ID only (never a raw client-supplied path), so
    there is no path-traversal surface: the DB holds the server-side path
    written by fill_review(). Raises LookupError (no artifact / no fill
    ran) or FileNotFoundError (artifact exists but file is gone).
    """
    from api.apply_state import get_review_artifact

    artifact = get_review_artifact(job_fingerprint)
    if not artifact or not artifact.get("screenshot_path"):
        raise LookupError("No screenshot exists yet (package-only, no fill run)")
    path = Path(str(artifact["screenshot_path"]))
    if not path.is_file():
        raise FileNotFoundError(f"Screenshot file is missing: {path}")
    return path


def _score_ratio(job: Dict[str, Any]) -> float:
    raw_score = float(job.get("match_score", job.get("score", 0)) or 0)
    return raw_score / 100 if raw_score > 1 else raw_score


def _prepare_submit_materials(job: Dict[str, Any]) -> Dict[str, str]:
    """Generate the tailored resume + cover letter once per submit (lazy imports).

    Returns {"resume_path": ..., "cover_letter_text": ...}. Raises RuntimeError
    when generation fails so intent fails closed instead of submitting
    attachment-less. The submit refill reuses exactly these files.
    """
    from tools.resume_generator import generate_resume_for_job

    resume_path = generate_resume_for_job(job)
    if not resume_path or not Path(str(resume_path)).is_file():
        raise RuntimeError("Tailored resume generation returned no file")

    from agents.gemini_tools import _load_cv_profile, generate_cover_letter

    selected_cv_path = job.get("selected_cv_path", "") or None
    cover_text = generate_cover_letter(
        job.get("job_title", "") or "Software Developer",
        job.get("company", "") or "Hiring Team",
        job.get("summary", "") or "",
        (os.getenv("APPLICANT_NAME") or "Mubashir").strip() or "Mubashir",
        tech_stack=job.get("tech_stack", "") or "",
        cv_profile=_load_cv_profile(selected_cv_path),
        selected_cv_path=selected_cv_path,
    )
    if not cover_text or len(cover_text.strip()) < 20:
        raise RuntimeError("Cover letter generation returned no text")
    return {"resume_path": str(resume_path), "cover_letter_text": cover_text}


def create_greenhouse_intent(job_fingerprint: str) -> Dict[str, str]:
    """Issue a five-minute one-use intent after a real GH fill and screenshot."""
    from api.apply_intents import ActiveIntentConflict, create_intent
    from api.apply_state import connect, get_review_artifact, save_review_artifact
    from agents.auto_applier import classify_tier, detect_ats_platform, generate_apply_package

    job = _get_cached_job(job_fingerprint)
    if detect_ats_platform(job.get("apply_url", "")) != "greenhouse":
        raise SubmitUnavailable("Submit is not available for this ATS")
    if classify_tier(job) == "dream":
        raise DreamTierForbidden("Dream-tier jobs require manual application")
    artifact = get_review_artifact(job_fingerprint)
    if (
        not artifact
        or artifact["platform"] != "greenhouse"
        or artifact["fill_status"] != "filled_ready"
        or not Path(artifact["package_path"]).exists()
        or not artifact["screenshot_path"]
        or not Path(artifact["screenshot_path"]).is_file()
    ):
        raise SubmitRejected(409, "Complete a successful Greenhouse fill and screenshot first")
    if not artifact["confirmation_path"] or not artifact["confirmation_message"]:
        raise SubmitRejected(502, "Greenhouse confirmation metadata is unavailable on the public page")

    try:
        materials = _prepare_submit_materials(job)
    except Exception as error:
        raise SubmitRejected(502, f"Submit materials generation failed: {error}")
    package_path = generate_apply_package(
        job, materials["resume_path"], materials["cover_letter_text"]
    )
    if not package_path:
        raise SubmitRejected(502, "Submit package rebuild returned no path")
    artifact = {
        **artifact,
        "package_path": str(package_path),
        "resume_path": materials["resume_path"],
        "cover_letter_text": materials["cover_letter_text"],
    }
    save_review_artifact(artifact)

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=5)
    import secrets

    token = secrets.token_urlsafe(32)
    connection = connect()
    try:
        try:
            result = create_intent(connection, job_fingerprint, token, expires_at, now)
        except ActiveIntentConflict as error:
            raise SubmitRejected(409, "An unexpired intent already exists", error.retry_after)
    finally:
        connection.close()
    return {"intent_token": token, "expires_at": result["expires_at"]}


def _run_greenhouse_submit(artifact: Dict[str, Any], job: Dict[str, Any]) -> Dict[str, Any]:
    """Submit once in a fresh page after filling; report whether click was attempted."""
    from agents.auto_applier import (
        APPLICANT_EMAIL,
        APPLICANT_LINKEDIN,
        APPLICANT_NAME,
        APPLICANT_PHONE,
        APPLICANT_PORTFOLIO,
        _fill_greenhouse_form,
        _get_playwright,
    )
    from api.apply_verification import verify_greenhouse_confirmation

    result: Dict[str, Any] = {"clicked": False, "verified": False, "error": None}
    sync_playwright = _get_playwright()
    if sync_playwright is None:
        result["error"] = "Playwright is not installed"
        return result

    profile = {
        "name": APPLICANT_NAME,
        "email": APPLICANT_EMAIL,
        "phone": APPLICANT_PHONE,
        "linkedin": APPLICANT_LINKEDIN,
        "portfolio": APPLICANT_PORTFOLIO,
    }
    browser = None
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            fill_result = _fill_greenhouse_form(
                page,
                artifact["apply_url"],
                artifact.get("resume_path"),
                artifact.get("cover_letter_text") or "",
                profile,
            )
            result["screenshot_path"] = fill_result.get("screenshot_path")
            if fill_result.get("status") != "filled_ready":
                result["error"] = fill_result.get("error") or fill_result.get("status")
                return result
            if (
                fill_result.get("confirmation_path") != artifact["confirmation_path"]
                or fill_result.get("confirmation_message") != artifact["confirmation_message"]
            ):
                result["error"] = "Greenhouse confirmation metadata changed since review"
                return result

            submit_button = page.locator(
                "input[type='submit'], button[type='submit'], #submit_app"
            ).first
            if submit_button.count() == 0:
                result["error"] = "Greenhouse submit button was not found"
                return result

            result["clicked"] = True
            submit_button.click(timeout=15000)
            confirmation_path = artifact["confirmation_path"]
            try:
                page.wait_for_url(
                    lambda url: (urlparse(str(url)).path.rstrip("/") or "/")
                    == (confirmation_path.rstrip("/") or "/"),
                    timeout=20000,
                )
            except Exception:
                pass
            result["verified"] = verify_greenhouse_confirmation(
                page,
                confirmation_path=confirmation_path,
                confirmation_message=artifact["confirmation_message"],
            )
            if not result["verified"]:
                result["error"] = "Greenhouse confirmation URL/message did not match"
    except Exception as error:
        result["error"] = str(error)
    finally:
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
    return result


def submit_greenhouse(
    path_fingerprint: str,
    confirm: Any,
    body_fingerprint: str | None,
    intent_token: str | None,
    typed_title: str | None,
) -> Dict[str, Any]:
    """Validate the request, claim/cap atomically, then submit Greenhouse only."""
    from agents.auto_applier import classify_tier, detect_ats_platform
    from api.apply_claims import (
        ClaimConflict,
        DailyCapExceeded,
        claim_first,
        finalize_claim,
        mark_pre_click_failure,
    )
    from api.apply_intents import IntentConsumed, IntentExpired, validate_intent
    from api.apply_state import connect, get_review_artifact
    from api.apply_validation import validate_confirmation_echo, validate_submit_inputs

    job = _get_cached_job(path_fingerprint)
    if detect_ats_platform(job.get("apply_url", "")) != "greenhouse":
        raise SubmitUnavailable("Submit is not available for this ATS")
    if classify_tier(job) == "dream":
        raise DreamTierForbidden("Dream-tier jobs require manual application")
    actual_ratio = _score_ratio(job)

    # (a) Explicit confirmation and exact fingerprint echo.
    rejections = validate_confirmation_echo(confirm, body_fingerprint, path_fingerprint, actual_ratio)
    if rejections:
        raise SubmitRejected(400, "Confirmation or fingerprint echo mismatch")

    # (b) Validate the one-use token for this same fingerprint. The claim
    # transaction revalidates and consumes it atomically after checking the
    # unique claim first, so a losing concurrent request cannot burn the token.
    if not intent_token:
        raise SubmitRejected(410, "Intent is missing or expired")
    connection = connect()
    try:
        try:
            validate_intent(connection, path_fingerprint, intent_token)
        except IntentConsumed:
            raise SubmitRejected(409, "Intent has already been consumed")
        except IntentExpired:
            raise SubmitRejected(410, "Intent is missing or expired")
    finally:
        connection.close()

    # (c) CV score and typed-title confirmation, with per-rejection audit logs.
    rejections = validate_submit_inputs(actual_ratio, job.get("job_title", ""), typed_title or "")
    if rejections:
        raise SubmitRejected(422, "Fit score or typed job title did not pass confirmation")

    artifact = get_review_artifact(path_fingerprint)
    if (
        not artifact
        or artifact["platform"] != "greenhouse"
        or artifact["fill_status"] != "filled_ready"
        or not Path(artifact["package_path"]).exists()
        or not Path(artifact["screenshot_path"]).is_file()
        or not artifact["confirmation_path"]
        or not artifact["confirmation_message"]
    ):
        raise SubmitRejected(410, "Greenhouse fill evidence or confirmation metadata is unavailable")
    if (
        not artifact.get("resume_path")
        or not Path(str(artifact["resume_path"])).is_file()
        or not (artifact.get("cover_letter_text") or "").strip()
    ):
        raise SubmitRejected(410, "Submit materials are missing — request a fresh intent")

    import agents.auto_applier as auto_applier

    connection = connect()
    try:
        try:
            token_hash = hashlib.sha256(intent_token.encode("utf-8")).hexdigest()
            claim_first(
                connection,
                path_fingerprint,
                daily_cap=auto_applier.AUTO_APPLY_DAILY_CAP,
                intent_hash=token_hash,
                intent_token_hash=token_hash,
            )
        except ClaimConflict as error:
            raise SubmitRejected(409, "A submit claim already exists", error.retry_after)
        except DailyCapExceeded as error:
            raise SubmitRejected(409, "Daily submit cap reached", error.retry_after)
        except IntentConsumed:
            raise SubmitRejected(409, "Intent has already been consumed")
        except IntentExpired:
            raise SubmitRejected(410, "Intent is missing or expired")
    finally:
        connection.close()

    attempt = _run_greenhouse_submit(artifact, job)
    connection = connect()
    try:
        if attempt["clicked"]:
            finalized = finalize_claim(
                connection,
                path_fingerprint,
                "submitted" if attempt["verified"] else "submit_unverified",
            )
            if not finalized:
                raise SubmitRejected(422, "Could not persist Greenhouse submit outcome")
            if attempt["verified"]:
                return {
                    "status": "submitted",
                    "job_fingerprint": path_fingerprint,
                    "verification": "greenhouse_confirmation",
                }
            raise SubmitRejected(422, "Greenhouse submission could not be verified")

        mark_pre_click_failure(connection, path_fingerprint)
        raise SubmitRejected(502, attempt.get("error") or "Greenhouse failed before submit click")
    finally:
        connection.close()
