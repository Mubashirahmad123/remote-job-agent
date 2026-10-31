"""Opt-in, offline Playwright checks of actual DOM replacement and file inputs.

The normal unit suite needs no browser. Docker CI opts in using its installed
Chromium; developers can run RUN_OFFLINE_BROWSER_TESTS=1 with Playwright's
Chromium installed. All navigations are intercepted and served from the local
synthetic fixture: no Greenhouse request or application submission is made.
"""
import os
from pathlib import Path

import pytest

from agents import auto_applier as aa

FIXTURE = Path(__file__).parent / "fixtures" / "greenhouse_attachment_form.html"
JOB_URL = "https://boards.greenhouse.io/example/jobs/83446"
PROFILE = {"name": "Test Applicant", "email": "test@example.invalid", "phone": "5550100100"}


@pytest.fixture(scope="module")
def browser():
    if os.getenv("RUN_OFFLINE_BROWSER_TESTS") != "1":
        pytest.skip("Set RUN_OFFLINE_BROWSER_TESTS=1 to run the offline Chromium fixture")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        options = {"headless": True}
        custom = os.getenv("TEST_CHROMIUM_EXECUTABLE")
        if custom:
            options["executable_path"] = custom
        instance = playwright.chromium.launch(**options)
        yield instance
        instance.close()


@pytest.fixture
def page(browser):
    context = browser.new_context()
    page = context.new_page()
    yield page
    context.close()


@pytest.mark.parametrize("mode,expected", [
    ("native", "files_present"),
    ("remount", "ui_confirmed"),
    ("drop", "unavailable"),
    ("ambiguous", "ambiguous_input"),
    ("wipe", "files_present"),
    ("wipe_clears_files", "empty_after_set"),
])
def test_greenhouse_fill_uses_fresh_dom_and_never_submits(page, monkeypatch, tmp_path, mode, expected):
    # Route ALL network through the fixture and bypass DNS-only URL checking;
    # neither the posting nor any third party is contacted.
    html = FIXTURE.read_text(encoding="utf-8")
    page.route("**/*", lambda route: route.fulfill(status=200, content_type="text/html", body=html))
    page.add_init_script(f"window.fixtureMode = {mode!r};")
    monkeypatch.setattr(aa, "assert_navigable_url", lambda *args, **kwargs: None)
    monkeypatch.chdir(tmp_path)
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4 synthetic")

    result = aa._fill_greenhouse_form(page, JOB_URL, str(resume), "Synthetic cover text", PROFILE)
    assert result["status"] == "filled_ready"
    assert result["field_verification"] in {"verified", "repaired"}
    assert result["resume_verify"] == expected
    assert result["resume_attached"] is (expected in {"files_present", "ui_confirmed"})
    if mode in {"native", "remount", "wipe"}:
        assert result["cover_letter_verify"] == expected
        assert result["cover_letter_attached"] is True
    if mode in {"wipe", "wipe_clears_files"}:
        assert result["field_verification"] == "repaired"
        assert page.locator("#first_name").input_value() == "Test"
    if mode == "wipe_clears_files":
        assert result["cover_letter_verify"] == "empty_after_set"
        assert result["cover_letter_attached"] is False
    if mode == "drop":
        assert result["cover_letter_verify"] == "unavailable"
        assert result["cover_letter_attached"] is False
    assert Path(result["screenshot_path"]).read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert page.evaluate("window.submitClicks") == 0


def test_other_field_or_hidden_chip_does_not_prove_resume_attachment(page):
    page.set_content("""<form>
      <section><label for="resume">Resume/CV</label><input id="resume" type="file">
        <div hidden><span>resume.pdf</span><button type="button">Remove file</button></div>
        <div style="opacity:0"><span>resume.pdf</span><button type="button">Remove file</button></div>
      </section>
      <section><label for="cover_letter">Cover Letter</label>
        <span>resume.pdf</span><button type="button">Remove file</button>
      </section>
    </form>""")
    state, chip = aa._verify_file_attachment(page, aa._GH_RESUME_INPUT_SELECTOR,
                                              "resume.pdf", kind="resume", allow_chip=True)
    assert (state, chip) == ("empty_after_set", False)


def test_native_file_with_wrong_name_is_not_verified(page, tmp_path):
    page.set_content('<form><label for="resume">Resume</label><input id="resume" type="file"></form>')
    wrong = tmp_path / "other.pdf"
    wrong.write_bytes(b"wrong")
    page.locator("#resume").set_input_files(str(wrong))
    state, chip = aa._verify_file_attachment(page, aa._GH_RESUME_INPUT_SELECTOR,
                                              "resume.pdf", kind="resume", allow_chip=True)
    assert (state, chip) == ("file_mismatch", False)


def test_native_file_with_same_name_but_wrong_size_is_not_verified(page, tmp_path):
    page.set_content('<form><label for="resume">Resume</label><input id="resume" type="file"></form>')
    resume = tmp_path / 'resume.pdf'
    resume.write_bytes(b'wrong bytes')
    page.locator('#resume').set_input_files(str(resume))
    state, chip = aa._verify_file_attachment(
        page, aa._GH_RESUME_INPUT_SELECTOR, 'resume.pdf', kind='resume',
        expected_size=500, allow_chip=True,
    )
    assert (state, chip) == ('file_mismatch', False)


@pytest.mark.parametrize('truncate,expected', [(False, 'verified'), (True, 'mismatch')])
def test_lever_resume_and_full_cover_text_are_read_back(page, monkeypatch, tmp_path, truncate, expected):
    html = '''<form class="application-form">
      <input name="firstName"><input name="lastName"><input type="email"><input type="tel">
      <input type="file" name="resume"><textarea name="cover"></textarea>
      <button type="submit">Submit</button>
    </form><script>
      window.submitClicks = 0;
      document.querySelector('form').addEventListener('submit', e => { e.preventDefault(); window.submitClicks++; });
      if (window.truncateCover) {
        document.querySelector('textarea').addEventListener('input', event => {
          setTimeout(() => { event.target.value = event.target.value.slice(0, 120); }, 50);
        });
      }
    </script>'''
    page.route('**/*', lambda route: route.fulfill(status=200, content_type='text/html', body=html))
    page.add_init_script(f'window.truncateCover = {str(truncate).lower()};')
    monkeypatch.setattr(aa, 'assert_navigable_url', lambda *args, **kwargs: None)
    monkeypatch.chdir(tmp_path)
    resume = tmp_path / 'resume.pdf'
    resume.write_bytes(b'%PDF-1.4 synthetic')
    cover = 'A' * 120 + ' the rest of the letter must not disappear'
    result = aa._fill_lever_form(page, 'https://jobs.lever.co/example/role/apply',
                                 str(resume), cover, PROFILE)
    assert result['status'] == 'filled_ready'
    assert result['resume_verify'] == 'files_present'
    assert result['resume_attached'] is True
    assert result['cover_letter_verify'] == expected
    assert result['cover_letter_pasted'] is (expected == 'verified')
    assert page.evaluate('window.submitClicks') == 0


def test_input_becoming_ambiguous_after_selection_is_rejected(page, tmp_path):
    page.set_content(FIXTURE.read_text(encoding='utf-8'))
    resume = tmp_path / 'tailored_resume.pdf'
    resume.write_bytes(b'%PDF-1.4 synthetic')
    selector = aa._GH_RESUME_INPUT_SELECTOR
    page.locator(selector).set_input_files(str(resume))
    page.evaluate("""() => {
      const upload = document.querySelector('#resume-field .upload');
      const second = document.createElement('input');
      second.type = 'file'; second.id = 'resume-extra';
      const chip = document.createElement('span'); chip.textContent = 'tailored_resume.pdf';
      const remove = document.createElement('button'); remove.type = 'button'; remove.textContent = 'Remove file';
      upload.append(second, chip, remove);
    }""")
    state, chip = aa._verify_file_attachment(
        page, selector, resume.name, kind='resume', allow_chip=True,
        expected_size=resume.stat().st_size,
    )
    assert (state, chip) == ('ambiguous_input', False)
    assert page.evaluate('window.submitClicks') == 0


def test_delayed_input_clear_cannot_pass_a_single_successful_read(page, tmp_path):
    page.set_content('<form><label for="resume">Resume</label><input id="resume" type="file"></form>')
    resume = tmp_path / 'resume.pdf'
    resume.write_bytes(b'%PDF-1.4 synthetic')
    page.locator('#resume').set_input_files(str(resume))
    page.evaluate("() => setTimeout(() => { document.querySelector('#resume').value = ''; }, 150)")
    state, chip = aa._verify_file_attachment(
        page, aa._GH_RESUME_INPUT_SELECTOR, resume.name, kind='resume',
        expected_size=resume.stat().st_size,
    )
    assert (state, chip) == ('empty_after_set', False)


def test_profile_wipe_during_attachment_checks_is_not_reported_verified(page, monkeypatch, tmp_path):
    html = FIXTURE.read_text(encoding='utf-8')
    page.route('**/*', lambda route: route.fulfill(status=200, content_type='text/html', body=html))
    monkeypatch.setattr(aa, 'assert_navigable_url', lambda *args, **kwargs: None)
    original_verify = aa._verify_file_attachment

    def verify_then_remount_profile(*args, **kwargs):
        observed = original_verify(*args, **kwargs)
        if kwargs['kind'] == 'cover':
            page.evaluate("() => { document.querySelector('#first_name').value = ''; }")
        return observed

    # Simulate a delayed render precisely between cover verification and the
    # final profile readback, without wall-clock race assumptions in CI.
    monkeypatch.setattr(aa, '_verify_file_attachment', verify_then_remount_profile)
    monkeypatch.chdir(tmp_path)
    resume = tmp_path / 'resume.pdf'
    resume.write_bytes(b'%PDF-1.4 synthetic')
    result = aa._fill_greenhouse_form(page, JOB_URL, str(resume), 'Synthetic cover text', PROFILE)
    assert result['field_verification'] == 'mismatch'
    assert result['profile_fields_verified'] == []
    assert page.evaluate('window.submitClicks') == 0


def test_greenhouse_cover_text_is_rechecked_after_upload_settles(page, monkeypatch, tmp_path):
    html = '''<form>
      <input id="first_name"><input id="last_name"><input id="email"><input id="phone">
      <input id="resume" type="file"><textarea name="cover"></textarea>
      <button type="submit">Submit</button>
    </form><script>
      window.submitClicks = 0;
      document.querySelector('form').addEventListener('submit', e => { e.preventDefault(); window.submitClicks++; });
    </script>'''
    page.route('**/*', lambda route: route.fulfill(status=200, content_type='text/html', body=html))
    monkeypatch.setattr(aa, 'assert_navigable_url', lambda *args, **kwargs: None)
    original_verify = aa._verify_file_attachment

    def verify_then_remount_cover(*args, **kwargs):
        observed = original_verify(*args, **kwargs)
        if kwargs['kind'] == 'resume':
            page.evaluate("() => { document.querySelector('textarea').value = ''; }")
        return observed

    monkeypatch.setattr(aa, '_verify_file_attachment', verify_then_remount_cover)
    monkeypatch.chdir(tmp_path)
    resume = tmp_path / 'resume.pdf'
    resume.write_bytes(b'%PDF-1.4 synthetic')
    result = aa._fill_greenhouse_form(page, JOB_URL, str(resume), 'Synthetic cover text', PROFILE)
    assert result['cover_letter_verify'] == 'mismatch'
    assert result['cover_letter_pasted'] is False
    assert page.evaluate('window.submitClicks') == 0
