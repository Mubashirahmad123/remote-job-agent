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

# --- CrewAI Tools (Fixed for your gemini_tools.py) ---
@tool("Scrapes remote job boards for jobs")
def scrape_tool() -> str:
    """
    Scrapes remote job boards for developer jobs.
    Returns a JSON string containing job data.
    """
    print("🔍 Scraping jobs from multiple boards...")
    jobs = scrape_all(debug=False)
    print(f"✅ Found {len(jobs)} jobs")
    
    # Return as JSON string for better CrewAI compatibility
    return json.dumps(jobs)

@tool("Processes scraped jobs and saves to Google Sheet")
def process_jobs_tool(scraped_jobs: str) -> str:
    """
    Processes scraped jobs JSON string, curates them, and saves to Google Sheet.
    
    Args:
        scraped_jobs: JSON string of scraped jobs from scrape_tool
    """
    print(f"📝 Processing jobs...")
    
    try:
        # Parse jobs from JSON string
        jobs = json.loads(scraped_jobs) if isinstance(scraped_jobs, str) else scraped_jobs
        
        if not jobs:
            return "No jobs to process"
        
        print(f"Processing {len(jobs)} jobs...")
        
        # Use curator to process jobs
        result = curate(jobs)
        
        if isinstance(result, dict):
            return f"Successfully processed jobs: {result.get('message', 'Jobs processed')}"
        else:
            return f"Jobs processed: {result}"
            
    except json.JSONDecodeError as e:
        error_msg = f"Failed to parse job data: {str(e)}"
        print(f"❌ {error_msg}")
        return error_msg
    except Exception as e:
        error_msg = f"Job processing failed: {str(e)}"
        print(f"❌ {error_msg}")
        return error_msg

@tool("Generates cover letter from job data")
def generate_cover_letter_tool(job_data: str) -> str:
    """
    Generates a personalized cover letter from job data using Gemini AI.
    
    Args:
        job_data: JSON string containing job information
    """
    print(f"✍️ Generating cover letter with improved error handling...")
    
    try:
        # Use the new function that handles all the parsing
        from agents.gemini_tools import generate_cover_letter_from_job_data
        
        result = generate_cover_letter_from_job_data(job_data)
        print("✅ Cover letter generated successfully!")
        return result
        
    except Exception as e:
        error_msg = f"Cover letter tool failed: {str(e)}"
        print(f"❌ {error_msg}")
        return error_msg

        # Fallback cover letter
        fallback = f"""
Dear Hiring Manager,

I am writing to express my interest in the software developer position at your company. With my background in software engineering and experience with modern development technologies, I am confident I can contribute effectively to your team.

I have experience working with Node.js, Django, React, and other modern web technologies. I'm particularly interested in remote development opportunities and would love to contribute to your team's success.

Thank you for your consideration.

Best regards,
Mubashir
        """.strip()
        
        return fallback

# --- Enhanced Tool for PDF Generation ---
@tool("Generates cover letter with PDF save")
def generate_cover_letter_with_pdf_tool(job_data: str) -> str:
    """
    Generates a personalized cover letter and saves it as PDF.
    
    Args:
        job_data: JSON string containing job information
    """
    print(f"✍️ Generating cover letter with PDF save...")
    
    try:
        from agents.gemini_tools import save_cover_letter_pdf
        
        # Parse job data
        jobs = json.loads(job_data) if isinstance(job_data, str) else job_data
        
        if not jobs or len(jobs) == 0:
            return "No jobs available to generate cover letter"
        
        best_job = jobs[0]
        job_title = best_job.get('job_title', 'Software Developer')
        company = best_job.get('company', 'Unknown Company')
        job_description = best_job.get('summary', 'Exciting opportunity in software development')
        applicant_name = "Mubashir"
        
        print(f"Generating cover letter for: {job_title} at {company}")
        
        # Generate cover letter
        cover_letter = generate_cover_letter(job_title, company, job_description, applicant_name)
        
        # Save as PDF
        pdf_path = save_cover_letter_pdf(cover_letter, job_title)
        
        result = f"Cover letter generated and saved as PDF: {pdf_path}\n\n{cover_letter}"
        print("✅ Cover letter generated and saved as PDF!")
        return result
        
    except Exception as e:
        error_msg = f"Cover letter with PDF generation failed: {str(e)}"
        print(f"❌ {error_msg}")
        return error_msg

# --- Agents ---
scraper_agent = Agent(
    role="Senior Job Scraper",
    goal="Scrape the latest remote developer jobs from multiple job boards",
    backstory="You are an expert web scraper who knows how to find the best remote developer jobs from various job boards. You're thorough, efficient, and always find the most relevant opportunities.",
    tools=[scrape_tool],
    llm=llm,
    verbose=True
)

curator_agent = Agent(
    role="Job Curator Specialist", 
    goal="Process and curate jobs, then save them to Google Sheet",
    backstory="You are a meticulous job curator who ensures only high-quality, relevant jobs make it to the final list. You remove duplicates, filter out irrelevant positions, and organize everything perfectly in Google Sheets.",
    tools=[process_jobs_tool],
    llm=llm,
    verbose=True
)

cover_letter_agent = Agent(
    role="Professional Cover Letter Writer",
    goal="Generate personalized, compelling cover letters using AI",
    backstory="You are a professional writer who specializes in creating tailored cover letters that help developers stand out. You use advanced AI to craft compelling, personalized applications and can save them as professional PDF documents.",
    tools=[generate_cover_letter_with_pdf_tool],  # Using PDF version
    llm=llm,
    verbose=True
)

# --- Tasks ---
scrape_task = Task(
    description="Scrape all available remote developer jobs from multiple job boards. Focus on entry-level to mid-level positions that match our tech stack filters (Node.js, Django, React, etc). Return the results as a JSON string.",
    agent=scraper_agent,
    expected_output="A JSON string containing comprehensive list of remote job postings with details like title, company, salary, tech stack, and application URLs."
)

curate_task = Task(
    description="Take the scraped jobs JSON from the previous task and process them by removing duplicates, filtering for quality, and saving the final curated list to our Google Sheet. Prioritize jobs with clear salary information and reputable companies.",
    agent=curator_agent,
    context=[scrape_task],  # Uses output from scrape_task
    expected_output="A confirmation message with the number of unique, high-quality jobs that were successfully saved to Google Sheet."
)

cover_letter_task = Task(
    description="Generate a personalized cover letter for the highest-quality job from the scraped jobs data. Use the job data from the scraping task to create a tailored application letter using Gemini AI. Save it as both text and PDF format. Focus on highlighting relevant skills like Node.js, Django, React, and remote work experience.",
    agent=cover_letter_agent,
    context=[scrape_task],  # Uses output from scrape_task
    expected_output="A professional, tailored cover letter that highlights relevant skills and experience for the selected job opportunity, saved as both text and PDF."
)

# --- Crew ---
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
        
        # Run CrewAI pipeline
        results = crew.kickoff()
        
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
    """Test individual tools"""
    print("🧪 Testing individual tools...")
    
    # Test scraper tool
    print("\n1. Testing scraper tool...")
    jobs_json = scrape_tool()
    jobs = json.loads(jobs_json)
    print(f"   Found {len(jobs)} jobs")
    
    if jobs:
        # Test processing tool
        print("\n2. Testing processing tool...")
        result = process_jobs_tool(jobs_json)
        print(f"   Result: {result}")
        
        # Test cover letter tool with PDF
        print("\n3. Testing cover letter tool with PDF...")
        cover_letter = generate_cover_letter_with_pdf_tool(jobs_json)
        print(f"   Cover letter generated with PDF save")

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
