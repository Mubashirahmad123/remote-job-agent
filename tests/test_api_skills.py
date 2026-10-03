"""GET /api/skills tests — isolated (no live Sheets, no network).

Fakes api.cache._read_tab_values so the aggregate runs against a known
tech_stack corpus containing the real-world messiness the column carries:
alias drift (node/nodejs/Node.js), duplicates inside one cell, blank cells,
prose leakage, and separator variety.
"""
import os
import sys

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


def _row(title, stack, fp):
    return [
        title, "Acme", "$80k", stack, "Remote", f"https://acme.com/j/{fp}",
        "summary", "2026-09-20", "Arbeitnow", "80", "Matched",
        "2026-09-22 10:00", "NEW", fp,
    ]


FAKE_TABS = {
    "ALL JOBS": [
        BASE_HEADER,
        # Alias drift for the same two skills across rows.
        _row("Backend Dev", "Python, nodejs, PostgreSQL", "fp-1"),
        _row("Platform Eng", "python; Node.js | postgres", "fp-2"),
        _row("API Dev", "PYTHON, node", "fp-3"),
        # Duplicate inside one cell must count once for that job.
        _row("Data Eng", "Python, python, Airflow", "fp-4"),
        # Blank stack: counted in total_jobs, excluded from jobs_with_stack.
        _row("Recruiter", "", "fp-5"),
        # Noise + a slash-joined token that must NOT be split.
        _row("DevOps", "CI/CD, Docker, n/a, 5+, various", "fp-6"),
        # Newline separator and bracket/quote junk.
        _row("Frontend", 'React\n"TypeScript"\n(CSS)', "fp-7"),
        # Prose leakage: >3-word token is dropped, real skills kept.
        _row("Fullstack", "React, strong experience with distributed teams", "fp-8"),
    ],
    "TOP MATCHES": [
        BASE_HEADER,
        _row("Backend Dev", "Python, Kubernetes", "fp-1"),
    ],
    "GOOD MATCHES": [BASE_HEADER],
    "APPLIED": [BASE_HEADER],
    "STATS": [["run_at", "total_processed"]],
}


@pytest.fixture(autouse=True)
def _fake_sheet(monkeypatch):
    monkeypatch.setattr(
        cache, "_read_tab_values", lambda tab: [list(r) for r in FAKE_TABS[tab]]
    )
    monkeypatch.setattr(cache, "_load_enrichment_map", lambda force=False: {})
    cache.refresh()
    yield
    cache.refresh()


@pytest.fixture()
def client():
    return TestClient(create_app())


def _by_name(body):
    return {s["name"]: s for s in body["skills"]}


class TestSkillsEndpoint:
    def test_shape_and_counts(self, client):
        r = client.get("/api/skills")
        assert r.status_code == 200
        body = r.json()
        assert body["tab"] == "ALL JOBS"
        assert body["total_jobs"] == 8          # blank-stack row included
        assert body["jobs_with_stack"] == 7     # blank-stack row excluded
        assert body["unique_skills"] >= 8
        names = _by_name(body)
        # node/nodejs/Node.js collapse to one entry across 3 jobs.
        assert names["Node.js"]["count"] == 3
        # python/PYTHON/Python collapse; the in-cell duplicate counts once.
        assert names["Python"]["count"] == 4
        assert names["PostgreSQL"]["count"] == 2
        assert names["React"]["count"] == 2

    def test_pct_is_share_of_stack_bearing_jobs(self, client):
        body = client.get("/api/skills").json()
        names = _by_name(body)
        # 4 of 7 stack-bearing rows mention Python -> 57%, not 4/8 = 50%.
        assert names["Python"]["pct"] == round(4 * 100 / 7)

    def test_sorted_desc_with_alphabetical_tiebreak(self, client):
        body = client.get("/api/skills?limit=100").json()
        counts = [s["count"] for s in body["skills"]]
        assert counts == sorted(counts, reverse=True)
        # Equal counts stay alphabetically ordered => stable across reads.
        for a, b in zip(body["skills"], body["skills"][1:]):
            if a["count"] == b["count"]:
                assert a["name"].lower() <= b["name"].lower()

    def test_slash_token_not_split(self, client):
        names = _by_name(client.get("/api/skills?limit=100").json())
        assert "CI/CD" in names
        assert "CI" not in names and "CD" not in names

    def test_noise_dropped(self, client):
        names = _by_name(client.get("/api/skills?limit=100").json())
        for junk in ("N/A", "Na", "5+", "Various", "", "Strong Experience With Distributed Teams"):
            assert junk not in names

    def test_quotes_and_brackets_stripped(self, client):
        names = _by_name(client.get("/api/skills?limit=100").json())
        assert "TypeScript" in names and "CSS" in names

    def test_limit_caps_results(self, client):
        body = client.get("/api/skills?limit=3").json()
        assert len(body["skills"]) == 3
        # unique_skills still reports the full count, not the truncated page.
        assert body["unique_skills"] > 3

    def test_tab_filter(self, client):
        body = client.get("/api/skills?tab=TOP MATCHES").json()
        assert body["tab"] == "TOP MATCHES"
        assert body["total_jobs"] == 1
        assert _by_name(body)["Kubernetes"]["count"] == 1

    def test_empty_tab_is_zeroed_not_an_error(self, client):
        body = client.get("/api/skills?tab=GOOD MATCHES").json()
        assert body["total_jobs"] == 0
        assert body["jobs_with_stack"] == 0
        assert body["skills"] == []

    def test_unknown_tab_400(self, client):
        r = client.get("/api/skills?tab=APPLIED")
        assert r.status_code == 400
        assert "Unknown tab" in r.json()["detail"]

    def test_limit_bounds_enforced(self, client):
        assert client.get("/api/skills?limit=0").status_code == 422
        assert client.get("/api/skills?limit=101").status_code == 422

    def test_sheet_failure_returns_empty_not_500(self, client, monkeypatch):
        def boom(tab):
            raise RuntimeError("Sheets down")

        monkeypatch.setattr(cache, "_read_tab_values", boom)
        cache.refresh()
        r = client.get("/api/skills")
        assert r.status_code == 200
        assert r.json()["skills"] == []

    def test_requires_token_when_set(self, monkeypatch):
        monkeypatch.setenv("API_TOKEN", "secret-token")
        c = TestClient(create_app())
        assert c.get("/api/skills").status_code == 401
        ok = c.get("/api/skills", headers={"Authorization": "Bearer secret-token"})
        assert ok.status_code == 200


class TestCanonicalization:
    """Unit-level checks on the splitter (no HTTP)."""

    def test_aliases_collapse(self):
        assert cache.extract_skills("js, JS, javascript") == ["JavaScript"]
        assert cache.extract_skills("k8s") == ["Kubernetes"]
        assert cache.extract_skills("golang") == ["Go"]

    def test_mixed_separators(self):
        got = cache.extract_skills("Python; Go | Rust, Elixir")
        assert got == ["Python", "Go", "Rust", "Elixir"]

    def test_acronyms_stay_upper(self):
        assert cache.extract_skills("aws, sql, api") == ["AWS", "SQL", "API"]

    def test_hand_cased_tokens_preserved(self):
        assert cache.extract_skills("iOS, GraphQL") == ["iOS", "GraphQL"]

    def test_list_input_supported(self):
        assert cache.extract_skills(["React", "react"]) == ["React"]

    def test_none_and_blank(self):
        assert cache.extract_skills(None) == []
        assert cache.extract_skills("") == []
        assert cache.extract_skills(",,  ,;") == []

    def test_overlong_token_dropped(self):
        assert cache.extract_skills("x" * 40) == []
