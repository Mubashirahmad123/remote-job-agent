"""
tools/resume_generator.py
Generates AI-tailored resume PDFs for specific jobs.
Uses Gemini with lightweight fallback (no LLM orchestrator dependency yet).
"""

import os
import json
import re
import hashlib
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from tools.font_utils import UnicodePDF

load_dotenv()

# =============================================================================
# LLM SETUP — with fallback chain
# =============================================================================

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GLM_API_KEY = os.getenv("GLM_API_KEY", "")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1")

# Try to import Gemini (new SDK first, legacy fallback)
try:
    from google import genai as _genai_new
    _GENAI_CLIENT = _genai_new.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
    GEMINI_AVAILABLE = _GENAI_CLIENT is not None
    _USE_NEW_GENAI = True
except ImportError:
    _USE_NEW_GENAI = False
    try:
        import google.generativeai as genai
        if GEMINI_API_KEY:
            genai.configure(api_key=GEMINI_API_KEY)
            GEMINI_AVAILABLE = True
        else:
            GEMINI_AVAILABLE = False
    except ImportError:
        GEMINI_AVAILABLE = False

# Try to import GLM
try:
    from zhipuai import ZhipuAI
    GLM_AVAILABLE = bool(GLM_API_KEY)
except ImportError:
    GLM_AVAILABLE = False

# Try to import Ollama
try:
    import requests
    OLLAMA_AVAILABLE = True
except ImportError:
    OLLAMA_AVAILABLE = False


def _call_gemini(prompt: str, model_name: str = "gemini-2.5-flash") -> str:
    """Call Gemini. Returns text or raises exception on failure."""
    if not GEMINI_AVAILABLE:
        raise Exception("Gemini not available")
    if _USE_NEW_GENAI:
        response = _GENAI_CLIENT.models.generate_content(model=model_name, contents=prompt)
    else:
        response = genai.GenerativeModel(model_name).generate_content(prompt)
    if response and response.text:
        return response.text.strip()
    raise Exception("Gemini returned empty response")


def _call_glm(prompt: str) -> str:
    """Call GLM-4 as fallback."""
    if not GLM_AVAILABLE:
        raise Exception("GLM not available")
    client = ZhipuAI(api_key=GLM_API_KEY)
    response = client.chat.completions.create(
        model="glm-4",
        messages=[{"role": "user", "content": prompt}],
    )
    if response and response.choices:
        return response.choices[0].message.content.strip()
    raise Exception("GLM returned empty response")


def _call_ollama(prompt: str) -> str:
    """Call local Ollama as final fallback."""
    if not OLLAMA_AVAILABLE:
        raise Exception("Ollama not available")
    resp = requests.post(
        f"{OLLAMA_URL}/api/generate",
        json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
        timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()
    if data and "response" in data:
        return data["response"].strip()
    raise Exception("Ollama returned empty response")


def generate_with_fallback(prompt: str, task: str = "resume") -> str:
    """
    Try Gemini → GLM → Ollama in sequence.
    Returns the first successful response.
    """
    errors = []

    # Try Gemini first
    try:
        print(f"  [{task}] Trying Gemini...")
        return _call_gemini(prompt)
    except Exception as e:
        errors.append(f"Gemini: {e}")
        print(f"  [{task}] Gemini failed: {e}")

    # Try GLM fallback
    if GLM_AVAILABLE:
        try:
            print(f"  [{task}] Trying GLM-4...")
            return _call_glm(prompt)
        except Exception as e:
            errors.append(f"GLM: {e}")
            print(f"  [{task}] GLM failed: {e}")

    # Try Ollama final fallback
    if OLLAMA_AVAILABLE:
        try:
            print(f"  [{task}] Trying Ollama ({OLLAMA_MODEL})...")
            return _call_ollama(prompt)
        except Exception as e:
            errors.append(f"Ollama: {e}")
            print(f"  [{task}] Ollama failed: {e}")

    raise Exception(f"All LLM providers failed for {task}: {'; '.join(errors)}")


# =============================================================================
# CV LOADING
# =============================================================================

def _load_cv_profile():
    """Load CV profile from parsed CV."""
    try:
        cv_path = os.getenv("CV_PATH", "").strip()
        if not cv_path:
            return None
        resolved = Path(cv_path)
        if not resolved.is_absolute():
            resolved = Path(__file__).resolve().parents[1] / resolved
        if not resolved.exists():
            return None
        from tools.cv_parser import parse_cv
        return parse_cv(str(resolved))
    except Exception as e:
        print(f"CV profile load failed: {e}")
        return None


def _get_base_resume_text(cv_profile):
    """Get base resume text from the original CV."""
    try:
        cv_path = os.getenv("CV_PATH", "").strip()
        if not cv_path:
            return ""
        resolved = Path(cv_path)
        if not resolved.is_absolute():
            resolved = Path(__file__).resolve().parents[1] / resolved
        if not resolved.exists():
            return ""
        
        # Try extract_cv_text first, fallback to reading raw text
        try:
            from tools.cv_parser import extract_cv_text
            return extract_cv_text(str(resolved))
        except ImportError:
            # Fallback: read PDF/DOCX raw
            if str(resolved).lower().endswith('.pdf'):
                import pdfplumber
                with pdfplumber.open(str(resolved)) as pdf:
                    return "\n".join(page.extract_text() or "" for page in pdf.pages)
            elif str(resolved).lower().endswith('.docx'):
                import docx
                doc = docx.Document(str(resolved))
                return "\n".join([p.text for p in doc.paragraphs])
            else:
                with open(resolved, 'r', encoding='utf-8', errors='ignore') as f:
                    return f.read()
    except Exception as e:
        print(f"Base resume text load failed: {e}")
        return ""


# =============================================================================
# RESUME GENERATION
# =============================================================================

def _build_smart_prompt(job, cv_profile, base_text):
    """
    Build a smart prompt that:
    1. Detects role type from job title
    2. Includes relevant CV sections only
    3. Emphasizes matching skills
    """
    job_title = job.get("job_title", "Software Developer")
    company = job.get("company", "Company")
    tech_stack = job.get("tech_stack", "")
    summary = job.get("summary", "")

    # Detect role category for better tailoring
    title_lower = job_title.lower()
    if any(k in title_lower for k in ["backend", "back-end", "server-side", "api", "node", "python", "java", "go", "rust", "django", "flask", "spring"]):
        role_category = "backend"
        role_hint = "Focus on backend skills: APIs, databases, server-side logic, system design."
    elif any(k in title_lower for k in ["frontend", "front-end", "ui", "react", "vue", "angular", "css", "html", "webpack"]):
        role_category = "frontend"
        role_hint = "Focus on frontend skills: UI/UX, component libraries, state management, performance."
    elif any(k in title_lower for k in ["fullstack", "full-stack", "full stack"]):
        role_category = "fullstack"
        role_hint = "Balance frontend and backend skills. Show end-to-end project ownership."
    elif any(k in title_lower for k in ["mobile", "ios", "android", "react native", "flutter"]):
        role_category = "mobile"
        role_hint = "Focus on mobile development: cross-platform, native modules, app store deployment."
    else:
        role_category = "software"
        role_hint = "Focus on general software engineering: problem solving, clean code, collaboration."

    # Build skill match section
    skill_match = ""
    if cv_profile:
        all_skills = (
            cv_profile.get("skills", []) +
            cv_profile.get("frameworks", []) +
            cv_profile.get("databases", []) +
            cv_profile.get("languages", [])
        )
        job_techs = [t.strip().lower() for t in tech_stack.split(",")] if tech_stack else []
        matched = [s for s in all_skills if any(jt in s.lower() or s.lower() in jt for jt in job_techs)]
        if matched:
            skill_match = f"\nMATCHING SKILLS FROM YOUR CV: {', '.join(matched[:10])}"

    # Smart truncation: take first 4000 chars but break at sentence boundary
    safe_base = base_text[:4500]
    last_period = safe_base.rfind('.')
    if last_period > 3000:
        safe_base = safe_base[:last_period + 1]

    profile_json = json.dumps(cv_profile, indent=2) if cv_profile else "{}"

    prompt = f"""You are an expert resume writer who specializes in ATS-optimized resumes for software developers.

ROLE TYPE: {role_category}
{role_hint}

JOB TITLE: {job_title}
COMPANY: {company}
REQUIRED TECHNOLOGIES: {tech_stack}
JOB DESCRIPTION: {summary}{skill_match}

CANDIDATE PROFILE:
{profile_json}

CANDIDATE CV (relevant sections):
{safe_base}

INSTRUCTIONS:
1. Write a professional summary (2-3 sentences) that directly addresses THIS job's requirements
2. List a "Technical Skills" section with technologies mentioned in the job description FIRST, then others
3. For work experience, rewrite bullet points to emphasize achievements using the job's required tech stack
4. Keep all factual information accurate — do NOT invent companies, dates, or degrees
5. Use strong action verbs and quantify achievements where possible
6. Format as clean markdown with # for name, ## for sections, - for bullet points

Return ONLY the markdown resume. No explanations, no notes.""" 

    return prompt


def generate_tailored_resume(job, cv_profile=None):
    """
    Generate a tailored resume for a specific job using LLM with fallback.
    Returns markdown-style resume text.
    """
    if cv_profile is None:
        cv_profile = _load_cv_profile()

    base_text = _get_base_resume_text(cv_profile)
    prompt = _build_smart_prompt(job, cv_profile, base_text)

    try:
        resume_text = generate_with_fallback(prompt, task="resume_generation")
        # Basic validation
        if not resume_text or len(resume_text) < 200:
            raise Exception("Generated resume too short")
        if "#" not in resume_text and "##" not in resume_text:
            raise Exception("Generated resume missing markdown headers")
        return resume_text
    except Exception as e:
        print(f"Resume generation failed: {e}")
        return _generate_fallback_resume(job, cv_profile)


def _generate_fallback_resume(job, cv_profile):
    """Generate a basic resume using actual CV data when all LLMs fail."""
    name = "Candidate"
    email = ""
    phone = ""
    location = ""
    
    if cv_profile:
        name = cv_profile.get("name", "Candidate")
        email = cv_profile.get("email", "")
        phone = cv_profile.get("phone", "")
        location = cv_profile.get("location", "")

    job_title = job.get("job_title", "Software Developer")
    tech_stack = job.get("tech_stack", "")

    # Extract actual skills from CV
    skills = []
    experience_lines = []
    education_lines = []
    
    if cv_profile:
        skills = (
            cv_profile.get("skills", []) +
            cv_profile.get("frameworks", []) +
            cv_profile.get("databases", []) +
            cv_profile.get("languages", [])
        )
        
        # Build experience from CV data
        for exp in cv_profile.get("experience", []):
            company_name = exp.get("company", "Company")
            role = exp.get("title", "Developer")
            duration = exp.get("duration", "")
            desc = exp.get("description", "")
            experience_lines.append(f"- **{role}** at {company_name} ({duration})")
            if desc:
                experience_lines.append(f"  - {desc[:100]}...")
        
        # Build education from CV data
        for edu in cv_profile.get("education", []):
            degree = edu.get("degree", "Bachelor's Degree")
            school = edu.get("institution", "University")
            year = edu.get("year", "")
            education_lines.append(f"- {degree}, {school} {year}")

    # If no structured data, use generic but relevant lines
    if not experience_lines:
        experience_lines = [
            "- Software Developer at Previous Company",
            "  - Built web applications using modern frameworks",
            "  - Developed RESTful APIs and database solutions",
            "  - Collaborated in agile teams"
        ]
    
    if not education_lines:
        education_lines = ["- Bachelor's degree in Computer Science or related field"]

    contact_line = f"{name}"
    if email:
        contact_line += f" | {email}"
    if phone:
        contact_line += f" | {phone}"
    if location:
        contact_line += f" | {location}"

    resume = f"""# {contact_line}

## Professional Summary
Experienced software developer seeking a {job_title} position. 
{('Proficient in ' + ', '.join(skills[:8]) + '.' if skills else 'Proficient in modern development technologies and best practices.')}

## Technical Skills
{', '.join(skills[:15]) if skills else tech_stack}

## Experience
{chr(10).join(experience_lines)}

## Education
{chr(10).join(education_lines)}

## Note
This is a fallback resume generated because AI services were unavailable. 
Please review and update before submitting.
"""
    return resume


# =============================================================================
# PDF GENERATION — Unicode-safe (imported from font_utils)
# =============================================================================

def _clean_markdown_for_pdf(text: str) -> str:
    """Convert markdown to plain text suitable for PDF."""
    # Remove markdown syntax
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)  # Bold
    text = re.sub(r'\*(.*?)\*', r'\1', text)       # Italic
    text = re.sub(r'`(.*?)`', r'\1', text)         # Code
    text = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', text) # Links
    text = re.sub(r'#{1,6}\s*', '', text)          # Headers
    text = re.sub(r'^\s*[-*]\s*', '• ', text, flags=re.M)  # Bullets
    return text


def save_resume_pdf(resume_text, job_title, company, folder="resumes"):
    """Save the tailored resume as a Unicode-safe PDF."""
    try:
        os.makedirs(folder, exist_ok=True)
        now = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        safe_title = sanitize_filename(job_title)[:40]
        safe_company = sanitize_filename(company)[:20]
        filename = f"{safe_title}_{safe_company}_{now}.pdf"
        filepath = os.path.join(folder, filename)

        pdf = UnicodePDF()
        
        # Parse markdown and render
        lines = resume_text.split("\n")
        in_bullet = False
        
        for line in lines:
            stripped = line.strip()
            
            if not stripped:
                pdf.ln(4)
                in_bullet = False
                continue
            
            # Name/header (first line starting with #)
            if stripped.startswith("# ") and lines.index(line) == 0:
                pdf.set_bold(16)
                pdf.multi_cell(0, 10, stripped[2:])
                pdf.ln(2)
                continue
            
            # Section headers
            if stripped.startswith("## "):
                pdf.set_bold(13)
                pdf.multi_cell(0, 10, stripped[3:])
                pdf.ln(1)
                in_bullet = False
                continue
            
            # Bullet points
            if stripped.startswith("- ") or stripped.startswith("• "):
                pdf.set_normal(10)
                text = stripped[2:]
                pdf.multi_cell(0, 7, f"    • {text}")
                in_bullet = True
                continue
            
            # Indented bullet continuation
            if in_bullet and stripped.startswith("  "):
                pdf.set_normal(10)
                pdf.multi_cell(0, 7, f"      {stripped.strip()}")
                continue
            
            # Regular text
            pdf.set_normal(10)
            pdf.multi_cell(0, 7, stripped)
            in_bullet = False

        pdf.output(filepath)
        print(f"✅ Resume saved to: {filepath}")
        return filepath
        
    except Exception as e:
        print(f"❌ Resume PDF save error: {e}")
        import traceback
        traceback.print_exc()
        return None


# =============================================================================
# DEDUPLICATION & MAIN PIPELINE
# =============================================================================

def _job_fingerprint(job) -> str:
    """Create a unique fingerprint for a job to prevent duplicate resumes."""
    key = f"{job.get('job_title', '')}|{job.get('company', '')}|{job.get('apply_url', '')}"
    return hashlib.md5(key.encode()).hexdigest()


def _existing_resume_for_job(job, folder="resumes") -> str:
    """Check if a resume already exists for this job (last 7 days)."""
    if not os.path.exists(folder):
        return None
    
    fingerprint = _job_fingerprint(job)[:8]
    job_title = sanitize_filename(job.get("job_title", ""))[:20]
    
    # Look for existing files matching this job
    for filename in os.listdir(folder):
        if fingerprint in filename and job_title in filename:
            filepath = os.path.join(folder, filename)
            # Check if file is less than 7 days old
            file_age = datetime.now() - datetime.fromtimestamp(os.path.getmtime(filepath))
            if file_age.days < 7:
                return filepath
    return None


def sanitize_filename(s):
    """Remove characters illegal in filenames."""
    return re.sub(r'[\\/*?:"<>|]', "", s)


def generate_resume_for_job(job, output_folder="resumes", skip_existing=True):
    """
    Full pipeline: generate tailored resume and save as PDF.
    
    Args:
        job: dict with job_title, company, tech_stack, summary, apply_url
        output_folder: where to save PDFs
        skip_existing: if True, return existing resume if < 7 days old
    
    Returns:
        Path to PDF file, or None on failure
    """
    print(f"📝 Generating tailored resume for: {job.get('job_title')} at {job.get('company')}")

    # Check for existing resume
    if skip_existing:
        existing = _existing_resume_for_job(job, output_folder)
        if existing:
            print(f"  ⏭️  Using existing resume (generated {existing})")
            return existing

    cv_profile = _load_cv_profile()
    resume_text = generate_tailored_resume(job, cv_profile)

    if resume_text:
        pdf_path = save_resume_pdf(
            resume_text,
            job.get("job_title", "Software Developer"),
            job.get("company", "Company"),
            output_folder
        )
        return pdf_path

    return None


# =============================================================================
# CLI / TEST
# =============================================================================

if __name__ == "__main__":
    # Test with a sample job
    test_job = {
        "job_title": "Full Stack Developer",
        "company": "TestCorp",
        "tech_stack": "React, Node.js, PostgreSQL",
        "summary": "We need a full stack developer to build our SaaS platform.",
        "apply_url": "https://example.com/job/123"
    }
    
    result = generate_resume_for_job(test_job, skip_existing=False)
    if result:
        print(f"Success! Resume at: {result}")
    else:
        print("Failed to generate resume.")