"""
tests/test_suite_hermeticity.py

Pins the isolation guarantees that tests/conftest.py makes. These deserve tests
of their own because the failure mode is invisible: a suite that quietly writes
into the developer's real `data/apply_submit.db` still passes every assertion,
and on a production host it creates — and can populate — the live claims,
intents and review-artifact tables as a side effect of running pytest.

Both leaks this guards against were real and were found by deleting the file and
watching it reappear:

* `api.apply_state.DB_PATH` is resolved at IMPORT time, so setting
  `APPLY_STATE_DB_PATH` in a fixture does nothing on its own; the module
  attribute has to be patched.
* the e2e harness isolated `AUTH_DB_PATH` but not `APPLY_STATE_DB_PATH`, so a
  suite run still created the apply tables in the repo's data directory.
"""

import os
import sqlite3
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"


def _repo_db_files() -> set:
    """Every SQLite file (and WAL/SHM sibling) currently in the repo's data/."""
    if not DATA_DIR.exists():
        return set()
    return {p.name for p in DATA_DIR.glob("*.db*")}


ARTIFACT = {
    "job_fingerprint": "hermetic-fp",
    "platform": "greenhouse",
    "job_title": "Hermetic Engineer",
    "apply_url": "https://boards.example.com/hermetic",
    "package_path": "pkg/hermetic.zip",
    "match_ratio": 0.5,
    "fill_status": "filled_ready",
    "created_at": "2026-10-08T00:00:00+00:00",
    "actor": "hermetic-test",
}


class TestApplyStateIsolation:
    def test_db_path_points_into_the_per_test_tmp_dir(self, tmp_path):
        from api import apply_state

        assert apply_state.DB_PATH == tmp_path / "apply_state_test.db"
        assert REPO_ROOT not in apply_state.DB_PATH.parents

    def test_db_path_is_a_path_not_a_str(self):
        # connect() calls DB_PATH.parent.mkdir(); a str raises AttributeError
        # rather than doing something merely wrong.
        from api import apply_state

        assert isinstance(apply_state.DB_PATH, Path)

    def test_env_var_agrees_with_the_patched_attribute(self):
        # The env var alone would NOT isolate anything (DB_PATH is read once, at
        # import), but the two must agree or a subprocess spawned by a test would
        # land on a different database than the test itself.
        from api import apply_state

        assert os.environ["APPLY_STATE_DB_PATH"] == str(apply_state.DB_PATH)

    def test_a_real_write_lands_in_the_tmp_store_and_not_in_the_repo(self):
        from api import apply_state

        before = _repo_db_files()
        apply_state.save_review_artifact(dict(ARTIFACT))
        assert _repo_db_files() == before, (
            "pytest wrote a SQLite file into the repo's data/ directory"
        )

        connection = sqlite3.connect(apply_state.DB_PATH)
        try:
            rows = connection.execute(
                "SELECT job_fingerprint, actor FROM apply_review_artifacts"
            ).fetchall()
        finally:
            connection.close()
        assert ("hermetic-fp", "hermetic-test") in rows

    def test_connect_creates_the_claim_and_intent_tables_in_the_tmp_store(self):
        from api import apply_state

        before = _repo_db_files()
        connection = apply_state.connect()
        tables = {
            r[0]
            for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        connection.close()
        assert {"apply_claims", "apply_intents", "apply_review_artifacts"} <= tables
        assert _repo_db_files() == before


class TestAuthIsolation:
    def test_auth_db_path_is_per_test(self, tmp_path):
        from api.auth import db_path

        assert db_path() == tmp_path / "auth_test.db"
        assert REPO_ROOT not in db_path().parents

    def test_creating_a_user_never_touches_the_repo_data_dir(self):
        from api.auth import create_user, db_path

        before = _repo_db_files()
        create_user("hermetic-user", "CorrectHorse9")
        assert _repo_db_files() == before, (
            "creating a user wrote into the repo's data/ directory"
        )

        connection = sqlite3.connect(db_path())
        try:
            usernames = [
                r[0] for r in connection.execute("SELECT username FROM users").fetchall()
            ]
        finally:
            connection.close()
        assert usernames == ["hermetic-user"]

    def test_auth_db_path_wins_over_apply_state_db_path(self):
        # Both fixtures are autouse, so this is the combination every test in the
        # suite actually runs under: auth and apply state must land in DIFFERENT
        # files, or a user row would be written into the apply database.
        from api import apply_state
        from api.auth import db_path

        assert db_path() != apply_state.DB_PATH

    def test_a_user_created_here_is_not_visible_to_the_next_test(self):
        from api.auth import count_users, create_user

        create_user("isolation-probe", "CorrectHorse9")
        assert count_users() == 1
        # The next test gets a fresh tmp_path and therefore a fresh store; this
        # assertion is what makes that observable rather than assumed.


class TestNoLeakedStateBetweenTests:
    def test_the_previous_test_left_no_users_behind(self):
        from api.auth import count_users

        assert count_users() == 0

    def test_the_previous_test_left_no_artifacts_behind(self):
        from api import apply_state

        connection = apply_state.connect()
        try:
            count = connection.execute(
                "SELECT count(*) FROM apply_review_artifacts"
            ).fetchone()[0]
        finally:
            connection.close()
        assert count == 0


class TestRepoDataDirIsNotABuildArtifact:
    def test_data_directory_is_gitignored(self):
        # If this ever stops being true, a test run could stage a database
        # containing Argon2id password hashes for commit.
        gitignore = (REPO_ROOT / ".gitignore").read_text()
        assert any(
            line.strip() in ("data/", "data/*.db", "/data/")
            for line in gitignore.splitlines()
        ), "data/ is no longer gitignored"

    def test_no_database_under_data_is_tracked_by_git(self):
        import subprocess

        result = subprocess.run(
            ["git", "ls-files", "data/"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            pytest.skip("git unavailable")
        tracked = [line for line in result.stdout.splitlines() if line.strip()]
        databases = [t for t in tracked if t.endswith((".db", ".sqlite", ".sqlite3"))]
        assert not databases, f"databases are tracked by git: {databases}"
