"""
agents/auto_applier.py
Auto-apply agent with tiered strategy, SQLite state tracking, and safety gates.

TIER STRATEGY:
    dream      → Auto-prepare, notify human, NEVER auto-submit
    good_fit   → Auto-fill form, pause for human review (default)
    batch      → Auto-fill + auto-submit (if AUTO_APPLY_CONFIRM=true)

Usage:
    python main.py apply                    # Simple mode
    AUTO_APPLY_PLAYWRIGHT=true python main.py apply   # Playwright mode
"""

import os
import json
import webbrowser
import re
import time
import random
import sqlite3
from datetime import datetime, timedelta
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
AUTO_APPLY_DAILY_CAP = int(os.getenv("AUTO_APPLY_DAILY_CAP", "5"))  # Hard daily limit for auto-submit

APPLICANT_NAME = os.getenv("APPLICANT_NAME", "Mubashir")
APPLICANT_EMAIL = os.getenv("APPLICANT_EMAIL", "")
APPLICANT_PHONE = os.getenv("APPLICANT_PHONE", "")
APPLICANT_LINKEDIN = os.getenv("APPLICANT_LINKEDIN", "")
APPLICANT_PORTFOLIO = os.getenv("APPLICANT_PORTFOLIO", "")
APPLICANT_GITHUB = os.getenv("APPLICANT_GITHUB", "")

# TIER THRESHOLDS
TIER_DREAM_THRESHOLD = int(os.getenv("TIER_DREAM_THRESHOLD", "90"))
TIER_BATCH_MAX = int(os.getenv("TIER_BATCH_MAX", "75"))

# =============================================================================
# SQLITE STATE DATABASE
# =============================================================================

DB_PATH = Path("data/job_agent.db")

def _init_db():
    """Initialize SQLite database for application state tracking."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_fingerprint TEXT UNIQUE,
            job_title TEXT,
            company TEXT,
            apply_url TEXT,
            tier TEXT,
            status TEXT,
            score INTEGER,
            resume_path TEXT,
            cover_letter_path TEXT,
            package_path TEXT,
            screenshot_path TEXT,
            error_log TEXT,
            applied_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_stats (
            date TEXT PRIMARY KEY,
            auto_submitted INTEGER DEFAULT 0,
            filled_ready INTEGER DEFAULT 0,
            dream_manual INTEGER DEFAULT 0,
            errors INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()

def _get_db():
    return sqlite3.connect(DB_PATH)

def _already_applied(job_fingerprint: str) -> bool:
    """Check if we already have a record for this job."""
    conn = _get_db()
    cur = conn.execute("SELECT 1 FROM applications WHERE job_fingerprint = ?", (job_fingerprint,))
    exists = cur.fetchone() is not None
    conn.close()
    return exists

def _get_daily_auto_submit_count() -> int:
    """How many auto-submits today?"""
    today = datetime.now().strftime("%Y-%m-%d")
    conn = _get_db()
    cur = conn.execute("SELECT auto_submitted FROM daily_stats WHERE date = ?", (today,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else 0

def _increment_daily_stat(column: str):
    today = datetime.now().strftime("%Y-%m-%d")
    conn = _get_db()
    conn.execute(f"""
        INSERT INTO daily_stats (date, {column}) VALUES (?, 1)
        ON CONFLICT(date) DO UPDATE SET {column} = {column} + 1
    """, (today,))
    conn.commit()
    conn.close()

def _save_application(job: Dict, result: Dict, tier: str):
    """Persist application state to SQLite."""
    conn = _get_db()
    conn.execute("""
        INSERT OR REPLACE INTO applications 
        (job_fingerprint, job_title, company, apply_url, tier, status, score,
         resume_path, cover_letter_path, package_path, screenshot_path, error_log, applied_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        job.get("job_fingerprint", job.get("apply_url", "")),
        job.get("job_title", ""),
        job.get("company", ""),
        job.get("apply_url", ""),
        tier,
        result.get("status", "unknown"),
        job.get("match_score", 0),
        result.get("resume_path"),
        result.get("cover_letter_path"),
        result.get("package_path"),
        result.get("screenshot_path"),
        result.get("error"),
        datetime.now()
    ))
    conn.commit()
    conn.close()

# =============================================================================
# TIER CLASSIFICATION
# =============================================================================

def classify_tier(job: Dict) -> str:
    """Classify job into tier based on match score and other signals."""
    score = int(job.get("match_score", job.get("score", 0)))
    
    if score >= TIER_DREAM_THRESHOLD:
        return "dream"
    elif score <= TIER_BATCH_MAX:
        return "batch"
    else:
        return "good_fit"

def get_tier_action(tier: str) -> Dict:
    """Get action config for a tier."""
    base = {
        "dream":      {"auto_open": True,  "auto_fill": False, "auto_submit": False, "notify": True,  "require_confirm": True},
        "good_fit":   {"auto_open": True,  "auto_fill": True,  "auto_submit": False, "notify": False, "require_confirm": True},
        "batch":      {"auto_open": True,  "auto_fill": True,  "auto_submit": AUTO_APPLY_CONFIRM, "notify": False, "require_confirm": False},
    }
    return base.get(tier, base["good_fit"])

# =============================================================================
# ATS PLATFORM DETECTION
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
    if "linkedin.com" in url_lower:
        return "linkedin"
    return "unknown"

# =============================================================================
# PLAYWRIGHT SETUP
# =============================================================================

def _get_playwright():
    try:
        from playwright.sync_api import sync_playwright
        return sync_playwright
    except ImportError:
        return None

# =============================================================================
# FORM FILLERS (Greenhouse + Lever)
# =============================================================================

def _fill_greenhouse_form(page, job_url: str, resume_path: Optional[str], 
                          cover_letter: str, user_profile: Dict) -> Dict:
    result = {"status": "unknown", "screenshot_path": None, "error": None}
    
    try:
        print(f"  🌐 Navigating to: {job_url}")
        page.goto(job_url, wait_until="networkidle", timeout=30000)
        page.wait_for_selector("#application-form, .application-form, form", timeout=10000)
        
        screenshot_dir = Path("screenshots")
        screenshot_dir.mkdir(exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        
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
        
        if resume_path and os.path.exists(resume_path):
            try:
                file_input = page.locator("input[type='file'][name*='resume'], input[type='file'][name*='cv']").first
                if file_input.count() > 0:
                    file_input.set_input_files(resume_path)
                    print(f"    ✅ Resume uploaded")
            except Exception as e:
                print(f"    ⚠️ Resume upload: {e}")
        
        if cover_letter:
            try:
                cl_field = page.locator("textarea[name*='cover'], textarea[name*='letter'], textarea[name*='message']").first
                if cl_field.count() > 0:
                    cl_field.fill(cover_letter)
                    print(f"    ✅ Cover letter pasted")
            except Exception as e:
                print(f"    ⚠️ Cover letter field: {e}")
        
        # Screenshot before submit
        screenshot_path = screenshot_dir / f"greenhouse_{ts}_before_submit.png"
        page.screenshot(path=str(screenshot_path), full_page=True)
        result["screenshot_path"] = str(screenshot_path)
        print(f"    📸 Screenshot: {screenshot_path}")
        
        # Check for custom questions (radio buttons, dropdowns, textareas we didn't fill)
        custom_elements = page.locator(".application-question, .custom-question, [class*='question']").count()
        if custom_elements > 0:
            print(f"    ⚠️ Detected {custom_elements} custom questions — needs human review")
            result["status"] = "custom_questions"
            return result
        
        submit_btn = page.locator("input[type='submit'], button[type='submit'], #submit_app").first
        if submit_btn.count() > 0:
            result["status"] = "filled_ready"
        else:
            result["status"] = "no_submit_button"
            
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        # Screenshot on failure
        try:
            fail_dir = Path("screenshots/failures")
            fail_dir.mkdir(parents=True, exist_ok=True)
            fail_path = fail_dir / f"greenhouse_{datetime.now().strftime('%Y%m%d_%H%M%S')}_error.png"
            page.screenshot(path=str(fail_path), full_page=True)
            result["screenshot_path"] = str(fail_path)
        except:
            pass
        print(f"    ❌ Error: {e}")
    
    return result


def _fill_lever_form(page, job_url: str, resume_path: Optional[str],
                     cover_letter: str, user_profile: Dict) -> Dict:
    result = {"status": "unknown", "screenshot_path": None, "error": None}
    
    try:
        print(f"  🌐 Navigating to: {job_url}")
        page.goto(job_url, wait_until="networkidle", timeout=30000)
        page.wait_for_selector(".application-form, form", timeout=10000)
        
        screenshot_dir = Path("screenshots")
        screenshot_dir.mkdir(exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Name
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
        
        if resume_path and os.path.exists(resume_path):
            try:
                file_input = page.locator("input[type='file']").first
                if file_input.count() > 0:
                    file_input.set_input_files(resume_path)
                    print(f"    ✅ Resume uploaded")
            except Exception as e:
                print(f"    ⚠️ Resume upload: {e}")
        
        if cover_letter:
            try:
                cl_field = page.locator("textarea[name*='cover'], textarea[placeholder*='cover']").first
                if cl_field.count() > 0:
                    cl_field.fill(cover_letter)
                    print(f"    ✅ Cover letter pasted")
            except Exception as e:
                print(f"    ⚠️ Cover letter: {e}")
        
        screenshot_path = screenshot_dir / f"lever_{ts}_before_submit.png"
        page.screenshot(path=str(screenshot_path), full_page=True)
        result["screenshot_path"] = str(screenshot_path)
        print(f"    📸 Screenshot: {screenshot_path}")
        
        # Check for custom questions
        custom_elements = page.locator(".custom-question, [data-qa*='question']").count()
        if custom_elements > 0:
            print(f"    ⚠️ Detected custom questions — needs human review")
            result["status"] = "custom_questions"
            return result
        
        submit_btn = page.locator("button[type='submit'], .postings-btn").first
        if submit_btn.count() > 0:
            result["status"] = "filled_ready"
        else:
            result["status"] = "no_submit_button"
            
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        try:
            fail_dir = Path("screenshots/failures")
            fail_dir.mkdir(parents=True, exist_ok=True)
            fail_path = fail_dir / f"lever_{datetime.now().strftime('%Y%m%d_%H%M%S')}_error.png"
            page.screenshot(path=str(fail_path), full_page=True)
            result["screenshot_path"] = str(fail_path)
        except:
            pass
        print(f"    ❌ Error: {e}")
    
    return result

# =============================================================================
# EMAIL OUTREACH FALLBACK
# =============================================================================

def generate_email_outreach(job: Dict, cover_letter: str, resume_path: Optional[str]) -> Optional[str]:
    """
    For non-ATS jobs, generate a cold email draft.
    Returns path to saved email draft.
    """
    company = job.get("company", "Company")
    job_title = job.get("job_title", "Role")
    apply_url = job.get("apply_url", "")
    
    # Try to find careers email
    careers_email = f"careers@{company.lower().replace(' ', '').replace(',', '')}.com"
    
    email_body = f"""Subject: Application for {job_title} — {APPLICANT_NAME}

Dear Hiring Manager at {company},

I came across the {job_title} position and I'm very interested in joining your team.

{cover_letter[:500]}...

I've attached my resume for your review. I'd welcome the opportunity to discuss how my skills align with your needs.

Best regards,
{APPLICANT_NAME}
{APPLICANT_EMAIL}
{APPLICANT_LINKEDIN}
{APPLICANT_PORTFOLIO}
"""
    
    email_dir = Path("email_drafts")
    email_dir.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_title = re.sub(r'[\\/*?:"<>|]', "", job_title)[:30]
    safe_company = re.sub(r'[\\/*?:"<>|]', "", company)[:20]
    email_path = email_dir / f"{safe_company}_{safe_title}_{ts}.txt"
    
    with open(email_path, "w", encoding="utf-8") as f:
        f.write(f"To: {careers_email}\n")
        f.write(f"Job URL: {apply_url}\n\n")
        f.write(email_body)
    
    print(f"    📧 Email draft saved: {email_path}")
    return str(email_path)

# =============================================================================
# APPLY PACKAGE (manual fallback)
# =============================================================================

def generate_apply_package(job: Dict, resume_path: Optional[str], cover_letter: str,
                           output_folder: str = "apply_packages") -> Optional[str]:
    try:
        os.makedirs(output_folder, exist_ok=True)
        
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_title = re.sub(r'[\\/*?:"<>|]', "", job.get("job_title", "Job"))[:30]
        safe_company = re.sub(r'[\\/*?:"<>|]', "", job.get("company", "Company"))[:20]
        package_name = f"{safe_company}_{safe_title}_{ts}"
        package_path = os.path.join(output_folder, package_name)
        os.makedirs(package_path, exist_ok=True)
        
        import shutil
        if resume_path and os.path.exists(resume_path):
            shutil.copy2(resume_path, os.path.join(package_path, "resume.pdf"))
        
        with open(os.path.join(package_path, "cover_letter.txt"), "w", encoding="utf-8") as f:
            f.write(cover_letter)
        
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
    Tier-aware auto-apply with safety gates.
    """
    job_title = job.get("job_title", "Unknown Job")
    company = job.get("company", "Unknown Company")
    apply_url = job.get("apply_url", "")
    tech_stack = job.get("tech_stack", "")
    summary = job.get("summary", "")
    match_score = job.get("match_score", job.get("score", 0))
    fingerprint = job.get("job_fingerprint", apply_url)

    # === GUARD: Already applied? ===
    if _already_applied(fingerprint):
        print(f"⏭️  Already applied to {job_title} at {company}. Skipping.")
        return {"status": "already_applied", "job_title": job_title, "company": company}

    # === GUARD: Daily cap for auto-submit ===
    tier = classify_tier(job)
    tier_action = get_tier_action(tier)
    
    if tier == "batch" and tier_action["auto_submit"]:
        daily_count = _get_daily_auto_submit_count()
        if daily_count >= AUTO_APPLY_DAILY_CAP:
            print(f"🚫 Daily auto-submit cap ({AUTO_APPLY_DAILY_CAP}) reached. Switching to review mode.")
            tier_action["auto_submit"] = False
            tier_action["require_confirm"] = True

    print(f"\n{'='*60}")
    print(f"🎯 [{tier.upper()}] {job_title} at {company} (Score: {match_score})")
    print(f"{'='*60}")
    print(f"   Auto-fill: {tier_action['auto_fill']} | Auto-submit: {tier_action['auto_submit']} | Confirm required: {tier_action['require_confirm']}")

    result = {
        "job_title": job_title,
        "company": company,
        "apply_url": apply_url,
        "score": match_score,
        "tier": tier,
        "resume_path": None,
        "cover_letter_path": None,
        "browser_opened": False,
        "sheet_updated": False,
        "playwright_result": None,
        "package_path": None,
        "email_draft_path": None,
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

    # Step 3: Apply mode based on tier + platform
    platform = detect_ats_platform(apply_url) if apply_url else "unknown"
    
    # DREAM jobs: Just notify and prepare, never touch the browser
    if tier == "dream":
        print(f"\n⭐ 3. DREAM JOB — Preparing package for manual application...")
        pkg = generate_apply_package(job, result.get("resume_path"), cover_letter)
        if pkg:
            result["package_path"] = pkg
        if apply_url and open_browser:
            webbrowser.open(apply_url)
            result["browser_opened"] = True
        result["status"] = "dream_manual"
        _increment_daily_stat("dream_manual")
        print(f"   🔔 Review and apply manually. Package ready.")

    # ATS platforms (Greenhouse/Lever): Playwright or package
    elif use_playwright and platform in ["greenhouse", "lever"]:
        print(f"\n🤖 3. Playwright auto-fill ({platform})...")
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
                    result["screenshot_path"] = pw_result.get("screenshot_path")
                    
                    # SUBMIT LOGIC
                    if pw_result["status"] == "filled_ready" and tier_action["auto_submit"]:
                        submit_btn = page.locator("input[type='submit'], button[type='submit'], #submit_app, .postings-btn").first
                        if submit_btn.count() > 0:
                            print(f"    🚀 Auto-submitting...")
                            submit_btn.click()
                            time.sleep(3)
                            result["status"] = "submitted"
                            _increment_daily_stat("auto_submitted")
                    else:
                        result["status"] = pw_result["status"]
                        if result["status"] == "filled_ready":
                            _increment_daily_stat("filled_ready")
                    
                    browser.close()
                    
            except Exception as e:
                print(f"   ❌ Playwright failed: {e}")
                result["status"] = "playwright_failed"
                _increment_daily_stat("errors")
        else:
            print(f"   ⚠️ Playwright not installed.")
            result["status"] = "playwright_not_installed"
    
    # Non-ATS jobs: Email outreach fallback
    elif platform in ["unknown", "workday", "workable", "linkedin"]:
        print(f"\n📧 3. Non-ATS platform ({platform}) — generating email draft...")
        email_path = generate_email_outreach(job, cover_letter, result.get("resume_path"))
        if email_path:
            result["email_draft_path"] = email_path
            result["status"] = "email_draft"
        if apply_url and open_browser:
            webbrowser.open(apply_url)
            result["browser_opened"] = True
    
    # Simple mode: Just open browser + package
    elif open_browser and apply_url:
        print(f"\n🌐 3. Opening browser: {apply_url}")
        try:
            webbrowser.open(apply_url)
            result["browser_opened"] = True
            pkg = generate_apply_package(job, result.get("resume_path"), cover_letter)
            if pkg:
                result["package_path"] = pkg
        except Exception as e:
            print(f"   ❌ Browser error: {e}")
    
    else:
        pkg = generate_apply_package(job, result.get("resume_path"), cover_letter)
        if pkg:
            result["package_path"] = pkg
            result["status"] = "package_only"

    # Step 4: Persist to SQLite
    _save_application(job, result, tier)

    # Step 5: Track in Google Sheet
    if mark_sheet:
        print(f"\n📊 4. Tracking in Google Sheet...")
        try:
            _track_application(job, result)
            result["sheet_updated"] = True
            print(f"   ✅ Tracked")
        except Exception as e:
            print(f"   ❌ Sheet tracking error: {e}")

    print(f"\n{'='*60}")
    print(f"✅ Done: {job_title} at {company} — Status: {result['status']} | Tier: {tier}")
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
    Batch apply with deduplication, tiering, and polite delays.
    """
    _init_db()
    limit = limit or AUTO_APPLY_LIMIT
    score_threshold = score_threshold or AUTO_APPLY_THRESHOLD
    
    # Filter: score + not already applied
    scored_jobs = []
    for j in jobs:
        score = int(j.get("match_score", j.get("score", 0)))
        fp = j.get("job_fingerprint", j.get("apply_url", ""))
        if score >= score_threshold and not _already_applied(fp):
            scored_jobs.append(j)
    
    scored_jobs.sort(key=lambda j: int(j.get("match_score", j.get("score", 0))), reverse=True)

    print(f"\n{'='*60}")
    print(f"BATCH AUTO-APPLY")
    print(f"Jobs above threshold {score_threshold}: {len(scored_jobs)}")
    print(f"Applying to top {min(limit, len(scored_jobs))}")
    print(f"Daily auto-submit cap: {AUTO_APPLY_DAILY_CAP} (used: {_get_daily_auto_submit_count()})")
    print(f"{'='*60}")

    results = []
    for i, job in enumerate(scored_jobs[:limit], 1):
        print(f"\n--- [{i}/{min(limit, len(scored_jobs))}] ---")
        
        tier = classify_tier(job)
        use_pw = AUTO_APPLY_PLAYWRIGHT and detect_ats_platform(job.get("apply_url", "")) in ["greenhouse", "lever"]
        
        result = auto_apply(job, use_playwright=use_pw)
        results.append(result)
        
        # Polite delay with jitter (45-120s)
        if i < len(scored_jobs[:limit]):
            delay = random.uniform(45, 120)
            print(f"   ⏳ Waiting {delay:.1f}s before next application...")
            time.sleep(delay)

    # Summary
    print(f"\n{'='*60}")
    print(f"BATCH SUMMARY")
    print(f"{'='*60}")
    
    statuses = {}
    tiers = {"dream": 0, "good_fit": 0, "batch": 0}
    for r in results:
        s = r["status"]
        statuses[s] = statuses.get(s, 0) + 1
        tiers[r.get("tier", "unknown")] = tiers.get(r.get("tier", "unknown"), 0) + 1
    
    print(f"\n  By Status:")
    for status, count in statuses.items():
        print(f"    {status}: {count}")
    
    print(f"\n  By Tier:")
    for tier, count in tiers.items():
        print(f"    {tier}: {count}")
    
    submitted = sum(1 for r in results if r["status"] == "submitted")
    dream_manual = sum(1 for r in results if r["status"] == "dream_manual")
    filled_ready = sum(1 for r in results if r["status"] in ["filled_ready", "package_only", "browser_opened", "email_draft"])
    errors = sum(1 for r in results if "error" in r["status"] or r["status"] in ["playwright_failed", "custom_questions"])
    
    print(f"\n  🚀 Auto-submitted: {submitted}")
    print(f"  ⭐ Dream jobs (manual): {dream_manual}")
    print(f"  ⏸️  Ready for review: {filled_ready}")
    print(f"  ❌ Errors/Blocked: {errors}")

    return results