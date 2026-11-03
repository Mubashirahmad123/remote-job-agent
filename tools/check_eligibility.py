import json
with open('logs/live_runs/remote-job-agent-live-20261102-001/phase_c_direct_shadow_results_v2.json') as f:
    data = json.load(f)

eligible_but_review = []
for job_id, job in data['per_job'].items():
    if job['eligibility'] == 'eligible' and job['decision'] == 'review':
        eligible_but_review.append((job_id, job))

print(f'Jobs with eligibility=eligible but final=review: {len(eligible_but_review)}')
for jid, j in eligible_but_review:
    print(f'  job_id: {jid}')
    print(f'  review_reasons: {j["review_reasons"]}')
    print(f'  score: {j["score"]}')
    print()