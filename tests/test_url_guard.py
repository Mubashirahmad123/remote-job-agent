"""The server must never aim a browser at a URL it has not vetted (H3).

`apply_url` flows from a job row into `page.goto()` inside a container that runs
as root with `./.env` and `./keys.json` mounted, and `api/apply.py` stores a
screenshot of whatever rendered — which `GET /api/apply/{fingerprint}/screenshot`
then returns to any authenticated caller. Before tools/url_guard.py existed the
only validation anywhere on that path was `Field(min_length=1)`.

Confirmed by probe against a live server: `POST /api/tracker` accepted
`apply_url = "javascript:alert(1)"` and `"file:///etc/passwd"`. Both failed
later, on an unrelated Sheets error — that is, after validation had already
passed them.

The rows do not have to come from an authenticated user. They come from scraped
postings, so a hostile listing on any board can supply one, and while the
scraper was disabling TLS verification on retry (H2) an on-path attacker could
inject one into any board at all.

Coverage here is three layers:

  1. the guard's own decision table, including the obfuscation shapes used to
     walk past a naive prefix check;
  2. the wiring — an AST scan proving every non-constant `page.goto()` and
     `webbrowser.open()` in the codebase is preceded by a guard in the same
     function, so adding a new sink without one fails the build;
  3. the API boundary, proving a rejected URL is a 422 and not a stored row.
"""

import ast
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.schemas import TrackerCreate
from tools import url_guard
from tools.url_guard import (
    UrlRejected,
    assert_navigable_url,
    check_navigable_url,
    is_navigable_url,
)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {".venv", "venv", "node_modules", ".git", "__pycache__", "tests"}


def _python_files():
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            if name.endswith(".py"):
                yield os.path.join(root, name)


# --- 1. the decision table ---------------------------------------------------

# Everything here was reachable before the guard. Each entry is a real
# destination an attacker would pick, not a synthetic edge case.
BLOCKED = [
    # non-web schemes a browser will happily honour from page.goto()
    "file:///etc/passwd",
    "file:///app/.env",
    "file:///app/keys.json",
    "javascript:alert(1)",
    "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==",
    "vbscript:msgbox(1)",
    "gopher://127.0.0.1:6379/_INFO",
    "dict://internal:6379/info",
    "ftp://internal-host/",
    # case and whitespace obfuscation of the scheme check
    "JaVaScRiPt:alert(1)",
    "FILE:///etc/passwd",
    "  file:///etc/passwd",
    "java\tscript:alert(1)",
    "file\n:///etc/passwd",
    # cloud metadata and the loopback API
    "http://169.254.169.254/latest/meta-data/",
    "http://[fd00:ec2::254]/",
    "http://metadata.google.internal/computeMetadata/v1/",
    "http://127.0.0.1/api/jobs",
    "http://localhost/x",
    "http://LOCALHOST/x",
    "http://[::1]/",
    # RFC1918, CGNAT and the other non-public ranges
    "http://10.0.0.5/",
    "http://192.168.1.1/",
    "http://172.16.0.1/",
    "http://100.64.0.1/",
    "http://100.127.255.254/",
    "http://0.0.0.0/",
    "http://224.0.0.1/",
    "http://240.0.0.1/",
    "http://192.88.99.1/",
    "http://[fc00::1]/",
    "http://[fe80::1]/",
    # IPv4-mapped IPv6, the classic way to smuggle a blocked v4 past v6 checks
    "http://[::ffff:127.0.0.1]/",
    "http://[::ffff:169.254.169.254]/",
    "http://[::ffff:100.64.0.1]/",
    # internal service ports, even on a public-looking hostname
    "http://evil.example:6379/",
    "http://evil.example:22/",
    "http://evil.example:5432/",
    "http://127.0.0.1:8000/api/jobs",
    # credential confusion: urlparse reports hostname=evil.example here
    "http://trusted.example@evil.example/",
    "http://user:pass@10.0.0.1/",
    # non-routable name namespaces
    "http://printer.local/",
    "http://db.corp/",
    "http://nas.lan/",
    "http://intranet.intranet/",
    # not URLs at all
    "",
    "   ",
    "not a url",
    "//evil.example/x",
    "/relative/path",
]

NON_STRINGS = [None, 42, 3.5, b"https://example.com/", object(), ["https://example.com/"]]

ALLOWED = [
    "https://boards.greenhouse.io/acme/jobs/123",
    "https://jobs.lever.co/company/uuid",
    "http://example.com/jobs/1",
    "https://example.com:443/x",
    "http://example.com:80/x",
    "https://sub.domain.co.uk/a/b?c=d&e=f#frag",
    "https://93.184.216.34/jobs/1",
    "https://example.com/",
]


@pytest.mark.parametrize("url", BLOCKED)
def test_blocked(url):
    reason = check_navigable_url(url)
    assert reason, f"{url!r} was allowed; this is the SSRF / local-file-read hole"


@pytest.mark.parametrize("url", ALLOWED)
def test_allowed(url):
    reason = check_navigable_url(url)
    assert not reason, f"{url!r} was rejected: {reason}"


@pytest.mark.parametrize("value", NON_STRINGS)
def test_non_strings_are_rejected(value):
    assert check_navigable_url(value), f"{value!r} should not be navigable"


def test_the_cgnat_gap_is_closed():
    """100.64.0.0/10 is not `is_private` on Python 3.11 and is exactly the range
    cloud providers use for their internal fabric. Found by probing the guard
    itself; pinned so a stdlib change cannot silently reopen it."""
    assert check_navigable_url("http://100.64.0.1/")
    assert check_navigable_url("http://100.127.255.254/")
    assert not check_navigable_url("http://8.8.8.8/"), "a public address must stay reachable"


def test_assert_raises_with_a_readable_reason():
    with pytest.raises(UrlRejected) as exc:
        assert_navigable_url("file:///app/keys.json")
    assert "scheme" in str(exc.value)
    assert exc.value.url == "file:///app/keys.json"
    # A ValueError subclass, so the existing per-job `except Exception` handlers
    # around the browser paths turn one poisoned row into a skip, not a crash.
    assert isinstance(exc.value, ValueError)


def test_assert_returns_the_url_so_it_can_be_used_inline():
    assert assert_navigable_url("https://example.com/jobs/1") == "https://example.com/jobs/1"


# --- resolve=True ------------------------------------------------------------


def test_resolve_rejects_a_public_hostname_pointing_at_metadata(monkeypatch):
    """The case syntax checking cannot catch: a normal-looking domain whose A
    record is the metadata service."""
    monkeypatch.setattr(
        url_guard.socket,
        "getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("169.254.169.254", 80))],
    )
    assert not check_navigable_url("http://attacker.example/", resolve=False), (
        "without resolution this is (correctly) indistinguishable from a real board"
    )
    reason = check_navigable_url("http://attacker.example/", resolve=True)
    assert "link-local" in reason or "169.254.169.254" in reason, reason


def test_resolve_rejects_when_only_one_of_several_records_is_internal(monkeypatch):
    """A multi-homed host is public if ANY address is internal — checking only
    the first record would be trivially bypassed."""
    monkeypatch.setattr(
        url_guard.socket,
        "getaddrinfo",
        lambda *a, **k: [
            (2, 1, 6, "", ("93.184.216.34", 443)),
            (2, 1, 6, "", ("10.0.0.9", 443)),
        ],
    )
    assert check_navigable_url("https://dual.example/", resolve=True)


def test_an_unresolvable_name_is_allowed_through(monkeypatch):
    """Deliberate, and the opposite of fail-closed — pinned so it cannot be
    "fixed" by accident.

    A host the resolver cannot answer is a host the browser cannot reach either,
    so rejecting it only changes the error text. And rejecting it would break
    hermetic testing outright: this repo's tests use RFC 2606 reserved names
    (.test, .example, .invalid) that correctly never resolve, so a fail-closed
    check made 5 tests in test_submit_recon.py fail the moment resolve=True was
    wired into tools/submit_recon.py.

    What must still be rejected is the case that matters — a name that resolves
    successfully to a non-public address — which the two tests above cover.
    """

    def _boom(*a, **k):
        raise url_guard.socket.gaierror("Name or service not known")

    monkeypatch.setattr(url_guard.socket, "getaddrinfo", _boom)
    assert check_navigable_url("https://does-not-exist.invalid/", resolve=True) == ""
    # Reserved TLDs used throughout the suite must pass the real resolver too.
    for host in ("https://example.test/jobs/1", "https://acme.example/j/1", "https://x.test/3"):
        assert check_navigable_url(host, resolve=True) == "", host


def test_resolve_accepts_a_genuinely_public_resolution(monkeypatch):
    monkeypatch.setattr(
        url_guard.socket,
        "getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 443))],
    )
    assert not check_navigable_url("https://boards.greenhouse.io/x", resolve=True)


# --- 2. the wiring -----------------------------------------------------------

# Sinks that hand a URL to a browser or the OS URL handler.
SINKS = {"goto", "open"}
SINK_OWNERS = {"page", "context", "browser", "webbrowser", "new_page"}


def _calls_in(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in SINKS:
                owner = func.value
                owner_name = owner.id if isinstance(owner, ast.Name) else getattr(owner, "attr", "")
                if owner_name in SINK_OWNERS:
                    yield node


def _unguarded_sinks(path):
    """goto()/open() calls taking a non-constant URL with no guard before them.

    A string constant is excluded because those are the hardcoded board
    homepages in tools/playwright_scraper.py — there is nothing for an attacker
    to influence, and guarding them would only obscure the rule that matters:
    every URL that came from data must be checked.
    """
    with open(path, encoding="utf-8") as fh:
        try:
            tree = ast.parse(fh.read(), filename=path)
        except SyntaxError:  # pragma: no cover
            return []
    problems = []
    for func in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        guards = [
            n.lineno
            for n in ast.walk(func)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            # Either form counts: `assert_navigable_url` raises into the caller's
            # per-job error handling, `is_navigable_url` is for a sink that
            # returns a bool instead (auto_applier._safe_open_browser).
            and n.func.id in {"assert_navigable_url", "is_navigable_url"}
        ]
        for call in _calls_in(func):
            if not call.args:
                continue
            first = call.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                continue  # hardcoded literal, no attacker influence
            if not any(g <= call.lineno for g in guards):
                problems.append(
                    f"{os.path.relpath(path, REPO)}:{call.lineno} in {func.name}() "
                    f"— {call.func.attr}() on a dynamic URL with no url_guard check before it"
                )
    return problems


def test_every_dynamic_browser_navigation_is_guarded():
    offenders = []
    for path in _python_files():
        offenders.extend(_unguarded_sinks(path))
    assert not offenders, (
        "these browser sinks take a URL that came from data and navigate without "
        "vetting it:\n  " + "\n  ".join(sorted(offenders))
    )


def test_the_scan_actually_finds_sinks():
    """Guard the guard: if the AST walk silently stopped matching (a rename from
    `page.goto` to something else, a refactor into a helper) the test above
    would pass vacuously forever."""
    found = {}
    for path in _python_files():
        with open(path, encoding="utf-8") as fh:
            try:
                tree = ast.parse(fh.read(), filename=path)
            except SyntaxError:  # pragma: no cover
                continue
        sinks = list(_calls_in(tree))
        if sinks:
            found[os.path.relpath(path, REPO)] = len(sinks)
    assert "agents/auto_applier.py" in found, f"sinks not detected: {found}"
    assert "tools/playwright_scraper.py" in found, f"sinks not detected: {found}"
    assert "tools/submit_recon.py" in found, f"sinks not detected: {found}"
    assert sum(found.values()) >= 12, f"only {sum(found.values())} sinks found: {found}"


def test_guard_module_is_the_single_source_of_the_rule():
    """No sink file may reimplement a weaker local check."""
    for rel in ("agents/auto_applier.py", "tools/playwright_scraper.py", "tools/submit_recon.py"):
        with open(os.path.join(REPO, rel), encoding="utf-8") as fh:
            src = fh.read()
        assert "url_guard" in src, f"{rel} navigates without importing tools.url_guard"


# --- 3. the API boundary -----------------------------------------------------


@pytest.mark.parametrize(
    "url", ["file:///etc/passwd", "javascript:alert(1)", "http://169.254.169.254/", "http://x:6379/"]
)
def test_tracker_schema_rejects_a_dangerous_apply_url(url):
    with pytest.raises(Exception) as exc:
        TrackerCreate(apply_url=url)
    assert "apply_url" in str(exc.value)


def test_tracker_schema_accepts_a_normal_board_url():
    created = TrackerCreate(apply_url="https://boards.greenhouse.io/acme/jobs/1")
    assert created.apply_url == "https://boards.greenhouse.io/acme/jobs/1"


def test_posting_a_dangerous_apply_url_is_a_422_not_a_stored_row():
    """End to end: the row must never reach the tracker, because a stored
    file:// URL is a live grenade for the next fill_review() run."""
    client = TestClient(create_app())
    response = client.post("/api/tracker", json={"apply_url": "file:///app/keys.json"})
    assert response.status_code == 422, response.text
    assert "apply_url" in response.text
    assert "scheme" in response.text


def test_the_schema_check_does_not_do_dns():
    """The request path must stay cheap. `example.invalid` never resolves, so a
    validator that resolved would reject it; the schema must accept it and leave
    the resolution check to the navigation site."""
    created = TrackerCreate(apply_url="https://does-not-exist.invalid/jobs/1")
    assert created.apply_url == "https://does-not-exist.invalid/jobs/1"
    assert check_navigable_url("https://does-not-exist.invalid/jobs/1") == ""


def test_is_navigable_matches_check():
    for url in BLOCKED[:12]:
        assert not is_navigable_url(url)
    for url in ALLOWED:
        assert is_navigable_url(url)
