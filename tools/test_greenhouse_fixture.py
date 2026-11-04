#!/usr/bin/env python3
"""Test Greenhouse fill with attachments using local fixture."""

import sys
sys.path.insert(0, r'C:\Users\Mubashir1\remote-job-agent')

import os
from pathlib import Path

os.environ['AUTO_APPLY_PLAYWRIGHT'] = 'true'

from playwright.sync_api import sync_playwright
from agents.auto_applier import _fill_greenhouse_form


def test_greenhouse_attachments():
    """Test Greenhouse fill with resume and cover letter attachments."""
    
    # Path to local fixture
    fixture_url = "https://boards.greenhouse.io/example/jobs/83446"
    
    user_profile = {
        "name": "Mubashir Nazir",
        "email": "test@example.com",
        "phone": "+91-0000000000",
        "linkedin": "https://linkedin.com/in/mubashir-ahmad-13027523b",
        "portfolio": "https://mubashir-portfolio1-gebqzzptl-mubashirs-projects-a83d22b0.vercel.app/",
        "github": "https://github.com/Mubashirahmad123"
    }
    
    resume_path = r"resumes\Senior Backend Engineer_Test Company_2026-11-03_09-29-50.pdf"
    cover_letter = "My interest in the Senior Backend Engineer role at Test Company is immense. With 2.8 impactful years as a Software Engineer at FastBeetle, I've been deeply involved in crafting resilient and performant backend services."
    
    print(f"Testing Greenhouse fill with attachments...")
    print(f"Fixture: {fixture_url}")
    print(f"Resume: {resume_path}")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        
        try:
            result = _fill_greenhouse_form(page, fixture_url, resume_path, cover_letter, user_profile)
            print(f"\nResult: {json.dumps(result, indent=2)}")
            
            # Check attachment verification
            print(f"\n--- Attachment Verification ---")
            print(f"resume_attached: {result.get('resume_attached')}")
            print(f"resume_verify: {result.get('resume_verify')}")
            print(f"resume_dom_confirmed: {result.get('resume_dom_confirmed')}")
            print(f"cover_letter_attached: {result.get('cover_letter_attached')}")
            print(f"cover_letter_pasted: {result.get('cover_letter_pasted')}")
            print(f"cover_letter_verify: {result.get('cover_letter_verify')}")
            print(f"cover_letter_dom_confirmed: {result.get('cover_letter_dom_confirmed')}")
            
            # Take screenshot
            screenshot_dir = Path("screenshots")
            screenshot_dir.mkdir(exist_ok=True)
            from datetime import datetime
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            screenshot_path = screenshot_dir / f"greenhouse_fixture_{ts}_before_submit.png"
            page.screenshot(path=str(screenshot_path), full_page=True)
            print(f"\nScreenshot saved: {screenshot_path}")
            
            return result
            
        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
            return {"error": str(e)}
        finally:
            browser.close()


if __name__ == "__main__":
    import json
    result = test_greenhouse_attachments()
    print(f"\nFinal result: {json.dumps(result, indent=2)}")