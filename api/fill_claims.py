"""Atomic in-progress claims for fill/review package generation.

Real bug this closes (2026-10-13 live session): two near-simultaneous
"Fill & Review" clicks each ran GET /api/apply/queue, both got the same top
jobs, and both follow-up POST /api/apply/{fp} requests passed the "no
package yet" check â€” record_package only runs AFTER the slow part (LLM
resume + cover letter + package folder) completes, so for the whole
minutes-long window the package index cannot see an in-flight fill. Result:
duplicate tailored resumes, duplicate cover-letter passes, and duplicate
apply_packages/ folders for the same job (Bling + Wheely in that session).

Why a dedicated table instead of an "in progress" row in apply_package_index:
the index is the completed-set memory â€” list_packaged_fingerprints() reads
EVERY row as "this job has a package", and /api/apply/packages reports that
list verbatim to the dashboard. Inserting in-progress rows there would make
a half-built job indistinguishable from a packaged one (and make
get_package_record point at a folder that does not exist yet). "In progress"
and "packaged" are different states, so they get different tables.

Lifecycle: claim BEFORE any generation starts (fill_review), refresh the
heartbeat at each pipeline stage and periodically during browser work, release when the fill ends either way — the
package index row is the durable record, the claim is only the in-flight
lock. A claim abandoned by a crashed process self-expires after
STALE_FILL_CLAIM_MINUTES of silence, and release_fill_claim deletes only the
row matching the caller's own claimed_at so a slow-but-alive fill can never
drop a fresher claim reclaimed over it.

Why the heartbeat exists: liveness is judged on heartbeat_at, never on
claimed_at. One fill legitimately runs for minutes (LLM resume, then LLM
cover letter, then a slow ATS fill with periodic worker heartbeats). A TTL measured
from the start would expire partway through a perfectly healthy fill, a
second request would reclaim the job, and both would generate — the exact
duplicate-package bug this module exists to close, returning silently.
Heartbeating separates "this worker died" from "this worker is slow", which
a single start-time TTL cannot do.
"""

import math
import sqlite3
from datetime import datetime, timedelta, timezone

STALE_FILL_CLAIM_MINUTES = 15


class FillInProgress(Exception):
    """Raised when a fill for this fingerprint is already in flight.

    The router maps it to 409 â€” a skip, not an error: the in-flight request
    is the one that will deliver the package.
    """

    def __init__(
        self,
        job_fingerprint: str,
        claimed_at: str = "",
        retry_after: int | None = None,
    ):
        super().__init__(f"A fill for job '{job_fingerprint}' is already in progress")
        self.job_fingerprint = job_fingerprint
        self.claimed_at = claimed_at
        self.retry_after = retry_after


def initialize_fill_claim_store(connection: sqlite3.Connection) -> None:
    connection.execute(
        """CREATE TABLE IF NOT EXISTS apply_fill_claims (
            job_fingerprint TEXT PRIMARY KEY,
            claimed_at TEXT NOT NULL,
            heartbeat_at TEXT NOT NULL,
            actor TEXT
        )"""
    )
    # Idempotent migration, same convention as apply_state.connect(): SQLite
    # has no ADD COLUMN IF NOT EXISTS and existing deployments hold real apply
    # history. COALESCE(heartbeat_at, claimed_at) below keeps pre-migration
    # rows live for exactly as long as their claimed_at would have implied.
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(apply_fill_claims)")
    }
    if "heartbeat_at" not in columns:
        connection.execute(
            "ALTER TABLE apply_fill_claims ADD COLUMN heartbeat_at TEXT"
        )
    connection.commit()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def claim_fill(
    connection: sqlite3.Connection,
    job_fingerprint: str,
    now: datetime | None = None,
    stale_after_minutes: int = STALE_FILL_CLAIM_MINUTES,
    actor: str = "",
) -> dict:
    """Atomically claim one fingerprint for fill generation, or raise.

    BEGIN IMMEDIATE serializes racing claims on the same row across threads
    (uvicorn runs sync routes in a threadpool) and processes, so exactly one
    concurrent caller ever gets "you generate" for a given job.

    Liveness is judged on heartbeat_at, NOT claimed_at. A fill is minutes
    long (LLM resume + cover letter + a slow ATS fill),
    so a fixed TTL measured from the start would expire *during* a healthy
    fill and let a second request reclaim the job while the first is still
    generating — the duplicate-package bug, silently. The worker instead
    calls refresh_fill_claim at each stage and every 15 seconds during the fill,
    so the TTL means "no heartbeat for this long" (crashed), not "has been running for this long".
    """
    timestamp = _as_utc(now or datetime.now(timezone.utc))
    timestamp_text = timestamp.isoformat()
    connection.execute("BEGIN IMMEDIATE")
    try:
        existing = connection.execute(
            "SELECT claimed_at, heartbeat_at FROM apply_fill_claims "
            "WHERE job_fingerprint = ?",
            (job_fingerprint,),
        ).fetchone()
        if existing is not None:
            # claimed_at is the ownership token and never moves; heartbeat_at
            # is what decides whether the owner is still alive.
            last_seen_text = existing[1] or existing[0]
            last_seen = _as_utc(datetime.fromisoformat(last_seen_text))
            expires_at = last_seen + timedelta(minutes=stale_after_minutes)
            if timestamp <= expires_at:
                retry_after = max(1, math.ceil((expires_at - timestamp).total_seconds()))
                raise FillInProgress(job_fingerprint, existing[0], retry_after)
            # Stale (the claiming process died mid-fill): the lock
            # self-expires and the job becomes claimable again instead of
            # disappearing from the queue forever.
            connection.execute(
                "DELETE FROM apply_fill_claims WHERE job_fingerprint = ?",
                (job_fingerprint,),
            )
        connection.execute(
            "INSERT INTO apply_fill_claims "
            "(job_fingerprint, claimed_at, heartbeat_at, actor) "
            "VALUES (?, ?, ?, ?)",
            (job_fingerprint, timestamp_text, timestamp_text,
             (actor or "").strip() or None),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return {
        "job_fingerprint": job_fingerprint,
        "claimed_at": timestamp_text,
        "heartbeat_at": timestamp_text,
        "actor": (actor or "").strip() or None,
    }


def refresh_fill_claim(
    connection: sqlite3.Connection,
    job_fingerprint: str,
    claimed_at: str,
    now: datetime | None = None,
) -> bool:
    """Prove the owner of this claim is still working. Returns False if the
    claim was already taken over, in which case the caller must stop.

    Ownership-scoped by claimed_at for the same reason release is: a fill
    that lost its claim to a heartbeat gap must NOT revive it, or two workers
    would generate the same job and both believe they owned it.
    """
    cursor = connection.execute(
        "UPDATE apply_fill_claims SET heartbeat_at = ? "
        "WHERE job_fingerprint = ? AND claimed_at = ?",
        (_as_utc(now or datetime.now(timezone.utc)).isoformat(),
         job_fingerprint, claimed_at),
    )
    connection.commit()
    return cursor.rowcount == 1


def release_fill_claim(
    connection: sqlite3.Connection,
    job_fingerprint: str,
    claimed_at: str,
) -> bool:
    """Drop the caller's own claim; never a fresher one taken over it.

    A fill whose heartbeat gap was long enough for another request to
    reclaim the job may finish afterwards; deleting THAT row would re-open
    the exact double-generation window the claim exists to close. Matching
    claimed_at keeps releases ownership-scoped.
    """
    cursor = connection.execute(
        "DELETE FROM apply_fill_claims WHERE job_fingerprint = ? AND claimed_at = ?",
        (job_fingerprint, claimed_at),
    )
    connection.commit()
    return cursor.rowcount == 1


def list_active_fill_fingerprints(
    connection: sqlite3.Connection,
    now: datetime | None = None,
    stale_after_minutes: int = STALE_FILL_CLAIM_MINUTES,
) -> set[str]:
    """Fingerprints with a live in-flight fill (queue eligibility).

    Judged on heartbeat_at so a long but healthy generation keeps its claim.
    Stale rows are ignored, not deleted: a job whose fill crashed is hidden
    from the queue only until its claim expires, then re-surfaces on its
    own (and the next POST reclaims the row either way).
    """
    timestamp = _as_utc(now or datetime.now(timezone.utc))
    cutoff = (timestamp - timedelta(minutes=stale_after_minutes)).isoformat()
    return {
        row[0]
        for row in connection.execute(
            "SELECT job_fingerprint FROM apply_fill_claims "
            "WHERE COALESCE(heartbeat_at, claimed_at) > ?",
            (cutoff,),
        ).fetchall()
        if row[0]
    }
