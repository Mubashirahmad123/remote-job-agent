"""Pipeline ledger isolation + standalone-curation funnel-entry regressions.

Live defects (2026-11-05, same leak class as the matching shadow):
* No conftest isolation for PIPELINE_LEDGER_DB, so pytest runs of curator
  tests appended funnel rows to the LIVE data/pipeline_ledger.db
    (run 8ee3d614ae4d, 05:58 UTC: exactly one terminal row
    `legacy_passed "Matched: python"` for a fixture job with no
    source/company, and zero raw_fetched rows).
* A standalone `curate()` call (no tracker run id, unstamped jobs) minted
  a fresh ledger run id and wrote ONLY terminal rows into it — a half-run
  reconciliation could never sum back to raw_fetched.
"""
from types import SimpleNamespace
from pathlib import Path
import json
import sqlite3

import pytest

from tools.pipeline_ledger import PipelineLedger


def test_pipeline_ledger_env_is_pinned_into_tmp(tmp_path):
    """Tripwire: the conftest isolation must be active, so no curate()
    call anywhere in the suite can reach the live repo ledger."""
    import os
    pinned = os.getenv("PIPELINE_LEDGER_DB", "")
    assert pinned, "conftest must set PIPELINE_LEDGER_DB"
    assert tmp_path.as_posix() in Path(pinned).as_posix(), (
        f"PIPELINE_LEDGER_DB={pinned!r} is not inside the test tmp dir; "
        "test funnel rows would leak into the live ledger")


def _load_curator_module(monkeypatch):
    """Load agents/curator.py privately with the Sheets/CV seams mocked."""
    import importlib.util
    import dotenv
    repo = Path(__file__).resolve().parents[1]
    path = repo / "agents" / "curator.py"
    spec = importlib.util.spec_from_file_location("_curator_ledger_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "cleanup_sheet", lambda *a: None)
    monkeypatch.setattr(module, "get_all_rows", lambda: [])
    monkeypatch.setattr(module, "load_seen_hashes", set)
    monkeypatch.setattr(module, "save_seen_hashes", lambda *a: None)
    monkeypatch.setattr(module, "append_rows", lambda *a: None)
    monkeypatch.setattr(module, "is_allowed_location", lambda job: True)
    # Every job rejected pre-scoring: cheap, no CV/LLM work, and both
    # terminal rows (legacy_rejected) must still balance against raw.
    monkeypatch.setattr(module, "_should_reject", lambda job: (True, "fixture"))
    monkeypatch.setattr(module, "CV_MATCHING_ENABLED", False)
    return module


_JOBS = [
    {"job_title": "Backend Fixture Job", "summary": "Python APIs",
     "apply_url": "https://ledger.test/backend-test"},
    {"job_title": "Frontend Fixture Job", "summary": "React CSS",
     "apply_url": "https://ledger.test/frontend-test"},
]


def test_standalone_curate_records_raw_fetched_and_reconciles(
        monkeypatch, tmp_path, capsys):
    """The 05:58 UTC half-run regression: curate() invoked with no tracker
    run id and unstamped jobs IS the funnel entry. It must record
    raw_fetched for its input, so the run it mints reconciles exactly."""
    curator = _load_curator_module(monkeypatch)
    tracker = SimpleNamespace(stage=lambda *a, **kw: None)  # no run_id
    result = curator.curate(_JOBS, tracker=tracker)

    assert result["status"] == "warning"  # all rejected, nothing passed
    ledger = PipelineLedger()  # same tmp env the curate run just wrote
    with sqlite3.connect(ledger.path) as db:
        (run_id,) = db.execute(
            "SELECT run_id FROM stage_events ORDER BY seq DESC LIMIT 1").fetchone()
    report = ledger.reconcile(run_id)
    assert report["raw_fetched"] == 2
    assert report["terminal_sum"] == 2
    assert report["missing_terminal"] == [] and report["duplicated_terminal"] == []
    assert report["complete"] is True
    out = capsys.readouterr().out
    assert "standalone curation" in out


def test_stamped_jobs_join_the_scrapes_run_without_double_counting(
        monkeypatch, tmp_path):
    """CLI path: scrape_all stamps ledger_run_id on the jobs and already
    recorded raw_fetched under that run. Re-curation (from the stamp)
    must join the SAME run and NOT re-record raw_fetched."""
    curator = _load_curator_module(monkeypatch)
    stamped = [dict(job, ledger_run_id="scrape-run-stamp") for job in _JOBS]
    ledger = PipelineLedger(run_id="scrape-run-stamp")
    ledger.record_jobs(stamped, "raw_fetched")

    tracker = SimpleNamespace(stage=lambda *a, **kw: None)  # no run_id
    curator.curate(stamped, tracker=tracker)

    report = ledger.reconcile()  # same instance path -> same run id
    assert report["raw_fetched"] == 2, "raw_fetched must not double-count"
    assert report["terminal_sum"] == 2
    assert report["complete"] is True


def test_shared_tracker_run_reuses_the_scrape_run(monkeypatch, tmp_path):
    """Same-process path: tracker.run_id set by scrape_all — curate keeps
    appending stages to it, and again raw must not double count."""
    curator = _load_curator_module(monkeypatch)
    ledger = PipelineLedger(run_id="scrape-run-tracker")
    ledger.record_jobs([dict(job) for job in _JOBS], "raw_fetched")

    tracker = SimpleNamespace(stage=lambda *a, **kw: None, run_id="scrape-run-tracker")
    curator.curate([dict(job) for job in _JOBS], tracker=tracker)

    report = ledger.reconcile("scrape-run-tracker")
    assert report["raw_fetched"] == 2
    assert report["terminal_sum"] == 2
    assert report["complete"] is True


def test_conftest_isolation_keeps_the_live_ledger_untouched_by_tests(
        monkeypatch, tmp_path):
    """Negative control for the tripwire: a test reaching for the default
    repo ledger proof — the live ledger is never constructed here."""
    live = Path(__file__).resolve().parents[1] / "data" / "pipeline_ledger.db"
    if live.exists():
        with sqlite3.connect(f"file:{live}?mode=ro", uri=True) as db:
            has_fixture_rows = db.execute(
                '''SELECT COUNT(*) FROM stage_events
                    WHERE job_fingerprint='backend' AND source='AnyTest'
                    ''').fetchone()
        assert has_fixture_rows[0] == 0
