"""
agents/auto_applier.py
Auto-apply agent for high-match jobs.

TWO MODES:
1. SIMPLE (default): Generate resume + cover letter → open browser → track in sheet
2. PLAYWRIGHT (optional): Auto-fill forms for Greenhouse/Lever with screenshots

Usage:
    python main.py apply                    # Simple mode
    AUTO_APPLY_PLAYWRIGHT=true python main.py apply   # Playwright mode
"""

import os
import json
import webbrowser
import re
import time
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from typing import Optional, Dict, List

load_dotenv()

# =============================================================================
# CONFIGURATION
# =============================================================================

AUTO_APPLY_ENABLED = os.getenv("AUTO_APPLY_ENABLED", "false").lower() == "true"
AUTO_APPLY_THRESHOLD = int(os.getenv("AUTO_APPLY_THRESHOLD", "70"))
AUTO_APPLY_LIMIT = int(os.getenv("AUTO_APPLY_LIMIT", "5"))
AUTO_APPLY_PLAYWRIGHT = os.getenv("AUTO_APPLY_PLAYWRIGHT", "false").lower() == "true"
AUTO_APPLY_CONFIRM = os.getenv("AUTO_APPLY_CONFIRM", "false").lower() == "true"

APPLICANT_NAME = os.getenv("APPLICANT_NAME", "Mubashir")
APPLICANT_EMAIL = os.getenv("APPLICANT_EMAIL", "")
APPLICANT_PHONE = os.getenv("APPLICANT_PHONE", "")
APPLICANT_LINKEDIN = os.getenv("APPLICANT_LINKEDIN", "")
APPLICANT_PORTFOLIO = os.getenv("APPLICANT_PORTFOLIO", "")
APPLICANT_GITHUB = os.getenv("APPLICANT_GITHUB", "")


# =============================================================================
# ATS PLATFORM DETECTION (for Playwright mode)
# =============================================================================

def detect_ats_platform(url: str) -> str:
    """Detect the application platform from the job URL."""
    url_lower = url.lower()
    
    if "boards.greenhouse.io" in url_lower or "greenhouse.io" in url_lower:
        return "greenhouse"
    if "jobs.lever.co" in url_lower or "lever.co" in url_lower:
        return "lever"
    if "myworkdayjobs.com" in url_lower or "workday.com" in url_lower:
        return "workday"
    if "apply.workable.com" in url_lower:
        return "workable"
    if "jobs.ashbyhq.com" in url_lower:
        return "ashby"
    if "breezy.hr" in url_lower:
        return "breezy"
    
    return "unknown"


# =============================================================================
# PLAYWRIGHT SETUP (lazy import)
# =============================================================================

def _get_playwright():
    try:
        from playwright.sync_api import sync_playwright
        return sync_playwright
    except ImportError:
        return None


# =============================================================================
# GREENHOUSE FORM FILLER
# =============================================================================

def _fill_greenhouse_form(page, job_url: str, resume_path: Optional[str], 
                          cover_letter: str, user_profile: Dict) -> Dict:
    """Fill Greenhouse application form."""
    result = {"status": "unknown", "screenshot_path": None, "error": None}
    
    try:
        print(f"  🌐 Navigating to: {job_url}")
        page.goto(job_url, wait_until="networkidle", timeout=30000)
        page.wait_for_selector("#application-form, .application-form, form", timeout=10000)
        
        # Screenshot dir
        screenshot_dir = "screenshots"
        os.makedirs(screenshot_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Fill fields
        fields = {
            "name": ("input[name='name'], input#first_name, input[name='first_name']", user_profile.get("name", APPLICANT_NAME)),
            "email": ("input[type='email'], input[name='email']", user_profile.get("email", APPLICANT_EMAIL)),
            "phone": ("input[type='tel'], input[name='phone']", user_profile.get("phone", APPLICANT_PHONE)),
            "linkedin": ("input[name*='linkedin'], input[id*='linkedin']", user_profile.get("linkedin", APPLICANT_LINKEDIN)),
            "portfolio": ("input[name*='website'], input[name*='portfolio']", user_profile.get("portfolio", APPLICANT_PORTFOLIO)),
        }
        
        for field_name, (selector, value) in fields.items():
            try:
                field = page.locator(selector).first
                if field.count() > 0 and value:
                    field.fill(value)
                    print(f"    ✅ Filled {field_name}")
            except Exception as e:
                print(f"    ⚠️ {field_name} field: {e}")
        
        # Resume upload
        if resume_path and os.path.exists(resume_path):
            try:
                file_input = page.locator("input[type='file'][name*='resume'], input[type='file'][name*='cv']").first
                if file_input.count() > 0:
                    file_input.set_input_files(resume_path)
                    print(f"    ✅ Resume uploaded")
            except Exception as e:
                print(f"    ⚠️ Resume upload: {e}")
        
        # Cover letter
        if cover_letter:
            try:
                cl_field = page.locator("textarea[name*='cover'], textarea[name*='letter'], textarea[name*='message']").first
                if cl_field.count() > 0:
                    cl_field.fill(cover_letter)
                    print(f"    ✅ Cover letter pasted")
            except Exception as e:
                print(f"    ⚠️ Cover letter field: {e}")
        
        # Screenshot before submit
        screenshot_path = f"{screenshot_dir}/greenhouse_{ts}_before_submit.png"
        page.screenshot(path=screenshot_path, full_page=True)
        result["screenshot_path"] = screenshot_path
        print(f"    📸 Screenshot: {screenshot_path}")
        
        # Submit logic
        submit_btn = page.locator("input[type='submit'], button[type='submit'], #submit_app").first
        if submit_btn.count() > 0:
            if AUTO_APPLY_CONFIRM:
                print(f"    🚀 Auto-submitting...")
                submit_btn.click()
                time.sleep(3)
                result["status"] = "submitted"
            else:
                print(f"    ⏸️  Form filled. Set AUTO_APPLY_CONFIRM=true to submit.")
                result["status"] = "filled_ready"
        else:
            result["status"] = "custom_questions"
            
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        print(f"    ❌ Error: {e}")
    
    return result


# =============================================================================
# LEVER FORM FILLER
# =============================================================================

def _fill_lever_form(page, job_url: str, resume_path: Optional[str],
                     cover_letter: str, user_profile: Dict) -> Dict:
    """Fill Lever application form."""
    result = {"status": "unknown", "screenshot_path": None, "error": None}
    
    try:
        print(f"  🌐 Navigating to: {job_url}")
        page.goto(job_url, wait_until="networkidle", timeout=30000)
        page.wait_for_selector(".application-form, form", timeout=10000)
        
        screenshot_dir = "screenshots"
        os.makedirs(screenshot_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Name (first/last)
        try:
            first = page.locator("input[name='firstName'], input[placeholder*='First']").first
            if first.count() > 0:
                name_parts = user_profile.get("name", APPLICANT_NAME).split()
                first.fill(name_parts[0] if name_parts else APPLICANT_NAME)
                
                last = page.locator("input[name='lastName'], input[placeholder*='Last']").first
                if last.count() > 0 and len(name_parts) > 1:
                    last.fill(" ".join(name_parts[1:]))
        except Exception as e:
            print(f"    ⚠️ Name: {e}")
        
        # Email, phone, linkedin, portfolio
        fields = {
            "email": ("input[type='email']", user_profile.get("email", APPLICANT_EMAIL)),
            "phone": ("input[type='tel']", user_profile.get("phone", APPLICANT_PHONE)),
            "linkedin": ("input[name*='linkedin']", user_profile.get("linkedin", APPLICANT_LINKEDIN)),
            "portfolio": ("input[name*='portfolio'], input[name*='website']", user_profile.get("portfolio", APPLICANT_PORTFOLIO)),
        }
        
        for field_name, (selector, value) in fields.items():
            try:
                field = page.locator(selector).first
                if field.count() > 0 and value:
                    field.fill(value)
            except Exception as e:
                print(f"    ⚠️ {field_name}: {e}")
        
        # Resume upload
        if resume_path and os.path.exists(resume_path):
            try:
                file_input = page.locator("input[type='file']").first
                if file_input.count() > 0:
                    file_input.set_input_files(resume_path)
                    print(f"    ✅ Resume uploaded")
            except Exception as e:
                print(f"    ⚠️ Resume upload: {e}")
        
        # Cover letter
        if cover_letter:
            try:
                cl_field = page.locator("textarea[name*='cover'], textarea[placeholder*='cover']").first
                if cl_field.count() > 0:
                    cl_field.fill(cover_letter)
                    print(f"    ✅ Cover letter pasted")
            except Exception as e:
                print(f"    ⚠️ Cover letter: {e}")
        
        # Screenshot
        screenshot_path = f"{screenshot_dir}/lever_{ts}_before_submit.png"
        page.screenshot(path=screenshot_path, full_page=True)
        result["screenshot_path"] = screenshot_path
        print(f"    📸 Screenshot: {screenshot_path}")
        
        # Submit
        submit_btn = page.locator("button[type='submit'], .postings-btn").first
        if submit_btn.count() > 0:
            if AUTO_APPLY_CONFIRM:
                print(f"    🚀 Auto-submitting...")
                submit_btn.click()
                time.sleep(3)
                result["status"] = "submitted"
            else:
                print(f"    ⏸️  Form filled. Set AUTO_APPLY_CONFIRM=true to submit.")
                result["status"] = "filled_ready"
        else:
            result["status"] = "custom_questions"
            
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        print(f"    ❌ Error: {e}")
    
    return result


# =============================================================================
# MANUAL APPLY PACKAGE (fallback)
# =============================================================================

def generate_apply_package(job: Dict, resume_path: Optional[str], cover_letter: str,
                           output_folder: str = "apply_packages") -> Optional[str]:
    """Generate a manual apply package with resume, cover letter, and HTML form."""
    try:
        os.makedirs(output_folder, exist_ok=True)
        
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_title = re.sub(r'[\\/*?:"<>|]', "", job.get("job_title", "Job"))[:30]
        safe_company = re.sub(r'[\\/*?:"<>|]', "", job.get("company", "Company"))[:20]
        package_name = f"{safe_company}_{safe_title}_{ts}"
        package_path = os.path.join(output_folder, package_name)
        os.makedirs(package_path, exist_ok=True)
        
        # Copy resume
        import shutil
        if resume_path and os.path.exists(resume_path):
            shutil.copy2(resume_path, os.path.join(package_path, "resume.pdf"))
        
        # Save cover letter
        with open(os.path.join(package_path, "cover_letter.txt"), "w", encoding="utf-8") as f:
            f.write(cover_letter)
        
        # JSON form data
        form_data = {
            "job": job,
            "applicant": {
                "name": APPLICANT_NAME,
                "email": APPLICANT_EMAIL,
                "phone": APPLICANT_PHONE,
                "linkedin": APPLICANT_LINKEDIN,
                "portfolio": APPLICANT_PORTFOLIO,
                "github": APPLICANT_GITHUB,
            },
            "cover_letter": cover_letter
        }
        
        with open(os.path.join(package_path, "form_data.json"), "w", encoding="utf-8") as f:
            json.dump(form_data, f, indent=2)
        
        # HTML helper
        html = f"""<!DOCTYPE html>
<html><head><title>Apply: {job.get('job_title')} at {job.get('company')}</title>
<style>
body {{ font-family: Arial; max-width: 700px; margin: 30px auto; padding: 20px; }}
.header {{ background: #f5f5f5; padding: 20px; border-radius: 8px; }}
.field {{ display: flex; margin: 12px 0; align-items: center; }}
.field label {{ width: 100px; font-weight: bold; }}
.field input {{ flex: 1; padding: 8px; border: 1px solid #ccc; border-radius: 4px; }}
button {{ background: #4CAF50; color: white; border: none; padding: 6px 16px; cursor: pointer; border-radius: 4px; margin-left: 8px; }}
button:hover {{ background: #45a049; }}
textarea {{ width: 100%; height: 250px; font-family: monospace; }}
a {{ color: #2196F3; }}
</style></head>
<body>
<div class="header">
    <h2>📝 Apply Package</h2>
    <h3>{job.get('job_title')} at {job.get('company')}</h3>
    <p><a href="{job.get('apply_url', '')}" target="_blank">Open Application ↗</a></p>
</div>
<div class="field"><label>Name:</label><input value="{APPLICANT_NAME}" id="n" readonly><button onclick="copy('n')">Copy</button></div>
<div class="field"><label>Email:</label><input value="{APPLICANT_EMAIL}" id="e" readonly><button onclick="copy('e')">Copy</button></div>
<div class="field"><label>Phone:</label><input value="{APPLICANT_PHONE}" id="p" readonly><button onclick="copy('p')">Copy</button></div>
<div class="field"><label>LinkedIn:</label><input value="{APPLICANT_LINKEDIN}" id="l" readonly><button onclick="copy('l')">Copy</button></div>
<div class="field"><label>Portfolio:</label><input value="{APPLICANT_PORTFOLIO}" id="pf" readonly><button onclick="copy('pf')">Copy</button></div>
<h3>Cover Letter</h3>
<textarea readonly>{cover_letter}</textarea>
<script>function copy(id) {{ var el=document.getElementById(id); el.select(); document.execCommand('copy'); }}</script>
</body></html>"""
        
        with open(os.path.join(package_path, "index.html"), "w", encoding="utf-8") as f:
            f.write(html)
        
        print(f"    📦 Apply package: {package_path}")
        return package_path
        
    except Exception as e:
        print(f"    ❌ Package error: {e}")
        return None


# =============================================================================
# MAIN AUTO-APPLY FUNCTION
# =============================================================================

def auto_apply(job, mark_sheet=True, open_browser=True, use_playwright=False):
    """
    Auto-apply to a job.

    Args:
        job: dict with job details
        mark_sheet: track in APPLIED sheet
        open_browser: open URL in browser (simple mode)
        use_playwright: auto-fill forms (advanced mode)
    
    Returns:
        dict with results
    """
    job_title = job.get("job_title", "Unknown Job")
    company = job.get("company", "Unknown Company")
    apply_url = job.get("apply_url", "")
    tech_stack = job.get("tech_stack", "")
    summary = job.get("summary", "")
    match_score = job.get("match_score", job.get("score", 0))

    print(f"\n{'='*60}")
    print(f"🎯 Applying: {job_title} at {company} (Score: {match_score})")
    print(f"{'='*60}")

    result = {
        "job_title": job_title,
        "company": company,
        "apply_url": apply_url,
        "score": match_score,
        "resume_path": None,
        "cover_letter_path": None,
        "browser_opened": False,
        "sheet_updated": False,
        "playwright_result": None,
        "package_path": None,
        "status": "started",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    # Step 1: Generate tailored resume
    print("\n📄 1. Generating tailored resume...")
    try:
        from tools.resume_generator import generate_resume_for_job
        resume_path = generate_resume_for_job(job)
        if resume_path:
            result["resume_path"] = resume_path
            print(f"   ✅ Resume: {resume_path}")
        else:
            print("   ⚠️ Resume generation failed")
    except Exception as e:
        print(f"   ❌ Resume error: {e}")

    # Step 2: Generate tailored cover letter
    print("\n📝 2. Generating tailored cover letter...")
    try:
        from agents.gemini_tools import generate_cover_letter, save_cover_letter_pdf, _load_cv_profile
        cv_profile = _load_cv_profile()
        cover_letter = generate_cover_letter(
            job_title, company, summary,
            applicant_name=APPLICANT_NAME,
            tech_stack=tech_stack,
            cv_profile=cv_profile
        )
        cl_path = save_cover_letter_pdf(cover_letter, job_title)
        if cl_path:
            result["cover_letter_path"] = cl_path
            print(f"   ✅ Cover letter: {cl_path}")
    except Exception as e:
        print(f"   ❌ Cover letter error: {e}")
        cover_letter = ""

    # Step 3: Apply mode
    platform = detect_ats_platform(apply_url) if apply_url else "unknown"
    
    if use_playwright and platform in ["greenhouse", "lever"]:
        # ADVANCED: Playwright form filling
        print(f"\n🤖 3. Playwright auto-fill mode ({platform})...")
        sync_playwright = _get_playwright()
        
        if sync_playwright:
            try:
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=False)
                    page = browser.new_page(viewport={"width": 1280, "height": 900})
                    
                    user_profile = {
                        "name": APPLICANT_NAME,
                        "email": APPLICANT_EMAIL,
                        "phone": APPLICANT_PHONE,
                        "linkedin": APPLICANT_LINKEDIN,
                        "portfolio": APPLICANT_PORTFOLIO,
                    }
                    
                    if platform == "greenhouse":
                        pw_result = _fill_greenhouse_form(page, apply_url, 
                                                          result.get("resume_path"), 
                                                          cover_letter, user_profile)
                    else:
                        pw_result = _fill_lever_form(page, apply_url,
                                                     result.get("resume_path"),
                                                     cover_letter, user_profile)
                    
                    result["playwright_result"] = pw_result
                    result["status"] = pw_result.get("status", "unknown")
                    browser.close()
                    
            except Exception as e:
                print(f"   ❌ Playwright failed: {e}")
                print(f"   📦 Falling back to manual package...")
                result["status"] = "playwright_failed"
        else:
            print(f"   ⚠️ Playwright not installed. Run: pip install playwright && playwright install chromium")
            result["status"] = "playwright_not_installed"
    
    elif open_browser and apply_url:
        # SIMPLE: Just open browser
        print(f"\n🌐 3. Opening browser: {apply_url}")
        try:
            webbrowser.open(apply_url)
            result["browser_opened"] = True
            print(f"   ✅ Browser opened")
            
            # Also generate apply package for convenience
            pkg = generate_apply_package(job, result.get("resume_path"), cover_letter)
            if pkg:
                result["package_path"] = pkg
                
        except Exception as e:
            print(f"   ❌ Browser error: {e}")
    
    else:
        # No browser, just package
        print(f"\n📦 3. Generating apply package...")
        pkg = generate_apply_package(job, result.get("resume_path"), cover_letter)
        if pkg:
            result["package_path"] = pkg
            result["status"] = "package_only"

    # Step 4: Track in APPLIED sheet
    if mark_sheet:
        print(f"\n📊 4. Tracking in Google Sheet...")
        try:
            _track_application(job, result)
            result["sheet_updated"] = True
            print(f"   ✅ Tracked in APPLIED sheet")
        except Exception as e:
            print(f"   ❌ Sheet tracking error: {e}")

    print(f"\n{'='*60}")
    print(f"✅ Done: {job_title} at {company} — Status: {result['status']}")
    print(f"{'='*60}")

    return result


def _track_application(job, apply_result):
    """Mark a job as applied in the Google Sheet APPLIED tab."""
    from tools.sheet_writer import get_sheet, get_or_create_worksheet, APPLIED_COLUMNS
    
    sheet = get_sheet()
    worksheet = get_or_create_worksheet(sheet, "APPLIED")

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    row = [
        job.get("job_title", ""),
        job.get("company", ""),
        job.get("salary", ""),
        job.get("tech_stack", ""),
        job.get("timezone", ""),
        job.get("apply_url", ""),
        job.get("summary", "")[:200],
        job.get("posted_date_iso", ""),
        job.get("source", ""),
        str(apply_result.get("score", job.get("match_score", ""))),
        job.get("match_reason", ""),
        timestamp,
        apply_result.get("status", "applied"),
        job.get("job_fingerprint", ""),
        timestamp,
        f"Resume: {apply_result.get('resume_path', 'N/A')} | CL: {apply_result.get('cover_letter_path', 'N/A')} | Status: {apply_result.get('status', '')}",
    ]

    existing = worksheet.get_all_values()
    if not existing:
        worksheet.insert_row(APPLIED_COLUMNS, index=1)

    worksheet.append_row(row)


# =============================================================================
# BATCH APPLY
# =============================================================================

def batch_auto_apply(jobs, limit=None, score_threshold=None):
    """
    Auto-apply to multiple high-scoring jobs.
    
    Args:
        jobs: list of job dicts
        limit: max jobs to apply (default from env)
        score_threshold: min score (default from env)
    """
    limit = limit or AUTO_APPLY_LIMIT
    score_threshold = score_threshold or AUTO_APPLY_THRESHOLD
    
    # Filter and sort
    scored_jobs = sorted(
        [j for j in jobs if int(j.get("match_score", j.get("score", 0))) >= score_threshold],
        key=lambda j: int(j.get("match_score", j.get("score", 0))),
        reverse=True,
    )

    print(f"\n{'='*60}")
    print(f"BATCH AUTO-APPLY")
    print(f"Jobs above threshold {score_threshold}: {len(scored_jobs)}")
    print(f"Applying to top {min(limit, len(scored_jobs))}")
    print(f"{'='*60}")

    results = []
    for i, job in enumerate(scored_jobs[:limit], 1):
        print(f"\n--- [{i}/{min(limit, len(scored_jobs))}] ---")
        
        # Use Playwright if enabled and platform is supported
        use_pw = AUTO_APPLY_PLAYWRIGHT and detect_ats_platform(job.get("apply_url", "")) in ["greenhouse", "lever"]
        
        result = auto_apply(job, use_playwright=use_pw)
        results.append(result)
        time.sleep(3)  # Be polite

    # Summary
    print(f"\n{'='*60}")
    print(f"BATCH SUMMARY")
    print(f"{'='*60}")
    
    statuses = {}
    for r in results:
        s = r["status"]
        statuses[s] = statuses.get(s, 0) + 1
    
    for status, count in statuses.items():
        print(f"  {status}: {count}")
    
    submitted = sum(1 for r in results if r["status"] == "submitted")
    filled = sum(1 for r in results if r["status"] in ["filled_ready", "package_only", "browser_opened"])
    errors = sum(1 for r in results if "error" in r["status"] or r["status"] == "playwright_failed")
    
    print(f"\n  Submitted: {submitted}")
    print(f"  Ready for review: {filled}")
    print(f"  Errors: {errors}")

    return results