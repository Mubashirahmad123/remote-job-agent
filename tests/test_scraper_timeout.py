"""Tests for the per-scraper time budget in agents/scrapper.py.

A hung board (e.g. JobSpy on LinkedIn, whose scrape_jobs() call has no
timeout of its own) must never stall the whole run: _run_optional_scraper
abandons it after the budget, records an error, and the run continues.
"""
import sys
import os
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.scrapper import (
    _run_optional_scraper,
    _scraper_timeout_seconds,
)
from tools.yield_tracker import YieldTracker


def _fast_scraper(debug=False):
    return [{"job_title": "Dev", "company": "Acme"}]


def _raising_scraper(debug=False):
    raise RuntimeError("board exploded")


def _hanging_scraper(debug=False):
    time.sleep(60)
    return [{"job_title": "Too late", "company": "Hung"}]


class TestScraperTimeoutSeconds:
    def test_default(self, monkeypatch):
        monkeypatch.delenv("SCRAPER_TIMEOUT", raising=False)
        assert _scraper_timeout_seconds() == 300.0

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("SCRAPER_TIMEOUT", "120")
        assert _scraper_timeout_seconds() == 120.0

    def test_minimum_clamp(self, monkeypatch):
        monkeypatch.setenv("SCRAPER_TIMEOUT", "1")
        assert _scraper_timeout_seconds() == 30.0

    def test_invalid_env_falls_back(self, monkeypatch):
        monkeypatch.setenv("SCRAPER_TIMEOUT", "not-a-number")
        assert _scraper_timeout_seconds() == 300.0


class TestRunOptionalScraper:
    def test_fast_scraper_unchanged(self):
        jobs, working, failed = [], [], []
        tracker = YieldTracker()
        _run_optional_scraper("Fast", _fast_scraper, jobs, working, failed, tracker=tracker)
        assert len(jobs) == 1
        assert working == ["Fast"]
        assert failed == []
        assert tracker.boards["Fast"]["status"] == "ok"

    def test_raising_scraper_records_error(self):
        jobs, working, failed = [], [], []
        tracker = YieldTracker()
        _run_optional_scraper("Boom", _raising_scraper, jobs, working, failed, tracker=tracker)
        assert jobs == []
        assert working == []
        assert failed == ["Boom"]
        assert tracker.boards["Boom"]["status"] == "error"

    def test_hanging_scraper_abandoned_after_budget(self):
        jobs, working, failed = [], [], []
        tracker = YieldTracker()
        started = time.monotonic()
        # Budget far below the 60s hang: must return in ~1s, not 60s.
        _run_optional_scraper("Hung", _hanging_scraper, jobs, working, failed,
                              tracker=tracker, timeout=1)
        elapsed = time.monotonic() - started
        assert elapsed < 30
        assert jobs == []  # late result discarded, never merged
        assert working == []
        assert failed == ["Hung"]
        assert tracker.boards["Hung"]["status"] == "error"
        assert "timeout" in str(tracker.boards["Hung"].get("error", ""))

    def test_running_state_visible_mid_board(self):
        release = threading.Event()
        observed = {}

        def _blocking_scraper(debug=False):
            release.wait(timeout=30)
            return []

        tracker = YieldTracker()
        thread = threading.Thread(
            target=_run_optional_scraper,
            args=("Slow", _blocking_scraper, [], [], []),
            kwargs={"tracker": tracker, "timeout": 30},
            daemon=True,
        )
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if tracker.boards.get("Slow", {}).get("status") == "running":
                    observed["running"] = True
                    break
                time.sleep(0.05)
            assert observed.get("running") is True
        finally:
            release.set()
            thread.join(timeout=10)
