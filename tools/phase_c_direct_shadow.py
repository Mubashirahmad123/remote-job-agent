#!/usr/bin/env python3
"""Phase C M2: Direct shadow pipeline invocation via run_optional_shadow()."""

import sys
sys.path.insert(0, r'C:\Users\Mubashir1\remote-job-agent')

import os
import json
from pathlib import Path

# Set env var to enable shadow
os.environ['MATCHING_SHADOW_PROFILE'] = str(Path("data/matching_profile.json").absolute())
os.environ['MATCHING_SHADOW_DB'] = str(Path("data/matching_shadow.db").absolute())

from tools.matching_shadow import run_optional_shadow


def load_and_dedup_jobs():
    path = Path("logs/live_runs/remote-job-agent-live-20261102-001/fresh_scrape.json")
    with open(path) as f:
        jobs = json.load(f)
    # Dedup by job_uid or apply_url
    seen = set()
    deduped = []
    for j in jobs:
        uid = j.get('job_uid') or j.get('apply_url') or ''
        if uid and uid not in seen:
            seen.add(uid)
            j = dict(j)
            j['job_uid'] = uid
            j['job_fingerprint'] = uid  # Shadow pipeline requires this
            deduped.append(j)
    return deduped


def main():
    print("Running ACTUAL run_optional_shadow() on fresh scrape...")
    jobs = load_and_dedup_jobs()
    print(f"Loaded {len(jobs)} deduped jobs")
    
    results = run_optional_shadow(jobs)
    print(f"Shadow results: {len(results)} jobs processed")
    
    # Analyze results
    decisions = {}
    eligibility_decisions = {}
    gate_outcomes = {}
    
    for job_id, result in results.items():
        decisions[result.decision] = decisions.get(result.decision, 0) + 1
        eligibility_decisions[result.eligibility.decision] = eligibility_decisions.get(result.eligibility.decision, 0) + 1
        for gate in result.eligibility.gates:
            key = f"{gate.name}:{gate.outcome}"
            gate_outcomes[key] = gate_outcomes.get(key, 0) + 1
    
    print(f"\nFinal decisions (from MatchResult.decision):")
    for k, v in sorted(decisions.items()):
        print(f"  {k}: {v}")
    
    print(f"\nEligibility decisions:")
    for k, v in sorted(eligibility_decisions.items()):
        print(f"  {k}: {v}")
    
    print(f"\nGate outcomes:")
    for k, v in sorted(gate_outcomes.items()):
        print(f"  {k}: {v}")
    
    # Save results
    output = {
        'total_processed': len(results),
        'decisions': decisions,
        'eligibility': eligibility_decisions,
        'gates': gate_outcomes,
        'per_job': {
            job_id: {
                'decision': result.decision,
                'score': result.required.score,
                'review_reasons': list(result.review_reasons),
                'eligibility': result.eligibility.decision,
                'gates': [{'name': g.name, 'outcome': g.outcome, 'reason': g.reason} for g in result.eligibility.gates]
            }
            for job_id, result in results.items()
        }
    }
    
    out_path = Path("logs/live_runs/remote-job-agent-live-20261102-001/phase_c_direct_shadow_results.json")
    with open(out_path, 'w') as f:
        json.dump(output, f, indent=2)
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()