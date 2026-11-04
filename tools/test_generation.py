import sys
import io
sys.path.insert(0, r'C:\Users\Mubashir1\remote-job-agent')

# Force UTF-8 encoding for stdout
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from agents.gemini_tools import generate_cover_letter
from tools.resume_generator import generate_resume_for_job

# Test cover letter generation
job = {
    'job_title': 'Senior Backend Engineer',
    'company': 'Test Company',
    'description': 'We are looking for a Senior Backend Engineer with 5+ years of experience in Python, PostgreSQL, and AWS. You will build scalable APIs and work with microservices architecture.',
    'apply_url': 'https://example.com/job/1'
}

print('Testing cover letter generation...')
cover = generate_cover_letter(job['job_title'], job['company'], job['description'])
print(f'Cover letter generated: {len(cover)} chars')
print(cover[:500])
print()

# Test resume generation
print('Testing resume generation...')
result = generate_resume_for_job(job)
print(f'Resume generation result: {result}')