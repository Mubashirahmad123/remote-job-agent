"""Phase 2 materials tests — isolated (never calls LLMs or PDF engines)."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient

from api import cache, materials
from api.app import create_app

FP = "fp-materials-001"
SNAP_FP = "fp-snap-001"

SHEET_HEADER = [
    "job_title", "company", "salary", "tech_stack", "timezone", "apply_url",
    "summary", "posted_date_iso", "source", "match_score", "match_reason",
    "scraped_at", "status", "job_fingerprint",
]

SNAPSHOT_ROW = {
    "job_title": "Snap Dev",
    "company": "SnapCo",
    "salary": "",
    "tech_stack": "Python",
    "timezone": "",
    "apply_url": "https://example.com/j/snap",
    "summary": "snapshot job",
    "posted_date_iso": "",
    "source": "SnapshotSource",
    "match_score": "",  # snapshot-shaped: unscored, empty string
    "match_reason": "",
    "scraped_at": "",
    "status": "NEW",
    "job_fingerprint": SNAP_FP,
}


@pytest.fixture()
def seeded_cache(monkeypatch):
    """Seed api.cache fakes per-test; clears TTL cache + enrichment."""
    cache.refresh()
    yield monkeypatch
    cache.refresh()


@pytest.fixture(autouse=True)
def _clean_registry():
    materials.reset_registry()
    yield
    materials.reset_registry()


@pytest.fixture()
def client():
    return TestClient(create_app())


class TestResume:
    def test_post_ok(self, client, monkeypatch):
        monkeypatch.setattr(
            materials, "generate_resume",
            lambda fp: {"status": "ok", "job_fingerprint": FP,
                        "job_title": "Backend Dev", "company": "Acme",
                        "filename": "resume.pdf"},
        )
        r = client.post(f"/api/resume/{FP}")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["filename"] == "resume.pdf"

    def test_post_unknown(self, client, monkeypatch):
        def missing(fp):
            raise LookupError("nope")

        monkeypatch.setattr(materials, "generate_resume", missing)
        assert client.post("/api/resume/nope").status_code == 404

    def test_post_failure(self, client, monkeypatch):
        def boom(fp):
            raise RuntimeError("LLM down")

        monkeypatch.setattr(materials, "generate_resume", boom)
        r = client.post(f"/api/resume/{FP}")
        assert r.status_code == 502

    def test_download_ok(self, client, monkeypatch, tmp_path):
        pdf = tmp_path / "tailored.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")
        monkeypatch.setattr(materials, "RESUMES_DIR", tmp_path)
        materials._record(FP, resume_pdf=str(pdf))
        r = client.get(f"/api/resume/{FP}/download")
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/pdf"
        assert r.content.startswith(b"%PDF")

    def test_download_missing(self, client):
        assert client.get(f"/api/resume/{FP}/download").status_code == 404

    def test_download_traversal_blocked(self, client, monkeypatch, tmp_path):
        monkeypatch.setattr(materials, "RESUMES_DIR", tmp_path)
        materials._record(FP, resume_pdf="/etc/passwd")
        assert client.get(f"/api/resume/{FP}/download").status_code == 404


class TestCoverLetter:
    def test_post_ok(self, client, monkeypatch):
        monkeypatch.setattr(
            materials, "generate_cover_letter",
            lambda fp: {"status": "ok", "job_fingerprint": FP,
                        "job_title": "Backend Dev", "company": "Acme",
                        "filename": "cl.txt", "cover_letter": "Dear Hiring Manager,"},
        )
        r = client.post(f"/api/cover-letter/{FP}")
        assert r.status_code == 200
        assert "Dear Hiring Manager" in r.json()["cover_letter"]

    def test_post_unknown(self, client, monkeypatch):
        def missing(fp):
            raise LookupError("nope")

        monkeypatch.setattr(materials, "generate_cover_letter", missing)
        assert client.post("/api/cover-letter/nope").status_code == 404

    def test_download_ok(self, client, monkeypatch, tmp_path):
        txt = tmp_path / "cl.txt"
        txt.write_text("Dear Hiring Manager,", encoding="utf-8")
        monkeypatch.setattr(materials, "COVER_LETTERS_DIR", tmp_path)
        materials._record(FP, cover_letter_file=str(txt))
        r = client.get(f"/api/cover-letter/{FP}/download")
        assert r.status_code == 200
        assert "Dear Hiring Manager" in r.text

    def test_download_missing(self, client):
        assert client.get(f"/api/cover-letter/{FP}/download").status_code == 404


class TestHygiene:
    def test_no_heavy_imports(self, client, monkeypatch):
        monkeypatch.setattr(
            materials, "generate_resume", lambda fp: {"status": "ok"}
        )
        monkeypatch.setattr(
            materials, "generate_cover_letter", lambda fp: {"status": "ok"}
        )
        client.post(f"/api/resume/{FP}")
        client.post(f"/api/cover-letter/{FP}")
        assert "agents.gemini_tools" not in sys.modules
        assert "tools.resume_generator" not in sys.modules


class TestResolveJobShapes:
    """Backend half of CV Studio bugs 1-2: resolve_job must work for both
    sheet-shaped rows (scored) AND snapshot-shaped rows (match_score "").

    JS-condition notes (frontend-logic-level, no browser available):
    - "3 demo options": frontend/index.html:427-430 hardcodes 3 <option
      value="1|2|3">. resumeStudio.js:41 `if (!jobs.length) return` keeps
      them whenever _jobs() is [] — i.e. store.state.jobs empty or every
      row lacks job_fingerprint (resumeStudio.js:30-36). store.js:187
      fallback sets jobs=[] when JobAgent.MOCK_JOBS undefined, so any
      loadJobs failure (API unreachable) yields exactly the 3 demo options.
    - "demo fallback": generate() resumeStudio.js:168-174 calls
      selectedFingerprint(); /^\\d+$/ on values "1|2|3" returns ''
      (resumeStudio.js:51-56) -> runShrinkEngine() demo. Even with a live
      fp, any createResume/createCoverLetter throw (404/502/UNREACHABLE,
      api.js:56-71) hits the catch at resumeStudio.js:194-197 -> demo.
    - Bug 3: no GET /api/cv or multi-CV backend route exists (see
      TestNoCvEndpoints); resumeStudio.js:59 + index.html:340-411 panels
      are hardcoded static markup with local-only handleUploadedFile.
    """

    def _sheet_vals(self, fp=FP):
        return {
            "ALL JOBS": [
                SHEET_HEADER,
                ["Backend Dev", "Acme", "$80k", "Python", "Remote",
                 "https://example.com/j/1", "APIs", "2026-09-20", "Src",
                 "88", "Matched: python", "2026-09-22 10:00", "NEW", fp],
            ],
            "TOP MATCHES": [SHEET_HEADER],
            "GOOD MATCHES": [SHEET_HEADER],
        }

    def test_resolve_job_sheet_shaped(self, seeded_cache):
        vals = self._sheet_vals()
        seeded_cache.setattr(
            cache, "_read_tab_values", lambda tab: vals.get(tab, []))
        job = materials.resolve_job(FP)
        assert job is not None
        assert job["job_fingerprint"] == FP
        assert job["job_title"] == "Backend Dev"

    def test_resolve_job_snapshot_shaped(self, seeded_cache):
        """Snapshot fallback rows (match_score '') must still resolve."""
        seeded_cache.setattr(cache, "_read_tab_values", lambda tab: [])
        # Offline mode: snapshot fallback only fires while Sheets unwired.
        seeded_cache.setattr(cache, "sheets_configured", lambda: False)
        seeded_cache.setattr(
            cache, "_local_snapshot_rows", lambda: [dict(SNAPSHOT_ROW)])
        job = materials.resolve_job(SNAP_FP)
        assert job is not None
        assert job["job_fingerprint"] == SNAP_FP
        assert job["job_title"] == "Snap Dev"

    def test_resolve_job_unknown_none(self, seeded_cache):
        seeded_cache.setattr(cache, "_read_tab_values", lambda tab: [])
        seeded_cache.setattr(cache, "_local_snapshot_rows", lambda: [])
        assert materials.resolve_job("no-such-fp") is None
        assert materials.resolve_job("") is None

    def test_generate_resume_snapshot_job_ok(
            self, seeded_cache, monkeypatch, tmp_path):
        """generate_resume works on a snapshot-shaped (unscored) job."""
        import types

        pdf = tmp_path / "tailored.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")
        fake_mod = types.ModuleType("tools.resume_generator")
        fake_mod.generate_resume_for_job = lambda job, **kw: pdf
        monkeypatch.setitem(
            sys.modules, "tools.resume_generator", fake_mod)
        monkeypatch.setattr(
            materials, "resolve_job", lambda fp: dict(SNAPSHOT_ROW))
        monkeypatch.setattr(materials, "RESUMES_DIR", tmp_path)
        rec = materials.generate_resume(SNAP_FP)
        assert rec["status"] == "ok"
        assert rec["job_fingerprint"] == SNAP_FP
        assert materials.get_resume_pdf(SNAP_FP) is not None

    def test_generate_resume_snapshot_job_unknown(self, monkeypatch):
        monkeypatch.setattr(materials, "resolve_job", lambda fp: None)
        with pytest.raises(LookupError):
            materials.generate_resume("missing-fp")

    def test_generate_cover_letter_snapshot_job_ok(self, monkeypatch, tmp_path):
        """generate_cover_letter works on a snapshot-shaped job."""
        import types

        fake_mod = types.ModuleType("agents.gemini_tools")
        fake_mod.generate_cover_letter = (
            lambda title, company, summary, applicant:
                "Dear Hiring Manager, this tailored letter is long enough.")
        monkeypatch.setitem(sys.modules, "agents.gemini_tools", fake_mod)
        monkeypatch.setattr(
            materials, "resolve_job", lambda fp: dict(SNAPSHOT_ROW))
        monkeypatch.setattr(materials, "COVER_LETTERS_DIR", tmp_path)
        rec = materials.generate_cover_letter(SNAP_FP)
        assert rec["status"] == "ok"
        assert rec["job_fingerprint"] == SNAP_FP
        assert len(rec["cover_letter"]) >= 20

    def test_generate_cover_letter_snapshot_job_unknown(self, monkeypatch):
        monkeypatch.setattr(materials, "resolve_job", lambda fp: None)
        with pytest.raises(LookupError):
            materials.generate_cover_letter("missing-fp")


class TestNoCvEndpoints:
    """Bug 3: no profile-cache / multi-CV backend endpoints exist yet."""

    def test_no_cv_profile_endpoint(self, client):
        assert client.get("/api/cv").status_code == 404

    def test_no_cvs_listing_endpoint(self, client):
        assert client.get("/api/cvs").status_code == 404
