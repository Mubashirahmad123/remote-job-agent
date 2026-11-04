"""D10 regression tests: the Phase 4 comparison must not claim agreement.

The defect being pinned: with no legacy ``eligible`` rows, the old expression

    (legacy == 'eligible') == (new == 'eligible')

is ``True`` for every pair of non-eligible decisions, so a 502-row CSV over 312
real jobs reported 100% agreement between two systems that never emitted a
positive decision. These tests require a real 3x3 matrix, a refusal on an
incomplete run, one row per ``job_uid``, and a score read from the ledger.
"""
from pathlib import Path

import pytest
import sqlite3

import phase4_full as p4
from tools.pipeline_ledger import PipelineLedger

PROFILE = {
    "version": "test-profile-v1",
    "skills": ["python", "react", "postgresql", "docker"],
    "learnable_skills": [],
    "policy": {
        "role_families": ["backend", "fullstack", "software"],
        "work_locations": ["india"],
        "seniority_levels": ["junior", "mid"],
        "relocation_destinations": ["india"],
        "work_cities": [],
        "remote_work_locations": ["india"],
        "years_experience": 3,
        "seniority_gap_threshold": 2,
        "sponsorship_required": False,
        "accept_unrestricted_remote": False,
    },
}


def _write_profile(tmp_path: Path) -> Path:
    import json
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(PROFILE), encoding="utf-8")
    return path


def _job(n: int, **over) -> dict:
    job = {
        "job_title": f"Backend Developer {n}",
        "company": f"Co{n}",
        "apply_url": f"https://example.test/job/{n}",
        "source": "ExampleBoard",
        "description": (
            "Fully remote. Open to candidates in India. "
            "Requirements: Python, React, PostgreSQL."),
    }
    job.update(over)
    return job


def _complete_run(tmp_path: Path) -> tuple[Path, str]:
    """3 raw instances, 3 terminal rows, one of each decided class."""
    db = tmp_path / "ledger.db"
    ledger = PipelineLedger(db, run_id="run-complete")
    jobs = [_job(i) for i in range(3)]
    ledger.record_jobs(jobs, "raw_fetched")
    ledger.record_jobs([jobs[0]], "legacy_passed",
                       score_of=lambda j: (88.0, {"total": 88}))
    ledger.record_jobs([jobs[1]], "legacy_low_match",
                       score_of=lambda j: (20.0, {"total": 20}))
    # legacy_rejected carries no score: the legacy engine rejects before scoring.
    ledger.record_jobs([jobs[2]], "legacy_rejected", reason_code="too_senior")
    return db, "run-complete"


def _row(legacy: str, new: str, stage: str = "s") -> p4.ComparisonRow:
    return p4.ComparisonRow(
        job_uid="uid", job_title="t", company="c", source="s",
        legacy_stage=stage, legacy_decision=legacy, legacy_score=None,
        legacy_reason="", new_decision=new, new_reasons="", required_score=None,
        location_gate="", role_gate="", seniority_gate="")


# ── The guard: no comparison from a partial run ───────────────────────────
def test_incomplete_run_is_refused(tmp_path):
    db = tmp_path / "ledger.db"
    ledger = PipelineLedger(db, run_id="run-partial")
    jobs = [_job(i) for i in range(3)]
    ledger.record_jobs(jobs, "raw_fetched")
    ledger.record_jobs([jobs[0]], "country_drop", reason_code="not_allowed")

    with pytest.raises(p4.IncompleteRunError) as excinfo:
        p4.require_complete(db, "run-partial")
    message = str(excinfo.value)
    assert "not reconcilable" in message
    assert "missing_terminal=2" in message


def test_main_writes_nothing_for_an_incomplete_run(tmp_path):
    db = tmp_path / "ledger.db"
    ledger = PipelineLedger(db, run_id="run-partial")
    jobs = [_job(i) for i in range(2)]
    ledger.record_jobs(jobs, "raw_fetched")
    out = tmp_path / "out.csv"

    code = p4.main(["--db", str(db), "--run", "run-partial",
                    "--profile", str(_write_profile(tmp_path)),
                    "--out", str(out)])

    assert code == 2
    assert not out.exists(), "a partial run must not produce a comparison CSV"


def test_duplicated_terminal_rows_are_refused(tmp_path):
    db = tmp_path / "ledger.db"
    ledger = PipelineLedger(db, run_id="run-double")
    job = _job(0)
    ledger.record_jobs([job], "raw_fetched")
    ledger.record_jobs([job], "legacy_passed", score_of=lambda j: (80.0, None))
    ledger.record_jobs([job], "legacy_low_match", score_of=lambda j: (10.0, None))

    with pytest.raises(p4.IncompleteRunError):
        p4.require_complete(db, "run-double")


def test_complete_run_is_accepted(tmp_path):
    db, run_id = _complete_run(tmp_path)
    assert p4.require_complete(db, run_id) == run_id


# ── Class mapping: a duplicate is not a rejection ─────────────────────────
def test_dedup_and_prefilter_are_not_rejections():
    assert p4.LEGACY_DECISION_BY_STAGE["dedup_url_dup"] == "duplicate"
    assert p4.LEGACY_DECISION_BY_STAGE["dedup_cross_board"] == "duplicate"
    assert p4.LEGACY_DECISION_BY_STAGE["dev_filter_drop"] == "prefiltered"
    assert p4.LEGACY_DECISION_BY_STAGE["country_drop"] == "prefiltered"
    assert p4.LEGACY_DECISION_BY_STAGE["legacy_rejected"] == "rejected"


def test_build_row_reports_duplicate_class(tmp_path):
    from tools.matching_shadow import load_profile
    profile = load_profile(_write_profile(tmp_path))
    row = p4.build_row(_job(0, job_uid="uid-1"),
                       {"stage": "dedup_url_dup", "reason_code": "",
                        "score": None}, profile)
    assert row.legacy_decision == "duplicate"


# ── Legacy score is read, not invented ────────────────────────────────────
def test_legacy_score_comes_from_the_ledger(tmp_path):
    from tools.matching_shadow import load_profile
    db, run_id = _complete_run(tmp_path)
    profile = load_profile(_write_profile(tmp_path))
    rows = {row.job_title: row for row in p4.build_rows(db, run_id, profile)}

    passed = rows["Backend Developer 0"]
    low = rows["Backend Developer 1"]
    rejected = rows["Backend Developer 2"]
    assert passed.legacy_score == 88.0
    assert low.legacy_score == 20.0
    assert rejected.legacy_score is None, (
        "legacy_rejected never scored, so a score would be fabricated")


def test_no_duplicate_rows_from_duplicated_job_texts(tmp_path):
    """A legacy ledger may still hold duplicate rows; the report must collapse."""
    import hashlib
    from tools.matching_shadow import load_profile
    db = tmp_path / "ledger.db"
    ledger = PipelineLedger(db, run_id="run-dup-text")
    job = _job(0)
    ledger.record_jobs([job], "raw_fetched")
    ledger.record_jobs([job], "legacy_passed", score_of=lambda j: (70.0, None))
    # Simulate the pre-D6 state: no unique key, and a second text row.
    with sqlite3.connect(db) as conn:
        conn.execute("DROP INDEX IF EXISTS idx_job_texts_run_uid")
        uid, = conn.execute(
            "SELECT job_uid FROM job_texts WHERE run_id='run-dup-text'"
        ).fetchone()
        conn.execute(
            """INSERT INTO job_texts
               (run_id, job_uid, title, company, url, source, description,
                description_sha256, fetched_at)
               VALUES (?, ?, 't', 'c', 'u', 's', 'd', ?, 'now')""",
            ("run-dup-text", uid, hashlib.sha256(b"d").hexdigest()))
        count, = conn.execute(
            "SELECT COUNT(*) FROM job_texts WHERE run_id='run-dup-text'"
        ).fetchone()
    assert count == 2, "duplicate row present"

    profile = load_profile(_write_profile(tmp_path))
    assert len(p4.build_rows(db, "run-dup-text", profile)) == 1


# ── The matrix is a matrix ────────────────────────────────────────────────
def test_confusion_matrix_reproduces_a_known_matrix():
    rows = [
        _row("eligible", "eligible"),
        _row("eligible", "review"),
        _row("eligible", "rejected"),
        _row("review", "eligible"),
        _row("review", "review"),
        _row("review", "review"),
        _row("rejected", "likely_fit"),
        _row("rejected", "review"),
        _row("rejected", "rejected"),
        _row("rejected", "rejected"),
        _row("duplicate", "review"),
        _row("prefiltered", "rejected"),
    ]
    report = p4.confusion(rows)

    assert report["matrix"][("eligible", "eligible")] == 1
    assert report["matrix"][("eligible", "review")] == 1
    assert report["matrix"][("review", "review")] == 2
    assert report["matrix"][("rejected", "likely_fit")] == 1
    assert report["matrix"][("rejected", "rejected")] == 2
    assert report["decided"] == 10
    assert report["excluded"] == {"duplicate": 1, "prefiltered": 1}


def test_agreement_is_per_class_and_never_a_bare_percentage():
    rows = [_row("rejected", "rejected"), _row("rejected", "review")]
    rates = p4.agreement_by_legacy_class(p4.confusion(rows))
    assert rates["eligible"] is None, "zero support must be undefined, not 100%"
    assert rates["review"] is None
    assert rates["rejected"] == 50.0


def test_render_report_refuses_to_call_disagreement_an_error():
    rows = [_row("rejected", "eligible"), _row("eligible", "review")]
    text = p4.render_report(rows, "run-x")
    lowered = text.lower()
    assert "disagreements, not errors" in lowered
    assert "false positive" not in lowered
    assert "false negative" not in lowered
    # Both directions are named and counted.
    assert "legacy_rejected_new_open: 1" in text
    assert "legacy_eligible_new_closed: 1" in text


def test_main_emits_one_row_per_job_uid(tmp_path):
    import csv
    db, run_id = _complete_run(tmp_path)
    out = tmp_path / "out.csv"
    code = p4.main(["--db", str(db), "--run", run_id,
                    "--profile", str(_write_profile(tmp_path)),
                    "--out", str(out)])
    assert code == 0
    with open(out, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 3, "3 instances fetched, 6 job_text rows stored"
    assert {row["legacy_decision"] for row in rows} == {
        "eligible", "review", "rejected"}
