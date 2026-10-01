"""Pure submit eligibility checks and structured rejection logging."""

import logging
import re
import unicodedata
from difflib import SequenceMatcher


MATCH_RATIO_THRESHOLD = 0.85
logger = logging.getLogger(__name__)


def normalize_title(value: str) -> str:
    if not isinstance(value, str):
        return ""
    decomposed = unicodedata.normalize("NFKD", value)
    without_marks = "".join(
        char for char in decomposed if not unicodedata.category(char).startswith("M")
    )
    without_punctuation = "".join(
        char
        for char in without_marks.casefold()
        if not unicodedata.category(char).startswith("P")
    )
    return re.sub(r"\s+", " ", without_punctuation).strip()


def validate_confirmation_echo(
    confirm,
    body_fingerprint: str | None,
    path_fingerprint: str,
    actual_ratio: float,
) -> list[dict]:
    """Validate strict confirmation and exact path/body fingerprint equality."""
    checks = []
    if confirm is not True:
        checks.append(("confirmation_required", True, confirm))
    if body_fingerprint != path_fingerprint:
        checks.append(("fingerprint_mismatch", path_fingerprint, body_fingerprint))

    rejections = []
    for reason, expected_value, raw_input in checks:
        logger.warning(
            "Submit rejected: reason=%s actual_ratio=%r expected_value=%r raw_input=%r",
            reason,
            actual_ratio,
            expected_value,
            raw_input,
            extra={
                "actual_ratio": actual_ratio,
                "expected_value": expected_value,
                "raw_input": raw_input,
                "rejection_reason": reason,
            },
        )
        rejections.append(
            {
                "reason": reason,
                "actual_ratio": actual_ratio,
                "expected_value": expected_value,
                "raw_input": raw_input,
            }
        )
    return rejections


def validate_submit_inputs(
    actual_ratio: float,
    expected_title: str,
    raw_title: str,
) -> list[dict]:
    """Return all failed checks and log each with its raw and expected values."""
    rejections = []
    checks = []

    if actual_ratio < MATCH_RATIO_THRESHOLD:
        checks.append(("fit_score", MATCH_RATIO_THRESHOLD, actual_ratio))

    normalized_expected = normalize_title(expected_title)
    normalized_input = normalize_title(raw_title)
    title_ratio = SequenceMatcher(None, normalized_expected, normalized_input).ratio()
    minimum_input_length = max(4, (len(normalized_expected) + 1) // 2)
    if len(normalized_expected) < 4:
        title_matches = normalized_input == normalized_expected
    else:
        title_matches = (
            len(normalized_input) >= minimum_input_length
            and title_ratio >= MATCH_RATIO_THRESHOLD
        )
    if not title_matches:
        checks.append(("title_mismatch", expected_title, raw_title, title_ratio))

    for check in checks:
        reason, expected_value, raw_input = check[:3]
        rejection_ratio = check[3] if len(check) == 4 else actual_ratio
        logger.warning(
            "Submit rejected: reason=%s actual_ratio=%r expected_value=%r raw_input=%r",
            reason,
            rejection_ratio,
            expected_value,
            raw_input,
            extra={
                "actual_ratio": rejection_ratio,
                "expected_value": expected_value,
                "raw_input": raw_input,
                "rejection_reason": reason,
            },
        )
        rejections.append(
            {
                "reason": reason,
                "actual_ratio": rejection_ratio,
                "expected_value": expected_value,
                "raw_input": raw_input,
            }
        )

    return rejections