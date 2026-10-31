"""Offline attachment-state contracts and transient DOM readback failures."""
import logging

import pytest

from agents.auto_applier import _cover_text_matches, _find_file_input, _verify_file_attachment


class FakePage:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.args = []
        self.waits = []

    def evaluate(self, _script, argument):
        self.args.append(argument)
        value = next(self.responses)
        if isinstance(value, Exception):
            raise value
        return value

    def wait_for_timeout(self, ms):
        self.waits.append(ms)


def test_fresh_dom_readback_retries_a_detached_locator_then_finds_chip(caplog):
    page = FakePage([RuntimeError("detached during rerender"),
                     {"inputMatch": False, "inputCount": 0, "chipMatch": True},
                     {"inputMatch": False, "inputCount": 0, "chipMatch": True}])
    with caplog.at_level(logging.DEBUG, logger="agents.auto_applier"):
        state, chip = _verify_file_attachment(page, "input#resume", "resume.pdf",
                                              kind="resume", allow_chip=True)
    assert (state, chip) == ("ui_confirmed", True)
    assert len(page.waits) == 2
    assert page.args[-1] == {"selector": "input#resume", "filename": "resume.pdf",
                             "expectedSize": None, "kind": "resume", "allowChip": True}
    assert any(record.exc_info for record in caplog.records)


def test_present_input_requires_exact_name_from_dom_and_takes_precedence_over_chip():
    page = FakePage([{"inputMatch": True, "inputCount": 1, "chipMatch": True}] * 2)
    assert _verify_file_attachment(page, "input#resume", "expected.pdf", kind="resume", allow_chip=True) == (
        "files_present", True
    )
    assert page.waits == [400]


def test_a_single_transient_file_observation_is_not_accepted():
    page = FakePage([
        {"inputMatch": True, "inputCount": 1, "chipMatch": False},
        *[{"inputMatch": False, "inputCount": 1, "chipMatch": False}] * 4,
    ])
    assert _verify_file_attachment(page, "input#resume", "resume.pdf", kind="resume") == (
        "empty_after_set", False
    )


@pytest.mark.parametrize("observation,expected", [
    ({"inputMatch": False, "inputCount": 1, "chipMatch": False}, "empty_after_set"),
    ({"inputMatch": False, "inputCount": 0, "chipMatch": False}, "unavailable"),
    ({"inputMatch": False, "inputHasFiles": True, "inputCount": 1, "chipMatch": True}, "file_mismatch"),
    ({"inputMatch": False, "inputHasFiles": True, "inputCount": 2, "chipMatch": True}, "ambiguous_input"),
    ({"inputMatch": 1, "inputCount": 1, "chipMatch": 1}, "empty_after_set"),
    (None, "unavailable"),
    (RuntimeError("readback failed"), "unavailable"),
])
def test_unverified_readback_never_claims_attached(observation, expected):
    page = FakePage([observation] * 5)
    state, chip = _verify_file_attachment(page, "input#resume", "resume.pdf", kind="resume", allow_chip=True)
    assert state == expected
    assert chip is False
    assert len(page.waits) == 4


def test_cover_text_comparison_rejects_truncation_even_after_120_characters():
    cover = "x" * 120 + " the important remaining text"
    assert not _cover_text_matches(cover[:120], cover)
    assert _cover_text_matches("first\nsecond\n", "first\r\nsecond\r\n")
    assert not _cover_text_matches(None, cover)


def test_ambiguous_file_inputs_are_not_silently_selected():
    from agents.auto_applier import _AmbiguousFileInput

    class Locator:
        def count(self):
            return 2

    class Page:
        def locator(self, _selector):
            return Locator()

    with pytest.raises(_AmbiguousFileInput):
        _find_file_input(Page(), "input[type=file]")
