"""
scratch/test_pdf_layout.py
Verification script for testing ATS 1-page CV and Cover Letter layout engine.
"""

import os
import sys
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from tools.resume_generator import save_resume_pdf, _generate_fallback_resume
from agents.gemini_tools import save_cover_letter_pdf
import pdfplumber

def test_cv_pdf_generation():
    print("Testing CV PDF Generation...")
    sample_job = {
        "job_title": "Full Stack Developer",
        "company": "TechCorp Solutions",
        "tech_stack": "React, Node.js, Python, PostgreSQL, AWS",
        "summary": "Building scalable microservices and responsive web applications.",
        "apply_url": "https://example.com/apply"
    }

    # Generate fallback resume markdown
    cv_md = _generate_fallback_resume(sample_job, cv_profile={
        "name": "Mubashir Ahmad",
        "email": "mubashir@example.com",
        "phone": "+1 (555) 019-2831",
        "location": "Lahore, Pakistan",
        "linkedin": "linkedin.com/in/mubashir",
        "github": "github.com/Mubashirahmad123",
        "skills": ["Python", "React", "Node.js", "PostgreSQL", "Docker", "AWS", "FastAPI"],
        "experience": [
            {
                "title": "Senior Full Stack Engineer",
                "company": "Innovate Tech",
                "duration": "2023 - Present",
                "description": "Architected microservices architecture serving 100k+ daily users using FastAPI and React."
            },
            {
                "title": "Software Developer",
                "company": "DevStudio",
                "duration": "2021 - 2023",
                "description": "Built REST APIs and optimized SQL database query performance by 40%."
            }
        ],
        "education": [
            {
                "degree": "BS in Computer Science",
                "institution": "University of Engineering & Technology",
                "year": "2021"
            }
        ]
    })

    pdf_path = save_resume_pdf(cv_md, sample_job["job_title"], sample_job["company"], folder="scratch/resumes")
    assert pdf_path and os.path.exists(pdf_path), "Resume PDF file not created"

    with pdfplumber.open(pdf_path) as pdf:
        num_pages = len(pdf.pages)
        print(f"📄 Resume PDF generated. Page count: {num_pages}")
        assert num_pages == 1, f"Resume PDF page count is {num_pages}, expected 1"
        print("✅ CV PDF 1-page check passed!")

def test_cover_letter_pdf_generation():
    print("\nTesting Cover Letter PDF Generation...")
    sample_letter = """Dear Hiring Manager,

I am writing to express my strong interest in the Full Stack Developer role at TechCorp Solutions. With over 3 years of hands-on experience developing web applications using React, Node.js, and Python, I am confident in my ability to deliver immediate value to your engineering team.

In my previous role at Innovate Tech, I architected high-throughput microservices using FastAPI and optimized frontend performance in React applications. My expertise in PostgreSQL and cloud deployment aligns closely with your tech stack requirements.

I am eager to contribute to TechCorp Solutions' mission and look forward to discussing how my background fits your team's needs. Thank you for your time and consideration.

Best regards,
Mubashir Ahmad"""

    pdf_path = save_cover_letter_pdf(sample_letter, "Full Stack Developer", "TechCorp Solutions", folder="scratch/cover_letters")
    assert pdf_path and os.path.exists(pdf_path), "Cover Letter PDF file not created"

    with pdfplumber.open(pdf_path) as pdf:
        num_pages = len(pdf.pages)
        print(f"📄 Cover Letter PDF generated. Page count: {num_pages}")
        assert num_pages == 1, f"Cover Letter PDF page count is {num_pages}, expected 1"
        print("✅ Cover Letter PDF 1-page check passed!")

if __name__ == "__main__":
    test_cv_pdf_generation()
    test_cover_letter_pdf_generation()
    print("\n🎉 ALL PDF LAYOUT TESTS PASSED PERFECTLY!")
