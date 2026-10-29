"""CV Studio read tests — isolated (no live Sheets, no LLM, no PDF engines).

Covers:
  1. materials.resolve_job for real Sheet rows AND snapshot rows
     (snapshot rows carry pipeline-MD5 fingerprints).
  2. GET /api/cv/profile happy path + 501-by-design path.
  3. GET /api/cv/variants happy path + missing-dir -> [] path.
  4. No-heavy-imports guard (agents.curator / main stay out of sys.modules).
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient

from api import cache, materials
from api.app import create_app

BASE_HEADER = [
    "job_title", "company", "salary", "tech_stack", "timezone", "apply_url",
    "summary", "posted_date_iso", "source", "match_score", "match_reason",
    "scraped_at", "status", "job_fingerprint",
]

FP_SHEET = "fp-sheet-001"

FAKE_PROFILE = {
    "name": "Test User",
    "email": "test@example.com",
    "phone": "+1000000000",
    "location": "Remote",
    "years_experience": 3,
    "skills": ["Python", "React"],
    "frameworks": ["Django"],
    "databases": ["PostgreSQL"],
    "languages": ["Python"],
    "preferred_titles": ["Backend Engineer"],
    "experience": [],
    "education": [],
    "seniority": "mid",
}


@pytest.fixture()
def client():
    return TestClient(create_app())


@pytest.fixture(autouse=True)
def _clean_caches():
    cache.refresh()
    cache.reset_cv_profile_cache()
    materials.reset_registry()
    yield
    cache.refresh()
    cache.reset_cv_profile_cache()
    materials.reset_registry()


class TestResolveJob:
    def test_sheet_row(self, monkeypatch):
        rows = [BASE_HEADER, ["Backend Dev", "Acme", "", "Python", "",
                "https://acme.com/j/1", "APIs", "", "Arbeitnow",
                "", "", "", "NEW", FP_SHEET]]
        tabs = {"ALL JOBS": rows, "TOP MATCHES": [BASE_HEADER],
                "GOOD MATCHES": [BASE_HEADER]}
        monkeypatch.setattr(
            cache, "_read_tab_values", lambda tab: [list(r) for r in tabs[tab]])
        monkeypatch.setattr(cache, "_load_enrichment_map", lambda force=False: {})
        cache.refresh()
        job = materials.resolve_job(FP_SHEET)
        assert job is not None
        assert job["job_title"] == "Backend Dev"
        assert job["tab"] == "ALL JOBS"

    def test_snapshot_row_md5(self, monkeypatch, tmp_path):
        from tools.deduplicator import job_fingerprint

        monkeypatch.setattr(cache, "_read_tab_values", lambda tab: [])
        monkeypatch.setattr(cache, "_load_enrichment_map", lambda force=False: {})
        # Offline mode: snapshot fallback only fires while Sheets unwired.
        monkeypatch.setattr(cache, "sheets_configured", lambda: False)
        job = {"job_title": "Backend Dev", "company": "Acme",
               "apply_url": "https://acme.com/j/9", "source": "Arbeitnow",
               "summary": "APIs"}
        payload = {"jobs": [job]}
        import json
        (tmp_path / "scraped_jobs.json").write_text(
            json.dumps(payload), encoding="utf-8")
        monkeypatch.setattr(cache, "PROJECT_ROOT", tmp_path)
        cache.refresh()
        expected_fp = job_fingerprint(job)
        found = cache.get_job(expected_fp)
        assert found is not None
        assert found["job_title"] == "Backend Dev"
        resolved = materials.resolve_job(expected_fp)
        assert resolved is not None
        assert resolved["job_fingerprint"] == expected_fp

    def test_unknown_returns_none(self, monkeypatch):
        monkeypatch.setattr(cache, "_read_tab_values", lambda tab: [])
        monkeypatch.setattr(cache, "_local_snapshot_rows", lambda: [])
        monkeypatch.setattr(cache, "_load_enrichment_map", lambda force=False: {})
        cache.refresh()
        assert materials.resolve_job("does-not-exist") is None


class TestCvProfile:
    def test_happy_path(self, client, monkeypatch):
        monkeypatch.setattr(cache, "get_cv_profile", lambda force=False: dict(FAKE_PROFILE))
        r = client.get("/api/cv/profile")
        assert r.status_code == 200
        body = r.json()
        assert body["name"] == "Test User"
        assert body["skills"] == ["Python", "React"]

    def test_missing_returns_501(self, client, monkeypatch):
        monkeypatch.setattr(cache, "get_cv_profile", lambda force=False: None)
        r = client.get("/api/cv/profile")
        assert r.status_code == 501
        assert "cache" in r.json()["detail"].lower()

    def test_cheap_loader_never_triggers_llm(self, monkeypatch, tmp_path):
        import tools.cv_parser as parser

        cv = tmp_path / "my_cv.pdf"
        cv.write_bytes(b"%PDF-1.4 fake cv")
        monkeypatch.setenv("CV_PATH", str(cv))
        cache.reset_cv_profile_cache()
        # No disk cache exists for this fresh file -> must return None,
        # and must never call the heavy parse_cv (LLM) path.
        def _boom(*a, **k):
            raise AssertionError("heavy parse_cv must not run per request")
        monkeypatch.setattr(parser, "parse_cv", _boom)
        assert cache.get_cv_profile(force=True) is None


class TestPutCvProfile:
    """B6 — PUT /api/cv/profile (previously zero coverage).

    Route-level tests mock the merge and pin the HTTP contract; cache-level
    tests run the REAL `cache.save_cv_profile` merge semantics (whitelist,
    coercion, partial merge) because that is where "never 500 on bad input"
    actually lives.
    """

    def test_happy_put_echoes_the_merged_profile(self, client, monkeypatch):
        captured = {}
        merged_out = {"name": "Studio Edit", "email": "edit@example.com",
                      "skills": ["Python", "FastAPI"]}

        def fake_save(patch):
            captured.update(patch)
            return dict(merged_out)

        monkeypatch.setattr(cache, "save_cv_profile", fake_save)
        r = client.put("/api/cv/profile", json={
            "name": "Studio Edit", "email": "edit@example.com",
            "not_a_real_field": {"nested": True},
        })
        assert r.status_code == 200
        body = r.json()
        assert body["name"] == "Studio Edit"
        assert body["skills"] == ["Python", "FastAPI"]
        # The route forwards the SET fields (exclude_unset), extras included;
        # the whitelist inside save_cv_profile is what ignores the unknowns.
        assert captured["email"] == "edit@example.com"
        assert captured["not_a_real_field"] == {"nested": True}

    def test_empty_body_sets_nothing(self, client, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            cache, "save_cv_profile", lambda patch: (captured.update(patch), dict(FAKE_PROFILE))[1])
        r = client.put("/api/cv/profile", json={})
        assert r.status_code == 200
        assert captured == {}

    def test_501_when_no_cache_anchor_exists(self, client, monkeypatch):
        monkeypatch.setattr(cache, "save_cv_profile", lambda patch: None)
        r = client.put("/api/cv/profile", json={"name": "X"})
        assert r.status_code == 501
        assert "cache" in r.json()["detail"].lower()

    def test_bad_declared_type_is_422_never_500(self, client):
        r = client.put("/api/cv/profile", json={"phone": {"nested": True}})
        assert 400 <= r.status_code < 500
        assert r.status_code != 500

    def test_unknown_field_types_do_not_500(self, client, monkeypatch):
        # Extra keys are allowed by the schema; the whitelist then ignores
        # them — the route must survive garbage shapes from future UI fields.
        monkeypatch.setattr(cache, "save_cv_profile", lambda patch: dict(FAKE_PROFILE))
        r = client.put("/api/cv/profile", json={
            "preferred_titles": "not a list", "custom_metric": {"x": "y"}})
        assert r.status_code == 200

    # --- real merge semantics (persistence captured, no disk side effects) --
    @pytest.fixture()
    def anchored_profile(self, monkeypatch, tmp_path):
        import tools.cv_parser as parser
        cv = tmp_path / "my_cv.pdf"
        cv.write_bytes(b"%PDF-1.4 fake cv")
        monkeypatch.setenv("CV_PATH", str(cv))
        cache.reset_cv_profile_cache()
        saved = {}

        monkeypatch.setattr(parser, "_load_cached_profile", lambda path: dict(FAKE_PROFILE))
        monkeypatch.setattr(parser, "_save_cached_profile",
                            lambda path, profile: saved.setdefault("profile", dict(profile)))
        yield saved
        cache.reset_cv_profile_cache()

    def test_partial_merge_preserves_untouched_fields(self, anchored_profile, client):
        r = client.put("/api/cv/profile", json={"email": "new@example.com"})
        assert r.status_code == 200
        saved = anchored_profile["profile"]
        assert saved["email"] == "new@example.com"
        assert saved["name"] == "Test User"          # untouched
        assert saved["skills"] == ["Python", "React"]  # untouched

    def test_skills_comma_string_is_coerced_never_500(self, anchored_profile, client):
        # The route-level coercion guarantee: skills arrive from the UI as one
        # comma-separated string and _coerce_skill_list normalizes them before
        # the cache merge. (A wrong type on a declared str field like `phone`
        # is a 422 — asserted above — never a 500.)
        r = client.put("/api/cv/profile", json={"skills": "Python , Django\n FastAPI"})
        assert r.status_code == 200
        saved = anchored_profile["profile"]
        assert saved["skills"] == ["Python", "Django", "FastAPI"]

    def test_none_clears_and_empty_skills_list_wins(self, anchored_profile, client):
        r = client.put("/api/cv/profile", json={"linkedin": None, "skills": None})
        assert r.status_code == 200
        saved = anchored_profile["profile"]
        assert saved["linkedin"] == ""
        assert saved["skills"] == []

    def test_unknown_field_is_whitelisted_out(self, anchored_profile, client):
        r = client.put("/api/cv/profile", json={"totally_unknown": "leak?"})
        assert r.status_code == 200
        saved = anchored_profile["profile"]
        assert "totally_unknown" not in saved

    def test_name_and_full_name_stay_in_sync(self, anchored_profile, client):
        r = client.put("/api/cv/profile", json={"full_name": "Renamed via Studio"})
        assert r.status_code == 200
        saved = anchored_profile["profile"]
        assert saved["full_name"] == "Renamed via Studio"
        assert saved["name"] == "Renamed via Studio"

    def test_put_never_triggers_llm_parsing(self, anchored_profile, client, monkeypatch):
        import tools.cv_parser as parser

        def _boom(*a, **k):
            raise AssertionError("PUT must not parse the CV or call any LLM")
        monkeypatch.setattr(parser, "parse_cv", _boom)
        r = client.put("/api/cv/profile", json={"name": "No-parse check"})
        assert r.status_code == 200


class TestCvVariants:
    def test_happy_path(self, client, monkeypatch):
        rows = [{"name": "cv_backend.pdf", "tags": ["backend", "python"]},
                {"name": "cv_fullstack.pdf", "tags": ["fullstack"]}]
        monkeypatch.setattr(cache, "list_cv_variants", lambda: list(rows))
        r = client.get("/api/cv/variants")
        assert r.status_code == 200
        body = r.json()
        assert len(body) == 2
        assert body[0]["name"] == "cv_backend.pdf"
        assert "backend" in body[0]["tags"]

    def test_missing_dir_returns_empty(self, client, monkeypatch, tmp_path):
        # Point CV_DIR at an empty temp dir and clear single-file fallback
        # so discovery honestly finds nothing (never 500).
        monkeypatch.setenv("CV_DIR", str(tmp_path / "nope-missing"))
        monkeypatch.setenv("CV_PATH", str(tmp_path / "also-missing.pdf"))
        r = client.get("/api/cv/variants")
        assert r.status_code == 200
        assert r.json() == []

    def test_real_library_lists_dir_safely(self, monkeypatch, tmp_path):
        cvs = tmp_path / "cvs"
        cvs.mkdir()
        (cvs / "cv_backend_python.pdf").write_bytes(b"%PDF fake")
        (cvs / "notes.txt").write_text("ignore me", encoding="utf-8")
        monkeypatch.setenv("CV_DIR", str(cvs))
        monkeypatch.delenv("CV_PATH", raising=False)
        rows = cache.list_cv_variants()
        assert rows == [{"name": "cv_backend_python.pdf",
                         "tags": ["backend", "python"]}]


class TestHygiene:
    def test_no_heavy_imports(self, client, monkeypatch):
        monkeypatch.setattr(cache, "get_cv_profile", lambda force=False: dict(FAKE_PROFILE))
        monkeypatch.setattr(cache, "list_cv_variants", lambda: [])
        client.get("/api/cv/profile")
        client.get("/api/cv/variants")
        assert "agents.curator" not in sys.modules
        assert "main" not in sys.modules
