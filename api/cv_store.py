"""
api/cv_store.py — CV upload ingest for the dashboard dropzone (Option A).

Stores an authenticated upload into the CV library as a tagged variant.
Scenario A personal-tool scale: the multi-user lifecycle (retention,
deletion policies, per-user ownership) stays deferred with the future
`user` product (PM.md §2.1a / USER_PRODUCT.md — the PO decision that
unblocked this slice is recorded there, 2026-10-28).

Design rules (grounded in this repo's written constraints):

- **Raw-body upload, no `python-multipart` dependency**: the browser sends
  the file bytes with the safe filename as a query parameter. One less
  supply-chain pin for a single route.
- **Content validation, not trust**: server-side size cap
  (`CV_UPLOAD_MAX_MB`, clamped) and magic-byte checks per extension
  (`%PDF-` / ZIP `PK`). A mislabeled body is rejected before storing.
- **No per-request LLM parsing** (the design rule behind
  `GET /api/cv/profile`'s 501): the request proves readability via
  `tools/cv_parser.extract_cv_text` offline and reports whether a fresh
  on-disk profile cache already exists for this file's content hash. The
  structured parse happens in the pipeline, as it already does for every
  CV on disk.
- **Registration == filename**: domain tags live in the filename
  (`tools/cv_library._extract_domain_tags`), so the stored name preserves
  the operator's tags and the library attaches the same ones at scoring
  time. The md5 content-hash suffix keeps uploads unique and aligns the
  stored file with cv_parser's hash-keyed cache paths.
- **Atomic write**: temp file in the target dir, then `os.replace` — a
  torn CV must never exist under the registered name (it would join the
  library discovery and poison scoring).
- **Stored ⇒ readable**: if the offline extraction yields no text, the
  file is DELETED and rejected (422). The 2026-10-03 incident taught this
  repo not to register unreadable content as a working CV.
- **PII discipline** (PRODUCTION.md §9a): uploads stay gitignored and out
  of images (cvs/ mount); logs carry name/size/outcome only — never file
  contents or extracted text.
"""

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]

_ALLOWED_EXT = {".pdf", ".docx"}
_MAGIC = {
    ".pdf": b"%PDF-",
    ".docx": b"PK\x03\x04",
}
_SAFE_CHARS = re.compile(r"[^A-Za-z0-9 ._-]+")

# The Profile-Parser freshness rule mirrored from cv_parser (_load_cached_profile):
# a cache entry older than 7 days is treated as absent here too — this endpoint
# must not report "profile cached" for content the pipeline would re-parse.
_FRESH_DAYS = 7


class CvUploadError(Exception):
    """Terminal, input-caused rejection. The router maps it to HTTP."""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


# ============================================================================
# Configuration
# ============================================================================

def max_upload_bytes() -> int:
    """Server-side cap: CV_UPLOAD_MAX_MB, clamped to 1..50 MB (default 10).

    The clamp matches the ACTION-budget style bounds used elsewhere; a
    nonsense env value cannot disable the size guard.
    """
    try:
        mb = int(str(os.getenv("CV_UPLOAD_MAX_MB", "10")).strip() or 10)
    except ValueError:
        mb = 10
    return max(1, min(50, mb)) * 1024 * 1024


def cv_dir_path() -> Path:
    """The CV_DIR directory resolved to an absolute path (created if missing)."""
    raw = (os.getenv("CV_DIR", "").strip() or "cvs")
    directory = Path(raw)
    if not directory.is_absolute():
        directory = PROJECT_ROOT / directory
    directory.mkdir(parents=True, exist_ok=True)
    return directory


# ============================================================================
# Filename rules — registration == filename
# ============================================================================

def _safe_stem_and_ext(raw_name: str) -> Tuple[str, str]:
    """basename → (safe stem, lowercase ext). 415 on unsupported/absent ext."""
    base = os.path.basename(str(raw_name or "").strip())
    ext = Path(base).suffix.lower()
    stem = Path(base).stem
    if not base or not ext or ext not in _ALLOWED_EXT:
        raise CvUploadError(
            415,
            "Only PDF and DOCX CV uploads are supported "
            "(extension required: .pdf or .docx).",
        )
    cleaned = _SAFE_CHARS.sub("_", stem).strip(". ").strip()
    cleaned = re.sub(r"[\s_-]+", "_", cleaned)[:60].strip("_")
    if not cleaned:
        cleaned = "cv_upload"
    return cleaned, ext


def stored_name_for(stem: str, ext: str, digest: str) -> str:
    """Encode identity on disk: tags stay in the stem the operator chose;
    the content-hash suffix guarantees uniqueness across re-uploads."""
    return f"{stem}__{digest[:8]}{ext}"


# ============================================================================
# Ingest
# ============================================================================

def ingest_cv_upload(filename: str, data: bytes) -> Dict[str, Any]:
    """Validate, store, and register one uploaded CV. Returns the honest
    outcome dict the router returns to the dashboard. Raises CvUploadError
    for every rejection. Never logs file contents."""
    stem, ext = _safe_stem_and_ext(filename)  # 415

    max_bytes = max_upload_bytes()
    if not isinstance(data, (bytes, bytearray)) or len(data) == 0:
        raise CvUploadError(413, "Empty upload: no file bytes received.")
    if len(data) > max_bytes:
        raise CvUploadError(
            413,
            f"File exceeds the {max_bytes // (1024 * 1024)} MB upload cap "
            f"({len(data)} bytes given).",
        )
    data = bytes(data)

    if not data.startswith(_MAGIC[ext]):
        raise CvUploadError(
            415,
            f"File content does not match its .{ext.lstrip('.')} extension "
            f"(magic bytes rejected before storing).",
        )

    digest = hashlib.md5(data).hexdigest()

    # True library tag semantics: exactly what tools/cv_library will attach
    # when the same name is discovered at scoring time.
    from tools.cv_library import _extract_domain_tags

    tags = _extract_domain_tags(f"{stem}{ext}")

    directory = cv_dir_path()
    target = directory / stored_name_for(stem, ext, digest)

    # Atomic store: temp file in the same dir, then os.replace.
    tmp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=str(directory), delete=False, suffix=".part"
        ) as tmp:
            tmp.write(data)
            tmp_name = tmp.name
        os.replace(tmp_name, target)
        tmp_name = None  # ownership moved to target
    finally:
        if tmp_name:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass

    # Stored ⇒ readable (offline only — never the LLM here).
    try:
        from tools.cv_parser import extract_cv_text

        text = extract_cv_text(str(target))
    except Exception:
        text = ""  # extraction failures surface as empty, never crash the route
    if not text.strip():
        try:
            target.unlink()
        except OSError:
            pass
        raise CvUploadError(
            422,
            "Uploaded file produced no extractable text — it is corrupt, "
            "empty, or image-only. Not registered.",
        )

    cached_probe = _cached_profile_if_fresh(target)

    # Log filename/size/outcome only (PII rule: never file contents).
    print(
        f"⬇ CV upload: {target.name} ({len(data)} bytes, tags={tags}, "
        f"cached_profile={'yes' if cached_probe else 'no'})"
    )

    return {
        "stored_name": target.name,
        "size_bytes": len(data),
        "tags": tags,
        "profile_cached": cached_probe is not None,
        "cached_profile": cached_probe,
        "message": (
            "Registered in the CV library (default CV untouched). Parses on "
            "the next pipeline run."
            if cached_probe is None
            else "Registered in the CV library; a fresh parsed profile for "
            "this exact file is already cached."
        ),
    }


def _cached_profile_if_fresh(path: Path) -> Optional[Dict[str, Any]]:
    """Report an existing fresh profile cache for this exact content, without
    triggering any parse (no LLM). Uses cv_parser's canonical md5-keyed cache
    path rather than re-implementing the file layout."""
    try:
        from tools.cv_parser import _get_cache_path

        cache_path = _get_cache_path(str(path))
        if not cache_path.exists():
            return None
        age_days = (
            datetime.now() - datetime.fromtimestamp(cache_path.stat().st_mtime)
        ).days
        if age_days > _FRESH_DAYS:
            return None
        with open(cache_path, "r", encoding="utf-8") as fh:
            profile = json.load(fh)
        # Shell guard — mirrors the parser's own non-shell rule: an entry
        # without name+skills+experience is a recorded failed parse.
        if not isinstance(profile, dict):
            return None
        if not (
            profile.get("name")
            or profile.get("skills")
            or profile.get("experience")
        ):
            return None
        return profile
    except Exception:
        return None
