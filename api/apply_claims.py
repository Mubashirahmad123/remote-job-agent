"""Transactional claim-first idempotency primitives for apply submissions."""

import math
import sqlite3
from datetime import datetime, timedelta, timezone

from api.apply_intents import IntentConsumed, IntentExpired


STALE_CLAIM_MINUTES = 15


class ClaimConflict(Exception):
    """Raised when a job already has a live or terminal submit claim."""

    def __init__(self, retry_after=None):
        super().__init__("A submit claim already exists for this job")
        self.retry_after = retry_after


class DailyCapExceeded(Exception):
    """Raised when creating a claim would exceed the daily submission cap."""

    def __init__(self, retry_after: int):
        super().__init__("Daily apply cap reached")
        self.retry_after = retry_after


def _add_column_if_missing(
    connection: sqlite3.Connection, table: str, column: str, declaration: str
) -> None:
    """Idempotent ADD COLUMN.

    SQLite has no `ADD COLUMN IF NOT EXISTS`, and every existing deployment
    already has these tables populated with real apply history — recreating
    them is not an option. So the schema is inspected first and the ALTER only
    runs when the column is genuinely absent. Mirrors the pattern already used
    in api/apply_state.py for the artifact columns.
    """
    existing = {
        row[1] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column not in existing:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")


def initialize_claim_store(connection: sqlite3.Connection) -> None:
    connection.execute(
        """CREATE TABLE IF NOT EXISTS apply_claims (
            job_fingerprint TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            claimed_at TEXT NOT NULL,
            cap_date TEXT NOT NULL,
            intent_hash TEXT NOT NULL,
            actor TEXT
        )"""
    )
    # `actor` was added after the table shipped; upgrade existing rows in place.
    # Nullable on purpose: a claim written before attribution existed has no
    # knowable author, and back-filling a guess would be worse than NULL.
    _add_column_if_missing(connection, "apply_claims", "actor", "TEXT")
    connection.execute(
        """CREATE TABLE IF NOT EXISTS daily_apply_caps (
            cap_date TEXT PRIMARY KEY,
            count INTEGER NOT NULL DEFAULT 0 CHECK (count >= 0)
        )"""
    )
    connection.commit()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _refund_cap_slot(connection: sqlite3.Connection, cap_date: str) -> None:
    connection.execute(
        "UPDATE daily_apply_caps SET count = MAX(0, count - 1) WHERE cap_date = ?",
        (cap_date,),
    )


def claim_first(
    connection: sqlite3.Connection,
    job_fingerprint: str,
    daily_cap: int,
    now: datetime | None = None,
    stale_after_minutes: int = STALE_CLAIM_MINUTES,
    intent_hash: str = "",
    intent_token_hash: str | None = None,
    actor: str = "",
) -> dict:
    """Reserve a unique job claim and daily-cap slot in one write transaction.

    `actor` is recorded on the claim row (see api.deps.resolve_actor). It is
    accepted but NOT required, because the daily cap is global rather than
    per-operator — attribution here is for forensics, not enforcement. An empty
    actor is stored as NULL so "unknown" stays distinguishable from a real name.
    """
    timestamp = _as_utc(now or datetime.now(timezone.utc))
    timestamp_text = timestamp.isoformat()
    cap_date = timestamp.date().isoformat()
    connection.execute("BEGIN IMMEDIATE")

    try:
        existing = connection.execute(
            "SELECT status, claimed_at, cap_date FROM apply_claims WHERE job_fingerprint = ?",
            (job_fingerprint,),
        ).fetchone()
        if existing:
            status, claimed_at_text, previous_cap_date = existing
            if status == "submit_in_progress":
                claimed_at = _as_utc(datetime.fromisoformat(claimed_at_text))
                expires_at = claimed_at + timedelta(minutes=stale_after_minutes)
                if timestamp > expires_at:
                    connection.execute(
                        "DELETE FROM apply_claims WHERE job_fingerprint = ?",
                        (job_fingerprint,),
                    )
                    _refund_cap_slot(connection, previous_cap_date)
                else:
                    retry_after = max(1, math.ceil((expires_at - timestamp).total_seconds()))
                    raise ClaimConflict(retry_after=retry_after)
            elif status == "failed_refunded":
                # Pre-click failure already refunded its cap slot at mark time;
                # drop the spent row so a corrected retry can claim fresh.
                connection.execute(
                    "DELETE FROM apply_claims WHERE job_fingerprint = ?",
                    (job_fingerprint,),
                )
            else:
                raise ClaimConflict()

        if intent_token_hash is not None:
            intent_row = connection.execute(
                "SELECT expires_at, consumed FROM apply_intents "
                "WHERE job_fingerprint = ? AND token_hash = ?",
                (job_fingerprint, intent_token_hash),
            ).fetchone()
            if intent_row is None or _as_utc(datetime.fromisoformat(intent_row[0])) <= timestamp:
                raise IntentExpired("Intent is missing or expired")
            if intent_row[1]:
                raise IntentConsumed("Intent has already been consumed")

        row = connection.execute(
            "SELECT count FROM daily_apply_caps WHERE cap_date = ?", (cap_date,)
        ).fetchone()
        current_count = row[0] if row else 0
        if current_count >= daily_cap:
            next_day = timestamp.replace(hour=0, minute=0, second=0, microsecond=0)
            next_day += timedelta(days=1)
            retry_after = max(1, math.ceil((next_day - timestamp).total_seconds()))
            raise DailyCapExceeded(retry_after)

        connection.execute(
            "INSERT INTO apply_claims "
            "(job_fingerprint, status, claimed_at, cap_date, intent_hash, actor) "
            "VALUES (?, 'submit_in_progress', ?, ?, ?, ?)",
            (
                job_fingerprint,
                timestamp_text,
                cap_date,
                intent_hash,
                (actor or "").strip() or None,
            ),
        )
        connection.execute(
            "INSERT INTO daily_apply_caps (cap_date, count) VALUES (?, 1) "
            "ON CONFLICT(cap_date) DO UPDATE SET count = count + 1",
            (cap_date,),
        )
        if intent_token_hash is not None:
            consumed = connection.execute(
                "UPDATE apply_intents SET consumed = 1 "
                "WHERE job_fingerprint = ? AND token_hash = ? AND consumed = 0",
                (job_fingerprint, intent_token_hash),
            )
            if consumed.rowcount != 1:
                raise IntentConsumed("Intent has already been consumed")
        connection.commit()
    except Exception:
        connection.rollback()
        raise

    return {
        "job_fingerprint": job_fingerprint,
        "status": "submit_in_progress",
        "claimed_at": timestamp_text,
        "cap_date": cap_date,
        "actor": (actor or "").strip() or None,
    }


def finalize_claim(
    connection: sqlite3.Connection,
    job_fingerprint: str,
    status: str,
) -> bool:
    """Persist a submit outcome while retaining its daily-cap reservation."""
    if status not in {"submitted", "submit_unverified"}:
        raise ValueError("Only submitted or submit_unverified are terminal outcomes")
    cursor = connection.execute(
        "UPDATE apply_claims SET status = ? "
        "WHERE job_fingerprint = ? AND status = 'submit_in_progress'",
        (status, job_fingerprint),
    )
    connection.commit()
    return cursor.rowcount == 1


def mark_pre_click_failure(connection: sqlite3.Connection, job_fingerprint: str) -> bool:
    """Mark a pre-click failure and refund its reserved daily-cap slot once."""
    connection.execute("BEGIN IMMEDIATE")
    try:
        row = connection.execute(
            "SELECT cap_date FROM apply_claims "
            "WHERE job_fingerprint = ? AND status = 'submit_in_progress'",
            (job_fingerprint,),
        ).fetchone()
        if row is None:
            connection.commit()
            return False
        _refund_cap_slot(connection, row[0])
        connection.execute(
            "UPDATE apply_claims SET status = 'failed_refunded' "
            "WHERE job_fingerprint = ?",
            (job_fingerprint,),
        )
        connection.commit()
        return True
    except Exception:
        connection.rollback()
        raise


def reconcile_failed_claim(connection: sqlite3.Connection, job_fingerprint: str) -> bool:
    """Refund a slot only when manual reconciliation marks an unverified claim failed."""
    connection.execute("BEGIN IMMEDIATE")
    try:
        row = connection.execute(
            "SELECT cap_date FROM apply_claims "
            "WHERE job_fingerprint = ? AND status = 'submit_unverified'",
            (job_fingerprint,),
        ).fetchone()
        if row is None:
            connection.commit()
            return False
        _refund_cap_slot(connection, row[0])
        connection.execute(
            "UPDATE apply_claims SET status = 'failed_refunded' "
            "WHERE job_fingerprint = ?",
            (job_fingerprint,),
        )
        connection.commit()
        return True
    except Exception:
        connection.rollback()
        raise