#!/usr/bin/env python3
"""Phase C M2: Run both matchers on fresh scrape and compare."""

import sys
sys.path.insert(0, r'C:\Users\Mubashir1\remote-job-agent')

import json
from pathlib import Path

from agents.curator import curate, _should_reject, _get_cv_matcher, _calculate_freshness_boost
from tools.matching_extract import extract_matching_evidence
from tools.matching_policy import CandidatePolicy, JobEvidence, evaluate_eligibility
from tools.matching_score import MatchProfile, Requirement, RequirementsEvidence, score_match
from tools.matching_shadow import load_profile, ensure_evidence, _job_requirements


MIN_SCORE = 30
KEYWORD_WEIGHT = 0.6
SEMANTIC_WEIGHT = 0.4


def run_legacy_matcher(jobs: list[dict]) -> list[dict]:
    matcher = _get_cv_matcher()
    results = []
    for job in jobs:
        j = dict(job)
        should_reject, reject_reason = _should_reject(j)
        if should_reject:
            j["legacy_decision"] = "rejected"
            j["legacy_reject_reason"] = reject_reason
            j["legacy_score"] = 0
            results.append(j)
            continue
        if matcher:
            score_result = matcher.score(j)
            keyword_score = score_result.get("score", 0)
            match_reason = score_result.get("match_reason", "")
        else:
            keyword_score = 0
            match_reason = "No CV matching"
        freshness = _calculate_freshness_boost(j.get("posted_date_iso", ""))
        base_score = keyword_score
        j["legacy_score"] = round(base_score, 1)
        j["legacy_match_reason"] = match_reason
        j["legacy_decision"] = "low_match" if base_score < MIN_SCORE else "passed"
        results.append(j)
    return results


def load_new_matcher_profile() -> MatchProfile:
    return load_profile(Path("data/matching_profile.json"))


def run_new_matcher(jobs: list[dict], profile: MatchProfile) -> list[dict]:
    results = []
    for job in jobs:
        j = dict(job)
        evidence = ensure_evidence(j)
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
        eligibility = evaluate_eligibility(source, profile.policy)
        extracted = evidence.get('requirements') or {}
        requirements = _job_requirements(extracted)
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


def confusion_matrix(legacy_jobs: list[dict], new_jobs: list[dict]) -> dict:
    legacy_labels = ['rejected', 'low_match', 'passed']
    new_labels = ['eligible', 'likely_fit', 'review', 'rejected']
    matrix = {l: {n: 0 for n in new_labels} for l in legacy_labels}
    disagreements = {
        'legacy_rejected_new_not_rejected': [],
        'legacy_low_match_new_eligible': [],
        'legacy_passed_new_review_or_rejected': [],
        'legacy_passed_new_eligible_likely_fit': [],
    }
    new_by_uid = {j['job_uid']: j for j in new_jobs}
    for lj in legacy_jobs:
        uid = lj.get('job_uid', lj.get('apply_url', ''))
        nj = new_by_uid.get(uid)
        if not nj:
            continue
        legacy_dec = lj['legacy_decision']
        new_dec = nj['new_decision']
        matrix[legacy_dec][new_dec] += 1
        if legacy_dec == 'rejected' and new_dec != 'rejected':
            disagreements['legacy_rejected_new_not_rejected'].append({
                'job_uid': uid, 'title': lj.get('job_title', ''), 'new_decision': new_dec,
                'new_reasons': nj.get('new_review_reasons', []), 'legacy_reason': lj.get('legacy_reject_reason', '')
            })
        elif legacy_dec == 'low_match' and new_dec in ('eligible', 'likely_fit'):
            disagreements['legacy_low_match_new_eligible'].append({
                'job_uid': uid, 'title': lj.get('job_title', ''), 'legacy_score': lj.get('legacy_score', 0),
                'new_score': nj.get('new_score'), 'new_decision': new_dec
            })
        elif legacy_dec == 'passed' and new_dec in ('review', 'rejected'):
            disagreements['legacy_passed_new_review_or_rejected'].append({
                'job_uid': uid, 'title': lj.get('job_title', ''), 'legacy_score': lj.get('legacy_score', 0),
                'new_score': nj.get('new_score'), 'new_decision': new_dec, 'new_reasons': nj.get('new_review_reasons', [])
            })
        elif legacy_dec == 'passed' and new_dec in ('eligible', 'likely_fit'):
            disagreements['legacy_passed_new_eligible_likely_fit'].append({
                'job_uid': uid, 'title': lj.get('job_title', ''), 'legacy_score': lj.get('legacy_score', 0),
                'new_score': nj.get('new_score'), 'new_decision': new_dec
            })
    per_class = {}
    for legacy_dec in legacy_labels:
        total = sum(matrix[legacy_dec].values())
        if total == 0:
            per_class[legacy_dec] = {'support': 0, 'agreement_rate': None, 'note': 'No support'}
            continue
        if legacy_dec == 'passed':
            agree_count = matrix[legacy_dec]['eligible'] + matrix[legacy_dec]['likely_fit']
        elif legacy_dec == 'low_match':
            agree_count = matrix[legacy_dec]['review']
        else:
            agree_count = matrix[legacy_dec]['rejected']
        per_class[legacy_dec] = {
            'support': total, 'agreement_count': agree_count,
            'agreement_rate': round(100 * agree_count / total, 1),
            'distribution': matrix[legacy_dec]
        }
    return {
        'matrix': matrix, 'per_class': per_class, 'disagreements': disagreements,
        'total': sum(sum(row.values()) for row in matrix.values())
    }


def main():
    snapshot_path = Path("logs/live_runs/remote-job-agent-live-20261102-001/fresh_scrape.json")
    if not snapshot_path.exists():
        print(f"ERROR: {snapshot_path} not found")
        sys.exit(1)
    with open(snapshot_path) as f:
        jobs = json.load(f)
    print(f"Loaded {len(jobs)} fresh jobs")
    # Dedup by job_uid or apply_url
    seen = set()
    deduped = []
    for j in jobs:
        uid = j.get('job_uid') or j.get('apply_url') or ''
        if uid and uid not in seen:
            seen.add(uid)
            j['job_uid'] = uid  # ensure job_uid for matching
            deduped.append(j)
    print(f"After dedup: {len(deduped)} jobs")
    print("\nRunning LEGACY matcher...")
    legacy_results = run_legacy_matcher(deduped)
    legacy_counts = {}
    for j in legacy_results:
        legacy_counts[j['legacy_decision']] = legacy_counts.get(j['legacy_decision'], 0) + 1
    print(f"  rejected: {legacy_counts.get('rejected', 0)}")
    print(f"  low_match: {legacy_counts.get('low_match', 0)}")
    print(f"  passed: {legacy_counts.get('passed', 0)}")
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
    print("\nComputing confusion matrix...")
    cm = confusion_matrix(legacy_results, new_results)
    print("\n" + "="*70)
    print("CONFUSION MATRIX (rows=legacy, cols=new)")
    print("="*70)
    legacy_labels = ['rejected', 'low_match', 'passed']
    new_labels = ['eligible', 'likely_fit', 'review', 'rejected']
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
    print("\nPER-CLASS AGREEMENT")
    for ll in legacy_labels:
        pc = cm['per_class'][ll]
        if pc['support'] == 0:
            print(f"  {ll}: No support")
        else:
            print(f"  {ll}: support={pc['support']}, agree={pc['agreement_count']}/{pc['support']} ({pc['agreement_rate']}%)")
            print(f"    Distribution: {pc['distribution']}")
    print("\nDIRECTIONAL DISAGREEMENTS")
    print(f"\n1. Legacy REJECTED -> New NOT rejected ({len(cm['disagreements']['legacy_rejected_new_not_rejected'])} jobs):")
    for d in cm['disagreements']['legacy_rejected_new_not_rejected'][:10]:
        print(f"   {d['job_uid'][:12]}: {d['title'][:50]} -> New: {d['new_decision']} (reasons: {d['new_reasons']})")
    print(f"\n2. Legacy LOW_MATCH -> New ELIGIBLE/LIKELY_FIT ({len(cm['disagreements']['legacy_low_match_new_eligible'])} jobs):")
    for d in cm['disagreements']['legacy_low_match_new_eligible'][:10]:
        print(f"   {d['job_uid'][:12]}: {d['title'][:50]} -> Legacy: {d['legacy_score']}, New: {d['new_decision']} (score: {d['new_score']})")
    print(f"\n3. Legacy PASSED -> New REVIEW/REJECTED ({len(cm['disagreements']['legacy_passed_new_review_or_rejected'])} jobs):")
    for d in cm['disagreements']['legacy_passed_new_review_or_rejected'][:10]:
        print(f"   {d['job_uid'][:12]}: {d['title'][:50]} -> Legacy: {d['legacy_score']}, New: {d['new_decision']} (score: {d['new_score']}, reasons: {d['new_reasons']})")
    print(f"\n4. Legacy PASSED & New ELIGIBLE/LIKELY_FIT ({len(cm['disagreements']['legacy_passed_new_eligible_likely_fit'])} jobs):")
    for d in cm['disagreements']['legacy_passed_new_eligible_likely_fit'][:10]:
        print(f"   {d['job_uid'][:12]}: {d['title'][:50]} -> Legacy: {d['legacy_score']}, New: {d['new_score']}")
    output_path = Path("logs/live_runs/remote-job-agent-live-20261102-001/phase_c_m2_comparison.json")
    output_data = {
        'legacy_results': [{k: v for k, v in j.items() if k in ('job_uid', 'job_title', 'company', 'source', 'legacy_decision', 'legacy_score', 'legacy_reject_reason', 'legacy_match_reason')} for j in legacy_results],
        'new_results': [{k: v for k, v in j.items() if k in ('job_uid', 'job_title', 'company', 'source', 'new_decision', 'new_score', 'new_review_reasons', 'new_eligibility')} for j in new_results],
        'confusion_matrix': cm,
        'summary': {'total_jobs': len(deduped), 'legacy_counts': legacy_counts, 'new_counts': new_counts}
    }
    with open(output_path, 'w') as f:
        json.dump(output_data, f, indent=2)
    print(f"\nDetailed results saved to {output_path}")
    print("\nNOTE: 'Agreement' is directional (legacy=production, new=shadow). Legacy is NOT ground truth.")


if __name__ == "__main__":
    main()