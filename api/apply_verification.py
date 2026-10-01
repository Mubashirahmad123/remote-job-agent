"""DOM-level confirmation checks used by the future apply submit service."""

from urllib.parse import urlparse


def verify_greenhouse_confirmation(page, confirmation_path: str, confirmation_message: str) -> bool:
    """Require both the configured confirmation URL path and visible copy."""
    actual_path = urlparse(page.url).path.rstrip("/") or "/"
    expected_path = confirmation_path.rstrip("/") or "/"
    if actual_path != expected_path:
        return False
    return confirmation_message in page.locator("body").inner_text()


def verify_lever_confirmation(page) -> bool:
    """Require Lever confirmation visibility and absence of error DOM.

    Exact confirmation copy remains pending the isolated Lever trial observation.
    """
    confirmation_visible = page.locator(".confirmation-message").is_visible()
    error_present = page.locator(
        "[role='alert'], .error, .error-message, .application-error"
    ).count() > 0
    return confirmation_visible and not error_present