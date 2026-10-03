"""Source-name canonicalization (`RemoteOK` vs `RemoteOKAPI`) — write + read.

The bug: `agents/scrapper.py` sets `source` from the board key, and several
keys are the same provider (RemoteOKAPI/RemoteOK share a URL; Remojobs-* are
Remotive API calls; FounditIN's URL is naukri.com). Every by-source view then
split one board into two.

Fixed on both sides: `tools.sheet_writer.prepare_job_for_sheet` for new rows,
`api.cache` on read so rows ALREADY in the Sheet under the old names merge too.
These tests pin both, plus the duplicate-URL fetch skip.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient

from api import cache
from api.app import create_app
from tools.sources import canonical_source, is_alias

BASE_HEADER = [
    "job_title", "company", "salary", "tech_stack", "timezone", "apply_url",
    "summary", "posted_date_iso", "source", "match_score", "match_reason",
    "scraped_at", "status", "job_fingerprint",
]


def _row(title, source, fp, stack="python"):
    return [
        title, "Acme", "", stack, "Remote", f"https://acme.com/j/{fp}",
        "summary", "2026-09-20", source, "80", "Matched",
        "2026-09-22 10:00", "NEW", fp,
    ]


# Historical rows: the same two providers written under four labels, exactly
# as a real sheet accumulated them across runs.
FAKE_TABS = {
    "ALL JOBS": [
        BASE_HEADER,
        _row("Backend Dev", "RemoteOK", "fp-1"),
        _row("Frontend Dev", "RemoteOKAPI", "fp-2"),
        _row("Platform Eng", "Remotive", "fp-3"),
        _row("API Dev", "Remojobs-Backend", "fp-4"),
        _row("Fullstack Dev", "Remojobs-Fullstack", "fp-5"),
        _row("Data Eng", "Arbeitnow", "fp-6"),
    ],
    "TOP MATCHES": [BASE_HEADER, _row("Backend Dev", "RemoteOKAPI", "fp-1")],
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


class TestCanonicalSource:
    def test_known_aliases_collapse(self):
        assert canonical_source("RemoteOKAPI") == "RemoteOK"
        assert canonical_source("Remojobs-Frontend") == "Remotive"
        assert canonical_source("Remojobs-Backend") == "Remotive"
        assert canonical_source("Remojobs-Fullstack") == "Remotive"
        assert canonical_source("FounditIN") == "Naukri"

    def test_case_and_space_drift(self):
        assert canonical_source("remotive") == "Remotive"
        assert canonical_source("  REMOTEOK  ") == "RemoteOK"
        assert canonical_source("we work remotely") == "WeWorkRemotely"

    def test_unknown_board_is_never_renamed(self):
        # A new board must pass through, not get absorbed into a neighbour.
        assert canonical_source("BrandNewBoard") == "BrandNewBoard"
        assert canonical_source("Remote4me") == "Remote4me"
        assert not is_alias("BrandNewBoard")

    def test_blank_and_none(self):
        assert canonical_source(None) == ""
        assert canonical_source("") == ""
        assert canonical_source("   ") == ""


class TestWritePath:
    def test_prepare_job_for_sheet_canonicalizes(self):
        from tools.sheet_writer import prepare_job_for_sheet

        job = {"job_title": "Dev", "apply_url": "https://x.test/1", "source": "RemoteOKAPI"}
        prepare_job_for_sheet(job, "2026-10-03 10:00")
        assert job["source"] == "RemoteOK"

    def test_write_path_preserves_unknown_boards(self):
        from tools.sheet_writer import prepare_job_for_sheet

        job = {"job_title": "Dev", "apply_url": "https://x.test/2", "source": "BrandNewBoard"}
        prepare_job_for_sheet(job, "2026-10-03 10:00")
        assert job["source"] == "BrandNewBoard"

    def test_missing_source_stays_empty_not_none(self):
        from tools.sheet_writer import prepare_job_for_sheet

        job = {"job_title": "Dev", "apply_url": "https://x.test/3"}
        prepare_job_for_sheet(job, "2026-10-03 10:00")
        assert job["source"] == ""


class TestReadPath:
    """Historical rows must merge without rewriting the Sheet."""

    def test_by_source_merges_aliases(self, client):
        body = client.get("/api/stats").json()
        by_source = body["by_source"]
        assert by_source["RemoteOK"] == 2, by_source      # RemoteOK + RemoteOKAPI
        assert by_source["Remotive"] == 3, by_source      # Remotive + 2x Remojobs-*
        assert by_source["Arbeitnow"] == 1
        for alias in ("RemoteOKAPI", "Remojobs-Backend", "Remojobs-Fullstack"):
            assert alias not in by_source, f"{alias} still splits by_source"

    def test_total_is_unchanged_by_merging(self, client):
        body = client.get("/api/stats").json()
        assert body["total_jobs"] == 6
        assert sum(body["by_source"].values()) == 6

    def test_jobs_expose_canonical_source(self, client):
        rows = client.get("/api/jobs?limit=50").json()
        sources = {r["source"] for r in rows}
        assert sources == {"RemoteOK", "Remotive", "Arbeitnow"}

    def test_source_filter_matches_alias_rows(self, client):
        # Canonical query returns BOTH the canonical and the alias row.
        rows = client.get("/api/jobs?source=RemoteOK&limit=50").json()
        assert len(rows) == 2
        assert {r["job_fingerprint"] for r in rows} == {"fp-1", "fp-2"}

    def test_alias_query_still_works(self, client):
        # An old bookmark/saved filter using the alias must not 0-result.
        rows = client.get("/api/jobs?source=RemoteOKAPI&limit=50").json()
        assert len(rows) == 2
        rows = client.get("/api/jobs?source=Remojobs-Frontend&limit=50").json()
        assert len(rows) == 3

    def test_unknown_source_filter_returns_nothing(self, client):
        assert client.get("/api/jobs?source=NoSuchBoard&limit=50").json() == []


class TestFetchDeduplication:
    def test_duplicate_urls_are_skipped_not_fetched_twice(self):
        """RemoteOKAPI/RemoteOK and FounditIN/Naukri share a URL."""
        import collections

        import agents.scrapper as sc

        by_url = collections.defaultdict(list)
        for name, info in sc.MASTER_BOARDS.items():
            by_url[(info.get("url") or "").strip()].append(name)
        dupes = {u: n for u, n in by_url.items() if len(n) > 1 and u}
        assert dupes, "fixture assumption: duplicate URLs exist in the config"

        # The loop must contain the skip, keyed on URL.
        import inspect

        src = inspect.getsource(sc.scrape_all)
        assert "fetched_urls" in src
        assert "skipped-duplicate" in src

    def test_board_entries_are_retained_for_history(self):
        import agents.scrapper as sc

        # Kept deliberately: board triage history in PRODUCTION.md refers to
        # these names. Dedupe happens at fetch time, not by deleting config.
        assert "RemoteOKAPI" in sc.MASTER_BOARDS
        assert "FounditIN" in sc.MASTER_BOARDS
