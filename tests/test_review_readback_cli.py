"""CLI and API must apply the same review readback policy; never click."""
import sys
from types import SimpleNamespace

import pytest

from agents import auto_applier as aa


@pytest.mark.parametrize('platform,overrides,tier,expected,reason', [
    ('greenhouse', {'resume_attached': False, 'resume_verify': 'unavailable'},
     'batch', 'needs_review', 'Resume attachment'),
    ('lever', {'cover_letter_pasted': False, 'cover_letter_verify': 'mismatch'},
     'good_fit', 'needs_review', 'Cover letter'),
    ('greenhouse', {'resume_attached': True, 'resume_verify': 'ui_confirmed'},
     'good_fit', 'filled_ready', None),
])
def test_cli_uses_review_readback_policy_without_clicking(monkeypatch, platform, overrides, tier, expected, reason):
    fill = {
        'status': 'filled_ready', 'screenshot_path': 'fixture.png',
        'field_verification': 'verified', 'profile_fields_verified': ['first_name', 'email'],
        'resume_attached': True, 'resume_verify': 'files_present',
        'cover_letter_pasted': True, 'cover_letter_verify': 'verified',
        **overrides,
    }
    monkeypatch.setattr(aa, '_init_db', lambda: None)
    monkeypatch.setattr(aa, '_already_applied', lambda fp: False)
    monkeypatch.setattr(aa, '_save_application', lambda *args: None)
    monkeypatch.setattr(aa, '_increment_daily_stat', lambda *args: None)
    monkeypatch.setattr(aa, '_get_daily_auto_submit_count', lambda: 0)
    monkeypatch.setattr(aa, 'classify_tier', lambda job: tier)
    monkeypatch.setattr(aa, 'AUTO_APPLY_CONFIRM', True)
    monkeypatch.setattr(aa, f'_fill_{platform}_form', lambda *args: fill.copy())
    monkeypatch.setitem(sys.modules, 'tools.resume_generator', SimpleNamespace(
        generate_resume_for_job=lambda job: 'synthetic_resume.pdf'))
    monkeypatch.setitem(sys.modules, 'agents.gemini_tools', SimpleNamespace(
        generate_cover_letter=lambda *args, **kwargs: 'Synthetic cover',
        save_cover_letter_pdf=lambda *args, **kwargs: 'synthetic_cover.pdf',
        _load_cv_profile=lambda *args: {},
    ))

    class Browser:
        def new_page(self, **kwargs):
            return SimpleNamespace()  # deliberately exposes no click method
        def close(self):
            pass

    class Playwright:
        def __enter__(self):
            return SimpleNamespace(chromium=SimpleNamespace(launch=lambda **kwargs: Browser()))
        def __exit__(self, *args):
            pass

    monkeypatch.setattr(aa, '_get_playwright', lambda: Playwright)
    host = 'boards.greenhouse.io' if platform == 'greenhouse' else 'jobs.lever.co'
    result = aa.auto_apply({'job_title': 'Fixture', 'company': 'Test',
                            'apply_url': f'https://{host}/example/jobs/1'},
                           mark_sheet=False, open_browser=False, use_playwright=True)
    assert result['status'] == expected
    assert result['playwright_result']['status'] == expected
    if reason:
        assert reason in result['playwright_result']['error']
