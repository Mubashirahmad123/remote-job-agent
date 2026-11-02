"""Opt-in personal-pipeline shadow hook. Never changes production selection.

MATCHING_SHADOW_PROFILE points to operator-owned JSON, not a user-facing API.
Structured evidence must be populated upstream; missing extraction stays review.
"""
from dataclasses import fields
import json
import os
from pathlib import Path
from uuid import uuid4

from tools.matching_policy import CandidatePolicy, JobEvidence
from tools.matching_score import MatchProfile, Requirement, RequirementsEvidence, score_match
from tools.matching_runtime import MatchStore


def _string_set(value, field):
    if not isinstance(value, (list, tuple, set, frozenset)) or any(
            not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{field} must be a collection of nonempty strings")
    return frozenset(value)


def _optional_number(value, field):
    """None or a real number; booleans are not numbers here."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a number or null")
    if value < 0:
        raise ValueError(f"{field} must not be negative")
    return value


def _optional_bool(value, field):
    if value is None:
        return False
    if type(value) is not bool:
        raise ValueError(f"{field} must be boolean")
    return value


def load_profile(path: Path) -> MatchProfile:
    """Operator-owned profile -> policy + skills.

    Every policy field is validated strictly: a malformed profile is an
    error, never a silently defaulted policy. Missing keys keep their
    conservative default (empty set / unknown), which makes the matching
    gate report UNKNOWN instead of guessing.
    """
    data = json.loads(path.read_text(encoding='utf-8'))
    policy = data['policy']
    return MatchProfile(CandidatePolicy(
        role_families=_string_set(policy.get('role_families', []), 'role_families'),
        work_locations=_string_set(policy.get('work_locations', []), 'work_locations'),
        seniority_levels=_string_set(policy.get('seniority_levels', []), 'seniority_levels'),
        relocation_destinations=_string_set(policy.get('relocation_destinations', []),
                                            'relocation_destinations'),
        sponsorship_required=_optional_bool(policy.get('sponsorship_required'), 'sponsorship_required')
        if policy.get('sponsorship_required') is not None else True,
        remote_work_locations=_string_set(policy.get('remote_work_locations', []),
                                          'remote_work_locations'),
        work_cities=_string_set(policy.get('work_cities', []), 'work_cities'),
        years_experience=_optional_number(policy.get('years_experience'), 'years_experience'),
        seniority_gap_threshold=_optional_number(policy.get('seniority_gap_threshold'),
                                                 'seniority_gap_threshold')
        if policy.get('seniority_gap_threshold') is not None else 2,
        accept_unrestricted_remote=_optional_bool(policy.get('accept_unrestricted_remote'),
                                                  'accept_unrestricted_remote')),
        _string_set(data['skills'], 'skills'), data['version'],
        _string_set(data.get('learnable_skills', []), 'learnable_skills'))


def ensure_evidence(job: dict) -> dict:
    """Attach deterministic, quote-verified evidence to a job.

    Errors are NOT swallowed — they propagate to shadow_batch which records
    them in run_status. Pre-existing evidence (e.g. hand-extracted) is
    respected.
    """
    existing = job.get('matching_evidence')
    if isinstance(existing, dict) and existing:
        return existing
    from tools.matching_extract import extract_matching_evidence
    evidence = extract_matching_evidence(job)
    job['matching_evidence'] = evidence
    return evidence


def _job_requirements(extracted: dict):
    """Extracted requirement groups -> scorer requirements (typed).

    `type` matters: practices and soft skills never enter coverage, so they
    can neither create a gap nor trigger the essential-gap rejection.
    """
    def groups(name):
        return tuple(Requirement(_string_set(r['alternatives'], 'alternatives'), r['evidence'],
                                 r.get('weight', 1), r.get('essential', False),
                                 r.get('type', 'technology'))
                    for r in extracted.get(name, []))

    return RequirementsEvidence(groups('required') if 'required' in extracted else None,
                                 groups('preferred'), extracted.get('complete', False),
                                 extracted.get('extractor_version', 'unextracted-v1'))


def _evaluate_job(job: dict, profile: MatchProfile, store: MatchStore, owner: str):
    """Evaluate ONE job. Raises on malformed input; the caller isolates it."""
    job_id = job.get('job_fingerprint')
    if not job_id:
        raise ValueError('Shadow jobs require stable job_fingerprint')
    evidence = ensure_evidence(job)
    job_fields = {f.name for f in fields(JobEvidence)} - {'title', 'description'}
    kwargs = {k: v for k, v in evidence.items() if k in job_fields}
    if kwargs.get('allowed_work_locations') is not None:
        kwargs['allowed_work_locations'] = _string_set(kwargs['allowed_work_locations'], 'allowed_work_locations')
    for name in ('responsibilities', 'role_hints'):
        if kwargs.get(name) is not None:
            kwargs[name] = _string_set(kwargs[name], name)
    kwargs.setdefault('work_mode', 'unknown')
    description = job.get('description') or job.get('summary') or None
    source = JobEvidence(job.get('job_title') or '', description, **kwargs)
    extracted = evidence.get('requirements') or {}
    requirements = _job_requirements(extracted)
    result = score_match(source, profile, requirements)
    # Include all relevant facts, not just the text, in decision provenance.
    content = json.dumps({'title': source.title, 'description': description, 'evidence': evidence},
                         sort_keys=True)
    store.record(owner, job_id, content, result, evidence)
    if extracted:
        store.cache_extraction(owner, content, requirements.extractor_version, extracted)
    return result


def shadow_batch(jobs: list[dict], profile: MatchProfile, store: MatchStore, owner: str,
                 run_id: str = None):
    """Evaluate a batch in shadow mode; never changes production selection.

    Per-job isolation (Phase 3): one malformed job must not abort the batch.
    Failed jobs are counted and listed in the run-status record
    (processed/failed/reasons) instead of silently disappearing, and no
    decision is invented for them. Extractor errors are recorded as
    extractor_error and the job is marked failed-extraction.
    """
    run_id = run_id or uuid4().hex[:12]
    store.start_run(owner, run_id, profile.version)
    results = {}
    failures = []
    for job in jobs:
        # Work on a shallow copy so the caller's job dicts are never mutated
        # by evidence attachment (ensure_evidence writes matching_evidence).
        job = dict(job) if isinstance(job, dict) else job
        job_id = job.get('job_fingerprint') if isinstance(job, dict) else None
        try:
            result = _evaluate_job(job, profile, store, owner)
        except Exception as exc:
            error_type = "extractor_error" if "extract" in type(exc).__name__.lower() else "evaluation_error"
            failures.append({"job_id": job_id,
                             "error": f"{error_type}: {type(exc).__name__}: {exc}"[:300]})
            continue
        results[job_id] = result
    store.finish_run(owner, run_id, profile.version, len(results), len(failures), failures)
    if failures:
        print(f"Matching shadow: {len(failures)} job(s) failed evaluation "
              f"(run {run_id}); see run_status.")
    return results


def shadow_config_status() -> dict:
    """Report shadow configuration without leaking profile content.

    Startup/health logging lives here so a run can never be mistaken for
    shadow-enabled when the profile is unset, missing, or invalid.
    """
    path = os.getenv('MATCHING_SHADOW_PROFILE', '').strip()
    if not path:
        return {"configured": False, "reason": "MATCHING_SHADOW_PROFILE unset"}
    status = {"configured": True, "path": path, "exists": Path(path).is_file(), "version": None,
              "unconfirmed": []}
    if status["exists"]:
        try:
            prof = load_profile(Path(path))
            status["version"] = prof.version
            # Collect unconfirmed preferences from _meta
            try:
                raw = json.loads(Path(path).read_text(encoding='utf-8'))
                meta = raw.get('_meta', {})
                status["unconfirmed"] = meta.get('unconfirmed_fields', [])
            except Exception:
                pass
        except Exception as exc:
            status["error"] = type(exc).__name__
    return status


def log_shadow_config() -> str:
    """One health line naming profile path and version when enabled.

    Includes unconfirmed fields so operators see which preferences are
    not personally confirmed.
    """
    status = shadow_config_status()
    if not status["configured"]:
        line = "Matching shadow: DISABLED (MATCHING_SHADOW_PROFILE unset)"
    elif not status["exists"]:
        line = f"Matching shadow: BROKEN (profile missing: {status['path']})"
    elif status.get("error"):
        line = f"Matching shadow: BROKEN (profile invalid: {status['error']})"
    else:
        unconfirmed = status.get("unconfirmed", [])
        uc = f" unconfirmed={unconfirmed}" if unconfirmed else ""
        line = f"Matching shadow: ENABLED profile={status['path']} version={status['version']}{uc}"
    print(line)
    return line


def run_optional_shadow(jobs: list[dict]):
    path = os.getenv('MATCHING_SHADOW_PROFILE', '').strip()
    if not path:
        return None
    profile = load_profile(Path(path))
    store = MatchStore(Path(os.getenv('MATCHING_SHADOW_DB', 'data/matching_shadow.db')))
    return shadow_batch(jobs, profile, store, 'personal')
