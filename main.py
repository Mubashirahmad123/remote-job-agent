"""
main.py
Entry point for Remote Job Agent.
Supports: crewai (default), simple, test, apply, resume
"""

import os
import json
import sys
import argparse
from pathlib import Path
from dotenv import load_dotenv

# Load .env FIRST before any other imports that might use env vars
BASE_DIR = Path(__file__).resolve().parent
env_file = BASE_DIR / ".env"

if not env_file.exists():
    print("❌ ERROR: .env file is missing!")
    exit(1)

load_dotenv(dotenv_path=env_file)

# Validate critical env vars
GOOGLE_SERVICE_ACCOUNT = os.getenv("GOOGLE_SERVICE_ACCOUNT")
GOOGLE_SHEETS_ID = os.getenv("GOOGLE_SHEETS_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
MISTRAL_MODEL = os.getenv("MISTRAL_MODEL", "mistral-medium-latest")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

if not GOOGLE_SERVICE_ACCOUNT or not GOOGLE_SHEETS_ID:
    print("❌ ERROR: Missing GOOGLE_SERVICE_ACCOUNT or GOOGLE_SHEETS_ID in .env")
    exit(1)

if not GEMINI_API_KEY and not MISTRAL_API_KEY and not GROQ_API_KEY:
    print("⚠️ WARNING: No LLM API key set (GEMINI/MISTRAL/GROQ). LLM features will fail.")

print("✅ Environment loaded successfully")
print(f"   Google Service Account: {GOOGLE_SERVICE_ACCOUNT}")
print(f"   Google Sheets ID: {GOOGLE_SHEETS_ID}")
print(f"   Gemini API Key: {'Loaded' if GEMINI_API_KEY else 'Missing'}")
print(f"   Mistral API Key: {'Loaded' if MISTRAL_API_KEY else 'Missing'}")
print(f"   Groq API Key: {'Loaded' if GROQ_API_KEY else 'Missing'}")


# =============================================================================
# IMPORTS (after env load)
# =============================================================================

# CrewAI imports (only when needed)
def _get_crewai():
    try:
        from crewai import Agent, Crew, Task, LLM
        from crewai.tools import tool
        return Agent, Crew, Task, LLM, tool
    except ImportError:
        return None, None, None, None, None

# Your modules
from agents.scrapper import scrape_all
from agents.curator import curate
from tools.sheet_writer import test_connection


# =============================================================================
# CONFIGURATION
# =============================================================================

RUN_MODE = os.getenv("RUN_MODE", "crewai")
MODEL = os.getenv("MODEL", "gemini/gemini-2.5-flash")

# Auto-apply settings from .env
AUTO_APPLY_ENABLED = os.getenv("AUTO_APPLY_ENABLED", "false").lower() == "true"
AUTO_APPLY_THRESHOLD = int(os.getenv("AUTO_APPLY_THRESHOLD", "70"))
AUTO_APPLY_LIMIT = int(os.getenv("AUTO_APPLY_LIMIT", "5"))
AUTO_APPLY_PLAYWRIGHT = os.getenv("AUTO_APPLY_PLAYWRIGHT", "false").lower() == "true"


# =============================================================================
# LLM SETUP — with fallback awareness
# =============================================================================

def _setup_llm():
    """Setup LLM with available provider (Gemini or Mistral via MODEL)."""
    Agent, Crew, Task, LLM, tool = _get_crewai()
    if not LLM:
        return None, None, None, None, None

    # Pick API key based on MODEL prefix so `MODEL=mistral/...` or
    # `MODEL=groq/...` just works.
    # CrewAI/LiteLLM expects e.g. model="mistral/mistral-medium-latest"
    # with api_key=MISTRAL_API_KEY, model="groq/llama-3.3-70b-versatile"
    # with api_key=GROQ_API_KEY, or model="gemini/gemini-2.5-flash"
    # with api_key=GEMINI_API_KEY.
    model_lower = MODEL.lower()
    if model_lower.startswith("mistral"):
        api_key = MISTRAL_API_KEY
        # LiteLLM needs the provider prefix
        model_name = MODEL if "/" in MODEL else f"mistral/{MODEL}"
        # LiteLLM reads MISTRAL_API_KEY from env — export it for safety
        if api_key and not os.getenv("MISTRAL_API_KEY"):
            os.environ["MISTRAL_API_KEY"] = api_key
    elif model_lower.startswith("groq"):
        api_key = GROQ_API_KEY
        model_name = MODEL if "/" in MODEL else f"groq/{MODEL}"
        if api_key and not os.getenv("GROQ_API_KEY"):
            os.environ["GROQ_API_KEY"] = api_key
    else:
        api_key = GEMINI_API_KEY
        model_name = MODEL

    if not api_key:
        print(f"⚠️ No API key for model {model_name}. Set GEMINI_API_KEY, MISTRAL_API_KEY or GROQ_API_KEY.")
        return Agent, Crew, Task, LLM, tool, None

    # Try to use the model from .env
    try:
        llm = LLM(
            model=model_name,
            api_key=api_key
        )
        print(f"✅ LLM configured: {model_name}")
        return Agent, Crew, Task, LLM, tool, llm
    except Exception as e:
        print(f"⚠️ LLM setup failed: {e}")
        return Agent, Crew, Task, LLM, tool, None


# =============================================================================
# CREWAI TOOLS
# =============================================================================

def _setup_crewai_tools(Agent, Crew, Task, LLM, tool, llm):
    """Setup CrewAI agents and tasks."""
    
    @tool("Scrapes remote job boards for jobs")
    def scrape_tool() -> str:
        """
        Scrapes remote job boards for developer jobs.
        Saves results to scraped_jobs.json and returns status.
        """
        print("🔍 Scraping jobs from multiple boards...")
        jobs = scrape_all(debug=False)
        print(f"✅ Found {len(jobs)} jobs")

        output_filename = BASE_DIR / "scraped_jobs.json"

        try:
            with open(output_filename, 'w', encoding='utf-8') as f:
                json.dump(jobs, f, indent=2, ensure_ascii=False)

            print(f"✅ Jobs saved to: {output_filename}")
            return json.dumps({
                "count": len(jobs),
                "file_path": str(output_filename),
                "status": "success"
            })

        except Exception as e:
            error_msg = f"Failed to save jobs: {e}"
            print(f"❌ {error_msg}")
            return json.dumps({"status": "error", "error": error_msg})

    @tool("Processes scraped jobs and saves to Google Sheet")
    def process_jobs_tool(file_path: str) -> str:
        """Reads job data, curates, and saves to Google Sheet."""
        print(f"📝 Processing jobs from: {file_path}...")

        possible_paths = [
            Path(file_path),
            BASE_DIR / "scraped_jobs.json",
            Path.cwd() / "scraped_jobs.json",
        ]

        actual_path = None
        for path in possible_paths:
            if path.exists():
                actual_path = path
                break

        if not actual_path:
            return f"❌ File not found. Searched: {[str(p) for p in possible_paths]}"

        try:
            with open(actual_path, 'r', encoding='utf-8') as f:
                jobs = json.load(f)

            if not jobs:
                return "No jobs to process."

            print(f"✅ Loaded {len(jobs)} jobs for curation")
            result = curate(jobs)

            if result["status"] == "success" and result.get("top_jobs"):
                top_jobs = result["top_jobs"]
                # Cache curated output so downstream tools (application
                # generation, auto-apply) consume it instead of re-running
                # curate() on the raw file — a second curate() would
                # fingerprint-dedupe exactly the jobs that just passed.
                curated_path = BASE_DIR / "curated_jobs.json"
                try:
                    from datetime import datetime, timezone
                    payload = {
                        "generated_at": datetime.now(timezone.utc).isoformat(),
                        "source_file": str(actual_path),
                        "source_count": len(jobs),
                        "jobs": top_jobs,
                    }
                    with open(curated_path, 'w', encoding='utf-8') as f:
                        json.dump(payload, f, indent=2, ensure_ascii=False)
                except Exception as e:
                    print(f"⚠️ Curated cache write failed: {e}")
                return (f"✅ Processed {len(jobs)} jobs. Found {len(top_jobs)} "
                        f"high-quality jobs saved to sheet and cached to {curated_path}.")
            else:
                return f"✅ Processed {len(jobs)} jobs. No high-quality matches found."

        except Exception as e:
            return f"❌ Processing failed: {e}"

    @tool("Generates cover letter and resume for top job")
    def generate_application_tool(file_path: str) -> str:
        """
        Generates tailored resume AND cover letter for the best job.
        Saves both as PDFs.
        """
        print(f"✍️ Generating application materials from: {file_path}...")

        # Consume the curated cache written by process_jobs_tool — never
        # re-run curate() on the raw file here (second curate() would
        # dedupe out exactly the jobs that just passed).
        curated_path = BASE_DIR / "curated_jobs.json"
        if not curated_path.exists():
            return "❌ No curated jobs found. Run the processor tool first."

        try:
            with open(curated_path, 'r', encoding='utf-8') as f:
                payload = json.load(f)
            curated_jobs = payload.get("jobs", []) if isinstance(payload, dict) else payload

            if not curated_jobs:
                return "❌ No high-quality jobs available for application generation."

            # Pick highest-scoring curated job
            best_job = max(curated_jobs, key=lambda x: x.get('match_score', 0) or 0)

            job_title = best_job.get('job_title', 'Software Developer')
            company = best_job.get('company', 'Unknown Company')
            summary = best_job.get('summary', '')
            tech_stack = best_job.get('tech_stack', '')

            print(f"🎯 Selected: {job_title} at {company} (Score: {best_job.get('match_score', 'N/A')})")

            # Generate resume
            from tools.resume_generator import generate_resume_for_job
            resume_path = generate_resume_for_job(best_job)
            resume_status = f"Resume: {resume_path}" if resume_path else "Resume: FAILED"

            # Generate cover letter (picked CV first, primary CV fallback)
            from agents.gemini_tools import generate_cover_letter, save_cover_letter_pdf, _load_cv_profile
            selected_cv_path = best_job.get('selected_cv_path', '') or None
            cv_profile = _load_cv_profile(selected_cv_path)
            cover_letter = generate_cover_letter(
                job_title, company, summary,
                applicant_name=os.getenv("APPLICANT_NAME", "Mubashir"),
                tech_stack=tech_stack,
                cv_profile=cv_profile,
                selected_cv_path=selected_cv_path
            )
            cl_path = save_cover_letter_pdf(cover_letter, job_title, company=company, cv_profile=cv_profile)
            cl_status = f"Cover Letter: {cl_path}" if cl_path else "Cover Letter: FAILED"

            return f"✅ Application materials generated.\n   {resume_status}\n   {cl_status}"

        except Exception as e:
            print(f"❌ Generation error: {e}")
            return f"❌ Failed: {e}"

    # --- Agents ---
    scraper_curator_agent = Agent(
        role="Job Scraper & Curator",
        goal="Scrape and curate remote developer jobs into Google Sheets",
        backstory="Expert at finding and filtering high-quality remote developer jobs.",
        tools=[scrape_tool, process_jobs_tool],
        llm=llm,
        verbose=True,
        max_retries=2
    )

    application_agent = Agent(
        role="Application Material Generator",
        goal="Generate tailored resumes and cover letters for top jobs",
        backstory="Expert resume writer and cover letter specialist for software developers.",
        tools=[generate_application_tool],
        llm=llm,
        verbose=True,
        max_retries=2
    )

    # --- Tasks ---
    scrape_curate_task = Task(
        description=(
            "1. Call the scraper tool to fetch jobs from 45+ boards. "
            "2. Call the processor tool to curate and save to Google Sheets. "
            "Return a summary of jobs scraped and curated."
        ),
        agent=scraper_curator_agent,
        expected_output="Summary: X jobs scraped, Y jobs curated to sheet."
    )

    generate_app_task = Task(
        description=(
            "Generate tailored resume and cover letter for the best matching job "
            "from the curated jobs cache (curated_jobs.json written by the processor tool). "
            "Save both as PDFs. Return file paths."
        ),
        agent=application_agent,
        context=[scrape_curate_task],
        expected_output="Resume and cover letter PDF paths."
    )

    # --- Crew ---
    crew = Crew(
        agents=[scraper_curator_agent, application_agent],
        tasks=[scrape_curate_task, generate_app_task],
        verbose=True
    )

    return crew


# =============================================================================
# RUN MODES
# =============================================================================

def run_pipeline():
    """Run complete CrewAI pipeline: scrape → curate → generate materials."""
    print("\n" + "="*60)
    print("🚀 CREWAI PIPELINE")
    print("="*60)

    # Test Google Sheets connection
    print("\n📡 Testing Google Sheets connection...")
    if not test_connection():
        print("❌ Google Sheets connection failed!")
        return False
    print("✅ Google Sheets connected")

    # Setup CrewAI
    Agent, Crew, Task, LLM, tool, llm = _setup_llm()
    if not llm:
        print("❌ CrewAI LLM setup failed. Falling back to simple mode.")
        return run_simple_scraper()

    crew = _setup_crewai_tools(Agent, Crew, Task, LLM, tool, llm)

    try:
        results = crew.kickoff()
        print("\n" + "="*60)
        print("📊 PIPELINE RESULTS")
        print("="*60)
        print(results)

        # Optional: auto-apply after pipeline
        if AUTO_APPLY_ENABLED:
            print("\n" + "="*60)
            print("🤖 AUTO-APPLY STEP")
            print("="*60)
            _run_auto_apply_from_file()

        return True

    except Exception as e:
        print(f"❌ Pipeline failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def run_simple_scraper():
    """Run scraper + curator without CrewAI (direct, no LLM overhead)."""
    print("\n" + "="*60)
    print("🔍 SIMPLE MODE: Direct Scraper")
    print("="*60)

    if not test_connection():
        print("❌ Google Sheets connection failed!")
        return False

    from tools.yield_tracker import YieldTracker
    tracker = YieldTracker()

    jobs = scrape_all(debug=False, tracker=tracker)
    print(f"✅ Scraped {len(jobs)} jobs")

    if jobs:
        # === CURATE BEFORE SAVING (curate() already saves to sheet internally) ===
        result = curate(jobs, tracker=tracker)
        tracker.save()
        tracker.print_table()
        curated_jobs = [j for j in result.get("top_jobs", []) if j.get("match_score", 0) >= 70]

        if curated_jobs:
            # Cache curated output so standalone `apply` / `resume` modes work
            # across separate `docker compose run` containers (same as crewai path).
            curated_path = BASE_DIR / "curated_jobs.json"
            try:
                from datetime import datetime, timezone
                payload = {
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "source_count": len(jobs),
                    "jobs": curated_jobs,
                }
                with open(curated_path, 'w', encoding='utf-8') as f:
                    json.dump(payload, f, indent=2, ensure_ascii=False)
                print(f"✅ Curated cache written to {curated_path} ({len(curated_jobs)} jobs)")
            except Exception as e:
                print(f"⚠️ Curated cache write failed: {e}")
            # Already persisted by curate() Step 6 — no second append_rows here.
            # Generate materials for top curated job
            best = max(curated_jobs, key=lambda x: x.get('match_score', 0) or 0)
            print(f"\n🎯 Top job: {best['job_title']} at {best['company']} (Score: {best.get('match_score')})")
            _generate_materials_for_job(best)
        else:
            print("⚠️ No jobs passed curation. Nothing saved.")
            return True

        # Auto-apply if enabled (only on curated jobs)
        if AUTO_APPLY_ENABLED and curated_jobs:
            _run_auto_apply(curated_jobs[:AUTO_APPLY_LIMIT])

    return True


def _generate_materials_for_job(job):
    """Generate resume + cover letter for a single job."""
    print("\n✍️ Generating application materials...")

    # Resume
    try:
        from tools.resume_generator import generate_resume_for_job
        resume_path = generate_resume_for_job(job)
        if resume_path:
            print(f"   ✅ Resume: {resume_path}")
    except Exception as e:
        print(f"   ❌ Resume: {e}")

    # Cover letter (picked CV first, primary CV fallback)
    try:
        from agents.gemini_tools import generate_cover_letter, save_cover_letter_pdf, _load_cv_profile
        selected_cv_path = job.get('selected_cv_path', '') or None
        cv_profile = _load_cv_profile(selected_cv_path)
        cover_letter = generate_cover_letter(
            job.get('job_title', ''),
            job.get('company', ''),
            job.get('summary', ''),
            os.getenv("APPLICANT_NAME", "Mubashir"),
            job.get('tech_stack', ''),
            cv_profile,
            selected_cv_path=selected_cv_path
        )
        cl_path = save_cover_letter_pdf(cover_letter, job.get('job_title', ''), company=job.get('company', 'Company'), cv_profile=cv_profile)
        if cl_path:
            print(f"   ✅ Cover Letter: {cl_path}")
    except Exception as e:
        print(f"   ❌ Cover Letter: {e}")


def _run_auto_apply(jobs=None, use_playwright=None):
    """Run auto-apply on jobs."""
    from agents.auto_applier import batch_auto_apply

    if jobs is None:
        jobs = _load_scraped_jobs()
        if not jobs:
            return

    # Determine playwright mode
    if use_playwright is None:
        use_playwright = AUTO_APPLY_PLAYWRIGHT

    print(f"\n🤖 Auto-Apply: threshold={AUTO_APPLY_THRESHOLD}, limit={AUTO_APPLY_LIMIT}, playwright={use_playwright}")

    # If using playwright, we need to pass use_playwright to individual auto_apply calls
    # batch_auto_apply doesn't support this yet, so we do it manually
    if use_playwright:
        from agents.auto_applier import auto_apply
        scored = sorted(
            [j for j in jobs if int(j.get("match_score", j.get("score", 0))) >= AUTO_APPLY_THRESHOLD],
            key=lambda j: int(j.get("match_score", j.get("score", 0))),
            reverse=True,
        )[:AUTO_APPLY_LIMIT]

        results = []
        for job in scored:
            result = auto_apply(job, use_playwright=True)
            results.append(result)
        return results
    else:
        return batch_auto_apply(jobs, limit=AUTO_APPLY_LIMIT, score_threshold=AUTO_APPLY_THRESHOLD)


def _run_auto_apply_from_file():
    """Run auto-apply from curated cache (has match_score)."""
    jobs = _load_curated_jobs()
    if jobs:
        _run_auto_apply(jobs)


def _load_curated_jobs():
    """Load scored jobs from curated_jobs.json. Fails loudly when missing —
    falling back to raw scraped_jobs.json would silently score everything 0
    (raw dicts have no match_score) and auto-apply would no-op."""
    curated_path = BASE_DIR / "curated_jobs.json"
    if not curated_path.exists():
        print("❌ No curated_jobs.json found. Run curation first (simple/crewai mode).")
        return []

    try:
        with open(curated_path, 'r', encoding='utf-8') as f:
            payload = json.load(f)
        jobs = payload.get("jobs", []) if isinstance(payload, dict) else payload
        print(f"✅ Loaded {len(jobs)} curated jobs from {curated_path}")
        return jobs
    except Exception as e:
        print(f"❌ Failed to load curated jobs: {e}")
        return []


def _load_scraped_jobs():
    """Load jobs from scraped_jobs.json."""
    jobs_file = BASE_DIR / "scraped_jobs.json"
    if not jobs_file.exists():
        print("❌ No scraped_jobs.json found.")
        return []

    try:
        with open(jobs_file, 'r', encoding='utf-8') as f:
            jobs = json.load(f)
        print(f"✅ Loaded {len(jobs)} jobs from {jobs_file}")
        return jobs
    except Exception as e:
        print(f"❌ Failed to load jobs: {e}")
        return []


def run_test_tools():
    """Test individual components."""
    print("\n" + "="*60)
    print("🧪 TEST MODE")
    print("="*60)

    print("\n1. Testing Google Sheets connection...")
    if test_connection():
        print("   ✅ Connected")
    else:
        print("   ❌ Failed")

    print("\n2. Testing scraper (single board)...")
    from agents.scrapper import test_individual_scraper
    jobs = test_individual_scraper("Remotive", debug=True)
    print(f"   ✅ Found {len(jobs)} jobs")

    print("\n3. Testing resume generation...")
    if jobs:
        from tools.resume_generator import generate_resume_for_job
        path = generate_resume_for_job(jobs[0], skip_existing=False)
        print(f"   {'✅' if path else '❌'} Resume: {path}")

    print("\n4. Testing cover letter generation...")
    if jobs:
        from agents.gemini_tools import generate_cover_letter, _load_cv_profile
        selected_cv_path = jobs[0].get('selected_cv_path', '') or None
        cv_profile = _load_cv_profile(selected_cv_path)
        cl = generate_cover_letter(
            jobs[0].get('job_title', ''),
            jobs[0].get('company', ''),
            jobs[0].get('summary', ''),
            os.getenv("APPLICANT_NAME", "Mubashir"),
            jobs[0].get('tech_stack', ''),
            cv_profile,
            selected_cv_path=selected_cv_path
        )
        print(f"   ✅ Cover letter: {len(cl)} chars")
        print(f"   Preview: {cl[:150]}...")


def run_auto_apply_cli(playwright=False):
    """CLI entry point for auto-apply."""
    print("\n" + "="*60)
    print("🤖 AUTO-APPLY MODE")
    print("="*60)

    jobs = _load_curated_jobs()
    if not jobs:
        print("❌ No curated jobs found. Run scrape + curation first.")
        return

    _run_auto_apply(jobs, use_playwright=playwright)


def run_resume_generation():
    """Generate resumes for top jobs."""
    print("\n" + "="*60)
    print("📝 RESUME GENERATION MODE")
    print("="*60)

    jobs = _load_curated_jobs()
    if not jobs:
        print("❌ No curated jobs found.")
        return

    from tools.resume_generator import generate_resume_for_job

    scored = sorted(
        [j for j in jobs if int(j.get("match_score", 0)) >= 70],
        key=lambda j: int(j.get("match_score", 0)),
        reverse=True,
    )[:5]

    for job in scored:
        path = generate_resume_for_job(job)
        status = "✅" if path else "❌"
        print(f"   {status} {job['job_title']} at {job['company']}")


# =============================================================================
# CLI ENTRY POINT
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Remote Job Agent")
    parser.add_argument(
        "mode",
        nargs="?",
        choices=["crewai", "simple", "test", "apply", "resume"],
        default=os.getenv("RUN_MODE", "crewai"),
        help="Run mode (default: crewai)"
    )
    parser.add_argument(
        "--playwright",
        action="store_true",
        help="Use Playwright auto-fill for apply mode"
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=AUTO_APPLY_THRESHOLD,
        help=f"Minimum score to apply (default: {AUTO_APPLY_THRESHOLD})"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=AUTO_APPLY_LIMIT,
        help=f"Max jobs to apply (default: {AUTO_APPLY_LIMIT})"
    )

    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"🚀 REMOTE JOB AGENT — Mode: {args.mode}")
    print(f"{'='*60}")

    if args.mode == "simple":
        run_simple_scraper()
    elif args.mode == "test":
        run_test_tools()
    elif args.mode == "apply":
        run_auto_apply_cli(playwright=args.playwright)
    elif args.mode == "resume":
        run_resume_generation()
    else:
        run_pipeline()


if __name__ == "__main__":
    main()