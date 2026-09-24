"""Live-shape freshness tests — 12-row Sheet mirror (2026-09-19..22).

Isolated: stubs api.cache._read_tab_values (test_api_phase1 pattern) —
never hits live Sheets/LLM. Locks in:
  - /api/jobs + cache.get_jobs carry fingerprints, scores, posted dates
    for all 12 rows (incl. empty-match_score rows)
  - materials.resolve_job succeeds for scored AND empty-score rows
  - refresh() actually clears (stale rows gone after Sheet change)
  - snapshot fallback never fires while Sheets is configured
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient

from api import cache, materials
from api.app import create_app
from api.schemas import JobOut

HDR = [
    "job_title", "company", "salary", "tech_stack", "timezone", "apply_url",
    "summary", "posted_date_iso", "source", "match_score", "match_reason",
    "scraped_at", "status", "job_fingerprint",
]


def _live_vals():
    """12 live-shaped Sheet rows; every 4th row has empty match_score."""
    vals = [list(HDR)]
    for i in range(12):
        day = 19 + (i % 4)
        ms = "" if i % 4 == 3 else str(60 + i)
        vals.append([
            f"Job {i}", f"Co {i}", f"${80 + i}k", "Python", "Remote",
            f"https://example.com/j/{i}", f"summary {i}",
            f"2026-09-{day}", "Arbeitnow", ms, "Matched: python",
            "2026-09-22 10:00", "NEW", f"fp-live-{i:03d}",
        ])
    return vals


@pytest.fixture()
def live_sheet(monkeypatch):
    vals = _live_vals()
    monkeypatch.setattr(
        cache, "_read_tab_values",
        lambda tab: [list(r) for r in vals] if tab == "ALL JOBS" else [list(HDR)],
    )
    monkeypatch.setattr(cache, "_load_enrichment_map", lambda force=False: {})
    cache.refresh()
    yield vals
    cache.refresh()


@pytest.fixture()
def client():
    return TestClient(create_app())


class TestLiveShape:
    def test_get_jobs_shape_direct(self, live_sheet):
        jobs = cache.get_jobs()
        assert len(jobs) == 12
        for j in jobs:
            assert (j.get("job_fingerprint") or "").strip(), j
            assert (j.get("posted_date_iso") or "").strip(), j
            ms = j.get("match_score")
            assert ms is None or isinstance(ms, str), j
            assert j["posted_date_iso"].strip()[:10] in (
                "2026-09-19", "2026-09-20", "2026-09-21", "2026-09-22")

    def test_jobs_endpoint_shape(self, live_sheet, client):
        r = client.get("/api/jobs", params={"limit": 50})
        assert r.status_code == 200
        jobs = r.json()
        assert len(jobs) == 12
        for j in jobs:
            assert j["job_fingerprint"]
            assert j["posted_date_iso"]
            JobOut(**j)  # empty score -> null, never 500

    def test_get_one_empty_score_row(self, live_sheet, client):
        fp = "fp-live-003"  # empty match_score row
        r = client.get(f"/api/jobs/{fp}")
        assert r.status_code == 200
        assert r.json()["match_score"] is None
        assert r.json()["posted_date_iso"] == "2026-09-22"

    def test_resolve_low_and_empty_score(self, live_sheet):
        scored = materials.resolve_job("fp-live-000")
        assert scored and scored["job_title"] == "Job 0"
        empty = materials.resolve_job("fp-live-003")
        assert empty and empty["job_title"] == "Job 3"
        assert (empty.get("match_score") or "") == ""
        assert materials.resolve_job("nope") is None


class TestRefreshClears:
    def test_refresh_drops_stale(self, monkeypatch):
        vals = _live_vals()
        monkeypatch.setattr(
            cache, "_read_tab_values",
            lambda tab: [list(r) for r in vals] if tab == "ALL JOBS" else [list(HDR)],
        )
        monkeypatch.setattr(cache, "_load_enrichment_map", lambda force=False: {})
        cache.refresh()
        assert len(cache.get_jobs()) == 12
        # Sheet shrinks to 1 row; cached copy still stale until refresh().
        vals[:] = [vals[0], vals[1]]
        assert len(cache.get_jobs()) == 12  # TTL still serving stale
        cleared = cache.refresh()
        assert "ALL JOBS" in cleared
        assert len(cache.get_jobs(force=True)) == 1
        cache.refresh()


class TestNoStaleSnapshot:
    def test_empty_read_stays_empty_when_sheets_configured(self, monkeypatch):
        monkeypatch.setattr(cache, "_read_tab_values", lambda tab: [])
        monkeypatch.setattr(cache, "sheets_configured", lambda: True)
        cache.refresh()
        assert cache.get_tab_rows("ALL JOBS", force=True) == []
        cache.refresh()

    def test_empty_read_falls_back_only_when_unwired(self, monkeypatch):
        monkeypatch.setattr(cache, "_read_tab_values", lambda tab: [])
        monkeypatch.setattr(cache, "sheets_configured", lambda: False)
        monkeypatch.setattr(
            cache, "_local_snapshot_rows",
            lambda: [{"job_title": "Snap", "apply_url": "https://x/y",
                      "job_fingerprint": "fp-snap"}],
        )
        cache.refresh()
        assert len(cache.get_tab_rows("ALL JOBS", force=True)) == 1
        cache.refresh()
