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
CV_EMBEDDINGS_PATH = Path(os.getenv("CV_EMBEDDINGS_PATH", "cv_embeddings.pkl"))

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
        job.get("job_title", ""),
        job.get("summary", ""),
        job.get("tech_stack", ""),
    ])

    if not job_text.strip():
        return 0

    try:
        job_embedding = model.encode(job_text)

        # Compare against each CV section
        scores = []
        for section_name, cv_emb in cv_embeddings.items():
            cv_vec = np.array(cv_emb).reshape(1, -1)
            job_vec = np.array(job_embedding).reshape(1, -1)

            # Normalize
            faiss.normalize_L2(cv_vec)
            faiss.normalize_L2(job_vec)

            # Cosine similarity
            index = faiss.IndexFlatIP(cv_vec.shape[1])
            index.add(cv_vec)
            similarity, _ = index.search(job_vec, 1)

            weight = 1.0
            if section_name == "experience":
                weight = 1.5
            elif section_name == "skills":
                weight = 1.3
            elif section_name == "education":
                weight = 0.5

            scores.append((similarity[0][0] + 1) * 50 * weight)

        if scores:
            return min(sum(scores) / sum(
                1.5 if s == "experience" else 1.3 if s == "skills" else 0.5
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
