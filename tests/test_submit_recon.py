"""Recon scanner logic (`tools/submit_recon.py`) — no browser required.

The scanner's value is its verdict, so the verdict logic is what gets
tested: a posting is only "clear" when the confirmation metadata exists,
the submit control exists, every required field is one the filler knows,
and no captcha stands in the way. Each of those four must independently be
able to block.
"""

import pytest

from tools import submit_recon


class _FakeNode:
    def __init__(self, text="", name=None, aria=None):
        self._text, self._name, self._aria = text, name, aria

    def get_attribute(self, key):
        return {"name": self._name, "aria-label": self._aria}.get(key)

    def inner_text(self):
        return self._text


class _FakeLocator:
    def __init__(self, nodes=None, count=0):
        self._nodes, self._count = nodes or [], count

    def all(self):
        return self._nodes

    def count(self):
        return self._count


class _FakePage:
    """Selector-routed page double."""

    def __init__(self, *, required=(), captcha=None, submit=True):
        self._required = [_FakeNode(text=label) for label in required]
        self._captcha = captcha
        self._submit = submit

    def goto(self, *_args, **_kwargs):
        return None

    def wait_for_timeout(self, *_args):
        return None

    def title(self):
        return "Job Application for Full Stack Engineer at Democorp"

    def locator(self, selector):
        if "aria-required" in selector:
            return _FakeLocator(nodes=self._required)
        for kind, sel in submit_recon.CAPTCHA_SELECTORS.items():
            if selector == sel:
                return _FakeLocator(count=1 if self._captcha == kind else 0)
        if "submit" in selector:
            return _FakeLocator(count=1 if self._submit else 0)
        return _FakeLocator()


@pytest.fixture()
def metadata_found(monkeypatch):
    import agents.auto_applier as aa

    monkeypatch.setattr(
        aa,
        "_greenhouse_confirmation_data",
        lambda _page: {
            "confirmation_path": "/confirmation/received",
            "confirmation_message": "Thank you for applying",
        },
    )


class TestKnownFieldDetection:
    @pytest.mark.parametrize(
        "label",
        ["First Name*", "Last Name *", "Email*", "Resume/CV", "LinkedIn Profile", "Phone"],
    )
    def test_fields_the_filler_handles(self, label):
        assert submit_recon._looks_known(label) is True

    @pytest.mark.parametrize(
        "label",
        [
            "Are you authorized to work in the US?*",
            "Why do you want to work here?*",
            "Desired salary*",
            "Gender",
        ],
    )
    def test_fields_the_filler_does_not_handle(self, label):
        assert submit_recon._looks_known(label) is False


class TestVerdict:
    def test_clear_posting(self, metadata_found):
        page = _FakePage(required=["First Name*", "Last Name*", "Email*"])
        report = submit_recon.inspect_posting(page, "https://example.test/jobs/1")
        assert report["verdict"] == "clear"
        assert report["blockers"] == []
        assert report["confirmation_metadata_found"] is True

    def test_captcha_blocks(self, metadata_found):
        page = _FakePage(required=["Email*"], captcha="recaptcha")
        report = submit_recon.inspect_posting(page, "https://example.test/jobs/2")
        assert report["verdict"] == "blocked"
        assert report["captcha"] == ["recaptcha"]
        assert any("captcha" in blocker for blocker in report["blockers"])

    def test_unhandled_required_question_blocks(self, metadata_found):
        page = _FakePage(required=["Email*", "Are you authorized to work in the US?*"])
        report = submit_recon.inspect_posting(page, "https://example.test/jobs/3")
        assert report["verdict"] == "blocked"
        assert report["unhandled_required_fields"] == ["Are you authorized to work in the US?*"]

    def test_missing_confirmation_metadata_blocks(self, monkeypatch):
        import agents.auto_applier as aa

        monkeypatch.setattr(
            aa,
            "_greenhouse_confirmation_data",
            lambda _page: {"confirmation_path": None, "confirmation_message": None},
        )
        page = _FakePage(required=["Email*"])
        report = submit_recon.inspect_posting(page, "https://example.test/jobs/4")
        assert report["verdict"] == "blocked"
        assert any("502" in blocker for blocker in report["blockers"])

    def test_missing_submit_button_blocks(self, metadata_found):
        page = _FakePage(required=["Email*"], submit=False)
        report = submit_recon.inspect_posting(page, "https://example.test/jobs/5")
        assert report["submit_button_found"] is False
        assert report["verdict"] == "blocked"


class TestScannerNeverActs:
    def test_recon_module_contains_no_click_or_fill_calls(self):
        """A read-only tool must stay read-only."""
        source = (submit_recon.__file__ and open(submit_recon.__file__, encoding="utf-8").read()) or ""
        body = source.split('"""', 2)[-1]  # ignore the module docstring
        for forbidden in (".click(", ".fill(", ".set_input_files(", ".type("):
            assert forbidden not in body, f"recon scanner must never call {forbidden}"
