"""Fill & Review must not reprocess the same top-N jobs.

Real bug this pins: clicking "Fill & Review Up to 3 Jobs" twice with no new
scrape in between re-selected and re-processed the same three highest-scoring
jobs every time — burning three LLM resume/cover-letter passes and dropping a
second (and third, fourth…) timestamped folder per job under
``apply_packages/``, with no way to progress past the current top three.

The fix records every prepared package in ``apply_package_index`` (one row per
fingerprint) and selects the next-best UNPROCESSED jobs from it. The second
click must therefore either process *different* jobs (the next-best three) or
report "no new eligible jobs" — never silently regenerate the same three.

Fully offline: fakes ``api.cache`` reads, the ATS filler, and package
generation. ``api.apply_state``'s DB is isolated to a per-test tmp file by
``tests/conftest.py``.
"""

import os
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient

from api import apply as apply_service
from api import apply_state
from api import cache
from api.app import create_app

THRESHOLD = 70
LIMIT = 3


def _job(fingerprint: str, score: int) -> dict:
    return {
        "job_fingerprint": fingerprint,
        "job_title": f"Engineer {fingerprint}",
        "company": f"Company {fingerprint}",
        # Non-Greenhouse/Lever URL -> package-only path, no browser fill.
        "apply_url": f"https://example.com/jobs/{fingerprint}",
        "match_score": score,
    }


def _jobs() -> list:
    """Five fillable, non-dream jobs in descending score order + one dream job."""
    return [
        _job("fp-a", 88),
        _job("fp-b", 84),
        _job("fp-c", 80),
        _job("fp-d", 76),
        _job("fp-e", 72),
        _job("fp-dream", 95),  # >= dream threshold: manual-only, never queued
    ]


@pytest.fixture()
def client(tmp_path, monkeypatch):
    # Mirror the auth setup used in test_api_apply.py so this file runs in the
    # same unsandboxed .env as the rest of the suite.
    monkeypatch.setenv("API_TOKEN", "test-apply-secret")
    monkeypatch.setenv("APPLY_API_TOKEN", "test-apply-secret")
    monkeypatch.setenv("APPLY_STATE_DB_PATH", str(tmp_path / "apply_state.db"))
    from pathlib import Path

    import api.auth as AU
    import api.apply_state as AS

    # monkeypatch.setattr, NOT plain assignment: these module attributes
    # outlive the test, so re-pointing them permanently would hand every
    # LATER test a DB path inside a tmp_path pytest deletes at teardown
    # (it surfaces as a ValueError deep inside api/auth.py, far from the
    # real culprit). DB_PATH must stay a Path — connect() calls .parent.mkdir().
    monkeypatch.setattr(AS, "DB_PATH", Path(tmp_path / "apply_state.db"))
    monkeypatch.setattr(AU, "db_path", lambda: Path(tmp_path / "auth.db"))
    AU.forget_initialized()
    try:
        yield TestClient(create_app(), raise_server_exceptions=False)
    finally:
        AU.forget_initialized()


_AUTH_HEADERS = {"Authorization": "Bearer test-apply-secret"}


def _install(monkeypatch, jobs, tracker_rows=None):
    """Fake the Sheets reads + the expensive pipeline calls for these tests."""
    by_fp = {j["job_fingerprint"]: j for j in jobs}
    monkeypatch.setattr(cache, "get_jobs", lambda tab="ALL JOBS", force=False: list(jobs))
    monkeypatch.setattr(cache, "get_job", lambda fp: by_fp.get(fp))
    monkeypatch.setattr(
        cache, "get_tracker_rows", lambda status=None, force=False: list(tracker_rows or [])
    )

    import agents.auto_applier as aa

    monkeypatch.setattr(
        aa,
        "generate_apply_package",
        lambda job, resume, letter, output_folder="apply_packages": f"/tmp/pkg/{job['job_fingerprint']}",
    )
    monkeypatch.setattr(
        apply_service,
        "_fill_ats_form",
        lambda job, *args, **kwargs: {
            "status": "package_only",
            "screenshot_path": None,
            "error": None,
        },
    )
    monkeypatch.setattr(
        apply_service,
        "_prepare_submit_materials",
        lambda job: {
            "resume_path": "/tmp/fake-resume.pdf",
            "cover_letter_text": "Fake tailored cover letter for queue tests.",
        },
    )

    # The read routes (GET /api/apply/queue, /api/apply/packages) depend on
    # `require_token`. conftest clears API_TOKEN around each test, so patch the
    # deps module attribute the same way the other API test files do. Nothing
    # here weakens submit: POST /api/apply/{fp} still goes through
    # require_actor + action_budget, and /intent + /submit keep their own
    # require_apply_token / require_submit_actor gates.
    import api.deps as deps

    monkeypatch.setattr(deps, "require_token", lambda request, creds=None: None)
    monkeypatch.setattr(deps, "require_apply_token", lambda request, creds=None: None)


def _queue(client, threshold=THRESHOLD, limit=LIMIT):
    response = client.get(
        f"/api/apply/queue?threshold={threshold}&limit={limit}",
        headers=_AUTH_HEADERS,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _fingerprints(body):
    return [j["job_fingerprint"] for j in body["jobs"]]


def _prepare(client, fingerprint, *, headers=None):
    return client.post(
        f"/api/apply/{fingerprint}",
        json={"mode": "review"},
        headers=headers or _AUTH_HEADERS,
    )


class TestQueueSelectsUnprocessedJobs:
    def test_first_click_selects_top_three(self, client, monkeypatch):
        _install(monkeypatch, _jobs())
        assert _fingerprints(_queue(client)) == ["fp-a", "fp-b", "fp-c"]

    def test_second_click_processes_different_jobs(self, client, monkeypatch):
        """The acceptance criterion: click twice, no scrape in between."""
        _install(monkeypatch, _jobs())

        first = _fingerprints(_queue(client))
        assert first == ["fp-a", "fp-b", "fp-c"]
        for fingerprint in first:
            assert _prepare(client, fingerprint).status_code == 200

        second = _fingerprints(_queue(client))
        assert second, "second click should find the next-best matches"
        assert not (set(second) & set(first)), (
            f"second click repeated already-packaged jobs: {second}"
        )
        assert second == ["fp-d", "fp-e"]

    def test_second_click_reports_no_new_eligible_jobs_when_pool_is_spent(
        self, client, monkeypatch
    ):
        # Exactly three eligible jobs and a limit of three: one click exhausts it.
        _install(monkeypatch, _jobs()[:3])

        first = _fingerprints(_queue(client))
        assert first == ["fp-a", "fp-b", "fp-c"]
        for fingerprint in first:
            assert _prepare(client, fingerprint).status_code == 200

        body = _queue(client)
        assert body["jobs"] == [], "an empty queue must be reported, not a repeat run"

    def test_empty_queue_explains_itself(self, client, monkeypatch):
        _install(monkeypatch, _jobs()[:3])
        for fingerprint in _fingerprints(_queue(client)):
            _prepare(client, fingerprint)

        body = _queue(client)
        assert body["jobs"] == []
        # The UI shows these counts to say WHY nothing was queued.
        assert body["excluded"]["packaged"] == 3
        assert body["eligible_total"] == 0


class TestNoDuplicatePackages:
    def test_repeat_prepare_without_regenerate_is_refused(self, client, monkeypatch):
        _install(monkeypatch, _jobs()[:1])

        assert _prepare(client, "fp-a").status_code == 200
        repeat = _prepare(client, "fp-a")

        assert repeat.status_code == 409
        assert "already has a package" in repeat.json()["detail"]
        assert apply_state.list_packaged_fingerprints() == {"fp-a"}

    def test_refused_repeat_never_generates_materials(self, client, monkeypatch):
        """The 409 must happen BEFORE the expensive LLM pass, or the fix does
        nothing for the wasted-calls half of the bug."""
        _install(monkeypatch, _jobs()[:1])
        calls = []

        def _record(job):
            calls.append(job)
            return {
                "resume_path": "/tmp/fake-resume.pdf",
                "cover_letter_text": "Fake tailored cover letter for queue tests.",
            }

        monkeypatch.setattr(apply_service, "_prepare_submit_materials", _record)

        assert _prepare(client, "fp-a").status_code == 200
        assert _prepare(client, "fp-a").status_code == 409

        assert len(calls) == 1, "a refused repeat still generated materials"

    def test_regenerate_is_the_deliberate_override(self, client, monkeypatch):
        _install(monkeypatch, _jobs()[:1])

        assert _prepare(client, "fp-a").status_code == 200
        rebuilt = client.post(
            "/api/apply/fp-a",
            json={"mode": "review", "regenerate": True},
            headers={"Authorization": "Bearer test-apply-secret"},
        )

        assert rebuilt.status_code == 200, rebuilt.text
        assert rebuilt.json()["regenerated"] is True
        # Upsert, not a second row: "has this job been packaged?" stays a
        # single lookup even after a deliberate rebuild.
        assert apply_state.list_packaged_fingerprints() == {"fp-a"}


class TestExclusionsBeyondPackages:
    def test_dream_tier_jobs_are_not_queued(self, client, monkeypatch):
        _install(monkeypatch, _jobs())
        body = _queue(client)
        assert "fp-dream" not in _fingerprints(body)
        assert body["excluded"]["dream"] == 1

    def test_tracked_jobs_are_not_queued(self, client, monkeypatch):
        _install(monkeypatch, _jobs()[:3], tracker_rows=[{"job_fingerprint": "fp-a"}])
        body = _queue(client)
        assert _fingerprints(body) == ["fp-b", "fp-c"]
        assert body["excluded"]["tracked"] == 1

    def test_tracker_rows_keyed_only_by_url_are_still_excluded(self, client, monkeypatch):
        _install(
            monkeypatch,
            _jobs()[:3],
            tracker_rows=[{"apply_url": "https://example.com/jobs/fp-a"}],
        )
        body = _queue(client)
        assert _fingerprints(body) == ["fp-b", "fp-c"]

    def test_below_threshold_jobs_are_counted_not_queued(self, client, monkeypatch):
        _install(monkeypatch, _jobs())
        body = _queue(client, threshold=85)
        assert _fingerprints(body) == ["fp-a"]
        assert body["excluded"]["below_threshold"] == 4


class TestPackagedFingerprintEndpoint:
    def test_reports_prepared_fingerprints(self, client, monkeypatch):
        _install(monkeypatch, _jobs()[:2])
        headers = {"Authorization": "Bearer test-apply-secret"}
        assert client.get("/api/apply/packages", headers=_AUTH_HEADERS).json() == {"fingerprints": [], "count": 0}

        _prepare(client, "fp-a")
        _prepare(client, "fp-b")

        assert client.get("/api/apply/packages", headers=_AUTH_HEADERS).json() == {
            "fingerprints": ["fp-a", "fp-b"],
            "count": 2,
        }


class TestUnknownTabIs400:
    """AUDIT B9 (2026-10-28): the queue's `tab` query reaches
    cache.get_jobs' JOB_TABS validation; apply.py maps the ValueError to a
    400 (like /api/jobs and /api/skills — those get their own tests too).
    A caller error must never surface as a 500 or hit Sheets at all."""

    def test_unknown_tab_is_400_not_500(self, client):
        # No _install: validation must fire before any sheet/tabs read.
        r = client.get(
            "/api/apply/queue?tab=APPLIED", headers=_AUTH_HEADERS)
        assert r.status_code == 400
        body = r.json()
        assert "Unknown jobs tab" in body["detail"]
        assert "incident" not in body["detail"]


class TestRapidDoubleFireProcessesEachJobOnce:
    """Two overlapping Fill & Review clicks must not double-generate.

    Real bug (2026-10-13 live session logs): two near-simultaneous
    GET /api/apply/queue calls both selected the same top jobs (Bling,
    Wheely), and BOTH follow-up POST /api/apply/{fp} requests passed the
    "no package yet" check — record_package only runs AFTER generation
    finishes, so for the whole minutes-long window the package index
    cannot see an in-flight fill. Both jobs were processed twice:
    duplicate resumes, duplicate cover-letter passes, duplicate
    apply_packages/ folders.

    The fix claims the fingerprint atomically BEFORE generation starts
    (api.fill_claims), so the loser of the race is refused with 409
    having burned zero LLM calls, and the queue skips in-progress jobs
    in favor of the next-best eligible ones.
    """

    def _counting_materials(self, monkeypatch, block_fp=None):
        """Patch _prepare_submit_materials to count generation passes per
        fingerprint; the pass for `block_fp` parks mid-generation until the
        test releases it, simulating the minutes-long LLM window."""
        counts = {}
        started = threading.Event()
        release = threading.Event()
        lock = threading.Lock()

        def _materials(job):
            fp = job["job_fingerprint"]
            with lock:
                counts[fp] = counts.get(fp, 0) + 1
            if fp == block_fp:
                started.set()
                assert release.wait(timeout=30), "test never released the blocked fill"
            return {
                "resume_path": "/tmp/fake-resume.pdf",
                "cover_letter_text": "Fake tailored cover letter for queue tests.",
            }

        monkeypatch.setattr(apply_service, "_prepare_submit_materials", _materials)
        return counts, started, release

    def test_overlapping_clicks_process_each_job_exactly_once(
        self, client, monkeypatch
    ):
        _install(monkeypatch, _jobs())
        counts, started, release = self._counting_materials(
            monkeypatch, block_fp="fp-a"
        )

        # The precondition from the live logs: two rapid queue reads see the
        # same top three because nothing is claimed or packaged yet.
        click1_selection = _fingerprints(_queue(client))
        click2_selection = _fingerprints(_queue(client))
        assert click1_selection == click2_selection == ["fp-a", "fp-b", "fp-c"]

        # Click 1 starts filling its top job; the fill parks mid-generation
        # holding the in-progress claim (the second tab in the live session).
        click1_result = {}

        def _first_click_fills_fp_a():
            click1_result["outcome"] = apply_service.fill_review(
                "fp-a", actor="tab-1"
            )

        first_fill = threading.Thread(target=_first_click_fills_fp_a, daemon=True)
        first_fill.start()
        assert started.wait(timeout=30), "first click never started generating fp-a"

        # Click 2, while fp-a is mid-generation:
        # - the queue must SKIP the in-progress job and surface the NEXT
        #   best eligible ones, not re-select fp-a.
        second_queue = _queue(client)
        assert "fp-a" not in _fingerprints(second_queue)
        assert _fingerprints(second_queue) == ["fp-b", "fp-c", "fp-d"]
        assert second_queue["excluded"]["in_progress"] == 1

        # - a duplicate POST for the SAME job (stale selection, double
        #   click) is refused with 409 "in progress" and generates nothing.
        assert counts["fp-a"] == 1
        duplicate = _prepare(client, "fp-a")
        assert duplicate.status_code == 409
        assert "already in progress" in duplicate.json()["detail"]
        assert counts["fp-a"] == 1, "a refused duplicate fill still generated"

        # - click 2 moves on cleanly to a job nobody is working on.
        assert _prepare(client, "fp-b").status_code == 200

        release.set()
        first_fill.join(timeout=30)
        assert click1_result["outcome"]["status"] == "package_only"

        # Exactly once across both clicks — never twice.
        assert counts == {"fp-a": 1, "fp-b": 1}
        assert apply_state.list_packaged_fingerprints() == {"fp-a", "fp-b"}

    def test_back_to_back_queue_clicks_process_each_job_once(
        self, client, monkeypatch
    ):
        """The acceptance criterion, sequentially: fire two queue requests for
        the same pool, process whatever each returns, and no eligible job may
        be processed twice across both requests."""
        _install(monkeypatch, _jobs())
        counts, _, _ = self._counting_materials(monkeypatch)

        processed = []
        for _click in range(2):
            for fingerprint in _fingerprints(_queue(client)):
                response = _prepare(client, fingerprint)
                if response.status_code == 200:
                    processed.append(fingerprint)
                else:
                    # Refused is acceptable; re-processed is not.
                    assert response.status_code == 409, response.text

        assert processed, "the pool has five eligible jobs; none were processed"
        assert sorted(processed) == sorted(set(processed)), (
            f"a job was processed twice across the two clicks: {processed}"
        )
        assert sorted(processed) == ["fp-a", "fp-b", "fp-c", "fp-d", "fp-e"]
        assert counts == {fp: 1 for fp in processed}, (
            "every processed job generated materials exactly once"
        )


class TestConcurrentPostsForOneJob:
    """Two POSTs for the SAME fingerprint must not both generate.

    The other tests in this file drive the queue and the fills in sequence,
    which is a simulation of the double-click rather than the thing itself.
    The live failure was genuinely concurrent: two HTTP requests, each on
    its own threadpool worker, reaching claim_fill at the same instant. If
    the claim is not atomic that race produces two packages, and this test
    is the one that notices.
    """

    def test_simultaneous_posts_yield_one_success_and_the_rest_409(
        self, client, monkeypatch
    ):
        _install(monkeypatch, _jobs()[:1])
        generations = []
        lock = threading.Lock()

        def _materials(job):
            # Simulate the slow LLM window so the losers must overlap it.
            threading.Event().wait(0.05)
            with lock:
                generations.append(job["job_fingerprint"])
            return {
                "resume_path": "/tmp/fake-resume.pdf",
                "cover_letter_text": "Fake tailored cover letter for queue tests.",
            }

        monkeypatch.setattr(apply_service, "_prepare_submit_materials", _materials)

        racers = 6
        start = threading.Barrier(racers)
        statuses: list[int] = []
        status_lock = threading.Lock()

        def _post():
            start.wait(timeout=30)
            response = _prepare(client, "fp-a")
            with status_lock:
                statuses.append(response.status_code)

        threads = [
            threading.Thread(target=_post, daemon=True) for _ in range(racers)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
        assert not any(t.is_alive() for t in threads), "racer thread hung"

        assert len(statuses) == racers
        assert statuses.count(200) == 1, f"expected exactly one winner, got {statuses}"
        # 409, never 500: a lost race is a skip, not a server error. A 500
        # here would mean the loser hit an IntegrityError instead of the
        # handled FillInProgress — i.e. the claim stopped being atomic.
        assert set(statuses) <= {200, 409}, f"unexpected statuses: {statuses}"
        assert statuses.count(409) == racers - 1

        # The real assertion: one LLM pass, one package, one index row.
        assert generations == ["fp-a"], f"generated more than once: {generations}"
        assert apply_state.list_packaged_fingerprints() == {"fp-a"}

    def test_a_refused_racer_leaves_no_claim_behind(self, client, monkeypatch):
        """Losers must not strand claims — that would hide the job forever."""
        _install(monkeypatch, _jobs())

        def _materials(job):
            threading.Event().wait(0.05)
            return {
                "resume_path": "/tmp/fake-resume.pdf",
                "cover_letter_text": "Fake tailored cover letter for queue tests.",
            }

        monkeypatch.setattr(apply_service, "_prepare_submit_materials", _materials)

        racers = 4
        start = threading.Barrier(racers)
        statuses: list[int] = []
        status_lock = threading.Lock()

        def _post():
            start.wait(timeout=30)
            response = _prepare(client, "fp-a")
            with status_lock:
                statuses.append(response.status_code)

        threads = [
            threading.Thread(target=_post, daemon=True) for _ in range(racers)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
        assert not any(t.is_alive() for t in threads), "racer thread hung"

        assert statuses.count(200) == 1, f"expected exactly one winner, got {statuses}"

        from api.apply_state import connect

        conn = connect()
        try:
            stranded = conn.execute(
                "SELECT COUNT(*) FROM apply_fill_claims WHERE job_fingerprint = ?",
                ("fp-a",),
            ).fetchone()[0]
        finally:
            conn.close()
        assert stranded == 0, "the finished fill did not release its claim"

        # And the job is immediately queueable again.
        assert _fingerprints(_queue(client)) == ["fp-b", "fp-c", "fp-d"]

    def test_the_claim_is_taken_before_the_already_packaged_check(
        self, client, monkeypatch
    ):
        """Pin the ORDER, which the race above depends on.

        Checking "already packaged?" before taking the claim is a
        time-of-check/time-of-use hole. A second request can read "no package
        yet", lose the CPU, and by the time it reaches claim_fill the first
        request has finished AND released its claim — so it claims a job that
        is now packaged and both generate. That is the original bug, and it
        reproduced here roughly one run in four until the order was swapped.

        Asserting it directly is deterministic; the race above only proves it
        probabilistically, so this is the test that stops the regression from
        quietly coming back.
        """
        _install(monkeypatch, _jobs()[:1])
        order = []

        import api.apply_state as AS

        real_claim = apply_service.claim_fill
        # fill_review imports get_package_record lazily inside the function,
        # so it must be patched where it is defined, not on api.apply.
        real_record = AS.get_package_record

        def _claim(*args, **kwargs):
            order.append("claim")
            return real_claim(*args, **kwargs)

        def _record(*args, **kwargs):
            order.append("package_check")
            return real_record(*args, **kwargs)

        # claim_fill is bound at api.apply's import, so that is the binding the
        # route actually calls; patching api.fill_claims would miss it.
        monkeypatch.setattr(apply_service, "claim_fill", _claim)
        monkeypatch.setattr(AS, "get_package_record", _record)

        assert _prepare(client, "fp-a").status_code == 200

        assert order[:2] == ["claim", "package_check"], (
            "the packaged check must happen UNDER the claim; checked first it "
            f"is a TOCTOU race (observed order: {order})"
        )
