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


def _wait_for(client, run_id, want=("done", "error"), timeout=10.0):
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

    def test_worker_error_recorded(self, client, monkeypatch):
        def boom(progress, tracker=None):
            raise RuntimeError("boards exploded")

        monkeypatch.setattr(runs, "_run_simple_pipeline", boom)
        r = client.post("/api/scrape")
        assert r.status_code == 202
        final = _wait_for(client, r.json()["run_id"])
        assert final["status"] == "error"
        assert "boards exploded" in final["error"]
        assert final["finished_at"]

    def test_no_heavy_imports_at_startup(self, client, monkeypatch):
        monkeypatch.setattr(
            runs, "_run_simple_pipeline", lambda progress, tracker=None: {"scraped": 0, "curated": 0}
        )
        r = client.post("/api/scrape")
        assert r.status_code == 202
        assert "agents.curator" not in sys.modules
        assert "main" not in sys.modules


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
