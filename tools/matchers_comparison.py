#!/usr/bin/env python3
"""Run both legacy and new matchers on the 312-job snapshot and produce confusion matrix.

Usage:
    python -m tools.matchers_comparison

Outputs:
    - Console: confusion matrix, per-class agreement, directional disagreement lists
    - JSON: detailed results for each job
"""

import json
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.curator import curate, _should_reject, _get_cv_matcher, _calculate_freshness_boost
from tools.matching_extract import extract_matching_evidence
from tools.matching_policy import CandidatePolicy, JobEvidence, evaluate_eligibility
from tools.matching_score import MatchProfile, Requirement, RequirementsEvidence, score_match
from tools.matching_shadow import load_profile, ensure_evidence, _job_requirements


# ─── Legacy matcher helpers ────────────────────────────────────────────────

MIN_SCORE = 30  # from agents.curator (global)
KEYWORD_WEIGHT = 0.6
SEMANTIC_WEIGHT = 0.4


def run_legacy_matcher(jobs: list[dict]) -> list[dict]:
    """Run the legacy matcher (curator's rejection + scoring) on a list of jobs.

    Returns list of jobs with legacy decision fields added:
    - legacy_decision: 'rejected' | 'low_match' | 'passed'
    - legacy_score: keyword_score (float)
    - legacy_reject_reason: str (if rejected)
    - legacy_match_reason: str (if low_match or passed)
    """
    # Initialize CV matcher
    matcher = _get_cv_matcher()
    
    results = []
    for job in jobs:
        # Make a copy to avoid mutating original
        j = dict(job)
        
        # Rejection check
        should_reject, reject_reason = _should_reject(j)
        if should_reject:
            j["legacy_decision"] = "rejected"
            j["legacy_reject_reason"] = reject_reason
            j["legacy_score"] = 0
            results.append(j)
            continue
        
        # Scoring
        if matcher:
            score_result = matcher.score(j)
            keyword_score = score_result.get("score", 0)
            match_reason = score_result.get("match_reason", "")
        else:
            keyword_score = 0
            match_reason = "No CV matching"
        
        # Freshness boost (ranking only)
        freshness = _calculate_freshness_boost(j.get("posted_date_iso", ""))
        
        # Semantic not available in this offline run
        base_score = keyword_score
        
        j["legacy_score"] = round(base_score, 1)
        j["legacy_match_reason"] = match_reason
        
        if base_score < MIN_SCORE:
            j["legacy_decision"] = "low_match"
        else:
            j["legacy_decision"] = "passed"
        
        results.append(j)
    
    return results


# ─── New matcher helpers ──────────────────────────────────────────────────

def load_new_matcher_profile() -> MatchProfile:
    """Load the operator profile for the new matcher."""
    profile_path = Path("data/matching_profile.json")
    return load_profile(profile_path)


def run_new_matcher(jobs: list[dict], profile: MatchProfile) -> list[dict]:
    """Run the new matcher (extract + policy + score) on a list of jobs.

    Returns list of jobs with new matcher decision fields added:
    - new_decision: 'eligible' | 'likely_fit' | 'review' | 'rejected'
    - new_score: coverage score (float or None)
    - new_review_reasons: list of str
    - new_eligibility: EligibilityResult
    """
    results = []
    for job in jobs:
        j = dict(job)
        
        # Extract evidence
        evidence = ensure_evidence(j)
        
        # Build JobEvidence for policy
        job_fields = set(JobEvidence.__dataclass_fields__.keys()) - {'title', 'description'}
        kwargs = {k: v for k, v in evidence.items() if k in job_fields}
        if kwargs.get('allowed_work_locations') is not None:
            from tools.matching_shadow import _string_set
            kwargs['allowed_work_locations'] = _string_set(kwargs['allowed_work_locations'], 'allowed_work_locations')
        for name in ('responsibilities', 'role_hints'):
            if kwargs.get(name) is not None:
                from tools.matching_shadow import _string_set
                kwargs[name] = _string_set(kwargs[name], name)
        kwargs.setdefault('work_mode', 'unknown')
        description = j.get('description') or j.get('summary') or None
        source = JobEvidence(j.get('job_title') or '', description, **kwargs)
        
        # Evaluate eligibility
        eligibility = evaluate_eligibility(source, profile.policy)
        
        # Get requirements
        extracted = evidence.get('requirements') or {}
        requirements = _job_requirements(extracted)
        
        # Score
        result = score_match(source, profile, requirements)
        
        j["new_decision"] = result.decision
        j["new_score"] = result.required.score
        j["new_review_reasons"] = list(result.review_reasons)
        j["new_eligibility"] = {
            "decision": eligibility.decision,
            "gates": [{"name": g.name, "outcome": g.outcome, "reason": g.reason} for g in eligibility.gates]
        }
        
        results.append(j)
    
    return results


# ─── Confusion matrix ──────────────────────────────────────────────────────

def confusion_matrix(legacy_jobs: list[dict], new_jobs: list[dict]) -> dict:
    """Compute confusion matrix between legacy and new matcher decisions.
    
    Legacy decisions: 'rejected', 'low_match', 'passed'
    New decisions: 'eligible', 'likely_fit', 'review', 'rejected'
    
    Returns dict with:
    - matrix: 3x4 dict of counts (legacy x new)
    - per_class: dict with agreement metrics per legacy class
    - disagreements: dict with lists of job_uids where decisions differ
    """
    # Map legacy -> row, new -> col
    legacy_labels = ['rejected', 'low_match', 'passed']
    new_labels = ['eligible', 'likely_fit', 'review', 'rejected']
    
    # Initialize matrix
    matrix = {l: {n: 0 for n in new_labels} for l in legacy_labels}
    
    # Track disagreements
    disagreements = {
        'legacy_rejected_new_not_rejected': [],
        'legacy_low_match_new_eligible': [],
        'legacy_passed_new_review_or_rejected': [],
        'legacy_passed_new_eligible_likely_fit': [],
    }
    
    # Create lookup by job_uid
    new_by_uid = {j['job_uid']: j for j in new_jobs}
    
    for lj in legacy_jobs:
        uid = lj['job_uid']
        nj = new_by_uid.get(uid)
        if not nj:
            continue
        
        legacy_dec = lj['legacy_decision']
        new_dec = nj['new_decision']
        
        matrix[legacy_dec][new_dec] += 1
        
        # Track notable disagreements
        if legacy_dec == 'rejected' and new_dec != 'rejected':
            disagreements['legacy_rejected_new_not_rejected'].append({
                'job_uid': uid,
                'title': lj.get('job_title', ''),
                'new_decision': new_dec,
                'new_reasons': nj.get('new_review_reasons', []),
                'legacy_reason': lj.get('legacy_reject_reason', '')
            })
        elif legacy_dec == 'low_match' and new_dec in ('eligible', 'likely_fit'):
            disagreements['legacy_low_match_new_eligible'].append({
                'job_uid': uid,
                'title': lj.get('job_title', ''),
                'legacy_score': lj.get('legacy_score', 0),
                'new_score': nj.get('new_score'),
                'new_decision': new_dec
            })
        elif legacy_dec == 'passed' and new_dec in ('review', 'rejected'):
            disagreements['legacy_passed_new_review_or_rejected'].append({
                'job_uid': uid,
                'title': lj.get('job_title', ''),
                'legacy_score': lj.get('legacy_score', 0),
                'new_score': nj.get('new_score'),
                'new_decision': new_dec,
                'new_reasons': nj.get('new_review_reasons', [])
            })
        elif legacy_dec == 'passed' and new_dec in ('eligible', 'likely_fit'):
            disagreements['legacy_passed_new_eligible_likely_fit'].append({
                'job_uid': uid,
                'title': lj.get('job_title', ''),
                'legacy_score': lj.get('legacy_score', 0),
                'new_score': nj.get('new_score'),
                'new_decision': new_dec
            })
    
    # Per-class agreement (legacy is NOT ground truth; these are directional)
    per_class = {}
    for legacy_dec in legacy_labels:
        total = sum(matrix[legacy_dec].values())
        if total == 0:
            per_class[legacy_dec] = {
                'support': 0,
                'agreement_rate': None,
                'note': 'No support'
            }
            continue
        
        # "Agreement" defined as: both say pass-ish, both say review-ish, both say reject-ish
        # This is NOT accuracy; legacy is the production selector, new is shadow
        if legacy_dec == 'passed':
            agree_count = matrix[legacy_dec]['eligible'] + matrix[legacy_dec]['likely_fit']
        elif legacy_dec == 'low_match':
            agree_count = matrix[legacy_dec]['review']  # low_match ~ review
        else:  # rejected
            agree_count = matrix[legacy_dec]['rejected']
        
        per_class[legacy_dec] = {
            'support': total,
            'agreement_count': agree_count,
            'agreement_rate': round(100 * agree_count / total, 1),
            'distribution': matrix[legacy_dec]
        }
    
    return {
        'matrix': matrix,
        'per_class': per_class,
        'disagreements': disagreements,
        'total': sum(sum(row.values()) for row in matrix.values())
    }


# ─── Main ──────────────────────────────────────────────────────────────────

def main():
    snapshot_path = Path("logs/live_runs/remote-job-agent-live-20261102-001/scraped_jobs_snapshot.json")
    
    if not snapshot_path.exists():
        print(f"ERROR: Snapshot not found at {snapshot_path}")
        print("Run the SQL extraction first:")
        print("  .venv/Scripts/python.exe -c \"import sqlite3, json; conn=sqlite3.connect('data/pipeline_ledger.db'); conn.row_factory=sqlite3.Row; c=conn.cursor(); c.execute('SELECT job_uid, title, company, url, source, description, description_sha256, fetched_at FROM job_texts WHERE run_id = \\'16556b5baffc\\' ORDER BY job_uid'); rows=c.fetchall(); jobs=[]; for r in rows: job={'job_uid':r['job_uid'],'job_title':r['title'],'company':r['company'],'apply_url':r['url'],'source':r['source'],'description':r['description'],'description_sha256':r['description_sha256'],'fetched_at':r['fetched_at']}; jobs.append(job); import json; json.dump(jobs, open('logs/live_runs/remote-job-agent-live-20261102-001/scraped_jobs_snapshot.json','w'), indent=2); print('Saved', len(jobs), 'jobs')\"")
        sys.exit(1)
    
    print(f"Loading snapshot from {snapshot_path}...")
    with open(snapshot_path) as f:
        jobs = json.load(f)
    
    print(f"Loaded {len(jobs)} jobs ({len(set(j['job_uid'] for j in jobs))} distinct)")
    
    # Deduplicate by job_uid (keep first occurrence)
    seen = set()
    deduped = []
    for j in jobs:
        if j['job_uid'] not in seen:
            seen.add(j['job_uid'])
            deduped.append(j)
    
    print(f"After dedup: {len(deduped)} distinct jobs")
    
    # Run legacy matcher
    print("\nRunning LEGACY matcher...")
    legacy_results = run_legacy_matcher(deduped)
    
    legacy_counts = {}
    for j in legacy_results:
        legacy_counts[j['legacy_decision']] = legacy_counts.get(j['legacy_decision'], 0) + 1
    print(f"  rejected: {legacy_counts.get('rejected', 0)}")
    print(f"  low_match: {legacy_counts.get('low_match', 0)}")
    print(f"  passed: {legacy_counts.get('passed', 0)}")
    
    # Run new matcher
    print("\nRunning NEW matcher...")
    profile = load_new_matcher_profile()
    new_results = run_new_matcher(deduped, profile)
    
    new_counts = {}
    for j in new_results:
        new_counts[j['new_decision']] = new_counts.get(j['new_decision'], 0) + 1
    print(f"  eligible: {new_counts.get('eligible', 0)}")
    print(f"  likely_fit: {new_counts.get('likely_fit', 0)}")
    print(f"  review: {new_counts.get('review', 0)}")
    print(f"  rejected: {new_counts.get('rejected', 0)}")
    
    # Confusion matrix
    print("\nComputing confusion matrix...")
    cm = confusion_matrix(legacy_results, new_results)
    
    # Print matrix
    print("\n" + "="*70)
    print("CONFUSION MATRIX (rows=legacy, cols=new)")
    print("="*70)
    legacy_labels = ['rejected', 'low_match', 'passed']
    new_labels = ['eligible', 'likely_fit', 'review', 'rejected']
    
    # Header
    print(f"{'':>12} |", end="")
    for nl in new_labels:
        print(f" {nl:>12}", end="")
    print()
    print("-" * 70)
    
    for ll in legacy_labels:
        print(f"{ll:>12} |", end="")
        for nl in new_labels:
            count = cm['matrix'][ll][nl]
            print(f" {count:>12}", end="")
        print()
    
    print("-" * 70)
    
    # Per-class agreement
    print("\nPER-CLASS AGREEMENT (legacy as reference, NOT ground truth)")
    print("="*70)
    for ll in legacy_labels:
        pc = cm['per_class'][ll]
        if pc['support'] == 0:
            print(f"  {ll}: No support")
        else:
            print(f"  {ll}: support={pc['support']}, agree={pc['agreement_count']}/{pc['support']} ({pc['agreement_rate']}%)")
            print(f"    Distribution: {pc['distribution']}")
    
    # Directional disagreements (explicitly labelled)
    print("\nDIRECTIONAL DISAGREEMENTS (legacy is production; new is shadow)")
    print("="*70)
    
    print(f"\n1. Legacy REJECTED but New NOT rejected ({len(cm['disagreements']['legacy_rejected_new_not_rejected'])} jobs):")
    for d in cm['disagreements']['legacy_rejected_new_not_rejected'][:10]:
        print(f"   {d['job_uid'][:12]}: {d['title'][:50]} -> New: {d['new_decision']} (reasons: {d['new_reasons']})")
    if len(cm['disagreements']['legacy_rejected_new_not_rejected']) > 10:
        print(f"   ... and {len(cm['disagreements']['legacy_rejected_new_not_rejected']) - 10} more")
    
    print(f"\n2. Legacy LOW_MATCH but New ELIGIBLE/LIKELY_FIT ({len(cm['disagreements']['legacy_low_match_new_eligible'])} jobs):")
    for d in cm['disagreements']['legacy_low_match_new_eligible'][:10]:
        print(f"   {d['job_uid'][:12]}: {d['title'][:50]} -> Legacy score: {d['legacy_score']}, New: {d['new_decision']} (score: {d['new_score']})")
    if len(cm['disagreements']['legacy_low_match_new_eligible']) > 10:
        print(f"   ... and {len(cm['disagreements']['legacy_low_match_new_eligible']) - 10} more")
    
    print(f"\n3. Legacy PASSED but New REVIEW/REJECTED ({len(cm['disagreements']['legacy_passed_new_review_or_rejected'])} jobs):")
    for d in cm['disagreements']['legacy_passed_new_review_or_rejected'][:10]:
        print(f"   {d['job_uid'][:12]}: {d['title'][:50]} -> Legacy score: {d['legacy_score']}, New: {d['new_decision']} (score: {d['new_score']}, reasons: {d['new_reasons']})")
    if len(cm['disagreements']['legacy_passed_new_review_or_rejected']) > 10:
        print(f"   ... and {len(cm['disagreements']['legacy_passed_new_review_or_rejected']) - 10} more")
    
    print(f"\n4. Legacy PASSED & New ELIGIBLE/LIKELY_FIT (aligned) ({len(cm['disagreements']['legacy_passed_new_eligible_likely_fit'])} jobs):")
    for d in cm['disagreements']['legacy_passed_new_eligible_likely_fit'][:10]:
        print(f"   {d['job_uid'][:12]}: {d['title'][:50]} -> Legacy: {d['legacy_score']}, New: {d['new_score']}")
    if len(cm['disagreements']['legacy_passed_new_eligible_likely_fit']) > 10:
        print(f"   ... and {len(cm['disagreements']['legacy_passed_new_eligible_likely_fit']) - 10} more")
    
    # Save detailed results
    output_path = Path("logs/live_runs/remote-job-agent-live-20261102-001/matchers_comparison.json")
    output_data = {
        'legacy_results': [
            {k: v for k, v in j.items() if k in ('job_uid', 'job_title', 'company', 'source', 'legacy_decision', 'legacy_score', 'legacy_reject_reason', 'legacy_match_reason')}
            for j in legacy_results
        ],
        'new_results': [
            {k: v for k, v in j.items() if k in ('job_uid', 'job_title', 'company', 'source', 'new_decision', 'new_score', 'new_review_reasons', 'new_eligibility')}
            for j in new_results
        ],
        'confusion_matrix': cm,
        'summary': {
            'total_jobs': len(deduped),
            'legacy_counts': legacy_counts,
            'new_counts': new_counts,
        }
    }
    
    with open(output_path, 'w') as f:
        json.dump(output_data, f, indent=2)
    
    print(f"\nDetailed results saved to {output_path}")
    print("\nNOTE: 'Agreement' is directional (legacy=production, new=shadow).")
    print("      Legacy is NOT ground truth. Disagreements are NOT errors.")
    print("      Human labels would be needed for accuracy measurement.")


if __name__ == "__main__":
    main()