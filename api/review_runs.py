"""Durable result handoff for bounded-wait fill-only requests.

No browser, LLM or submit code here. A run is owned by its fill claim. Updates
and artifact writes verify ownership under a SQLite write lock, so a late old
worker cannot replace evidence from a newer attempt.
"""
import json
from datetime import datetime, timezone
from uuid import uuid4


def initialize_review_run_store(connection):
    connection.execute("""CREATE TABLE IF NOT EXISTS apply_review_runs (
        job_fingerprint TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        claimed_at TEXT NOT NULL,
        state TEXT NOT NULL,
        result_json TEXT,
        started_at TEXT NOT NULL
    )""")


def assert_fill_owner(connection, fingerprint, claimed_at):
    if claimed_at is None:
        return  # compatibility for non-worker artifact/CLI writers
    row = connection.execute(
        "SELECT claimed_at FROM apply_fill_claims WHERE job_fingerprint = ?",
        (fingerprint,),
    ).fetchone()
    if row is None or row[0] != claimed_at:
        raise RuntimeError("Review worker no longer owns this fill claim")


def begin_run(connection, fingerprint, claimed_at):
    run_id = uuid4().hex
    connection.execute("BEGIN IMMEDIATE")
    try:
        assert_fill_owner(connection, fingerprint, claimed_at)
        connection.execute("""INSERT INTO apply_review_runs
            (job_fingerprint, run_id, claimed_at, state, started_at)
            VALUES (?, ?, ?, 'pending', ?)
            ON CONFLICT(job_fingerprint) DO UPDATE SET run_id=excluded.run_id,
              claimed_at=excluded.claimed_at, state='pending', result_json=NULL,
              started_at=excluded.started_at""",
            (fingerprint, run_id, claimed_at, datetime.now(timezone.utc).isoformat()))
        # Regeneration must not serve the previous screenshot while new work
        # is pending, or let intent creation reuse that old review evidence.
        connection.execute("DELETE FROM apply_review_artifacts WHERE job_fingerprint = ?", (fingerprint,))
        connection.commit()
        return run_id
    except BaseException:
        connection.rollback()
        raise


def finish_run(connection, fingerprint, run_id, claimed_at, result):
    connection.execute("BEGIN IMMEDIATE")
    try:
        assert_fill_owner(connection, fingerprint, claimed_at)
        changed = connection.execute("""UPDATE apply_review_runs
            SET state='complete', result_json=?
            WHERE job_fingerprint=? AND run_id=? AND claimed_at=? AND state='pending'""",
            (json.dumps(result), fingerprint, run_id, claimed_at)).rowcount
        connection.commit()
        return changed == 1
    except BaseException:
        connection.rollback()
        raise


def read_run(connection, fingerprint, run_id=None):
    # Read run + claim from ONE snapshot. Otherwise a worker can commit its
    # result and release the claim between these SELECTs, turning a successful
    # completion into a false "worker stopped" error for the polling client.
    owns_transaction = not connection.in_transaction
    if owns_transaction:
        connection.execute("BEGIN")
    try:
        return _read_run_snapshot(connection, fingerprint, run_id)
    finally:
        if owns_transaction:
            connection.rollback()  # read-only; release snapshot/reader lock


def _read_run_snapshot(connection, fingerprint, run_id=None):
    row = connection.execute("SELECT * FROM apply_review_runs WHERE job_fingerprint=?", (fingerprint,)).fetchone()
    if row is None:
        raise LookupError("No review run exists for this job")
    if run_id is not None and run_id != row['run_id']:
        raise ValueError("Review run was replaced by a newer attempt")
    if row['state'] == 'complete':
        return {**json.loads(row['result_json']), 'review_run_id': row['run_id']}
    # A process restart/crash must not leave clients polling forever. Claims
    # expire by heartbeat; a newer attempt must never be confused with this one.
    from api.fill_claims import list_active_fill_fingerprints
    owner = connection.execute("SELECT claimed_at FROM apply_fill_claims WHERE job_fingerprint=?", (fingerprint,)).fetchone()
    if owner is None or owner[0] != row['claimed_at'] or fingerprint not in list_active_fill_fingerprints(connection):
        return {'status': 'error', 'job_fingerprint': fingerprint, 'review_run_id': row['run_id'],
                'fill_error': 'Review worker stopped or its claim expired; use Regenerate to retry.',
                'screenshot_url': None, 'submit_enabled': False}
    return {'status': 'review_pending', 'job_fingerprint': fingerprint,
            'review_run_id': row['run_id'], 'screenshot_url': None, 'submit_enabled': False}


def expire_run(connection, fingerprint, run_id, claimed_at, result):
    """Fence an over-deadline worker atomically before permitting any retry."""
    connection.execute("BEGIN IMMEDIATE")
    try:
        assert_fill_owner(connection, fingerprint, claimed_at)
        changed = connection.execute("""UPDATE apply_review_runs SET state='complete', result_json=?
            WHERE job_fingerprint=? AND run_id=? AND claimed_at=? AND state='pending'""",
            (json.dumps(result), fingerprint, run_id, claimed_at)).rowcount
        if changed:
            connection.execute("DELETE FROM apply_review_artifacts WHERE job_fingerprint=?", (fingerprint,))
            connection.execute("DELETE FROM apply_fill_claims WHERE job_fingerprint=? AND claimed_at=?",
                               (fingerprint, claimed_at))
        connection.commit()
        return changed == 1
    except BaseException:
        connection.rollback()
        raise
