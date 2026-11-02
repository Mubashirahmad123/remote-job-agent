"""Phase 1 tests: per-job append-only ledger, stage reconciliation, board taxonomy.

Offline: real SQLite in a tmp dir, no network, no Sheets.
"""
import sqlite3

import pytest

from tools.pipeline_ledger import (
    TERMINAL_STAGES,
    PipelineLedger,
    consecutive_bad_boards,
)


def _job(n, source="Arbeitnow", **kwargs):
    base = {
        "source": source, "job_title": f"Job {n}",
        "company": f"Company {n}", "apply_url": f"https://x/{n}",
        "summary": f"summary {n}",
    }
    base.update(kwargs)
    return base


class TestStageLedger:
    def test_append_only_rows_persist_and_never_overwrite(self, tmp_path):
        db = tmp_path / "ledger.db"
        ledger = PipelineLedger(db, run_id="run-a")
        ledger.record_jobs([_job(1)], "raw_fetched")
        ledger.record_jobs([_job(1)], "dev_filter_drop", reason_code="too_senior")
        # Second write for the SAME job/stage is a NEW row, not a replace.
        ledger.record_jobs([_job(1)], "raw_fetched")
        with sqlite3.connect(db) as conn:
            count, = conn.execute(
                "SELECT COUNT(*) FROM stage_events WHERE run_id='run-a'").fetchone()
        assert count == 3

    def test_fingerprint_derived_when_missing(self, tmp_path):
        from tools.deduplicator import job_fingerprint
        ledger = PipelineLedger(tmp_path / "ledger.db", run_id="run-b")
        job = _job(1)
        ledger.record_jobs([job], "dedup_url_dup", reason_code="url_seen")
        with sqlite3.connect(tmp_path / "ledger.db") as conn:
            fp, = conn.execute("SELECT job_fingerprint FROM stage_events").fetchone()
        assert fp == job_fingerprint(job)

    def test_reason_score_breakdown_travel_with_rows(self, tmp_path):
        db = tmp_path / "ledger.db"
        ledger = PipelineLedger(db, run_id="run-c")
        jobs = [_job(2), _job(3)]
        scores = {"Job 2": (55.0, {"core_coverage": 0.1}), "Job 3": (80.0, None)}
        ledger.record_jobs(jobs, "legacy_low_match",
                           reason_code="No recognizable tech skills",
                           score_of=lambda j: scores[j["job_title"]])
        with sqlite3.connect(db) as conn:
            rows = conn.execute(
                "SELECT score, breakdown FROM stage_events ORDER BY seq").fetchall()
        assert rows[0][0] == 55.0 and rows[0][1] == '{"core_coverage": 0.1}'
        assert rows[1][0] == 80.0 and rows[1][1] is None

    def test_bad_row_does_not_abort_batch(self, tmp_path):
        db = tmp_path / "ledger.db"
        ledger = PipelineLedger(db, run_id="run-d")
        jobs = [_job(4), _job(5)]
        attempts = {"boom": 0}

        def score_of(_job):
            attempts["boom"] += 1
            if attempts["boom"] == 1:
                raise ValueError("bad job data")
            return (70, None)

        ledger.record_jobs(jobs, "legacy_passed", score_of=score_of)
        with sqlite3.connect(db) as conn:
            count, = conn.execute("SELECT COUNT(*) FROM stage_events").fetchone()
        assert count == 2


class TestReconciliation:
    def test_funnel_sums_exactly_to_fetched(self, tmp_path):
        db = tmp_path / "ledger.db"
        ledger = PipelineLedger(db, run_id="run-e")
        raw = [_job(i) for i in range(10)]
        ledger.record_jobs(raw, "raw_fetched")
        ledger.record_jobs(raw[0:3], "dev_filter_drop", reason_code="no_dev_indicators")
        ledger.record_jobs(raw[3:5], "country_drop", reason_code="not_allowed")
        ledger.record_jobs(raw[5:7], "dedup_url_dup", reason_code="url_seen")
        ledger.record_jobs(raw[7:8], "dedup_cross_board", reason_code="title_company_dup")
        ledger.record_jobs(raw[8:9], "legacy_low_match", reason_code="below_min")
        ledger.record_jobs(raw[9:10], "legacy_passed", reason_code="match")
        report = ledger.reconcile("run-e")
        assert report["raw_fetched"] == 10
        assert report["terminal_sum"] == 10
        assert report["complete"] is True
        assert report["stages"]["dev_filter_drop"] == 3

    def test_job_without_terminal_row_is_reported(self, tmp_path):
        ledger = PipelineLedger(tmp_path / "ledger.db", run_id="run-f")
        raw = [_job(1), _job(2)]
        ledger.record_jobs(raw, "raw_fetched")
        ledger.record_jobs([raw[0]], "legacy_passed", reason_code="match")
        report = ledger.reconcile("run-f")
        assert report["complete"] is False
        assert len(report["missing_terminal"]) == 1
        assert report["raw_fetched"] == 2

    def test_two_terminal_rows_for_one_job_are_reported(self, tmp_path):
        ledger = PipelineLedger(tmp_path / "ledger.db", run_id="run-g")
        raw = [_job(1)]
        ledger.record_jobs(raw, "raw_fetched")
        ledger.record_jobs(raw, "legacy_low_match", reason_code="below_min")
        ledger.record_jobs(raw, "legacy_passed", reason_code="match")
        report = ledger.reconcile("run-g")
        assert report["complete"] is False
        assert len(report["duplicated_terminal"]) == 1

    def test_terminal_stages_documented_match_expected_funnel(self):
        assert set(TERMINAL_STAGES) == {
            "dev_filter_drop", "country_drop", "date_drop",
            "dedup_missing_url", "dedup_url_dup", "dedup_cross_board",
            "dedup_fingerprint", "legacy_rejected", "legacy_low_match",
            "legacy_passed",
        }

    def test_same_fingerprint_different_urls_are_two_instances(self, tmp_path):
        """Live-run defect (2026-10-31): the content fingerprint is NOT
        unique — 331 raw rows collapsed to 315 distinct fingerprints, so
        reconciling by fingerprint reported false '2+ terminal rows'.
        Identity must be per INSTANCE (fingerprint + url + source)."""
        ledger = PipelineLedger(tmp_path / "ledger.db", run_id="run-uid")
        job_a = _job(1)
        job_a["job_fingerprint"] = "shared-fingerprint"
        job_b = dict(job_a)
        job_b["apply_url"] = "https://other/1"
        job_b["source"] = "OtherBoard"
        ledger.record_jobs([job_a, job_b], "raw_fetched")
        ledger.record_jobs([job_a], "legacy_passed", reason_code="match")
        ledger.record_jobs([job_b], "legacy_low_match", reason_code="below_min")
        report = ledger.reconcile("run-uid")
        assert report["raw_fetched"] == 2
        assert report["raw_instances"] == 2
        assert report["terminal_sum"] == 2
        assert report["complete"] is True
        assert report["duplicated_terminal"] == []
        assert report["missing_terminal"] == []

    def test_duplicate_instance_still_reports_unbalanced_counts(self, tmp_path):
        """The same posting fetched twice from one board is TWO instances
        and both need a terminal row; a missing one must be reported."""
        ledger = PipelineLedger(tmp_path / "ledger.db", run_id="run-uid2")
        job = _job(9)
        ledger.record_jobs([job, dict(job)], "raw_fetched")
        ledger.record_jobs([job], "legacy_passed", reason_code="match")
        report = ledger.reconcile("run-uid2")
        assert report["raw_fetched"] == 2
        assert report["terminal_sum"] == 1
        assert report["complete"] is False


class TestBoardTaxonomy:
    def test_status_outside_taxonomy_rejected(self, tmp_path):
        ledger = PipelineLedger(tmp_path / "ledger.db", run_id="run-h")
        with pytest.raises(ValueError):
            ledger.record_board("FlexJobs", "empty", 0)

    def test_skipped_and_empty_are_distinct_statuses(self, tmp_path):
        ledger = PipelineLedger(tmp_path / "ledger.db", run_id="run-i")
        ledger.record_board("Himalayas", "empty_confirmed", 0)
        ledger.record_board("Jobspresso", "parse_zero", 0)
        ledger.record_board("FlexJobs", "timeout", 0)
        ledger.record_board("Remotive", "skipped_js", 0)
        status = ledger.board_status_for_run("run-i")
        assert status["Himalayas"]["status"] == "empty_confirmed"
        assert status["Jobspresso"]["status"] == "parse_zero"
        assert status["FlexJobs"]["status"] == "timeout"
        assert status["Remotive"]["status"] == "skipped_js"

    def test_three_consecutive_bad_runs_flagged_ok_resets(self):
        flagged = consecutive_bad_boards({
            "FlexJobs": ["timeout", "timeout", "timeout"],
            "Jobspresso": ["parse_zero", "parse_zero", "parse_zero"],
            "Himalayas": ["empty_confirmed", "empty_confirmed", "ok"],
            "Remotive": ["ok", "ok", "ok"],
        })
        assert set(flagged) == {"FlexJobs", "Jobspresso"}

    def test_streak_needs_only_last_three_runs(self):
        flagged = consecutive_bad_boards({
            "FlexJobs": ["timeout", "timeout", "timeout", "timeout", "error"],
        })
        assert "FlexJobs" in flagged


class TestLedgerJobTextPersistence:
    """Job text persistence: every fetched job's raw text is stored with its
    SHA-256, so a run is re-evaluable offline without re-scraping."""
    def test_job_text_persisted_for_every_raw_fetched(self, tmp_path):
        db = tmp_path / "ledger.db"
        ledger = PipelineLedger(db, run_id="run-text-1")
        jobs = [
            {"job_title": "Job A", "company": "Co A", "apply_url": "https://a/1",
             "source": "Board1", "description": "Full description of job A here"},
            {"job_title": "Job B", "company": "Co B", "apply_url": "https://b/2",
             "source": "Board2", "description": "Full description of job B"},
        ]
        ledger.record_jobs(jobs, "raw_fetched")

        with sqlite3.connect(db) as conn:
            count, = conn.execute(
                "SELECT COUNT(*) FROM job_texts WHERE run_id='run-text-1'").fetchone()
        assert count == 2

        import hashlib
        with sqlite3.connect(db) as conn:
            rows = conn.execute(
                "SELECT job_uid, description_sha256 FROM job_texts WHERE run_id='run-text-1'"
            ).fetchall()
        assert len(rows) == 2
        for uid, sha in rows:
            assert len(sha) == 64
            row = conn.execute(
                "SELECT description FROM job_texts WHERE job_uid=?", (uid,)).fetchone()
            expected = hashlib.sha256(row[0].encode("utf-8")).hexdigest()
            assert sha == expected

    def test_description_capped_at_20000(self, tmp_path):
        db = tmp_path / "ledger.db"
        ledger = PipelineLedger(db, run_id="run-text-2")
        long_desc = "x" * 30000
        jobs = [{"job_title": "Long Job", "company": "Co", "apply_url": "https://long/1",
                 "source": "Board", "description": long_desc}]
        ledger.record_jobs(jobs, "raw_fetched")

        with sqlite3.connect(db) as conn:
            desc, = conn.execute("SELECT description FROM job_texts").fetchone()
        assert len(desc) == 20000

    def test_reload_run_jobs_for_reevaluation(self, tmp_path):
        """Reload run jobs from job_texts and verify they can be re-evaluated."""
        db = tmp_path / "ledger.db"
        ledger = PipelineLedger(db, run_id="run-text-3")
        jobs_in = [
            {"job_title": "Backend Developer", "company": "Tech Co",
             "apply_url": "https://example.com/job/1", "source": "TestBoard",
             "description": "We are hiring a Backend Developer with Python and Django experience."},
            {"job_title": "Frontend Developer", "company": "Web Co",
             "apply_url": "https://example.com/job/2", "source": "TestBoard",
             "description": "Frontend role with React and TypeScript."},
        ]
        ledger.record_jobs(jobs_in, "raw_fetched")

        reloaded = ledger.reload_run_jobs("run-text-3")
        assert len(reloaded) == 2

        by_title = {j["job_title"]: j for j in reloaded}
        assert "Backend Developer" in by_title
        assert "Frontend Developer" in by_title

        assert by_title["Backend Developer"]["description"] ==             "We are hiring a Backend Developer with Python and Django experience."
        assert by_title["Backend Developer"]["source"] == "TestBoard"
        assert by_title["Backend Developer"]["apply_url"] == "https://example.com/job/1"

        assert by_title["Frontend Developer"]["description"] ==             "Frontend role with React and TypeScript."
        assert by_title["Frontend Developer"]["job_uid"] is not None

    def test_run_job_text_count(self, tmp_path):
        db = tmp_path / "ledger.db"
        ledger = PipelineLedger(db, run_id="run-text-4")
        jobs = [
            {"job_title": f"Job {i}", "company": f"Co {i}", "apply_url": f"https://example.com/{i}",
             "source": "Board", "description": f"Description {i}"}
            for i in range(5)
        ]
        ledger.record_jobs(jobs, "raw_fetched")
        assert ledger.run_job_text_count("run-text-4") == 5

