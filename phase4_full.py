"""Phase 4: Compare legacy vs new matching engine using LEDGER job_texts."""
import csv
import sqlite3
import sys
from pathlib import Path
from dataclasses import fields as dc_fields
from collections import Counter
from tools.matching_extract import extract_matching_evidence
from tools.matching_policy import CandidatePolicy, JobEvidence, evaluate_eligibility
from tools.matching_score import MatchProfile, Requirement, RequirementsEvidence, score_match
from tools.matching_shadow import load_profile, _string_set

def safe_print(s):
    sys.stdout.write(s.encode('cp1252', errors='replace').decode('cp1252') + '\n')

profile = load_profile(Path('data/matching_profile.json'))

# Load job_texts from the ledger
con = sqlite3.connect('data/pipeline_ledger.db')
latest_run = con.execute("SELECT DISTINCT run_id FROM stage_events ORDER BY seq DESC LIMIT 1").fetchone()[0]
safe_print(f"Using ledger run: {latest_run}")

# Get all job texts with their terminal stage
jobs_data = con.execute(
    """SELECT jt.job_uid, jt.title, jt.company, jt.url, jt.source, jt.description,
                   jt.description_sha256
       FROM job_texts jt
       WHERE jt.run_id=?
       ORDER BY jt.seq""",
    (latest_run,)).fetchall()

print(f"Total jobs in ledger: {len(jobs_data)}")

# Get terminal stage for each job_uid
terminal_stages = {}
for row in con.execute(
    """SELECT job_uid, stage FROM stage_events
       WHERE run_id=? AND stage IN (
           'dev_filter_drop', 'country_drop', 'date_drop',
           'dedup_missing_url', 'dedup_url_dup', 'dedup_cross_board', 'dedup_fingerprint',
           'legacy_rejected', 'legacy_low_match', 'legacy_passed')
       ORDER BY seq""",
    (latest_run,)).fetchall():
    terminal_stages[row[0]] = row[1]

con.close()

print(f"Jobs with terminal stage: {len(terminal_stages)}")

results = []
for job_uid, title, company, url, source, description, sha in jobs_data:
    terminal = terminal_stages.get(job_uid, 'unknown')

    # LEGACY DECISION based on terminal stage
    if terminal == 'legacy_passed':
        legacy_decision = 'eligible'
    elif terminal == 'legacy_rejected':
        legacy_decision = 'rejected'
    elif terminal == 'legacy_low_match':
        legacy_decision = 'review'
    elif terminal in ('dev_filter_drop', 'country_drop', 'date_drop',
                      'dedup_missing_url', 'dedup_url_dup', 'dedup_cross_board',
                      'dedup_fingerprint'):
        legacy_decision = 'rejected'
    else:
        legacy_decision = 'unknown'

    # NEW ENGINE evaluation
    evidence = extract_matching_evidence({
        'job_title': title or '',
        'timezone': '',
        'description': description or '',
        'apply_url': url or '',
        'source': source or '',
        'job_fingerprint': job_uid,
    })

    job_fields = {f.name for f in dc_fields(JobEvidence)} - {'title', 'description'}
    kwargs = {k: v for k, v in evidence.items() if k in job_fields}
    for k in ('allowed_work_locations', 'responsibilities', 'role_hints'):
        if k in kwargs and kwargs[k] is not None:
            kwargs[k] = frozenset(kwargs[k])
    kwargs.setdefault('work_mode', 'unknown')
    source_job = JobEvidence(title or '', description or '', **kwargs)

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

    result = score_match(source_job, profile, requirements)

    results.append({
        'job_fingerprint': job_uid,
        'job_title': title or '',
        'company': company or '',
        'source': source or '',
        'legacy_score': None,
        'legacy_decision': legacy_decision,
        'legacy_stage': terminal,
        'new_decision': result.decision,
        'agreement': (legacy_decision == 'eligible') == (result.decision == 'eligible'),
        'required_score': result.required.score,
        'review_reasons': '|'.join(result.review_reasons),
        'location_gate': '|'.join(f"{g.name}={g.outcome}:{g.reason}" for g in result.eligibility.gates if g.name == 'location'),
        'role_gate': '|'.join(f"{g.name}={g.outcome}:{g.reason}" for g in result.eligibility.gates if g.name == 'role'),
        'seniority_gate': '|'.join(f"{g.name}={g.outcome}:{g.reason}" for g in result.eligibility.gates if g.name == 'seniority'),
        'description': description or '',
    })

# Write CSV
with open('phase4_comparison_full.csv', 'w', newline='', encoding='utf-8') as f:
    writer = csv.DictWriter(f, fieldnames=[
        'job_fingerprint', 'job_title', 'company', 'source',
        'legacy_score', 'legacy_decision', 'legacy_stage',
        'new_decision', 'agreement',
        'required_score', 'review_reasons',
        'location_gate', 'role_gate', 'seniority_gate',
        'description',
    ])
    writer.writeheader()
    writer.writerows(results)

safe_print(f"\nResults written to phase4_comparison_full.csv ({len(results)} jobs)")

# Summary counts
legacy_eligible = sum(1 for r in results if r['legacy_decision'] == 'eligible')
legacy_rejected = sum(1 for r in results if r['legacy_decision'] == 'rejected')
legacy_review = sum(1 for r in results if r['legacy_decision'] == 'review')
legacy_unknown = sum(1 for r in results if r['legacy_decision'] == 'unknown')
new_eligible = sum(1 for r in results if r['new_decision'] == 'eligible')
new_rejected = sum(1 for r in results if r['new_decision'] == 'rejected')
new_review = sum(1 for r in results if r['new_decision'] == 'review')
new_likely_fit = sum(1 for r in results if r['new_decision'] == 'likely_fit')

safe_print(f"\n=== SUMMARY ===")
safe_print(f"Total jobs: {len(results)}")
safe_print(f"Legacy: eligible={legacy_eligible}, review={legacy_review}, rejected={legacy_rejected}, unknown={legacy_unknown}")
safe_print(f"New:    eligible={new_eligible}, review={new_review}, rejected={new_rejected}, likely_fit={new_likely_fit}")
safe_print(f"Agreement: {sum(1 for r in results if r['agreement'])} jobs")

safe_print("")
safe_print("=== Legacy eligible but new rejects/reviews ===")
for r in results:
    if r['legacy_decision'] == 'eligible' and r['new_decision'] in ('rejected', 'review'):
        safe_print(f"  {r['job_title'][:60]:<60} | legacy_stage={r['legacy_stage']} | new={r['new_decision']} | reasons={r['review_reasons'][:80]}")

safe_print("")
safe_print("=== Legacy rejected but new review/likely_fit ===")
for r in results:
    if r['legacy_decision'] == 'rejected' and r['new_decision'] in ('review', 'likely_fit'):
        safe_print(f"  {r['job_title'][:60]:<60} | new={r['new_decision']} | reasons={r['review_reasons'][:80]}")

safe_print("")
safe_print("=== Review reasons ranked ===")
reason_counter = Counter()
for r in results:
    for reason in r['review_reasons'].split('|'):
        if reason:
            reason_counter[reason] += 1
for reason, count in reason_counter.most_common():
    safe_print(f"  {reason}: {count}")
