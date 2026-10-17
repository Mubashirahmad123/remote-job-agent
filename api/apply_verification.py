"""DOM-level confirmation checks used by the future apply submit service."""

import html
import re
from urllib.parse import urlparse


def _normalize_confirmation_text(value: str) -> str:
    text = re.sub(r"<[^>]*>", " ", value)
    return " ".join(html.unescape(text).split())


def verify_greenhouse_confirmation(page, confirmation_path: str, confirmation_message: str) -> bool:
    """Require both the configured confirmation URL path and visible copy."""
    actual_path = urlparse(page.url).path.rstrip("/") or "/"
    expected_path = confirmation_path.rstrip("/") or "/"
    if actual_path != expected_path:
        return False
    expected_message = _normalize_confirmation_text(confirmation_message)
    if not expected_message:
        return False
    actual_message = _normalize_confirmation_text(page.locator("body").inner_text())
    return expected_message in actual_message


def verify_lever_confirmation(page) -> bool:
    """Require Lever confirmation visibility and absence of error DOM.

    Exact confirmation copy remains pending the isolated Lever trial observation.
    """
    confirmation_visible = page.locator(".confirmation-message").is_visible()
    error_present = page.locator(
        "[role='alert'], .error, .error-message, .application-error"
    ).count() > 0
    return confirmation_visible and not error_present