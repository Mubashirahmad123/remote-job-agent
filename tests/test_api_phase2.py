"""Phase 2 scrape-run tests — isolated (never runs the real pipeline).

Fakes api.runs._run_simple_pipeline so no boards, Sheets writes, or CV
parsing happen. Real cache.refresh() still runs (harmless, faked Sheets
in phase-1 style are NOT loaded here — refresh on empty cache is safe).
"""
import sys
import os
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient

from api import runs
from api.app import create_app


@pytest.fixture(autouse=True)
def _clean_registry():
    runs.reset_registry()
    yield
    runs.reset_registry()


@pytest.fixture()
def client():
    return TestClient(create_app())


def _wait_for(client, run_id, want=("done", "error"), timeout=30.0):
    """Poll a background run until it settles.

    The budget is generous on purpose. What is being asserted is "this run
    reaches a terminal state", not "it does so within N seconds on an idle
    machine" — the pipeline is mocked, so the only thing the timeout is really
    measuring is how long the OS takes to schedule a daemon thread. On a
    loaded full-suite run that exceeded 10s often enough to redden CI
    intermittently, which is how a scheduling delay gets mistaken for a bug.
    It still fails, and immediately, if the run never completes.
    """
    deadline = time.monotonic() + timeout
    last = {}
    while time.monotonic() < deadline:
        r = client.get(f"/api/scrape/{run_id}")
        assert r.status_code == 200
        last = r.json()
        if last["status"] in want:
            return last
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} never reached {want}: {last}")


class TestStartScrape:
    def test_start_and_finish(self, client, monkeypatch):
        monkeypatch.setattr(
            runs, "_run_simple_pipeline", lambda progress, tracker=None: {"scraped": 10, "curated": 3}
        )
        r = client.post("/api/scrape")
        assert r.status_code == 202
        body = r.json()
        assert body["run_id"]
        assert body["status"] in ("queued", "running")
        final = _wait_for(client, body["run_id"])
        assert final["status"] == "done"
        assert final["scraped"] == 10
        assert final["curated"] == 3
        assert final["finished_at"]

    def test_overlap_conflict(self, client, monkeypatch):
        gate = threading.Event()

        def slow(progress, tracker=None):
            progress("scraping", 0)
            assert gate.wait(timeout=10.0)
            return {"scraped": 1, "curated": 0}

        monkeypatch.setattr(runs, "_run_simple_pipeline", slow)
        first = client.post("/api/scrape")
        assert first.status_code == 202
        second = client.post("/api/scrape")
        assert second.status_code == 409
        gate.set()
        final = _wait_for(client, first.json()["run_id"])
        assert final["status"] == "done"

    def test_wedged_run_blocks_then_restart_recovered(self, client, monkeypatch):
        """AUDIT B9 (2026-10-28): there is no watchdog on purpose — api/runs.py
        documents why a recorded-only watchdog would be worse than the 409.
        The documented operator recovery for a wedged run is an API restart,
        which empties the in-memory registry and clears the 409. This test
        pins that contract so the caveat cannot silently stop being true."""
        release = threading.Event()

        def hang(progress, tracker=None):
            release.wait(timeout=15.0)
            return {"scraped": 0, "curated": 0}

        monkeypatch.setattr(runs, "_run_simple_pipeline", hang)
        first = client.post("/api/scrape")
        assert first.status_code == 202
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if (runs.get_run(first.json()["run_id"]) or {}).get("status") == "running":
                break
            time.sleep(0.05)
        assert (runs.get_run(first.json()["run_id"]) or {}).get("status") == "running"
        second = client.post("/api/scrape")
        assert second.status_code == 409
        # Restart-equivalent recovery: the registry is in-memory, so a restart
        # IS a registry clear — the wedged thread dies with the process.
        runs.reset_registry()
        third = client.post("/api/scrape")
        assert third.status_code == 202
        release.set()

    def test_worker_error_recorded(self, client, monkeypatch, caplog):
        def boom(progress, tracker=None):
            raise RuntimeError("boards exploded")
        monkeypatch.setattr(runs, "_run_simple_pipeline", boom)
        r = client.post("/api/scrape")
        assert r.status_code == 202
        final = _wait_for(client, r.json()["run_id"])
        assert final["status"] == "error"
        assert final["finished_at"]
        # Q6 (2026-10-18): the record carries the incident-id pattern (same
        # contract as api/errors.py) instead of raw exception text — the
        # message must NOT reach the dashboard, the full traceback must go
        # to the server log, and the id in the record must be greppable
        # there.
        assert "boards exploded" not in final["error"]
        assert "Scrape failed" in final["error"]
        assert "incident" in final["error"]
        # Full traceback landed in the server log under that incident id
        # (caplog records it; "Captured log call" above shows the same).
        assert "boards exploded" in caplog.text

    def test_no_heavy_imports_at_startup(self, client, monkeypatch):
        monkeypatch.setattr(
            runs, "_run_simple_pipeline", lambda progress, tracker=None: {"scraped": 0, "curated": 0}
        )
        before = set(sys.modules)
        r = client.post("/api/scrape")
        assert r.status_code == 202
        # The contract (api/runs.py docstring) is that the API never imports
        # the pipeline itself. It may already be present in sys.modules when
        # another test file imported agents.curator first (order-dependent),
        # so assert on what the RUN added, not on global absence.
        added = set(sys.modules) - before
        assert "agents.curator" not in added
        assert "main" not in added


class TestGetScrape:
    def test_get_one_and_list(self, client, monkeypatch):
        monkeypatch.setattr(
            runs, "_run_simple_pipeline", lambda progress, tracker=None: {"scraped": 5, "curated": 1}
        )
        run_id = client.post("/api/scrape").json()["run_id"]
        final = _wait_for(client, run_id)
        assert final["run_id"] == run_id
        listed = client.get("/api/scrape").json()
        assert any(r["run_id"] == run_id for r in listed)

    def test_get_unknown(self, client):
        assert client.get("/api/scrape/nope123").status_code == 404

    def test_run_record_has_board_fields(self, client, monkeypatch):
        monkeypatch.setattr(
            runs, "_run_simple_pipeline", lambda progress, tracker=None: {"scraped": 0, "curated": 0}
        )
        body = client.post("/api/scrape").json()
        for field in ("boards_total", "boards_done", "boards_ok",
                      "boards_failed", "boards_empty", "fetched"):
            assert field in body, field

    def test_run_record_has_structured_events(self, client, monkeypatch):
        def pipeline(progress, tracker=None):
            progress("scraping", 2)
            progress("curating", 2)
            return {"scraped": 2, "curated": 1}

        monkeypatch.setattr(runs, "_run_simple_pipeline", pipeline)
        run_id = client.post("/api/scrape").json()["run_id"]
        final = _wait_for(client, run_id)
        assert final["events"]
        assert final["events"][0]["type"] == "lifecycle"
        assert final["events"][-1]["type"] == "complete"
        assert all(not key.startswith("_") for key in final)


class TestSummarizeBoards:
    def test_rollup(self):
        boards = {
            "A": {"status": "ok", "fetched": 10},
            "B": {"status": "error", "fetched": 0},
            "C": {"status": "empty", "fetched": 0},
            "D": {"status": "skipped-js", "fetched": 0},
            "E": {"status": "ok", "fetched": "7"},
            "F": "garbage",
        }
        s = runs._summarize_boards(boards, 45)
        assert s == {
            "boards_total": 45,
            "boards_done": 5,
            "boards_ok": 2,
            "boards_failed": 1,
            "boards_empty": 2,
            "fetched": 17,
        }

    def test_empty(self):
        assert runs._summarize_boards({}, 0)["boards_done"] == 0


def test_progress_counts_optional_tracker_passes_in_both_plan_and_final(monkeypatch):
    """A1: configured boards + optional passes are one shared work-item plan."""
    from types import SimpleNamespace
    from agents import scrapper
    from tools.yield_tracker import YieldTracker

    monkeypatch.setattr(scrapper, "MASTER_BOARDS", {"BoardA": {}, "BoardB": {}})
    assert set(scrapper.SYNTHETIC_TRACKER_BOARDS) == {
        "JobSpy", "PlaywrightStealth", "Crawl4AI-JustRemote",
    }
    assert runs._board_total() == 5
    statuses = ["ok", "empty", "skipped-disabled", "error", "ok"]
    names = ["BoardA", "BoardB", *scrapper.SYNTHETIC_TRACKER_BOARDS]
    tracker = YieldTracker()

    def scrape_all(debug=False, tracker=None):
        for index, (name, status) in enumerate(zip(names, statuses), start=1):
            tracker.scrape(name, status, fetched=1 if status == "ok" else 0)
            summary = runs._summarize_boards(tracker.snapshot(), runs._board_total())
            assert summary["boards_done"] == index
            assert summary["boards_done"] <= summary["boards_total"]
        # A curation-only source must not count as an additional scan.
        tracker.stage("country", {"unplanned-source": 3})
        return [{"job_title": "fake"}]

    monkeypatch.setattr(scrapper, "scrape_all", scrape_all)
    monkeypatch.setitem(sys.modules, "agents.curator", SimpleNamespace(curate=lambda jobs, tracker: {"top_jobs": []}))
    monkeypatch.setattr(tracker, "save", lambda: None)
    monkeypatch.setattr(runs, "_write_curated_cache", lambda jobs, top: None)
    final = runs._run_simple_pipeline(lambda *args: None, tracker)
    assert final["boards_total"] == final["boards_done"] == 5
    assert (final["boards_ok"], final["boards_failed"], final["boards_empty"]) == (2, 1, 2)
    assert final["fetched"] == 2


def test_board_plan_union_does_not_double_count_reused_synthetic_name(monkeypatch):
    from agents import scrapper

    monkeypatch.setattr(scrapper, "MASTER_BOARDS", {"JobSpy": {}, "BoardA": {}})
    assert runs._board_total() == 4


def test_tracker_snapshot_is_independent_during_concurrent_row_additions():
    from tools.yield_tracker import YieldTracker

    tracker = YieldTracker()
    tracker.scrape("start", "ok", 1)
    snapshot = tracker.snapshot()
    tracker.scrape("start", "error", 0)
    assert snapshot["start"] == {"status": "ok", "fetched": 1}

    def add_rows():
        for index in range(4000):
            tracker.scrape(str(index), "ok", 1)

    writer = threading.Thread(target=add_rows)
    writer.start()
    while writer.is_alive():
        rows = tracker.snapshot()
        runs._summarize_boards(rows, 5000)
        runs._board_snapshot(rows)
    writer.join()
    assert len(tracker.snapshot()) == 4001


def test_real_scrape_orchestrator_emits_only_the_planned_tracker_rows(monkeypatch):
    """Exercise real scrape_all control flow with every external scraper faked."""
    from types import SimpleNamespace
    from agents import scrapper
    from tools.yield_tracker import YieldTracker

    configured = {'One': {'url': 'https://one.invalid'}, 'Two': {'url': 'https://two.invalid'}}
    monkeypatch.setattr(scrapper, 'MASTER_BOARDS', configured)
    monkeypatch.setattr(scrapper, 'JS_RENDERED_BOARDS', set())
    monkeypatch.setattr(scrapper, 'time', SimpleNamespace(sleep=lambda seconds: None))
    monkeypatch.setattr(scrapper, '_load_board_health', lambda: {})
    monkeypatch.setattr(scrapper, '_board_breaker_check', lambda *args: False)
    monkeypatch.setattr(scrapper, 'fetch_jobs_from_board', lambda *args: [])
    monkeypatch.setenv('ENABLE_JOBSPY', 'false')
    monkeypatch.setitem(sys.modules, 'tools.playwright_scraper',
                        SimpleNamespace(scrape_stealth_boards=lambda debug=False: []))
    monkeypatch.setitem(sys.modules, 'tools.crawl4ai_scraper',
                        SimpleNamespace(scrape_justremote_with_crawl4ai=lambda debug=False: []))
    monkeypatch.setitem(sys.modules, 'agents.gemini_tools', SimpleNamespace(
        reset_llm_call_stats=lambda: None,
        get_llm_call_stats=lambda reset=False: {'attempts': 0}))
    tracker = YieldTracker()
    assert scrapper.scrape_all(tracker=tracker) == []
    expected = set(configured) | set(scrapper.SYNTHETIC_TRACKER_BOARDS)
    assert set(tracker.boards) == expected
    summary = runs._summarize_boards(tracker.snapshot(), runs._board_total())
    assert summary['boards_done'] == summary['boards_total'] == len(expected)
