"""Studio dropdown data-contract regression — /api/jobs shape, not values.

User complaint: Studio dropdown showed old jobs. The dropdown
(frontend/js/components/resumeStudio.js populateJobSelect) is fed by
GET /api/jobs via JobAgent.store.normalizeJob, which needs per row:
  - non-empty ``job_fingerprint`` (option value + generate target), and
  - non-empty ``posted_date_iso`` (posted date / age note).

This suite locks that contract at the API boundary: it stubs
``api.cache._read_tab_values`` with sheet-shaped rows spanning the
ground-truth window (2026-09-19..22) plus one stale 2026-08-30 row, and
asserts SHAPE (keys present, non-empty, unique) — never exact values,
counts, or titles, so the test survives real sheet churn.

Isolated: no live Sheets, no LLM, no browser (TESTER.md iron rules).
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

# Sheet-shaped fake: fresh window rows + one stale Aug-30 row.
# Shape matters (fp + posted_date_iso present); values are arbitrary.
FAKE_VALUES = [
    BASE_HEADER,
    ["Backend Dev", "Acme", "$80k", "Python", "Remote",
     "https://acme.com/j/1", "APIs", "2026-09-19", "Arbeitnow",
     "76", "Matched: python", "2026-09-19 10:00", "NEW", "fp-fresh-19"],
    ["Frontend Dev", "Beta", "", "React", "Remote",
     "https://beta.com/j/2", "UI", "2026-09-20", "Remotive",
     "73", "Matched: react", "2026-09-20 10:00", "NEW", "fp-fresh-20"],
    ["Data Engineer", "Gamma", "", "SQL", "Remote",
     "https://gamma.com/j/3", "Pipes", "2026-09-21", "Arbeitnow",
     "71", "Matched: sql", "2026-09-21 10:00", "NEW", "fp-fresh-21"],
    ["DevOps Eng", "Delta", "", "AWS", "Remote",
     "https://delta.com/j/4", "Infra", "2026-09-22", "Remotive",
     "70", "Matched: aws", "2026-09-22 10:00", "NEW", "fp-fresh-22"],
    ["Legacy Role", "OldCo", "", "Java", "Remote",
     "https://oldco.com/j/old", "Old", "2026-08-30", "Arbeitnow",
     "60", "Matched: java", "2026-08-30 10:00", "NEW", "fp-stale-0830"],
]

OLD_FP = "fp-stale-0830"


@pytest.fixture(autouse=True)
def _fake_sheet(monkeypatch):
    monkeypatch.setattr(
        cache, "_read_tab_values", lambda tab: [list(r) for r in FAKE_VALUES]
        if tab == "ALL JOBS" else [list(BASE_HEADER)],
    )
    # No enrichment: contract must hold on base sheet columns alone.
    monkeypatch.setattr(cache, "_load_enrichment_map",
                        lambda force=False: {})
    cache.refresh()
    yield
    cache.refresh()


@pytest.fixture()
def client():
    return TestClient(create_app())


class TestJobsDataContract:
    """Every /api/jobs row carriesDropdown-usable fp + posted date."""

    def test_every_row_has_non_empty_fingerprint(self, client):
        jobs = client.get("/api/jobs", params={"limit": 500}).json()
        assert len(jobs) == len(FAKE_VALUES) - 1  # header excluded
        for job in jobs:
            fp = job.get("job_fingerprint")
            assert isinstance(fp, str) and fp.strip(), (
                f"row missing job_fingerprint: {job.get('job_title')!r}"
            )

    def test_every_row_has_non_empty_posted_date_iso(self, client):
        jobs = client.get("/api/jobs", params={"limit": 500}).json()
        for job in jobs:
            posted = job.get("posted_date_iso")
            assert isinstance(posted, str) and posted.strip(), (
                f"row {job.get('job_fingerprint')!r} missing posted_date_iso"
            )
            assert posted.strip()[:4].isdigit(), (
                f"row {job.get('job_fingerprint')!r} posted_date_iso "
                f"not date-shaped: {posted!r}"
            )

    def test_fingerprints_unique(self, client):
        jobs = client.get("/api/jobs", params={"limit": 500}).json()
        fps = [j["job_fingerprint"] for j in jobs]
        assert len(set(fps)) == len(fps)

    def test_stale_row_kept_with_contract_intact(self, client):
        """Staleness is the UI's call — the API must not drop the old row
        nor strip its contract fields (dropdown shows the age note)."""
        jobs = {j["job_fingerprint"]: j
                for j in client.get("/api/jobs", params={"limit": 500}).json()}
        assert OLD_FP in jobs, "Aug-30 row must still be served"
        assert jobs[OLD_FP]["posted_date_iso"].strip().startswith("2026-08-30")

    def test_get_one_stale_row(self, client):
        r = client.get(f"/api/jobs/{OLD_FP}")
        assert r.status_code == 200
        body = r.json()
        assert body["job_fingerprint"] == OLD_FP
        assert body["posted_date_iso"].strip().startswith("2026-08-30")


class TestJobsContractFailures:
    """Failure paths: bad tab, unknown fp, empty-fp row shape."""

    def test_bad_tab_400(self, client):
        assert client.get("/api/jobs", params={"tab": "NOPE"}).status_code == 400

    def test_unknown_fingerprint_404(self, client):
        assert client.get("/api/jobs/does-not-exist").status_code == 404

    def test_empty_fingerprint_row_surfaces_null(self, client, monkeypatch):
        """Documents WHY the backend must never write empty fingerprints:
        the schema coerces "" -> null, leaving the dropdown with no
        generatable option value for that row."""
        bad = [list(BASE_HEADER),
               ["No FP Role", "NoFP", "", "Go", "Remote",
                "https://nofp.com/j/1", "x", "2026-09-22", "Remotive",
                "70", "m", "2026-09-22 10:00", "NEW", ""]]
        monkeypatch.setattr(
            cache, "_read_tab_values",
            lambda tab: [list(r) for r in bad],
        )
        cache.refresh()
        jobs = client.get("/api/jobs").json()
        assert len(jobs) == 1
        assert jobs[0]["job_fingerprint"] is None
        assert jobs[0]["posted_date_iso"] == "2026-09-22"
