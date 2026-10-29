"""CV upload ingest tests — api/cv_store.py + POST /api/cv/upload.

Isolated (no live Sheets, no LLM, no real PDF engines, no repo-state writes):
  · text extraction is faked via tools.cv_parser.extract_cv_text
  · the profile-cache path is redirected to a temp dir (no cache/ pollution)
  · CV_DIR points at a temp dir; CVPath/my_cv.pdf is untouched

Covers the honest-outcome contract of ingest_cv_upload:
  happy PDF with domain tags · DOCX happy · dedup (identical bytes -> identical
  stored name) · 415 unsupported extension · 415 magic mismatch (nothing
  stored, no .part leftovers) · 413 empty + oversize · 422 unreadable (file
  deleted, nothing registered) · fresh-cache probe (reports an existing fresh
  profile, never parses with the LLM) · router error mapping + endpoint
  roundtrip + live CVLibrary listing · no-heavy-imports guard.
"""
import hashlib
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient

import api.cv_store as cv_store
import tools.cv_parser as cv_parser
from api.cv_store import CvUploadError, ingest_cv_upload, max_upload_bytes
from api.app import create_app

PDF_MAGIC = b"%PDF-1.4\n"
DOCX_MAGIC = b"PK\x03\x04"

FAKE_PROFILE = {
    "name": "Test User",
    "email": "test@example.com",
    "skills": ["Python", "FastAPI"],
    "experience": [{"title": "Dev", "company": "Acme"}],
}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Temp CV_DIR + redirected profile-cache root for every test.

    Mirrors the parser's real cache identity (md5(file)[:16]) so the probe
    behavior under test is the production behavior, just rooted in tmp.
    """
    monkeypatch.setenv("CV_DIR", str(tmp_path))
    cache_dir = tmp_path / "parser_cache"
    cache_dir.mkdir()
    monkeypatch.setattr(
        cv_parser, "_get_cache_path",
        lambda cv_path: cache_dir
        / f"cv_profile_{hashlib.md5(open(cv_path, 'rb').read()).hexdigest()[:16]}.json",
    )
    yield tmp_path


@pytest.fixture()
def readable(monkeypatch):
    monkeypatch.setattr(cv_parser, "extract_cv_text", lambda p: "SENIOR BACKEND CV text")


@pytest.fixture()
def unreadable(monkeypatch):
    monkeypatch.setattr(cv_parser, "extract_cv_text", lambda p: "")


class TestMaxUploadBytes:
    def test_default_is_10mb(self, monkeypatch):
        monkeypatch.delenv("CV_UPLOAD_MAX_MB", raising=False)
        assert max_upload_bytes() == 10 * 1024 * 1024

    def test_env_value_is_used(self, monkeypatch):
        monkeypatch.setenv("CV_UPLOAD_MAX_MB", "3")
        assert max_upload_bytes() == 3 * 1024 * 1024

    def test_clamped_into_1_50(self, monkeypatch):
        monkeypatch.setenv("CV_UPLOAD_MAX_MB", "0")
        assert max_upload_bytes() == 1024 * 1024
        monkeypatch.setenv("CV_UPLOAD_MAX_MB", "999")
        assert max_upload_bytes() == 50 * 1024 * 1024

    def test_garbage_env_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("CV_UPLOAD_MAX_MB", "ten")
        assert max_upload_bytes() == 10 * 1024 * 1024


class TestIngestOffline:
    def test_pdf_happy_with_domain_tags(self, readable):
        data = PDF_MAGIC + b"\x12\x00" * 32
        out = ingest_cv_upload("Mubashir-CV-backend-2024.pdf", data)
        stored = cv_store.cv_dir_path() / out["stored_name"]
        assert out["stored_name"].endswith(".pdf")
        assert Path(out["stored_name"]).stem.endswith(
            hashlib.md5(data).hexdigest()[:8]
        )
        assert out["tags"] == ["backend"]
        assert out["size_bytes"] == len(data)
        assert stored.read_bytes() == data
        assert out["profile_cached"] is False
        assert out["cached_profile"] is None
        assert "next pipeline run" in out["message"]

    def test_untagged_name_counts_as_general(self, readable):
        out = ingest_cv_upload("my_cv.pdf", PDF_MAGIC + b"x")
        assert out["tags"] == ["general"]

    def test_docx_happy(self, readable):
        data = DOCX_MAGIC + b"\x00" * 16
        out = ingest_cv_upload("cv devops.docx", data)
        assert out["stored_name"].endswith(".docx")
        assert out["tags"] == ["devops"]
        assert (cv_store.cv_dir_path() / out["stored_name"]).read_bytes() == data

    def test_tags_match_the_library_extractor(self, readable):
        # The saved filename must yield the same tags when CVLibrary discovers
        # it later — registration == filename.
        from tools.cv_library import _extract_domain_tags

        out = ingest_cv_upload("cv_backend_python.pdf", PDF_MAGIC + b"x")
        assert out["tags"] == _extract_domain_tags(out["stored_name"])
        assert out["tags"] == ["backend", "python"]

    def test_dedup_identical_bytes_get_one_file(self, readable):
        data = PDF_MAGIC + b"same-content"
        a = ingest_cv_upload("cv_backend.pdf", data)
        b = ingest_cv_upload("cv_backend.pdf", data)
        assert a["stored_name"] == b["stored_name"]
        files = [p.name for p in cv_store.cv_dir_path().glob("*.pdf")]
        assert files == [a["stored_name"]]

    def test_unsupported_extension_is_415(self):
        with pytest.raises(CvUploadError) as ei:
            ingest_cv_upload("notes.rtf", b"plain text")
        assert ei.value.status_code == 415

    def test_magic_mismatch_is_415_and_stores_nothing(self, readable):
        with pytest.raises(CvUploadError) as ei:
            ingest_cv_upload("fake.pdf", b"JUNK-FILE-NOT-A-PDF")
        assert ei.value.status_code == 415
        assert list(cv_store.cv_dir_path().glob("cv_*")) == []
        assert list(cv_store.cv_dir_path().glob("*.part")) == []

    def test_empty_body_is_413(self, monkeypatch, readable):
        monkeypatch.setattr(cv_store, "max_upload_bytes", lambda: 1024)
        with pytest.raises(CvUploadError) as ei:
            ingest_cv_upload("big.pdf", b"")
        assert ei.value.status_code == 413

    def test_oversize_body_is_413(self, monkeypatch, readable):
        monkeypatch.setattr(cv_store, "max_upload_bytes", lambda: 16)
        with pytest.raises(CvUploadError) as ei:
            ingest_cv_upload("big.pdf", PDF_MAGIC + b"x" * 16)
        assert ei.value.status_code == 413

    def test_unreadable_file_is_rejected_and_deleted(self, unreadable):
        data = PDF_MAGIC + b"\x00" * 32
        with pytest.raises(CvUploadError) as ei:
            ingest_cv_upload("cv_backend.pdf", data)
        assert ei.value.status_code == 422
        assert list(cv_store.cv_dir_path().glob("cv_*")) == []
        assert list(cv_store.cv_dir_path().glob("*.part")) == []

    def test_probe_never_calls_the_llm_parser(self, readable, monkeypatch):
        def _boom(*a, **k):
            raise AssertionError("fresh-cache probe must not call parse_cv")

        monkeypatch.setattr(cv_parser, "parse_cv", _boom)
        out = ingest_cv_upload("cv_python.pdf", PDF_MAGIC + b"\x00" * 32)
        assert out["profile_cached"] is False


class TestFreshCacheProbe:
    def _reingest_with_cached_profile(self, monkeypatch, data=PDF_MAGIC + b"\x00" * 32,
                                      shell=False, stale=False):
        first = ingest_cv_upload("cv_python.pdf", data)
        cache_path = cv_parser._get_cache_path(str(cv_store.cv_dir_path() / first["stored_name"]))
        import json

        body = {"name": "", "skills": [], "experience": []} if shell else dict(FAKE_PROFILE)
        cache_path.write_text(json.dumps(body), encoding="utf-8")
        if stale:
            past = time.time() - 10 * 86400
            os.utime(cache_path, (past, past))
        return ingest_cv_upload("cv_python.pdf", data)

    def test_fresh_full_profile_is_reported(self, readable, monkeypatch):
        out = self._reingest_with_cached_profile(monkeypatch)
        assert out["profile_cached"] is True
        assert out["cached_profile"]["name"] == "Test User"

    def test_stale_entry_is_not_reposted_as_fresh(self, readable, monkeypatch):
        out = self._reingest_with_cached_profile(monkeypatch, stale=True)
        assert out["profile_cached"] is False

    def test_empty_shell_never_counts_as_a_profile(self, readable, monkeypatch):
        out = self._reingest_with_cached_profile(monkeypatch, shell=True)
        assert out["profile_cached"] is False


class TestUploadEndpoint:
    @pytest.fixture()
    def client(self):
        return TestClient(create_app())

    def test_roundtrip_and_live_variants_listing(self, client, readable):
        data = PDF_MAGIC + b"\x00" * 32
        r = client.post(
            "/api/cv/upload?filename=cv_backend_python.pdf",
            content=data,
            headers={"Content-Type": "application/pdf"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["tags"] == ["backend", "python"]
        assert body["size_bytes"] == len(data)
        assert body["stored_name"].endswith(".pdf")
        assert body["cached_profile"] is None
        # The newly stored file must be discoverable by the real library
        # machinery (CVLibrary scans the dir; profiles stay lazy).
        v = client.get("/api/cv/variants")
        assert v.status_code == 200
        names = [row["name"] for row in v.json()]
        assert body["stored_name"] in names

    def test_router_maps_415(self, client, readable):
        r = client.post(
            "/api/cv/upload?filename=notes.rtf", content=b"plain text"
        )
        assert r.status_code == 415
        assert "pdf" in r.json()["detail"].lower()

    def test_router_maps_422(self, client, unreadable):
        r = client.post(
            "/api/cv/upload?filename=cv_backend.pdf",
            content=PDF_MAGIC + b"\x00" * 32,
        )
        assert r.status_code == 422
        assert "not registered" in r.json()["detail"].lower()

    def test_missing_filename_is_422(self, client, readable):
        r = client.post("/api/cv/upload", content=PDF_MAGIC + b"x")
        assert r.status_code == 422  # FastAPI's missing-required-query response

    def test_ingest_stays_off_the_heavy_pipeline(self, readable, monkeypatch):
        # Delta-based, so it holds no matter which other test files ran
        # before this one: only modules THIS ingest pulls in count.
        before = set(sys.modules)
        ingest_cv_upload("cv_python.pdf", PDF_MAGIC + b"\x00" * 32)
        new_heavy = sorted(
            m for m in set(sys.modules) - before
            if m == "crewai" or m.startswith(("crewai.", "agents.", "main."))
        )
        assert new_heavy == [], f"upload pulled heavy modules: {new_heavy}"
