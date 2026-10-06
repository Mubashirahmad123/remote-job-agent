"""User accounts + server-side sessions for browser auth (SQLite).

Reuse rule: the same SQLite file as the apply-state store by default
(APPLY_STATE_DB_PATH, default data/apply_submit.db) — auth adds its own
`users` + `sessions` tables instead of new infrastructure. AUTH_DB_PATH
overrides to a dedicated file when desired.

Security
  Passwords: Argon2id via argon2-cffi (never plaintext, never logged).
  Sessions:  256-bit url-safe token in the cookie; only SHA-256(token) is
             stored, so a DB leak does not yield usable session tokens.
             HttpOnly cookie (JS can never read it), SameSite=Lax,
             Secure on https (auto behind proxy, SESSION_COOKIE_SECURE
             overrides).
  API_TOKEN: stays server-side only. It is accepted as a Bearer header for
             server-to-server calls (scheduler/CI) but is never exposed in
             URLs, localStorage, frontend JS, or API responses.

Env
  AUTH_DB_PATH           optional dedicated auth DB file.
  SESSION_TTL_HOURS      session lifetime (default 168 = 7 days).
  SESSION_COOKIE_SECURE  empty = Secure only on https (auto); true/false override.

All access is lazy (inside functions) so importing this module never touches
the filesystem or network beyond argon2 import.
"""

import hashlib
import os
import secrets
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerifyMismatchError

# --- DB (reuses the existing apply-state SQLite file by default) --------------

def db_path() -> Path:
    """Resolve the SQLite file lazily (env may change between tests/restarts)."""
    return Path(
        os.getenv("AUTH_DB_PATH")
        or os.getenv("APPLY_STATE_DB_PATH")
        or "data/apply_submit.db"
    )


SESSION_COOKIE = "rja_session"

_TTL_MIN_HOURS = 1
_TTL_MAX_HOURS = 24 * 90  # 90 days


def _resolve_ttl_hours() -> int:
    try:
        ttl = int(float(os.getenv("SESSION_TTL_HOURS", "168")))
    except (TypeError, ValueError):
        return 168
    return max(_TTL_MIN_HOURS, min(_TTL_MAX_HOURS, ttl))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat()


# --- Password hashing (Argon2id) ----------------------------------------------

# argon2-cffi defaults are Argon2id, 64 MiB, t=3, p=4 — OWASP-aligned. The
# `type=Type.ID` argument is explicit so a future library default change
# cannot silently weaken stored hashes.
_hasher = PasswordHasher(type=Type.ID)


def hash_password(password: str) -> str:
    """Argon2id hash of a plaintext password (self-contained, salted)."""
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Constant-time Argon2id verification; False on any mismatch/bad hash."""
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError, ValueError):
        return False


# --- Store --------------------------------------------------------------------

def connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    initialize_auth_store(connection)
    return connection


def initialize_auth_store(connection: sqlite3.Connection) -> None:
    """Create users + sessions tables (idempotent, safe to call every time)."""
    connection.execute(
        """CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        )"""
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        )"""
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at)"
    )
    connection.commit()


# --- Users --------------------------------------------------------------------

def create_user(username: str, password: str) -> int:
    """Create one user with an Argon2id password hash. Returns the user id.

    Raises ValueError on a duplicate username or a too-short password.
    """
    name = (username or "").strip()
    if not (3 <= len(name) <= 64):
        raise ValueError("Username must be 3-64 characters")
    if not password or len(password) < 8:
        raise ValueError("Password must be at least 8 characters")
    connection = connect()
    try:
        cursor = connection.execute(
            "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
            (name, hash_password(password), _iso(_now())),
        )
        connection.commit()
        return int(cursor.lastrowid)
    except sqlite3.IntegrityError as e:
        raise ValueError(f"Username '{name}' already exists") from e
    finally:
        connection.close()


def update_password(username: str, password: str) -> bool:
    """Reset one user's password (Argon2id). False when the user is unknown."""
    name = (username or "").strip()
    if not password or len(password) < 8:
        raise ValueError("Password must be at least 8 characters")
    connection = connect()
    try:
        cursor = connection.execute(
            "UPDATE users SET password_hash = ? WHERE username = ?",
            (hash_password(password), name),
        )
        connection.commit()
        return cursor.rowcount > 0
    finally:
        connection.close()


def count_users() -> int:
    """Number of users; -1 when the store is unreadable (fail closed)."""
    try:
        connection = connect()
        try:
            row = connection.execute("SELECT COUNT(*) FROM users").fetchone()
            return int(row[0])
        finally:
            connection.close()
    except Exception:
        return -1


def verify_login(username: str, password: str) -> Optional[Dict[str, Any]]:
    """{id, username} when username+password match; None otherwise.

    Case-insensitive username (NOCASE column); constant-time Argon2id verify.
    """
    name = (username or "").strip()
    if not name or not password:
        return None
    try:
        connection = connect()
        try:
            row = connection.execute(
                "SELECT id, username, password_hash FROM users WHERE username = ?",
                (name,),
            ).fetchone()
        finally:
            connection.close()
    except Exception:
        return None
    if row is None:
        return None
    if not verify_password(row["password_hash"], password):
        return None
    return {"id": int(row["id"]), "username": row["username"]}


# --- Sessions (server-side, survive uvicorn restarts via SQLite) --------------

def _token_hash(token: str) -> str:
    """Only the SHA-256 of the cookie token is persisted."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(user_id: int) -> tuple:
    """Mint a fresh session. Returns (raw_cookie_token, expires_at_iso)."""
    token = secrets.token_urlsafe(32)
    now = _now()
    expires = now + timedelta(hours=_resolve_ttl_hours())
    connection = connect()
    try:
        connection.execute(
            "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (_token_hash(token), user_id, _iso(now), _iso(expires)),
        )
        connection.commit()
    finally:
        connection.close()
    return token, _iso(expires)


def get_session(token: str) -> Optional[Dict[str, Any]]:
    """{user_id, username, expires_at} for a valid, unexpired session token."""
    raw = (token or "").strip()
    if not raw:
        return None
    try:
        connection = connect()
        try:
            row = connection.execute(
                """SELECT s.expires_at, u.id AS user_id, u.username
                FROM sessions s JOIN users u ON u.id = s.user_id
                WHERE s.token_hash = ?""",
                (_token_hash(raw),),
            ).fetchone()
        finally:
            connection.close()
    except Exception:
        return None
    if row is None:
        return None
    expires_at = row["expires_at"]
    try:
        if _now() > datetime.fromisoformat(expires_at):
            return None
    except (TypeError, ValueError):
        return None
    return {
        "user_id": int(row["user_id"]),
        "username": row["username"],
        "expires_at": expires_at,
    }


def delete_session(token: str) -> bool:
    """Invalidate one session server-side. True when a row was removed."""
    raw = (token or "").strip()
    if not raw:
        return False
    connection = connect()
    try:
        cursor = connection.execute(
            "DELETE FROM sessions WHERE token_hash = ?", (_token_hash(raw),)
        )
        connection.commit()
        return cursor.rowcount > 0
    finally:
        connection.close()


def purge_expired_sessions() -> int:
    """Delete expired sessions (called on login). Returns rows removed."""
    cutoff = _iso(_now())
    connection = connect()
    try:
        cursor = connection.execute(
            "DELETE FROM sessions WHERE expires_at <= ?", (cutoff,)
        )
        connection.commit()
        return cursor.rowcount
    finally:
        connection.close()


# --- Request helpers ----------------------------------------------------------

def session_user(request) -> Optional[Dict[str, Any]]:
    """Valid session for a Request's cookie, or None (never raises)."""
    try:
        token = request.cookies.get(SESSION_COOKIE) or ""
        return get_session(token)
    except Exception:
        return None


def open_access() -> bool:
    """True only when API_TOKEN is unset AND no users exist (fresh local dev).

    This preserves today's open-localhost default until the first user is
    created (create_user.py) or API_TOKEN is set — the moment either exists,
    every /api/* route requires a valid session (or the server-side Bearer).
    A DB read failure counts as "users may exist" (fail closed).
    """
    if (os.getenv("API_TOKEN") or "").strip():
        return False
    return count_users() == 0


def _cookie_secure(request) -> bool:
    """Secure flag: https (auto behind proxy) or SESSION_COOKIE_SECURE=true."""
    raw = (os.getenv("SESSION_COOKIE_SECURE") or "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    try:
        return request.url.scheme == "https"
    except Exception:
        return False


def set_session_cookie(response, token: str, secure: bool = False) -> None:
    """Attach the HttpOnly session cookie (SameSite=Lax, path=/)."""
    max_age = _resolve_ttl_hours() * 3600
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=max_age,
        expires=max_age,
        path="/",
        httponly=True,
        secure=secure,
        samesite="lax",
    )


def clear_session_cookie(response, secure: bool = False) -> None:
    """Remove the session cookie (matches the set attributes exactly)."""
    response.delete_cookie(
        SESSION_COOKIE,
        path="/",
        httponly=True,
        secure=secure,
        samesite="lax",
    )
