"""Regression coverage for the 2026-10-18 AUDIT.md fixes.

Every test here maps to a numbered finding: the Bugs 1-4 counters/clamps,
the C2 scoring redesign, PM-4's role-noun body patterns, the B8 days_ago
repair, the §6 circuit breaker and the Bug 5 Sheets backoff. Isolated units
only — no Sheets, no LLMs, no browsers, no network.
"""

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents import scrapper as sc
from tools import sheet_writer
from tools.cv_matcher import CVMatcher, NO_CORE_STACK_CEILING
from tools.deduplicator import title_company_key


# =============================================================================
# Bugs 3 + 4 — freshness bounds (agents/curator.py)
# =============================================================================

def _boost(days_old: int) -> int:
    from datetime import date, timedelta
    from agents.curator import _calculate_freshness_boost
    posted = (date.today() - timedelta(days=days_old)).isoformat()
    return _calculate_freshness_boost(posted)


def test_freshness_day7_gets_zero_not_day4_boost():
    # Bug 3: the map says day 7 -> 0; the old `<= 7` branch gave it +2.
    assert _boost(7) == 0
    assert _boost(6) == 2  # days 4-6 keep the small boost


def test_freshness_day30_and_old():
    assert _boost(30) == 0
    assert _boost(31) == -10


def test_freshness_today_and_yesterday():
    assert _boost(0) == 20
    assert _boost(1) == 10


def test_future_date_one_day_is_timezone_skew_gets_today_boost():
    # Bug 4: -1 day is a legitimate timezone artifact, treated as today.
    assert _boost(-1) == 20


def test_future_date_beyond_one_day_gets_no_boost():
    # Bug 4: garbage future dates must not outrank genuinely fresh jobs.
    assert _boost(-5) == 0
    assert _boost(-400) == 0


# =============================================================================
# Bug 2 — cross-board dedup key (tools/deduplicator.py)
# =============================================================================

def test_same_title_company_different_url_is_same_key():
    a = {"job_title": "Software Engineer I, Fullstack (Search)", "company": "Wayfair",
         "apply_url": "https://boards.greenhouse.io/wayfair/jobs/1"}
    b = {"job_title": "Software Engineer I, Fullstack (Search)", "company": "Wayfair",
         "apply_url": "https://jobs.lever.co/wayfair/2"}
    assert title_company_key(a) == title_company_key(b)


def test_key_is_whitespace_and_case_insensitive():
    a = {"job_title": "Senior  Engineer", "company": "Dave", "apply_url": "https://a/1"}
    b = {"job_title": "senior engineer", "company": "dave", "apply_url": "https://a/2"}
    assert title_company_key(a) == title_company_key(b)


def test_missing_half_of_key_never_matches():
    # Two "Unknown"-company jobs share nothing else — collapsing them would
    # be a false positive.
    assert title_company_key({"job_title": "Developer", "company": ""}) == ""
    assert title_company_key({"job_title": "", "company": "Acme"}) == ""


# =============================================================================
# Bugs 1 + 2 — curator counters and second dedup pass
# =============================================================================

@pytest.fixture
def curator_module(monkeypatch):
    """Load curator privately with no on-disk CV/LLM setup or module leaks."""
    import dotenv
    from tools import cv_library

    monkeypatch.setenv("CV_PATH", "")
    monkeypatch.setenv("CV_DIR", "")
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **kw: None)
    monkeypatch.setattr(cv_library, "_library", None)
    path = Path(__file__).resolve().parents[1] / "agents" / "curator.py"
    spec = importlib.util.spec_from_file_location("_curator_audit_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "cleanup_sheet", lambda *a: None)
    monkeypatch.setattr(module, "get_all_rows", lambda: [])
    monkeypatch.setattr(module, "load_seen_hashes", set)
    monkeypatch.setattr(module, "save_seen_hashes", lambda *a: None)
    monkeypatch.setattr(module, "append_rows", lambda *a: None)
    monkeypatch.setattr(module, "is_allowed_location", lambda job: True)
    monkeypatch.setattr(module, "_should_reject", lambda job: (False, ""))
    return module


def test_missing_url_counted_not_dropped_silently(curator_module, monkeypatch):
    # Bug 1: 155 - 15 = 140 expected vs 136 counted — 4 jobs vanished.
    jobs = [
        {"job_title": "A", "company": "x", "apply_url": "https://a/1"},
        {"job_title": "B", "company": "x", "apply_url": "https://a/1"},   # url dup
        {"job_title": "C", "company": "x", "apply_url": ""},              # missing url
        {"job_title": "D", "company": "x", "apply_url": "https://d/1"},
    ]
    result = curator_module.curate(jobs, tracker=SimpleNamespace(stage=lambda *a: None))
    assert result["stats"]["url_duplicates"] == 1
    assert result["stats"]["missing_url"] == 1
    # No CV configured -> everything scores 0 -> nothing passes the gate.
    assert result["status"] == "warning"


def test_cross_board_duplicates_collapsed(curator_module):
    # Bug 2: same opening on two boards — different URLs, one job.
    jobs = [
        {"job_title": "Backend Engineer", "company": "Dave", "apply_url": "https://gh/dave/1"},
        {"job_title": "Backend Engineer", "company": "Dave", "apply_url": "https://lever/dave/1"},
        {"job_title": "Frontend Engineer", "company": "Dave", "apply_url": "https://gh/dave/2"},
    ]
    result = curator_module.curate(jobs, tracker=SimpleNamespace(stage=lambda *a: None))
    assert result["stats"]["cross_board_dupes"] == 1


def test_stats_account_for_every_input_job(curator_module):
    # original == url dupes + missing url + cross-board dupes + fp dupes + unique
    jobs = [
        {"job_title": "A", "company": "x", "apply_url": "https://a/1"},
        {"job_title": "A", "company": "x", "apply_url": "https://a/1"},   # url dup
        {"job_title": "B", "company": "x", "apply_url": ""},              # missing url
        {"job_title": "C", "company": "x", "apply_url": "https://c/1"},
        {"job_title": "C", "company": "x", "apply_url": "https://c/2"},   # cross-board
    ]
    stats = curator_module.curate(
        jobs, tracker=SimpleNamespace(stage=lambda *a: None))["stats"]
    assert stats["url_duplicates"] == 1
    assert stats["missing_url"] == 1
    assert stats["cross_board_dupes"] == 1
    assert stats["low_match"] == 2  # A and C survive dedup, score 0


# =============================================================================
# C2 — coverage credit redesign + capped no-core-stack path (tools/cv_matcher.py)
# =============================================================================

CV = {
    "skills": ["Python", "React", "PostgreSQL"],
    "preferred_titles": ["fullstack", "backend"],
    "seniority": "mid",
}


def _job(title, summary):
    return {"job_title": title, "summary": summary, "tech_stack": ""}


@pytest.fixture(scope="module")
def matcher():
    return CVMatcher(CV)


def test_detailed_posting_is_no_longer_punished(matcher):
    # C2's exact failure class: 5 core skills listed, CV matches 3 — the
    # old linear formula scored this ~55 (LOW MATCH). It must now pass.
    job = _job("Full Stack Developer",
               "Join our team working with Python React Node.js and Docker on PostgreSQL microservices")
    result = matcher.score(job)
    assert result["score"] >= 70
    assert result["has_core_signal"] is True


def test_partial_coverage_orders_below_full_coverage(matcher):
    strong = matcher.score(_job(
        "Full Stack Developer",
        "Working with Python React Node.js Docker PostgreSQL microservices"))
    weak = matcher.score(_job(
        "Full Stack Developer",
        "Working with Python Node.js Docker Redis Kubernetes golang"))
    assert strong["score"] > weak["score"]


def test_genuine_no_overlap_stays_zero(matcher):
    # The has_core_signal gate keeps its meaning: a core stack the CV does
    # not touch at all is a real zero, not a maybe.
    result = matcher.score(_job("Golang Engineer", "Golang Kubernetes microservices"))
    assert result["score"] == 0
    assert result["match_reason"] == "No core stack overlap"


def test_no_core_stack_listed_capped_below_gate(matcher):
    # Stub/tooling-only text: never 0 when signals agree, never a full pass
    # either — capped into the maybe range for human triage.
    result = matcher.score(_job(
        "Full Stack Developer", "Team player with git and agile experience"))
    assert result["score"] <= NO_CORE_STACK_CEILING
    assert result["score"] < 70
    assert "No core stack listed" in result["match_reason"]


def test_no_core_stack_with_zero_signals_scores_zero(matcher):
    result = matcher.score(_job("Software Engineer", "Great opportunity, apply now"))
    assert result["score"] == 0


# =============================================================================
# PM-4 — body rejection patterns require a role noun (tools/cv_matcher.py)
# =============================================================================

def test_security_company_blurb_does_not_reject(matcher):
    # BeyondTrust's Cloud Engineer was rejected because the company blurb
    # mentions cybersecurity. "Works at a security company" is not a
    # rejection reason.
    should, _ = matcher.should_reject(_job(
        "Cloud Engineer",
        "Join BeyondTrust, a cybersecurity leader, and build our AWS platform"))
    assert should is False


def test_cybersecurity_role_in_body_still_rejects(matcher):
    should, reason = matcher.should_reject(_job(
        "Cloud Engineer",
        "We are hiring a cybersecurity engineer to run our SOC"))
    assert should is True
    assert "cybersecurity" in reason


def test_title_cybersecurity_still_rejects(matcher):
    # Titles keep the bare pattern — a security-role title IS the role.
    should, _ = matcher.should_reject(_job(
        "Cybersecurity Analyst", "Protect systems and networks"))
    assert should is True


# =============================================================================
# B8 — days_ago is real again (agents/scrapper.py)
# =============================================================================

def test_days_ago_returns_real_age():
    from datetime import date, timedelta
    assert sc.days_ago(date.today().isoformat()) == 0
    old = (date.today() - timedelta(days=49)).isoformat()
    assert sc.days_ago(old) == 49


def test_days_ago_unparseable_or_missing_returns_none():
    assert sc.days_ago("not-a-date") is None
    assert sc.days_ago("") is None
    assert sc.days_ago(None) is None


# =============================================================================
# §6 — circuit breaker (agents/scrapper.py)
# =============================================================================

@pytest.fixture
def breaker(tmp_path, monkeypatch):
    monkeypatch.setattr(sc, "BOARD_HEALTH_PATH", tmp_path / "board_health.json")
    health = {}
    return health


def test_breaker_open_after_three_consecutive_failures(breaker):
    for _ in range(sc.BREAKER_FAIL_THRESHOLD):
        sc._board_breaker_record("FlexJobs", breaker, success=False)
    assert sc._board_breaker_check("FlexJobs", breaker) is True


def test_breaker_not_tripped_by_one_or_two_failures(breaker):
    sc._board_breaker_record("Remotees", breaker, success=False)
    sc._board_breaker_record("Remotees", breaker, success=False)
    assert sc._board_breaker_check("Remotees", breaker) is False


def test_breaker_cooldown_decrements_per_run(breaker):
    for _ in range(sc.BREAKER_FAIL_THRESHOLD):
        sc._board_breaker_record("CWJobs", breaker, success=False)
    assert sc._board_breaker_check("CWJobs", breaker) is True
    assert breaker["CWJobs"]["cooldown"] == sc.BREAKER_COOLDOWN_RUNS - 1


def test_breaker_resets_on_recovery(breaker):
    for _ in range(sc.BREAKER_FAIL_THRESHOLD):
        sc._board_breaker_record("NaukriGulf", breaker, success=False)
    sc._board_breaker_record("NaukriGulf", breaker, success=True)
    assert breaker["NaukriGulf"] == {"fails": 0, "cooldown": 0}
    assert sc._board_breaker_check("NaukriGulf", breaker) is False


def test_breaker_state_persists_to_disk(breaker, monkeypatch):
    # Each run is a fresh interpreter — state must survive via the JSON file.
    for _ in range(sc.BREAKER_FAIL_THRESHOLD):
        sc._board_breaker_record("FlexJobs", breaker, success=False)
    reloaded = sc._load_board_health()
    assert reloaded["FlexJobs"]["fails"] == sc.BREAKER_FAIL_THRESHOLD


def test_timesjobs_dropped_from_master_boards():
    # §6: TLS chain genuinely broken, out of region, 3 retries burned every
    # run — the board is removed.
    assert "TimesJobs" not in sc.MASTER_BOARDS


# =============================================================================
# Bug 5 — Sheets 429 backoff (tools/sheet_writer.py)
# =============================================================================

class _Throttled(Exception):
    """Stand-in for gspread.exceptions.APIError with a .status attribute."""

    def __init__(self, status=429):
        super().__init__(f"[{status}] Quota exceeded")
        self.status = status


@pytest.fixture
def no_sleep(monkeypatch):
    sleeps = []
    monkeypatch.setattr(sheet_writer.time, "sleep", lambda s: sleeps.append(s))
    return sleeps


def test_backoff_retries_429_then_succeeds(no_sleep):
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise _Throttled(429)
        return "ok"

    assert sheet_writer._sheets_backoff(flaky) == "ok"
    assert calls["n"] == 3
    assert len(no_sleep) == 2  # backed off between attempts


def test_backoff_retries_5xx(no_sleep):
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 2:
            raise _Throttled(503)
        return "ok"

    assert sheet_writer._sheets_backoff(flaky) == "ok"
    assert calls["n"] == 2


def test_backoff_gives_up_after_max_retries(no_sleep):
    calls = {"n": 0}

    def always_429():
        calls["n"] += 1
        raise _Throttled(429)

    with pytest.raises(_Throttled):
        sheet_writer._sheets_backoff(always_429)
    assert calls["n"] == sheet_writer.SHEETS_MAX_RETRIES


def test_backoff_does_not_retry_other_errors(no_sleep):
    calls = {"n": 0}

    def broken():
        calls["n"] += 1
        raise ValueError("not a quota problem")

    with pytest.raises(ValueError):
        sheet_writer._sheets_backoff(broken)
    assert calls["n"] == 1
    assert no_sleep == []


# =============================================================================
# PM-1 — tier thresholds are module-level and coherent (tools/sheet_writer.py)
# =============================================================================

def test_tier_thresholds_share_the_documented_story():
    # TOP bar above the GOOD bar, GOOD bar following MIN_MATCH_SCORE, and
    # the maybe-bucket floor below both.
    assert sheet_writer.TOP_MATCH_THRESHOLD > sheet_writer.GOOD_MATCH_THRESHOLD
    assert sheet_writer.MAYBE_MATCH_THRESHOLD < sheet_writer.GOOD_MATCH_THRESHOLD


def test_maybe_bucket_disabled_by_default():
    # A new tab changes sheet structure — it must be opt-in.
    assert sheet_writer.MAYBE_MATCHES_ENABLED is False


# =============================================================================
# Review items (2026-10-21) — titles, zero-scoring, rejections, ranking
# =============================================================================

def test_title_keywords_derived_from_experience_when_preferred_empty():
    # Review item 1: empty preferred_titles silently disabled the
    # title-alignment bonus. The CV's own experience titles are the same
    # signal and must fill in.
    cv = {"skills": ["Python"], "preferred_titles": [],
          "experience": [{"title": "Software Engineer", "description": ""}]}
    m = CVMatcher(cv)
    assert "software" in m.cv_title_keywords


def test_deliberate_preferred_titles_respected_over_experience():
    # A user redirecting careers ("Data Scientist") must not have stale
    # experience titles override the explicit list.
    cv = {"skills": ["Python"], "preferred_titles": ["Data Scientist"],
          "experience": [{"title": "Software Engineer", "description": ""}]}
    m = CVMatcher(cv)
    assert m.cv_title_keywords == set()


def test_generic_title_with_thin_description_not_zero():
    # Review item 2: "Software Engineer" over an incomplete description was
    # a hard 0. Title agreement is real signal — capped into the maybe
    # range, never a silent discard.
    cv = {"skills": ["Python", "React"], "preferred_titles": ["Software Engineer"],
          "seniority": "junior"}
    m = CVMatcher(cv)
    result = m.score({"job_title": "Software Engineer",
                      "summary": "Great team, competitive salary", "tech_stack": ""})
    assert 0 < result["score"] <= NO_CORE_STACK_CEILING
    assert "title signals only" in result["match_reason"]


def test_integration_engineer_title_not_rejected():
    # Review item 3: backend/API integration roles are target dev work.
    m = CVMatcher(CV)
    should, _ = m.should_reject({"job_title": "Backend Integration Engineer (APIs)",
                                 "summary": "", "tech_stack": ""})
    assert should is False


def test_enterprise_integration_still_rejected():
    # The tool patterns that motivated the old bare title pattern remain.
    m = CVMatcher(CV)
    should, _ = m.should_reject({"job_title": "Mulesoft Integration Engineer",
                                 "summary": "", "tech_stack": ""})
    assert should is True


def test_score_breakdown_travels_with_result():
    # Review item 5: every score explanation must be checkable against the
    # numbers that produced it.
    m = CVMatcher(CV)
    result = m.score({"job_title": "Full Stack Developer",
                      "summary": "Python React PostgreSQL microservices",
                      "tech_stack": ""})
    b = result["breakdown"]
    assert b["title_bonus"] >= 0
    assert 0.0 <= b["core_credit"] <= 1.0
    assert b["cap_applied"] is None  # main path, nothing capped
    # The claimed components must actually reassemble the score.
    rebuilt = int(b["core_credit"] * 70 + b["exact_bonus"] + b["tooling_bonus"]
                  + b["title_bonus"] + b["seniority_bonus"])
    assert min(100, rebuilt) == result["score"]


def test_rank_score_attached_and_distinct_from_match(curator_module, monkeypatch):
    # Review item 4: match quality (the gate) and the ranking composite
    # (salary/company/stack tie-breaks) are different numbers and both must
    # be visible on the job.
    monkeypatch.setattr(curator_module, "CV_MATCHING_ENABLED", True)
    monkeypatch.setattr(curator_module, "CV_PROFILE", {"skills": ["Python"]})
    monkeypatch.setattr(curator_module, "_CV_LIBRARY", SimpleNamespace(is_empty=True))
    monkeypatch.setattr(curator_module, "_get_matcher_for_profile",
                        lambda *a, **kw: SimpleNamespace(
                            score=lambda job: {"score": 80, "match_reason": "t"}))
    jobs = [{"job_title": "Backend Developer", "company": "Acme", "salary": "$90k",
             "tech_stack": "Python", "apply_url": "https://a/1",
             "summary": "Python API work"}]
    result = curator_module.curate(jobs, tracker=SimpleNamespace(stage=lambda *a: None))
    job = result["top_jobs"][0]
    assert isinstance(job["rank_score"], int)
    assert job["match_score"] == 80          # CV fit (gated)
    assert job["rank_score"] >= job["match_score"] * 2  # composite adds order signals
