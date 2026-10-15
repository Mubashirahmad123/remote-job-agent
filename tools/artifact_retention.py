"""
tools/artifact_retention.py
Deletes generated artifacts older than ARTIFACT_RETENTION_DAYS (default 4).

Scope is fixed and narrow: ONLY the four generated-artifact folders at the
repo root — resumes/, apply_packages/, cover_letters/, screenshots/. Anything
else on disk (my_cv.pdf, archive/, data/, logs/, caches) is never touched:
a cleanup helper that walks wider than its contract is a rm -rf with a
schedule.

Runs from scheduler.py (at daemon startup and daily) and standalone:

    python -m tools.artifact_retention

Deletion rule: an item's mtime older than the cutoff goes. Artifacts are
write-once (a resume or package is generated, then never modified), so mtime
is a faithful age signal. A fresh file inside an otherwise-old package keeps
the whole package until its own mtime goes stale — evidence of what was
generated for a job outlives the job, never the reverse.
"""

import os
from datetime import datetime, timedelta
from pathlib import Path

# The four generated-artifact roots. Relative to the repo root, resolved the
# same way tools/cv_parser.py anchors its cache — never relative to cwd, so a
# scheduler started from another directory cannot sweep the wrong folders.
BASE_DIR = Path(__file__).resolve().parents[1]
ARTIFACT_DIRS = ("resumes", "apply_packages", "cover_letters", "screenshots")

DEFAULT_RETENTION_DAYS = 4


def retention_days_from_env() -> int:
    """Parse ARTIFACT_RETENTION_DAYS. Defaults to 4; refuses bad values loudly
    rather than guessing (a cleanup with a wrong retention window is
    destructive, so a typo must stop the run, not quietly become 0)."""
    raw = (os.getenv("ARTIFACT_RETENTION_DAYS") or "").strip() or str(DEFAULT_RETENTION_DAYS)
    try:
        days = int(raw)
    except ValueError:
        raise ValueError(
            f"ARTIFACT_RETENTION_DAYS must be a whole number of days, got {raw!r}"
        )
    if days < 1:
        raise ValueError(
            f"ARTIFACT_RETENTION_DAYS must be >= 1 day, got {days} — refusing to "
            "run a cleanup that would delete fresh artifacts"
        )
    return days


def _cleanup_root(root: Path, cutoff: datetime) -> dict:
    """Delete old files under root, then prune empty old directories.

    Per-item error tolerance: one locked file (Windows, a PDF open in a
    viewer) must not abort the sweep — it stays until the next run.
    """
    summary = {"deleted_files": 0, "deleted_dirs": 0, "bytes_freed": 0}
    if not root.exists() or root.is_symlink():
        return summary

    # Snapshot directory mtimes BEFORE deleting files: on Windows and POSIX,
    # unlinking a child updates the parent directory's mtime, so a dir emptied
    # by pass 1 would otherwise look freshly-written and never be pruned.
    dirs = [p for p in root.rglob("*") if p.is_dir() and not p.is_symlink()]
    dir_mtimes = {p: p.stat().st_mtime for p in dirs}

    # Pass 1: old files, deepest first so nested cases behave.
    for path in sorted((p for p in root.rglob("*") if p.is_file() and not p.is_symlink()),
                       key=lambda p: len(p.parts), reverse=True):
        try:
            if datetime.fromtimestamp(path.stat().st_mtime) < cutoff:
                size = path.stat().st_size
                path.unlink()
                summary["deleted_files"] += 1
                summary["bytes_freed"] += size
        except OSError:
            continue

    # Pass 2: prune directories that were old BEFORE the sweep and are now
    # empty (bottom-up, judged on the snapshot mtime above).
    for path in sorted(dirs, key=lambda p: len(p.parts), reverse=True):
        try:
            if (not any(path.iterdir())
                    and datetime.fromtimestamp(dir_mtimes[path]) < cutoff):
                path.rmdir()
                summary["deleted_dirs"] += 1
        except OSError:
            continue

    return summary


def cleanup_artifacts(retention_days: int | None = None, base_dir: Path | str | None = None) -> dict:
    """Delete generated artifacts older than the retention window.

    Args:
        retention_days: items older than this many days are deleted. Defaults
            to ARTIFACT_RETENTION_DAYS (env), which defaults to 4.
        base_dir: repo root to resolve the artifact folders against. Defaults
            to the repo this file lives in. Test seams, not normal knobs.

    Returns:
        {"deleted_files": int, "deleted_dirs": int, "bytes_freed": int,
         "retention_days": int, "roots": {name: {...per-root counts...}}}

    Raises:
        ValueError: on a retention window that is not a positive whole
            number of days — refusing beats sweeping with a broken bound.
    """
    if retention_days is None:
        retention_days = retention_days_from_env()
    if not isinstance(retention_days, int) or retention_days < 1:
        raise ValueError(f"retention_days must be a positive int, got {retention_days!r}")

    root_base = Path(base_dir) if base_dir is not None else BASE_DIR
    cutoff = datetime.now() - timedelta(days=retention_days)

    total = {"deleted_files": 0, "deleted_dirs": 0, "bytes_freed": 0,
             "retention_days": retention_days, "roots": {}}
    for name in ARTIFACT_DIRS:
        per_root = _cleanup_root(root_base / name, cutoff)
        total["roots"][name] = per_root
        total["deleted_files"] += per_root["deleted_files"]
        total["deleted_dirs"] += per_root["deleted_dirs"]
        total["bytes_freed"] += per_root["bytes_freed"]
    return total


if __name__ == "__main__":
    import sys
    # cp1252 consoles cannot encode emoji banners; degrade to "?" instead of
    # crashing AFTER a successful sweep (the crash is worse than the message).
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    result = cleanup_artifacts()
    kb = result["bytes_freed"] / 1024
    print(f"🧹 Artifact retention: {result['retention_days']}-day window — "
          f"{result['deleted_files']} files / {result['deleted_dirs']} dirs removed, {kb:.0f} KB freed")
    for name, stats in result["roots"].items():
        print(f"   {name}: {stats['deleted_files']} files, {stats['deleted_dirs']} dirs")
