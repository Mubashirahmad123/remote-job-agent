"""
tools/cv_library.py
Multi-CV library: discovers CV files, parses them, and picks the best fit per job.

Usage:
    CV_DIR=cvs/   — folder containing cv_backend.pdf, cv_fullstack.pdf, etc.
    CV_PATH=my_cv.pdf  — single-CV fallback (used when CV_DIR is not set)

The library is stateless across runs (each pipeline run re-parses as needed,
but individual CVs are cached to disk via cv_parser's md5-hash caching).
"""

import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# =============================================================================
# DOMAIN TAG EXTRACTION
# =============================================================================

# Tags extracted from filenames to label each CV.
# Order matters: more specific tags are checked first.
_DOMAIN_TAGS = [
    "fullstack", "full_stack", "full-stack",
    "backend", "back_end", "back-end",
    "frontend", "front_end", "front-end",
    "mobile",
    "devops",
    "python",
    "react",
    "node",
    "java",
    "senior",
    "junior",
    "general",
]

_DOMAIN_NORMALISE = {
    "full_stack":  "fullstack",
    "full-stack":  "fullstack",
    "back_end":    "backend",
    "back-end":    "backend",
    "front_end":   "frontend",
    "front-end":   "frontend",
}


def _extract_domain_tags(filename: str) -> List[str]:
    """
    Extract zero or more domain tags from a filename.
    e.g. 'cv_backend_python.pdf'  -> ['backend', 'python']
         'my_cv.pdf'              -> ['general']
    """
    stem = Path(filename).stem.lower()
    # replace separators so we can match whole words
    normalised = re.sub(r"[-_ ]", " ", stem)
    found = []
    for tag in _DOMAIN_TAGS:
        tag_norm = re.sub(r"[-_ ]", " ", tag)
        if re.search(r"\b" + re.escape(tag_norm) + r"\b", normalised):
            canonical = _DOMAIN_NORMALISE.get(tag, tag)
            if canonical not in found:
                found.append(canonical)
    return found if found else ["general"]


# =============================================================================
# CV LIBRARY
# =============================================================================

class CVLibrary:
    """
    Discovers and manages a collection of CV files.

    Attributes
    ----------
    cvs : list[dict]
        Each entry: {
            'path':    str,          # absolute path to CV file
            'name':    str,          # basename
            'tags':    list[str],    # domain tags extracted from filename
            'profile': dict | None,  # parsed CV profile (lazy-loaded)
        }
    """

    def __init__(self, cv_dir: Optional[str] = None):
        """
        Parameters
        ----------
        cv_dir : str | None
            Path to the CV folder. If None, falls back to the CV_DIR env var,
            and then to CV_PATH (single-file mode).
        """
        self.cvs: List[Dict] = []
        self._pick_cache: Dict[str, Dict] = {}  # job_fingerprint -> result
        self._matcher_cache: Dict[str, object] = {}  # cv path -> CVMatcher (profiles are immutable after parse)
        self._cv_dir: Optional[Path] = None

        self._load(cv_dir)

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def _load(self, cv_dir: Optional[str]):
        """Discover CV files and register them (profiles not yet parsed)."""
        dir_path = cv_dir or os.getenv("CV_DIR", "").strip()

        if dir_path:
            resolved = Path(dir_path)
            if not resolved.is_absolute():
                # Resolve relative to project root (parent of tools/)
                resolved = Path(__file__).resolve().parents[1] / resolved
            if resolved.is_dir():
                self._cv_dir = resolved
                self._discover_dir(resolved)
                return
            else:
                print(f"Warning: CV_DIR '{resolved}' not found -- falling back to CV_PATH")

        # Single-file fallback
        single = os.getenv("CV_PATH", "").strip()
        if single:
            single_path = Path(single)
            if not single_path.is_absolute():
                single_path = Path(__file__).resolve().parents[1] / single_path
            if single_path.exists():
                self._register(single_path)
            else:
                print(f"Warning: CV_PATH '{single}' not found")

    def _discover_dir(self, directory: Path):
        """Walk directory and register all PDF/DOCX files."""
        extensions = {".pdf", ".docx"}
        files = sorted(
            f for f in directory.iterdir()
            if f.is_file() and f.suffix.lower() in extensions
        )
        if not files:
            print(f"Warning: No PDF/DOCX files found in CV_DIR '{directory}'")
            return
        for f in files:
            self._register(f)

    def _register(self, path: Path):
        """Add a CV file to the registry."""
        tags = _extract_domain_tags(path.name)
        self.cvs.append({
            "path":    str(path),
            "name":    path.name,
            "tags":    tags,
            "profile": None,  # lazy-parsed on first use
        })
        print(f"   Registered CV: {path.name} (tags: {', '.join(tags)})")

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def _ensure_parsed(self, entry: Dict):
        """Parse and cache profile for a single CV entry (idempotent)."""
        if entry["profile"] is None:
            try:
                from tools.cv_parser import parse_cv
                entry["profile"] = parse_cv(entry["path"])
            except Exception as e:
                print(f"Warning: Could not parse CV '{entry['name']}': {e}")
                entry["profile"] = {}

    def parse_all(self):
        """Pre-parse all registered CVs (optional -- pick_best also does this lazily)."""
        for entry in self.cvs:
            self._ensure_parsed(entry)

    # ------------------------------------------------------------------
    # Picking
    # ------------------------------------------------------------------

    def pick_best(self, job: Dict) -> Tuple[Optional[str], Optional[Dict], int]:
        """
        Select the best-fit CV for a given job.

        Returns
        -------
        (cv_path, cv_profile, score)
            cv_path:    absolute path string, or None if library is empty.
            cv_profile: parsed profile dict, or None.
            score:      keyword match score (0-100).
        """
        if not self.cvs:
            return None, None, 0

        # Cache hit (within a single pipeline run)
        cache_key = job.get("job_fingerprint") or job.get("apply_url") or ""
        if cache_key and cache_key in self._pick_cache:
            cached = self._pick_cache[cache_key]
            return cached["cv_path"], cached["cv_profile"], cached["score"]

        from tools.cv_matcher import CVMatcher

        best_path: Optional[str] = None
        best_profile: Optional[Dict] = None
        best_score = -1
        best_name = ""

        for entry in self.cvs:
            self._ensure_parsed(entry)
            profile = entry["profile"]
            if not profile:
                continue
            try:
                matcher = self._matcher_cache.get(entry["path"])
                if matcher is None:
                    matcher = CVMatcher(profile)
                    self._matcher_cache[entry["path"]] = matcher
                result = matcher.score(job)
                score = result.get("score", 0)
            except Exception:
                score = 0

            # Tie-break: alphabetical name (already sorted on discovery)
            if score > best_score:
                best_score = score
                best_path = entry["path"]
                best_profile = profile
                best_name = entry["name"]

        job_title = job.get("job_title", "?")[:50]
        if best_path:
            print(f"   Best CV for '{job_title}': {best_name} (score {best_score})")

        result_entry = {"cv_path": best_path, "cv_profile": best_profile, "score": best_score}
        if cache_key:
            self._pick_cache[cache_key] = result_entry

        return best_path, best_profile, best_score

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def is_empty(self) -> bool:
        return len(self.cvs) == 0

    @property
    def count(self) -> int:
        return len(self.cvs)

    def summary(self):
        """Print a summary table of all registered CVs."""
        if not self.cvs:
            print("   (no CVs registered)")
            return
        print(f"\n{'='*55}")
        print(f"{'CV FILE':<30} {'TAGS':<20}")
        print(f"{'-'*55}")
        for entry in self.cvs:
            print(f"  {entry['name']:<28} {', '.join(entry['tags']):<20}")
        print(f"{'='*55}")


# =============================================================================
# MODULE-LEVEL SINGLETON (instantiated once at import time)
# =============================================================================

_library: Optional[CVLibrary] = None


def get_library(cv_dir: Optional[str] = None, force_reload: bool = False) -> CVLibrary:
    """
    Return the shared CVLibrary singleton.

    Parameters
    ----------
    cv_dir : str | None
        Override the folder path. Only respected on first call or when
        force_reload=True.
    force_reload : bool
        If True, discard the cached singleton and rebuild from scratch.
    """
    global _library
    if _library is None or force_reload:
        _library = CVLibrary(cv_dir=cv_dir)
    return _library


def pick_best_cv(job: Dict, cv_dir: Optional[str] = None) -> Tuple[Optional[str], Optional[Dict], int]:
    """
    Convenience wrapper: pick the best CV for a job using the shared library.

    Returns (cv_path, cv_profile, score).
    """
    return get_library(cv_dir).pick_best(job)
