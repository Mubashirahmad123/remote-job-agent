import sys
sys.path.insert(0, r'C:\Users\Mubashir1\remote-job-agent')

import os
from pathlib import Path
os.environ['AUTO_APPLY_PLAYWRIGHT'] = 'true'

from playwright.sync_api import sync_playwright
from agents.auto_applier import _fill_greenhouse_form

# Test Greenhouse fill with a real Greenhouse test URL
GREENHOUSE_TEST_URL = "https://boards.greenhouse.io/example/jobs/83446"

user_profile = {
    "name": "Mubashir Ahmad",
    "email": "test@example.com",
    "phone": "+1-555-123-4567",
    "linkedin": "https://linkedin.com/in/test",
    "portfolio": "https://github.com/test"
}

resume_path = "resumes/Senior Backend Engineer_Test Company_2026-11-03_09-29-50.pdf"
cover_letter = "Test cover letter content for Greenhouse testing."

print(f"Testing Greenhouse fill with URL: {GREENHOUSE_TEST_URL}")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()
    
    try:
        result = _fill_greenhouse_form(page, GREENHOUSE_TEST_URL, resume_path, cover_letter, user_profile)
        print(f"Result: {result}")
        
        # Take a screenshot before submit (as per the function)
        screenshot_dir = Path("screenshots")
        screenshot_dir.mkdir(exist_ok=True)
        from datetime import datetime
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        screenshot_path = screenshot_dir / f"greenhouse_{ts}_before_submit.png"
        page.screenshot(path=str(screenshot_path), full_page=True)
        print(f"Screenshot saved to: {screenshot_path}")
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        browser.close()