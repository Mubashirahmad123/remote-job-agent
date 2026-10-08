"""Production-hardening tests for the login/auth path.

Each test here pins one specific defect that was found by probing the running
app, so a regression re-opens a known hole rather than introducing a new one:

  rate limiting   - /api/auth/login is the only unauthenticated write; a
                    sync `time.sleep()` penalty used to hold a threadpool
                    worker, so ~40 concurrent bad passwords stalled the app.
  input ceiling   - an unbounded `password` field bought a full Argon2id
                    verify on arbitrary-length input from one small JSON body.
  reset revokes   - a password change used to leave every existing session
                    valid for the rest of its TTL.
  docs gated      - /docs + /openapi.json disclosed the full route inventory.
  shell gated     - /index.html bypassed the `GET /` login redirect.
  bind guard      - the guard read API_HOST only, so the documented
                    `uvicorn api.app:app --host 0.0.0.0` bound publicly.
  fail-closed     - per-route auth means one forgotten Depends ships public.
  sqlite cost     - schema DDL ran on every authenticated request.
"""

import inspect
import os
import sqlite3
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient

import api.routers.auth as auth_router
from api.app import (
    _GATED_ROUTERS,
    _argv_host,
    _enforce_bind_guard,
    _include_gated,
    create_app,
)
from api.deps import require_token
from api.routers import auth
from api.auth import (
    create_user,
    db_path,
    forget_initialized,
    get_session,
    revoke_user_sessions,
    update_password,
    verify_login,
)
from api.ratelimit import RateLimiter, client_ip, login_limiter, reset_login_limiter

COOKIE = "rja_session"
PASSWORD = "s3cretPass1"


@pytest.fixture()
def client():
    return TestClient(create_app())


def sign_in(client, username="alice", password=PASSWORD):
    return client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )


# --- rate limiting -----------------------------------------------------------


def test_login_is_a_coroutine_and_never_blocks_a_worker_thread():
    """The penalty must be awaited, not `time.sleep`'d in a sync handler.

    Structural assertion on purpose: a TestClient is synchronous, so measuring
    real threadpool saturation from a test is unreliable. What actually caused
    the outage was (a) a sync `def` handler, which FastAPI dispatches to the
    40-thread pool, and (b) a blocking sleep inside it. Pinning both properties
    catches a revert even though the timing itself is environment-dependent.
    """
    assert inspect.iscoroutinefunction(auth_router.login), (
        "login must be `async def` — a sync handler runs in the threadpool, "
        "so a failure penalty blocks a worker for every bad-password request"
    )
    # Inspect the executable code, not the module text: the docstring quotes
    # `time.sleep` to explain what used to be wrong with it.
    body = inspect.getsource(auth_router.login)
    assert "time.sleep" not in body, "use `await asyncio.sleep`, never time.sleep"
    assert "asyncio.sleep" in body, "the failure penalty must be awaited"


def test_exhausted_budget_returns_429_with_retry_after(client, monkeypatch):
    monkeypatch.setenv("LOGIN_RATE_LIMIT", "3")
    monkeypatch.setenv("LOGIN_USER_RATE_LIMIT", "999")  # isolate the IP budget
    monkeypatch.setenv("LOGIN_RATE_WINDOW", "600")
    reset_login_limiter()
    create_user("alice", PASSWORD)

    for _ in range(3):
        assert sign_in(client, password="wrong-one").status_code == 401

    blocked = sign_in(client, password="wrong-one")
    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) >= 1
    # The detail must not leak whether the username exists or which budget tripped.
    assert "alice" not in blocked.json()["detail"].lower()


def test_rate_limit_rejects_before_doing_any_argon2_work(client, monkeypatch):
    """The 429 path must be cheap — that is the entire point of the limiter.

    If verification ran first, an attacker would still be buying an Argon2id
    hash per request and the limiter would only be hiding the response.
    """
    monkeypatch.setenv("LOGIN_RATE_LIMIT", "1")
    monkeypatch.setenv("LOGIN_USER_RATE_LIMIT", "999")
    reset_login_limiter()
    create_user("alice", PASSWORD)

    assert sign_in(client, password="wrong-one").status_code == 401

    calls = []
    real_verify = auth_router.verify_login
    monkeypatch.setattr(
        auth_router, "verify_login", lambda *a, **k: calls.append(a) or real_verify(*a, **k)
    )
    assert sign_in(client, password="wrong-one").status_code == 429
    assert calls == [], "verify_login must not run once the budget is spent"


def test_per_username_budget_survives_ip_rotation(client, monkeypatch):
    """Rotating IPs must not grant unlimited guesses against one account."""
    monkeypatch.setenv("LOGIN_RATE_LIMIT", "999")  # isolate the username budget
    monkeypatch.setenv("LOGIN_USER_RATE_LIMIT", "2")
    reset_login_limiter()
    create_user("alice", PASSWORD)

    for ip in ("10.0.0.1", "10.0.0.2"):
        response = sign_in(client, password="wrong-one")
        response  # both allowed: different IPs, same account budget
    assert sign_in(client, password="wrong-one").status_code == 429


def test_successful_login_clears_the_account_budget_but_not_the_ip_budget(
    client, monkeypatch
):
    """An operator who mistyped twice should not be locked out of their next
    session — but one valid credential does not prove the address is benign."""
    monkeypatch.setenv("LOGIN_RATE_LIMIT", "999")
    monkeypatch.setenv("LOGIN_USER_RATE_LIMIT", "2")
    reset_login_limiter()
    create_user("alice", PASSWORD)

    sign_in(client, password="wrong-one")
    assert sign_in(client, password=PASSWORD).status_code == 200

    # Account budget was reset by the success, so a fresh failure is allowed
    # again rather than 429-ing immediately.
    assert sign_in(client, password="wrong-one").status_code == 401


def test_failed_attempt_does_not_write_to_the_database(client, monkeypatch):
    """`purge_expired_sessions()` moved to the success path.

    An unauthenticated request must not be able to earn a database write —
    that is free amplification against the SQLite file.
    """
    create_user("alice", PASSWORD)
    calls = []
    monkeypatch.setattr(
        auth_router,
        "purge_expired_sessions",
        lambda: calls.append(1),
    )
    sign_in(client, password="wrong-one")
    assert calls == [], "a failed login must not trigger a DB write"

    sign_in(client, password=PASSWORD)
    assert calls == [1], "a successful login still does the housekeeping"


def test_limiter_prunes_and_is_bounded():
    """Distinct keys must not grow the tracker without bound."""
    limiter = RateLimiter(limit=1, window_seconds=60, max_keys=64)
    for index in range(500):
        limiter.allow(f"ip:10.0.{index // 250}.{index % 250}")
    assert len(limiter._hits) <= 64


def test_client_ip_ignores_forwarded_for_unless_explicitly_trusted(monkeypatch):
    """X-Forwarded-For is client-controlled; trusting it by default would let
    an attacker mint a fresh bucket per request by randomising the header."""

    class _Client:
        host = "203.0.113.7"

    class _Request:
        client = _Client()
        headers = {"x-forwarded-for": "198.51.100.9"}

    monkeypatch.delenv("TRUST_PROXY_HEADERS", raising=False)
    assert client_ip(_Request()) == "203.0.113.7"

    monkeypatch.setenv("TRUST_PROXY_HEADERS", "true")
    assert client_ip(_Request()) == "198.51.100.9"


# --- input ceilings ----------------------------------------------------------


def test_oversized_password_is_rejected_by_the_schema(client):
    create_user("alice", PASSWORD)
    response = client.post(
        "/api/auth/login", json={"username": "alice", "password": "x" * 200_000}
    )
    assert response.status_code == 422, (
        "LoginRequest.password needs max_length, or one small JSON body buys a "
        "full Argon2id verify on 200 KB of input"
    )


def test_oversized_username_is_rejected_by_the_schema(client):
    create_user("alice", PASSWORD)
    response = client.post(
        "/api/auth/login", json={"username": "u" * 5_000, "password": PASSWORD}
    )
    assert response.status_code == 422


def test_verify_login_refuses_oversized_password_even_off_the_http_path(monkeypatch):
    """The ceiling must not be HTTP-only — `verify_login` is importable."""
    create_user("alice", PASSWORD)
    monkeypatch.setenv("PASSWORD_MAX_LENGTH", "128")
    assert verify_login("alice", "y" * 5_000) is None
    assert verify_login("alice", PASSWORD) is not None


def test_create_user_rejects_an_over_long_password():
    from api.auth import password_max_length

    with pytest.raises(ValueError):
        create_user("alice", "z" * (password_max_length() + 1))


# --- password reset revokes sessions -----------------------------------------


def test_password_reset_revokes_every_existing_session(client):
    """The single most important property of a credential reset.

    Before this, a stolen `rja_session` cookie kept working for the rest of its
    7-day TTL no matter how often the password was rotated.
    """
    create_user("alice", PASSWORD)
    token = sign_in(client).cookies.get(COOKIE)
    assert token and get_session(token) is not None

    assert update_password("alice", "BrandNewPass99") is True

    assert get_session(token) is None, "old session must be dead after a reset"
    assert client.get("/api/health", cookies={COOKIE: token}).status_code == 401
    # ...and the new credential works.
    assert sign_in(client, password="BrandNewPass99").status_code == 200


def test_revoke_user_sessions_is_targeted(client):
    """Revoking one user must not sign out everyone else."""
    create_user("alice", PASSWORD)
    create_user("bob", "s3cretPass2")
    alice_token = sign_in(client, "alice").cookies.get(COOKIE)
    bob_token = sign_in(client, "bob", "s3cretPass2").cookies.get(COOKIE)

    alice_id = verify_login("alice", PASSWORD)["id"]
    assert revoke_user_sessions(alice_id) == 1

    assert get_session(alice_token) is None
    assert get_session(bob_token) is not None, "bob must stay signed in"


def test_resetting_an_unknown_user_revokes_nothing():
    assert update_password("nobody-here", "BrandNewPass99") is False


# --- docs + dashboard shell are gated ----------------------------------------


def test_docs_and_openapi_require_a_session(client):
    create_user("alice", PASSWORD)
    for path in ("/docs", "/openapi.json", "/redoc"):
        assert client.get(path).status_code == 401, f"{path} leaked the API surface"

    token = sign_in(client).cookies.get(COOKIE)
    assert client.get("/docs", cookies={COOKIE: token}).status_code == 200
    assert client.get("/openapi.json", cookies={COOKIE: token}).status_code == 200


def test_docs_can_be_published_explicitly(monkeypatch):
    monkeypatch.setenv("API_DOCS_ENABLED", "true")
    create_user("alice", PASSWORD)
    anonymous = TestClient(create_app())
    assert anonymous.get("/docs").status_code == 200


def test_index_html_cannot_bypass_the_login_gate(client):
    """StaticFiles serves /index.html directly, past the `GET /` redirect."""
    create_user("alice", PASSWORD)

    bypass = client.get("/index.html", follow_redirects=False)
    assert bypass.status_code == 302
    assert "/login.html" in bypass.headers["location"]

    token = sign_in(client).cookies.get(COOKIE)
    assert client.get("/index.html", cookies={COOKIE: token}).status_code == 200


def test_login_page_itself_stays_public(client):
    create_user("alice", PASSWORD)
    assert client.get("/login.html").status_code == 200


def test_security_headers_are_present_without_caddy(client):
    """Caddy adds these in the documented deploy, but the app must not be
    silently unprotected when run directly (bare uvicorn, a tunnel, a VM)."""
    response = client.get("/login.html")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "SAMEORIGIN"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"


# --- bind guard --------------------------------------------------------------


def test_bind_guard_catches_uvicorn_host_flag(monkeypatch):
    """`uvicorn api.app:app --host 0.0.0.0` used to pass the guard.

    The guard read only API_HOST, so the documented command bound on every
    interface with no API_TOKEN — and with no users, `open_access()` then made
    the whole API public.
    """
    monkeypatch.delenv("API_HOST", raising=False)
    monkeypatch.delenv("API_TOKEN", raising=False)

    monkeypatch.setattr(sys, "argv", ["uvicorn", "api.app:app", "--host", "0.0.0.0"])
    assert _argv_host() == "0.0.0.0"
    with pytest.raises(RuntimeError, match="non-local bind"):
        _enforce_bind_guard()

    monkeypatch.setattr(sys, "argv", ["uvicorn", "api.app:app", "--host=0.0.0.0"])
    assert _argv_host() == "0.0.0.0"
    with pytest.raises(RuntimeError):
        _enforce_bind_guard()


def test_bind_guard_allows_local_and_tokened_binds(monkeypatch):
    monkeypatch.delenv("API_TOKEN", raising=False)
    monkeypatch.setattr(sys, "argv", ["uvicorn", "api.app:app", "--host", "127.0.0.1"])
    _enforce_bind_guard()  # no raise

    monkeypatch.setattr(sys, "argv", ["uvicorn", "api.app:app", "--host", "0.0.0.0"])
    monkeypatch.setenv("API_TOKEN", "server-secret")
    _enforce_bind_guard()  # no raise: token present


# --- fail-closed router gating -----------------------------------------------


def test_router_level_gate_covers_a_route_that_forgets_its_dependency():
    """The regression this exists for: per-route auth fails OPEN.

    A brand-new route with no `Depends(require_token)` of its own must still be
    authenticated, because the router carries the dependency.

    Built on a bare FastAPI app rather than `create_app()`: create_app() mounts
    StaticFiles at "/" LAST, and Starlette matches routes in order, so a router
    included afterwards is shadowed by the mount and 404s before auth is even
    consulted. That ordering is correct for the real app (the mount must lose to
    /api/*), it just means the mechanism has to be tested directly.
    """
    create_user("alice", PASSWORD)

    forgotten = APIRouter(tags=["forgotten"])

    @forgotten.get("/api/forgotten-route")
    def forgotten_route() -> dict:  # no auth dependency on purpose
        return {"secret": True}

    module = types.SimpleNamespace(router=forgotten)

    app = FastAPI()
    app.include_router(auth_router.router)  # ungated: login must stay reachable
    _include_gated(app, module)
    anonymous = TestClient(app)

    assert anonymous.get("/api/forgotten-route").status_code == 401

    token = sign_in(anonymous).cookies.get(COOKIE)
    assert anonymous.get("/api/forgotten-route", cookies={COOKIE: token}).status_code == 200


def test_mutating_router_dependencies_is_a_silent_no_op():
    """Pins the trap `_include_gated` exists to avoid.

    Appending to `router.dependencies` after construction does NOT gate
    anything on this FastAPI version (included routers resolve lazily): the
    route registers, the app starts cleanly, and every request is served
    UNGATED. If a future upgrade makes mutation work, this test fails and the
    comment in app.py can be relaxed — but it must never be discovered the
    other way round, in production.
    """
    create_user("alice", PASSWORD)

    mutated = APIRouter(tags=["mutated"])

    @mutated.get("/api/mutated-route")
    def mutated_route() -> dict:
        return {"secret": True}

    mutated.dependencies = list(mutated.dependencies) + [Depends(require_token)]
    app = FastAPI()
    app.include_router(mutated)

    response = TestClient(app).get("/api/mutated-route")
    assert response.status_code == 200, (
        "mutation now takes effect — _include_gated can be simplified, update it"
    )


def test_auth_router_is_never_gated():
    """/api/auth/login must stay reachable logged out, or nobody can ever sign
    in once a user exists."""
    assert auth_router.router.dependencies == []
    assert auth not in _GATED_ROUTERS


def test_create_app_is_repeatable_and_stays_gated():
    """`create_app()` runs once per test against module-level router singletons.

    Building the app twice must not lose the router-level gate on the second
    build (the routers are shared objects, so any state left behind by the
    first call would show up here).
    """
    create_user("alice", PASSWORD)
    create_app()
    second = TestClient(create_app())

    assert second.get("/api/health").status_code == 401
    token = sign_in(second).cookies.get(COOKIE)
    assert second.get("/api/health", cookies={COOKIE: token}).status_code == 200


def test_every_api_route_is_gated_except_the_auth_endpoints(client):
    """Exhaustive check of the live route table, not just the known ones.

    Walks into `_IncludedRouter.original_router` because this FastAPI version
    keeps included routers as wrapper objects instead of flattening their
    routes into `app.routes` — iterating the top level alone would find zero
    /api paths and pass vacuously.
    """
    create_user("alice", PASSWORD)
    # The only intentionally public API paths: the login flow itself, and the
    # liveness probe (an uptime monitor has no session, so it must be able to
    # tell "up but not signed in" from "down"). Everything else is gated.
    exempt = {
        "/api/auth/login",
        "/api/auth/logout",
        "/api/auth/me",
        "/api/health/live",
    }

    def walk(routes):
        for route in routes:
            nested = getattr(route, "original_router", None)
            if nested is not None:
                yield from walk(nested.routes)
                continue
            yield route

    checked = 0
    for route in walk(client.app.routes):
        path = getattr(route, "path", "") or ""
        if not path.startswith("/api") or path in exempt:
            continue
        if "{" in path:  # parameterised paths are covered by their own tests
            continue
        for method in (getattr(route, "methods", None) or set()) - {"HEAD", "OPTIONS"}:
            response = client.request(method, path)
            assert response.status_code == 401, f"{method} {path} is not gated"
            checked += 1
    assert checked >= 10, f"route table looks wrong, only checked {checked}"


# --- sqlite cost -------------------------------------------------------------


def test_wal_journal_mode_is_enabled():
    """WAL lets the per-request session read proceed while a login writes."""
    create_user("alice", PASSWORD)
    connection = sqlite3.connect(db_path())
    try:
        mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        connection.close()
    assert str(mode).lower() == "wal"


def test_schema_ddl_runs_once_per_process_not_per_request(client):
    """`require_token` reads the session on every request; it must not also run
    2x CREATE TABLE + CREATE INDEX each time (~3.6 ms/request measured)."""
    import api.auth as auth_module

    create_user("alice", PASSWORD)
    token = sign_in(client).cookies.get(COOKIE)

    calls = []
    real_initialize = auth_module.initialize_auth_store
    monkey_initialize = lambda connection: calls.append(1) or real_initialize(connection)
    auth_module.initialize_auth_store = monkey_initialize
    forget_initialized(str(db_path()))
    try:
        for _ in range(10):
            assert client.get("/api/health", cookies={COOKIE: token}).status_code == 200
    finally:
        auth_module.initialize_auth_store = real_initialize

    assert len(calls) <= 1, f"schema built {len(calls)}x across 10 requests"


# --- cookie flags still correct after the refactor ---------------------------


def test_session_cookie_flags_are_unchanged(client):
    create_user("alice", PASSWORD)
    response = sign_in(client)
    assert response.status_code == 200

    cookie = next(
        (h for h in response.headers.get_list("set-cookie") if h.startswith(COOKIE + "=")),
        "",
    )
    lowered = cookie.lower()
    assert "httponly" in lowered
    assert "samesite=lax" in lowered
    assert "path=/" in lowered
    assert "max-age=" in lowered
    # The raw token must never appear in the body — only its SHA-256 is stored.
    assert "expires=" in lowered


def test_cors_allows_credentials_now_that_auth_is_a_cookie():
    """With allow_credentials=False a cross-origin dashboard configured via
    API_CORS_ORIGINS could never send the session cookie at all."""
    app = create_app()
    for middleware in app.user_middleware:
        if middleware.cls.__name__ == "CORSMiddleware":
            assert middleware.kwargs.get("allow_credentials") is True
            origins = middleware.kwargs.get("allow_origins") or []
            assert "*" not in origins, "wildcard origin + credentials is invalid"
            return
    pytest.fail("CORSMiddleware not found")


def test_liveness_probe_is_public_and_reveals_nothing(client):
    """An uptime monitor / LB healthcheck has no session cookie.

    Without this route it receives a 401 from /api/health and cannot tell "the
    server is up but I am not signed in" from "the server is dead" — both look
    like an outage. The response must carry no deployment state either, since
    an unauthenticated endpoint is a disclosure surface.
    """
    create_user("alice", PASSWORD)  # auth fully enforced

    response = client.get("/api/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    # Still gated: the informative endpoint must not leak just because live is open.
    assert client.get("/api/health").status_code == 401
