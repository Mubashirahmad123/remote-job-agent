"""Test hermeticity: never inherit the developer's real .env tokens.

`agents/*` call `load_dotenv()` at import, so a local `.env` containing
`API_TOKEN` / `APPLY_API_TOKEN` (even a trailing-comment artifact like
`API_TOKEN=  # comment`, which python-dotenv parses as a garbage non-empty
value) leaks into the test process and flips every unauthenticated route to
401. Tests that need a token set it explicitly via `monkeypatch.setenv`;
everything else must see a clean slate.
"""

import os

import pytest


@pytest.fixture(autouse=True)
def _clear_api_tokens(monkeypatch):
    monkeypatch.delenv("API_TOKEN", raising=False)
    monkeypatch.delenv("APPLY_API_TOKEN", raising=False)


@pytest.fixture(autouse=True)
def _isolate_auth_db(tmp_path, monkeypatch):
    """Point the auth store at a per-test SQLite file.

    api.auth.db_path() resolves env lazily, so a user created in one test
    never leaks into another (or into the developer's real
    data/apply_submit.db, which would flip unauthenticated routes to 401).
    AUTH_DB_PATH wins over APPLY_STATE_DB_PATH, so apply-state tests that set
    the latter keep their own isolation.
    """
    monkeypatch.setenv("AUTH_DB_PATH", str(tmp_path / "auth_test.db"))


@pytest.fixture(autouse=True)
def _isolate_apply_state_db(tmp_path, monkeypatch):
    """Point the apply-state store at a per-test SQLite file.

    `api.apply_state.DB_PATH` is resolved ONCE, at import time, from
    APPLY_STATE_DB_PATH — unlike `api.auth.db_path()`, which reads the env on
    every call. So setting the env var alone does nothing here: the module
    attribute has to be patched, or any test reaching `apply_state.connect()`
    writes to the developer's real `data/apply_submit.db`. Run the suite on a
    production host and that means creating — and potentially populating — the
    live claims/intents/review-artifact tables. Verified: without this fixture a
    full `pytest tests/` recreates data/apply_submit.db.

    Every consumer imports the module or its functions (`from api import
    apply_state`, `from api.apply_state import connect`), never `DB_PATH` by
    value, so patching the attribute is seen everywhere.

    The value must be a `Path`, not a `str`: `connect()` calls
    `DB_PATH.parent.mkdir()`, and a str raises AttributeError.
    """
    from api import apply_state

    target = tmp_path / "apply_state_test.db"
    # Env too, so anything spawned as a subprocess inherits the same isolation.
    monkeypatch.setenv("APPLY_STATE_DB_PATH", str(target))
    monkeypatch.setattr(apply_state, "DB_PATH", target)


@pytest.fixture(autouse=True)
def _disarm_submit_env(monkeypatch):
    """Never inherit an armed submit switch from the developer's shell/.env.

    `api.safety.submit_enabled()` honours SUBMIT_ENABLED / SUBMIT_DRY_RUN so a
    live run can be armed for one process without editing tracked code. That
    means a leftover `SUBMIT_ENABLED=true` would otherwise silently turn every
    "must fail closed with 403" assertion into a false pass — the exact class
    of bug these tests exist to catch. Tests that want the path open set the
    constants explicitly via monkeypatch.
    """
    monkeypatch.delenv("SUBMIT_ENABLED", raising=False)
    monkeypatch.delenv("SUBMIT_DRY_RUN", raising=False)


@pytest.fixture(autouse=True)
def _isolate_submit_artifacts(monkeypatch, tmp_path):
    """Keep submit/dry-run evidence dirs out of the repo during tests."""
    monkeypatch.setenv("SUBMIT_ARTIFACT_DIR", str(tmp_path / "submit_runs"))


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Clear login rate-limit buckets before AND after every test.

    api.ratelimit is process-global by design (docker-compose runs the API with
    --workers 1, so in-process is exact). Pytest runs the whole suite in one
    process, and every TestClient presents the same peer address — without this
    the per-IP budget would accumulate across unrelated test files and a later
    login test would fail with a 429 that has nothing to do with what it is
    testing. Reset on both sides so a test that deliberately exhausts the
    budget cannot leak into the next one.
    """
    from api.ratelimit import reset_login_limiter

    reset_login_limiter()
    yield
    reset_login_limiter()


@pytest.fixture(autouse=True)
def _forget_auth_schema_memo():
    """Drop api.auth's per-process "schema already built" memo.

    `connect()` now runs its DDL once per (process, db path) instead of on
    every request. Each test gets a fresh tmp_path AUTH_DB_PATH, so the memo is
    naturally keyed differently — but clearing it keeps an accidental
    cross-test path collision from silently skipping table creation, which
    would surface as a confusing "no such table" rather than a real failure.
    """
    from api.auth import forget_initialized

    forget_initialized()
    yield
    forget_initialized()
