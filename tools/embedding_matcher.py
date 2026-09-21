"""
tools/embedding_matcher.py
Semantic job matching with sentence-transformers + FAISS.
Phase 2 feature — optional, gracefully skipped if not installed.

Usage:
    pip install sentence-transformers faiss-cpu
"""

import os
import json
import pickle
from pathlib import Path
from typing import Optional, List, Dict
from dotenv import load_dotenv

load_dotenv()

# Graceful import
try:
    from sentence_transformers import SentenceTransformer  # type: ignore
    SENTENCE_AVAILABLE = True
except ImportError:
    SENTENCE_AVAILABLE = False

try:
    import faiss  # type: ignore
    import numpy as np
    FAISS_AVAILABLE = True
except ImportError:
    FAISS_AVAILABLE = False


EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

BASE_DIR = Path(__file__).resolve().parents[1]

_cv_emb_path = os.getenv("CV_EMBEDDINGS_PATH", "cv_embeddings.pkl")
CV_EMBEDDINGS_PATH = Path(_cv_emb_path)
if not CV_EMBEDDINGS_PATH.is_absolute():
    CV_EMBEDDINGS_PATH = BASE_DIR / CV_EMBEDDINGS_PATH

# Shared section weights — single source of truth for numerator and denominator.
SECTION_WEIGHTS = {
    "experience": 1.5,
    "skills": 1.3,
    "education": 0.5,
}
DEFAULT_SECTION_WEIGHT = 1.0


def section_weight(name: str) -> float:
    return SECTION_WEIGHTS.get(name, DEFAULT_SECTION_WEIGHT)

_model = None


def _get_model():
    global _model
    if _model is None and SENTENCE_AVAILABLE:
        _model = SentenceTransformer(EMBEDDING_MODEL)
    return _model


def embed_text(text: str) -> Optional[list]:
    """Convert text to embedding vector."""
    model = _get_model()
    if not model:
        return None
    return model.encode(text).tolist()


def load_cv_embeddings(path: Optional[Path] = None) -> Optional[dict]:
    """
    Load pre-computed CV embeddings from disk.
    """
    path = path or CV_EMBEDDINGS_PATH
    if not path.exists():
        return None
    try:
        with open(path, "rb") as f:
            return pickle.load(f)
    except Exception:
        return None


def save_cv_embeddings(embeddings: dict, path: Optional[Path] = None):
    """Save CV embeddings to disk."""
    path = path or CV_EMBEDDINGS_PATH
    with open(path, "wb") as f:
        pickle.dump(embeddings, f)


def compute_cv_embeddings(cv_text: str) -> Optional[dict]:
    """
    Compute and return embeddings for a CV.
    Splits CV into sections and embeds each section.
    """
    if not SENTENCE_AVAILABLE or not FAISS_AVAILABLE:
        return None

    model = _get_model()
    if not model:
        return None

    sections = _split_cv_sections(cv_text)
    embeddings = {}
    for name, text in sections.items():
        if text.strip():
            embeddings[name] = model.encode(text).tolist()
    return embeddings


def _split_cv_sections(cv_text: str) -> dict:
    """Split CV into logical sections."""
    sections = {}
    current_section = "header"
    current_lines = []

    for line in cv_text.split("\n"):
        lower = line.strip().lower()
        if any(kw in lower for kw in ["experience", "work history", "employment"]):
            if current_lines:
                sections[current_section] = "\n".join(current_lines)
            current_section = "experience"
            current_lines = [line]
        elif any(kw in lower for kw in ["education", "academic"]):
            if current_lines:
                sections[current_section] = "\n".join(current_lines)
            current_section = "education"
            current_lines = [line]
        elif any(kw in lower for kw in ["skills", "technologies", "competencies"]):
            if current_lines:
                sections[current_section] = "\n".join(current_lines)
            current_section = "skills"
            current_lines = [line]
        else:
            current_lines.append(line)

    if current_lines:
        sections[current_section] = "\n".join(current_lines)

    return sections


def score_semantic(job: dict, cv_embeddings: dict) -> float:
    """
    Score a job's relevance to CV using semantic similarity.
    Returns 0-100 score.

    Args:
        job: job dict with 'job_title', 'summary', 'tech_stack'
        cv_embeddings: pre-computed CV embeddings

    Returns:
        float score 0-100
    """
    if not SENTENCE_AVAILABLE or not FAISS_AVAILABLE or not cv_embeddings:
        return 0

    model = _get_model()
    if not model:
        return 0

    # Build job text
    job_text = " ".join([
        job.get("job_title") or "",
        job.get("summary") or "",
        job.get("tech_stack") or "",
    ])

    if not job_text.strip():
        return 0

    try:
        job_embedding = model.encode(job_text)
        job_vec = np.array(job_embedding, dtype=np.float32).reshape(1, -1)
        faiss.normalize_L2(job_vec)
        dim = job_vec.shape[1]

        # Compare against each CV section (job vector normalized once;
        # per-section FAISS index is tiny — dim is fixed so reuse it)
        scores = []
        for section_name, cv_emb in cv_embeddings.items():
            cv_vec = np.array(cv_emb, dtype=np.float32).reshape(1, -1)
            if cv_vec.shape[1] != dim:
                continue

            # Normalize
            faiss.normalize_L2(cv_vec)

            # Cosine similarity
            index = faiss.IndexFlatIP(dim)
            index.add(cv_vec)
            similarity, _ = index.search(job_vec, 1)

            weight = section_weight(section_name)

            scores.append((similarity[0][0] + 1) * 50 * weight)

        if scores:
            return min(sum(scores) / sum(
                section_weight(s)
                for s in cv_embeddings.keys()
            ), 100.0)

    except Exception as e:
        print(f"Semantic scoring failed: {e}")

    return 0


def build_cv_index(cv_text: str, output_path: Optional[Path] = None) -> Optional[Path]:
    """
    Build a FAISS index from CV text and save to disk.
    Returns path to saved index.
    """
    embeddings = compute_cv_embeddings(cv_text)
    if not embeddings:
        return None

    path = output_path or CV_EMBEDDINGS_PATH
    save_cv_embeddings(embeddings, path)
    print(f"CV embeddings saved to {path}")
    return path


def build_cv_index_from_file(cv_path: Optional[str] = None) -> Optional[Path]:
    """Correct way to build embeddings from a PDF/DOCX CV file.

    Uses tools.cv_parser.extract_cv_text (pdfplumber/python-docx) — never
    raw-bytes decode, which produces garbage for PDFs.

    Usage:
        python -m tools.embedding_matcher
        python -c "from tools.embedding_matcher import build_cv_index_from_file; build_cv_index_from_file('my_cv.pdf')"
    """
    import os as _os

    resolved = cv_path or _os.getenv("CV_PATH", "my_cv.pdf")
    p = Path(resolved)
    if not p.is_absolute():
        p = BASE_DIR / p
    from tools.cv_parser import extract_cv_text
    text = extract_cv_text(str(p))
    if not text or not text.strip():
        print(f"❌ Could not extract text from {p}")
        return None
    return build_cv_index(text)


if __name__ == "__main__":
    import sys
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    build_cv_index_from_file(arg)
