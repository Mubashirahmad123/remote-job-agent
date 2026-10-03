"""Stage 0: the three-state kill switch and the dry-run rehearsal.

The property these tests defend is narrow and absolute: **a dry run must
never click.** Everything else here supports that one claim — that the
rehearsal reaches the same gates a real submit reaches, proves the submit
control exists, and then stops, without consuming the intent, taking the
claim, or counting against the daily cap.

Two of these are source-level guards rather than behavioural assertions.
That is deliberate: "the click is unreachable in dry run" and "no state is
mutated before the dry-run return" are *ordering* properties, and ordering
is exactly what a later refactor silently breaks while every behavioural
test keeps passing.
"""

import inspect

import pytest
from fastapi.testclient import TestClient

from api import apply as apply_service
from api import safety
from api.app import create_app

from tests.test_api_apply import (  # reuse the submit scaffolding
    FP_SUBMIT,
    GREENHOUSE_SUBMIT_JOB,
    _apply_auth,
    _issue_intent,
    _seed_greenhouse_submit,
    _submit_body,
)


@pytest.fixture()
def client():
    return TestClient(create_app())


# --------------------------------------------------------------------------
# Switch resolution
# --------------------------------------------------------------------------


class TestSwitchResolution:
    def test_disarmed_by_default(self):
        assert safety.SUBMIT_ENABLED is False
        assert safety.SUBMIT_DRY_RUN is False
        assert safety.submit_enabled() is False
        assert safety.submit_mode() == "disarmed"

    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
    def test_env_can_arm_for_one_process(self, monkeypatch, value):
        monkeypatch.setenv("SUBMIT_ENABLED", value)
        assert safety.submit_enabled() is True
        assert safety.submit_mode() == "armed"

    @pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "maybe", " "])
    def test_non_affirmative_env_stays_closed(self, monkeypatch, value):
        monkeypatch.setenv("SUBMIT_ENABLED", value)
        assert safety.submit_enabled() is False

    def test_dry_run_alone_never_opens_the_path(self, monkeypatch):
        """SUBMIT_DRY_RUN is a modifier, not a second way in."""
        monkeypatch.setenv("SUBMIT_DRY_RUN", "true")
        assert safety.submit_enabled() is False
        assert safety.submit_mode() == "disarmed"

    def test_dry_run_mode_requires_both(self, monkeypatch):
        monkeypatch.setenv("SUBMIT_ENABLED", "true")
        monkeypatch.setenv("SUBMIT_DRY_RUN", "true")
        assert safety.submit_mode() == "dry_run"

    def test_conftest_scrubs_inherited_arming(self):
        """A developer's armed .env must not leak into the suite."""
        import os

        assert os.getenv("SUBMIT_ENABLED") is None
        assert os.getenv("SUBMIT_DRY_RUN") is None


class TestRoutesStillFailClosed:
    def test_submit_403_when_disarmed_even_with_dry_run_env(self, client, monkeypatch):
        monkeypatch.setenv("APPLY_API_TOKEN", "test-apply-secret")
        monkeypatch.setenv("SUBMIT_DRY_RUN", "true")
        response = client.post(
            f"/api/apply/{FP_SUBMIT}/submit",
            json={"confirm": True},
            headers=_apply_auth(),
        )
        assert response.status_code == 403

    def test_intent_403_when_disarmed_even_with_dry_run_env(self, client, monkeypatch):
        monkeypatch.setenv("APPLY_API_TOKEN", "test-apply-secret")
        monkeypatch.setenv("SUBMIT_DRY_RUN", "true")
        response = client.post(
            f"/api/apply/{FP_SUBMIT}/intent",
            json={"mode": "review"},
            headers=_apply_auth(),
        )
        assert response.status_code == 403


# --------------------------------------------------------------------------
# The rehearsal itself
# --------------------------------------------------------------------------


class _ClickRecorder:
    """Fails the test loudly if a dry run ever reaches the submit click."""

    def __init__(self):
        self.clicks = 0

    def click(self, **_kwargs):
        self.clicks += 1


def _fake_playwright(monkeypatch, recorder, *, with_recaptcha=False):
    """Install a Playwright double for the submit path only."""
    import agents.auto_applier as aa

    class _Button:
        def __init__(self):
            self._recorder = recorder

        def count(self):
            return 1

        def click(self, **kwargs):
            self._recorder.click(**kwargs)

    class _Body:
        def inner_text(self):
            return "Thanks for applying"

        def is_visible(self):
            return True

    class _Locator:
        def __init__(self, selector):
            self.selector = selector

        @property
        def first(self):
            return _Button()

        def count(self):
            if "recaptcha" in self.selector:
                return 1 if with_recaptcha else 0
            return 0

        def inner_text(self):
            return "Thanks for applying"

    class _Page:
        url = "https://job-boards.greenhouse.io/example/confirmation/received"

        def locator(self, selector):
            if "submit" in selector:
                class _Wrap:
                    first = _Button()
                return _Wrap()
            if selector == "body":
                return _Body()
            return _Locator(selector)

        def wait_for_url(self, *_args, **_kwargs):
            return None

        def screenshot(self, **_kwargs):
            return None

        def content(self):
            return "<html><body>Thanks for applying</body></html>"

    class _Context:
        class tracing:
            @staticmethod
            def start(**_kwargs):
                pass

            @staticmethod
            def stop(**_kwargs):
                pass

        def new_page(self, **_kwargs):
            return _Page()

        def close(self):
            pass

    class _Browser:
        def new_context(self, **_kwargs):
            return _Context()

        def new_page(self, **_kwargs):
            return _Page()

        def close(self):
            pass

    class _Chromium:
        def launch(self, **_kwargs):
            return _Browser()

    class _Pw:
        chromium = _Chromium()

    class _Ctx:
        def __enter__(self):
            return _Pw()

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(aa, "_get_playwright", lambda: (lambda: _Ctx()))
    monkeypatch.setattr(
        aa,
        "_fill_greenhouse_form",
        lambda page, url, resume, cover, profile: {
            "status": "filled_ready",
            "screenshot_path": "screenshots/fake.png",
            "field_verification": "verified",
            "profile_fields_verified": ["first_name", "last_name", "email"],
            "resume_attached": True,
            "cover_letter_pasted": True,
            "confirmation_path": "/confirmation/received",
            "confirmation_message": "Thanks for applying",
        },
    )


class TestDryRunNeverClicks:
    def test_runner_stops_before_click(self, monkeypatch, tmp_path):
        recorder = _ClickRecorder()
        _fake_playwright(monkeypatch, recorder)
        monkeypatch.setenv("SUBMIT_ARTIFACT_DIR", str(tmp_path / "runs"))

        artifact = {
            "apply_url": GREENHOUSE_SUBMIT_JOB["apply_url"],
            "resume_path": str(tmp_path / "r.pdf"),
            "cover_letter_text": "cover",
            "confirmation_path": "/confirmation/received",
            "confirmation_message": "Thanks for applying",
            "job_fingerprint": FP_SUBMIT,
        }
        result = apply_service._run_greenhouse_submit(
            artifact, GREENHOUSE_SUBMIT_JOB, dry_run=True
        )

        assert recorder.clicks == 0, "dry run clicked the submit button"
        assert result["clicked"] is False
        assert result["would_click"] is True
        assert result["dry_run"] is True
        assert result["verified"] is False

    def test_armed_run_does_click(self, monkeypatch, tmp_path):
        """The counterpart: without dry run the same fakes DO click.

        Without this, `test_runner_stops_before_click` would still pass if the
        click were broken for unrelated reasons.
        """
        recorder = _ClickRecorder()
        _fake_playwright(monkeypatch, recorder)
        monkeypatch.setenv("SUBMIT_ARTIFACT_DIR", str(tmp_path / "runs"))

        artifact = {
            "apply_url": GREENHOUSE_SUBMIT_JOB["apply_url"],
            "resume_path": str(tmp_path / "r.pdf"),
            "cover_letter_text": "cover",
            "confirmation_path": "/confirmation/received",
            "confirmation_message": "Thanks for applying",
            "job_fingerprint": FP_SUBMIT,
        }
        result = apply_service._run_greenhouse_submit(
            artifact, GREENHOUSE_SUBMIT_JOB, dry_run=False
        )

        assert recorder.clicks == 1
        assert result["clicked"] is True

    def test_bot_protection_is_reported_not_swallowed(self, monkeypatch, tmp_path):
        recorder = _ClickRecorder()
        _fake_playwright(monkeypatch, recorder, with_recaptcha=True)
        monkeypatch.setenv("SUBMIT_ARTIFACT_DIR", str(tmp_path / "runs"))

        artifact = {
            "apply_url": GREENHOUSE_SUBMIT_JOB["apply_url"],
            "resume_path": str(tmp_path / "r.pdf"),
            "cover_letter_text": "cover",
            "confirmation_path": "/confirmation/received",
            "confirmation_message": "Thanks for applying",
            "job_fingerprint": FP_SUBMIT,
        }
        result = apply_service._run_greenhouse_submit(
            artifact, GREENHOUSE_SUBMIT_JOB, dry_run=True
        )
        assert result["bot_protection"]["present"] is True
        assert "recaptcha" in result["bot_protection"]["kinds"]


class TestDryRunOverHttp:
    def test_dry_run_returns_report_and_never_claims(self, client, monkeypatch, tmp_path):
        monkeypatch.setenv("APPLY_API_TOKEN", "test-apply-secret")
        _seed_greenhouse_submit(monkeypatch, tmp_path)
        monkeypatch.setattr("api.safety.SUBMIT_DRY_RUN", True)
        recorder = _ClickRecorder()
        _fake_playwright(monkeypatch, recorder)

        import api.apply_claims as apply_claims

        def _explode(*_args, **_kwargs):
            raise AssertionError("dry run reached claim_first")

        monkeypatch.setattr(apply_claims, "claim_first", _explode)

        intent = _issue_intent(client)
        assert intent.status_code == 200
        token = intent.json()["intent_token"]

        response = client.post(
            f"/api/apply/{FP_SUBMIT}/submit",
            json=_submit_body(token),
            headers=_apply_auth(),
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "dry_run"
        assert payload["status"] != "submitted"
        assert payload["would_click"] is True
        assert payload["verification"] == "none_dry_run"
        assert recorder.clicks == 0

    def test_dry_run_is_repeatable_intent_not_consumed(self, client, monkeypatch, tmp_path):
        """A rehearsal you can only run once is not a rehearsal."""
        monkeypatch.setenv("APPLY_API_TOKEN", "test-apply-secret")
        _seed_greenhouse_submit(monkeypatch, tmp_path)
        monkeypatch.setattr("api.safety.SUBMIT_DRY_RUN", True)
        _fake_playwright(monkeypatch, _ClickRecorder())

        token = _issue_intent(client).json()["intent_token"]
        first = client.post(
            f"/api/apply/{FP_SUBMIT}/submit", json=_submit_body(token), headers=_apply_auth()
        )
        second = client.post(
            f"/api/apply/{FP_SUBMIT}/submit", json=_submit_body(token), headers=_apply_auth()
        )
        assert first.status_code == 200
        assert second.status_code == 200, "the first dry run consumed the intent"
        assert second.json()["status"] == "dry_run"

    def test_dry_run_still_enforces_the_real_gates(self, client, monkeypatch, tmp_path):
        """Rehearsing a submit that a real submit would reject proves nothing."""
        monkeypatch.setenv("APPLY_API_TOKEN", "test-apply-secret")
        _seed_greenhouse_submit(monkeypatch, tmp_path)
        monkeypatch.setattr("api.safety.SUBMIT_DRY_RUN", True)
        _fake_playwright(monkeypatch, _ClickRecorder())

        token = _issue_intent(client).json()["intent_token"]
        wrong_title = client.post(
            f"/api/apply/{FP_SUBMIT}/submit",
            json=_submit_body(token, typed_title="Totally Different Role"),
            headers=_apply_auth(),
        )
        assert wrong_title.status_code == 422


# --------------------------------------------------------------------------
# Ordering guards (mutation-resistant)
# --------------------------------------------------------------------------


class TestOrderingGuards:
    def test_dry_run_return_precedes_the_click(self):
        source = inspect.getsource(apply_service._run_greenhouse_submit)
        assert "if dry_run:" in source
        assert source.index("if dry_run:") < source.index("submit_button.click("), (
            "the dry-run stop must come before the click, or dry run can submit"
        )

    def test_dry_run_branch_precedes_any_state_mutation(self):
        source = inspect.getsource(apply_service.submit_greenhouse)
        assert "submit_dry_run()" in source
        assert source.index("submit_dry_run()") < source.index("claim_first("), (
            "dry run must return before claim_first, or rehearsals burn the "
            "intent and the daily cap"
        )

    def test_kill_switch_is_checked_through_the_helper(self):
        """Direct constant reads would bypass env arming and drift apart."""
        for module in (apply_service, __import__("api.routers.apply", fromlist=["x"])):
            source = inspect.getsource(module)
            assert "safety.SUBMIT_ENABLED" not in source.replace("SUBMIT_ENABLED=False", ""), (
                f"{module.__name__} reads the constant directly instead of submit_enabled()"
            )
