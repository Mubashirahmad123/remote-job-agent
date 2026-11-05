"""Shadow-DB hermeticity: test fixtures must never reach the live shadow DB.

The leak (discovered 2026-11-04): `agents/curator.py` calls `load_dotenv()`
at import, so a developer's `.env` with
`MATCHING_SHADOW_PROFILE=data/matching_profile.json` leaked into pytest;
every test whose fixture jobs flowed through `curator.curate()` then wrote
real decisions — including synthetic `job_fingerprint: "backend"`/`"frontend"`
jobs from tests/test_multi_cv_semantic.py — into the live
`data/matching_shadow.db` (20 rows, 2 of them `rejected`).

The fix lives in tests/conftest.py (`_isolate_shadow_db`); these tests prove
it holds for the whole suite and would re-detect a regression.

Constraints honored (tests/MATCHING_QA.md + repo testing guidelines):
no network, no Sheets, no live LLM calls; the live shadow DB is only ever
read (row COUNT, never content) and only to prove it was not touched.
"""
import os
import sqlite3
from pathlib import Path

from tools.matching_shadow import run_optional_shadow

import json


REPO_ROOT = Path(__file__).resolve().parents[1]
LIVE_DB = REPO_ROOT / "data" / "matching_shadow.db"


def _write_profile(tmp_path: Path, name: str = "profile.json") -> Path:
    """Minimal valid operator profile (same shape tests/test_matching_shadow uses)."""
    data = {
        "policy": {
            "role_families": ["fullstack", "backend", "frontend"],
            "work_locations": ["india"],
            "seniority_levels": ["junior", "mid"],
            "relocation_destinations": ["india"],
            "sponsorship_required": False,
        },
        "skills": ["python", "react"],
        "version": "test-v1",
        "learnable_skills": [],
    }
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _leak_fixture_jobs():
    """The EXACT fixture shape that leaked: tests/test_multi_cv_semantic.jobs()."""
    return [
        {"job_title": "Python Backend Developer", "summary": "Python FastAPI PostgreSQL",
         "apply_url": "https://example.com/backend", "job_fingerprint": "backend"},
        {"job_title": "React Frontend Developer", "summary": "React JavaScript CSS",
         "apply_url": "https://example.com/frontend", "job_fingerprint": "frontend"},
    ]


def _live_db_count() -> int:
    """Read-only count of the live shadow DB; 0 when absent (fresh CI)."""
    if not LIVE_DB.exists():
        return 0
    conn = sqlite3.connect(f"file:{LIVE_DB.as_posix()}?mode=ro", uri=True)
    try:
        return conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]
    finally:
        conn.close()


class TestSuiteIsolation:
    def test_shadow_profile_env_is_absent_in_every_test(self):
        """The conftest guard: PROFILE deleted, DB pinned into tmp_path.

        If this fails, a developer's .env leaked through again and the WHOLE
        matching suite is capable of writing the live shadow DB (the original
        bug). conftest resolves MATCHING_SHADOW_DB lazily per test, so the
        value must sit inside this test's own tmp_path.
        """
        leaked = os.getenv("MATCHING_SHADOW_PROFILE")
        assert not leaked, (
            f"MATCHING_SHADOW_PROFILE leaked into the test process: {leaked!r}. "
            "tests/conftest.py::_isolate_shadow_db must delete it — with the "
            "operator profile active, curator.curate() in any test writes "
            "fixture-jobs decisions to the live data/matching_shadow.db."
        )
        db = os.getenv("MATCHING_SHADOW_DB", "")
        tmp = db or "<unset>"
        assert db, "MATCHING_SHADOW_DB must be pinned by conftest"
        assert "shadow_test.db" in db, f"unexpected shadow db target: {db}"

    def test_disabled_hook_writes_nothing_without_profile(self):
        before = _live_db_count()
        assert run_optional_shadow(_leak_fixture_jobs()) is None
        assert _live_db_count() == before


class TestLeakReproduction:
    def test_optin_writes_only_to_pinned_tmp_db(self, tmp_path):
        """Reproduce the original leak under the guarded env.

        Set ONLY the profile var (the typical mistake: a test enables shadow
        and forgets the DB path). Before the conftest fix, `run_optional_shadow`
        fell back to the repo's `data/matching_shadow.db` and the fixture jobs
        below were appended there — they reached the DB even as `rejected`.
        With the fix, the fallback lands in tmp_path and the live DB never
        gains a row.
        """
        before_live = _live_db_count()
        monkey_profile = _write_profile(tmp_path)
        os.environ["MATCHING_SHADOW_PROFILE"] = str(monkey_profile)
        try:
            results = run_optional_shadow(_leak_fixture_jobs())
        finally:
            os.environ.pop("MATCHING_SHADOW_PROFILE", None)
        assert set(results) == {"backend", "frontend"}
        # The pytest-pinned DB received exactly the two fixture decisions.
        pinned = Path(os.environ["MATCHING_SHADOW_DB"])
        assert pinned.exists()
        conn = sqlite3.connect(pinned)
        try:
            ids = {row[0] for row in conn.execute("SELECT job_id FROM decisions")}
        finally:
            conn.close()
        assert ids == {"backend", "frontend"}
        # The live DB is untouched, before vs after.
        assert _live_db_count() == before_live
