"""Phase 4: Compare legacy vs new matching engine on ALL scored jobs."""
import json
import csv
import os
from pathlib import Path
from dataclasses import fields as dc_fields
from collections import Counter

from tools.matching_extract import extract_matching_evidence
from tools.matching_policy import CandidatePolicy, JobEvidence, evaluate_eligibility
from tools.matching_score import MatchProfile, Requirement, RequirementsEvidence, score_match
from tools.matching_shadow import load_profile, _string_set

profile = load_profile(Path('data/matching_profile.json'))

# Load scraped jobs
scrape_file = 'scraped_jobs_fresh.json'
if not os.path.exists(scrape_file):
    scrape_file = 'scraped_jobs_fast.json'
    if not os.path.exists(scrape_file):
        print("ERROR: No scraped jobs file found. Run measure_fast_boards.py first.")
        exit(1)

with open(scrape_file, 'r', encoding='utf-8') as f:
    jobs = json.load(f)

print(f"Phase 4: Running new matching engine on {len(jobs)} scraped jobs\n")

results = []
for job in jobs:
    evidence = extract_matching_evidence(job)
    job_fields = {f.name for f in dc_fields(JobEvidence)} - {'title', 'description'}
    kwargs = {k: v for k, v in evidence.items() if k in job_fields}
    for k in ('allowed_work_locations', 'responsibilities', 'role_hints'):
        if k in kwargs and kwargs[k] is not None:
            kwargs[k] = frozenset(kwargs[k])
    kwargs.setdefault('work_mode', 'unknown')
    description = job.get('description') or job.get('summary') or None
    source = JobEvidence(job.get('job_title') or '', description, **kwargs)
    extracted = evidence.get('requirements') or {}

    def groups(name):
        return tuple(Requirement(_string_set(r['alternatives'], 'alternatives'), r['evidence'],
                                 r.get('weight', 1), r.get('essential', False),
                                 r.get('type', 'technology'))
                    for r in extracted.get(name, []))
    requirements = RequirementsEvidence(
        groups('required') if 'required' in extracted else None,
        groups('preferred'), extracted.get('complete', False),
        extracted.get('extractor_version', 'unextracted-v1'))

    result = score_match(source, profile, requirements)
    gates = [(g.name, g.outcome, g.reason) for g in result.eligibility.gates]

    # Legacy decision: match_score >= 70 → eligible, otherwise review/rejected
    legacy_score = job.get('match_score', 0) or 0
    legacy_decision = 'eligible' if legacy_score >= 70 else ('review' if legacy_score > 0 else 'rejected')

    results.append({
        'job_fingerprint': job.get('job_fingerprint', ''),
        'job_title': job.get('job_title', ''),
        'company': job.get('company', ''),
        'source': job.get('source', ''),
        'legacy_score': legacy_score,
        'legacy_decision': legacy_decision,
        'new_decision': result.decision,
        'agreement': (legacy_decision == 'eligible') == (result.decision == 'eligible'),
        'required_score': result.required.score,
        'review_reasons': '|'.join(result.review_reasons),
        'location_gate': '|'.join(f"{g.name}={g.outcome}:{g.reason}" for g in result.eligibility.gates if g.name == 'location'),
        'role_gate': '|'.join(f"{g.name}={g.outcome}:{g.reason}" for g in result.eligibility.gates if g.name == 'role'),
        'seniority_gate': '|'.join(f"{g.name}={g.outcome}:{g.reason}" for g in result.eligibility.gates if g.name == 'seniority'),
    })

# Write CSV
with open('phase4_comparison_full.csv', 'w', newline='', encoding='utf-8') as f:
    writer = csv.DictWriter(f, fieldnames=[
        'job_fingerprint', 'job_title', 'company', 'source',
        'legacy_score', 'legacy_decision', 'new_decision', 'agreement',
        'required_score', 'review_reasons',
        'location_gate', 'role_gate', 'seniority_gate',
    ])
    writer.writeheader()
    writer.writerows(results)

print(f"Results written to phase4_comparison_full.csv ({len(results)} jobs)")

# Summary counts
legacy_eligible = sum(1 for r in results if r['legacy_decision'] == 'eligible')
legacy_rejected = sum(1 for r in results if r['legacy_decision'] == 'rejected')
legacy_review = sum(1 for r in results if r['legacy_decision'] == 'review')
new_eligible = sum(1 for r in results if r['new_decision'] == 'eligible')
new_rejected = sum(1 for r in results if r['new_decision'] == 'rejected')
new_review = sum(1 for r in results if r['new_decision'] == 'review')
new_likely_fit = sum(1 for r in results if r['new_decision'] == 'likely_fit')

print()
print("=== SUMMARY ===")
print(f"Total jobs: {len(results)}")
print(f"Legacy: eligible={legacy_eligible}, review={legacy_review}, rejected={legacy_rejected}")
print(f"New:    eligible={new_eligible}, review={new_review}, rejected={new_rejected}, likely_fit={new_likely_fit}")
print(f"Agreement: {sum(1 for r in results if r['agreement'])} jobs")

print()
print("=== Legacy eligible but new rejects/reviews (legacy false positives) ===")
for r in results:
    if r['legacy_decision'] == 'eligible' and r['new_decision'] in ('rejected', 'review'):
        print(f"  {r['job_title'][:60]:<60} | legacy_score={r['legacy_score']} | new={r['new_decision']} | reasons={r['review_reasons'][:80]}")

print()
print("=== Legacy rejected but new review/likely_fit (legacy false negatives) ===")
for r in results:
    if r['legacy_decision'] == 'rejected' and r['new_decision'] in ('review', 'likely_fit'):
        print(f"  {r['job_title'][:60]:<60} | new={r['new_decision']} | reasons={r['review_reasons'][:80]}")

print()
print("=== Review reasons ranked ===")
reason_counter = Counter()
for r in results:
    for reason in r['review_reasons'].split('|'):
        if reason:
            reason_counter[reason] += 1
for reason, count in reason_counter.most_common():
    print(f"  {reason}: {count}")
