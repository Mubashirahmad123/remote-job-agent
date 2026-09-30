"""Phase 2a fill-only apply tests — isolated (no Sheets, LLM, or browser).

Fakes api.cache.get_job (job resolution) and
agents.auto_applier.generate_apply_package (local package build) so no
Google credentials, LLM calls, or Playwright launches happen.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient

from api import cache
from api.app import create_app

FP_GOOD = "fp-good-001"
FP_DREAM = "fp-dream-002"

GOOD_JOB = {
    "job_fingerprint": FP_GOOD,
    "job_title": "Backend Dev",
    "company": "Acme",
    "apply_url": "https://acme.com/j/1",
    "match_score": 76,
}

DREAM_JOB = {
    "job_fingerprint": FP_DREAM,
    "job_title": "Staff Engineer",
    "company": "DreamCo",
    "apply_url": "https://dream.co/j/9",
    "match_score": 97,
}


@pytest.fixture()
def client():
    return TestClient(create_app())


def _fake_env(monkeypatch, good=True):
    monkeypatch.setattr(cache, "get_job", lambda fp: GOOD_JOB if fp == FP_GOOD else (DREAM_JOB if fp == FP_DREAM else None))
    import agents.auto_applier as aa

    monkeypatch.setattr(aa, "classify_tier", lambda job: "good_fit" if job.get("job_fingerprint") == FP_GOOD else "dream")
    monkeypatch.setattr(aa, "generate_apply_package", lambda job, resume, letter, output_folder="apply_packages": "/tmp/apply_packages/fake-pkg")


class TestApplyFillOnly:
    def test_happy_path(self, client, monkeypatch):
        _fake_env(monkeypatch)
        r = client.post(f"/api/apply/{FP_GOOD}", json={"mode": "review"})
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "filled_ready"
        assert body["mode"] == "review"
        assert body["tier"] == "good_fit"
        assert body["submit_enabled"] is False
        assert body["package_path"]

    def test_default_mode_is_review(self, client, monkeypatch):
        _fake_env(monkeypatch)
        r = client.post(f"/api/apply/{FP_GOOD}", json={})
        assert r.status_code == 200

    def test_unknown_job_404(self, client, monkeypatch):
        _fake_env(monkeypatch)
        assert client.post("/api/apply/nope", json={"mode": "review"}).status_code == 404

    def test_non_review_mode_400(self, client, monkeypatch):
        _fake_env(monkeypatch)
        for bad in ("submit", "auto", "confirm", ""):
            r = client.post(f"/api/apply/{FP_GOOD}", json={"mode": bad})
            assert r.status_code == 400, bad

    def test_dream_tier_422(self, client, monkeypatch):
        _fake_env(monkeypatch)
        r = client.post(f"/api/apply/{FP_DREAM}", json={"mode": "review"})
        assert r.status_code == 422

    def test_submit_unreachable_with_confirm_env(self, client, monkeypatch):
        monkeypatch.setenv("AUTO_APPLY_CONFIRM", "true")
        _fake_env(monkeypatch)
        r = client.post(f"/api/apply/{FP_GOOD}", json={"mode": "review"})
        assert r.status_code == 200
        assert r.json()["status"] == "filled_ready"
        # Even with the env flag, a submit request is still rejected —
        # no status:"submitted" exists anywhere in the response.
        r2 = client.post(f"/api/apply/{FP_GOOD}", json={"mode": "submit"})
        assert r2.status_code == 400

    def test_no_heavy_imports_at_startup(self, client, monkeypatch):
        _fake_env(monkeypatch)
        # Ensure pipeline modules were never imported by the request path
        # beyond the lazy auto_applier import inside the handler.
        for mod in ("agents.curator", "main"):
            sys.modules.pop(mod, None)
        client.post(f"/api/apply/{FP_GOOD}", json={"mode": "review"})
        assert "agents.curator" not in sys.modules
        assert "main" not in sys.modules


class TestBindGuard:
    def test_non_local_without_token_refused(self, monkeypatch):
        import api.app as appmod

        monkeypatch.setenv("API_HOST", "0.0.0.0")
        monkeypatch.delenv("API_TOKEN", raising=False)
        with pytest.raises(RuntimeError):
            appmod.create_app()

    def test_non_local_with_token_allowed(self, monkeypatch):
        import api.app as appmod

        monkeypatch.setenv("API_HOST", "0.0.0.0")
        monkeypatch.setenv("API_TOKEN", "secret")
        app = appmod.create_app()
        assert app is not None
