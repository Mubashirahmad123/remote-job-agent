"""Test hermeticity: never inherit the developer's real .env tokens.

`agents/*` call `load_dotenv()` at import, so a local `.env` containing
`API_TOKEN` / `APPLY_API_TOKEN` (even a trailing-comment artifact like
`API_TOKEN=  # comment`, which python-dotenv parses as a garbage non-empty
value) leaks into the test process and flips every unauthenticated route to
401. Tests that need a token set it explicitly via `monkeypatch.setenv`;
everything else must see a clean slate.
"""

import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# Captured at collection time, before any fixture has had the chance to patch
# it. Anything that finds this object missing has replaced it globally.
_ORIGINAL_AUTH_DB_PATH = None


def pytest_configure(config):
    global _ORIGINAL_AUTH_DB_PATH
    from api.auth import db_path

    _ORIGINAL_AUTH_DB_PATH = db_path


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
    """Clear the login AND action rate-limit buckets before and after every test.

    api.ratelimit is process-global by design (docker-compose runs the API with
    --workers 1, so in-process is exact). Pytest runs the whole suite in one
    process, and every TestClient presents the same peer address — without this
    the per-IP budget would accumulate across unrelated test files and a later
    login test would fail with a 429 that has nothing to do with what it is
    testing. Reset on both sides so a test that deliberately exhausts the
    budget cannot leak into the next one.
    """
    from api.ratelimit import reset_action_limiter, reset_login_limiter

    reset_login_limiter()
    reset_action_limiter()
    yield
    reset_login_limiter()
    reset_action_limiter()


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


@pytest.fixture(autouse=True)
def _no_global_db_path_leak(tmp_path):
    """Fail a test that inherited global DB state from the test before it.

    Module globals outlive the test that assigns them. A fixture written as
    `auth.db_path = lambda: Path(tmp_path / "auth.db")` — rather than
    `monkeypatch.setattr(...)` — silently re-points the store at a tmp_path
    pytest deletes at teardown. The damage never shows up in the test that
    caused it: it surfaces in every LATER test as a bare ValueError from deep
    inside api/auth.py, which points nowhere near the real culprit.

    That is not hypothetical. Two lines in a `client` fixture did exactly this
    and turned 116 unrelated tests red across eight files.

    Checked at SETUP, not teardown, for two reasons:

    * `monkeypatch` restores during its own finalisation, which happens after
      this fixture's teardown — comparing values at teardown would flag every
      correctly-written monkeypatch fixture as a false positive.
    * `_isolate_apply_state_db` re-patches `apply_state.DB_PATH` at the start
      of every test, so a leak there is invisible to any check. `api.auth
      .db_path` is the one global nothing re-establishes: conftest sets the
      AUTH_DB_PATH env var and lets `db_path()` read it lazily. So it is both
      the leak that actually bites and the one that can be observed.
    """
    from api import apply_state
    from api.auth import db_path

    if db_path is not _ORIGINAL_AUTH_DB_PATH:
        pytest.fail(
            "api.auth.db_path was replaced by a previous test and never "
            "restored (use monkeypatch.setattr, not a plain assignment). "
            "Every test from here on would read a deleted tmp_path."
        )
    if REPO_ROOT in apply_state.DB_PATH.parents:
        pytest.fail(
            f"api.apply_state.DB_PATH escaped test isolation: "
            f"{apply_state.DB_PATH}"
        )
    if tmp_path not in apply_state.DB_PATH.parents:
        pytest.fail(
            f"api.apply_state.DB_PATH is outside this test's tmp_path: "
            f"{apply_state.DB_PATH}"
        )
