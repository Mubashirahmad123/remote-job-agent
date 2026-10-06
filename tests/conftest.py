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
