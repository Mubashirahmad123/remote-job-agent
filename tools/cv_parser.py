"""
tools/cv_parser.py
Extracts structured profile from PDF/DOCX CVs.
Uses LLM fallback chain (Gemini → GLM → Ollama).
Caches parsed profile to avoid re-parsing.
"""

import os
import json
import re
import hashlib
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# =============================================================================
# LLM FALLBACK SETUP
# =============================================================================

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GLM_API_KEY = os.getenv("GLM_API_KEY", "")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1")

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


def _call_gemini(prompt: str) -> str:
    if not GEMINI_AVAILABLE:
        raise Exception("Gemini not available")
    model = genai.GenerativeModel("gemini-2.5-flash")
    response = model.generate_content(prompt)
    if response and response.text:
        return response.text.strip()
    raise Exception("Empty response")


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
    raise Exception("Empty response")


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
    raise Exception("Empty response")


def _parse_with_llm(prompt: str, task: str = "cv_parsing") -> str:
    """Try Gemini → GLM → Ollama."""
    errors = []
    try:
        return _call_gemini(prompt)
    except Exception as e:
        errors.append(f"Gemini: {e}")
    if GLM_AVAILABLE:
        try:
            return _call_glm(prompt)
        except Exception as e:
            errors.append(f"GLM: {e}")
    if OLLAMA_AVAILABLE:
        try:
            return _call_ollama(prompt)
        except Exception as e:
            errors.append(f"Ollama: {e}")
    raise Exception(f"All LLMs failed: {'; '.join(errors)}")


# =============================================================================
# TEXT EXTRACTION
# =============================================================================

def extract_cv_text(cv_path: str) -> str:
    """
    Extract raw text from PDF or DOCX CV.
    Returns empty string on failure (never None).
    """
    path = Path(cv_path)
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        try:
            import pdfplumber
            with pdfplumber.open(path) as pdf:
                text = "\n".join(page.extract_text() or "" for page in pdf.pages)
                return text.strip()
        except Exception as e:
            print(f"❌ PDF extraction failed: {e}")
            return ""

    if suffix == ".docx":
        try:
            import docx
            document = docx.Document(path)
            text = "\n".join(p.text for p in document.paragraphs if p.text)
            return text.strip()
        except ImportError:
            print("❌ python-docx not installed. Run: pip install python-docx")
            return ""
        except Exception as e:
            print(f"❌ DOCX extraction failed: {e}")
            return ""

    raise ValueError(f"Unsupported file format: '{suffix}'. Only .pdf and .docx are supported.")


# =============================================================================
# CACHING
# =============================================================================

def _get_cache_path(cv_path: str) -> Path:
    """Get cache file path based on CV file hash."""
    file_hash = hashlib.md5(open(cv_path, "rb").read()).hexdigest()[:16]
    cache_dir = Path(__file__).resolve().parents[1] / "cache"
    cache_dir.mkdir(exist_ok=True)
    return cache_dir / f"cv_profile_{file_hash}.json"


def _load_cached_profile(cv_path: str) -> dict:
    """Load cached profile if it exists and is recent (< 7 days)."""
    cache_path = _get_cache_path(cv_path)
    if not cache_path.exists():
        return None
    try:
        age = (datetime.now() - datetime.fromtimestamp(cache_path.stat().st_mtime)).days
        if age > 7:
            return None
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save_cached_profile(cv_path: str, profile: dict):
    """Save profile to cache."""
    try:
        cache_path = _get_cache_path(cv_path)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(profile, f, indent=2)
    except Exception as e:
        print(f"⚠️ Cache save failed: {e}")


# =============================================================================
# SMART TEXT TRUNCATION
# =============================================================================

def _smart_truncate(text: str, max_chars: int = 6000) -> str:
    """
    Truncate text at sentence boundary to avoid cutting mid-sentence.
    6000 chars ≈ 1500 tokens — safe for Gemini Flash's 1M context.
    """
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars]
    # Try to find last sentence boundary
    for boundary in [".\n", ". ", "\n\n", "\n"]:
        idx = truncated.rfind(boundary)
        if idx > max_chars * 0.7:  # Only break if we keep 70%+ of text
            return truncated[:idx + len(boundary)].strip()
    return truncated.strip()


# =============================================================================
# PROFILE VALIDATION
# =============================================================================

def _validate_profile(profile: dict) -> dict:
    """Ensure profile has all required fields with correct types."""
    required_fields = {
        "name": str,
        "email": str,
        "phone": str,
        "location": str,
        "years_experience": (int, float),
        "skills": list,
        "frameworks": list,
        "databases": list,
        "languages": list,
        "preferred_titles": list,
        "experience": list,
        "education": list,
        "seniority": str,
    }
    
    defaults = {
        "name": "",
        "email": "",
        "phone": "",
        "location": "",
        "years_experience": 0,
        "skills": [],
        "frameworks": [],
        "databases": [],
        "languages": [],
        "preferred_titles": [],
        "experience": [],
        "education": [],
        "seniority": "mid",
    }
    
    validated = {}
    for field, expected_type in required_fields.items():
        value = profile.get(field)
        if value is None or not isinstance(value, expected_type):
            validated[field] = defaults[field]
        else:
            validated[field] = value
    return validated


# =============================================================================
# MAIN PARSER
# =============================================================================

def parse_cv(cv_path: str, use_cache: bool = True, return_raw: bool = False) -> dict:
    """
    Parse a CV into structured JSON.
    
    Args:
        cv_path: Path to .pdf or .docx file
        use_cache: If True, use cached profile if available
        return_raw: If True, also include '_raw_text' in output
    
    Returns:
        Parsed CV profile dict with all required fields
    """
    # Check cache
    if use_cache:
        cached = _load_cached_profile(cv_path)
        if cached:
            print("✅ Using cached CV profile")
            return cached
    
    # Extract text
    text = extract_cv_text(cv_path)
    if not text:
        print("❌ Could not extract text from CV")
        return _validate_profile({})
    
    # Smart truncate
    safe_text = _smart_truncate(text, max_chars=6000)
    
    # Build prompt with explicit schema
    prompt = f"""Extract structured data from this CV. Return ONLY valid JSON.

REQUIRED SCHEMA:
{{
    "name": "Full name",
    "email": "email@example.com",
    "phone": "+1234567890",
    "location": "City, Country",
    "years_experience": 0,
    "seniority": "junior|mid|senior",
    "skills": ["skill1", "skill2"],
    "frameworks": ["React", "Django"],
    "databases": ["PostgreSQL", "MongoDB"],
    "languages": ["Python", "JavaScript"],
    "preferred_titles": ["Full Stack Developer", "Backend Engineer"],
    "experience": [
        {{
            "title": "Job Title",
            "company": "Company Name",
            "duration": "2022-2024",
            "description": "Brief description of responsibilities"
        }}
    ],
    "education": [
        {{
            "degree": "Bachelor of Science",
            "institution": "University Name",
            "year": "2022"
        }}
    ]
}}

RULES:
- Use empty string "" or empty list [] if field not found
- years_experience: number only (0 if not specified)
- seniority: infer from experience level ("junior", "mid", "senior")
- experience: extract 3 most recent roles with descriptions
- education: extract all degrees with institutions
- Do NOT invent information not in the CV

CV TEXT:
{safe_text}
"""
    
    # Parse with LLM fallback
    try:
        raw_response = _parse_with_llm(prompt, task="cv_parsing")
        
        # Clean markdown fences
        raw_response = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_response, flags=re.I | re.S).strip()
        
        # Fix trailing commas
        raw_response = re.sub(r",\s*([\]}])", r"\1", raw_response)
        raw_response = re.sub(r",\s*$", "", raw_response)
        
        parsed = json.loads(raw_response)
        
    except json.JSONDecodeError as e:
        print(f"⚠️ JSON parsing failed: {e}")
        print(f"   Raw response: {raw_response[:200]}...")
        parsed = {}
    except Exception as e:
        print(f"⚠️ LLM parsing failed: {e}")
        parsed = {}
    
    # Validate
    profile = _validate_profile(parsed)
    
    # Add metadata
    profile["_parsed_at"] = datetime.now().isoformat()
    profile["_source_file"] = str(cv_path)
    if return_raw:
        profile["_raw_text"] = text[:2000]  # First 2000 chars for reference
    
    # Cache
    if use_cache:
        _save_cached_profile(cv_path, profile)
    
    print(f"✅ CV parsed: {profile['name'] or 'Unknown'} | {profile['years_experience']} years | {len(profile['skills'])} skills")
    return profile


# =============================================================================
# TEST
# =============================================================================

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        cv_file = sys.argv[1]
    else:
        cv_file = os.getenv("CV_PATH", "cv.pdf")
    
    if not Path(cv_file).exists():
        print(f"❌ CV file not found: {cv_file}")
        print("Usage: python tools/cv_parser.py <path_to_cv.pdf>")
        sys.exit(1)
    
    profile = parse_cv(cv_file, return_raw=True)
    print(f"\n{'='*60}")
    print("PARSED PROFILE:")
    print(f"{'='*60}")
    print(json.dumps(profile, indent=2))