from dotenv import load_dotenv
import os
import json
from pathlib import Path
from crewai import Agent, Crew, Task, LLM
from crewai.tools import tool
from typing import List, Dict, Any

# --- Import your custom functions ---
from agents.scrapper import scrape_all
from agents.curator import curate
from agents.gemini_tools import generate_cover_letter  # Using your existing file
from tools.sheet_writer import append_rows, test_connection

# --- .env and credentials setup ---
BASE_DIR = Path(__file__).resolve().parent
env_file = BASE_DIR / ".env"

if not env_file.exists():
    print("❌ ERROR: .env file is missing!")
    exit(1)
else:
    load_dotenv(dotenv_path=env_file)

GOOGLE_SERVICE_ACCOUNT = os.getenv("GOOGLE_SERVICE_ACCOUNT")
GOOGLE_SHEETS_ID = os.getenv("GOOGLE_SHEETS_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not GOOGLE_SERVICE_ACCOUNT or not GOOGLE_SHEETS_ID:
    print("❌ ERROR: Missing required environment variables!")
    exit(1)

if not GEMINI_API_KEY:
    print("❌ WARNING: GEMINI_API_KEY is not set. Gemini features will not work.")

print("✅ All good!")
print("Google Service Account:", GOOGLE_SERVICE_ACCOUNT)
print("Google Sheets ID:", GOOGLE_SHEETS_ID)
print("Gemini API Key Loaded:", bool(GEMINI_API_KEY))

# Configure LLM
llm = LLM(
    model=os.environ.get("MODEL", "gemini/gemini-2.0-flash"), 
    api_key=os.getenv("GEMINI_API_KEY")
)

# --- CrewAI Tools (FIXED VERSION) ---
@tool("Scrapes remote job boards for jobs")
def scrape_tool() -> str:
    """
    Scrapes remote job boards for developer jobs.
    Returns a JSON string containing job data.
    """
    print("🔍 Scraping jobs from multiple boards...")
    jobs = scrape_all(debug=False)
    print(f"✅ Found {len(jobs)} jobs")
    
    # Use absolute path to ensure file is created in the right location
    base_dir = Path(__file__).resolve().parent
    output_filename = base_dir / "scraped_jobs.json"
    
    try:
        with open(output_filename, 'w', encoding='utf-8') as f:
            json.dump(jobs, f, indent=2, ensure_ascii=False)
        
        print(f"✅ Jobs saved to: {output_filename}")
        
        # Verify the file was created
        if output_filename.exists():
            file_size = output_filename.stat().st_size
            print(f"✅ File verified: {file_size} bytes")
        
        return json.dumps({
            "jobs": jobs, 
            "count": len(jobs), 
            "file_path": str(output_filename),
            "status": "success"
        }, ensure_ascii=False)
        
    except Exception as e:
        error_msg = f"Failed to save jobs: {e}"
        print(f"❌ {error_msg}")
        return json.dumps({"status": "error", "error": error_msg})

@tool("Processes scraped jobs from a file and saves to Google Sheet")
def process_jobs_tool(file_path: str) -> str:
    """
    Reads job data from a file, curates them, and saves to Google Sheet.
    Args:
        file_path: The path to the JSON file containing scraped jobs.
    """
    print(f"📝 Processing jobs from file: {file_path}...")
    
    # Try multiple possible paths
    base_dir = Path(__file__).resolve().parent
    possible_paths = [
        Path(file_path),
        base_dir / "scraped_jobs.json",
        Path.cwd() / "scraped_jobs.json",
        base_dir / file_path if not Path(file_path).is_absolute() else Path(file_path)
    ]
    
    actual_file_path = None
    for path in possible_paths:
        if path.exists():
            actual_file_path = path
            print(f"✅ Found file at: {actual_file_path}")
            break
    
    if not actual_file_path:
        error_msg = f"❌ File not found. Searched: {[str(p) for p in possible_paths]}"
        print(error_msg)
        return error_msg
    
    try:
        with open(actual_file_path, 'r', encoding='utf-8') as f:
            jobs = json.load(f)
        
        if not jobs:
            return "No jobs to process in the file."
        
        print(f"✅ Loaded {len(jobs)} jobs for processing")
        
        # Curate the jobs
        result = curate(jobs)
        
        print(f"✅ Curation completed with status: {result.get('status', 'unknown')}")
        
        if result["status"] == "success" and result.get("top_jobs"):
            job_count = len(result["top_jobs"])
            return f"Successfully processed and curated {len(jobs)} jobs. Found {job_count} high-quality jobs and saved to Google Sheet."
        else:
            return f"Job processing completed but no high-quality jobs found. Original count: {len(jobs)}"
            
    except FileNotFoundError:
        return f"Error: The file '{actual_file_path}' was not found."
    except json.JSONDecodeError as e:
        return f"Error: Invalid JSON in file: {e}"
    except Exception as e:
        return f"Job processing failed: {str(e)}"

@tool("Generates cover letter with PDF save from a file")
def generate_cover_letter_with_pdf_tool(file_path: str) -> str:
    """
    Reads job data from a file, generates a cover letter for the best job,
    and saves it as a PDF.
    Args:
        file_path: The path to the JSON file containing scraped jobs.
    """
    print(f"✍️ Generating cover letter from file: {file_path}...")
    
    # Try multiple possible paths (same logic as process_jobs_tool)
    base_dir = Path(__file__).resolve().parent
    possible_paths = [
        Path(file_path),
        base_dir / "scraped_jobs.json",
        Path.cwd() / "scraped_jobs.json",
        base_dir / file_path if not Path(file_path).is_absolute() else Path(file_path)
    ]
    
    actual_file_path = None
    for path in possible_paths:
        if path.exists():
            actual_file_path = path
            print(f"✅ Found file at: {actual_file_path}")
            break
    
    if not actual_file_path:
        error_msg = f"❌ File not found for cover letter. Searched: {[str(p) for p in possible_paths]}"
        print(error_msg)
        # Return fallback instead of error
        return generate_fallback_cover_letter()
    
    try:
        with open(actual_file_path, 'r', encoding='utf-8') as f:
            jobs = json.load(f)
        
        if not jobs:
            print("❌ No jobs in file, using fallback")
            return generate_fallback_cover_letter()
        
        print(f"✅ Loaded {len(jobs)} jobs for cover letter generation")
        
        # Find the best job (prioritize jobs with salary info)
        best_job = None
        for job in jobs:
            if job.get('salary') and job['salary'].strip():
                best_job = job
                break
        
        if not best_job:
            best_job = jobs[0]  # Fallback to first job
        
        job_title = best_job.get('job_title', 'Software Developer')
        company = best_job.get('company', 'Unknown Company')
        job_description = best_job.get('summary', 'Exciting opportunity')
        
        print(f"✍️ Generating cover letter for: {job_title} at {company}")
        
        # Import and generate cover letter
        from agents.gemini_tools import save_cover_letter_pdf, generate_cover_letter
        
        cover_letter = generate_cover_letter(job_title, company, job_description, "Mubashir")
        pdf_path = save_cover_letter_pdf(cover_letter, job_title)
        
        return f"✅ Cover letter generated and saved as PDF: {pdf_path}"
        
    except Exception as e:
        print(f"❌ Cover letter generation error: {e}")
        return generate_fallback_cover_letter()

def generate_fallback_cover_letter() -> str:
    """Generate a fallback cover letter when the main process fails"""
    fallback = """Dear Hiring Manager,

I am writing to express my interest in the software developer position at your company. With my background in software engineering and experience with modern development technologies, I am confident I can contribute effectively to your team.

I have experience working with Node.js, Django, React, and other modern web technologies. I'm particularly interested in remote development opportunities and would love to contribute to your team's success.

Thank you for your consideration.

Best regards,
Mubashir"""
    
    try:
        # Try to save fallback as PDF too
        from agents.gemini_tools import save_cover_letter_pdf
        pdf_path = save_cover_letter_pdf(fallback, "Software_Developer")
        return f"✅ Fallback cover letter generated and saved as PDF: {pdf_path}"
    except Exception as e:
        return f"✅ Fallback cover letter generated (PDF save failed: {e})"

# --- Agents (unchanged) ---
scraper_agent = Agent(
    role="Senior Job Scraper",
    goal="Scrape the latest remote developer jobs from multiple job boards",
    backstory="You are an expert web scraper who knows how to find the best remote developer jobs from various job boards. You're thorough, efficient, and always find the most relevant opportunities.",
    tools=[scrape_tool],
    llm=llm,
    verbose=True,
    max_retries=3
)

curator_agent = Agent(
    role="Job Curator Specialist", 
    goal="Process and curate jobs, then save them to Google Sheet",
    backstory="You are a meticulous job curator who ensures only high-quality, relevant jobs make it to the final list. You remove duplicates, filter out irrelevant positions, and organize everything perfectly in Google Sheets.",
    tools=[process_jobs_tool],
    llm=llm,
    verbose=True,
    max_retries=3
)

cover_letter_agent = Agent(
    role="Professional Cover Letter Writer",
    goal="Generate personalized, compelling cover letters using AI",
    backstory="You are a professional writer who specializes in creating tailored cover letters that help developers stand out. You use advanced AI to craft compelling, personalized applications and can save them as professional PDF documents.",
    tools=[generate_cover_letter_with_pdf_tool],
    llm=llm,
    verbose=True,
    max_retries=3
)

# --- Tasks (unchanged) ---
scrape_task = Task(
    description="Scrape all available remote developer jobs from multiple job boards. The tool will save the results to a file named 'scraped_jobs.json'.",
    agent=scraper_agent,
    expected_output="A confirmation message stating the number of jobs found and that they have been saved to 'scraped_jobs.json'."
)

curate_task = Task(
    description="Take the scraped jobs JSON from the previous task and process them by removing duplicates, filtering for quality, and saving the final curated list to our Google Sheet. Use the file path 'scraped_jobs.json' to read the job data.",
    agent=curator_agent,
    context=[scrape_task],
    expected_output="A confirmation message with the number of unique, high-quality jobs that were successfully saved to Google Sheet."
)

cover_letter_task = Task(
    description="Generate a personalized cover letter for the highest-quality job from the scraped jobs data. Use the file 'scraped_jobs.json' to read the job data and create a tailored application letter using Gemini AI. Save it as both text and PDF format. Focus on highlighting relevant skills like Node.js, Django, React, and remote work experience.",
    agent=cover_letter_agent,
    context=[scrape_task],
    expected_output="A professional, tailored cover letter that highlights relevant skills and experience for the selected job opportunity, saved as both text and PDF."
)

# --- Crew (unchanged) ---
crew = Crew(
    agents=[scraper_agent, curator_agent, cover_letter_agent],
    tasks=[scrape_task, curate_task, cover_letter_task],
    verbose=True
)

def run_pipeline():
    """Run the complete job scraping and processing pipeline"""
    print("🚀 Starting CrewAI Job Pipeline...")
    
    try:
        # Test Google Sheets connection first
        print("🔍 Testing Google Sheets connection...")
        if not test_connection():
            print("❌ Google Sheets connection failed!")
            return False
        
        # Add debug info
        print(f"📁 Current working directory: {Path.cwd()}")
        print(f"📁 Script directory: {Path(__file__).resolve().parent}")
        
        # Run CrewAI pipeline
        results = crew.kickoff()
        
        # Check if files were created
        check_files_after_pipeline()
        
        print("\n" + "="*50)
        print("📊 PIPELINE RESULTS")
        print("="*50)
        print(results)
        
        return True
        
    except Exception as e:
        print(f"❌ Pipeline failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def check_files_after_pipeline():
    """Check if files were created after pipeline execution"""
    base_dir = Path(__file__).resolve().parent
    possible_files = [
        "scraped_jobs.json",
        base_dir / "scraped_jobs.json"
    ]
    
    for file_path in possible_files:
        if Path(file_path).exists():
            print(f"✅ Found jobs file: {file_path}")
            with open(file_path, 'r') as f:
                content = f.read()
                print(f"📊 File size: {len(content)} characters")
                if content:
                    try:
                        data = json.loads(content)
                        print(f"📊 JSON contains: {len(data)} items")
                    except:
                        print("❌ File exists but contains invalid JSON")
            return
    
    print("❌ No jobs file found after pipeline execution")

# Rest of your functions remain the same...
def run_simple_scraper():
    """Run just the scraper without CrewAI (for testing)"""
    print("🔍 Running simple scraper test...")
    
    # Test connection
    if not test_connection():
        print("❌ Google Sheets connection failed!")
        return
    
    # Scrape jobs
    jobs = scrape_all(debug=False)
    
    # Save to sheets
    if jobs:
        print(f"💾 Saving {len(jobs)} jobs to Google Sheets...")
        append_rows(jobs)
        print("✅ Jobs saved successfully!")
        
        # Test cover letter generation with PDF
        if jobs:
            print("✍️ Testing cover letter generation with PDF...")
            best_job = max(jobs, key=lambda x: len(x.get('salary', '')))  # Pick job with salary info
            
            cover_letter = generate_cover_letter(
                best_job.get('job_title', 'Software Developer'),
                best_job.get('company', 'Tech Company'),
                best_job.get('summary', 'Great opportunity'),
                "Mubashir"
            )
            
            # Save as PDF
            from agents.gemini_tools import save_cover_letter_pdf
            pdf_path = save_cover_letter_pdf(cover_letter, best_job.get('job_title', 'Software Developer'))
            
            print(f"✅ Cover letter generated and saved as PDF: {pdf_path}")
    else:
        print("❌ No jobs found")

def test_tools():
    """Test individual tools with the new file-based workflow"""
    print("🧪 Testing individual tools...")
    
    # 1. Test scraper tool - it will now create the file
    print("\n1. Testing scraper tool...")
    scrape_result = scrape_tool()
    print(f"   Scraper tool output: {scrape_result}")

    # Define the filename we expect the scraper to create
    jobs_filename = "scraped_jobs.json"

    # Check if the file was actually created before proceeding
    if os.path.exists(jobs_filename):
        # 2. Test processing tool using the file path
        print("\n2. Testing processing tool...")
        result = process_jobs_tool(jobs_filename)
        print(f"   Processing tool result: {result}")
        
        # 3. Test cover letter tool with PDF using the file path
        print("\n3. Testing cover letter tool with PDF...")
        cover_letter_result = generate_cover_letter_with_pdf_tool(jobs_filename)
        print(f"   Cover letter tool result: {cover_letter_result}")
    else:
        print(f"❌ ERROR in test: The file '{jobs_filename}' was not created by scrape_tool().")

if __name__ == "__main__":
    print("Starting job...")
    
    # Choose which mode to run
    mode = os.getenv("RUN_MODE", "crewai")  # Options: "crewai", "simple", "test"
    
    if mode == "simple":
        run_simple_scraper()
    elif mode == "test":
        test_tools()
    else:
        run_pipeline()
