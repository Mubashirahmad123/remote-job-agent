"""
agents/gemini_tools.py
Cover letter generation + markdown job extraction.
Uses LLM fallback chain (Gemini → GLM → Ollama).
"""

import os
import json
import re
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from tools.font_utils import UnicodePDF

load_dotenv()

# =============================================================================
# LLM SETUP — shared fallback chain (same as resume_generator)
# =============================================================================

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GLM_API_KEY = os.getenv("GLM_API_KEY", "")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1")

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

try:
    from zhipuai import ZhipuAI
    GLM_AVAILABLE = bool(GLM_API_KEY)
except ImportError:
    GLM_AVAILABLE = False

try:
    import requests
    OLLAMA_AVAILABLE = True
except ImportError:
    OLLAMA_AVAILABLE = False


def _call_gemini(prompt: str, model_name: str = "gemini-2.5-flash") -> str:
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


def generate_with_fallback(prompt: str, task: str = "cover_letter") -> str:
    """Try Gemini → GLM → Ollama. Returns first success."""
    errors = []

    try:
        print(f"  [{task}] Trying Gemini...")
        return _call_gemini(prompt)
    except Exception as e:
        errors.append(f"Gemini: {e}")
        print(f"  [{task}] Gemini failed: {e}")

    if GLM_AVAILABLE:
        try:
            print(f"  [{task}] Trying GLM-4...")
            return _call_glm(prompt)
        except Exception as e:
            errors.append(f"GLM: {e}")
            print(f"  [{task}] GLM failed: {e}")

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
    """Load the CV profile from the parsed CV."""
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
    except Exception:
        return None


# =============================================================================
# ROLE DETECTION
# =============================================================================

def _detect_role_category(job_title: str) -> tuple:
    """
    Detect role category from job title.
    Returns (category, role_hint, tone)
    """
    title_lower = job_title.lower()
    
    backend_keywords = ["backend", "back-end", "server-side", "api", "node", "python", 
                        "java", "go", "rust", "django", "flask", "spring", "express", 
                        "laravel", "rails", ".net", "c#"]
    frontend_keywords = ["frontend", "front-end", "ui", "react", "vue", "angular", 
                         "css", "html", "webpack", "next.js", "nuxt", "svelte"]
    fullstack_keywords = ["fullstack", "full-stack", "full stack", "mern", "mean", "jamstack"]
    mobile_keywords = ["mobile", "ios", "android", "react native", "flutter", "swift", "kotlin"]
    devops_keywords = ["devops", "sre", "site reliability", "platform", "infrastructure", "cloud"]
    
    if any(k in title_lower for k in backend_keywords):
        return "backend", "Focus on backend engineering: APIs, databases, system design, server optimization.", "backend engineer"
    elif any(k in title_lower for k in frontend_keywords):
        return "frontend", "Focus on frontend engineering: UI/UX, component architecture, state management, performance optimization.", "frontend developer"
    elif any(k in title_lower for k in fullstack_keywords):
        return "fullstack", "Balance frontend and backend skills. Show end-to-end ownership and architecture decisions.", "full stack developer"
    elif any(k in title_lower for k in mobile_keywords):
        return "mobile", "Focus on mobile development: cross-platform frameworks, native modules, app performance.", "mobile developer"
    elif any(k in title_lower for k in devops_keywords):
        return "devops", "Focus on infrastructure: CI/CD, cloud platforms, monitoring, automation.", "DevOps engineer"
    else:
        return "software", "Focus on general software engineering: problem solving, clean code, collaboration.", "software developer"


def _build_skill_section(cv_profile, job_tech_stack: str, role_category: str) -> str:
    """
    Build a personalized skills section that prioritizes job-relevant skills.
    """
    if not cv_profile:
        return ""
    
    all_skills = (
        cv_profile.get("skills", []) +
        cv_profile.get("frameworks", []) +
        cv_profile.get("databases", []) +
        cv_profile.get("languages", [])
    )
    
    if not all_skills:
        return ""
    
    # Match skills against job tech stack
    job_techs = [t.strip().lower() for t in job_tech_stack.split(",")] if job_tech_stack else []
    
    matched = []
    unmatched = []
    
    for skill in all_skills:
        skill_lower = skill.lower()
        is_match = any(jt in skill_lower or skill_lower in jt for jt in job_techs)
        if is_match:
            matched.append(skill)
        else:
            unmatched.append(skill)
    
    # Prioritize matched skills, then add others
    prioritized = matched[:6] + unmatched[:4]
    
    if not prioritized:
        return ""
    
    return f"Relevant skills: {', '.join(prioritized)}."


# =============================================================================
# COVER LETTER GENERATION
# =============================================================================

def generate_cover_letter(job_title, company, job_description, applicant_name="Mubashir", 
                          tech_stack="", cv_profile=None):
    """
    Generate a tailored cover letter with role-specific tone and skill matching.
    Uses LLM fallback chain for reliability.
    """
    try:
        print(f"🤖 Generating cover letter for: {job_title} at {company}")

        # Load CV if not provided
        if cv_profile is None:
            cv_profile = _load_cv_profile()

        # Detect role for proper tone
        role_category, role_hint, role_noun = _detect_role_category(job_title)
        
        # Build personalized skills section
        skills_section = _build_skill_section(cv_profile, tech_stack, role_category)
        
        # Build experience highlight
        experience_section = ""
        if cv_profile and cv_profile.get("experience"):
            # Find most relevant experience
            experiences = cv_profile.get("experience", [])
            if experiences:
                top_exp = experiences[0]
                exp_title = top_exp.get("title", "Developer")
                exp_company = top_exp.get("company", "Previous Company")
                experience_section = f"Most recently, I worked as {exp_title} at {exp_company}."

        prompt = f"""Write a concise, enthusiastic cover letter (150-200 words) for a {role_noun} position.

TONE GUIDANCE: {role_hint}

JOB TITLE: {job_title}
COMPANY: {company}
JOB DESCRIPTION: {job_description[:500]}
{skills_section}
{experience_section}

REQUIREMENTS:
- Open with specific interest in THIS company and THIS role
- Mention 2-3 relevant technologies from the job description that I have experience with
- Show enthusiasm and cultural fit
- Keep it under 200 words
- Sign as {applicant_name}
- Do NOT use generic phrases like "I am writing to express my interest"
- Do NOT mention technologies not relevant to this specific role

Return ONLY the cover letter text, no explanations.""" 

        cover_letter = generate_with_fallback(prompt, task="cover_letter")
        
        # Validate
        if len(cover_letter) < 50:
            raise Exception("Cover letter too short")
        if applicant_name not in cover_letter:
            raise Exception("Cover letter missing applicant name")
            
        print("✅ Cover letter generated successfully!")
        return cover_letter
        
    except Exception as e:
        print(f"❌ Cover letter generation failed: {e}")
        return _generate_fallback_cover_letter(job_title, company, job_description, 
                                               applicant_name, role_category)


def _generate_fallback_cover_letter(job_title, company, job_description, applicant_name, role_category):
    """Generate a role-appropriate fallback cover letter."""
    
    role_phrases = {
        "backend": "backend systems and APIs",
        "frontend": "user interfaces and frontend architecture", 
        "fullstack": "end-to-end web applications",
        "mobile": "mobile applications",
        "devops": "cloud infrastructure and CI/CD pipelines",
        "software": "software solutions"
    }
    
    focus = role_phrases.get(role_category, "software development")
    
    return f"""Dear Hiring Manager,

I'm excited about the {job_title} opportunity at {company}. With hands-on experience building {focus}, I'm confident I can contribute from day one.

{job_description[:150]}...

I'd love to discuss how my background aligns with your team's needs. Thank you for your time and consideration.

Best regards,
{applicant_name}"""


# =============================================================================
# CREWAI INTEGRATION
# =============================================================================

def generate_cover_letter_from_job_data(job_data_json):
    """
    Generate cover letter from job data JSON (for CrewAI tools).
    """
    try:
        print("📝 Parsing job data for cover letter generation...")
        
        if isinstance(job_data_json, str):
            if not job_data_json.strip():
                print("❌ No job data found (empty string)")
                return None
            job_data = json.loads(job_data_json)
        else:
            job_data = job_data_json

        if not job_data:
            print("❌ No job data found")
            return None    
            
        if isinstance(job_data, list) and len(job_data) > 0:
            job = job_data[0]
        else:
            job = job_data
        
        job_title = job.get('job_title', 'Software Developer')
        company = job.get('company', 'the company')
        job_description = job.get('summary', job.get('description', 'Exciting development opportunity'))
        tech_stack = job.get('tech_stack', '')
        
        print(f"📋 Extracted: {job_title} at {company}")
        
        cv_profile = _load_cv_profile()
        cover_letter = generate_cover_letter(job_title, company, job_description, 
                                             "Mubashir", tech_stack, cv_profile)
        
        # Save PDF
        try:
            pdf_path = save_cover_letter_pdf(cover_letter, job_title)
            print(f"📄 PDF saved: {pdf_path}")
        except Exception as pdf_error:
            print(f"⚠️ PDF save failed: {pdf_error}")
        
        return cover_letter
        
    except Exception as e:
        error_msg = f"Cover letter generation failed: {e}"
        print(f"❌ {error_msg}")
        return f"Error: {error_msg}"


# =============================================================================
# MARKDOWN JOB EXTRACTION
# =============================================================================

def extract_jobs_from_markdown(markdown: str) -> list:
    """
    Extract developer jobs from crawler markdown using LLM with fallback.
    """
    if not markdown:
        return []

    prompt = f"""
Extract all job listings from the following content.
Return a JSON array with these fields:
job_title, company, salary, tech_stack, timezone, apply_url, summary, posted_date_iso.

Only include software/developer jobs. Skip senior, lead, principal, staff, manager,
director, and head-of-engineering roles.

Content:
{markdown[:8000]}

Return ONLY valid JSON, no markdown fences and no explanation.
"""

    try:
        text = generate_with_fallback(prompt, task="markdown_extraction")
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I | re.S).strip()
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            parsed = parsed.get("jobs", [])
        return parsed if isinstance(parsed, list) else []
    except Exception as e:
        print(f"❌ Markdown extraction failed: {e}")
        return []


# =============================================================================
# PDF SAVING — Unicode-safe
# =============================================================================

def sanitize_filename(s):
    return re.sub(r'[\\/*?:"<>|]', "", s)


def save_cover_letter_pdf(text, job_title, folder="cover_letters"):
    """Save cover letter as Unicode-safe PDF."""
    try:
        os.makedirs(folder, exist_ok=True)
        now = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"{sanitize_filename(job_title)}_{now}.pdf"
        filepath = os.path.join(folder, filename)

        pdf = UnicodePDF()
        pdf.set_bold(14)
        pdf.multi_cell(0, 10, f"Cover Letter: {job_title}")
        pdf.set_normal(11)
        pdf.multi_cell(0, 8, text)
        pdf.output(filepath)
        
        print(f"✅ Cover letter saved to: {filepath}")
        return filepath
    except Exception as e:
        print(f"❌ PDF save error: {e}")
        return None


# =============================================================================
# TEST
# =============================================================================

def test_cover_letter_generation():
    """Test cover letter with different role types."""
    test_cases = [
        {
            "job_title": "Backend Engineer",
            "company": "Stripe",
            "description": "Build high-performance APIs and payment systems using Python and Go.",
            "tech_stack": "Python, Go, PostgreSQL, Redis, Kubernetes"
        },
        {
            "job_title": "Frontend Developer",
            "company": "Vercel",
            "description": "Build the Next.js platform and developer tools with React and TypeScript.",
            "tech_stack": "React, TypeScript, Next.js, CSS, Vercel"
        },
        {
            "job_title": "Full Stack Developer",
            "company": "StartupXYZ",
            "description": "Own end-to-end features from database to UI.",
            "tech_stack": "Node.js, React, MongoDB, AWS"
        }
    ]
    
    for test in test_cases:
        print(f"\n{'='*50}")
        print(f"Testing: {test['job_title']} at {test['company']}")
        print(f"{'='*50}")
        
        letter = generate_cover_letter(
            test["job_title"],
            test["company"],
            test["description"],
            "Mubashir",
            test["tech_stack"]
        )
        print(f"\nGenerated letter ({len(letter)} chars):")
        print(letter[:300] + "...")


if __name__ == "__main__":
    test_cover_letter_generation()