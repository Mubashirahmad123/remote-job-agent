"""Stage 0 recon: inspect Greenhouse postings without filling or clicking.

Why this exists separately from the dry run in `api/apply.py`: that dry run
needs a cached job, a completed fill/review, and an issued intent, so it can
only rehearse postings that are already in the pipeline. This scans *any*
URL in seconds and answers the cheap questions first:

  - Is the confirmation metadata that `verify_greenhouse_confirmation()`
    depends on actually discoverable on this page? If it is not, `/intent`
    will 502 and a live submit is impossible — worth knowing before
    arranging anything else.
  - Which fields does the form mark required? `_fill_greenhouse_form` only
    knows name/email/phone/resume/cover/linkedin/website. Anything else
    marked required will fail validation *after* the click, which looks
    identical to a verification bug.
  - Is there a captcha between the button and the submission?

Nothing here types, uploads, or clicks. Read-only.

Usage:
    python -m tools.submit_recon https://job-boards.greenhouse.io/example/jobs/83446
    python -m tools.submit_recon --file urls.txt --json recon.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

from tools.url_guard import assert_navigable_url

# Fields the existing Greenhouse filler knows how to populate. Anything
# required and outside this set is an unhandled required question.
KNOWN_FIELDS = {
    "first_name",
    "last_name",
    "full_name",
    "name",
    "email",
    "phone",
    "resume",
    "cv",
    "cover_letter",
    "linkedin",
    "website",
    "portfolio",
}

CAPTCHA_SELECTORS = {
    "recaptcha": "iframe[src*='recaptcha'], .g-recaptcha, [data-sitekey]",
    "hcaptcha": "iframe[src*='hcaptcha'], .h-captcha",
    "turnstile": "iframe[src*='challenges.cloudflare.com'], .cf-turnstile",
}


def _looks_known(label: str) -> bool:
    slug = "".join(ch if ch.isalnum() else "_" for ch in label.lower())
    return any(known in slug for known in KNOWN_FIELDS)


def _required_fields(page) -> List[str]:
    """Collect visible required field labels.

    Greenhouse marks required fields both with `aria-required`/`required` and
    with a `*` in the label, so both are checked; duplicates collapse.
    """
    labels: List[str] = []
    try:
        nodes = page.locator(
            "[aria-required='true'], [required], label:has-text('*')"
        ).all()
    except Exception:
        return labels
    for node in nodes:
        for getter in (
            lambda n: n.get_attribute("aria-label"),
            lambda n: n.get_attribute("name"),
            lambda n: n.inner_text(),
        ):
            try:
                value = (getter(node) or "").strip().replace("\n", " ")
            except Exception:
                value = ""
            if value:
                labels.append(value[:80])
                break
    seen, unique = set(), []
    for label in labels:
        key = label.lower()
        if key not in seen:
            seen.add(key)
            unique.append(label)
    return unique


def inspect_posting(page, url: str) -> Dict[str, Any]:
    from agents.auto_applier import _greenhouse_confirmation_data

    report: Dict[str, Any] = {"url": url}
    # URLs here come from argv or a --file list, so they are operator-supplied
    # rather than scraped — but this is still a browser sink pointed at an
    # arbitrary string, and run() already records a rejected URL as an error.
    assert_navigable_url(url, resolve=True)
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    try:
        page.wait_for_timeout(2500)  # let client-rendered forms settle
    except Exception:
        pass

    report["title"] = (page.title() or "").strip()

    metadata = _greenhouse_confirmation_data(page)
    report["confirmation_path"] = metadata.get("confirmation_path")
    report["confirmation_message"] = metadata.get("confirmation_message")
    report["confirmation_metadata_found"] = bool(
        metadata.get("confirmation_path") and metadata.get("confirmation_message")
    )

    captchas = []
    for kind, selector in CAPTCHA_SELECTORS.items():
        try:
            if page.locator(selector).count() > 0:
                captchas.append(kind)
        except Exception:
            continue
    report["captcha"] = captchas

    try:
        report["submit_button_found"] = (
            page.locator("input[type='submit'], button[type='submit'], #submit_app").count() > 0
        )
    except Exception:
        report["submit_button_found"] = False

    required = _required_fields(page)
    report["required_fields"] = required
    report["unhandled_required_fields"] = [f for f in required if not _looks_known(f)]

    # The verdict is advisory. It says whether a live attempt is worth
    # arranging, never whether one is safe — that stays an operator call.
    blockers = []
    if not report["confirmation_metadata_found"]:
        blockers.append("no confirmation metadata (intent will 502)")
    if not report["submit_button_found"]:
        blockers.append("no submit button found")
    if report["unhandled_required_fields"]:
        blockers.append(
            f"{len(report['unhandled_required_fields'])} unhandled required field(s)"
        )
    if captchas:
        blockers.append(f"captcha present ({', '.join(captchas)})")
    report["blockers"] = blockers
    report["verdict"] = "clear" if not blockers else "blocked"
    return report


def run(urls: List[str], headless: bool = True) -> List[Dict[str, Any]]:
    from agents.auto_applier import _get_playwright

    sync_playwright = _get_playwright()
    if sync_playwright is None:
        raise SystemExit("Playwright is not installed — run: pip install playwright && playwright install chromium")

    reports: List[Dict[str, Any]] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        page = context.new_page()
        for url in urls:
            try:
                reports.append(inspect_posting(page, url))
            except Exception as error:
                reports.append({"url": url, "verdict": "error", "error": str(error)})
        context.close()
        browser.close()
    return reports


def _print(reports: List[Dict[str, Any]]) -> None:
    for report in reports:
        mark = {"clear": "OK  ", "blocked": "WARN", "error": "ERR "}.get(report.get("verdict"), "?   ")
        print(f"\n{mark} {report['url']}")
        if report.get("error"):
            print(f"       error: {report['error']}")
            continue
        print(f"       title:        {report.get('title')}")
        print(f"       confirmation: {report.get('confirmation_path')!r} / {report.get('confirmation_message')!r}")
        print(f"       submit button: {report.get('submit_button_found')}")
        print(f"       captcha:      {report.get('captcha') or 'none detected'}")
        print(f"       required:     {report.get('required_fields')}")
        if report.get("unhandled_required_fields"):
            print(f"       UNHANDLED:    {report['unhandled_required_fields']}")
        if report.get("blockers"):
            print(f"       blockers:     {'; '.join(report['blockers'])}")

    total = len(reports)
    clear = sum(1 for r in reports if r.get("verdict") == "clear")
    print(f"\n{clear}/{total} posting(s) clear of known blockers.")


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only Greenhouse submit-path recon (never clicks).")
    parser.add_argument("urls", nargs="*", help="Greenhouse posting URLs")
    parser.add_argument("--file", help="File with one URL per line")
    parser.add_argument("--json", dest="json_out", help="Write the full report to this JSON path")
    parser.add_argument("--headed", action="store_true", help="Show the browser")
    args = parser.parse_args(argv)

    urls = list(args.urls)
    if args.file:
        urls += [line.strip() for line in Path(args.file).read_text(encoding="utf-8").splitlines() if line.strip()]
    if not urls:
        parser.error("give at least one URL or --file")

    reports = run(urls, headless=not args.headed)
    _print(reports)
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(reports, indent=2), encoding="utf-8")
        print(f"\nFull report: {args.json_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
