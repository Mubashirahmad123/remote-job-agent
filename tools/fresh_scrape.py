import sys
sys.path.insert(0, r'C:\Users\Mubashir1\remote-job-agent')

from agents.scrapper import scrape_all
import json

jobs = scrape_all()
print('Total jobs scraped:', len(jobs))
for j in jobs[:5]:
    title = j.get('job_title', 'N/A')[:50]
    company = j.get('company', 'N/A')[:30]
    source = j.get('source', 'N/A')
    print(' ', title, 'at', company, 'from', source)

with open('logs/live_runs/remote-job-agent-live-20261102-001/fresh_scrape.json', 'w') as f:
    json.dump(jobs, f, indent=2)
print('Saved to fresh_scrape.json')