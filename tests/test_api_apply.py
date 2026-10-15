"""Phase 2a fill-only apply tests â€” isolated (no Sheets, LLM, or browser).

Fakes api.cache.get_job (job resolution) and
agents.auto_applier.generate_apply_package (local package build) so no
Google credentials, LLM calls, or Playwright launches happen.
"""
import sys
import os
from pathlib import Path


class _FakeTracing:
    """Stand-in for Playwright's context.tracing (submit-path instrumentation)."""

    def start(self, **_kwargs):
        pass

    def stop(self, **_kwargs):
        pass


def _fake_context(page_factory):
    """Minimal BrowserContext double: the submit path records video/HAR/trace
    on a context, so the fakes must hand one back instead of a bare page."""

    class _FakeContext:
        tracing = _FakeTracing()

        def new_page(self, **_kwargs):
            return page_factory()

        def close(self):
            pass

    return _FakeContext()


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api import cache as CACHE
from api import apply as apply_service

FP_GOOD = "fp-good-001"
FP_DREAM = "fp-dream-002"
FP_SUBMIT = "fp-gh-submit-003"
FP_LEVER = "fp-lever-submit-004"

GOOD_JOB = {
    "job_fingerprint": FP_GOOD,
    "job_title": "Backend Dev",
    "company": "Acme",
    "apply_url": "https://boards.greenhouse.io/acme/jobs/1",
    "match_score": 76,
}

DREAM_JOB = {
    "job_fingerprint": FP_DREAM,
    "job_title": "Staff Engineer",
    "company": "DreamCo",
    "apply_url": "https://dream.co/j/9",
    "match_score": 97,
}

GREENHOUSE_SUBMIT_JOB = {
    "job_fingerprint": FP_SUBMIT,
    "job_title": "Senior Python Engineer",
    "company": "Greenhouse Demo",
    "apply_url": "https://boards.greenhouse.io/demo/jobs/3",
    "match_score": 86,
}

LEVER_SUBMIT_JOB = {
    **GREENHOUSE_SUBMIT_JOB,
    "job_fingerprint": FP_LEVER,
    "apply_url": "https://jobs.lever.co/demo/role",
}

_AUTH_HEADERS = {"Authorization": "Bearer test-apply-secret"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("API_TOKEN", "test-apply-secret")
    monkeypatch.setenv("APPLY_API_TOKEN", "test-apply-secret")
    monkeypatch.setenv("APPLY_STATE_DB_PATH", str(tmp_path / "apply_state.db"))
    import api.auth as AU
    import api.apply_state as AS
    # monkeypatch.setattr, NOT plain assignment: these two module attributes
    # outlive the test, and a direct `AS.DB_PATH = ...` permanently re-points
    # the apply store (and `AU.db_path`, via the closure below) at a tmp_path
    # pytest deletes at teardown. Every later test that authenticates then
    # blows up in api/auth.py with a ValueError on the vanished directory.
    monkeypatch.setattr(AS, "DB_PATH", Path(tmp_path / "apply_state.db"))
    monkeypatch.setattr(AU, "db_path", lambda: Path(tmp_path / "auth.db"))
    AU.forget_initialized()
    try:
        yield TestClient(create_app())
    finally:
        # Drop the DDL memo for the tmp auth DB too, or the next test inherits
        # an "already initialized" entry pointing at a deleted file.
        AU.forget_initialized()


def _fake_env(monkeypatch, good=True):
    monkeypatch.setattr(CACHE, "get_job", lambda fp: GOOD_JOB if fp == FP_GOOD else (DREAM_JOB if fp == FP_DREAM else None))
    import agents.auto_applier as aa

    monkeypatch.setattr(aa, "classify_tier", lambda job: "good_fit" if job.get("job_fingerprint") == FP_GOOD else "dream")
    monkeypatch.setattr(aa, "generate_apply_package", lambda job, resume, letter, output_folder="apply_packages": "/tmp/apply_packages/fake-pkg")
    monkeypatch.setattr(
        apply_service,
        "_fill_ats_form",
        lambda job, *args, **kwargs: {
            "status": "filled_ready",
            "screenshot_path": "screenshots/fake.png",
            "error": None,
            "field_verification": "verified",
            "profile_fields_verified": ["first_name", "last_name", "email"],
        },
    )
    monkeypatch.setattr(
        apply_service,
        "_prepare_submit_materials",
        lambda job: {"resume_path": "/tmp/fake-resume.pdf", "cover_letter_text": "Fake cover letter text for review tests."},
    )
    import api.apply_state as apply_state

    monkeypatch.setattr(apply_state, "save_review_artifact", lambda artifact: None)


def _seed_greenhouse_submit(monkeypatch, tmp_path, job=GREENHOUSE_SUBMIT_JOB):
    import api.apply_state as apply_state
    import agents.auto_applier as aa

    monkeypatch.setattr(apply_state, "DB_PATH", tmp_path / "apply-submit.sqlite")
    monkeypatch.setattr("api.safety.SUBMIT_ENABLED", True)
    import api.cache as CACHE2

    monkeypatch.setattr(CACHE2, "get_job", lambda fp: job if fp == job["job_fingerprint"] else None)
    monkeypatch.setattr(aa, "classify_tier", lambda _job: "good_fit")

    # also set APPLY_API_TOKEN so the intent/submit auth path works in tests
    monkeypatch.setenv("APPLY_API_TOKEN", "test-apply-secret")

    # The test client will send the required Bearer header, so patch only the
    # `require_token` dependency so APPLY_API_TOKEN is still checked where it
    # should be (the intent/submit routes).

    package = tmp_path / "packages" / job["job_fingerprint"]
    package.mkdir(parents=True)
    screenshot = tmp_path / "screenshots" / f"{job['job_fingerprint']}.png"
    screenshot.parent.mkdir(parents=True)
    screenshot.write_bytes(b"png")
    resume = tmp_path / "resumes" / f"{job['job_fingerprint']}.pdf"
    resume.parent.mkdir(parents=True)
    resume.write_bytes(b"%PDF-1.4 fake resume")
    (package / "resume.pdf").write_bytes(b"%PDF-1.4 fake resume")
    (package / "cover_letter.txt").write_text("Seeded cover letter for submit tests.", encoding="utf-8")
    (package / "form_data.json").write_text("{}", encoding="utf-8")
    (package / "index.html").write_text("<html></html>", encoding="utf-8")
    apply_state.save_review_artifact({
        "job_fingerprint": job["job_fingerprint"],
        "platform": "greenhouse",
        "job_title": job["job_title"],
        "apply_url": job["apply_url"],
        "package_path": str(package),
        "screenshot_path": str(screenshot),
        "confirmation_path": "/confirmation/received",
        "confirmation_message": "Thanks for applying",
        "match_ratio": 0.86,
        "fill_status": "filled_ready",
        "created_at": "2026-09-29T12:00:00+00:00",
        "resume_path": str(resume),
        "cover_letter_text": "Seeded cover letter for submit tests.",
        "field_verification": "verified",
        "profile_fields_verified": ["first_name", "last_name", "email"],
    })
    monkeypatch.setattr(
        apply_service,
        "_prepare_submit_materials",
        lambda _job: {"resume_path": str(resume), "cover_letter_text": "Seeded cover letter for submit tests."},
    )
    submit_package = tmp_path / "packages" / f"{job['job_fingerprint']}-submit"

    def _fake_submit_package(_job, resume_path, cover_letter, output_folder="apply_packages"):
        submit_package.mkdir(parents=True, exist_ok=True)
        import shutil

        shutil.copy2(resume_path, submit_package / "resume.pdf")
        (submit_package / "cover_letter.txt").write_text(cover_letter, encoding="utf-8")
        (submit_package / "form_data.json").write_text("{}", encoding="utf-8")
        (submit_package / "index.html").write_text("<html></html>", encoding="utf-8")
        return str(submit_package)

    monkeypatch.setattr(aa, "generate_apply_package", _fake_submit_package)


def _issue_intent(client, fingerprint=FP_SUBMIT):
    return client.post(
        f"/api/apply/{fingerprint}/intent",
        json={"mode": "review"},
        headers=_AUTH_HEADERS,
    )


def _submit_body(intent_token, fingerprint=FP_SUBMIT, **updates):
    body = {
        "confirm": True,
        "job_fingerprint": fingerprint,
        "intent_token": intent_token,
        "typed_title": GREENHOUSE_SUBMIT_JOB["job_title"],
    }
    body.update(updates)
    return body


class TestApplyFillOnly:
    def test_happy_path(self, client, monkeypatch):
        _fake_env(monkeypatch)
        r = client.post(f"/api/apply/{FP_GOOD}", json={"mode": "review"}, headers=_AUTH_HEADERS)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "filled_ready"
        assert body["mode"] == "review"
        assert body["tier"] == "good_fit"
        assert body["submit_enabled"] is False
        assert body["package_path"]
        assert body["screenshot_path"] == "screenshots/fake.png"
        assert body["apply_url"] == GOOD_JOB["apply_url"]

    def test_default_mode_is_review(self, client, monkeypatch):
        _fake_env(monkeypatch)
        r = client.post(f"/api/apply/{FP_GOOD}", json={}, headers=_AUTH_HEADERS)
        assert r.status_code == 200

    def test_unknown_job_404(self, client, monkeypatch):
        _fake_env(monkeypatch)
        assert client.post("/api/apply/nope", json={"mode": "review"}, headers=_AUTH_HEADERS).status_code == 404

    def test_non_review_mode_400(self, client, monkeypatch):
        _fake_env(monkeypatch)
        for bad in ("submit", "auto", "confirm", ""):
            r = client.post(f"/api/apply/{FP_GOOD}", json={"mode": bad}, headers=_AUTH_HEADERS)
            assert r.status_code == 400, bad

    def test_dream_tier_422(self, client, monkeypatch):
        _fake_env(monkeypatch)
        r = client.post(f"/api/apply/{FP_DREAM}", json={"mode": "review"}, headers=_AUTH_HEADERS)
        assert r.status_code == 422

    def test_submit_unreachable_with_confirm_env(self, client, monkeypatch):
        monkeypatch.setenv("AUTO_APPLY_CONFIRM", "true")
        _fake_env(monkeypatch)
        r = client.post(f"/api/apply/{FP_GOOD}", json={"mode": "review"}, headers=_AUTH_HEADERS)
        assert r.status_code == 200
        assert r.json()["status"] == "filled_ready"
        # Even with the env flag, a submit request is still rejected â€”
        # no status:"submitted" exists anywhere in the response.
        r2 = client.post(f"/api/apply/{FP_GOOD}", json={"mode": "submit"}, headers=_AUTH_HEADERS)
        assert r2.status_code == 400

    def test_supported_ats_fill_failure_keeps_review_package(self, client, monkeypatch):
        _fake_env(monkeypatch)
        monkeypatch.setattr(
            apply_service,
            "_fill_ats_form",
            lambda job, *args, **kwargs: {"status": "error", "screenshot_path": None, "error": "form timed out"},
        )

        response = client.post(f"/api/apply/{FP_GOOD}", json={"mode": "review"}, headers=_AUTH_HEADERS)

        assert response.status_code == 200
        assert response.json()["status"] == "error"
        assert response.json()["fill_error"] == "form timed out"
        assert response.json()["package_path"]
        assert response.json()["submit_enabled"] is False

    def test_unsupported_ats_returns_package_only(self, client, monkeypatch):
        _fake_env(monkeypatch)
        unsupported_job = {**GOOD_JOB, "apply_url": "https://acme.example/jobs/1"}
        monkeypatch.setattr(CACHE, "get_job", lambda fp: unsupported_job)
        monkeypatch.setattr(apply_service, "_fill_ats_form", lambda job, *args, **kwargs: None)

        response = client.post(f"/api/apply/{FP_GOOD}", json={"mode": "review"}, headers=_AUTH_HEADERS)

        assert response.status_code == 200
        assert response.json()["status"] == "package_only"
        assert response.json()["screenshot_path"] is None
        assert response.json()["package_path"]

    def test_greenhouse_missing_required_maps_to_needs_review(self, client, monkeypatch):
        _fake_env(monkeypatch)
        monkeypatch.setattr(
            apply_service,
            "_fill_ats_form",
            lambda job, *args, **kwargs: {
                "status": "filled_ready",
                "screenshot_path": "screenshots/fake.png",
                "error": None,
                "field_verification": "missing_required",
                "profile_fields_verified": [],
            },
        )
        response = client.post(f"/api/apply/{FP_GOOD}", json={"mode": "review"}, headers=_AUTH_HEADERS)
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "needs_review"
        assert body["field_verification"] == "missing_required"
        assert body["profile_fields_verified"] == []
        assert "Required applicant fields" in (body["fill_error"] or "")

    def test_greenhouse_verified_fill_stays_filled_ready(self, client, monkeypatch):
        _fake_env(monkeypatch)
        monkeypatch.setattr(
            apply_service,
            "_fill_ats_form",
            lambda job, *args, **kwargs: {
                "status": "filled_ready",
                "screenshot_path": "screenshots/fake.png",
                "error": None,
                "field_verification": "verified",
                "profile_fields_verified": ["first_name", "email"],
            },
        )
        response = client.post(f"/api/apply/{FP_GOOD}", json={"mode": "review"}, headers=_AUTH_HEADERS)
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "filled_ready"
        assert body["profile_fields_verified"] == ["first_name", "email"]

    def test_needs_review_artifact_blocks_intent(self, client, monkeypatch, tmp_path):
        import api.apply_state as apply_state

        _seed_greenhouse_submit(monkeypatch, tmp_path)
        artifact = apply_state.get_review_artifact(FP_SUBMIT)
        artifact["fill_status"] = "needs_review"
        artifact["field_verification"] = "missing_required"
        artifact["profile_fields_verified"] = []
        apply_state.save_review_artifact(artifact)
        r = _issue_intent(client)
        assert r.status_code == 409

    def test_no_heavy_imports_at_startup(self, client, monkeypatch):
        _fake_env(monkeypatch)
        # Ensure pipeline modules were never imported by the request path
        # beyond the lazy auto_applier import inside the handler.
        for mod in ("agents.curator", "main"):
            sys.modules.pop(mod, None)
        client.post(f"/api/apply/{FP_GOOD}", json={"mode": "review"}, headers=_AUTH_HEADERS)
        assert "agents.curator" not in sys.modules
        assert "main" not in sys.modules


class TestGreenhouseIntentAndSubmit:
    def test_apply_routes_require_bearer_even_when_global_token_unset(self, client, monkeypatch):
        monkeypatch.delenv("API_TOKEN", raising=False)
        monkeypatch.delenv("APPLY_API_TOKEN", raising=False)

        intent = client.post(f"/api/apply/{FP_SUBMIT}/intent", json={"mode": "review"})
        submit = client.post(f"/api/apply/{FP_SUBMIT}/submit", json={})
        arbitrary_bearer = client.post(
            f"/api/apply/{FP_SUBMIT}/submit",
            json={},
            headers={"Authorization": "Bearer anything"},
        )

        assert intent.status_code == 401
        assert submit.status_code == 401
        assert arbitrary_bearer.status_code == 401

    def test_apply_token_is_independent_of_global_api_token(self, client, monkeypatch, tmp_path):
        _seed_greenhouse_submit(monkeypatch, tmp_path)
        monkeypatch.delenv("API_TOKEN", raising=False)
        monkeypatch.setenv("APPLY_API_TOKEN", "dedicated-secret")

        response = client.post(
            f"/api/apply/{FP_SUBMIT}/intent",
            json={"mode": "review"},
            headers={"Authorization": "Bearer dedicated-secret"},
        )

        assert response.status_code == 200

    def test_global_api_token_alone_is_401_on_apply_routes(self, client, monkeypatch, tmp_path):
        _seed_greenhouse_submit(monkeypatch, tmp_path)
        monkeypatch.setenv("API_TOKEN", "global-secret")
        monkeypatch.delenv("APPLY_API_TOKEN", raising=False)
        headers = {"Authorization": "Bearer global-secret"}

        intent = client.post(f"/api/apply/{FP_SUBMIT}/intent", json={"mode": "review"}, headers=headers)
        submit = client.post(f"/api/apply/{FP_SUBMIT}/submit", json=_submit_body("any-token"), headers=headers)

        assert intent.status_code == 401
        assert submit.status_code == 401

    def test_intent_requires_existing_package_and_screenshot(self, client, monkeypatch, tmp_path):
        _seed_greenhouse_submit(monkeypatch, tmp_path)
        import api.apply_state as apply_state

        connection = apply_state.connect()
        try:
            connection.execute("DELETE FROM apply_review_artifacts WHERE job_fingerprint = ?", (FP_SUBMIT,))
            connection.commit()
        finally:
            connection.close()
        monkeypatch.setenv("APPLY_API_TOKEN", "test-apply-secret")

        response = _issue_intent(client)

        assert response.status_code == 409

    def test_intent_issues_random_token_and_persists_only_hash(self, client, monkeypatch, tmp_path):
        _seed_greenhouse_submit(monkeypatch, tmp_path)
        monkeypatch.setenv("APPLY_API_TOKEN", "test-apply-secret")

        response = _issue_intent(client)

        assert response.status_code == 200, response.text
        body = response.json()
        assert len(body["intent_token"]) >= 40
        assert "token_hash" not in body
        import api.apply_state as apply_state
        import hashlib

        connection = apply_state.connect()
        try:
            stored = connection.execute(
                "SELECT token_hash, consumed FROM apply_intents WHERE job_fingerprint = ?",
                (FP_SUBMIT,),
            ).fetchone()
        finally:
            connection.close()
        assert stored[0] == hashlib.sha256(body["intent_token"].encode()).hexdigest()
