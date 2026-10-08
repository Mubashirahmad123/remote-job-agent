"""Sessions need an idle ceiling, not just an absolute one (L4).

`SESSION_TTL_HOURS` defaulted to 168 — seven days — and nothing else bounded a
session. A cookie stolen and NOT immediately used stayed valid for the full
week: from a laptop backup, a shared machine, an old browser profile, a synced
cookie store. `MAX_SESSIONS_PER_USER` caps how many can exist and
`update_password` revokes them all, but neither helps when the password was
never changed and the cookie was simply copied.

Now `get_session` enforces two ceilings:

  * `expires_at`   absolute — dies this long after it was minted, however active
  * `last_seen_at` idle — dies this long after its last request, however young

Worth stating plainly what this does and does not buy, because the honest
version is less impressive: an attacker who USES a stolen cookie keeps sliding
its own idle window, so an idle timeout does not stop an active thief. It closes
the steal-now-use-later window. The absolute TTL is still what bounds the active
one. Both are needed and neither replaces the other.

Time is never slept through in these tests. Every case writes the timestamp it
wants straight into the sessions table, so "48 hours idle" is exact rather than
approximate and the file runs in well under a second.
"""

import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api import auth
from api.app import create_app
from api.auth import (
    _resolve_idle_timeout_hours,
    _resolve_ttl_hours,
    _token_hash,
    connect,
    create_session,
    create_user,
    get_session,
    purge_expired_sessions,
)
from api.ratelimit import reset_action_limiter, reset_login_limiter

PASSWORD = "s3cretPass1"


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.replace(microsecond=0).isoformat()


def _write(token, **columns):
    """Set columns on a session row directly. This is how the tests move time:
    writing `last_seen_at = now - 48h` is exact, deterministic and instant,
    where sleeping 48 hours is none of those things."""
    connection = connect()
    try:
        assignments = ", ".join(f"{name} = ?" for name in columns)
        connection.execute(
            f"UPDATE sessions SET {assignments} WHERE token_hash = ?",
            (*[_iso(value) for value in columns.values()], _token_hash(token)),
        )
        connection.commit()
    finally:
        connection.close()


def _read(token, column):
    connection = connect()
    try:
        row = connection.execute(
            f"SELECT {column} FROM sessions WHERE token_hash = ?", (_token_hash(token),)
        ).fetchone()
        return row[0] if row else None
    finally:
        connection.close()


@pytest.fixture(autouse=True)
def _clean_state():
    reset_login_limiter()
    reset_action_limiter()
    yield
    reset_login_limiter()
    reset_action_limiter()


@pytest.fixture()
def client():
    return TestClient(create_app())


@pytest.fixture()
def alice():
    return create_user("alice", PASSWORD)


# --- the knob ----------------------------------------------------------------


def test_the_default_is_one_day():
    assert _resolve_idle_timeout_hours() == 24


def test_the_idle_ceiling_is_clamped_to_the_absolute_ttl(monkeypatch):
    """The clamp is against SESSION_TTL_HOURS, not against the 90-day maximum.
    An idle timeout longer than the absolute TTL is unreachable — the session
    dies absolutely first and the idle rule could never fire — so accepting it
    would be accepting a knob that does nothing while looking configured."""
    monkeypatch.setenv("SESSION_TTL_HOURS", "6")
    monkeypatch.setenv("SESSION_IDLE_TIMEOUT_HOURS", "999")
    assert _resolve_ttl_hours() == 6
    assert _resolve_idle_timeout_hours() == 6


@pytest.mark.parametrize("value", ["0", "-1", "-999"])
def test_a_non_positive_idle_timeout_becomes_one_hour_not_unlimited(monkeypatch, value):
    """`0` is the dangerous reading: taken literally it would sign every session
    out instantly, and someone setting it hoping for "disabled" gets an outage
    instead. There is no way to turn the idle ceiling off; set it equal to
    SESSION_TTL_HOURS if you want only the absolute one."""
    monkeypatch.setenv("SESSION_IDLE_TIMEOUT_HOURS", value)
    assert _resolve_idle_timeout_hours() == 1


@pytest.mark.parametrize("value", ["", "abc", "nan", "1.5.2"])
def test_garbage_falls_back_to_the_default(monkeypatch, value):
    monkeypatch.setenv("SESSION_IDLE_TIMEOUT_HOURS", value)
    assert _resolve_idle_timeout_hours() == 24


def test_a_fractional_value_is_accepted(monkeypatch):
    monkeypatch.setenv("SESSION_IDLE_TIMEOUT_HOURS", "0.5")
    assert _resolve_idle_timeout_hours() == 1, "0.5 rounds down to 0, which must clamp to 1"


# --- the two ceilings --------------------------------------------------------


def test_a_fresh_session_works(alice):
    token, _ = create_session(alice)
    session = get_session(token)
    assert session is not None and session["username"] == "alice"


def test_a_session_idle_past_the_ceiling_stops_working(alice, monkeypatch):
    monkeypatch.setenv("SESSION_IDLE_TIMEOUT_HOURS", "24")
    token, _ = create_session(alice)
    _write(token, last_seen_at=_now() - timedelta(hours=25))
    assert get_session(token) is None


def test_a_session_idle_inside_the_ceiling_keeps_working(alice, monkeypatch):
    monkeypatch.setenv("SESSION_IDLE_TIMEOUT_HOURS", "24")
    token, _ = create_session(alice)
    _write(token, last_seen_at=_now() - timedelta(hours=23))
    assert get_session(token) is not None


def test_the_idle_ceiling_bites_while_the_absolute_ttl_is_still_valid(alice, monkeypatch):
    """This is the actual finding. The old code had only the absolute check, so
    a session one day idle with six days of TTL left was perfectly usable."""
    monkeypatch.setenv("SESSION_TTL_HOURS", "168")
    monkeypatch.setenv("SESSION_IDLE_TIMEOUT_HOURS", "24")
    token, expires = create_session(alice)
    _write(token, last_seen_at=_now() - timedelta(hours=48))

    # Absolutely still valid — six days of TTL left on the clock.
    assert _now() < datetime.fromisoformat(expires)
    # ...and now refused anyway, because nobody used it for two days.
    assert get_session(token) is None


def test_an_absolutely_expired_session_is_still_refused(alice, monkeypatch):
    """The new ceiling must not replace the old one."""
    monkeypatch.setenv("SESSION_IDLE_TIMEOUT_HOURS", "24")
    token, _ = create_session(alice)
    past = _now() - timedelta(days=30)
    _write(token, created_at=past, last_seen_at=past, expires_at=past - timedelta(days=23))
    assert get_session(token) is None


def test_using_a_session_slides_the_window(alice, monkeypatch):
    """An active session must not be signed out — otherwise the fix is just a
    24-hour absolute TTL and everyone loses their session mid-job-hunt."""
    monkeypatch.setenv("SESSION_IDLE_TIMEOUT_HOURS", "24")
    token, _ = create_session(alice)

    for day in range(1, 6):
        # Each day, arrive one hour before the idle ceiling would have killed it.
        _write(token, last_seen_at=_now() - timedelta(hours=23))
        assert get_session(token) is not None, f"signed out on day {day} despite use"

    # Five days of continuous use, and the session is still alive — which the
    # absolute TTL alone would also allow, but the idle ceiling alone would not.
    assert get_session(token) is not None


# --- the touch, and why it is throttled --------------------------------------


def test_the_touch_is_throttled_to_one_write_per_minute(alice, monkeypatch):
    """`get_session` runs on EVERY authenticated request, so an unthrottled
    touch would turn every dashboard poll into a write to the sessions table."""
    touches = []
    monkeypatch.setattr(auth, "_touch_session", lambda *a, **k: touches.append(a))
    token, _ = create_session(alice)

    get_session(token)
    get_session(token)
    get_session(token)
    assert touches == [], "a just-created session is nowhere near the idle ceiling"

    _write(token, last_seen_at=_now() - timedelta(seconds=auth._SESSION_TOUCH_SECONDS + 1))
    get_session(token)
    assert len(touches) == 1, "past the throttle interval, exactly one touch"


def test_a_touch_really_writes(alice, monkeypatch):
    token, _ = create_session(alice)
    stale = _now() - timedelta(seconds=auth._SESSION_TOUCH_SECONDS + 5)
    _write(token, last_seen_at=stale)
    before = _read(token, "last_seen_at")
    assert get_session(token) is not None
    after = _read(token, "last_seen_at")
    assert after > before, "last_seen_at did not move forward"


def test_a_failed_touch_never_raises(alice, monkeypatch):
    """Bookkeeping must never turn a working session into an error.

    The guard lives INSIDE `_touch_session`, so that is where it has to be
    tested. The first version of this test monkeypatched `_touch_session` with a
    function that raised, which replaced the real one along with its own
    try/except and then "proved" the opposite of what it was for: it asserted
    that get_session survives a callee that was never written to survive
    anything. Breaking `connect` and calling the real function tests the real
    guard.
    """
    token, _ = create_session(alice)
    _write(token, last_seen_at=_now() - timedelta(seconds=auth._SESSION_TOUCH_SECONDS + 1))

    def _locked(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    # `monkeypatch.context()`, NOT `monkeypatch.undo()`. The monkeypatch fixture
    # is function-scoped, so conftest's autouse `_isolate_auth_db` — which does
    # `monkeypatch.setenv("AUTH_DB_PATH", tmp_path/...)` — is the SAME instance
    # this test is handed. Calling undo() rolls back every patch on it,
    # including that one, and `db_path()` then resolves to the developer's real
    # `data/apply_submit.db`: the session is not there, get_session returns
    # None, and the test appears to have caught a bug in the code. A context
    # undoes only what was patched inside it.
    with monkeypatch.context() as broken_db:
        broken_db.setattr(auth, "connect", _locked)
        auth._touch_session(_token_hash(token), _now())  # must not raise

    # ...and the session it belongs to is still perfectly good once the
    # database comes back, since the touch only ever moves last_seen_at forward.
    assert get_session(token) is not None


# --- upgrading an existing deployment ---------------------------------------


def test_the_column_is_created_and_migrated():
    columns = {
        row[1]
        for row in connect().execute("PRAGMA table_info(sessions)").fetchall()
    }
    assert "last_seen_at" in columns, columns


def test_a_legacy_row_with_no_last_seen_falls_back_to_created_at(alice, monkeypatch):
    """Rows written before the column existed read back as NULL. Neither reading
    of that is safe on its own: 'never seen' signs everyone out on the first
    request after the deploy, and 'seen now' makes every pre-existing session
    immortal. Falling back to created_at is neither."""
    monkeypatch.setenv("SESSION_IDLE_TIMEOUT_HOURS", "24")
    token, _ = create_session(alice)
    connection = connect()
    try:
        connection.execute(
            "UPDATE sessions SET last_seen_at = NULL WHERE token_hash = ?",
            (_token_hash(token),),
        )
        connection.commit()
    finally:
        connection.close()
    assert _read(token, "last_seen_at") is None
    # created_at is moments old, so the legacy row is alive...
    assert get_session(token) is not None

    # ...and it still expires on the fallback, so it is not immortal.
    _write(token, created_at=_now() - timedelta(hours=25))
    connection = connect()
    try:
        connection.execute(
            "UPDATE sessions SET last_seen_at = NULL WHERE token_hash = ?",
            (_token_hash(token),),
        )
        connection.commit()
    finally:
        connection.close()
    assert get_session(token) is None


def test_an_unparseable_timestamp_fails_closed(alice):
    token, _ = create_session(alice)
    connection = connect()
    try:
        connection.execute(
            "UPDATE sessions SET last_seen_at = 'not a timestamp' WHERE token_hash = ?",
            (_token_hash(token),),
        )
        connection.commit()
    finally:
        connection.close()
    assert get_session(token) is None


# --- purge -------------------------------------------------------------------


def test_purge_removes_idle_dead_rows_not_just_absolute_ones(alice, monkeypatch):
    """get_session already refuses them, but leaving the rows means they count
    against MAX_SESSIONS_PER_USER forever."""
    monkeypatch.setenv("SESSION_IDLE_TIMEOUT_HOURS", "24")
    live, _ = create_session(alice)
    dead, _ = create_session(alice)
    _write(dead, last_seen_at=_now() - timedelta(hours=48))

    assert purge_expired_sessions() == 1
    assert _read(dead, "last_seen_at") is None, "the idle-dead row is still there"
    assert get_session(live) is not None, "purge removed a live session"


def test_purge_spares_a_legacy_row_it_cannot_date(alice, monkeypatch):
    """COALESCE(last_seen_at, created_at) mirrors get_session's fallback exactly,
    so the purge and the read path can never disagree about a legacy row."""
    monkeypatch.setenv("SESSION_IDLE_TIMEOUT_HOURS", "24")
    token, _ = create_session(alice)
    connection = connect()
    try:
        connection.execute(
            "UPDATE sessions SET last_seen_at = NULL WHERE token_hash = ?",
            (_token_hash(token),),
        )
        connection.commit()
    finally:
        connection.close()
    assert purge_expired_sessions() == 0
    assert get_session(token) is not None


def test_dead_sessions_do_not_push_out_a_live_one(alice, monkeypatch):
    """The consequence of not purging: dead rows occupy the per-user cap, so
    _evict_excess_sessions removes a LIVE session on their behalf at the next
    login and the operator is signed out for no reason they can see."""
    monkeypatch.setenv("MAX_SESSIONS_PER_USER", "2")
    monkeypatch.setenv("SESSION_IDLE_TIMEOUT_HOURS", "24")

    keeper, _ = create_session(alice)
    abandoned, _ = create_session(alice)
    _write(abandoned, last_seen_at=_now() - timedelta(hours=48))

    purge_expired_sessions()
    newest, _ = create_session(alice)

    assert get_session(keeper) is not None, (
        "a live session was evicted to make room, because an idle-dead one was "
        "still occupying the cap"
    )
    assert get_session(newest) is not None


# --- over HTTP ---------------------------------------------------------------


def test_an_idle_session_gets_401_from_the_api(client, monkeypatch):
    monkeypatch.setenv("SESSION_IDLE_TIMEOUT_HOURS", "24")
    create_user("alice", PASSWORD)
    login = client.post(
        "/api/auth/login", json={"username": "alice", "password": PASSWORD}
    )
    assert login.status_code == 200, login.text
    assert client.get("/api/jobs").status_code != 401

    token = login.cookies[auth.SESSION_COOKIE]
    _write(token, last_seen_at=_now() - timedelta(hours=48))

    response = client.get("/api/jobs")
    assert response.status_code == 401, (
        f"an idle session was still served: {response.status_code}"
    )


def test_signing_in_again_after_an_idle_logout_works(client, monkeypatch):
    """The recovery path has to work, or this feature locks people out."""
    monkeypatch.setenv("SESSION_IDLE_TIMEOUT_HOURS", "24")
    create_user("alice", PASSWORD)
    login = client.post(
        "/api/auth/login", json={"username": "alice", "password": PASSWORD}
    )
    token = login.cookies[auth.SESSION_COOKIE]
    _write(token, last_seen_at=_now() - timedelta(hours=48))
    assert client.get("/api/jobs").status_code == 401

    client.cookies.clear()
    again = client.post(
        "/api/auth/login", json={"username": "alice", "password": PASSWORD}
    )
    assert again.status_code == 200, again.text
    assert client.get("/api/jobs").status_code != 401


def test_logout_is_unaffected(client):
    """The idle path must not have changed what an explicit logout does."""
    create_user("alice", PASSWORD)
    login = client.post(
        "/api/auth/login", json={"username": "alice", "password": PASSWORD}
    )
    assert login.status_code == 200, login.text
    assert client.post("/api/auth/logout").json().get("deleted") is True
    assert client.get("/api/jobs").status_code == 401
