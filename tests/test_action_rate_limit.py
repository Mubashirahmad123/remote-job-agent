"""Per-actor budgets for the endpoints that cost real money or real CPU (M3).

`login_limiter` guarded the only unauthenticated write. Nothing else had a
ceiling, so any authenticated caller could loop the endpoints that actually
consume resources:

    POST /api/resume/{fp}          an LLM call plus PDF generation
    POST /api/cover-letter/{fp}    an LLM call plus PDF generation
    POST /api/apply/{fp}           a full headless-browser fill run
    POST /api/apply/{fp}/intent    a headless-browser recon run
    POST /api/apply/{fp}/submit    a headless-browser submission
    POST /api/scrape               ~47 boards over the network, plus a browser
    POST /api/jobs/refresh         a sheet-cache invalidation and refetch

The audit confirmed this was not theoretical: POST /api/scrape returned **202
for the operator role** and the scrape actually ran. So one leaked operator
session — or one XSS payload, or one browser tab left open on a shared machine —
was an unbounded Gemini/GLM credit burn and an unbounded outbound traffic source
from the operator's own VM. The operator role exists precisely to be the
lower-trust one, and on this axis it had exactly as much power as admin.

Two properties of the design are pinned here and are easy to get wrong:

  * Keyed on ACTOR, not IP. Keying on IP repeats the H1 mistake — the budget
    becomes launderable by rotating source addresses, and behind a proxy every
    operator shares one bucket. The actor is already resolved for attribution,
    so this costs nothing.
  * Split into two kinds. Per-job work a human clicks through one job at a time
    ("action", generous) and whole-pipeline triggers ("run", strict) differ by
    an order of magnitude in cost; one shared budget would either let a single
    /api/scrape loop run free or throttle legitimate resume tailoring.
"""

import ast
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api.app import create_app
from api.auth import create_user
from api.ratelimit import (
    ACTION_KINDS,
    action_limiter,
    reset_action_limiter,
)

COOKIE = "rja_session"
PASSWORD = "s3cretPass1"

# A fingerprint that does not exist: generate_resume raises LookupError -> 404
# without touching an LLM, so the route can be hammered in a test hermetically.
BOGUS_FP = "0" * 40
# An unknown tab: cache.refresh raises ValueError before any Sheets call -> 400.
BOGUS_TAB = "NOT A REAL TAB"

# (method, path) -> the budget kind it must spend. This is the contract; the
# static test below walks the router ASTs to prove every one of them honours it.
BUDGETED_ROUTES = {
    ("POST", "/api/resume/{job_fingerprint}"): "action",
    ("POST", "/api/cover-letter/{job_fingerprint}"): "action",
    ("POST", "/api/apply/{job_fingerprint}"): "action",
    ("POST", "/api/apply/{job_fingerprint}/intent"): "action",
    ("POST", "/api/apply/{job_fingerprint}/submit"): "action",
    ("POST", "/api/scrape"): "run",
    ("POST", "/api/jobs/refresh"): "run",
}

ROUTER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api", "routers")


@pytest.fixture()
def client():
    return TestClient(create_app())


@pytest.fixture(autouse=True)
def _clean_budgets():
    reset_action_limiter()
    yield
    reset_action_limiter()


@pytest.fixture(autouse=True)
def _stub_expensive_handlers(monkeypatch):
    """Keep this file's HTTP tests free of process-wide side effects.

    Calling the real `materials.generate_resume` lazily imports
    `tools.resume_generator` and `agents.gemini_tools` into `sys.modules`. That
    is visible to every later test in the process, and
    `tests/test_api_materials.py::TestHygiene::test_no_heavy_imports` asserts
    those two modules are NOT loaded — so hammering these routes for real made
    that test fail whenever this file ran first.

    The budget is spent in the dependency, before the handler, so a handler that
    raises immediately exercises exactly the same path. LookupError is what the
    route already maps to 404.
    """
    from api import materials as materials_service

    def _not_found(fingerprint):
        raise LookupError(fingerprint)

    monkeypatch.setattr(materials_service, "generate_resume", _not_found)
    monkeypatch.setattr(materials_service, "generate_cover_letter", _not_found)


def _login(client, username, password=PASSWORD):
    response = client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200, response.text
    return response


def _resume(client, fingerprint=BOGUS_FP):
    return client.post(f"/api/resume/{fingerprint}")


def _refresh(client, tab=BOGUS_TAB):
    return client.post("/api/jobs/refresh", json={"tab": tab})


# --- the limiter itself ------------------------------------------------------


def test_the_two_kinds_exist_and_have_distinct_defaults():
    assert set(ACTION_KINDS) == {"action", "run"}
    action_default = None
    run_default = None
    for _ in range(200):
        if not action_limiter.allow("kind-probe", "action").allowed:
            break
        action_default = (action_default or 0) + 1
    for _ in range(200):
        if not action_limiter.allow("kind-probe", "run").allowed:
            break
        run_default = (run_default or 0) + 1
    assert action_default == 60, f"the 'action' default moved to {action_default}"
    assert run_default == 6, f"the 'run' default moved to {run_default}"
    assert action_default > run_default, (
        "whole-pipeline triggers must be the stricter budget of the two"
    )


def test_an_unknown_kind_is_a_programming_error_not_a_silent_pass():
    with pytest.raises(ValueError):
        action_limiter.allow("alice", "unbounded")


def test_the_budget_is_per_actor():
    for _ in range(6):
        assert action_limiter.allow("alice", "run").allowed
    assert not action_limiter.allow("alice", "run").allowed, "alice should be out"
    assert action_limiter.allow("bob", "run").allowed, (
        "one operator exhausting the budget must not lock out another"
    )


def test_the_budget_is_per_kind():
    for _ in range(6):
        assert action_limiter.allow("alice", "run").allowed
    assert not action_limiter.allow("alice", "run").allowed
    assert action_limiter.allow("alice", "action").allowed, (
        "the two budgets are independent: running out of pipeline triggers must "
        "not stop someone tailoring a resume"
    )


def test_a_denied_call_reports_how_long_to_wait():
    for _ in range(6):
        action_limiter.allow("alice", "run")
    decision = action_limiter.allow("alice", "run")
    assert not decision.allowed
    assert decision.retry_after >= 1, "Retry-After must be a usable positive number"
    assert decision.retry_after <= 600


def test_env_overrides_the_defaults(monkeypatch):
    monkeypatch.setenv("RUN_RATE_LIMIT", "2")
    monkeypatch.setenv("RUN_RATE_WINDOW", "600")
    reset_action_limiter()
    assert action_limiter.allow("alice", "run").allowed
    assert action_limiter.allow("alice", "run").allowed
    assert not action_limiter.allow("alice", "run").allowed


@pytest.mark.parametrize("value", ["0", "-5", "not-a-number", ""])
def test_a_nonsensical_limit_falls_back_instead_of_opening_or_closing(monkeypatch, value):
    """`0` is the dangerous one: taken literally it denies everything and the
    API looks broken. Garbage must fall back to the documented default."""
    monkeypatch.setenv("RUN_RATE_LIMIT", value)
    reset_action_limiter()
    for _ in range(6):
        assert action_limiter.allow("alice", "run").allowed
    assert not action_limiter.allow("alice", "run").allowed


def test_reset_clears_every_kind():
    for _ in range(6):
        action_limiter.allow("alice", "run")
    assert not action_limiter.allow("alice", "run").allowed
    reset_action_limiter()
    assert action_limiter.allow("alice", "run").allowed


def test_an_empty_actor_still_gets_one_shared_bucket():
    """No identity must not mean no budget — that is the whole finding."""
    for _ in range(6):
        assert action_limiter.allow("", "run").allowed
    assert not action_limiter.allow("", "run").allowed


# --- through the real app ----------------------------------------------------


def test_exhausted_run_budget_returns_429_with_retry_after(client, monkeypatch):
    monkeypatch.setenv("RUN_RATE_LIMIT", "3")
    reset_action_limiter()
    create_user("alice", PASSWORD)
    _login(client, "alice")

    statuses = [_refresh(client).status_code for _ in range(3)]
    assert statuses == [400, 400, 400], (
        "the invalid tab should 400 every time; anything else means the handler "
        f"changed and this test is no longer exercising what it thinks: {statuses}"
    )

    blocked = _refresh(client)
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) >= 1
    assert "budgeted" in blocked.json()["detail"].lower()


def test_a_failed_request_still_spends_the_budget(client, monkeypatch):
    """The 400s above consumed the budget. That is deliberate: the cost being
    limited is the *handling* of the request, and a caller who can make requests
    fail cheaply should not get an unlimited number of them. It also means the
    limiter cannot be bypassed by sending input that errors out."""
    monkeypatch.setenv("RUN_RATE_LIMIT", "2")
    reset_action_limiter()
    create_user("alice", PASSWORD)
    _login(client, "alice")
    assert _refresh(client).status_code == 400
    assert _refresh(client).status_code == 400
    assert _refresh(client).status_code == 429


def test_exhausted_action_budget_returns_429(client, monkeypatch):
    monkeypatch.setenv("ACTION_RATE_LIMIT", "3")
    reset_action_limiter()
    create_user("alice", PASSWORD)
    _login(client, "alice")

    # A non-existent fingerprint 404s before any LLM call, so this hammers the
    # real route with no side effects.
    statuses = [_resume(client).status_code for _ in range(3)]
    assert statuses == [404, 404, 404], statuses
    assert _resume(client).status_code == 429


def test_the_two_budgets_do_not_share_a_ceiling_over_http(client, monkeypatch):
    monkeypatch.setenv("RUN_RATE_LIMIT", "1")
    monkeypatch.setenv("ACTION_RATE_LIMIT", "10")
    reset_action_limiter()
    create_user("alice", PASSWORD)
    _login(client, "alice")

    assert _refresh(client).status_code == 400
    assert _refresh(client).status_code == 429, "the run budget is one deep"
    assert _resume(client).status_code == 404, (
        "being out of pipeline triggers must not stop tailoring a resume"
    )


def test_each_operator_has_their_own_budget(client, monkeypatch):
    monkeypatch.setenv("RUN_RATE_LIMIT", "1")
    reset_action_limiter()
    create_user("alice", PASSWORD, role="admin")
    create_user("bob", PASSWORD, role="operator")

    _login(client, "alice")
    assert _refresh(client).status_code == 400
    assert _refresh(client).status_code == 429

    client.cookies.clear()
    _login(client, "bob")
    assert _refresh(client).status_code == 400, (
        "alice exhausting her budget must not lock bob out — that would let any "
        "operator deny the service to every colleague by looping one endpoint"
    )


def test_a_service_bearer_is_budgeted_too(client, monkeypatch):
    """The Bearer path resolves to the shared "automation" actor, so it gets one
    budget of its own rather than none."""
    monkeypatch.setenv("RUN_RATE_LIMIT", "1")
    monkeypatch.setenv("API_TOKEN", "svc-token-12345")
    reset_action_limiter()
    headers = {"Authorization": "Bearer svc-token-12345"}
    assert client.post("/api/jobs/refresh", json={"tab": BOGUS_TAB}, headers=headers).status_code == 400
    blocked = client.post("/api/jobs/refresh", json={"tab": BOGUS_TAB}, headers=headers)
    assert blocked.status_code == 429


def test_the_scrape_trigger_is_budgeted(client, monkeypatch):
    """The specific audit finding: POST /api/scrape returned 202 for the
    operator role with no ceiling. The handler is stubbed so the test does not
    actually scrape 47 boards — the budget is spent in the dependency, before
    the handler, so the stub does not weaken what is being asserted."""
    from api import runs

    monkeypatch.setenv("RUN_RATE_LIMIT", "2")
    reset_action_limiter()
    calls = []
    monkeypatch.setattr(
        runs, "start_scrape", lambda: calls.append(1) or {"run_id": "stub", "status": "started"}
    )
    create_user("bob", PASSWORD, role="operator")
    _login(client, "bob")

    assert client.post("/api/scrape").status_code == 202
    assert client.post("/api/scrape").status_code == 202
    blocked = client.post("/api/scrape")
    assert blocked.status_code == 429
    assert len(calls) == 2, "the third request must never reach the handler"


def test_cheap_reads_are_not_budgeted(client):
    """The dashboard polls GET /api/jobs constantly. Putting a budget on reads
    would break the UI, so this asserts the limiter stayed off them."""
    create_user("alice", PASSWORD)
    _login(client, "alice")
    for _ in range(80):
        response = client.get("/api/jobs")
        assert response.status_code != 429, "a read endpoint must never be budgeted"


def test_anonymous_callers_are_still_rejected_before_being_budgeted(client, monkeypatch):
    """The limiter must not become a way to probe or to DoS unauthenticated:
    auth still runs, so an anonymous caller gets 401 and spends nothing."""
    monkeypatch.setenv("RUN_RATE_LIMIT", "1")
    reset_action_limiter()
    create_user("alice", PASSWORD)
    assert _refresh(client).status_code == 401
    assert _refresh(client).status_code == 401, (
        "a 429 here would mean anonymous requests are consuming the shared "
        "budget and could lock out the real operator"
    )


# --- the wiring, statically --------------------------------------------------


def _post_handlers():
    """(path, FunctionDef) for every @router.post(...) in api/routers/."""
    for name in sorted(os.listdir(ROUTER_DIR)):
        if not name.endswith(".py"):
            continue
        with open(os.path.join(ROUTER_DIR, name), encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=name)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not (
                    isinstance(decorator, ast.Call)
                    and isinstance(decorator.func, ast.Attribute)
                    and decorator.func.attr == "post"
                    and decorator.args
                    and isinstance(decorator.args[0], ast.Constant)
                    and isinstance(decorator.args[0].value, str)
                ):
                    continue
                yield decorator.args[0].value, node, name


def _budget_kinds(node):
    """The kinds this handler spends, read from its Depends(action_budget(...))."""
    kinds = set()
    defaults = list(node.args.defaults) + [d for d in node.args.kw_defaults if d is not None]
    for default in defaults:
        # The default is `Depends(action_budget("run"))` — the call we care about
        # is NESTED inside it, so walk the whole expression rather than only
        # looking at the outermost call. Checking only the top level silently
        # returns no kinds and reports every route as unbudgeted.
        for sub in ast.walk(default):
            if not isinstance(sub, ast.Call):
                continue
            func = sub.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name != "action_budget" or not sub.args:
                continue
            if isinstance(sub.args[0], ast.Constant):
                kinds.add(sub.args[0].value)
    return kinds


@pytest.mark.parametrize(
    "method,path,kind",
    [(m, p, k) for (m, p), k in sorted(BUDGETED_ROUTES.items())],
)
def test_every_expensive_route_spends_the_right_budget(method, path, kind):
    handlers = [(n, f) for p, n, f in _post_handlers() if p == path]
    assert handlers, f"no {method} handler for {path} — the route moved or was renamed"
    assert len(handlers) == 1, f"{path} is declared in more than one router: {handlers}"
    node, filename = handlers[0]
    kinds = _budget_kinds(node)
    assert kinds == {kind}, (
        f"{path} in {filename} spends {kinds or 'NO budget at all'}, expected "
        f"{{{kind!r}}}. This is the route that runs an LLM call or a headless "
        "browser, so an empty set means it is unbounded again."
    )


def test_no_budget_kind_is_misspelled():
    for path, node, filename in _post_handlers():
        for kind in _budget_kinds(node):
            assert kind in ACTION_KINDS, (
                f"{path} in {filename} spends unknown kind {kind!r}; a typo here "
                "would raise ValueError on every request to that route"
            )


def test_read_endpoints_stay_unbudgeted_in_source():
    """Cheap reads power the dashboard's polling. Assert it in source too, so
    adding a budget to a GET is a deliberate, reviewed act."""
    for name in sorted(os.listdir(ROUTER_DIR)):
        if not name.endswith(".py"):
            continue
        with open(os.path.join(ROUTER_DIR, name), encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=name)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if (
                    isinstance(decorator, ast.Call)
                    and isinstance(decorator.func, ast.Attribute)
                    and decorator.func.attr == "get"
                ):
                    assert not _budget_kinds(node), (
                        f"GET handler {node.name} in {name} is budgeted"
                    )
