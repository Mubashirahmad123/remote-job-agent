"""
tests/test_artifact_retention.py

Pins the contract of the scheduler's artifact retention sweep
(tools/artifact_retention.py):

  * ONLY the four generated-artifact folders are swept — a stale file
    elsewhere (my_cv.pdf, archive/, repo root) must survive;
  * the retention window is enforced by mtime: old files go, fresh stay;
  * empty old directories are pruned, but a package holding a fresh file
    survives whole (evidence outlives the job, never the reverse);
  * a broken retention window (0, negative, non-integer) refuses to run
    loudly instead of sweeping with a dangerous bound;
  * missing artifact folders are fine (fresh installs).

Fully offline: everything happens under tmp_path via the base_dir seam.
"""

import os
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from tools.artifact_retention import (
    ARTIFACT_DIRS,
    cleanup_artifacts,
    retention_days_from_env,
)


def _age(path: Path, days: float) -> None:
    """Set a path's mtime `days` into the past (works on files and dirs)."""
    stamp = time.mktime((datetime.now() - timedelta(days=days)).timetuple())
    os.utime(path, (stamp, stamp))


def _make_file(path: Path, days_old: float = 0.0, size: int = 100) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    if days_old:
        _age(path, days_old)
    return path


class TestSweepScope:
    def test_only_sweeps_the_four_artifact_dirs(self, tmp_path):
        # A pile of stale files that must ALL survive: personal CV, archive
        # holding area, and a random repo-root file.
        cv = _make_file(tmp_path / "my_cv.pdf", days_old=30)
        archived = _make_file(tmp_path / "archive" / "old.pdf", days_old=30)
        stray = _make_file(tmp_path / "notes.txt", days_old=30)
        old_resume = _make_file(tmp_path / "resumes" / "old.pdf", days_old=30)

        cleanup_artifacts(retention_days=4, base_dir=tmp_path)

        assert cv.exists()
        assert archived.exists()
        assert stray.exists()
        assert not old_resume.exists()

    def test_missing_artifact_dirs_are_fine(self, tmp_path):
        result = cleanup_artifacts(retention_days=4, base_dir=tmp_path)
        assert result["deleted_files"] == 0
        assert set(result["roots"]) == set(ARTIFACT_DIRS)


class TestRetentionWindow:
    def test_old_files_deleted_fresh_kept(self, tmp_path):
        old = _make_file(tmp_path / "resumes" / "old.pdf", days_old=5, size=50)
        fresh = _make_file(tmp_path / "resumes" / "new.pdf", days_old=0)

        result = cleanup_artifacts(retention_days=4, base_dir=tmp_path)

        assert not old.exists()
        assert fresh.exists()
        assert result["deleted_files"] == 1
        assert result["bytes_freed"] == 50
        assert result["retention_days"] == 4

    def test_boundary_file_exactly_at_window_survives(self, tmp_path):
        # 4-day window: a file aged 4 days minus an hour is still inside.
        edge = _make_file(tmp_path / "resumes" / "edge.pdf", days_old=4 - 1 / 24)
        cleanup_artifacts(retention_days=4, base_dir=tmp_path)
        assert edge.exists()

    def test_old_package_dir_pruned_after_its_files_go(self, tmp_path):
        pkg = tmp_path / "apply_packages" / "Acme_Job_20260101"
        _make_file(pkg / "resume.pdf", days_old=10)
        _make_file(pkg / "cover_letter.txt", days_old=10)
        _age(pkg, 10)

        result = cleanup_artifacts(retention_days=4, base_dir=tmp_path)

        assert not pkg.exists()
        assert result["deleted_dirs"] == 1

    def test_package_with_one_fresh_file_survives_whole(self, tmp_path):
        # Old package dir, old files, but ONE fresh file inside: nothing goes.
        # The dir is kept (not empty), and its old files stay with it — a
        # half-deleted package is worse than a full old one.
        pkg = tmp_path / "apply_packages" / "Acme_Job_20260101"
        _make_file(pkg / "old_resume.pdf", days_old=10)
        fresh = _make_file(pkg / "new_resume.pdf", days_old=0)
        _age(pkg, 0)

        cleanup_artifacts(retention_days=4, base_dir=tmp_path)

        assert pkg.exists()
        assert fresh.exists()

    def test_nested_screenshots_swept_recursively(self, tmp_path):
        nested_dir = tmp_path / "screenshots" / "greenhouse_fail"
        old_shot = _make_file(nested_dir / "gh_error.png", days_old=9)
        _age(nested_dir, 9)
        fresh_dir = tmp_path / "screenshots" / "today"
        fresh_shot = _make_file(fresh_dir / "filled.png", days_old=0)

        result = cleanup_artifacts(retention_days=4, base_dir=tmp_path)

        assert not old_shot.exists()
        assert not nested_dir.exists()  # old AND empty -> pruned
        assert fresh_shot.exists()
        assert result["deleted_dirs"] == 1


class TestRetentionBoundRefusesBadValues:
    def test_zero_days_refused_nothing_deleted(self, tmp_path):
        old = _make_file(tmp_path / "resumes" / "old.pdf", days_old=30)
        with pytest.raises(ValueError):
            cleanup_artifacts(retention_days=0, base_dir=tmp_path)
        assert old.exists()  # refused BEFORE any deletion

    def test_negative_days_refused(self, tmp_path):
        with pytest.raises(ValueError):
            cleanup_artifacts(retention_days=-3, base_dir=tmp_path)

    def test_non_integer_days_refused(self, tmp_path):
        with pytest.raises(ValueError):
            cleanup_artifacts(retention_days=2.5, base_dir=tmp_path)


class TestEnvParsing:
    def test_env_value_used_as_default(self, tmp_path, monkeypatch):
        old = _make_file(tmp_path / "resumes" / "old.pdf", days_old=2)
        monkeypatch.setenv("ARTIFACT_RETENTION_DAYS", "1")
        result = cleanup_artifacts(base_dir=tmp_path)  # no explicit days
        assert not old.exists()
        assert result["retention_days"] == 1

    def test_default_is_four_days(self, monkeypatch):
        monkeypatch.delenv("ARTIFACT_RETENTION_DAYS", raising=False)
        assert retention_days_from_env() == 4

    def test_bad_env_value_raises_loudly(self, monkeypatch):
        monkeypatch.setenv("ARTIFACT_RETENTION_DAYS", "soon")
        with pytest.raises(ValueError, match="whole number"):
            retention_days_from_env()

    def test_env_zero_raises_loudly(self, monkeypatch):
        monkeypatch.setenv("ARTIFACT_RETENTION_DAYS", "0")
        with pytest.raises(ValueError, match=">= 1"):
            retention_days_from_env()
