"""Opt-in personal-pipeline shadow hook. Never changes production selection.

MATCHING_SHADOW_PROFILE points to operator-owned JSON, not a user-facing API.
Structured evidence must be populated upstream; missing extraction stays review.
"""
from dataclasses import fields
import json
import os
from pathlib import Path

from tools.matching_policy import CandidatePolicy, JobEvidence
from tools.matching_score import MatchProfile, Requirement, RequirementsEvidence, score_match
from tools.matching_runtime import MatchStore


def _string_set(value, field):
    if not isinstance(value, (list, tuple, set, frozenset)) or any(
            not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{field} must be a collection of nonempty strings")
    return frozenset(value)


def load_profile(path: Path) -> MatchProfile:
    data = json.loads(path.read_text(encoding='utf-8'))
    policy = data['policy']
    return MatchProfile(CandidatePolicy(
        _string_set(policy.get('role_families', []), 'role_families'), _string_set(policy.get('work_locations', []), 'work_locations'),
        _string_set(policy.get('seniority_levels', []), 'seniority_levels'), _string_set(policy.get('relocation_destinations', []), 'relocation_destinations'),
        policy.get('sponsorship_required', True)),
        _string_set(data['skills'], 'skills'), data['version'], _string_set(data.get('learnable_skills', []), 'learnable_skills'))


def ensure_evidence(job: dict) -> dict:
    """Extract deterministic, quote-verified evidence for a job.

    Phase 2: nothing populated job["matching_evidence"], so every job
    became REVIEW (gates unknown) and the shortlist stayed empty. The
    extractor is deterministic and local - no network, no LLM - and job
    text is treated as untrusted DATA: it is pattern-matched, never
    obeyed. The caller's job dict is not mutated; the returned evidence
    dict is used directly by shadow_batch.
    """
    existing = job.get('matching_evidence')
    if isinstance(existing, dict) and existing:
        return existing
    try:
        from tools.matching_extract import extract_matching_evidence
        return extract_matching_evidence(job)
    except Exception:
        # A malformed job carries no evidence, so its gates stay UNKNOWN.
        return {}


def shadow_batch(jobs: list[dict], profile: MatchProfile, store: MatchStore, owner: str):
    results = {}
    for job in jobs:
        job_id = job.get('job_fingerprint')
        if not job_id:
            raise ValueError('Shadow jobs require stable job_fingerprint')
        evidence = ensure_evidence(job)
        job_fields = {f.name for f in fields(JobEvidence)} - {'title', 'description'}
        kwargs = {k: v for k, v in evidence.items() if k in job_fields}
        if kwargs.get('allowed_work_locations') is not None:
            kwargs['allowed_work_locations'] = _string_set(kwargs['allowed_work_locations'], 'allowed_work_locations')
        kwargs.setdefault('work_mode', 'unknown')
        description = job.get('description') or job.get('summary') or None
        source = JobEvidence(job.get('job_title') or '', description, **kwargs)
        extracted = evidence.get('requirements') or {}

        def groups(name):
            return tuple(Requirement(_string_set(r['alternatives'], 'alternatives'), r['evidence'],
                                     r.get('weight', 1), r.get('essential', False))
                         for r in extracted.get(name, []))

        requirements = RequirementsEvidence(groups('required') if 'required' in extracted else None,
                                             groups('preferred'), extracted.get('complete', False),
                                             extracted.get('extractor_version', 'unextracted-v1'))
        result = score_match(source, profile, requirements)
        # Include all relevant facts, not just the text, in decision provenance.
        content = json.dumps({'title': source.title, 'description': description, 'evidence': evidence},
                             sort_keys=True)
        store.record(owner, job_id, content, result)
        if extracted:
            store.cache_extraction(owner, content, requirements.extractor_version, extracted)
        results[job_id] = result
    return results


def shadow_config_status() -> dict:
    """Report shadow configuration without leaking profile content.

    Startup/health logging lives here so a run can never be mistaken for
    shadow-enabled when the profile is unset, missing, or invalid.
    """
    path = os.getenv('MATCHING_SHADOW_PROFILE', '').strip()
    if not path:
        return {"configured": False, "reason": "MATCHING_SHADOW_PROFILE unset"}
    status = {"configured": True, "path": path, "exists": Path(path).is_file(), "version": None}
    if status["exists"]:
        try:
            status["version"] = load_profile(Path(path)).version
        except Exception as exc:
            status["error"] = type(exc).__name__
    return status


def log_shadow_config() -> str:
    """One health line naming profile path and version when enabled."""
    status = shadow_config_status()
    if not status["configured"]:
        line = "Matching shadow: DISABLED (MATCHING_SHADOW_PROFILE unset)"
    elif not status["exists"]:
        line = f"Matching shadow: BROKEN (profile missing: {status['path']})"
    elif status.get("error"):
        line = f"Matching shadow: BROKEN (profile invalid: {status['error']})"
    else:
        line = f"Matching shadow: ENABLED profile={status['path']} version={status['version']}"
    print(line)
    return line


def run_optional_shadow(jobs: list[dict]):
    path = os.getenv('MATCHING_SHADOW_PROFILE', '').strip()
    if not path:
        return None
    profile = load_profile(Path(path))
    store = MatchStore(Path(os.getenv('MATCHING_SHADOW_DB', 'data/matching_shadow.db')))
    return shadow_batch(jobs, profile, store, 'personal')
