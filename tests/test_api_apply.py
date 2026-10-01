"""Phase 2a fill-only apply tests — isolated (no Sheets, LLM, or browser).

Fakes api.cache.get_job (job resolution) and
agents.auto_applier.generate_apply_package (local package build) so no
Google credentials, LLM calls, or Playwright launches happen.
"""
import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient

from api import cache
from api import apply as apply_service
from api.app import create_app

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


@pytest.fixture()
def client():
    return TestClient(create_app())


def _fake_env(monkeypatch, good=True):
    monkeypatch.setattr(cache, "get_job", lambda fp: GOOD_JOB if fp == FP_GOOD else (DREAM_JOB if fp == FP_DREAM else None))
    import agents.auto_applier as aa

    monkeypatch.setattr(aa, "classify_tier", lambda job: "good_fit" if job.get("job_fingerprint") == FP_GOOD else "dream")
    monkeypatch.setattr(aa, "generate_apply_package", lambda job, resume, letter, output_folder="apply_packages": "/tmp/apply_packages/fake-pkg")
    monkeypatch.setattr(
        apply_service,
        "_fill_ats_form",
        lambda job, *args, **kwargs: {"status": "filled_ready", "screenshot_path": "screenshots/fake.png", "error": None},
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
    monkeypatch.setattr(cache, "get_job", lambda fp: job if fp == job["job_fingerprint"] else None)
    monkeypatch.setattr(aa, "classify_tier", lambda _job: "good_fit")
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


def _apply_auth():
    return {"Authorization": "Bearer test-apply-secret"}


def _issue_intent(client, fingerprint=FP_SUBMIT):
    return client.post(
        f"/api/apply/{fingerprint}/intent",
        json={"mode": "review"},
        headers=_apply_auth(),
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
        r = client.post(f"/api/apply/{FP_GOOD}", json={"mode": "review"})
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

    def test_supported_ats_fill_failure_keeps_review_package(self, client, monkeypatch):
        _fake_env(monkeypatch)
        monkeypatch.setattr(
            apply_service,
            "_fill_ats_form",
            lambda job, *args, **kwargs: {"status": "error", "screenshot_path": None, "error": "form timed out"},
        )

        response = client.post(f"/api/apply/{FP_GOOD}", json={"mode": "review"})

        assert response.status_code == 200
        assert response.json()["status"] == "error"
        assert response.json()["fill_error"] == "form timed out"
        assert response.json()["package_path"]
        assert response.json()["submit_enabled"] is False

    def test_unsupported_ats_returns_package_only(self, client, monkeypatch):
        _fake_env(monkeypatch)
        unsupported_job = {**GOOD_JOB, "apply_url": "https://acme.example/jobs/1"}
        monkeypatch.setattr(cache, "get_job", lambda fp: unsupported_job)
        monkeypatch.setattr(apply_service, "_fill_ats_form", lambda job, *args, **kwargs: None)

        response = client.post(f"/api/apply/{FP_GOOD}", json={"mode": "review"})

        assert response.status_code == 200
        assert response.json()["status"] == "package_only"
        assert response.json()["screenshot_path"] is None
        assert response.json()["package_path"]

    def test_no_heavy_imports_at_startup(self, client, monkeypatch):
        _fake_env(monkeypatch)
        # Ensure pipeline modules were never imported by the request path
        # beyond the lazy auto_applier import inside the handler.
        for mod in ("agents.curator", "main"):
            sys.modules.pop(mod, None)
        client.post(f"/api/apply/{FP_GOOD}", json={"mode": "review"})
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
        assert stored[1] == 0

    def test_only_one_live_intent_per_fingerprint(self, client, monkeypatch, tmp_path):
        _seed_greenhouse_submit(monkeypatch, tmp_path)
        monkeypatch.setenv("APPLY_API_TOKEN", "test-apply-secret")

        first = _issue_intent(client)
        second = _issue_intent(client)

        assert first.status_code == 200
        assert second.status_code == 409
        assert second.json()["retry_after"] > 0

    def test_intent_missing_confirmation_metadata_fails_closed(self, client, monkeypatch, tmp_path):
        _seed_greenhouse_submit(monkeypatch, tmp_path)
        import api.apply_state as apply_state

        connection = apply_state.connect()
        try:
            connection.execute(
                "UPDATE apply_review_artifacts SET confirmation_path = NULL "
                "WHERE job_fingerprint = ?",
                (FP_SUBMIT,),
            )
            connection.commit()
        finally:
            connection.close()
        monkeypatch.setenv("APPLY_API_TOKEN", "test-apply-secret")

        response = _issue_intent(client)

        assert response.status_code == 502

    def test_intent_reuses_reviewed_materials_without_regeneration(self, client, monkeypatch, tmp_path):
        _seed_greenhouse_submit(monkeypatch, tmp_path)
        monkeypatch.setenv("APPLY_API_TOKEN", "test-apply-secret")
        # Generation and packaging must never run at intent time: the token
        # covers exactly the reviewed artifact, nothing regenerated.
        monkeypatch.setattr(
            apply_service, "_prepare_submit_materials",
            lambda _job: (_ for _ in ()).throw(AssertionError("intent must not regenerate materials")),
        )
        import agents.auto_applier as aa

        monkeypatch.setattr(
            aa, "generate_apply_package",
            lambda *a, **k: (_ for _ in ()).throw(AssertionError("intent must not rebuild the package")),
        )
        import api.apply_state as apply_state

        before = dict(apply_state.get_review_artifact(FP_SUBMIT))

        response = _issue_intent(client)

        assert response.status_code == 200, response.text
        after = dict(apply_state.get_review_artifact(FP_SUBMIT))
        assert after == before
        assert not (tmp_path / "packages" / f"{FP_SUBMIT}-submit").exists()

    def test_intent_missing_materials_fails_closed_without_token(self, client, monkeypatch, tmp_path):
        _seed_greenhouse_submit(monkeypatch, tmp_path)
        monkeypatch.setenv("APPLY_API_TOKEN", "test-apply-secret")
        import api.apply_state as apply_state

        # Reviewed artifact with stale materials (resume gone, cover blank):
        # intent must fail closed without issuing a token.
        Path(str(apply_state.get_review_artifact(FP_SUBMIT)["resume_path"])).unlink()
        connection = apply_state.connect()
        try:
            connection.execute(
                "UPDATE apply_review_artifacts SET cover_letter_text = '' WHERE job_fingerprint = ?",
                (FP_SUBMIT,),
            )
            connection.commit()
        finally:
            connection.close()

        response = _issue_intent(client)

        assert response.status_code == 502
        connection = apply_state.connect()
        try:
            intent = connection.execute(
                "SELECT 1 FROM apply_intents WHERE job_fingerprint = ?", (FP_SUBMIT,)
            ).fetchone()
        finally:
            connection.close()
        assert intent is None

    def test_rejected_duplicate_intent_leaves_artifact_untouched(self, client, monkeypatch, tmp_path):
        _seed_greenhouse_submit(monkeypatch, tmp_path)
        monkeypatch.setenv("APPLY_API_TOKEN", "test-apply-secret")
        monkeypatch.setattr(
            apply_service, "_prepare_submit_materials",
            lambda _job: (_ for _ in ()).throw(AssertionError("rejected intent must not generate")),
        )
        import api.apply_state as apply_state

        first = _issue_intent(client)
        assert first.status_code == 200
        before = dict(apply_state.get_review_artifact(FP_SUBMIT))

        second = _issue_intent(client)

        assert second.status_code == 409
        assert dict(apply_state.get_review_artifact(FP_SUBMIT)) == before

    def test_submit_refill_reuses_intent_materials(self, client, monkeypatch, tmp_path):
        import agents.auto_applier as aa

        _seed_greenhouse_submit(monkeypatch, tmp_path)
        monkeypatch.setenv("APPLY_API_TOKEN", "test-apply-secret")
        intent = _issue_intent(client)
        captured = {}

        def _fake_filler(page, url, resume_path, cover_letter, profile):
            captured["resume_path"] = resume_path
            captured["cover_letter"] = cover_letter
            return {
                "status": "filled_ready",
                "screenshot_path": None,
                "error": None,
                "confirmation_path": "/confirmation/received",
                "confirmation_message": "Thanks for applying",
                "resume_attached": True,
                "resume_verify": "files_present",
                "cover_letter_pasted": True,
                "cover_letter_verify": "verified",
            }

        monkeypatch.setattr(aa, "_fill_greenhouse_form", _fake_filler)
        # Call the real submit runner with a stubbed browser page.
        import api.apply_state as apply_state

        connection = apply_state.connect()
        try:
            artifact = dict(connection.execute(
                "SELECT * FROM apply_review_artifacts WHERE job_fingerprint = ?", (FP_SUBMIT,)
            ).fetchone())
        finally:
            connection.close()

        class _FakeSubmitButton:
            def count(self):
                return 0

        class _FakeSubmitPage:
            def locator(self, selector):
                if "submit" in selector or "submit_app" in selector:
                    return _FakeSubmitButtonWithFirst()
                return _FakeSubmitButton()

        class _FakeSubmitButtonWithFirst:
            first = _FakeSubmitButton()

        class _FakeSubmitBrowser:
            def new_page(self, **kwargs):
                return _FakeSubmitPage()

            def close(self):
                pass

        class _FakeSubmitChromium:
            def launch(self, **kwargs):
                return _FakeSubmitBrowser()

        class _FakeSubmitPlaywright:
            chromium = _FakeSubmitChromium()

        class _FakeSubmitContext:
            def __enter__(self):
                return _FakeSubmitPlaywright()

            def __exit__(self, *_args):
                return False

        monkeypatch.setattr(aa, "_get_playwright", lambda: _FakeSubmitContext)
        outcome = apply_service._run_greenhouse_submit(artifact, GREENHOUSE_SUBMIT_JOB)

        assert captured["resume_path"] == artifact["resume_path"]
        assert captured["cover_letter"] == artifact["cover_letter_text"]
        assert outcome["clicked"] is False  # stubbed page has no submit button

    def test_submit_missing_resume_file_fails_closed_before_browser(self, client, monkeypatch, tmp_path):
        _seed_greenhouse_submit(monkeypatch, tmp_path)
        monkeypatch.setenv("APPLY_API_TOKEN", "test-apply-secret")
        intent = _issue_intent(client)
        assert intent.status_code == 200
        import api.apply_state as apply_state

        connection = apply_state.connect()
        try:
            resume_path = connection.execute(
                "SELECT resume_path FROM apply_review_artifacts WHERE job_fingerprint = ?", (FP_SUBMIT,)
            ).fetchone()[0]
        finally:
            connection.close()
        Path(resume_path).unlink()
        monkeypatch.setattr(
            apply_service, "_run_greenhouse_submit",
            lambda *_args: pytest.fail("browser must not start without materials"),
        )

        response = client.post(
            f"/api/apply/{FP_SUBMIT}/submit",
            json=_submit_body(intent.json()["intent_token"]),
            headers=_apply_auth(),
        )

        assert response.status_code == 410
        connection = apply_state.connect()
        try:
            claim = connection.execute(
                "SELECT 1 FROM apply_claims WHERE job_fingerprint = ?", (FP_SUBMIT,)
            ).fetchone()
        finally:
            connection.close()
        assert claim is None

    def test_real_packager_includes_resume_and_cover_text(self, client, monkeypatch, tmp_path):
        import agents.auto_applier as aa

        real_packager = aa.generate_apply_package
        _seed_greenhouse_submit(monkeypatch, tmp_path)
        out = tmp_path / "real-pkg"
        resume = tmp_path / "resumes" / f"{FP_SUBMIT}.pdf"

        package_path = real_packager(
            GREENHOUSE_SUBMIT_JOB, str(resume), "Real cover text here.", output_folder=str(out)
        )

        assert Path(package_path, "resume.pdf").read_bytes() == resume.read_bytes()
        assert Path(package_path, "cover_letter.txt").read_text() == "Real cover text here."

    def test_lever_intent_and_submit_are_out_of_scope(self, client, monkeypatch, tmp_path):
        _seed_greenhouse_submit(monkeypatch, tmp_path, LEVER_SUBMIT_JOB)
        monkeypatch.setenv("APPLY_API_TOKEN", "test-apply-secret")

        intent = _issue_intent(client, FP_LEVER)
        submit = client.post(
            f"/api/apply/{FP_LEVER}/submit",
            json={"confirm": True, "job_fingerprint": FP_LEVER, "intent_token": "x", "typed_title": "x"},
            headers=_apply_auth(),
        )

        assert intent.status_code == 422
        assert "not available for this ATS" in intent.json()["detail"]
        assert submit.status_code == 422
        assert "not available for this ATS" in submit.json()["detail"]

    def test_lever_submit_never_claims_or_calls_browser(self, client, monkeypatch, tmp_path):
        _seed_greenhouse_submit(monkeypatch, tmp_path, LEVER_SUBMIT_JOB)
        monkeypatch.setenv("APPLY_API_TOKEN", "test-apply-secret")
        monkeypatch.setattr(
            apply_service,
            "_run_greenhouse_submit",
            lambda *_args: pytest.fail("Lever must never reach Greenhouse submit helper"),
        )

        response = client.post(
            f"/api/apply/{FP_LEVER}/submit",
            json={"confirm": True, "job_fingerprint": FP_LEVER, "intent_token": "x", "typed_title": "x"},
            headers=_apply_auth(),
        )

        assert response.status_code == 422
        import api.apply_state as apply_state

        connection = apply_state.connect()
        try:
            claim = connection.execute(
                "SELECT 1 FROM apply_claims WHERE job_fingerprint = ?", (FP_LEVER,)
            ).fetchone()
        finally:
            connection.close()
        assert claim is None

    def test_condition_a_rejects_before_browser_or_claim(self, client, monkeypatch, tmp_path):
        _seed_greenhouse_submit(monkeypatch, tmp_path)
        monkeypatch.setenv("APPLY_API_TOKEN", "test-apply-secret")
        intent = _issue_intent(client)
        monkeypatch.setattr(
            apply_service,
            "_run_greenhouse_submit",
            lambda *_args: pytest.fail("browser must not start before condition gates"),
        )

        response = client.post(
            f"/api/apply/{FP_SUBMIT}/submit",
            json=_submit_body(intent.json()["intent_token"], confirm=1),
            headers=_apply_auth(),
        )

        assert response.status_code == 400

    def test_missing_body_and_malformed_confirmation_are_400(self, client, monkeypatch, tmp_path):
        _seed_greenhouse_submit(monkeypatch, tmp_path)
        monkeypatch.setenv("APPLY_API_TOKEN", "test-apply-secret")

        missing_body = client.post(
            f"/api/apply/{FP_SUBMIT}/submit", headers=_apply_auth()
        )
        malformed_confirm = client.post(
            f"/api/apply/{FP_SUBMIT}/submit",
            json={"confirm": "true", "job_fingerprint": FP_SUBMIT},
            headers=_apply_auth(),
        )

        assert missing_body.status_code == 400
        assert malformed_confirm.status_code == 400

    def test_body_path_fingerprint_mismatch_is_400(self, client, monkeypatch, tmp_path):
        _seed_greenhouse_submit(monkeypatch, tmp_path)
        monkeypatch.setenv("APPLY_API_TOKEN", "test-apply-secret")
        intent = _issue_intent(client)

        response = client.post(
            f"/api/apply/{FP_SUBMIT}/submit",
            json=_submit_body(intent.json()["intent_token"], job_fingerprint="wrong"),
            headers=_apply_auth(),
        )

        assert response.status_code == 400

    def test_non_string_intent_and_title_map_to_gate_statuses(self, client, monkeypatch, tmp_path):
        _seed_greenhouse_submit(monkeypatch, tmp_path)
        monkeypatch.setenv("APPLY_API_TOKEN", "test-apply-secret")

        malformed_intent = client.post(
            f"/api/apply/{FP_SUBMIT}/submit",
            json={"confirm": True, "job_fingerprint": FP_SUBMIT, "intent_token": 123},
            headers=_apply_auth(),
        )
        intent = _issue_intent(client)
        malformed_title = client.post(
            f"/api/apply/{FP_SUBMIT}/submit",
            json=_submit_body(intent.json()["intent_token"], typed_title=123),
            headers=_apply_auth(),
        )

        assert malformed_intent.status_code == 410
        assert malformed_title.status_code == 422

    def test_missing_expired_and_consumed_intents_map_to_410_and_409(self, client, monkeypatch, tmp_path):
        _seed_greenhouse_submit(monkeypatch, tmp_path)
        monkeypatch.setenv("APPLY_API_TOKEN", "test-apply-secret")
        headers = _apply_auth()

        missing = client.post(
            f"/api/apply/{FP_SUBMIT}/submit",
            json=_submit_body("missing-token"), headers=headers,
        )
        issued = _issue_intent(client)
        import api.apply_state as apply_state

        connection = apply_state.connect()
        try:
            connection.execute(
                "UPDATE apply_intents SET expires_at = '2020-01-01T00:00:00+00:00' "
                "WHERE job_fingerprint = ?",
                (FP_SUBMIT,),
            )
            connection.commit()
        finally:
            connection.close()
        expired = client.post(
            f"/api/apply/{FP_SUBMIT}/submit",
            json=_submit_body(issued.json()["intent_token"]), headers=headers,
        )
        fresh = _issue_intent(client)
        connection = apply_state.connect()
        try:
            connection.execute(
                "UPDATE apply_intents SET expires_at = '2999-01-01T00:00:00+00:00', consumed = 1 "
                "WHERE job_fingerprint = ?",
                (FP_SUBMIT,),
            )
            connection.commit()
        finally:
            connection.close()
        consumed = client.post(
            f"/api/apply/{FP_SUBMIT}/submit",
            json=_submit_body(fresh.json()["intent_token"]), headers=headers,
        )

        assert missing.status_code == 410
        assert expired.status_code == 410
        assert consumed.status_code == 409

    def test_condition_c_score_and_typed_title_rejections_are_422(self, client, monkeypatch, tmp_path):
        _seed_greenhouse_submit(monkeypatch, tmp_path)
        monkeypatch.setenv("APPLY_API_TOKEN", "test-apply-secret")
        intent = _issue_intent(client)

        mismatch = client.post(
            f"/api/apply/{FP_SUBMIT}/submit",
            json=_submit_body(intent.json()["intent_token"], typed_title="Staff Architect"),
            headers=_apply_auth(),
        )

        assert mismatch.status_code == 422

    def test_verified_greenhouse_submit_consumes_intent_and_daily_slot(self, client, monkeypatch, tmp_path):
        _seed_greenhouse_submit(monkeypatch, tmp_path)
        monkeypatch.setenv("APPLY_API_TOKEN", "test-apply-secret")
        intent = _issue_intent(client)
        monkeypatch.setattr(
            apply_service,
            "_run_greenhouse_submit",
            lambda artifact, job: {"clicked": True, "verified": True, "error": None},
        )

        response = client.post(
            f"/api/apply/{FP_SUBMIT}/submit",
            json=_submit_body(intent.json()["intent_token"]),
            headers=_apply_auth(),
        )

        assert response.status_code == 200, response.text
        assert response.json()["status"] == "submitted"
        import api.apply_state as apply_state

        connection = apply_state.connect()
        try:
            claim = connection.execute(
                "SELECT status FROM apply_claims WHERE job_fingerprint = ?", (FP_SUBMIT,)
            ).fetchone()
            intent_row = connection.execute(
                "SELECT consumed FROM apply_intents WHERE job_fingerprint = ?", (FP_SUBMIT,)
            ).fetchone()
            cap = connection.execute("SELECT count FROM daily_apply_caps").fetchone()
        finally:
            connection.close()
        assert claim[0] == "submitted"
        assert intent_row[0] == 1
        assert cap[0] == 1

    def test_unverified_submit_is_sticky_and_consumes_daily_cap(self, client, monkeypatch, tmp_path):
        _seed_greenhouse_submit(monkeypatch, tmp_path)
        monkeypatch.setenv("APPLY_API_TOKEN", "test-apply-secret")
        intent = _issue_intent(client)
        monkeypatch.setattr(
            apply_service,
            "_run_greenhouse_submit",
            lambda artifact, job: {"clicked": True, "verified": False, "error": "confirmation mismatch"},
        )

        response = client.post(
            f"/api/apply/{FP_SUBMIT}/submit",
            json=_submit_body(intent.json()["intent_token"]),
            headers=_apply_auth(),
        )

        assert response.status_code == 422
        import api.apply_state as apply_state

        connection = apply_state.connect()
        try:
            status = connection.execute(
                "SELECT status FROM apply_claims WHERE job_fingerprint = ?", (FP_SUBMIT,)
            ).fetchone()[0]
            count = connection.execute("SELECT count FROM daily_apply_caps").fetchone()[0]
        finally:
            connection.close()
        assert status == "submit_unverified"
        assert count == 1

    def test_pre_click_failure_marks_failed_refunded_and_returns_502(self, client, monkeypatch, tmp_path):
        _seed_greenhouse_submit(monkeypatch, tmp_path)
        monkeypatch.setenv("APPLY_API_TOKEN", "test-apply-secret")
        intent = _issue_intent(client)
        monkeypatch.setattr(
            apply_service,
            "_run_greenhouse_submit",
            lambda artifact, job: {"clicked": False, "verified": False, "error": "missing submit control"},
        )

        response = client.post(
            f"/api/apply/{FP_SUBMIT}/submit",
            json=_submit_body(intent.json()["intent_token"]),
            headers=_apply_auth(),
        )

        assert response.status_code == 502
        import api.apply_state as apply_state

        connection = apply_state.connect()
        try:
            status = connection.execute(
                "SELECT status FROM apply_claims WHERE job_fingerprint = ?", (FP_SUBMIT,)
            ).fetchone()[0]
            count = connection.execute("SELECT count FROM daily_apply_caps").fetchone()[0]
        finally:
            connection.close()
        assert status == "failed_refunded"
        assert count == 0

    def test_daily_cap_exhaustion_rolls_back_claim_and_intent_consumption(self, client, monkeypatch, tmp_path):
        _seed_greenhouse_submit(monkeypatch, tmp_path)
        monkeypatch.setenv("APPLY_API_TOKEN", "test-apply-secret")
        intent = _issue_intent(client)
        import agents.auto_applier as aa
        import api.apply_state as apply_state

        monkeypatch.setattr(aa, "AUTO_APPLY_DAILY_CAP", 0)
        response = client.post(
            f"/api/apply/{FP_SUBMIT}/submit",
            json=_submit_body(intent.json()["intent_token"]),
            headers=_apply_auth(),
        )

        assert response.status_code == 409
        assert response.json()["retry_after"] > 0
        connection = apply_state.connect()
        try:
            claim = connection.execute(
                "SELECT 1 FROM apply_claims WHERE job_fingerprint = ?", (FP_SUBMIT,)
            ).fetchone()
            consumed = connection.execute(
                "SELECT consumed FROM apply_intents WHERE job_fingerprint = ?", (FP_SUBMIT,)
            ).fetchone()[0]
        finally:
            connection.close()
        assert claim is None
        assert consumed == 0

    def test_manual_reconciliation_requires_apply_bearer_and_refunds_slot(self, client, monkeypatch, tmp_path):
        _seed_greenhouse_submit(monkeypatch, tmp_path)
        monkeypatch.setenv("APPLY_API_TOKEN", "test-apply-secret")
        import api.apply_state as apply_state
        from api.apply_claims import claim_first, finalize_claim

        connection = apply_state.connect()
        try:
            claim_first(connection, FP_SUBMIT, daily_cap=5, intent_hash="hash")
            finalize_claim(connection, FP_SUBMIT, "submit_unverified")
        finally:
            connection.close()
        monkeypatch.setattr(
            cache,
            "update_tracker_and_get",
            lambda *args: {"job_title": "Senior Python Engineer", "company": "Greenhouse Demo", "status": "rejected"},
        )

        unauthorized = client.patch(
            f"/api/tracker/{FP_SUBMIT}",
            json={"status": "rejected", "reconcile_submit_failure": True},
        )
        authorized = client.patch(
            f"/api/tracker/{FP_SUBMIT}",
            json={"status": "rejected", "reconcile_submit_failure": True},
            headers=_apply_auth(),
        )

        assert unauthorized.status_code == 401
        assert authorized.status_code == 200
        connection = apply_state.connect()
        try:
            status = connection.execute(
                "SELECT status FROM apply_claims WHERE job_fingerprint = ?", (FP_SUBMIT,)
            ).fetchone()[0]
            cap = connection.execute("SELECT count FROM daily_apply_caps").fetchone()[0]
        finally:
            connection.close()
        assert status == "failed_refunded"
        assert cap == 0


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


def test_ats_fill_runner_opens_review_browser_and_closes_after_tab(monkeypatch):
    import agents.auto_applier as auto_applier

    calls = {}

    class FakePage:
        def wait_for_event(self, event_name, timeout):
            calls["wait_event"] = (event_name, timeout)

    class FakeBrowser:
        def new_page(self, **kwargs):
            calls["viewport"] = kwargs["viewport"]
            return FakePage()

        def close(self):
            calls["closed"] = True

    class FakeChromium:
        def launch(self, **kwargs):
            calls["headless"] = kwargs["headless"]
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

    class FakePlaywrightContext:
        def __enter__(self):
            return FakePlaywright()

        def __exit__(self, *_args):
            return False

    def fake_greenhouse_filler(page, url, resume_path, cover_letter, profile):
        calls["fill_args"] = (page, url, resume_path, cover_letter, profile)
        return {"status": "filled_ready", "screenshot_path": "screenshots/fake.png", "error": None}

    monkeypatch.setattr(auto_applier, "detect_ats_platform", lambda _url: "greenhouse")
    monkeypatch.setattr(auto_applier, "_is_container", lambda: False)
    monkeypatch.setattr(auto_applier, "_get_playwright", lambda: FakePlaywrightContext)
    monkeypatch.setattr(auto_applier, "_fill_greenhouse_form", fake_greenhouse_filler)

    result = apply_service._fill_ats_form(GOOD_JOB)

    assert result["status"] == "filled_ready"
    assert result["browser_opened"] is True
    assert calls["headless"] is False
    assert calls["closed"] is True
    assert calls["wait_event"] == ("close", 30 * 60 * 1000)
    assert calls["viewport"] == {"width": 1280, "height": 900}
    assert calls["fill_args"][1:4] == (GOOD_JOB["apply_url"], None, "")


def test_unsupported_ats_does_not_launch_playwright(monkeypatch):
    import agents.auto_applier as auto_applier

    monkeypatch.setattr(auto_applier, "detect_ats_platform", lambda _url: "workday")
    monkeypatch.setattr(
        auto_applier,
        "_get_playwright",
        lambda: pytest.fail("Playwright must not launch for unsupported ATS"),
    )

    assert apply_service._fill_ats_form(
        {**GOOD_JOB, "apply_url": "https://example.wd5.myworkdayjobs.com/job"}
    ) is None


class TestApplyScreenshotRoute:
    def test_fill_review_returns_screenshot_url(self, client, monkeypatch):
        _fake_env(monkeypatch)
        r = client.post(f"/api/apply/{FP_GOOD}", json={"mode": "review"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["screenshot_url"] == f"/api/apply/{FP_GOOD}/screenshot"

    def test_package_only_has_no_screenshot_url(self, client, monkeypatch):
        _fake_env(monkeypatch)
        monkeypatch.setattr(
            apply_service, "_fill_ats_form", lambda job, *args, **kwargs: None,
        )
        r = client.post(f"/api/apply/{FP_GOOD}", json={"mode": "review"})
        assert r.status_code == 200, r.text
        assert r.json()["screenshot_url"] is None

    def test_screenshot_404_without_artifact(self, client):
        r = client.get("/api/apply/missing-fp/screenshot")
        assert r.status_code == 404

    def test_screenshot_200_serves_png(self, client, monkeypatch, tmp_path):
        _seed_greenhouse_submit(monkeypatch, tmp_path)
        r = client.get(f"/api/apply/{FP_SUBMIT}/screenshot")
        assert r.status_code == 200, r.text
        assert r.headers["content-type"].startswith("image/")
        assert r.content == b"png"

    def test_screenshot_404_when_file_gone(self, client, monkeypatch, tmp_path):
        import api.apply_state as apply_state

        _seed_greenhouse_submit(monkeypatch, tmp_path)
        artifact = apply_state.get_review_artifact(FP_SUBMIT)
        Path(str(artifact["screenshot_path"])).unlink()
        r = client.get(f"/api/apply/{FP_SUBMIT}/screenshot")
        assert r.status_code == 404

    def test_screenshot_requires_token_when_set(self, client, monkeypatch, tmp_path):
        _seed_greenhouse_submit(monkeypatch, tmp_path)
        monkeypatch.setenv("API_TOKEN", "secret")
        assert client.get(f"/api/apply/{FP_SUBMIT}/screenshot").status_code == 401
        authed = client.get(
            f"/api/apply/{FP_SUBMIT}/screenshot",
            headers={"Authorization": "Bearer secret"},
        )
        assert authed.status_code == 200


class TestSubmitKillSwitch:
    def test_intent_is_403_when_kill_switch_off(self, client, monkeypatch, tmp_path):
        _seed_greenhouse_submit(monkeypatch, tmp_path)
        monkeypatch.setattr("api.safety.SUBMIT_ENABLED", False)
        monkeypatch.setenv("APPLY_API_TOKEN", "test-apply-secret")
        r = client.post(
            f"/api/apply/{FP_SUBMIT}/intent",
            json={"mode": "review"},
            headers=_apply_auth(),
        )
        assert r.status_code == 403

    def test_submit_is_403_when_kill_switch_off(self, client, monkeypatch, tmp_path):
        _seed_greenhouse_submit(monkeypatch, tmp_path)
        monkeypatch.setattr("api.safety.SUBMIT_ENABLED", False)
        monkeypatch.setenv("APPLY_API_TOKEN", "test-apply-secret")
        r = client.post(
            f"/api/apply/{FP_SUBMIT}/submit",
            json=_submit_body("any-token"),
            headers=_apply_auth(),
        )
        assert r.status_code == 403

    def test_kill_switch_off_marks_no_claim(self, client, monkeypatch, tmp_path):
        import api.apply_state as apply_state

        _seed_greenhouse_submit(monkeypatch, tmp_path)
        monkeypatch.setattr("api.safety.SUBMIT_ENABLED", False)
        monkeypatch.setenv("APPLY_API_TOKEN", "test-apply-secret")
        client.post(
            f"/api/apply/{FP_SUBMIT}/submit",
            json=_submit_body("any-token"),
            headers=_apply_auth(),
        )
        assert apply_state.get_claim_status(FP_SUBMIT) is None


class TestSubmitAttachmentGate:
    def _run_refill(self, monkeypatch, fill_result):
        import agents.auto_applier as aa

        _fake = dict(
            {
                "status": "filled_ready",
                "screenshot_path": None,
                "error": None,
                "confirmation_path": "/confirmation/received",
                "confirmation_message": "Thanks for applying",
            },
            **fill_result,
        )
        monkeypatch.setattr(aa, "_fill_greenhouse_form", lambda *a, **k: _fake)

        class _NoButton:
            def count(self):
                return 0

        class _Page:
            def locator(self, selector):
                class _Wrap:
                    first = _NoButton()

                return _Wrap()

        class _Browser:
            def new_page(self, **kwargs):
                return _Page()

            def close(self):
                pass

        class _Chromium:
            def launch(self, **kwargs):
                return _Browser()

        class _Pw:
            chromium = _Chromium()

        class _Ctx:
            def __enter__(self):
                return _Pw()

            def __exit__(self, *_a):
                return False

        monkeypatch.setattr(aa, "_get_playwright", lambda: _Ctx)
        return apply_service._run_greenhouse_submit(
            {
                "apply_url": "https://boards.greenhouse.io/demo/jobs/3",
                "resume_path": "r.pdf",
                "cover_letter_text": "cover text here",
                "confirmation_path": "/confirmation/received",
                "confirmation_message": "Thanks for applying",
            },
            GREENHOUSE_SUBMIT_JOB,
        )

    def test_refill_without_resume_proof_never_clicks(self, monkeypatch):
        outcome = self._run_refill(
            monkeypatch,
            {
                "field_verification": "verified",
                "profile_fields_verified": ["first_name", "last_name", "email"],
            },
        )
        assert outcome["clicked"] is False
        assert "Resume attachment unverified" in (outcome["error"] or "")

    def test_refill_without_cover_proof_never_clicks(self, monkeypatch):
        outcome = self._run_refill(
            monkeypatch,
            {
                "resume_attached": True,
                "resume_verify": "files_present",
                "field_verification": "verified",
                "profile_fields_verified": ["first_name", "last_name", "email"],
            },
        )
        assert outcome["clicked"] is False
        assert "Cover letter unverified" in (outcome["error"] or "")

    def test_refill_with_both_proofs_passes_gate(self, monkeypatch):
        outcome = self._run_refill(
            monkeypatch,
            {
                "resume_attached": True,
                "resume_verify": "files_present",
                "cover_letter_pasted": True,
                "cover_letter_verify": "verified",
                "field_verification": "verified",
                "profile_fields_verified": ["first_name", "last_name", "email"],
            },
        )
        # No submit button on the stub page, but the attachment gate passed:
        assert outcome["error"] == "Greenhouse submit button was not found"
        assert outcome["clicked"] is False

    def test_refill_field_mismatch_never_clicks(self, monkeypatch):
        outcome = self._run_refill(
            monkeypatch,
            {
                "resume_attached": True,
                "resume_verify": "files_present",
                "cover_letter_pasted": True,
                "cover_letter_verify": "verified",
                "field_verification": "mismatch",
            },
        )
        assert outcome["clicked"] is False
        assert "Field readback unverified" in (outcome["error"] or "")

    def test_refill_field_unavailable_never_clicks(self, monkeypatch):
        outcome = self._run_refill(
            monkeypatch,
            {
                "resume_attached": True,
                "resume_verify": "files_present",
                "cover_letter_pasted": True,
                "cover_letter_verify": "verified",
                "field_verification": "unavailable",
            },
        )
        assert outcome["clicked"] is False
        assert "Field readback unverified" in (outcome["error"] or "")

    def test_refill_field_verified_proceeds_past_gate(self, monkeypatch):
        outcome = self._run_refill(
            monkeypatch,
            {
                "resume_attached": True,
                "resume_verify": "files_present",
                "cover_letter_pasted": True,
                "cover_letter_verify": "verified",
                "field_verification": "verified",
                "profile_fields_verified": ["first_name", "email"],
            },
        )
        # No submit button on the stub page, but the field gate passed:
        assert outcome["error"] == "Greenhouse submit button was not found"
        assert outcome["clicked"] is False

    def test_refill_field_repaired_proceeds_past_gate(self, monkeypatch):
        outcome = self._run_refill(
            monkeypatch,
            {
                "resume_attached": True,
                "resume_verify": "files_present",
                "cover_letter_pasted": True,
                "cover_letter_verify": "verified",
                "field_verification": "repaired",
                "profile_fields_verified": ["first_name", "last_name", "email"],
            },
        )
        # No submit button on the stub page, but the field gate passed:
        assert outcome["error"] == "Greenhouse submit button was not found"
        assert outcome["clicked"] is False

    def test_refill_without_profile_fields_never_clicks(self, monkeypatch):
        outcome = self._run_refill(
            monkeypatch,
            {
                "resume_attached": True,
                "resume_verify": "files_present",
                "cover_letter_pasted": True,
                "cover_letter_verify": "verified",
                "field_verification": "verified",
                "profile_fields_verified": [],
            },
        )
        assert outcome["clicked"] is False
        assert "Applicant profile fields unverified" in (outcome["error"] or "")

    def test_refill_without_email_never_clicks(self, monkeypatch):
        outcome = self._run_refill(
            monkeypatch,
            {
                "resume_attached": True,
                "resume_verify": "files_present",
                "cover_letter_pasted": True,
                "cover_letter_verify": "verified",
                "field_verification": "verified",
                "profile_fields_verified": ["first_name", "last_name"],
            },
        )
        assert outcome["clicked"] is False
        assert "Applicant profile fields unverified" in (outcome["error"] or "")

    def test_refill_without_name_never_clicks(self, monkeypatch):
        outcome = self._run_refill(
            monkeypatch,
            {
                "resume_attached": True,
                "resume_verify": "files_present",
                "cover_letter_pasted": True,
                "cover_letter_verify": "verified",
                "field_verification": "verified",
                "profile_fields_verified": ["email"],
            },
        )
        assert outcome["clicked"] is False
        assert "Applicant profile fields unverified" in (outcome["error"] or "")

    def test_refill_full_name_path_satisfies_name_requirement(self, monkeypatch):
        outcome = self._run_refill(
            monkeypatch,
            {
                "resume_attached": True,
                "resume_verify": "files_present",
                "cover_letter_pasted": True,
                "cover_letter_verify": "verified",
                "field_verification": "verified",
                "profile_fields_verified": ["full_name", "email"],
            },
        )
        # Name via full_name fallback + email passes the profile gate:
        assert outcome["error"] == "Greenhouse submit button was not found"
        assert outcome["clicked"] is False

    def test_refill_missing_required_state_never_clicks(self, monkeypatch):
        outcome = self._run_refill(
            monkeypatch,
            {
                "resume_attached": True,
                "resume_verify": "files_present",
                "cover_letter_pasted": True,
                "cover_letter_verify": "verified",
                "field_verification": "missing_required",
                "profile_fields_verified": [],
            },
        )
        assert outcome["clicked"] is False
        assert "Field readback unverified" in (outcome["error"] or "")
