"""Phase 1 read-API tests — isolated (no live Sheets, no network).

Fakes api.cache._read_tab_values and api.cache._load_enrichment_map so no
Google credentials are needed.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient

from api import cache
from api.app import create_app

BASE_HEADER = [
    "job_title", "company", "salary", "tech_stack", "timezone", "apply_url",
    "summary", "posted_date_iso", "source", "match_score", "match_reason",
    "scraped_at", "status", "job_fingerprint",
]

TRACKER_HEADER = [
    "job_title", "company", "apply_url", "match_score",
    "applied_date", "status", "follow_up_date", "notes",
    "source", "salary", "contact", "last_updated",
]

STATS_HEADER = [
    "run_at", "total_processed", "new_jobs_added",
    "duplicates_skipped", "top_matches", "good_matches",
]

FP1 = "fp-aaa-111"
FP2 = "fp-bbb-222"

FAKE_TABS = {
    "ALL JOBS": [
        BASE_HEADER,
        ["Backend Dev", "Acme", "$80k", "Python", "Remote",
         "https://acme.com/j/1", "APIs", "2026-09-20", "Arbeitnow",
         "76", "Matched: python", "2026-09-22 10:00", "NEW", FP1],
        ["Frontend Dev", "", "", "React", "Remote",
         "https://acme.com/j/2", "UI", "2026-09-21", "Remotive",
         "73", "Matched: react", "2026-09-22 10:00", "NEW", FP2],
    ],
    "TOP MATCHES": [
        BASE_HEADER,
        ["Backend Dev", "Acme", "$80k", "Python", "Remote",
         "https://acme.com/j/1", "APIs", "2026-09-20", "Arbeitnow",
         "76", "Matched: python", "2026-09-22 10:00", "NEW", FP1],
    ],
    "GOOD MATCHES": [BASE_HEADER],
    "APPLIED": [
        TRACKER_HEADER,
        ["Backend Dev", "Acme", "https://acme.com/j/1", "76",
         "2026-09-22 10:00", "applied", "2026-09-29", "", "Arbeitnow",
         "$80k", "", "2026-09-22 10:00"],
    ],
    "STATS": [
        STATS_HEADER,
        ["2026-09-22 10:00", "147", "2", "145", "1", "0"],
    ],
}

FAKE_ENRICHMENT = {
    FP1: {
        "ranking_score": 96,
        "keyword_score": 76,
        "semantic_score": "",  # curator writes "" when not computed -> null
        "freshness_boost": 20,
        "semantic_computed": False,
        "selected_cv_path": "/app/my_cv.pdf",
        "selected_cv": "my_cv.pdf",
        "location_tags": ["berlin"],
        "location": "",
        "job_type": "",
    }
    # FP2 deliberately absent -> all enrichment fields null, never crash.
}


@pytest.fixture(autouse=True)
def _fake_sheet(monkeypatch):
    monkeypatch.setattr(
        cache, "_read_tab_values", lambda tab: [list(r) for r in FAKE_TABS[tab]]
    )
    monkeypatch.setattr(
        cache, "_load_enrichment_map", lambda force=False: dict(FAKE_ENRICHMENT)
    )
    cache.refresh()
    yield
    cache.refresh()


@pytest.fixture()
def client():
    return TestClient(create_app())


class TestHealth:
    def test_ok(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert "curated_jobs_loaded" in body

    def test_no_secrets_leak(self, client):
        r = client.get("/api/health")
        text = r.text.lower()
        for token in ("gsk_", "AIza", "GOOGLE_SERVICE_ACCOUNT",
                      "GOOGLE_SHEETS_ID", "api_key", "secret"):
            assert token.lower() not in text

    def test_no_heavy_imports_at_startup(self, client):
        client.get("/api/health")
        assert "agents.curator" not in sys.modules
        assert "main" not in sys.modules


class TestJobs:
    def test_list_all(self, client):
        r = client.get("/api/jobs")
        assert r.status_code == 200
        jobs = r.json()
        assert len(jobs) == 2

    def test_enrichment_join_and_empty_to_null(self, client):
        jobs = {j["job_fingerprint"]: j for j in client.get("/api/jobs").json()}
        enriched = jobs[FP1]
        assert enriched["ranking_score"] == 96
        assert enriched["keyword_score"] == 76
        assert enriched["semantic_score"] is None  # "" -> null
        assert enriched["location_tags"] == ["berlin"]
        assert enriched["selected_cv"] == "my_cv.pdf"
        missing = jobs[FP2]
        assert missing["ranking_score"] is None
        assert missing["location_tags"] is None
        assert missing["company"] is None  # "" -> null

    def test_tab_param(self, client):
        r = client.get("/api/jobs", params={"tab": "TOP MATCHES"})
        assert r.status_code == 200
        assert len(r.json()) == 1

    def test_bad_tab(self, client):
        assert client.get("/api/jobs", params={"tab": "NOPE"}).status_code == 400

    def test_search_and_source_filter(self, client):
        assert len(client.get("/api/jobs", params={"q": "frontend"}).json()) == 1
        assert len(client.get("/api/jobs", params={"source": "remotive"}).json()) == 1
        assert len(client.get("/api/jobs", params={"limit": 1}).json()) == 1

    def test_get_one(self, client):
        r = client.get(f"/api/jobs/{FP1}")
        assert r.status_code == 200
        assert r.json()["ranking_score"] == 96

    def test_get_one_missing(self, client):
        assert client.get("/api/jobs/does-not-exist").status_code == 404


class TestStats:
    def test_snapshot(self, client):
        r = client.get("/api/stats")
        assert r.status_code == 200
        body = r.json()
        assert body["total_jobs"] == 2
        assert body["tabs"]["ALL JOBS"] == 2
        assert body["by_source"]["Arbeitnow"] == 1
        assert len(body["stats_rows"]) == 1


class TestTracker:
    def test_list(self, client):
        r = client.get("/api/tracker")
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) == 1
        assert rows[0]["status"] == "applied"
        assert rows[0]["follow_up_date"] == "2026-09-29"

    def test_status_filter(self, client):
        assert len(client.get("/api/tracker", params={"status": "applied"}).json()) == 1
        assert client.get("/api/tracker", params={"status": "offer"}).json() == []

    def test_patch_bad_status(self, client):
        r = client.patch(f"/api/tracker/{FP1}", json={"status": "hired"})
        assert r.status_code == 400

    def test_patch_unknown(self, client):
        r = client.patch("/api/tracker/does-not-exist", json={"status": "offer"})
        assert r.status_code == 404

    def test_patch_ok(self, client, monkeypatch):
        monkeypatch.setattr(cache, "_resolve_tracker_url",
                            lambda fp: "https://acme.com/j/1")
        monkeypatch.setattr(cache, "update_tracker_status",
                            lambda fp, status, notes="": True)
        updated = dict(zip(TRACKER_HEADER, list(FAKE_TABS["APPLIED"][1])))
        updated["status"] = "interviewing"
        monkeypatch.setattr(cache, "get_tracker_rows",
                            lambda status=None, force=False: [updated])
        r = client.patch(f"/api/tracker/{FP1}",
                         json={"status": "interviewing", "notes": "call Tue"})
        assert r.status_code == 200
        assert r.json()["status"] == "interviewing"


class TestRefresh:
    def test_refresh(self, client):
        client.get("/api/jobs")  # warm cache
        r = client.post("/api/jobs/refresh")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["warmed"]["ALL JOBS"] == 2

    def test_refresh_bad_tab(self, client):
        r = client.post("/api/jobs/refresh", json={"tab": "NOPE"})
        assert r.status_code == 400
