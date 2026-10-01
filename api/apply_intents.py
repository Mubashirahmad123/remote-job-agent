"""Atomic one-live-intent-per-fingerprint primitive."""

import hashlib
import hmac
import math
import sqlite3
from datetime import datetime, timezone


class ActiveIntentConflict(Exception):
    """Raised when the fingerprint already has an unexpired intent."""

    def __init__(self, retry_after: int):
        super().__init__("An unexpired intent already exists for this job")
        self.retry_after = retry_after


class IntentExpired(Exception):
    """Raised when an intent is missing, expired, or belongs to another fp."""


class IntentConsumed(Exception):
    """Raised when the fingerprint's intent has already been consumed."""


def initialize_intent_store(connection: sqlite3.Connection) -> None:
    connection.execute(
        """CREATE TABLE IF NOT EXISTS apply_intents (
            job_fingerprint TEXT PRIMARY KEY,
            token_hash TEXT UNIQUE NOT NULL,
            expires_at TEXT NOT NULL,
            consumed INTEGER NOT NULL DEFAULT 0 CHECK (consumed IN (0, 1))
        )"""
    )
    connection.commit()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def create_intent(
    connection: sqlite3.Connection,
    job_fingerprint: str,
    intent_token: str,
    expires_at: datetime,
    now: datetime | None = None,
) -> dict:
    """Create or replace an expired intent under a serialized write lock."""
    timestamp = _as_utc(now or datetime.now(timezone.utc))
    expiration = _as_utc(expires_at)
    if expiration <= timestamp:
        raise ValueError("Intent expiry must be in the future")
    token_hash = hashlib.sha256(intent_token.encode("utf-8")).hexdigest()

    connection.execute("BEGIN IMMEDIATE")
    try:
        existing = connection.execute(
            "SELECT expires_at, consumed FROM apply_intents WHERE job_fingerprint = ?",
            (job_fingerprint,),
        ).fetchone()
        if existing:
            existing_expiry = _as_utc(datetime.fromisoformat(existing[0]))
            # A consumed intent is single-use and spent: allow replacement with
            # a fresh token instead of forcing the operator to wait out the TTL.
            if existing[1] and existing_expiry > timestamp:
                connection.execute(
                    "DELETE FROM apply_intents WHERE job_fingerprint = ?",
                    (job_fingerprint,),
                )
            elif existing_expiry > timestamp:
                retry_after = max(
                    1, math.ceil((existing_expiry - timestamp).total_seconds())
                )
                raise ActiveIntentConflict(retry_after)

        connection.execute(
            "INSERT INTO apply_intents "
            "(job_fingerprint, token_hash, expires_at, consumed) "
            "VALUES (?, ?, ?, 0) ON CONFLICT(job_fingerprint) DO UPDATE SET "
            "token_hash = excluded.token_hash, expires_at = excluded.expires_at, consumed = 0",
            (job_fingerprint, token_hash, expiration.isoformat()),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise

    return {
        "job_fingerprint": job_fingerprint,
        "token_hash": token_hash,
        "expires_at": expiration.isoformat(),
        "consumed": False,
    }


def live_intent_retry_after(
    connection: sqlite3.Connection,
    job_fingerprint: str,
    now: datetime | None = None,
) -> int | None:
    """Return retry_after seconds when a live (unexpired, unconsumed) intent exists.

    Read-only pre-check so callers can reject duplicates BEFORE expensive
    work (material generation) or state mutation (artifact rewrites).
    Returns None when a fresh intent may be issued (none, expired, consumed).
    """
    timestamp = _as_utc(now or datetime.now(timezone.utc))
    row = connection.execute(
        "SELECT expires_at, consumed FROM apply_intents WHERE job_fingerprint = ?",
        (job_fingerprint,),
    ).fetchone()
    if row is None:
        return None
    expiry = _as_utc(datetime.fromisoformat(row[0]))
    if row[1] or expiry <= timestamp:
        return None
    return max(1, math.ceil((expiry - timestamp).total_seconds()))


def validate_intent(
    connection: sqlite3.Connection,
    job_fingerprint: str,
    intent_token: str,
    now: datetime | None = None,
) -> str:
    """Return the token hash only when its matching intent is live and unused."""
    timestamp = _as_utc(now or datetime.now(timezone.utc))
    if not isinstance(intent_token, str) or not intent_token:
        raise IntentExpired("Intent is missing or malformed")
    token_hash = hashlib.sha256(intent_token.encode("utf-8")).hexdigest()
    row = connection.execute(
        "SELECT token_hash, expires_at, consumed FROM apply_intents "
        "WHERE job_fingerprint = ?",
        (job_fingerprint,),
    ).fetchone()
    if row is None or not hmac.compare_digest(row[0], token_hash):
        raise IntentExpired("Intent is missing or does not match this job")
    if _as_utc(datetime.fromisoformat(row[1])) <= timestamp:
        raise IntentExpired("Intent has expired")
    if row[2]:
        raise IntentConsumed("Intent has already been consumed")
    return token_hash


def consume_intent(
    connection: sqlite3.Connection,
    job_fingerprint: str,
    intent_token: str,
    now: datetime | None = None,
) -> None:
    """Atomically consume a validated token; a concurrent consume cannot win twice."""
    connection.execute("BEGIN IMMEDIATE")
    try:
        token_hash = validate_intent(connection, job_fingerprint, intent_token, now)
        cursor = connection.execute(
            "UPDATE apply_intents SET consumed = 1 "
            "WHERE job_fingerprint = ? AND token_hash = ? AND consumed = 0",
            (job_fingerprint, token_hash),
        )
        if cursor.rowcount != 1:
            raise IntentConsumed("Intent has already been consumed")
        connection.commit()
    except Exception:
        connection.rollback()
        raise