"""Real review worker/routes/SQLite, fake browser and material boundaries only.

Events exercise the HTTP wait boundary without sleeping 90/180 seconds.
No job board, credentials, model, real browser, intent or submit is used.
"""
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api import apply as service, apply_state, cache, review_worker
from api.app import create_app
from api.fill_claims import FillInProgress, STALE_FILL_CLAIM_MINUTES, claim_fill, list_active_fill_fingerprints
from api.review_runs import begin_run, read_run

FP = 'review-handoff-job'
JOB = {'job_fingerprint': FP, 'job_title': 'Developer', 'company': 'Fixture',
       'apply_url': 'https://boards.greenhouse.io/fixture/jobs/1', 'match_score': 76}
HEADERS = {'Authorization': 'Bearer handoff-test-only'}


def until(condition):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        result = condition()
        if result:
            return result
        time.sleep(.005)
    raise AssertionError('Review worker did not reach expected state')


@pytest.fixture
def setup(monkeypatch, tmp_path):
    import agents.auto_applier as aa
    original_threads = set(threading.enumerate())
    gate = threading.Event()
    entered = threading.Event()
    state = {'calls': 0, 'block': True}
    lock = threading.Lock()

    def filler(*args):
        with lock:
            index = state['calls']
            state['calls'] += 1
        entered.set()
        if state['block'] and index == 0:
            assert gate.wait(5), 'test must release the fake browser'
        path = tmp_path / f'owned-{index}.png'
        path.write_bytes(f'image-{index}'.encode())
        return {'status': 'filled_ready', 'screenshot_path': str(path),
                'confirmation_path': '/fixture/thanks', 'confirmation_message': 'Fixture received',
                'field_verification': state.get('verification', 'verified'),
                'profile_fields_verified': ['first_name', 'email']}

    class Browser:
        def new_page(self, **kwargs):
            return SimpleNamespace(wait_for_event=lambda *a, **k: None)
        def close(self):
            pass

    class Playwright:
        def __enter__(self):
            return SimpleNamespace(chromium=SimpleNamespace(launch=lambda **kwargs: Browser()))
        def __exit__(self, *args):
            pass

    monkeypatch.setattr(aa, '_get_playwright', lambda: Playwright)
    monkeypatch.setattr(aa, '_is_container', lambda: True)
    monkeypatch.setattr(aa, '_fill_greenhouse_form', filler)
    monkeypatch.setattr(aa, 'classify_tier', lambda job: 'good_fit')
    monkeypatch.setattr(aa, 'generate_apply_package', lambda *a, **k: str(tmp_path / 'package'))
    monkeypatch.setattr(cache, 'get_job', lambda fp: {**JOB, 'job_fingerprint': fp})
    monkeypatch.setattr(service, '_prepare_submit_materials', lambda job: {
        'resume_path': str(tmp_path / 'resume.pdf'), 'cover_letter_text': 'Synthetic cover text'})
    monkeypatch.setattr(review_worker, 'fill_wait_seconds', lambda: .02)
    monkeypatch.setattr(review_worker, 'HEARTBEAT_SECONDS', .01)
    monkeypatch.setenv('API_TOKEN', 'handoff-test-only')
    with TestClient(create_app(), headers=HEADERS) as client:
        yield SimpleNamespace(client=client, gate=gate, entered=entered, state=state)
        gate.set()
        for thread in set(threading.enumerate()) - original_threads:
            if thread.name in {'review-fill', 'review-heartbeat', 'apply-review-browser'}:
                thread.join(6)
                assert not thread.is_alive(), thread.name


def poll(client, run):
    return client.get(run['review_status_url']).json()


def terminal(client, run):
    return until(lambda: (result if (result := poll(client, run))['status'] != 'review_pending' else None))


@pytest.mark.parametrize('value,expected', [(None, 180), ('', 180), ('bad', 180),
    ('nan', 180), ('-1', 1), ('0', 1), ('42', 42), ('900', 600)])
def test_foreground_timeout_configuration(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv('APPLY_FILL_TIMEOUT', raising=False)
    else:
        monkeypatch.setenv('APPLY_FILL_TIMEOUT', value)
    # setup fixture intentionally overrides this function, so use no setup here.
    assert review_worker.fill_wait_seconds() == expected


def test_late_completion_saves_owned_image_metadata_actor_and_real_screenshot_route(setup):
    response = setup.client.post(f'/api/apply/{FP}', json={})
    assert response.status_code == 200
    pending = response.json()
    assert pending['status'] == 'review_pending'
    assert pending['screenshot_url'] is None
    assert pending['submit_enabled'] is False
    assert setup.entered.wait(2)
    assert apply_state.get_review_artifact(FP) is None
    # No unowned image guessed while pending. Once the exact path arrives,
    # the API route is usable, not permanently stuck at the old 404.
    setup.gate.set()
    result = terminal(setup.client, pending)
    assert result['status'] == 'filled_ready'
    assert result['confirmation_metadata_available'] is True
    assert result['field_verification'] == 'verified'
    assert result['profile_fields_verified'] == ['first_name', 'email']
    image = setup.client.get(result['screenshot_url'])
    assert image.status_code == 200
    assert image.content == b'image-0'
    artifact = apply_state.get_review_artifact(FP)
    assert artifact['confirmation_path'] == '/fixture/thanks'
    assert artifact['confirmation_message'] == 'Fixture received'
    assert artifact['actor'] == 'automation'
    assert artifact['cover_letter_text'] == 'Synthetic cover text'
    assert setup.state['calls'] == 1


def test_pending_work_keeps_claim_and_duplicate_regenerate_does_not_launch_browser(setup):
    run = setup.client.post(f'/api/apply/{FP}', json={}).json()
    assert run['status'] == 'review_pending'
    conn = apply_state.connect()
    try:
        before = conn.execute('SELECT heartbeat_at FROM apply_fill_claims WHERE job_fingerprint=?', (FP,)).fetchone()[0]
        until(lambda: conn.execute('SELECT heartbeat_at FROM apply_fill_claims WHERE job_fingerprint=?', (FP,)).fetchone()[0] != before)
        assert FP in list_active_fill_fingerprints(conn)
    finally:
        conn.close()
    response = setup.client.post(f'/api/apply/{FP}', json={'regenerate': True})
    assert response.status_code == 409
    assert setup.state['calls'] == 1
    setup.gate.set()
    assert terminal(setup.client, run)['status'] == 'filled_ready'


def test_regeneration_hides_previous_evidence_and_rejects_stale_run_id(setup):
    setup.state['block'] = False
    first = setup.client.post(f'/api/apply/{FP}', json={}).json()
    if first['status'] == 'review_pending':
        first = terminal(setup.client, first)
    assert first['status'] == 'filled_ready'
    # Block the next request with a test boundary, not an actual slow board.
    original = service._fill_ats_form
    service._fill_ats_form = lambda *a, **k: (setup.gate.wait(5), original(*a, **k))[1]
    try:
        second = setup.client.post(f'/api/apply/{FP}', json={'regenerate': True}).json()
        assert second['status'] == 'review_pending'
        assert apply_state.get_review_artifact(FP) is None
        assert setup.client.get(f'/api/apply/{FP}/screenshot').status_code == 404
        assert setup.client.get(f'/api/apply/{FP}/review-status', params={'run_id': first['review_run_id']}).status_code == 409
        setup.gate.set()
        final = terminal(setup.client, second)
        assert setup.client.get(final['screenshot_url']).content == b'image-1'
    finally:
        setup.gate.set()
        service._fill_ats_form = original


def test_watchdog_fences_old_result_without_overwriting_a_newer_retry(setup, monkeypatch):
    first = setup.client.post(f'/api/apply/{FP}', json={}).json()
    assert setup.entered.wait(2)
    monkeypatch.setattr(review_worker, 'MAX_REVIEW_RUN_SECONDS', 0)
    failed = terminal(setup.client, first)
    assert failed['status'] == 'error'
    assert 'work limit' in failed['fill_error']
    # Retry gets its own run/claim; the first browser is still held at a gate.
    monkeypatch.setattr(review_worker, 'MAX_REVIEW_RUN_SECONDS', 1800)
    second = setup.client.post(f'/api/apply/{FP}', json={'regenerate': True}).json()
    if second['status'] == 'review_pending':
        second = terminal(setup.client, second)
    assert second['status'] == 'filled_ready'
    setup.gate.set()
    until(lambda: (Path(apply_state.get_review_artifact(FP)['screenshot_path']).parent / 'owned-0.png').exists())
    # Join old workers before asserting no late overwrite (not a timing guess).
    for thread in list(threading.enumerate()):
        if thread.name in {'review-fill', 'apply-review-browser'}:
            thread.join(3)
    assert setup.client.get(second['screenshot_url']).content == b'image-1'
    assert setup.client.get(f'/api/apply/{FP}/review-status', params={'run_id': first['review_run_id']}).status_code == 409


def test_two_fingerprints_never_share_a_result_or_image(setup):
    first = setup.client.post(f'/api/apply/{FP}', json={}).json()
    second = setup.client.post('/api/apply/other-job', json={}).json()
    if second['status'] == 'review_pending':
        second = terminal(setup.client, second)
    assert second['job_fingerprint'] == 'other-job'
    setup.gate.set()
    first = terminal(setup.client, first)
    assert first['screenshot_path'] != second['screenshot_path']
    assert setup.client.get(first['screenshot_url']).content == b'image-0'
    assert setup.client.get(second['screenshot_url']).content == b'image-1'


def test_status_reads_are_authenticated_and_unknown_run_is_404(setup):
    assert setup.client.get(f'/api/apply/{FP}/review-status', headers={'Authorization': ''}).status_code == 401
    assert setup.client.get('/api/apply/no-run/review-status').status_code == 404


def test_crashed_or_reclaimed_worker_is_reported_without_endless_polling():
    conn = apply_state.connect()
    try:
        t0 = datetime.now(timezone.utc) - timedelta(minutes=STALE_FILL_CLAIM_MINUTES + 1)
        claim = claim_fill(conn, FP, now=t0)
        run_id = begin_run(conn, FP, claim['claimed_at'])
        result = read_run(conn, FP, run_id)
        assert result['status'] == 'error'
        assert result['screenshot_url'] is None
    finally:
        conn.close()


def test_unique_screenshot_stamps_even_with_same_clock_tick(monkeypatch):
    import agents.auto_applier as aa
    class FixedTime:
        @staticmethod
        def now():
            return datetime(2026, 10, 15, 12, 0, 0)
    monkeypatch.setattr(aa, 'datetime', FixedTime)
    stamps = {aa._review_screenshot_stamp() for _ in range(100)}
    assert len(stamps) == 100
    assert all(stamp.startswith('20261015_120000_') for stamp in stamps)


def test_heartbeat_cadence_is_safely_inside_claim_ttl():
    assert review_worker.HEARTBEAT_SECONDS < STALE_FILL_CLAIM_MINUTES * 60 / 2
    assert review_worker.MAX_REVIEW_RUN_SECONDS > review_worker.HEARTBEAT_SECONDS


def test_late_unverified_fields_remain_needs_review(setup):
    setup.state['verification'] = 'unavailable'
    run = setup.client.post(f'/api/apply/{FP}', json={}).json()
    setup.gate.set()
    result = terminal(setup.client, run)
    assert result['status'] == 'needs_review'
    assert result['submit_enabled'] is False
    assert apply_state.get_review_artifact(FP)['fill_status'] == 'needs_review'
    assert setup.client.get(result['screenshot_url']).status_code == 200


def test_persistence_failure_does_not_publish_broken_image_url(setup, monkeypatch):
    def fail(_artifact):
        raise RuntimeError('dummy-private-storage-detail')
    monkeypatch.setattr(apply_state, 'save_review_artifact', fail)
    run = setup.client.post(f'/api/apply/{FP}', json={}).json()
    setup.gate.set()
    result = terminal(setup.client, run)
    assert result['status'] == 'error'
    assert result['screenshot_url'] is None
    assert 'dummy-private-storage-detail' not in str(result)
    assert apply_state.get_review_artifact(FP) is None
    conn = apply_state.connect()
    try:
        until(lambda: FP not in list_active_fill_fingerprints(conn))
    finally:
        conn.close()


def test_poll_completion_and_claim_release_use_one_sqlite_snapshot():
    """Force completion between the run-row and claim-row SELECTs.

    Without the read transaction this deterministically reports a false worker
    failure. With it the poll sees pending, then the next poll sees success.
    """
    import json
    conn = apply_state.connect()
    claim = claim_fill(conn, FP)
    run_id = begin_run(conn, FP, claim['claimed_at'])
    finished = threading.Event()
    errors = []
    threads = []

    def complete():
        writer = apply_state.connect()
        try:
            writer.execute("UPDATE apply_review_runs SET state='complete', result_json=? WHERE job_fingerprint=?",
                           (json.dumps({'status': 'filled_ready', 'submit_enabled': False}), FP))
            writer.execute('DELETE FROM apply_fill_claims WHERE job_fingerprint=?', (FP,))
            writer.commit()
        except Exception as error:
            errors.append(error)
        finally:
            writer.close()
            finished.set()

    class SnapshotConnection:
        def __getattr__(self, name):
            return getattr(conn, name)

        def execute(self, sql, *args):
            cursor = conn.execute(sql, *args)
            if sql.startswith('SELECT * FROM apply_review_runs'):
                class Cursor:
                    def fetchone(self):
                        row = cursor.fetchone()
                        thread = threading.Thread(target=complete)
                        threads.append(thread)
                        thread.start()
                        if not conn.in_transaction:
                            assert finished.wait(5)
                        return row
                return Cursor()
            return cursor

    try:
        result = read_run(SnapshotConnection(), FP, run_id)
        assert result['status'] == 'review_pending'
        assert finished.wait(5)
        assert not errors
        assert read_run(conn, FP, run_id)['status'] == 'filled_ready'
    finally:
        conn.rollback()
        for thread in threads:
            thread.join(6)
            assert not thread.is_alive()
        conn.close()
