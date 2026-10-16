"""Fill-only work outlives the HTTP wait, not its ownership lease.

No submit code. Results are durably handed off, not discarded in a queue.
The watchdog bounds claim lifetime even if an underlying browser call hangs;
Python cannot forcibly kill that thread, so ownership checks fence late writes.
"""
import logging
import os
import time
from threading import Event, Thread
from urllib.parse import quote

from api import apply_state
from api.fill_claims import refresh_fill_claim, release_fill_claim
from api.review_runs import begin_run, finish_run, expire_run

logger = logging.getLogger(__name__)
HEARTBEAT_SECONDS = 15
MAX_REVIEW_RUN_SECONDS = 30 * 60


def fill_wait_seconds():
    """Foreground wait only; never a license to submit. Bound malformed env."""
    try:
        return max(1, min(600, int(os.getenv('APPLY_FILL_TIMEOUT', '180'))))
    except (TypeError, ValueError):
        return 180


def run_review(fingerprint, claimed_at, work):
    connection = apply_state.connect()
    try:
        run_id = begin_run(connection, fingerprint, claimed_at)
    finally:
        connection.close()
    completed = Event()
    stop = Event()
    outcome = {}
    started = time.monotonic()

    def failure(message):
        return {'status': 'error', 'job_fingerprint': fingerprint,
                'review_run_id': run_id, 'fill_error': message,
                'screenshot_url': None, 'submit_enabled': False}

    def heartbeat_loop():
        while not stop.wait(HEARTBEAT_SECONDS):
            conn = None
            try:
                conn = apply_state.connect()
                if time.monotonic() - started >= MAX_REVIEW_RUN_SECONDS:
                    result = failure('Review exceeded its 30-minute work limit; use Regenerate to retry.')
                    if expire_run(conn, fingerprint, run_id, claimed_at, result):
                        outcome['result'] = result
                        completed.set()
                    return
                if not refresh_fill_claim(conn, fingerprint, claimed_at):
                    return  # lost ownership; writes are fenced by the DB guard
            except Exception:
                logger.exception('Review heartbeat/watchdog failed for %s', fingerprint)
            finally:
                if conn is not None:
                    conn.close()

    def worker():
        try:
            result = work()
            conn = apply_state.connect()
            try:
                if not finish_run(conn, fingerprint, run_id, claimed_at, result):
                    raise RuntimeError('Review run is no longer pending')
            finally:
                conn.close()
            outcome['result'] = {**result, 'review_run_id': run_id}
        except Exception as error:
            logger.exception('Review fill failed for %s after %.2fs', fingerprint, time.monotonic() - started)
            # The synchronous caller keeps its existing exception contract.
            # A later status read gets a safe message, not private exception data.
            outcome['error'] = error
            try:
                conn = apply_state.connect()
                try:
                    finish_run(conn, fingerprint, run_id, claimed_at,
                               failure('Review fill failed. Check server logs; use Regenerate to retry.'))
                finally:
                    conn.close()
            except Exception:
                logger.exception('Could not finalize failed review for %s', fingerprint)
        finally:
            stop.set()
            try:
                conn = apply_state.connect()
                try:
                    release_fill_claim(conn, fingerprint, claimed_at)
                finally:
                    conn.close()
            except Exception:
                logger.exception('Could not release review claim for %s', fingerprint)
            finally:
                completed.set()

    # The caller releases the claim on setup/start failure. Once started the
    # worker owns release, including after the HTTP caller has returned pending.
    watch = Thread(target=heartbeat_loop, name='review-heartbeat', daemon=True)
    watch.start()
    try:
        Thread(target=worker, name='review-fill', daemon=True).start()
    except BaseException:
        stop.set()
        raise
    if completed.wait(fill_wait_seconds()):
        if 'error' in outcome and 'result' not in outcome:
            raise outcome['error']
        return outcome['result']
    logger.info('Review %s run %s still pending after %.2fs foreground wait',
                fingerprint, run_id, time.monotonic() - started)
    return {'status': 'review_pending', 'mode': 'review', 'job_fingerprint': fingerprint,
            'review_run_id': run_id, 'screenshot_path': None, 'screenshot_url': None,
            'review_status_url': f'/api/apply/{quote(fingerprint, safe="")}/review-status?run_id={run_id}',
            'submit_enabled': False}
