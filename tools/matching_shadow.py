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


def shadow_batch(jobs: list[dict], profile: MatchProfile, store: MatchStore, owner: str):
    results = {}
    for job in jobs:
        job_id = job.get('job_fingerprint')
        if not job_id:
            raise ValueError('Shadow jobs require stable job_fingerprint')
        evidence = job.get('matching_evidence') or {}
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


def run_optional_shadow(jobs: list[dict]):
    path = os.getenv('MATCHING_SHADOW_PROFILE', '').strip()
    if not path:
        return None
    profile = load_profile(Path(path))
    store = MatchStore(Path(os.getenv('MATCHING_SHADOW_DB', 'data/matching_shadow.db')))
    return shadow_batch(jobs, profile, store, 'personal')
