"""
tools/embedding_matcher.py
Semantic job matching with sentence-transformers + FAISS.
Phase 2 feature — optional, gracefully skipped if not installed.

Usage:
    pip install sentence-transformers faiss-cpu
"""

import os
import json
import hashlib
import math
import tempfile
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

# JSON, not pickle. The cache is `{section name: [float, ...]}` — pure data, so
# a pickle bought nothing except the ability to execute arbitrary code on load:
# `pickle.load` runs whatever `__reduce__` the file names, with the privileges of
# whoever reads it. The path came from `CV_EMBEDDINGS_PATH` in `.env` and
# defaulted to the repo root, i.e. a writable location, so anyone able to put a
# file there (a shared volume, a restored backup, a different vulnerability, a
# planted artifact) got code execution the next time curation scored a job. It
# was the ONLY pickle/eval/exec sink in the repo; tests/test_embedding_cache.py
# now scans for any of them coming back.
#
# The format change is silent-by-default in the wrong direction — a missing or
# unreadable cache degrades to keyword-only scoring — so a legacy pickle is
# reported rather than quietly ignored. See _legacy_pickle_notice.
_CV_EMBEDDINGS_DEFAULT = "cv_embeddings.json"
_LEGACY_PICKLE_NAME = "cv_embeddings.pkl"

_cv_emb_path = os.getenv("CV_EMBEDDINGS_PATH", _CV_EMBEDDINGS_DEFAULT)
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
_model_name = None


def _get_model():
    global _model, _model_name
    if SENTENCE_AVAILABLE and (_model is None or _model_name != EMBEDDING_MODEL):
        _model = SentenceTransformer(EMBEDDING_MODEL)
        _model_name = EMBEDDING_MODEL
    return _model


def embed_text(text: str) -> Optional[list]:
    """Convert text to embedding vector."""
    model = _get_model()
    if not model:
        return None
    return model.encode(text).tolist()


def _legacy_pickle_notice(path: Path) -> None:
    """Say so when a pre-JSON cache is being ignored, instead of degrading quietly.

    Without this, an operator who upgrades with a working `cv_embeddings.pkl`
    gets keyword-only scoring and no signal at all — the exact failure README
    warns about, now caused by our own format change.
    """
    candidates = [path if path.suffix.lower() == ".pkl" else None, BASE_DIR / _LEGACY_PICKLE_NAME]
    for candidate in candidates:
        if candidate is not None and candidate.exists():
            print(
                f"⚠️ Ignoring legacy pickle cache {candidate}. Embeddings are JSON now "
                f"(the pickle format could execute code on load). Rebuild with: "
                f"python -m tools.embedding_matcher"
            )
            return


def _is_pickle_shaped(path: Path) -> bool:
    """Protocol 2+ pickles start with \x80; older ones with '(' or '}'."""
    try:
        with open(path, "rb") as handle:
            return handle.read(1) in (b"\x80", b"(", b"}")
    except OSError:
        return False


def load_cv_embeddings(path: Optional[Path] = None) -> Optional[dict]:
    """Load pre-computed CV embeddings from disk as JSON.

    Returns None when there is no usable cache, which callers treat as
    "semantic matching unavailable, score by keyword". Never raises and never
    deserializes anything that can run code.
    """
    path = path or CV_EMBEDDINGS_PATH
    if not path.exists():
        return None
    if path.suffix.lower() == ".pkl" or _is_pickle_shaped(path):
        _legacy_pickle_notice(path)
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return None
    # Shape it or reject it: score_semantic() iterates the values as vectors, so
    # a JSON list or a dict of strings would fail deep inside the scorer with an
    # error that does not mention this file.
    if not isinstance(data, dict):
        return None
    for key, vector in data.items():
        if not isinstance(key, str) or not isinstance(vector, list):
            return None
        if not all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in vector):
            return None
    return data


def save_cv_embeddings(embeddings: dict, path: Optional[Path] = None):
    """Save CV embeddings to disk as JSON.

    Round-trips exactly: Python's json encoder writes floats with repr(), which
    is the shortest string that parses back to the same double, so a saved
    embedding reloads bit-for-bit.
    """
    path = path or CV_EMBEDDINGS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(embeddings, handle)


# Managed per-file caches are separate from the legacy bare-vector JSON API.
# A bare cache cannot prove which CV/model produced it and is never substituted
# for a selected CV. One stable slot per resolved path bounds growth on edits.
EMBEDDING_CACHE_DIR = BASE_DIR / "cache" / "cv_embeddings"
EMBEDDING_CACHE_VERSION = 1


def _valid_embeddings(data) -> bool:
    """Reject empty, non-finite or mixed-dimension section vectors."""
    if not isinstance(data, dict) or not data:
        return False
    dimension = None
    for section, vector in data.items():
        if not isinstance(section, str) or not isinstance(vector, list) or not vector:
            return False
        if not all(
            isinstance(v, (int, float)) and not isinstance(v, bool)
            and math.isfinite(v) for v in vector
        ):
            return False
        if dimension is not None and len(vector) != dimension:
            return False
        dimension = len(vector)
    return True


class CVEmbeddingCache:
    """Lazy embeddings for the exact CV used for keyword scoring.

    Hash the source bytes, not mtime/size, so in-place edits invalidate both
    memory and disk caches. Model name and cache schema are also part of the
    identity. No parsing LLM is used: extraction is local PDF/DOCX text reading.
    Instantiate once per curation run to memoize failures without retrying a
    missing model for every job; the next run can retry a recovered dependency.
    """

    def __init__(self, cache_dir: Optional[Path] = None):
        self.cache_dir = Path(cache_dir) if cache_dir is not None else EMBEDDING_CACHE_DIR
        self._memory = {}
        self._notices = set()

    def warn_once(self, path: Path, reason: str) -> None:
        """Report a CV-specific degradation once per run without CV contents."""
        key = (str(path), reason)
        if key not in self._notices:
            self._notices.add(key)
            print(f"Semantic matching: {path.name}: {reason}")

    def cache_path(self, cv_path) -> Path:
        path = Path(cv_path)
        if not path.is_absolute():
            path = BASE_DIR / path
        path = path.resolve()
        slot = hashlib.sha256(str(path).encode("utf-8")).hexdigest()
        return self.cache_dir / f"{slot}.json"

    def get(self, cv_path) -> Optional[dict]:
        """Return validated sections or None (explicit keyword-only fallback)."""
        path = Path(cv_path)
        if not path.is_absolute():
            path = BASE_DIR / path
        path = path.resolve()
        if not SENTENCE_AVAILABLE or not FAISS_AVAILABLE:
            self.warn_once(path, "optional semantic dependencies unavailable; using keyword-only scoring")
            return None
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            self.warn_once(path, "CV unreadable; using keyword-only scoring")
            return None
        identity = {
            "version": EMBEDDING_CACHE_VERSION,
            "cv_sha256": digest,
            "model": EMBEDDING_MODEL,
        }
        key = str(path)
        cached = self._memory.get(key)
        if cached is not None and cached[0] == identity:
            return cached[1]

        # Memoize unsuccessful work for this source/model only. Never return
        # a previous CV version's vectors after a failed rebuild.
        self._memory[key] = (identity, None)
        target = self.cache_path(path)
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
            if (isinstance(payload, dict) and payload.get("identity") == identity
                    and _valid_embeddings(payload.get("embeddings"))):
                embeddings = payload["embeddings"]
                self._memory[key] = (identity, embeddings)
                return embeddings
        except (OSError, ValueError, TypeError):
            pass

        try:
            from tools.cv_parser import extract_cv_text
            text = extract_cv_text(str(path))
            if not text or not text.strip():
                self.warn_once(path, "no extractable CV text; using keyword-only scoring")
                return None
            embeddings = compute_cv_embeddings(text)
            if not _valid_embeddings(embeddings):
                self.warn_once(path, "no usable embeddings; using keyword-only scoring")
                return None
            # Do not label vectors as current if the file changed during text
            # extraction/encoding. A subsequent call will see the new digest.
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                self.warn_once(path, "CV changed during embedding; using keyword-only scoring")
                return None
        except Exception as exc:
            self.warn_once(path, f"embedding failed ({type(exc).__name__}); using keyword-only scoring")
            return None

        self._memory[key] = (identity, embeddings)
        # Atomic replacement prevents readers seeing a partial JSON file.
        # Temporary files are owner-readable only and never contain raw CV text.
        temporary = None
        try:
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=target.parent, suffix=".tmp", delete=False
            ) as handle:
                temporary = Path(handle.name)
                json.dump({"identity": identity, "embeddings": embeddings}, handle, allow_nan=False)
            os.replace(temporary, target)
        except OSError:
            self.warn_once(path, "disk cache unavailable; using in-memory embeddings for this run")
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
        return embeddings


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


def score_semantic(job: dict, cv_embeddings: dict) -> Optional[float]:
    """
    Score a job's relevance to CV using semantic similarity.
    Returns 0-100 score.

    Args:
        job: job dict with 'job_title', 'summary', 'tech_stack'
        cv_embeddings: pre-computed CV embeddings

    Returns:
        float score 0-100, or None when scoring could not be performed.
        A genuine 0 is a computed mismatch, not an unavailable score.
    """
    if not SENTENCE_AVAILABLE or not FAISS_AVAILABLE or not cv_embeddings:
        return None

    model = _get_model()
    if not model:
        return None

    # Build job text
    job_text = " ".join([
        job.get("job_title") or "",
        job.get("summary") or "",
        job.get("tech_stack") or "",
    ])

    if not job_text.strip():
        return None

    try:
        job_embedding = model.encode(job_text)
        job_vec = np.array(job_embedding, dtype=np.float32).reshape(1, -1)
        faiss.normalize_L2(job_vec)
        dim = job_vec.shape[1]

        # Compare against each CV section (job vector normalized once;
        # per-section FAISS index is tiny — dim is fixed so reuse it)
        scores = []
        weights = []
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
            weights.append(weight)

        if scores:
            result = float(sum(scores) / sum(weights))
            return max(0.0, min(result, 100.0)) if math.isfinite(result) else None

    except Exception as e:
        print(f"Semantic scoring failed ({type(e).__name__}); using keyword-only scoring")

    return None


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
    embeddings = CVEmbeddingCache().get(p)
    if not embeddings:
        return None
    # Compatibility export for tools using load_cv_embeddings(). Curation uses
    # only the managed, source/model-validated cache, never this bare mapping.
    save_cv_embeddings(embeddings)
    print(f"CV embeddings saved to {CV_EMBEDDINGS_PATH}")
    return CV_EMBEDDINGS_PATH


if __name__ == "__main__":
    import sys
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    build_cv_index_from_file(arg)
