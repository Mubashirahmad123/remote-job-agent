"""Pre-endpoint 2b tests for fill, verification, and claim primitives."""
import os
import hashlib
import sqlite3
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.auto_applier import (
    _fill_greenhouse_form,
    _fill_lever_form,
    _greenhouse_confirmation_data,
    _safe_score,
    classify_tier,
)
from api.apply_claims import (
    ClaimConflict,
    DailyCapExceeded,
    claim_first,
    initialize_claim_store,
    finalize_claim,
    mark_pre_click_failure,
    reconcile_failed_claim,
)
from api.apply_intents import (
    ActiveIntentConflict,
    IntentConsumed,
    IntentExpired,
    consume_intent,
    create_intent,
    initialize_intent_store,
    validate_intent,
)
from api.apply_verification import (
    verify_greenhouse_confirmation,
    verify_lever_confirmation,
)
from api.app import create_app
from api.safety import SUBMIT_ENABLED
from api.apply_validation import (
    normalize_title,
    validate_confirmation_echo,
    validate_submit_inputs,
)


class FakeLocator:
    def __init__(self, page, selector):
        self.page = page
        self.selector = selector
        self.first = self

    def count(self):
        if self.selector in {
            "a.show-page-apply, a.postings-btn[href]",
            "a.show-page-apply",
        }:
            return int(bool(self.page.apply_href))
        if self.selector == "[role='alert'], .error, .error-message, .application-error":
            return self.page.error_count
        if "custom-question" in self.selector or "application-question" in self.selector or "data-qa*='question'" in self.selector or "[class*='question']" in self.selector:
            return self.page.custom_question_count
        if "submit" in self.selector or ".postings-btn" in self.selector:
            return self.page.submit_count
        if self.selector == "body":
            return 1
        return 1 if self.page.form_fields_present else 0

    def get_attribute(self, name):
        return self.page.apply_href if name == "href" else None

    def fill(self, value):
        self.page.fill_count += 1
        self.page.filled_values[self.selector] = value

    def press_sequentially(self, value):
        self.page.fill_count += 1
        self.page.filled_values[self.selector] = value

    def press(self, _key):
        return None

    def click(self):
        return None

    def evaluate(self, _expr):
        key = self.selector
        if key in self.page.filled_values:
            return self.page.filled_values[key]
        return "" if self.page.form_fields_present else None

    def set_input_files(self, path):
        self.page.fill_count += 1

    def inner_text(self):
        return self.page.body_text

    def all_text_contents(self):
        return self.page.embedded_json

    def is_visible(self):
        return self.page.confirmation_visible

    def click(self):
        self.page.click_count += 1


class FakePage:
    def __init__(
        self,
        *,
        apply_href=None,
        custom_question_count=0,
        submit_count=1,
        form_fields_present=True,
        timeout_selector=False,
        confirmation_visible=False,
        error_count=0,
        embedded_json=None,
        body_text="",
        url="",
    ):
        self.apply_href = apply_href
        self.custom_question_count = custom_question_count
        self.submit_count = submit_count
        self.form_fields_present = form_fields_present
        self.timeout_selector = timeout_selector
        self.confirmation_visible = confirmation_visible
        self.error_count = error_count
        self.embedded_json = embedded_json or []
        self.body_text = body_text
        self.url = url
        self.goto_calls = []
        self.wait_calls = []
        self.fill_count = 0
        self.click_count = 0
        self.filled_values = {}

    def goto(self, url, *, wait_until, timeout):
        self.goto_calls.append((url, wait_until, timeout))
        self.url = url

    def wait_for_selector(self, selector, *, timeout):
        self.wait_calls.append((selector, timeout, self.url))
        if self.timeout_selector:
            raise TimeoutError("form selector timed out")

    def locator(self, selector):
        return FakeLocator(self, selector)

    def screenshot(self, **kwargs):
        return None


PROFILE = {
    "name": "Test Applicant",
    "email": "test@example.invalid",
    "phone": "5550100199",
    "linkedin": "https://example.invalid/profile",
    "portfolio": "https://example.invalid/portfolio",
}


@pytest.mark.parametrize(
    ("custom_questions", "submit_count", "expected"),
    [
        (0, 1, "filled_ready"),
        (1, 1, "custom_questions"),
        (0, 0, "no_submit_button"),
    ],
)
def test_greenhouse_fill_matrix_never_clicks(custom_questions, submit_count, expected):
    page = FakePage(custom_question_count=custom_questions, submit_count=submit_count)

    result = _fill_greenhouse_form(
        page, "https://boards.greenhouse.io/example/jobs/1", None, "", PROFILE
    )

    assert result["status"] == expected
    assert page.goto_calls[0][1] == "domcontentloaded"
    assert page.wait_calls[0][0] == "#application-form, .application-form, form"
    assert page.click_count == 0


def test_greenhouse_form_timeout_never_clicks():
    page = FakePage(timeout_selector=True)

    result = _fill_greenhouse_form(
        page, "https://boards.greenhouse.io/example/jobs/1", None, "", PROFILE
    )

    assert result["status"] == "error"
    assert "timed out" in result["error"]
    assert page.click_count == 0


def test_greenhouse_fill_reports_verified_profile_fields():
    page = FakePage(custom_question_count=0, submit_count=1)

    result = _fill_greenhouse_form(
        page, "https://boards.greenhouse.io/example/jobs/1", None, "", PROFILE
    )

    assert result["status"] == "filled_ready"
    assert result["field_verification"] in {"verified", "repaired"}
    verified = set(result.get("profile_fields_verified") or [])
    assert ("first_name" in verified or "full_name" in verified)
    assert "email" in verified
    assert page.click_count == 0


def test_greenhouse_fill_with_no_profile_fields_is_missing_required():
    page = FakePage(
        custom_question_count=0, submit_count=1, form_fields_present=False
    )

    result = _fill_greenhouse_form(
        page, "https://boards.greenhouse.io/example/jobs/1", None, "", PROFILE
    )

    # Vacuous pass is closed: zero typed fields must not verify.
    assert result["profile_fields_verified"] == []
    assert result["field_verification"] == "missing_required"
    assert page.click_count == 0


@pytest.mark.parametrize(
    ("custom_questions", "submit_count", "expected"),
    [
        (0, 1, "filled_ready"),
        (1, 1, "custom_questions"),
        (0, 0, "no_submit_button"),
    ],
)
def test_lever_fill_matrix_never_clicks(custom_questions, submit_count, expected):
    posting_url = "https://jobs.lever.co/example/role"
    page = FakePage(
        apply_href="/example/role/apply",
        custom_question_count=custom_questions,
        submit_count=submit_count,
    )

    result = _fill_lever_form(page, posting_url, None, "", PROFILE)

    assert result["status"] == expected
    assert [call[0] for call in page.goto_calls] == [
        posting_url,
        "https://jobs.lever.co/example/role/apply",
    ]
    assert all(call[1] == "domcontentloaded" for call in page.goto_calls)
    assert page.wait_calls[0][2].endswith("/apply")
    assert page.click_count == 0


def test_lever_form_timeout_never_clicks():
    page = FakePage(apply_href="/example/role/apply", timeout_selector=True)

    result = _fill_lever_form(
        page, "https://jobs.lever.co/example/role", None, "", PROFILE
    )

    assert result["status"] == "error"
    assert "timed out" in result["error"]
    assert page.click_count == 0


def test_lever_apply_page_resolution_accepts_absolute_anchor_href():
    page = FakePage(apply_href="https://jobs.lever.co/example/role/apply")

    result = _fill_lever_form(
        page, "https://jobs.lever.co/example/role", None, "", PROFILE
    )

    assert result["status"] == "filled_ready"
    assert page.goto_calls[-1][0] == "https://jobs.lever.co/example/role/apply"
    assert page.click_count == 0


def test_lever_apply_page_resolution_rejects_missing_anchor_before_filling():
    page = FakePage(apply_href=None)

    result = _fill_lever_form(
        page, "https://jobs.lever.co/example/role", None, "", PROFILE
    )

    assert result["status"] == "error"
    assert "apply-page link" in result["error"]
    assert page.fill_count == 0
    assert page.click_count == 0


def test_lever_apply_page_resolution_rejects_non_apply_href_before_filling():
    page = FakePage(apply_href="/example/role/other")

    result = _fill_lever_form(
        page, "https://jobs.lever.co/example/role", None, "", PROFILE
    )

    assert result["status"] == "error"
    assert "valid /apply href" in result["error"]
    assert page.fill_count == 0
    assert page.click_count == 0


def test_lever_apply_url_does_not_follow_a_second_apply_link():
    apply_url = "https://jobs.lever.co/example/role/apply"
    page = FakePage(apply_href=None)

    result = _fill_lever_form(page, apply_url, None, "", PROFILE)

    assert result["status"] == "filled_ready"
    assert [call[0] for call in page.goto_calls] == [apply_url]
    assert page.wait_calls[0][2] == apply_url
    assert page.click_count == 0


@pytest.mark.parametrize(
    ("url", "body", "expected"),
    [
        ("https://boards.greenhouse.io/confirmation", "Application received", True),
        ("https://boards.greenhouse.io/confirmation", "Different text", False),
        ("https://boards.greenhouse.io/jobs/1", "Application received", False),
    ],
)
def test_greenhouse_confirmation_requires_path_and_message(url, body, expected):
    page = FakePage(url=url, body_text=body)

    assert verify_greenhouse_confirmation(
        page, confirmation_path="/confirmation", confirmation_message="Application received"
    ) is expected


def test_greenhouse_confirmation_message_match_is_case_sensitive():
    page = FakePage(
        url="https://boards.greenhouse.io/confirmation",
        body_text="application received",
    )

    assert not verify_greenhouse_confirmation(
        page, confirmation_path="/confirmation", confirmation_message="Application received"
    )


def test_greenhouse_confirmation_path_is_an_exact_path_match():
    page = FakePage(
        url="https://boards.greenhouse.io/notconfirmation",
        body_text="Application received",
    )

    assert not verify_greenhouse_confirmation(
        page, confirmation_path="/confirmation", confirmation_message="Application received"
    )


@pytest.mark.parametrize(
    ("visible", "error_count", "expected"),
    [(True, 0, True), (False, 0, False), (True, 1, False)],
)
def test_lever_confirmation_requires_visibility_without_error_dom(
    visible, error_count, expected
):
    page = FakePage(confirmation_visible=visible, error_count=error_count)

    assert verify_lever_confirmation(page) is expected


@pytest.mark.skip(
    reason="Lever submit deferred — no live confirmation-text observation available without a paid account; revisit if a free path is found later"
)
def test_lever_confirmation_exact_copy_TODO_after_step2():
    pytest.fail("Lever submit is intentionally out of scope until confirmation text is observed")


def test_greenhouse_confirmation_metadata_is_read_from_embedded_json():
    page = FakePage(embedded_json=[
        '{"props":{"job":{"confirmationPath":"/confirmation/123",'
        '"confirmation_message":"Thanks for applying"}}}'
    ])

    assert _greenhouse_confirmation_data(page) == {
        "confirmation_path": "/confirmation/123",
        "confirmation_message": "Thanks for applying",
    }


def test_greenhouse_confirmation_metadata_missing_is_not_invented():
    page = FakePage(embedded_json=['{"job":{"title":"Software Engineer"}}'])

    assert _greenhouse_confirmation_data(page) == {
        "confirmation_path": None,
        "confirmation_message": None,
    }


def _new_claim_db(path=":memory:"):
    connection = sqlite3.connect(path, timeout=5, check_same_thread=False)
    initialize_claim_store(connection)
    return connection


def test_claim_is_persisted_before_browser_work():
    connection = _new_claim_db()
    now = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)

    claim = claim_first(
        connection, "fp-1", daily_cap=2, now=now, intent_hash="stored-intent-hash"
    )

    row = connection.execute(
        "SELECT status, job_fingerprint, intent_hash FROM apply_claims WHERE job_fingerprint = ?",
        ("fp-1",),
    ).fetchone()
    assert row == ("submit_in_progress", "fp-1", "stored-intent-hash")
    assert claim["job_fingerprint"] == "fp-1"
    connection.close()


def test_duplicate_live_claim_is_conflict_with_retry_after():
    connection = _new_claim_db()
    now = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
    claim_first(connection, "fp-1", daily_cap=2, now=now)

    with pytest.raises(ClaimConflict) as error:
        claim_first(connection, "fp-1", daily_cap=2, now=now + timedelta(minutes=2))

    assert error.value.retry_after > 0
    connection.close()


def test_stale_claim_expires_and_refunds_slot_before_retry():
    connection = _new_claim_db()
    now = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
    claim_first(connection, "fp-1", daily_cap=1, now=now)

    replacement = claim_first(
        connection, "fp-1", daily_cap=1, now=now + timedelta(minutes=16)
    )

    assert replacement["claimed_at"] == (now + timedelta(minutes=16)).isoformat()
    assert connection.execute("SELECT count FROM daily_apply_caps").fetchone()[0] == 1
    connection.close()


def test_stale_claim_refunds_the_original_day_when_retried_next_day():
    connection = _new_claim_db()
    previous_day = datetime(2026, 9, 28, 23, 40, tzinfo=timezone.utc)
    retry_time = datetime(2026, 9, 29, 0, 1, tzinfo=timezone.utc)
    claim_first(connection, "fp-1", daily_cap=1, now=previous_day)

    claim_first(connection, "fp-1", daily_cap=1, now=retry_time)

    counts = dict(connection.execute("SELECT cap_date, count FROM daily_apply_caps"))
    assert counts["2026-09-28"] == 0
    assert counts["2026-09-29"] == 1
    connection.close()


def test_claim_is_not_stale_at_exactly_fifteen_minutes():
    connection = _new_claim_db()
    now = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
    claim_first(connection, "fp-1", daily_cap=2, now=now)

    with pytest.raises(ClaimConflict):
        claim_first(connection, "fp-1", daily_cap=2, now=now + timedelta(minutes=15))
    connection.close()


def test_submit_unverified_claim_stays_sticky_past_stale_window():
    connection = _new_claim_db()
    now = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
    claim_first(connection, "fp-1", daily_cap=2, now=now)
    connection.execute(
        "UPDATE apply_claims SET status = 'submit_unverified' WHERE job_fingerprint = 'fp-1'"
    )
    connection.commit()

    with pytest.raises(ClaimConflict):
        claim_first(connection, "fp-1", daily_cap=2, now=now + timedelta(hours=1))
    connection.close()


def test_daily_cap_exhaustion_rolls_back_claim_insert_and_counter():
    connection = _new_claim_db()
    now = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
    claim_first(connection, "fp-1", daily_cap=1, now=now)

    with pytest.raises(DailyCapExceeded):
        claim_first(connection, "fp-2", daily_cap=1, now=now)

    assert connection.execute(
        "SELECT 1 FROM apply_claims WHERE job_fingerprint = 'fp-2'"
    ).fetchone() is None
    assert connection.execute("SELECT count FROM daily_apply_caps").fetchone()[0] == 1
    connection.close()


def test_daily_cap_conflict_includes_retry_after():
    connection = _new_claim_db()
    now = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
    claim_first(connection, "fp-1", daily_cap=1, now=now)

    with pytest.raises(DailyCapExceeded) as error:
        claim_first(connection, "fp-2", daily_cap=1, now=now)

    assert error.value.retry_after == 12 * 60 * 60
    connection.close()


def test_zero_daily_cap_rolls_back_without_creating_claim_or_counter():
    connection = _new_claim_db()
    now = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)

    with pytest.raises(DailyCapExceeded):
        claim_first(connection, "fp-1", daily_cap=0, now=now)

    assert connection.execute("SELECT COUNT(*) FROM apply_claims").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM daily_apply_caps").fetchone()[0] == 0
    connection.close()


def test_failed_manual_reconciliation_refunds_only_unverified_claim():
    connection = _new_claim_db()
    now = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
    claim_first(connection, "fp-1", daily_cap=1, now=now)
    connection.execute(
        "UPDATE apply_claims SET status = 'submit_unverified' WHERE job_fingerprint = 'fp-1'"
    )
    connection.commit()

    assert reconcile_failed_claim(connection, "fp-1") is True
    assert connection.execute("SELECT count FROM daily_apply_caps").fetchone()[0] == 0
    assert connection.execute(
        "SELECT status FROM apply_claims WHERE job_fingerprint = 'fp-1'"
    ).fetchone()[0] == "failed_refunded"
    assert not reconcile_failed_claim(connection, "fp-1")
    connection.close()


@pytest.mark.parametrize("terminal_status", ["submitted", "submit_unverified"])
def test_terminal_outcomes_consume_daily_cap_slot(terminal_status):
    connection = _new_claim_db()
    now = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
    claim_first(connection, "fp-1", daily_cap=1, now=now)

    assert finalize_claim(connection, "fp-1", terminal_status)
    assert connection.execute("SELECT count FROM daily_apply_caps").fetchone()[0] == 1
    with pytest.raises(ClaimConflict):
        claim_first(connection, "fp-1", daily_cap=1, now=now + timedelta(minutes=16))
    with pytest.raises(DailyCapExceeded):
        claim_first(connection, "fp-2", daily_cap=1, now=now)
    connection.close()


def test_pre_click_failure_refunds_once_and_sets_failed_refunded():
    connection = _new_claim_db()
    now = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
    claim_first(connection, "fp-1", daily_cap=1, now=now)

    assert mark_pre_click_failure(connection, "fp-1")
    assert not mark_pre_click_failure(connection, "fp-1")
    assert connection.execute("SELECT count FROM daily_apply_caps").fetchone()[0] == 0
    assert connection.execute(
        "SELECT status FROM apply_claims WHERE job_fingerprint = 'fp-1'"
    ).fetchone()[0] == "failed_refunded"
    connection.close()


def test_manual_reconciliation_does_not_refund_a_still_claimed_attempt():
    connection = _new_claim_db()
    now = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
    claim_first(connection, "fp-1", daily_cap=1, now=now)

    assert reconcile_failed_claim(connection, "fp-1") is False
    assert connection.execute("SELECT count FROM daily_apply_caps").fetchone()[0] == 1
    connection.close()


def test_claims_for_different_fingerprints_have_independent_uniqueness():
    connection = _new_claim_db()
    now = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)

    claim_first(connection, "fp-1", daily_cap=3, now=now)
    claim_first(connection, "fp-2", daily_cap=3, now=now)

    assert connection.execute("SELECT COUNT(*) FROM apply_claims").fetchone()[0] == 2
    connection.close()


def test_concurrent_duplicate_claims_have_one_winner(tmp_path):
    database = str(tmp_path / "claims.sqlite")
    setup_connection = sqlite3.connect(database)
    initialize_claim_store(setup_connection)
    setup_connection.close()
    barrier = threading.Barrier(2)
    now = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)

    def attempt_claim():
        connection = sqlite3.connect(database, timeout=5)
        try:
            barrier.wait()
            claim_first(connection, "fp-concurrent", daily_cap=2, now=now)
            return "claimed"
        except ClaimConflict:
            return "conflict"
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: attempt_claim(), range(2)))

    assert sorted(outcomes) == ["claimed", "conflict"]
    connection = sqlite3.connect(database)
    assert connection.execute("SELECT COUNT(*) FROM apply_claims").fetchone()[0] == 1
    connection.close()


def test_concurrent_distinct_claims_cannot_overrun_daily_cap(tmp_path):
    database = str(tmp_path / "capped-claims.sqlite")
    setup_connection = sqlite3.connect(database)
    initialize_claim_store(setup_connection)
    setup_connection.close()
    barrier = threading.Barrier(2)
    now = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)

    def attempt_claim(fingerprint):
        connection = sqlite3.connect(database, timeout=5)
        try:
            barrier.wait()
            claim_first(connection, fingerprint, daily_cap=1, now=now)
            return "claimed"
        except DailyCapExceeded:
            return "capped"
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt_claim, ("fp-1", "fp-2")))

    assert sorted(outcomes) == ["capped", "claimed"]
    connection = sqlite3.connect(database)
    assert connection.execute("SELECT COUNT(*) FROM apply_claims").fetchone()[0] == 1
    assert connection.execute("SELECT count FROM daily_apply_caps").fetchone()[0] == 1
    connection.close()


def test_submit_routes_are_registered_but_kill_switch_stays_off():
    app = create_app()
    routes = app.openapi()["paths"]

    assert "/api/apply/{job_fingerprint}/intent" in routes
    assert "/api/apply/{job_fingerprint}/submit" in routes
    assert SUBMIT_ENABLED is False


def test_match_threshold_and_casefolded_title_acceptance(caplog):
    rejections = validate_submit_inputs(
        actual_ratio=0.85,
        expected_title="Senior Python Engineer",
        raw_title=" senior python engineer ",
    )

    assert rejections == []
    assert caplog.records == []


def test_title_normalization_decomposes_marks_removes_punctuation_and_collapses_space():
    assert normalize_title("  D\u00e9veloppeur \u2014 Caf\u00e9!  II ") == "developpeur cafe ii"


def test_short_expected_title_requires_exact_normalized_equality():
    assert validate_submit_inputs(0.9, "Q-A", "qa") == []
    rejected = validate_submit_inputs(0.9, "QA", "Q")
    assert [item["reason"] for item in rejected] == ["title_mismatch"]


def test_long_expected_title_rejects_input_below_minimum_length():
    rejected = validate_submit_inputs(0.9, "Senior Engineer", "Senior")

    assert [item["reason"] for item in rejected] == ["title_mismatch"]


@pytest.mark.parametrize(("ratio", "accepted"), [(0.85, True), (0.849, False)])
def test_title_sequence_matcher_threshold_boundary(monkeypatch, ratio, accepted):
    import api.apply_validation as validation

    class FixedMatcher:
        def __init__(self, *_args):
            pass

        def ratio(self):
            return ratio

    monkeypatch.setattr(validation, "SequenceMatcher", FixedMatcher)
    rejections = validation.validate_submit_inputs(0.9, "Senior Engineer", "Senior Engineer")

    assert (not rejections) is accepted


def test_below_threshold_rejection_logs_ratio_expected_value_and_raw_input(caplog):
    with caplog.at_level("WARNING", logger="api.apply_validation"):
        rejections = validate_submit_inputs(
            actual_ratio=0.849,
            expected_title="Engineer",
            raw_title="Engineer",
        )

    assert [rejection["reason"] for rejection in rejections] == ["fit_score"]
    record = caplog.records[0]
    assert record.actual_ratio == 0.849
    assert record.expected_value == 0.85
    assert record.raw_input == 0.849
    assert "actual_ratio=0.849" in record.message
    assert "expected_value=0.85" in record.message
    assert "raw_input=0.849" in record.message


def test_title_mismatch_rejection_logs_ratio_expected_title_and_raw_title(caplog):
    with caplog.at_level("WARNING", logger="api.apply_validation"):
        rejections = validate_submit_inputs(
            actual_ratio=0.91,
            expected_title="Senior Engineer",
            raw_title="Staff Engineer",
        )

    assert [rejection["reason"] for rejection in rejections] == ["title_mismatch"]
    record = caplog.records[0]
    assert record.actual_ratio == pytest.approx(0.6896551724)
    assert record.expected_value == "Senior Engineer"
    assert record.raw_input == "Staff Engineer"
    assert "expected_value='Senior Engineer'" in record.message
    assert "raw_input='Staff Engineer'" in record.message


def test_each_rejection_logs_the_original_ratio_and_its_own_expected_value(caplog):
    with caplog.at_level("WARNING", logger="api.apply_validation"):
        rejections = validate_submit_inputs(
            actual_ratio=0.7,
            expected_title="Engineer",
            raw_title="Developer",
        )

    assert len(rejections) == len(caplog.records) == 2
    assert [record.actual_ratio for record in caplog.records] == pytest.approx(
        [0.7, 8 / 17]
    )
    assert [record.expected_value for record in caplog.records] == [0.85, "Engineer"]
    assert [record.raw_input for record in caplog.records] == [0.7, "Developer"]
    assert "actual_ratio=0.7" in caplog.records[0].message
    assert "raw_input=0.7" in caplog.records[0].message
    assert "actual_ratio=0.47058823529411764" in caplog.records[1].message
    assert "raw_input='Developer'" in caplog.records[1].message


def test_confirmation_echo_requires_literal_true_and_exact_fingerprint(caplog):
    with caplog.at_level("WARNING", logger="api.apply_validation"):
        rejected = validate_confirmation_echo(True, "fp-1", "fp-1", 0.92)

    assert rejected == []
    assert caplog.records == []


@pytest.mark.parametrize("confirm", [False, 1, "true", None])
def test_confirmation_echo_rejects_non_boolean_true_and_audits(caplog, confirm):
    with caplog.at_level("WARNING", logger="api.apply_validation"):
        rejected = validate_confirmation_echo(confirm, "fp-1", "fp-1", 0.92)

    assert [item["reason"] for item in rejected] == ["confirmation_required"]
    assert caplog.records[0].actual_ratio == 0.92
    assert caplog.records[0].expected_value is True
    assert caplog.records[0].raw_input == confirm
    assert "actual_ratio=0.92" in caplog.records[0].message
    assert "expected_value=True" in caplog.records[0].message
    assert "raw_input=" in caplog.records[0].message


def test_confirmation_echo_rejects_fingerprint_mismatch_and_audits(caplog):
    with caplog.at_level("WARNING", logger="api.apply_validation"):
        rejected = validate_confirmation_echo(True, "fp-other", "fp-1", 0.92)

    assert [item["reason"] for item in rejected] == ["fingerprint_mismatch"]
    assert caplog.records[0].actual_ratio == 0.92
    assert caplog.records[0].expected_value == "fp-1"
    assert caplog.records[0].raw_input == "fp-other"


def test_multiple_confirmation_rejections_are_each_audited(caplog):
    with caplog.at_level("WARNING", logger="api.apply_validation"):
        rejected = validate_confirmation_echo(False, "wrong-fp", "right-fp", 0.8)

    assert len(rejected) == len(caplog.records) == 2
    assert [record.expected_value for record in caplog.records] == [True, "right-fp"]
    assert [record.raw_input for record in caplog.records] == [False, "wrong-fp"]
    assert all(record.actual_ratio == 0.8 for record in caplog.records)


def _new_intent_db():
    connection = sqlite3.connect(":memory:")
    initialize_intent_store(connection)
    return connection


def test_only_one_unexpired_intent_is_allowed_per_fingerprint():
    connection = _new_intent_db()
    now = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
    create_intent(connection, "fp-1", "intent-1", now + timedelta(minutes=5), now)

    with pytest.raises(ActiveIntentConflict):
        create_intent(connection, "fp-1", "intent-2", now + timedelta(minutes=10), now)
    connection.close()


def test_intent_storage_hashes_token_and_validates_matching_fingerprint():
    connection = _new_intent_db()
    now = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
    intent = create_intent(
        connection, "fp-1", "opaque-token", now + timedelta(minutes=5), now
    )

    assert intent["token_hash"] == hashlib.sha256(b"opaque-token").hexdigest()
    stored = connection.execute(
        "SELECT token_hash, consumed FROM apply_intents WHERE job_fingerprint = 'fp-1'"
    ).fetchone()
    assert stored == (hashlib.sha256(b"opaque-token").hexdigest(), 0)
    assert validate_intent(connection, "fp-1", "opaque-token", now) == stored[0]
    connection.close()


@pytest.mark.parametrize(
    ("fingerprint", "token", "exception"),
    [
        ("fp-1", "wrong-token", IntentExpired),
        ("fp-other", "opaque-token", IntentExpired),
    ],
)
def test_wrong_token_or_fingerprint_is_a_dead_intent(fingerprint, token, exception):
    connection = _new_intent_db()
    now = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
    create_intent(connection, "fp-1", "opaque-token", now + timedelta(minutes=5), now)

    with pytest.raises(exception):
        validate_intent(connection, fingerprint, token, now)
    connection.close()


def test_expired_intent_is_rejected():
    connection = _new_intent_db()
    now = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
    create_intent(connection, "fp-1", "opaque-token", now + timedelta(minutes=5), now)

    with pytest.raises(IntentExpired):
        validate_intent(connection, "fp-1", "opaque-token", now + timedelta(minutes=5))
    connection.close()


def test_consumed_intent_cannot_be_reused():
    connection = _new_intent_db()
    now = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
    create_intent(connection, "fp-1", "opaque-token", now + timedelta(minutes=5), now)

    consume_intent(connection, "fp-1", "opaque-token", now)
    with pytest.raises(IntentConsumed):
        validate_intent(connection, "fp-1", "opaque-token", now)
    connection.close()


def test_expired_intent_can_be_replaced_for_same_fingerprint():
    connection = _new_intent_db()
    now = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
    create_intent(connection, "fp-1", "intent-1", now + timedelta(minutes=5), now)

    replacement = create_intent(
        connection,
        "fp-1",
        "intent-2",
        now + timedelta(minutes=10),
        now + timedelta(minutes=5),
    )

    assert replacement["token_hash"] == hashlib.sha256(b"intent-2").hexdigest()
    assert connection.execute(
        "SELECT token_hash FROM apply_intents WHERE job_fingerprint = 'fp-1'"
    ).fetchone()[0] == hashlib.sha256(b"intent-2").hexdigest()
    connection.close()


def test_intent_expiring_now_is_no_longer_live():
    connection = _new_intent_db()
    now = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
    create_intent(connection, "fp-1", "intent-1", now, now - timedelta(minutes=1))

    replacement = create_intent(connection, "fp-1", "intent-2", now + timedelta(minutes=5), now)

    assert replacement["token_hash"] == hashlib.sha256(b"intent-2").hexdigest()
    connection.close()


def test_live_intents_for_different_fingerprints_are_independent():
    connection = _new_intent_db()
    now = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)

    create_intent(connection, "fp-1", "intent-1", now + timedelta(minutes=5), now)
    create_intent(connection, "fp-2", "intent-2", now + timedelta(minutes=5), now)

    assert connection.execute("SELECT COUNT(*) FROM apply_intents").fetchone()[0] == 2
    connection.close()


def test_concurrent_intent_requests_have_one_live_winner(tmp_path):
    database = str(tmp_path / "intents.sqlite")
    setup_connection = sqlite3.connect(database)
    initialize_intent_store(setup_connection)
    setup_connection.close()
    barrier = threading.Barrier(2)
    now = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)

    def attempt_intent(intent_id):
        connection = sqlite3.connect(database, timeout=5)
        try:
            barrier.wait()
            create_intent(
                connection,
                "fp-same",
                intent_id,
                now + timedelta(minutes=5),
                now,
            )
            return "created"
        except ActiveIntentConflict:
            return "conflict"
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt_intent, ("intent-1", "intent-2")))

    assert sorted(outcomes) == ["conflict", "created"]
    connection = sqlite3.connect(database)
    assert connection.execute("SELECT COUNT(*) FROM apply_intents").fetchone()[0] == 1
    connection.close()


def test_consumed_intent_is_replaceable_without_waiting():
    connection = _new_intent_db()
    now = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
    create_intent(connection, "fp-1", "intent-1", now + timedelta(minutes=5), now)
    consume_intent(connection, "fp-1", "intent-1", now)

    replacement = create_intent(connection, "fp-1", "intent-2", now + timedelta(minutes=5), now)

    assert replacement["token_hash"] == hashlib.sha256(b"intent-2").hexdigest()
    validate_intent(connection, "fp-1", "intent-2", now)
    connection.close()


def test_unconsumed_live_intent_still_conflicts():
    connection = _new_intent_db()
    now = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
    create_intent(connection, "fp-1", "intent-1", now + timedelta(minutes=5), now)

    with pytest.raises(ActiveIntentConflict):
        create_intent(connection, "fp-1", "intent-2", now + timedelta(minutes=5), now)
    connection.close()


def test_failed_refunded_claim_allows_fresh_retry():
    connection = _new_claim_db()
    now = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
    claim_first(connection, "fp-1", daily_cap=2, now=now)
    assert mark_pre_click_failure(connection, "fp-1") is True

    retry = claim_first(connection, "fp-1", daily_cap=2, now=now + timedelta(minutes=1))

    assert retry["status"] == "submit_in_progress"
    count = connection.execute(
        "SELECT count FROM daily_apply_caps WHERE cap_date = '2026-09-29'"
    ).fetchone()[0]
    assert count == 1  # refunded slot reused, not double-counted
    connection.close()


def test_terminal_submitted_claim_still_conflicts():
    connection = _new_claim_db()
    now = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
    claim_first(connection, "fp-1", daily_cap=2, now=now)
    finalize_claim(connection, "fp-1", "submitted")

    with pytest.raises(ClaimConflict):
        claim_first(connection, "fp-1", daily_cap=2, now=now + timedelta(minutes=1))
    connection.close()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (85, 85),
        (76.5, 76),
        ("85.0", 85),
        ("87%", 87),
        ("  72  ", 72),
        ("", 0),
        (None, 0),
        ("not-a-score", 0),
    ],
)
def test_safe_score_coerces_sheet_values(raw, expected):
    assert _safe_score({"match_score": raw}) == expected


def test_safe_score_never_crashes_tier_classification():
    assert classify_tier({"match_score": "85.0"}) == "good_fit"
    assert classify_tier({"match_score": ""}) == "batch"
    assert classify_tier({"match_score": None}) == "batch"
    assert classify_tier({"match_score": "95%"}) == "dream"
