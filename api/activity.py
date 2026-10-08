"""Merged, time-ordered, actor-attributed activity feed.

Reads the write tables that already exist and unions them into one list — it
introduces no new storage of its own, so it cannot drift from what actually
happened.

Sources
  apply_claims            a submit claim was taken (claimed_at, actor, status)
  apply_intents           a one-use intent was issued (expires_at, actor)
  apply_review_artifacts  a review package was built (created_at, actor, fill_status)
  login_events            a sign-in was attempted (at, username, outcome, ip)

What is deliberately NOT here
  Google Sheets tracker rows. The APPLIED tab stores `created_by` on the row but
  keeps no change history, so "who flipped this to rejected, when" is not
  recoverable from it. Inventing a second history store for Sheets writes is a
  bigger decision than this feed; the SQLite side is complete because those
  tables were already the system of record.

Robustness
  Every source is read independently and every failure degrades to "this source
  contributed nothing". A deployment whose database predates the `actor` column,
  or that has never issued an intent, must still get a feed rather than a 500 —
  the tables are created lazily and may genuinely not exist yet.
"""

import sqlite3
from typing import Any, Dict, List, Optional

DEFAULT_LIMIT = 50
MAX_LIMIT = 500


def _normalize_limit(limit: Optional[int]) -> int:
    try:
        value = int(limit if limit is not None else DEFAULT_LIMIT)
    except (TypeError, ValueError):
        return DEFAULT_LIMIT
    return max(1, min(MAX_LIMIT, value))


def _rows(connection: sqlite3.Connection, sql: str, params: tuple = ()) -> List[sqlite3.Row]:
    """Run one SELECT, returning [] if the table or a column does not exist."""
    try:
        return list(connection.execute(sql, params).fetchall())
    except sqlite3.Error:
        return []


def _claim_events(connection, limit: int) -> List[Dict[str, Any]]:
    rows = _rows(
        connection,
        "SELECT job_fingerprint, status, claimed_at, cap_date, actor "
        "FROM apply_claims ORDER BY claimed_at DESC LIMIT ?",
        (limit,),
    )
    return [
        {
            "kind": "submit_claim",
            "at": row["claimed_at"],
            "actor": row["actor"],
            "job_fingerprint": row["job_fingerprint"],
            "detail": {"status": row["status"], "cap_date": row["cap_date"]},
        }
        for row in rows
    ]


def _intent_events(connection, limit: int) -> List[Dict[str, Any]]:
    rows = _rows(
        connection,
        "SELECT job_fingerprint, expires_at, consumed, actor "
        "FROM apply_intents ORDER BY expires_at DESC LIMIT ?",
        (limit,),
    )
    return [
        {
            "kind": "apply_intent",
            "at": row["expires_at"],
            "actor": row["actor"],
            "job_fingerprint": row["job_fingerprint"],
            "detail": {"consumed": bool(row["consumed"])},
        }
        for row in rows
    ]


def _artifact_events(connection, limit: int) -> List[Dict[str, Any]]:
    rows = _rows(
        connection,
        "SELECT job_fingerprint, created_at, platform, fill_status, job_title, actor "
        "FROM apply_review_artifacts ORDER BY created_at DESC LIMIT ?",
        (limit,),
    )
    return [
        {
            "kind": "review_artifact",
            "at": row["created_at"],
            "actor": row["actor"],
            "job_fingerprint": row["job_fingerprint"],
            "detail": {
                "platform": row["platform"],
                "fill_status": row["fill_status"],
                "job_title": row["job_title"],
            },
        }
        for row in rows
    ]


def _login_events(limit: int) -> List[Dict[str, Any]]:
    """Read login history from the AUTH store, not the apply-state store.

    These are the same file by default (both fall back to data/apply_submit.db),
    but AUTH_DB_PATH exists precisely to let an operator split them. Reading
    login_events off the apply-state connection would then silently return
    nothing — an admin would see an activity feed with no sign-in history and no
    indication that a whole source was missing.
    """
    from api.auth import connect as auth_connect

    try:
        connection = auth_connect()
    except Exception:
        return []
    try:
        rows = _rows(
            connection,
            "SELECT at, username, client_ip, outcome, user_id "
            "FROM login_events ORDER BY id DESC LIMIT ?",
            (limit,),
        )
    finally:
        connection.close()
    return [
        {
            "kind": "login",
            "at": row["at"],
            "actor": row["username"],
            "job_fingerprint": None,
            "detail": {"outcome": row["outcome"], "client_ip": row["client_ip"]},
        }
        for row in rows
    ]


def collect(limit: Optional[int] = None, include_logins: bool = False) -> List[Dict[str, Any]]:
    """Merged feed, newest first.

    Each source is capped at `limit` before the merge, so the union is at most
    4 x limit rows and is then re-trimmed — reading unbounded history to return
    50 rows would be wasteful on a table that only ever grows.

    `include_logins` is off by default: login events carry client IPs, which is
    a step more sensitive than "who built which review package". The caller
    (api/routers/activity.py) decides based on role.
    """
    from api.apply_state import connect

    bounded = _normalize_limit(limit)
    connection = connect()
    try:
        events: List[Dict[str, Any]] = []
        events.extend(_claim_events(connection, bounded))
        events.extend(_intent_events(connection, bounded))
        events.extend(_artifact_events(connection, bounded))
        if include_logins:
            events.extend(_login_events(bounded))
    finally:
        connection.close()

    # Missing/unparseable timestamps sort last rather than raising: a row from
    # an older schema must not break the whole feed.
    def sort_key(event: Dict[str, Any]) -> str:
        return event.get("at") or ""

    events.sort(key=sort_key, reverse=True)
    return events[:bounded]
