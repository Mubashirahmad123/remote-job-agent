"""Internal exception text must not become the HTTP response (L1).

Every 502 in this API used to be `detail=f"<action> failed: {e}"`. The message
this was actually found with, from a live server:

    {"detail": "Resume generation failed: expected str, bytes or os.PathLike
     object, not NoneType"}

Worst of both worlds. Useless to the operator — no file, no line, no cause —
and a free description of the internals for anyone probing the API. The
concrete case was worse than that: `GET /api/apply/{fp}/screenshot` caught
`FileNotFoundError` and forwarded `str(e)`, which *is* the absolute path, so it
would reply `[Errno 2] No such file or directory: '/app/screenshots/ab12.png'`
and confirm exactly where artifacts live inside the container.

Now: the traceback goes to the server log under a short incident id, the caller
gets the action name and that id, and `api/errors.py` explains the reasoning.

Two failure modes are pinned here, because fixing only one of them is easy:

  * leaking — covered by the behavioural tests, which raise an exception
    carrying a fake private key, a container path, a library name and a source
    location, then assert none of it reaches the response and all of it reaches
    the log.
  * over-correcting into an API that says "failed" to everything — covered by
    `test_messages_written_for_the_user_still_reach_the_user`. The 400s and
    409s in this API carry messages written deliberately for the caller
    ("Unknown tab 'X'. Choose from: ..."). Routing those through the generic
    handler would hide nothing and make the dashboard worse, so they are
    asserted to still come through verbatim.

Plus a static AST check over `api/routers/`, because the behavioural tests can
only cover the routes that exist today: any *new* broad `except Exception` that
interpolates its exception into a response detail fails here at once.
"""

import ast
import logging
import os
import re
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api.app import create_app
from api.auth import create_user
from api.ratelimit import reset_action_limiter, reset_login_limiter

PASSWORD = "s3cretPass1"
BOGUS_FP = "0" * 40
ROUTER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api", "routers")

# An exception message built to contain every category of thing that must not
# leave the server: a credential, a container filesystem path, a third-party
# library name, and a source location.
LEAKY_MESSAGE = (
    "expected str, bytes or os.PathLike object, not NoneType while reading "
    "/app/keys.json (GOOGLE_PRIVATE_KEY=-----BEGIN PRIVATE KEY-----MIIEvQIBADAN) "
    "from sheet 1AbCdEfGh via gspread at api/cache.py:214"
)

LEAKY_FRAGMENTS = (
    "/app/keys.json",
    "GOOGLE_PRIVATE_KEY",
    "MIIEvQIBADAN",
    "NoneType",
    "gspread",
    "api/cache.py",
    "1AbCdEfGh",
)

# An incident id as api/errors.py mints one: 8 hex characters.
INCIDENT = re.compile(r"incident ([0-9a-f]{8})")


@pytest.fixture()
def client():
    return TestClient(create_app())


@pytest.fixture(autouse=True)
def _clean_state():
    reset_login_limiter()
    reset_action_limiter()
    yield
    reset_login_limiter()
    reset_action_limiter()


@pytest.fixture()
def signed_in(client):
    create_user("alice", PASSWORD)
    response = client.post(
        "/api/auth/login", json={"username": "alice", "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    return client


@pytest.fixture()
def exploding_resume(monkeypatch):
    from api import materials as materials_service

    def _boom(fingerprint):
        raise TypeError(LEAKY_MESSAGE)

    monkeypatch.setattr(materials_service, "generate_resume", _boom)
    monkeypatch.setattr(materials_service, "generate_cover_letter", _boom)


def _detail(response):
    return response.json().get("detail", "")


# --- the leak ----------------------------------------------------------------


def test_a_502_names_the_operation_and_nothing_else(signed_in, exploding_resume, caplog):
    with caplog.at_level(logging.ERROR, logger="api.errors"):
        response = signed_in.post(f"/api/resume/{BOGUS_FP}")

    assert response.status_code == 502
    detail = _detail(response)
    assert "Resume generation" in detail, (
        "the caller still needs to know WHICH operation failed"
    )
    for fragment in LEAKY_FRAGMENTS:
        assert fragment not in detail, f"{fragment!r} reached the client: {detail!r}"
    assert "Traceback" not in detail
    assert detail.count("\n") == 0, "a multi-line detail is a stack trace"


def test_the_details_go_to_the_log_under_the_same_incident(
    signed_in, exploding_resume, caplog
):
    with caplog.at_level(logging.ERROR, logger="api.errors"):
        response = signed_in.post(f"/api/resume/{BOGUS_FP}")

    match = INCIDENT.search(_detail(response))
    assert match, f"the response carries no incident id: {_detail(response)!r}"
    incident = match.group(1)

    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert incident in logged, (
        f"incident {incident} is not in the log, so the id the caller was given "
        "cannot be used to find anything"
    )
    for fragment in LEAKY_FRAGMENTS:
        assert fragment in logged, f"{fragment!r} is missing from the server log"
    # exc_info=<instance> is what makes the traceback appear; the message alone
    # is what the client already had and could not act on.
    assert any(record.exc_info for record in caplog.records), (
        "the failure was logged without a traceback"
    )


def test_the_cover_letter_route_is_covered_too(signed_in, exploding_resume):
    response = signed_in.post(f"/api/cover-letter/{BOGUS_FP}")
    assert response.status_code == 502
    detail = _detail(response)
    assert "Cover letter generation" in detail
    for fragment in LEAKY_FRAGMENTS:
        assert fragment not in detail


def test_the_tracker_route_is_covered_too(signed_in, monkeypatch):
    from api import cache

    def _boom(*args, **kwargs):
        raise RuntimeError(LEAKY_MESSAGE)

    monkeypatch.setattr(cache, "add_tracker_entry", _boom)
    response = signed_in.post(
        "/api/tracker", json={"apply_url": "https://boards.greenhouse.io/acme/jobs/1"}
    )
    assert response.status_code == 502
    detail = _detail(response)
    assert "Tracker create" in detail
    for fragment in LEAKY_FRAGMENTS:
        assert fragment not in detail


def test_each_failure_gets_its_own_incident_id(signed_in, exploding_resume, caplog):
    """Not a constant, and not a counter — a counter would tell any caller how
    many failures the server has had."""
    with caplog.at_level(logging.ERROR, logger="api.errors"):
        ids = [
            INCIDENT.search(_detail(signed_in.post(f"/api/resume/{BOGUS_FP}"))).group(1)
            for _ in range(5)
        ]
    assert len(set(ids)) == 5, ids


def test_a_missing_screenshot_does_not_disclose_its_path(signed_in, monkeypatch):
    """`str(FileNotFoundError)` IS the absolute path. This was the one route
    where the leak was the point of the exception rather than an accident."""
    from api import apply as apply_service

    def _gone(fingerprint):
        raise FileNotFoundError(2, "No such file or directory", "/app/screenshots/ab12cd34.png")

    monkeypatch.setattr(apply_service, "get_review_screenshot_path", _gone)
    response = signed_in.get(f"/api/apply/{BOGUS_FP}/screenshot")
    assert response.status_code == 404
    detail = _detail(response)
    assert "/app" not in detail and "screenshots" not in detail, detail
    assert detail == "Screenshot not found"


def test_a_handwritten_lookup_message_is_still_passed_through(signed_in, monkeypatch):
    """Not every exception is a leak. This one was written for the caller, so
    the fix must leave it alone — otherwise the dashboard's honest empty state
    turns into a bare 404."""
    from api import apply as apply_service

    def _none_yet(fingerprint):
        raise LookupError("No screenshot exists yet (package-only, no fill run)")

    monkeypatch.setattr(apply_service, "get_review_screenshot_path", _none_yet)
    response = signed_in.get(f"/api/apply/{BOGUS_FP}/screenshot")
    assert response.status_code == 404
    assert _detail(response) == "No screenshot exists yet (package-only, no fill run)"


# --- the opposite failure mode: an API that says nothing ---------------------


def test_messages_written_for_the_user_still_reach_the_user(signed_in):
    """These strings are the API being helpful, not leaking. If a future
    "harden the errors" pass routes them through api.errors.failure, the
    dashboard gets worse and nothing gets safer."""
    unknown_tab = signed_in.post("/api/jobs/refresh", json={"tab": "NOT A REAL TAB"})
    assert unknown_tab.status_code == 400
    detail = _detail(unknown_tab)
    assert "Unknown tab" in detail and "ALL JOBS" in detail, detail
    assert "incident" not in detail, "a caller error is not a server incident"


def test_a_conflict_still_explains_itself(signed_in, monkeypatch):
    from api import runs

    def _busy():
        raise RuntimeError("A scrape run is already active (run_id 123)")

    monkeypatch.setattr(runs, "start_scrape", _busy)
    response = signed_in.post("/api/scrape")
    assert response.status_code == 409
    assert "already active" in _detail(response)


# --- static: every route, including ones that do not exist yet ---------------


def _broad_exception_handlers(filename):
    with open(os.path.join(ROUTER_DIR, filename), encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=filename)
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and isinstance(node.type, ast.Name):
            # Only `except Exception`. `except ValueError` and friends catch
            # errors whose messages were written for the caller.
            if node.type.id == "Exception":
                yield node


def _details_that_leak(handler):
    """HTTPException(...) calls inside `handler` whose detail names the caught
    exception — as an f-string interpolation or as `str(e)`."""
    bound = handler.name
    if not bound:
        return []
    leaks = []
    for node in ast.walk(handler):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if name != "HTTPException":
            continue
        detail = next((kw.value for kw in node.keywords if kw.arg == "detail"), None)
        if detail is None:
            continue
        for reference in ast.walk(detail):
            if isinstance(reference, ast.Name) and reference.id == bound:
                leaks.append(ast.unparse(node))
                break
    return leaks


def test_no_broad_handler_forwards_its_exception_to_the_client():
    offenders = {}
    for filename in sorted(os.listdir(ROUTER_DIR)):
        if not filename.endswith(".py"):
            continue
        for handler in _broad_exception_handlers(filename):
            leaks = _details_that_leak(handler)
            if leaks:
                offenders[f"{filename}:{handler.lineno}"] = leaks
    assert not offenders, (
        "these broad `except Exception` handlers interpolate the caught "
        f"exception into a response detail: {offenders}. Use "
        "`raise failure(\"<Action>\", exc)` from api.errors, which logs the "
        "traceback server-side and returns an incident id instead."
    )


def test_every_broad_handler_does_something_deliberate():
    """A broad handler that neither reports a failure nor says why it is
    swallowing the error is how the next leak gets written."""
    for filename in sorted(os.listdir(ROUTER_DIR)):
        if not filename.endswith(".py"):
            continue
        for handler in _broad_exception_handlers(filename):
            body = ast.unparse(handler)
            if "failure(" in body or "missing(" in body or "HTTPException" in body:
                continue
            # Reaches here only if the handler swallows every exception and says
            # nothing. Two places legitimately do: system.py zeroes a warmed-tab
            # count when one tab fails so the others still return, and cv.py
            # falls back rather than failing a read. Both are deliberate and
            # both are silent by design, so they are named here — a third one is
            # a decision that should be made on purpose, not inherited.
            assert filename in {"cv.py", "system.py"}, (
                f"{filename}:{handler.lineno} swallows every exception without "
                "reporting it. If that is intentional, add the file here with a "
                "reason; otherwise report it with api.errors.failure()."
            )


def test_api_errors_is_the_only_module_that_mints_incident_ids():
    """So the format cannot drift into two shapes that a log grep would miss."""
    import api.errors

    assert api.errors._incident_id.__module__ == "api.errors"
    for filename in sorted(os.listdir(ROUTER_DIR)):
        if not filename.endswith(".py"):
            continue
        with open(os.path.join(ROUTER_DIR, filename), encoding="utf-8") as fh:
            assert "uuid" not in fh.read(), f"{filename} mints its own ids"
