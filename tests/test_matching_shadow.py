"""Section 3B wiring tests: profile loader strictness and offline shadow smoke.

No network, no Sheets, no live APIs. Matches tests/MATCHING_QA.md constraints.
"""
import json
from pathlib import Path

import pytest

from tools.matching_shadow import (
    load_profile,
    log_shadow_config,
    shadow_batch,
    shadow_config_status,
)
from tools.matching_runtime import MatchStore


def _write_profile(tmp_path: Path, name: str = "profile.json", **overrides) -> Path:
    data = {
        "policy": {
            "role_families": ["fullstack", "backend", "frontend"],
            "work_locations": ["india"],
            "seniority_levels": ["junior", "mid"],
            "relocation_destinations": ["india"],
            "sponsorship_required": False,
        },
        "skills": ["python", "react"],
        "version": "test-v1",
        "learnable_skills": [],
    }
    data.update(overrides)
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


class TestLoadProfileStrictness:
    def test_string_valued_skill_list_is_rejected(self, tmp_path):
        # Regression: a bare string must not silently become a one-element set.
        path = _write_profile(tmp_path, skills="python")
        with pytest.raises(ValueError):
            load_profile(path)

    def test_string_valued_policy_list_is_rejected(self, tmp_path):
        path = _write_profile(tmp_path)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["policy"]["work_locations"] = "india"
        path.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(ValueError):
            load_profile(path)

    def test_empty_string_list_member_is_rejected(self, tmp_path):
        path = _write_profile(tmp_path, skills=["python", "   "])
        with pytest.raises(ValueError):
            load_profile(path)

    def test_non_bool_sponsorship_is_rejected(self, tmp_path):
        path = _write_profile(tmp_path)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["policy"]["sponsorship_required"] = "false"
        path.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(ValueError):
            load_profile(path)

    def test_valid_profile_loads(self, tmp_path):
        profile = load_profile(_write_profile(tmp_path))
        assert profile.version == "test-v1"
        assert "india" in profile.policy.work_locations
        assert profile.policy.sponsorship_required is False


class TestShadowConfigStatus:
    def test_unconfigured_reports_disabled(self, monkeypatch):
        monkeypatch.setenv("MATCHING_SHADOW_PROFILE", "")
        assert shadow_config_status() == {
            "configured": False, "reason": "MATCHING_SHADOW_PROFILE unset"}

    def test_missing_profile_is_broken_not_disabled(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MATCHING_SHADOW_PROFILE", str(tmp_path / "nope.json"))
        status = shadow_config_status()
        assert status["configured"] is True
        assert status["exists"] is False

    def test_valid_profile_reports_version(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MATCHING_SHADOW_PROFILE", str(_write_profile(tmp_path)))
        status = shadow_config_status()
        assert status["exists"] is True
        assert status["version"] == "test-v1"

    def test_health_line_reflects_configuration(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("MATCHING_SHADOW_PROFILE", "")
        assert "DISABLED" in log_shadow_config()
        monkeypatch.setenv("MATCHING_SHADOW_PROFILE", str(tmp_path / "nope.json"))
        assert "BROKEN" in log_shadow_config()
        monkeypatch.setenv("MATCHING_SHADOW_PROFILE", str(_write_profile(tmp_path)))
        line = log_shadow_config()
        assert "ENABLED" in line and "test-v1" in line
        out = capsys.readouterr().out
        assert out.count("Matching shadow:") == 3


class TestShadowBatchOfflineSmoke:
    """Phase 3: per-job isolation — one bad job is a recorded failure,
    never an abort of the whole batch."""

    def test_missing_fingerprint_is_recorded_not_aborted(self, tmp_path):
        profile = load_profile(_write_profile(tmp_path))
        store = MatchStore(tmp_path / "shadow.db")
        # Phase 3 per-job isolation: ValueError is caught inside shadow_batch.
        results = shadow_batch([{"job_title": "Backend Engineer"}],
                               profile, store, "test-owner")
        assert results == {}
        # No decision recorded (nothing to evaluate), but one failure tracked.
        assert store.decision_count("test-owner") == 0

    def test_decision_row_per_job(self, tmp_path):
        profile = load_profile(_write_profile(tmp_path))
        store = MatchStore(tmp_path / "shadow.db")
        jobs = [
            {"job_fingerprint": "fp-1", "job_title": "Backend Engineer",
             "summary": "Build APIs"},
            {"job_fingerprint": "fp-2", "job_title": "Frontend Developer",
             "summary": "React work"},
        ]
        results = shadow_batch(jobs, profile, store, "test-owner")
        assert set(results) == {"fp-1", "fp-2"}
        import sqlite3
        with sqlite3.connect(store.path) as db:
            rows = db.execute("SELECT job_id, decision FROM decisions").fetchall()
        assert {r[0] for r in rows} == {"fp-1", "fp-2"}
        # No evidence: gates unknown -> review, never eligible.
        assert all(r[1] == "review" for r in rows)

    def test_every_decision_row_carries_its_own_batch_run_id(self, tmp_path):
        """2026-11-05: the shadow's own run_status row held the run id, but
        decisions didn't — attribution across 1,380 live rows worked only by
        timestamp correlation. shadow_batch must bind every decision it
        appends to the batch's run id, the exact join key to run_status."""
        profile = load_profile(_write_profile(tmp_path))
        store = MatchStore(tmp_path / "shadow.db")
        jobs = [
            {"job_fingerprint": "fp-1", "job_title": "Backend Engineer",
             "summary": "Build APIs"},
            {"job_fingerprint": "fp-2", "job_title": "Frontend Developer",
             "summary": "React work"},
        ]
        shadow_batch(jobs, profile, store, "test-owner", run_id="shadow-run-9")
        import sqlite3
        with sqlite3.connect(store.path) as db:
            run_ids = {r[0] for r in db.execute(
                "SELECT run_id FROM decisions").fetchall()}
            run_row = db.execute(
                "SELECT run_id FROM run_status WHERE run_id='shadow-run-9'").fetchone()
        assert run_ids == {"shadow-run-9"}
        assert run_row is not None

    def test_auto_generated_run_id_lands_on_decisions_too(self, tmp_path):
        """When no run id is supplied, shadow_batch generates one — the very
        id that goes to run_status must be the one on the decision rows."""
        from tools.matching_shadow import ensure_evidence
        profile = load_profile(_write_profile(tmp_path))
        store = MatchStore(tmp_path / "shadow.db")
        import sqlite3
        captured = {}
        real_finish = store.finish_run

        def spy_finish(owner, run_id, profile_v, processed, failed, reasons=None):
            captured["run_id"] = run_id
            return real_finish(owner, run_id, profile_v, processed, failed, reasons)

        store.finish_run = spy_finish
        shadow_batch([{"job_fingerprint": "fp-9", "job_title": "Backend Engineer",
                       "summary": "Build APIs"}], profile, store, "test-owner")
        import sqlite3
        with sqlite3.connect(store.path) as db:
            rows = db.execute("SELECT run_id FROM decisions").fetchall()
        assert len(rows) == 1
        assert rows[0][0] == captured["run_id"]
        assert rows[0][0] is not None

    def test_extractor_error_recorded_in_run_status(self, tmp_path, monkeypatch):
        """Extractor errors are recorded in run_status, not silently swallowed."""
        from tools.matching_shadow import ensure_evidence

        def boom(job):
            raise RuntimeError("extractor crashed")

        monkeypatch.setattr("tools.matching_shadow.ensure_evidence", boom)

        profile = load_profile(_write_profile(tmp_path))
        store = MatchStore(tmp_path / "shadow.db")
        run_id = "test-run-001"
        jobs = [{"job_fingerprint": "fp-bad", "job_title": "Backend Engineer",
                 "summary": "Build APIs"}]
        results = shadow_batch(jobs, profile, store, "test-owner", run_id=run_id)
        assert results == {}
        # Run status should record the failure
        status = store.run_status("test-owner", run_id)
        assert status is not None
        assert status["failed"] == 1
        assert status["processed"] == 0
        assert any("extractor crashed" in str(f["error"]) for f in status["reasons"])
