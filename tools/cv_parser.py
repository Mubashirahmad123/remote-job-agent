import json
import os
import re
from pathlib import Path;

import google.generativeai as genai

def extract_cv_text(cv_path: str) -> str:
    """Extract raw text from a PDF or DOCX CV."""
    path = Path(cv_path)
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages)

    if suffix == ".docx":
        import docx
        document = docx.Document(path)
        return "\n".join(paragraph.text for paragraph in document.paragraphs)

    raise ValueError("CV must be a .pdf or .docx file")


def parse_cv(cv_path: str) -> dict:
    text = extract_cv_text(cv_path)

    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    model = genai.GenerativeModel("gemini-2.5-flash")  # ← create model instance

    prompt = f"""
Extract structured data from this CV. Return ONLY valid JSON, no explanation:
{{
    "name": "",
    "years_experience": 0,
    "skills": [],
    "frameworks": [],
    "databases": [],
    "preferred_titles": [],
    "seniority": "junior or mid",
    "languages": []
}}

CV TEXT:
{text[:4000]}
"""
    response = model.generate_content(prompt)
    raw = response.text.replace("```json", "").replace("```", "").strip()

    # Fix common Gemini JSON issues: trailing commas before ] or }
    raw = re.sub(r",\s*([\]}])", r"\1", raw)
    # Remove trailing comma before newline/EOF
    raw = re.sub(r",\s*$", "", raw)

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"⚠️ CV JSON parsing failed: {e}")
        # Return a minimal default profile so CV matching can still operate
        return {
            "name": "",
            "years_experience": 0,
            "skills": [],
            "frameworks": [],
            "databases": [],
            "preferred_titles": [],
            "seniority": "mid",
            "languages": [],
        }