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
GLM_MODEL = os.getenv("GLM_MODEL", "glm-4")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
MISTRAL_MODEL = os.getenv("MISTRAL_MODEL", "mistral-medium-latest")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1")
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "")  # required for Ollama Cloud, empty = local server

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
    MISTRAL_AVAILABLE = bool(MISTRAL_API_KEY)
    GROQ_AVAILABLE = bool(GROQ_API_KEY)
except ImportError:
    OLLAMA_AVAILABLE = False
    MISTRAL_AVAILABLE = False
    GROQ_AVAILABLE = False


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
        model=GLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
    )
    if response and response.choices:
        return response.choices[0].message.content.strip()
    raise Exception("GLM returned empty response")


def _call_mistral(prompt: str) -> str:
    """Call Mistral API (OpenAI-compatible endpoint, no extra dep needed)."""
    if not MISTRAL_AVAILABLE:
        raise Exception("Mistral not available")
    resp = requests.post(
        "https://api.mistral.ai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {MISTRAL_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": MISTRAL_MODEL,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, AttributeError):
        raise Exception(f"Mistral returned unexpected response: {data}")


def _call_groq(prompt: str) -> str:
    """Call Groq API (OpenAI-compatible endpoint, no extra dep needed)."""
    if not GROQ_AVAILABLE:
        raise Exception("Groq not available")
    resp = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": GROQ_MODEL,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, AttributeError):
        raise Exception(f"Groq returned unexpected response: {data}")


def _call_ollama(prompt: str) -> str:
    """Call Ollama (local server or Ollama Cloud) as final fallback."""
    if not OLLAMA_AVAILABLE:
        raise Exception("Ollama not available")
    headers = {"Authorization": f"Bearer {OLLAMA_API_KEY}"} if OLLAMA_API_KEY else {}
    resp = requests.post(
        f"{OLLAMA_URL}/api/generate",
        headers=headers,
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
    Try Gemini → Groq → Mistral → GLM → Ollama in sequence.
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

    # Try Groq fallback
    if GROQ_AVAILABLE:
        try:
            print(f"  [{task}] Trying Groq ({GROQ_MODEL})...")
            return _call_groq(prompt)
        except Exception as e:
            errors.append(f"Groq: {e}")
            print(f"  [{task}] Groq failed: {e}")

    # Try Mistral fallback
    if MISTRAL_AVAILABLE:
        try:
            print(f"  [{task}] Trying Mistral ({MISTRAL_MODEL})...")
            return _call_mistral(prompt)
        except Exception as e:
            errors.append(f"Mistral: {e}")
            print(f"  [{task}] Mistral failed: {e}")

    # Try GLM fallback
    if GLM_AVAILABLE:
        try:
            print(f"  [{task}] Trying GLM ({GLM_MODEL})...")
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

def _resolve_cv_path(cv_path_override=None):
    """Resolve which CV file to load: explicit pick first, then CV_PATH env."""
    if cv_path_override:
        resolved = Path(cv_path_override)
        if not resolved.is_absolute():
            resolved = Path(__file__).resolve().parents[1] / resolved
        if resolved.exists():
            return resolved
        print(f"Selected CV not found: {cv_path_override} — falling back to CV_PATH")
    cv_path = os.getenv("CV_PATH", "").strip()
    if not cv_path:
        return None
    resolved = Path(cv_path)
    if not resolved.is_absolute():
        resolved = Path(__file__).resolve().parents[1] / resolved
    return resolved if resolved.exists() else None


def _load_cv_profile(cv_path_override=None):
    """Load CV profile from parsed CV.

    Uses the per-job picked CV (curator's ``selected_cv_path``) when one is
    given and exists on disk; falls back to ``CV_PATH`` otherwise so
    single-CV setups keep working unchanged.
    """
    try:
        resolved = _resolve_cv_path(cv_path_override)
        if resolved is None:
            return None
        from tools.cv_parser import parse_cv
        return parse_cv(str(resolved))
    except Exception as e:
        print(f"CV profile load failed: {e}")
        return None


def _get_base_resume_text(cv_profile, cv_path_override=None):
    """Get base resume text from the original CV (picked CV first, CV_PATH fallback)."""
    try:
        resolved = _resolve_cv_path(cv_path_override)
        if resolved is None:
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

INSTRUCTIONS FOR 1-PAGE ATS RESUME:
1. Keep content ultra-concise to guarantee a 1-PAGE fit.
2. Write a professional summary (2-3 sentences max, ~40 words) directly aligned with this job.
3. Include a "Technical Skills" section grouped logically (Languages, Frameworks, Tools/Cloud).
4. Include top 2-3 work experiences with max 3 bullet points each, highlighting measurable impact.
5. Use standard markdown headers: # for Candidate Name, ## for Sections, ### for Role | Company | Dates.
6. Return ONLY markdown text, no preamble or extra notes."""

    return prompt


def generate_tailored_resume(job, cv_profile=None):
    """
    Generate a tailored resume for a specific job using LLM with fallback.
    Returns markdown-style resume text.

    When ``cv_profile`` is not given, the job's ``selected_cv_path`` (set by
    the curator's multi-CV pick) is used first, falling back to ``CV_PATH``.
    """
    selected_cv_path = job.get("selected_cv_path", "") if isinstance(job, dict) else ""
    if cv_profile is None:
        cv_profile = _load_cv_profile(selected_cv_path or None)

    base_text = _get_base_resume_text(cv_profile, selected_cv_path or None)
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
        
        for exp in cv_profile.get("experience", []):
            company_name = exp.get("company", "Company")
            role = exp.get("title", "Developer")
            duration = exp.get("duration", "")
            desc = exp.get("description", "")
            experience_lines.append(f"### {role} | {company_name} | {duration}")
            if desc:
                experience_lines.append(f"- {desc[:120]}")
        
        for edu in cv_profile.get("education", []):
            degree = edu.get("degree", "Bachelor's Degree")
            school = edu.get("institution", "University")
            year = edu.get("year", "")
            education_lines.append(f"- **{degree}**, {school} ({year})")

    if not experience_lines:
        experience_lines = [
            f"### Software Developer | Technology Company | 2022 - Present",
            "  - Developed web applications and services using modern frameworks",
            "  - Built RESTful APIs and database solutions",
            "  - Collaborated in agile development teams"
        ]
    
    if not education_lines:
        education_lines = ["- Bachelor's degree in Computer Science or related field"]

    resume = f"""# {name}

## Professional Summary
Results-driven software developer seeking a {job_title} position. Proficient in modern development tools, clean architecture, and building scalable software solutions.

## Technical Skills
{', '.join(skills[:15]) if skills else tech_stack}

## Experience
{chr(10).join(experience_lines)}

## Education
{chr(10).join(education_lines)}
"""
    return resume


# =============================================================================
# PDF GENERATION — ATS-Optimized Single-Page Layout Engine
# =============================================================================

def _clean_markdown_for_pdf(text: str) -> str:
    """Convert markdown to plain text suitable for PDF."""
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
    text = re.sub(r'\*(.*?)\*', r'\1', text)
    text = re.sub(r'`(.*?)`', r'\1', text)
    text = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', text)
    text = re.sub(r'#{1,6}\s*', '', text)
    text = re.sub(r'^\s*[-*]\s*', '• ', text, flags=re.M)
    return text


def save_resume_pdf(resume_text, job_title, company, folder="resumes", cv_profile=None, cv_path=None, cv_tag=None):
    """Save the tailored resume as a single-page ATS-optimized PDF.

    ``cv_profile``/``cv_path`` carry the curator's picked CV so the header
    contact block matches the profile the resume was tailored from. When
    omitted, the primary ``CV_PATH`` profile is used (backward compatible).
    ``cv_tag`` (picked-CV stem) is embedded in the filename so the 7-day
    reuse cache can tell profiles apart.
    """
    try:
        os.makedirs(folder, exist_ok=True)
        now = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        safe_title = sanitize_filename(job_title)[:40]
        safe_company = sanitize_filename(company)[:20]
        tag_suffix = f"_{cv_tag}" if cv_tag else ""
        filename = f"{safe_title}_{safe_company}{tag_suffix}_{now}.pdf"
        filepath = os.path.join(folder, filename)

        # Multi-pass rendering configs to guarantee 1-page fit
        passes = [
            {"margin": 12, "body_size": 9.5, "bullet_lh": 4.2},
            {"margin": 10, "body_size": 9.0, "bullet_lh": 3.8},
            {"margin": 8,  "body_size": 8.5, "bullet_lh": 3.5},
        ]

        # Parse candidate profile for header contact info (prefer the picked CV)
        if cv_profile is None:
            cv_profile = _load_cv_profile(cv_path)
        profile_name = cv_profile.get("name", "").strip() if cv_profile else ""
        candidate_name = profile_name or "Candidate"
        email = cv_profile.get("email", "") if cv_profile else ""
        phone = cv_profile.get("phone", "") if cv_profile else ""
        location = cv_profile.get("location", "") if cv_profile else ""
        linkedin = cv_profile.get("linkedin", "") if cv_profile else ""
        github = cv_profile.get("github", "") if cv_profile else ""

        for pass_idx, pass_cfg in enumerate(passes):
            pdf = UnicodePDF(margin=pass_cfg["margin"])
            body_size = pass_cfg["body_size"]
            bullet_lh = pass_cfg["bullet_lh"]

            lines = resume_text.split("\n")
            header_rendered = False

            # The profile name is ground truth for the header. The LLM's "# Name"
            # line is only a fallback when the profile has no name, and a
            # mismatch is logged (never silently ship a hallucinated name).
            # Either way the "# ..." line itself is consumed as the header.
            if lines and lines[0].strip().startswith("# "):
                top_line = lines[0].strip()[2:].strip()
                if top_line:
                    llm_name = top_line.split("|")[0].strip()
                    if not profile_name:
                        candidate_name = llm_name or candidate_name
                    elif llm_name and llm_name.lower() != profile_name.lower():
                        print(f"⚠️ Resume header name mismatch: profile={profile_name!r} llm={llm_name!r} — using profile")
                    header_rendered = True

            contact_parts = [p for p in [email, phone, location, linkedin, github] if p]
            if not contact_parts:
                print("⚠️ Resume header has no contact info (profile missing email/phone/location)")
            pdf.add_header(candidate_name, title=job_title, contact_info=contact_parts)

            idx = 1 if header_rendered else 0
            while idx < len(lines):
                line = lines[idx]
                stripped = line.strip()

                if not stripped:
                    idx += 1
                    continue

                # Section Headers (## Section)
                if stripped.startswith("## "):
                    sec_title = stripped[3:].strip()
                    pdf.add_section_header(sec_title)
                    idx += 1
                    continue

                # Subheaders (### Role | Company | Dates | Location)
                if stripped.startswith("### "):
                    sub_txt = stripped[4:].strip()
                    parts = [p.strip() for p in sub_txt.split("|")]
                    role = parts[0] if len(parts) > 0 else ""
                    comp = parts[1] if len(parts) > 1 else ""
                    dates = parts[2] if len(parts) > 2 else ""
                    loc = parts[3] if len(parts) > 3 else ""
                    pdf.add_experience_header(role, comp, dates, loc)
                    idx += 1
                    continue

                # Bullet points (- or •)
                if stripped.startswith("- ") or stripped.startswith("• "):
                    bullet_text = stripped[2:].strip()
                    bullet_text = re.sub(r'\*\*(.*?)\*\*', r'\1', bullet_text)
                    bullet_text = re.sub(r'\*(.*?)\*', r'\1', bullet_text)
                    pdf.add_bullet(bullet_text, font_size=body_size, line_height=bullet_lh)
                    idx += 1
                    continue

                # Bold line pattern **Role** at Company (Dates)
                if stripped.startswith("**") and " at " in stripped:
                    m = re.match(r'\*\*(.*?)\*\*\s*at\s*(.*?)(?:\s*\((.*?)\))?$', stripped)
                    if m:
                        role, comp, dates = m.group(1), m.group(2), m.group(3) or ""
                        pdf.add_experience_header(role, comp, dates)
                        idx += 1
                        continue

                # Regular text line
                clean_text = re.sub(r'\*\*(.*?)\*\*', r'\1', stripped)
                clean_text = re.sub(r'\*(.*?)\*', r'\1', clean_text)
                pdf.set_normal(body_size)
                pdf.multi_cell(pdf.get_printable_width(), bullet_lh, clean_text)
                pdf.ln(1)
                idx += 1

            if pdf.page_count <= 1:
                pdf.output(filepath)
                print(f"[OK] ATS 1-page Resume saved to: {filepath} (Pass {pass_idx+1})")
                return filepath

        # If Pass 3 still exceeds 1 page, output pass 3
        pdf.output(filepath)
        print(f"[OK] ATS Resume saved to: {filepath} (Pass 3 compact)")
        return filepath

    except Exception as e:
        print(f"[ERROR] Resume PDF save error: {e}")
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


def _cv_cache_tag(job) -> str:
    """Short tag identifying which CV a cached resume was built from.

    Returns the sanitized picked-CV stem (e.g. ``cv_backend``) or ``""`` for
    single-CV setups. Embedded in generated filenames so the 7-day reuse
    cache never serves a resume tailored from a different profile.
    """
    selected = job.get("selected_cv_path", "") if isinstance(job, dict) else ""
    if not selected:
        return ""
    stem = Path(selected).stem
    return sanitize_filename(stem)[:30]


def _existing_resume_for_job(job, folder="resumes") -> str:
    """Check if a resume already exists for this job (last 7 days).

    When the job carries a picked CV, only a resume built from that same CV
    (tag embedded in the filename) is reused — never another profile's PDF.
    """
    if not os.path.exists(folder):
        return None

    fingerprint = _job_fingerprint(job)[:8]
    job_title = sanitize_filename(job.get("job_title", ""))[:20]
    cv_tag = _cv_cache_tag(job)

    # Look for existing files matching this job
    for filename in os.listdir(folder):
        if fingerprint in filename and job_title in filename:
            if cv_tag and cv_tag not in filename:
                continue  # built from a different CV profile — don't reuse
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

    # Use the curator's picked CV when one was recorded for this job;
    # otherwise fall back to the primary CV (single-CV setups).
    selected_cv_path = job.get("selected_cv_path", "") if isinstance(job, dict) else ""
    cv_profile = _load_cv_profile(selected_cv_path or None)
    resume_text = generate_tailored_resume(job, cv_profile)

    if resume_text:
        pdf_path = save_resume_pdf(
            resume_text,
            job.get("job_title", "Software Developer"),
            job.get("company", "Company"),
            output_folder,
            cv_profile=cv_profile,
            cv_path=selected_cv_path or None,
            cv_tag=_cv_cache_tag(job) or None,
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