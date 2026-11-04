import json
with open('logs/live_runs/remote-job-agent-live-20261102-001/phase_c_direct_shadow_results_v2.json') as f:
    data = json.load(f)

eligible_jobs = []
for job_id, job in data['per_job'].items():
    if job['eligibility'] == 'eligible':
        eligible_jobs.append((job_id, job))

print(f'Jobs with eligibility=eligible: {len(eligible_jobs)}')
for jid, j in eligible_jobs:
    print(f'  job_id: {jid}')
    print(f'  final decision: {j["decision"]}')
    print(f'  review_reasons: {j["review_reasons"]}')
    print(f'  score: {j["score"]}')
    print(f'  gates: {[(g["name"], g["outcome"], g["reason"]) for g in j["gates"]]}')
    print()