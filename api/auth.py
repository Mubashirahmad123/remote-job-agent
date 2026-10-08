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
  PASSWORD_MAX_LENGTH    upper bound on accepted passwords (default 128).

All access is lazy (inside functions) so importing this module never touches
the filesystem or network beyond argon2 import.
"""

import hashlib
import os
import secrets
import sqlite3
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

# Roles. `admin` is the only role permitted to reach POST /api/apply/{fp}/submit
# once the SUBMIT_ENABLED kill-switch is lifted; `operator` can do everything
# else. Kept as strings rather than an int so a row in SQLite is readable
# without a lookup table.
ROLE_ADMIN = "admin"
ROLE_OPERATOR = "operator"
VALID_ROLES = frozenset({ROLE_ADMIN, ROLE_OPERATOR})


def _default_role_for_new_user(connection: sqlite3.Connection) -> str:
    """First user on a fresh store is admin; everyone after is operator.

    Bootstrapping matters: if the first account were an operator, nobody could
    ever reach the admin-only submit path, and there would be no way to promote
    anyone without editing SQLite by hand. Granting admin to the first user
    only means a leaked second credential is not automatically privileged.
    """
    try:
        row = connection.execute("SELECT COUNT(*) FROM users").fetchone()
        return ROLE_ADMIN if int(row[0]) == 0 else ROLE_OPERATOR
    except Exception:
        return ROLE_OPERATOR


# Cap on concurrent live sessions per user. Unbounded meant one leaked password
# could mint unlimited 7-day sessions with no way to notice. Creating a session
# past the cap evicts the OLDEST, so a legitimate operator on many devices is
# never locked out — only the stalest session is dropped.
_DEFAULT_MAX_SESSIONS_PER_USER = 10


def _max_sessions_per_user() -> int:
    try:
        value = int(float(os.getenv("MAX_SESSIONS_PER_USER", "") or _DEFAULT_MAX_SESSIONS_PER_USER))
    except (TypeError, ValueError):
        return _DEFAULT_MAX_SESSIONS_PER_USER
    return max(1, min(1000, value))


# Password length bounds. The floor is a policy choice; the CEILING is a
# resource-control choice: Argon2id cost is dominated by its memory/time
# parameters, but hashing is still linear in input length, so an unbounded
# `password` field turns one small JSON body into avoidable CPU work. 128
# characters is far beyond any real passphrase and rejects the abuse cheaply.
#
# Both names are public (no leading underscore) because create_user.py and the
# HTTP schema need the same bounds; importing a private name across modules
# hides a real contract.
PASSWORD_MIN_LENGTH = 8
DEFAULT_PASSWORD_MAX_LENGTH = 128


def password_max_length() -> int:
    try:
        value = int(float(os.getenv("PASSWORD_MAX_LENGTH", "") or DEFAULT_PASSWORD_MAX_LENGTH))
    except (TypeError, ValueError):
        return DEFAULT_PASSWORD_MAX_LENGTH
    # Never below the minimum, never absurdly high.
    return max(PASSWORD_MIN_LENGTH, min(4096, value))


def check_password_policy(password: str) -> None:
    """Raise ValueError unless the password is within the length policy.

    Public: `create_user.py` and the HTTP schema both need to state the same
    bound the server will enforce, so it is a contract, not an internal detail.
    """
    if not password or len(password) < PASSWORD_MIN_LENGTH:
        raise ValueError(f"Password must be at least {PASSWORD_MIN_LENGTH} characters")
    ceiling = password_max_length()
    if len(password) > ceiling:
        raise ValueError(f"Password must be at most {ceiling} characters")


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

# Argon2id hash of a throwaway secret, generated once with
# `secrets.token_urlsafe(32)` and then DISCARDED — the plaintext was never
# printed, stored or committed. It is a valid hash of a password nobody knows,
# and its only job is to be verified against on the "no such user" path so that
# path costs the same as the "wrong password" path. See `verify_login`.
#
# The parameters must match what `hash_password` produces (m=65536,t=3,p=4) or
# the two paths take visibly different time and the whole point is lost;
# tests/test_login_timing.py pins that.
_DECOY_PASSWORD_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$ZAe+TaQIKCjsj95dlE1+Yw$"
    "V63cfWFDLSjC0kFbXzQE2xid6O3PUz+ixvi/W3GDhVk"
)


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

# Paths whose schema has already been created in THIS process. `connect()` is
# called on every authenticated request (require_token -> get_session), and
# running 2x CREATE TABLE + CREATE INDEX each time measured ~3.6 ms per request
# of pure auth overhead. DDL is idempotent, so doing it once per (process, db
# path) is equivalent — and the key is the path, not a bare flag, so a test that
# monkeypatches AUTH_DB_PATH between calls still gets its schema built.
_initialized_paths: set = set()


def connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    key = str(path)
    if key not in _initialized_paths:
        initialize_auth_store(connection)
        _initialized_paths.add(key)
    return connection


def forget_initialized(path: Optional[str] = None) -> None:
    """Drop the "schema already built" memo for one path, or for all paths.

    Exists for tests and for the rare case where the DB file is deleted under a
    running process (the next `connect()` then rebuilds the schema).
    """
    if path is None:
        _initialized_paths.clear()
    else:
        _initialized_paths.discard(str(path))


def initialize_auth_store(connection: sqlite3.Connection) -> None:
    """Create users + sessions tables (idempotent, safe to call every time)."""
    # WAL lets readers proceed while a login/logout writes. Without it the
    # default rollback journal blocks every concurrent reader for the duration
    # of the write — and `require_token` reads the sessions table on every
    # single request. journal_mode is persisted in the DB header, so setting it
    # here (once per process, at schema-build time) is enough.
    # Best-effort: some filesystems (network mounts) refuse WAL, and the store
    # must keep working in the default journal mode rather than fail to start.
    try:
        connection.execute("PRAGMA journal_mode=WAL")
    except sqlite3.Error:
        pass
    connection.execute(
        """CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            last_login_at TEXT,
            role TEXT NOT NULL DEFAULT 'operator'
        )"""
    )
    # Columns added after the table shipped. ALTER is a no-op guard because
    # SQLite has no ADD COLUMN IF NOT EXISTS, so an existing deployment
    # upgrades in place instead of failing on "duplicate column name".
    for column, declaration in (
        ("last_login_at", "TEXT"),
        ("role", "TEXT NOT NULL DEFAULT 'operator'"),
    ):
        try:
            connection.execute(f"ALTER TABLE users ADD COLUMN {column} {declaration}")
        except sqlite3.Error:
            pass
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
    # Sessions are looked up by user on revoke; without this it is a scan.
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)"
    )
    # Persisted login audit trail. Logs rotate away and `users.last_login_at`
    # only ever records the most recent SUCCESS, so neither can answer "who
    # tried to get in, from where, and how often". Deliberately records
    # failures too — that is the interesting half. No passwords, ever.
    connection.execute(
        """CREATE TABLE IF NOT EXISTS login_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            at TEXT NOT NULL,
            username TEXT NOT NULL,
            client_ip TEXT,
            outcome TEXT NOT NULL CHECK (outcome IN ('ok','failed','rate_limited')),
            user_id INTEGER
        )"""
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_login_events_at ON login_events(at)"
    )
    connection.commit()


# --- Users --------------------------------------------------------------------

def create_user(username: str, password: str, role: Optional[str] = None) -> int:
    """Create one user with an Argon2id password hash. Returns the user id.

    `role` is "admin" or "operator". When omitted, the FIRST user on a fresh
    store becomes admin and every later user becomes operator — see
    `_default_role_for_new_user`. Passing an unknown role raises rather than
    silently downgrading, so a typo in `create_user.py --role` cannot quietly
    create an account that can never reach the admin-only submit path.

    Raises ValueError on a duplicate username or an out-of-policy password.
    """
    name = (username or "").strip()
    if not (3 <= len(name) <= 64):
        raise ValueError("Username must be 3-64 characters")
    check_password_policy(password)
    if role is not None:
        role = str(role).strip().lower()
        if role not in VALID_ROLES:
            raise ValueError(
                f"Role must be one of: {', '.join(sorted(VALID_ROLES))} (got '{role}')"
            )
    connection = connect()
    try:
        effective_role = role or _default_role_for_new_user(connection)
        cursor = connection.execute(
            "INSERT INTO users (username, password_hash, created_at, role) "
            "VALUES (?, ?, ?, ?)",
            (name, hash_password(password), _iso(_now()), effective_role),
        )
        connection.commit()
        return int(cursor.lastrowid)
    except sqlite3.IntegrityError as e:
        raise ValueError(f"Username '{name}' already exists") from e
    finally:
        connection.close()


def set_user_role(username: str, role: str) -> bool:
    """Promote/demote one user. False when the user is unknown."""
    name = (username or "").strip()
    normalized = str(role or "").strip().lower()
    if normalized not in VALID_ROLES:
        raise ValueError(
            f"Role must be one of: {', '.join(sorted(VALID_ROLES))} (got '{role}')"
        )
    connection = connect()
    try:
        cursor = connection.execute(
            "UPDATE users SET role = ? WHERE username = ?", (normalized, name)
        )
        connection.commit()
        return cursor.rowcount > 0
    finally:
        connection.close()


def get_user_role(username: str) -> Optional[str]:
    """One user's role, or None when unknown. Used by the admin gate."""
    name = (username or "").strip()
    if not name:
        return None
    try:
        connection = connect()
        try:
            row = connection.execute(
                "SELECT role FROM users WHERE username = ?", (name,)
            ).fetchone()
        finally:
            connection.close()
    except Exception:
        return None
    if row is None:
        return None
    # A row written before the role column existed reads back as NULL/'';
    # treat that as the least-privileged role rather than failing open.
    return (row[0] or ROLE_OPERATOR).strip().lower() or ROLE_OPERATOR


def revoke_user_sessions(user_id: int) -> int:
    """Delete every session belonging to one user. Returns rows removed.

    Used on password change: a credential reset must invalidate sessions
    minted under the OLD credential, otherwise a stolen `rja_session` cookie
    keeps working for the rest of its TTL no matter how often the password is
    rotated. This is the single most important property of a password reset,
    and it is why the reset cannot just be an UPDATE.
    """
    connection = connect()
    try:
        cursor = connection.execute(
            "DELETE FROM sessions WHERE user_id = ?", (int(user_id),)
        )
        connection.commit()
        return cursor.rowcount
    finally:
        connection.close()


def update_password(username: str, password: str) -> bool:
    """Reset one user's password (Argon2id) AND revoke all their sessions.

    False when the user is unknown. Revoking is unconditional — it happens in
    the same operation as the hash update so there is no window where the old
    password is gone but old sessions still work.
    """
    name = (username or "").strip()
    check_password_policy(password)
    connection = connect()
    try:
        cursor = connection.execute(
            "UPDATE users SET password_hash = ? WHERE username = ?",
            (hash_password(password), name),
        )
        connection.commit()
        changed = cursor.rowcount > 0
        if changed:
            row = connection.execute(
                "SELECT id FROM users WHERE username = ?", (name,)
            ).fetchone()
            if row is not None:
                connection.execute(
                    "DELETE FROM sessions WHERE user_id = ?", (int(row["id"]),)
                )
                connection.commit()
        return changed
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
    The password ceiling is enforced here too (not only in the HTTP schema) so
    no caller can push an oversized blob into Argon2.

    Exactly one Argon2id verification happens per attempt that gets this far,
    whether or not the username exists, so the two failures are not separable by
    timing. Requests rejected on their own shape (empty or oversized password)
    deliberately skip the verification: that branch is decided by what the CALLER
    sent, not by whether the account exists, so it leaks nothing about usernames
    and paying for a decoy verify there would only re-open the unbounded-Argon2
    hole the ceiling exists to close.
    """
    name = (username or "").strip()
    if not name or not password or len(password) > password_max_length():
        return None
    try:
        connection = connect()
        try:
            row = connection.execute(
                "SELECT id, username, password_hash, role FROM users WHERE username = ?",
                (name,),
            ).fetchone()
        finally:
            connection.close()
    except Exception:
        return None
    if row is None:
        # No such user. Verify anyway, against the decoy, and throw the answer
        # away. Without this the two failures are trivially distinguishable by
        # how long they take: an existing user costs one Argon2id verify (~107 ms
        # at these parameters) and a non-existent one cost none at all. Measured
        # before the fix, over the real HTTP endpoint: 601-799 ms for a username
        # that existed against 507-508 ms for one that did not — distributions
        # that did not overlap, so a handful of requests sorted any candidate
        # list into "real account" and "not a real account". That is a
        # prerequisite for every other attack on this endpoint: a password spray
        # aimed only at usernames known to exist, and a targeted phishing list
        # of confirmed employees.
        #
        # The response body was already identical (401, same JSON) and the audit
        # trail already records the attempt either way, so time was the only
        # remaining channel. It is not perfectly closed — the two paths still
        # differ by one indexed SQLite lookup and Python overhead — but the
        # ~107 ms Argon2 gap dwarfed those by two orders of magnitude, and what
        # is left is under the noise floor of a network round trip.
        verify_password(_DECOY_PASSWORD_HASH, password)
        return None
    if not verify_password(row["password_hash"], password):
        return None
    _touch_last_login(int(row["id"]))
    # A row written before the role column existed reads back as NULL; fall
    # back to the least-privileged role so an upgrade never grants admin.
    role = (row["role"] or ROLE_OPERATOR).strip().lower() or ROLE_OPERATOR
    return {"id": int(row["id"]), "username": row["username"], "role": role}


def _touch_last_login(user_id: int) -> None:
    """Stamp `last_login_at` (audit signal). Never fails a good login."""
    try:
        connection = connect()
        try:
            connection.execute(
                "UPDATE users SET last_login_at = ? WHERE id = ?",
                (_iso(_now()), user_id),
            )
            connection.commit()
        finally:
            connection.close()
    except Exception:
        pass


def record_login_event(
    username: str, outcome: str, client_ip: str = "", user_id: Optional[int] = None
) -> None:
    """Persist one login attempt to the audit trail. Never raises.

    Complements the logger: logs rotate away and `users.last_login_at` only
    stores the most recent success, so neither can answer "who tried to get in,
    from where, how often, and did any of it succeed". `outcome` is one of
    ok|failed|rate_limited (CHECK-constrained in the schema).

    Swallowing errors is deliberate — an audit write that fails must never turn
    a working login into a 500, and must never block a rejection.
    """
    if outcome not in ("ok", "failed", "rate_limited"):
        return
    try:
        connection = connect()
        try:
            connection.execute(
                "INSERT INTO login_events (at, username, client_ip, outcome, user_id) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    _iso(_now()),
                    (username or "").strip()[:64] or "-",
                    (client_ip or "").strip()[:64],
                    outcome,
                    user_id,
                ),
            )
            connection.commit()
        finally:
            connection.close()
    except Exception:
        pass


def recent_login_events(limit: int = 50) -> list:
    """Most recent login events, newest first (admin audit read)."""
    try:
        bounded = max(1, min(500, int(limit)))
    except (TypeError, ValueError):
        bounded = 50
    try:
        connection = connect()
        try:
            rows = connection.execute(
                "SELECT at, username, client_ip, outcome, user_id FROM login_events "
                "ORDER BY id DESC LIMIT ?",
                (bounded,),
            ).fetchall()
        finally:
            connection.close()
    except Exception:
        return []
    return [
        {
            "at": row["at"],
            "username": row["username"],
            "client_ip": row["client_ip"],
            "outcome": row["outcome"],
            "user_id": row["user_id"],
        }
        for row in rows
    ]


# --- Sessions (server-side, survive uvicorn restarts via SQLite) --------------

def _token_hash(token: str) -> str:
    """Only the SHA-256 of the cookie token is persisted."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _evict_excess_sessions(connection: sqlite3.Connection, user_id: int) -> int:
    """Trim one user's live sessions down to the cap, oldest first.

    Runs inside the same transaction that inserts the new session, so the cap
    can never be exceeded even under concurrent logins from the same account.
    Evicting the OLDEST (not refusing the newest) means a legitimate operator
    who signs in on a phone, a laptop and a desktop is never locked out — only
    the stalest session is dropped. Caller must have opened the transaction.
    """
    cap = _max_sessions_per_user()
    rows = connection.execute(
        "SELECT token_hash FROM sessions WHERE user_id = ? ORDER BY created_at ASC",
        (user_id,),
    ).fetchall()
    # -1: the session about to be inserted is not in `rows` yet.
    excess = len(rows) - (cap - 1)
    if excess <= 0:
        return 0
    for row in rows[:excess]:
        connection.execute("DELETE FROM sessions WHERE token_hash = ?", (row[0],))
    return excess


def create_session(user_id: int) -> tuple:
    """Mint a fresh session. Returns (raw_cookie_token, expires_at_iso).

    Enforces MAX_SESSIONS_PER_USER (default 10) by evicting the oldest live
    session for that user inside the same write transaction.
    """
    token = secrets.token_urlsafe(32)
    now = _now()
    expires = now + timedelta(hours=_resolve_ttl_hours())
    connection = connect()
    try:
        # BEGIN IMMEDIATE so two concurrent logins for the same account cannot
        # both read the pre-insert count and overshoot the cap.
        connection.execute("BEGIN IMMEDIATE")
        try:
            _evict_excess_sessions(connection, user_id)
            connection.execute(
                "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                (_token_hash(token), user_id, _iso(now), _iso(expires)),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    finally:
        connection.close()
    return token, _iso(expires)


def get_session(token: str) -> Optional[Dict[str, Any]]:
    """{user_id, username, role, expires_at} for a valid, unexpired session.

    `role` is resolved on every read rather than cached in the session row, so
    a demotion via `set_user_role` takes effect on the next request instead of
    only when the operator happens to sign in again.
    """
    raw = (token or "").strip()
    if not raw:
        return None
    try:
        connection = connect()
        try:
            row = connection.execute(
                """SELECT s.expires_at, u.id AS user_id, u.username, u.role
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
    try:
        role = (row["role"] or ROLE_OPERATOR).strip().lower() or ROLE_OPERATOR
    except (IndexError, KeyError):
        role = ROLE_OPERATOR
    return {
        "user_id": int(row["user_id"]),
        "username": row["username"],
        "role": role,
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


def cookie_secure(request) -> bool:
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
