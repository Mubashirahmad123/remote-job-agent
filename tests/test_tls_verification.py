"""TLS certificate verification is never disabled.

`agents/scrapper.py` fetches ~47 job boards over HTTPS. It used to turn
certificate verification off in three separate places:

  1. `urllib3.disable_warnings(InsecureRequestWarning)` at import time, so
     nothing complained about the requests below;
  2. `SSL_ISSUE_BOARDS = {"TimesJobs", "NaukriGulf"}` plus
     `verify_ssl: False` in those two board configs — verification off before
     the first byte was sent;
  3. an `except requests.exceptions.SSLError` handler that set `verify_ssl =
     False` and retried — verification off after any single TLS failure.

(3) is the one that matters. It meant an on-path attacker only had to cause one
TLS error — a bad certificate, a reset during the handshake — and the retry
would then fetch that board over an **unauthenticated** connection and accept
whatever came back. Observed firing live during this audit against
jobspresso.co, arc.dev, lemon.io, euremotejobs.com and workingnomads.co.

What an attacker controls at that point:

  * `apply_url`, which `agents/auto_applier.py` passes to `page.goto()` in a
    real browser, and which is served back to any authenticated operator as a
    screenshot (see tests/test_url_guard.py);
  * the job description text, which is pasted into the LLM prompts that
    generate resumes and cover letters — direct prompt injection;
  * rows written into the operator's Google Sheet.

Trading a board with a broken certificate for a MITM hole on every board is not
a trade worth making, so verification is now unconditional and is not a
parameter of anything. A board whose chain does not validate is skipped, with
the reason logged, and the operator's remedy is REQUESTS_CA_BUNDLE (which still
verifies, against a bundle that contains the missing intermediate) or dropping
the board.

The scans below are AST-based rather than grep-based on purpose: the fixed
source contains the words "verify_ssl" and "SSL_ISSUE_BOARDS" in comments and
docstrings explaining what was removed, and a text scan would either fail on
that prose or have to be loosened until it stopped meaning anything.
"""

import ast
import inspect
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import requests

import agents.scrapper as scrapper

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {".venv", "venv", "node_modules", ".git", "__pycache__", "tests"}

# Keyword arguments that, set to False, disable a TLS check somewhere.
INSECURE_KWARGS = {"verify", "ignore_https_errors", "ssl_verify", "verify_ssl", "check_hostname"}


def _python_files():
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            if name.endswith(".py"):
                yield os.path.join(root, name)


def _insecure_calls(path):
    """Every call site that turns a TLS check off, found by parsing the AST."""
    with open(path, encoding="utf-8") as fh:
        source = fh.read()
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError:  # pragma: no cover - the suite would already have failed
        return []
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg in INSECURE_KWARGS and isinstance(kw.value, ast.Constant) and kw.value.value is False:
                    found.append((node.lineno, f"{kw.arg}=False"))
            # ssl._create_unverified_context() / CERT_NONE
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name == "disable_warnings":
                found.append((node.lineno, "urllib3.disable_warnings(...) hides the one signal that a request was unverified"))
        elif isinstance(node, ast.Attribute) and node.attr == "CERT_NONE":
            found.append((node.lineno, "ssl.CERT_NONE"))
    return found


# --- source-wide scan --------------------------------------------------------


def test_nothing_in_the_codebase_disables_tls_verification():
    offenders = {}
    for path in _python_files():
        hits = _insecure_calls(path)
        if hits:
            offenders[os.path.relpath(path, REPO)] = hits
    assert not offenders, (
        "TLS verification is disabled at these call sites:\n"
        + "\n".join(f"  {f}:{line}  {why}" for f, hs in sorted(offenders.items()) for line, why in hs)
    )


def test_no_function_accepts_a_verification_parameter():
    """The knob must not exist, or a caller can pass False even with the
    downgrades removed."""
    offenders = []
    for path in _python_files():
        with open(path, encoding="utf-8") as fh:
            try:
                tree = ast.parse(fh.read(), filename=path)
            except SyntaxError:  # pragma: no cover
                continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = [a.arg for a in node.args.args + node.args.kwonlyargs]
                bad = [a for a in args if a in INSECURE_KWARGS or a == "verify_ssl"]
                if bad:
                    offenders.append(f"{os.path.relpath(path, REPO)}:{node.lineno} {node.name}({', '.join(bad)})")
    assert not offenders, f"these functions still take a verification switch: {offenders}"


def test_no_board_config_carries_a_verification_override():
    dicts = {
        name: getattr(scrapper, name)
        for name in dir(scrapper)
        if isinstance(getattr(scrapper, name), dict)
        and any(isinstance(v, dict) and "url" in v for v in getattr(scrapper, name).values())
    }
    assert dicts, "found no board-config dicts; this test has stopped looking in the right place"
    bad = {
        f"{board_name}.{key}": value
        for board_name, boards in dicts.items()
        for key, value in boards.items()
        if isinstance(value, dict)
        for k, v in value.items()
        if k in INSECURE_KWARGS
    }
    assert not bad, f"per-board TLS overrides: {bad}"
    total = sum(len(b) for b in dicts.values())
    assert total >= 40, f"only {total} boards found — the scan is probably not covering the real config"


def test_ssl_issue_board_list_is_gone():
    assert not hasattr(scrapper, "SSL_ISSUE_BOARDS"), (
        "SSL_ISSUE_BOARDS existed only to switch verification off for its members"
    )


# --- behaviour ---------------------------------------------------------------


class _RecordingSession:
    """Stands in for scrapper._SESSION and records what it was asked to do."""

    def __init__(self, error):
        self.error = error
        self.verify_args = []

    def get(self, url, **kwargs):
        # "OMITTED" is the safe case: requests defaults verify to True, and not
        # passing the argument at all means nothing can set it to False.
        self.verify_args.append(kwargs.get("verify", "OMITTED"))
        if self.error:
            raise self.error
        return _FakeResponse()


class _FakeResponse:
    status_code = 200
    text = "<html></html>"

    def raise_for_status(self):
        return None

    def json(self):
        return {}


@pytest.fixture()
def no_sleep(monkeypatch):
    """fetch_with_retry sleeps several seconds per attempt; the delays are not
    what is under test."""
    monkeypatch.setattr(scrapper.time, "sleep", lambda _s: None)


def test_a_tls_failure_never_causes_an_unverified_retry(monkeypatch, no_sleep):
    """The core regression. Before the fix, attempt 1 raised SSLError and
    attempt 2 was made with verify=False — so this asserts on every attempt, not
    just the first."""
    session = _RecordingSession(requests.exceptions.SSLError("certificate verify failed"))
    monkeypatch.setattr(scrapper, "_SESSION", session)

    result = scrapper.fetch_with_retry(
        "https://broken-cert.example.test/jobs", max_retries=3, board_name="BrokenBoard"
    )

    assert result is None, "an unvalidatable board must be skipped, not fetched"
    assert len(session.verify_args) == 3, f"expected 3 attempts, saw {session.verify_args}"
    assert False not in session.verify_args, (
        f"verification was disabled on a retry: {session.verify_args}. This is the "
        "MITM hole: any attacker who can cause one TLS error then gets to serve "
        "arbitrary job content, including the apply_url a real browser later opens."
    )


def test_a_known_bad_board_is_not_pre_downgraded(monkeypatch, no_sleep):
    """TimesJobs and NaukriGulf were the two boards verification was switched
    off for before the first request. They must now be fetched like any other."""
    for board in ("TimesJobs", "NaukriGulf"):
        session = _RecordingSession(None)
        monkeypatch.setattr(scrapper, "_SESSION", session)
        scrapper.fetch_with_retry("https://example.test/jobs", max_retries=1, board_name=board)
        assert False not in session.verify_args, f"{board} fetched without verification: {session.verify_args}"


def test_a_successful_fetch_passes_no_verification_override(monkeypatch, no_sleep):
    session = _RecordingSession(None)
    monkeypatch.setattr(scrapper, "_SESSION", session)
    response = scrapper.fetch_with_retry("https://example.test/jobs", board_name="AnyBoard")
    assert response is not None
    assert session.verify_args == ["OMITTED"], (
        f"fetch passed verify={session.verify_args}; omitting it lets requests "
        "use its own secure default and leaves nothing to set to False"
    )


def test_fetch_with_retry_signature_has_no_verification_switch():
    params = list(inspect.signature(scrapper.fetch_with_retry).parameters)
    assert "verify_ssl" not in params, params
    assert params == ["url", "headers", "timeout", "max_retries", "board_name"], (
        f"signature changed to {params}; if a verification parameter was added "
        "back, this test is the reason it should not have been"
    )


def test_the_ssl_handler_explains_the_remedy(capsys, monkeypatch, no_sleep):
    """A skipped board must tell the operator what to do, or the fix reads as
    'the scraper is broken' and the downgrade gets reverted."""
    session = _RecordingSession(requests.exceptions.SSLError("certificate verify failed"))
    monkeypatch.setattr(scrapper, "_SESSION", session)
    scrapper.fetch_with_retry("https://broken-cert.example.test/jobs", max_retries=1, board_name="BrokenBoard")
    out = capsys.readouterr().out
    assert "REQUESTS_CA_BUNDLE" in out, f"no actionable remedy in the log:\n{out}"
    assert "never" in out.lower() or "not negotiable" in out.lower(), (
        "the log should state that verification is not disabled, so the skip is "
        "not mistaken for a bug to work around"
    )
