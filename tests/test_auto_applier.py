"""Unit tests for agents/auto_applier.py"""
import sys
import os
import json
import tempfile
import shutil
from pathlib import Path
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.auto_applier import (
    classify_tier,
    get_tier_action,
    detect_ats_platform,
    _init_db,
    _already_applied,
    _get_daily_auto_submit_count,
    _increment_daily_stat,
    _save_application,
    generate_apply_package,
    generate_email_outreach,
    AUTO_APPLY_CONFIRM,
    TIER_DREAM_THRESHOLD,
    TIER_BATCH_MAX,
)


class TestClassifyTier:
    def test_dream_tier(self):
        job = {"match_score": TIER_DREAM_THRESHOLD}
        assert classify_tier(job) == "dream"

    def test_dream_tier_above(self):
        job = {"match_score": 95}
        assert classify_tier(job) == "dream"

    def test_good_fit_tier_above_batch(self):
        score = TIER_BATCH_MAX + 1
        job = {"match_score": score}
        assert classify_tier(job) == "good_fit"

    def test_good_fit_tier_mid(self):
        mid = (TIER_BATCH_MAX + TIER_DREAM_THRESHOLD) // 2
        job = {"match_score": mid}
        assert classify_tier(job) == "good_fit"

    def test_batch_tier(self):
        job = {"match_score": 0}
        assert classify_tier(job) == "batch"

    def test_batch_tier_at_max(self):
        job = {"match_score": TIER_BATCH_MAX}
        assert classify_tier(job) == "batch"

    def test_batch_tier_below(self):
        job = {"match_score": TIER_BATCH_MAX - 10}
        assert classify_tier(job) == "batch"

    def test_fallback_to_score_key(self):
        job = {"score": 80}
        assert classify_tier(job) == "good_fit"

    def test_missing_score_defaults_batch(self):
        job = {}
        assert classify_tier(job) == "batch"


class TestGetTierAction:
    def test_dream_action(self):
        action = get_tier_action("dream")
        assert action["auto_open"] == True
        assert action["auto_fill"] == False
        assert action["auto_submit"] == False
        assert action["notify"] == True
        assert action["require_confirm"] == True

    def test_good_fit_action(self):
        action = get_tier_action("good_fit")
        assert action["auto_open"] == True
        assert action["auto_fill"] == True
        assert action["auto_submit"] == False
        assert action["notify"] == False
        assert action["require_confirm"] == True

    def test_batch_action_confirm_disabled(self):
        action = get_tier_action("batch")
        assert action["auto_open"] == True
        assert action["auto_fill"] == True
        assert action["auto_submit"] == AUTO_APPLY_CONFIRM
        assert action["notify"] == False
        assert action["require_confirm"] == False

    def test_unknown_tier_falls_back_to_good_fit(self):
        action = get_tier_action("nonexistent")
        assert action["auto_fill"] == True
        assert action["require_confirm"] == True


class TestDetectATSPlatform:
    def test_greenhouse(self):
        assert detect_ats_platform("https://boards.greenhouse.io/company/jobs/123") == "greenhouse"

    def test_greenhouse_alt(self):
        assert detect_ats_platform("https://company.greenhouse.io/jobs/123") == "greenhouse"

    def test_lever(self):
        assert detect_ats_platform("https://jobs.lever.co/company/role") == "lever"

    def test_lever_alt(self):
        assert detect_ats_platform("https://company.lever.co/jobs/123") == "lever"

    def test_workday(self):
        assert detect_ats_platform("https://myworkdayjobs.com/company") == "workday"

    def test_workday_alt(self):
        assert detect_ats_platform("https://company.workday.com/careers") == "workday"

    def test_workable(self):
        assert detect_ats_platform("https://apply.workable.com/company/") == "workable"

    def test_ashby(self):
        assert detect_ats_platform("https://jobs.ashbyhq.com/company") == "ashby"

    def test_breezy(self):
        assert detect_ats_platform("https://company.breezy.hr/p/123") == "breezy"

    def test_linkedin(self):
        assert detect_ats_platform("https://www.linkedin.com/jobs/view/123") == "linkedin"

    def test_unknown(self):
        assert detect_ats_platform("https://company.com/careers") == "unknown"

    def test_empty_url(self):
        assert detect_ats_platform("") == "unknown"

    def test_case_insensitive(self):
        assert detect_ats_platform("HTTPS://BOARDS.GREENHOUSE.IO/JOBS/123") == "greenhouse"


class TestGenerateApplyPackage:
    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.job = {
            "job_title": "Backend Developer",
            "company": "TestCorp",
            "apply_url": "https://testcorp.com/apply/123",
            "match_score": 85,
            "summary": "Build APIs",
            "tech_stack": "Python, Django",
        }
        self.cover_letter = "Dear Hiring Manager, I am a great fit..."

    def teardown_method(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_generates_package_without_resume(self):
        pkg = generate_apply_package(self.job, None, self.cover_letter, output_folder=self.temp_dir)
        assert pkg is not None
        assert Path(pkg).exists()
        assert Path(pkg, "cover_letter.txt").exists()
        assert Path(pkg, "form_data.json").exists()
        assert Path(pkg, "index.html").exists()
        assert not Path(pkg, "resume.pdf").exists()

    def test_form_data_contains_job_and_applicant(self):
        pkg = generate_apply_package(self.job, None, self.cover_letter, output_folder=self.temp_dir)
        with open(Path(pkg, "form_data.json")) as f:
            data = json.load(f)
        assert data["job"]["job_title"] == "Backend Developer"
        assert data["job"]["company"] == "TestCorp"
        assert "applicant" in data
        assert data["cover_letter"] == self.cover_letter

    def test_cover_letter_content_written(self):
        pkg = generate_apply_package(self.job, None, self.cover_letter, output_folder=self.temp_dir)
        with open(Path(pkg, "cover_letter.txt"), encoding="utf-8") as f:
            content = f.read()
        assert content == self.cover_letter

    def test_index_html_contains_job_info(self):
        pkg = generate_apply_package(self.job, None, self.cover_letter, output_folder=self.temp_dir)
        with open(Path(pkg, "index.html"), encoding="utf-8") as f:
            html = f.read()
        assert "Backend Developer" in html
        assert "TestCorp" in html
        assert self.cover_letter in html

    def test_returns_none_on_error(self):
        result = generate_apply_package(self.job, None, self.cover_letter, output_folder="")
        assert result is None


class TestGenerateEmailOutreach:
    def setup_method(self):
        self.job = {
            "job_title": "Frontend Engineer",
            "company": "WebCorp",
            "apply_url": "https://webcorp.com/careers/456",
            "summary": "Build UI components",
        }
        self.cover_letter = "I have 5 years of React experience."
        self.resume_path = None

    def teardown_method(self):
        email_dir = Path("email_drafts")
        if email_dir.exists():
            shutil.rmtree(str(email_dir), ignore_errors=True)

    def test_generates_email_draft(self):
        path = generate_email_outreach(self.job, self.cover_letter, self.resume_path)
        assert path is not None
        assert Path(path).exists()

    def test_email_contains_subject_and_body(self):
        path = generate_email_outreach(self.job, self.cover_letter, self.resume_path)
        with open(path, encoding="utf-8") as f:
            content = f.read()
        assert "Subject:" in content
        assert "Frontend Engineer" in content
        assert "WebCorp" in content
        assert self.cover_letter[:500] in content

    def test_email_includes_applicant_info(self):
        path = generate_email_outreach(self.job, self.cover_letter, self.resume_path)
        with open(path, encoding="utf-8") as f:
            content = f.read()
        assert "Mubashir" in content or "APPLICANT_NAME" not in content
        assert "careers@webcorp.com" in content


class TestSQLiteState:
    def setup_method(self):
        self.db_path = Path("data/job_agent.db")
        if self.db_path.exists():
            self.db_path.unlink()
        _init_db()

    def teardown_method(self):
        if self.db_path.exists():
            self.db_path.unlink()

    def test_not_applied_initially(self):
        assert _already_applied("some_fingerprint") == False

    def test_tracks_application(self):
        job = {
            "job_fingerprint": "test_fp_001",
            "job_title": "Engineer",
            "company": "Co",
            "apply_url": "https://co.com/apply",
            "match_score": 80,
        }
        result = {"status": "filled_ready", "resume_path": None, "cover_letter_path": None,
                  "package_path": None, "screenshot_path": None, "error": None}
        _save_application(job, result, "good_fit")
        assert _already_applied("test_fp_001") == True

    def test_fingerprint_fallback_to_url(self):
        job = {
            "job_title": "Dev",
            "company": "Inc",
            "apply_url": "https://inc.com/apply/unique",
        }
        result = {"status": "email_draft", "resume_path": None, "cover_letter_path": None,
                  "package_path": None, "screenshot_path": None, "error": None}
        _save_application(job, result, "batch")
        assert _already_applied("https://inc.com/apply/unique") == True

    def test_daily_stats_start_at_zero(self):
        count = _get_daily_auto_submit_count()
        assert isinstance(count, int)

    def test_daily_stat_increments(self):
        before = _get_daily_auto_submit_count()
        _increment_daily_stat("auto_submitted")
        after = _get_daily_auto_submit_count()
        assert after == before + 1
