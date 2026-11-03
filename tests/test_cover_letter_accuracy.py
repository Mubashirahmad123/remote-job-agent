#!/usr/bin/env python3
"""Regression test: Cover letter must not invent experience years."""

import sys
sys.path.insert(0, r'C:\Users\Mubashir1\remote-job-agent')

import re
import json
from agents.gemini_tools import generate_cover_letter
from tools.cv_parser import parse_cv


def parse_experience_years(cv_profile: dict) -> float:
    """Calculate total experience years from CV profile, handling overlaps."""
    experience = cv_profile.get("experience", [])
    if not experience:
        return 0.0
    
    intervals = []
    for exp in experience:
        duration = exp.get("duration", "")
        # Parse "Aug. 2024 – Apr. 2026" format
        match = re.search(r'([A-Za-z]+)\.\s*(\d{4})\s*[–-]\s*([A-Za-z]+)\.\s*(\d{4})', duration)
        if match:
            start_month, start_year, end_month, end_year = match.groups()
            start = int(start_year) + (["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"].index(start_month[:3]) / 12)
            end = int(end_year) + (["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"].index(end_month[:3]) / 12)
            intervals.append((start, end))
    
    # Merge overlapping intervals
    intervals.sort()
    merged = []
    for start, end in intervals:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    
    total_years = sum(end - start for start, end in merged)
    return round(total_years, 1)


def extract_years_claims(text: str) -> list[float]:
    """Extract all 'X years' / 'X+ years' claims from text."""
    claims = []
    # Match "X years", "X+ years", "X years experience", etc.
    for match in re.finditer(r'(\d+(?:\.\d+)?)\+?\s*years?', text, re.IGNORECASE):
        claims.append(float(match.group(1)))
    # Match written-out numbers: "five years", "five+ years", etc.
    word_to_num = {
        'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5,
        'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10
    }
    for word, num in word_to_num.items():
        if re.search(rf'\b{word}\+?\s*years?', text, re.IGNORECASE):
            claims.append(float(num))
    return claims


def test_cover_letter_experience_accuracy():
    """Test that cover letter doesn't invent experience years."""
    # Load actual CV profile
    cv_path = "my_cv.pdf"
    cv_profile = parse_cv(cv_path)
    
    actual_years = parse_experience_years(cv_profile)
    print(f"Actual CV experience: {actual_years} years")
    print(f"Profile years_experience field: {cv_profile.get('years_experience')}")
    
    # Generate cover letter for a test job
    job = {
        'job_title': 'Senior Backend Engineer',
        'company': 'Test Company',
        'description': 'We are looking for a Senior Backend Engineer with 5+ years of experience in Python, PostgreSQL, and AWS.',
        'apply_url': 'https://example.com/job/1'
    }
    
    cover_letter = generate_cover_letter(
        job['job_title'], 
        job['company'], 
        job['description']
    )
    
    print("\n--- Generated Cover Letter ---")
    print(cover_letter)
    
    # Extract claims
    claims = extract_years_claims(cover_letter)
    print(f"\nExperience claims found: {claims}")
    
    # Verify no claim exceeds actual experience
    max_claim = max(claims) if claims else 0
    tolerance = 0.5  # Allow small rounding differences
    
    assert max_claim <= actual_years + tolerance, \
        f"Cover letter claims {max_claim} years but CV shows {actual_years} years"
    print(f"\n✅ PASS: All claims ({max_claim} max) within actual experience ({actual_years})")


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    test_cover_letter_experience_accuracy()