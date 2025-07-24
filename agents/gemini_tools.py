import os
from dotenv import load_dotenv
import google.generativeai as genai
from fpdf import FPDF
from datetime import datetime
import re
import json

# --- Load environment variables from .env file ---
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise Exception("❌ Gemini API key not set! Please add GEMINI_API_KEY to your .env file.")

# --- Configure Gemini globally ---
genai.configure(api_key=GEMINI_API_KEY)

def generate_cover_letter(job_title, company, job_description, applicant_name="Mubashir"):
    """
    Generate a concise, enthusiastic, and tailored cover letter for a specific job using Gemini.
    """
    try:
        print(f"🤖 Calling Gemini API for: {job_title} at {company}")
        
        prompt = f"""Write a concise, enthusiastic, and tailored cover letter for the following job.
Mention the company and job title. Highlight relevant skills (Node, Django, React, etc if relevant).
{"Sign as " + applicant_name if applicant_name else ""}

JOB TITLE: {job_title}
COMPANY: {company}
JOB DESCRIPTION: {job_description}
"""
        
        model = genai.GenerativeModel("gemini-2.0-flash")
        
        # Add retry logic
        max_retries = 3
        for attempt in range(max_retries):
            try:
                print(f"  Attempt {attempt + 1}/{max_retries}")
                response = model.generate_content(prompt)
                
                if response and response.text:
                    print("✅ Gemini API call successful!")
                    return response.text.strip()
                else:
                    print("⚠️ Empty response from Gemini")
                    
            except Exception as e:
                print(f"❌ Gemini API error (attempt {attempt + 1}): {e}")
                if attempt == max_retries - 1:  # Last attempt
                    raise e
                
        # If all retries failed
        raise Exception("All Gemini API attempts failed")
        
    except Exception as e:
        print(f"❌ Gemini generation failed: {e}")
        
        # Return fallback cover letter
        fallback = f"""
Dear Hiring Manager,

I am writing to express my interest in the {job_title} position at {company}. With my background in software engineering and experience with modern development technologies, I am confident I can contribute effectively to your team.

I have experience working with Node.js, Django, React, and other modern web technologies. {job_description[:100]}...

I am excited about the possibility of joining {company} and would welcome the opportunity to discuss how my skills can benefit your team.

Thank you for your consideration.

Best regards,
{applicant_name}
        """.strip()
        
        print("📝 Using fallback cover letter due to Gemini failure")
        return fallback

# Add this new function for better CrewAI integration
def generate_cover_letter_from_job_data(job_data_json):
    """
    Generate cover letter from job data JSON (for CrewAI tools)
    """
    try:
        print("📝 Parsing job data for cover letter generation...")
        
        # Parse job data
        if isinstance(job_data_json, str):
            job_data = json.loads(job_data_json)
        else:
            job_data = job_data_json
            
        # Handle if it's a list of jobs
        if isinstance(job_data, list) and len(job_data) > 0:
            job = job_data[0]  # Take the first/best job
        else:
            job = job_data
        
        # Extract job details
        job_title = job.get('job_title', 'Software Developer')
        company = job.get('company', 'the company')
        job_description = job.get('summary', job.get('description', 'Exciting development opportunity'))
        
        print(f"📋 Extracted: {job_title} at {company}")
        
        # Generate cover letter
        cover_letter = generate_cover_letter(job_title, company, job_description, "Mubashir")
        
        # Optionally save as PDF
        try:
            pdf_path = save_cover_letter_pdf(cover_letter, job_title)
            print(f"📄 PDF saved: {pdf_path}")
        except Exception as pdf_error:
            print(f"⚠️ PDF save failed: {pdf_error}")
        
        return cover_letter
        
    except Exception as e:
        error_msg = f"Cover letter generation from job data failed: {e}"
        print(f"❌ {error_msg}")
        return f"Error: {error_msg}"

def sanitize_filename(s):
    # Remove characters that are invalid in filenames
    return re.sub(r'[\\/*?:"<>|]', "", s)

def save_cover_letter_pdf(text, job_title, folder="cover_letters"):
    """
    Save the cover letter as a PDF file with job title and timestamp.
    """
    try:
        os.makedirs(folder, exist_ok=True)
        now = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"{sanitize_filename(job_title)}_{now}.pdf"
        filepath = os.path.join(folder, filename)

        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", size=12)
        # MultiCell for line wrapping
        pdf.multi_cell(0, 10, text)
        pdf.output(filepath)
        print(f"✅ Cover letter saved to: {filepath}")
        return filepath
    except Exception as e:
        print(f"❌ PDF save error: {e}")
        return None

# Test function
def test_gemini_with_debug():
    """Test Gemini with detailed debugging"""
    print("🧪 Testing Gemini with debug info...")
    print(f"API Key present: {bool(GEMINI_API_KEY)}")
    print(f"API Key length: {len(GEMINI_API_KEY) if GEMINI_API_KEY else 0}")
    
    test_job_data = [{
        "job_title": "Full Stack Developer", 
        "company": "TestCorp",
        "summary": "We need a skilled developer with React and Node.js experience."
    }]
    
    result = generate_cover_letter_from_job_data(test_job_data)
    print(f"Result length: {len(result)}")
    print("First 200 chars:", result[:200])

# --- Example usage ---
if __name__ == "__main__":
    test_gemini_with_debug()
