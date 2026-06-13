import json
import os

import google.generativeai as genai


def score_job(job: dict, cv_profile: dict) -> tuple[int, str]:
    """Score a job from 0 to 100 against the candidate CV profile."""
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    model = genai.GenerativeModel("gemini-2.0-flash")

    prompt = f"""
Score this job listing from 0-100 based on fit with this candidate.

CANDIDATE:
- Skills: {', '.join(cv_profile.get('skills', []))}
- Frameworks: {', '.join(cv_profile.get('frameworks', []))}
- Experience: {cv_profile.get('years_experience', 0)} years
- Seniority: {cv_profile.get('seniority', 'mid')}
- Looking for: {', '.join(cv_profile.get('preferred_titles', []))}

JOB:
- Title: {job.get('job_title', '')}
- Company: {job.get('company', '')}
- Tech Stack: {job.get('tech_stack', '')}
- Summary: {job.get('summary', '')[:400]}

Scoring:
- 90-100: Perfect match
- 70-89: Good match
- 50-69: Partial match
- 0-49: Poor match or too senior

Return ONLY JSON: {{"score": 85, "reason": "Matches Node.js, React, mid-level remote"}}
"""
    response = model.generate_content(prompt)
    raw = response.text.replace("```json", "").replace("```", "").strip()
    result = json.loads(raw)
    return int(result["score"]), result["reason"]
