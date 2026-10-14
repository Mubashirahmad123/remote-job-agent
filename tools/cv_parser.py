"""
tools/cv_parser.py
Extracts structured profile from PDF/DOCX CVs.
Uses LLM fallback chain (Gemini → Groq → Mistral → GLM → Ollama).
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
GLM_MODEL = os.getenv("GLM_MODEL", "glm-4")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
MISTRAL_MODEL = os.getenv("MISTRAL_MODEL", "mistral-medium-latest")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1")
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "")  # required for Ollama Cloud, empty = local server

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

# GLM (fallback 3) is plain HTTP against Zhipu's OpenAI-compatible endpoint.
# The zhipuai SDK is NOT used: it pins pyjwt<2.9.0 while crewai pins
# pyjwt>=2.13.0, and having both makes requirements.txt unsatisfiable.
# See the module docstring of tools/glm_client.py before reintroducing it.
try:
    from tools import glm_client as _glm
    GLM_AVAILABLE = _glm.is_available(GLM_API_KEY)
except ImportError:
    try:
        import glm_client as _glm  # direct script run: tools/ is sys.path[0]
        GLM_AVAILABLE = _glm.is_available(GLM_API_KEY)
    except ImportError:
        GLM_AVAILABLE = False

try:
    import requests
    OLLAMA_AVAILABLE = True
    MISTRAL_AVAILABLE = bool(MISTRAL_API_KEY)
    GROQ_AVAILABLE = bool(GROQ_API_KEY)
except ImportError:
    OLLAMA_AVAILABLE = False
    MISTRAL_AVAILABLE = False
    GROQ_AVAILABLE = False


def _call_gemini(prompt: str) -> str:
    if not GEMINI_AVAILABLE:
        raise Exception("Gemini not available")
    if _USE_NEW_GENAI:
        response = _GENAI_CLIENT.models.generate_content(model="gemini-2.5-flash", contents=prompt)
    else:
        response = genai.GenerativeModel("gemini-2.5-flash").generate_content(prompt)
    if response and response.text:
        return response.text.strip()
    raise Exception("Empty response")


def _call_glm(prompt: str) -> str:
    """Call GLM over its OpenAI-compatible HTTP endpoint (no zhipuai SDK)."""
    if not GLM_AVAILABLE:
        raise Exception("GLM not available")
    return _glm.call_glm(prompt, api_key=GLM_API_KEY, model=GLM_MODEL)


def _call_mistral(prompt: str) -> str:
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
    raise Exception("Empty response")


def _parse_with_llm(prompt: str, task: str = "cv_parsing") -> str:
    """Try Gemini → Groq → Mistral → GLM → Ollama."""
    errors = []
    try:
        return _call_gemini(prompt)
    except Exception as e:
        errors.append(f"Gemini: {e}")
    if GROQ_AVAILABLE:
        try:
            return _call_groq(prompt)
        except Exception as e:
            errors.append(f"Groq: {e}")
    if MISTRAL_AVAILABLE:
        try:
            return _call_mistral(prompt)
        except Exception as e:
            errors.append(f"Mistral: {e}")
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
    """Load cached profile if it exists and is recent (< 7 days).

    Never trusts an empty-shell entry (no name + no skills + no experience):
    that is a recorded FAILED parse, not a profile. The 2026-10-03 incident ran
    for days because exactly such a file was served as a valid cached profile
    and every job scored 0 against it. A shell is treated as a cache miss so
    the caller re-parses instead of silently scoring against nothing.
    """
    cache_path = _get_cache_path(cv_path)
    if not cache_path.exists():
        return None
    try:
        age = (datetime.now() - datetime.fromtimestamp(cache_path.stat().st_mtime)).days
        if age > 7:
            return None
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if _is_empty_shell(data):
            print(f"⚠️ Ignoring cached CV profile '{cache_path.name}': empty shell from a "
                  f"failed parse (no name/skills/experience). Re-parsing.")
            return None
        return data
    except Exception:
        return None


def _save_cached_profile(cv_path: str, profile: dict):
    """Save profile to cache. Refuses to persist an empty shell.

    Caching a failed parse as if it were valid data is the 2026-10-03 bug:
    the shell outlived the transient LLM outage that produced it and broke
    every scoring run for days. Raises CVParseError instead of writing.
    """
    if _is_empty_shell(profile):
        raise CVParseError(
            "Refusing to cache an empty CV profile (no name, no skills, no "
            "experience) — that is a failed parse, not a profile."
        )
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

class CVParseError(Exception):
    """Raised when CV parsing fails or produces an empty, unusable profile.

    Callers must treat this as "no profile available" — never as an
    empty-but-valid profile. An empty shell flowing downstream silently
    turned every job score into 0 for days (2026-10-03 incident).
    """


def _is_empty_shell(profile) -> bool:
    """True when a profile carries no usable signal: no name, no skills
    AND no experience. This is the three-field check used to diagnose the
    2026-10-03 zero-score incident; it means parsing FAILED, not that the
    CV is sparse — a real parse always yields at least one of the three.
    """
    if not isinstance(profile, dict):
        return True
    return (
        not profile.get("name")
        and not profile.get("skills")
        and not profile.get("experience")
    )


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
    
    Raises:
        CVParseError: if no text could be extracted from the file, or if
            parsing yields an empty profile (no name AND no skills AND no
            experience). An empty result is a FAILED parse and is never
            cached or returned as if it were valid — a cached empty shell
            silently scored every job 0 for days (2026-10-03 incident).
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
        raise CVParseError(
            f"Could not extract any text from '{cv_path}' — the file is "
            "corrupt, empty, or not a readable PDF/DOCX."
        )
    
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
    parse_error = None
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
        parse_error = f"LLM returned invalid JSON: {e}"
        parsed = {}
    except Exception as e:
        print(f"⚠️ LLM parsing failed: {e}")
        parse_error = str(e)
        parsed = {}
    
    # Validate
    profile = _validate_profile(parsed)
    
    # Empty-shell gate (2026-10-03 incident): no name AND no skills AND no
    # experience means parsing FAILED — a real parse always yields at least
    # one of the three. Never cache it, never return it as if it were valid;
    # a cached shell silently scored every job 0 for days.
    if _is_empty_shell(profile):
        cause = parse_error or "no name, no skills and no experience were extracted"
        print("❌ CV parse produced an empty profile — refusing to cache or return it.")
        print(f"   Cause: {cause}")
        print("   Check LLM provider availability (Gemini/Groq/Mistral/GLM/Ollama)")
        print(f"   and that '{cv_path}' is a readable PDF/DOCX.")
        raise CVParseError(
            f"CV parse produced an empty profile for '{cv_path}' — refusing to "
            f"cache or return it. Cause: {cause}"
        )
    
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