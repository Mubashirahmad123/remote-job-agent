"""Read-only diagnostic for Greenhouse confirmation metadata discovery."""

from __future__ import annotations

import argparse
import json
import time
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.request import Request, urlopen

from agents.auto_applier import _get_playwright, _greenhouse_confirmation_data
from tools.url_guard import assert_navigable_url

DEFAULT_URL = "https://job-boards.greenhouse.io/example/jobs/83446"
POLL_SECONDS = 20
POLL_INTERVAL_SECONDS = 0.5


def find_values(value: Any) -> Optional[Tuple[str, str]]:
    if isinstance(value, dict):
        normalized = {
            str(key).replace("_", "").casefold(): item
            for key, item in value.items()
        }
        path = normalized.get("confirmationpath")
        message = normalized.get("confirmationmessage")
        if (
            isinstance(path, str)
            and path.strip()
            and isinstance(message, str)
            and message.strip()
        ):
            return path.strip(), message.strip()
        for child in value.values():
            found = find_values(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = find_values(child)
            if found:
                return found
    elif isinstance(value, str) and value[:1] in "[{":
        try:
            return find_values(json.loads(value))
        except (json.JSONDecodeError, TypeError):
            return None
    return None


class _PageMarkup(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.scripts: List[Dict[str, Any]] = []
        self.data_attributes: List[Tuple[str, str]] = []
        self._script: Optional[Dict[str, Any]] = None

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        attrs_dict = {key: value or "" for key, value in attrs}
        for key, value in attrs_dict.items():
            if key.startswith("data-"):
                self.data_attributes.append((key, value))
        if tag.casefold() == "script":
            script: Dict[str, Any] = {"attrs": attrs_dict, "text": ""}
            self.scripts.append(script)
            self._script = script

    def handle_startendtag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.casefold() == "script":
            self._script = None

    def handle_data(self, data: str) -> None:
        if self._script is not None:
            self._script["text"] += data

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "script":
            self._script = None


def _get_raw_html(url: str) -> str:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=45) as response:
        body = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
    return body.decode(charset, errors="replace")


def _widened_search(page) -> Optional[Tuple[str, str, str]]:
    for index, script in enumerate(
        page.locator("script").evaluate_all(
            "(nodes) => nodes.map((node) => ({text: node.textContent || '', attrs: Array.from(node.attributes, a => [a.name, a.value])}))"
        ),
        1,
    ):
        text = script["text"]
        try:
            found = find_values(json.loads(text))
        except (json.JSONDecodeError, TypeError):
            found = find_values(text)
        if found:
            return f"script[{index}]", found[0], found[1]

    data_attributes = page.locator("*").evaluate_all(
        "(nodes) => nodes.flatMap((node) => Array.from(node.attributes)"
        ".filter((a) => a.name.startsWith('data-'))"
        ".map((a) => [a.name, a.value]))"
    )
    for index, (name, value) in enumerate(data_attributes, 1):
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            continue
        found = find_values(parsed)
        if found:
            return f"data-attribute[{index}] {name}", found[0], found[1]
    return None


def _confirmation_contexts(label: str, html: str) -> None:
    print(f"Confirmation matches in {label}:")
    lower_html = html.casefold()
    start = 0
    matches = 0
    while True:
        index = lower_html.find("confirmation", start)
        if index < 0:
            break
        left = max(0, index - 100)
        right = min(len(html), index + len("confirmation") + 120)
        print(f"  offset {index}: {html[left:right]!r}")
        matches += 1
        start = index + len("confirmation")
    if not matches:
        print("  no matches")


def _describe_html(label: str, html: str, output_path: Path) -> _PageMarkup:
    output_path.write_text(html, encoding="utf-8")
    parser = _PageMarkup()
    parser.feed(html)
    print(f"{label} saved: {output_path} ({output_path.stat().st_size} bytes)")
    print(f"{label} script tags ({len(parser.scripts)}):")
    for index, script in enumerate(parser.scripts, 1):
        attrs = script["attrs"]
        data_attrs = {
            key: value for key, value in attrs.items() if key.startswith("data-")
        }
        preview = " ".join(script["text"].split())[:120]
        print(
            f"  {index}: type={attrs.get('type')!r}, id={attrs.get('id')!r}, "
            f"data={data_attrs!r}, text={preview!r}"
        )
    return parser


def run(url: str, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    assert_navigable_url(url, resolve=True)
    raw_html = _get_raw_html(url)
    _describe_html("Raw HTTP HTML", raw_html, output_dir / "raw.html")
    _confirmation_contexts("raw HTTP HTML", raw_html)

    sync_playwright = _get_playwright()
    if sync_playwright is None:
        raise RuntimeError("Playwright is unavailable; install Playwright and Chromium.")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            started = time.monotonic()
            narrow_result = _greenhouse_confirmation_data(page)
            widened_result = _widened_search(page)
            first_seen: Optional[float] = (
                0.0 if narrow_result.get("confirmation_path") or widened_result else None
            )
            while first_seen is None and time.monotonic() - started < POLL_SECONDS:
                page.wait_for_timeout(int(POLL_INTERVAL_SECONDS * 1000))
                narrow_result = _greenhouse_confirmation_data(page)
                widened_result = _widened_search(page)
                if narrow_result.get("confirmation_path") or widened_result:
                    first_seen = time.monotonic() - started

            print(f"Poll duration: {time.monotonic() - started:.2f}s")
            print(f"First metadata observation: {first_seen!r} seconds after domcontentloaded")
            print(f"Narrow extractor result: {narrow_result!r}")
            print(f"Widened search result: {widened_result!r}")

            rendered_html = page.content()
            _describe_html("Rendered HTML", rendered_html, output_dir / "rendered.html")
            _confirmation_contexts("rendered HTML", rendered_html)
        finally:
            browser.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("scratch/confirmation-metadata-probe"),
    )
    args = parser.parse_args()
    run(args.url, args.output_dir)


if __name__ == "__main__":
    main()
