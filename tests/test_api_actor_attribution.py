"""Actor attribution + roles (Scenario A — PM.md §5, BACKEND.md §4).

Auth answers "may this request through?". These tests cover the other question:
"who did it?" — the identity that `apply_access_ok()` used to compute and then
throw away by returning a bool.

Covered
  precedence      session -> username; service Bearer -> "automation";
                  BOTH -> session wins; open-access dev -> "local-dev";
                  nothing identifiable -> 401 (never an empty actor)
  persistence     the actor actually lands in apply_claims, apply_intents and
                  apply_review_artifacts, and reaches the Sheets write path
  roles           first user on a fresh store is admin, later users operator;
                  submit requires an admin SESSION or the service token;
                  an operator session is 403 even with the token attached
  session cap     MAX_SESSIONS_PER_USER evicts the oldest, never the newest
  audit trail     login_events records ok/failed/rate_limited with the IP
  activity feed   merged newest-first; login events are admin-only
"""

import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.auth import (
    ROLE_ADMIN,
    ROLE_OPERATOR,
    create_session,
    create_user,
    get_session,
    get_user_role,
    recent_login_events,
    record_login_event,
    set_user_role,
    verify_login,
)
from api.deps import AUTOMATION_ACTOR, OPEN_ACCESS_ACTOR, resolve_actor

COOKIE = "rja_session"
PASSWORD = "s3cretPass1"


@pytest.fixture()
def client():
    return TestClient(create_app())


def sign_in(client, username, password=PASSWORD):
    response = client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200, response.text
    return response.cookies.get(COOKIE), response.json()


def as_user(token):
    return {COOKIE: token}


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


# --- precedence --------------------------------------------------------------


def test_session_attributes_to_the_username(client):
    create_user("alice", PASSWORD)
    token, body = sign_in(client, "alice")
    assert body["username"] == "alice"

    response = client.get("/api/auth/me", cookies=as_user(token))
    assert response.json()["username"] == "alice"


def test_service_token_attributes_to_the_automation_sentinel(client, monkeypatch):
    create_user("alice", PASSWORD)
    monkeypatch.setenv("APPLY_API_TOKEN", "apply-secret")

    request = client.build_request("POST", "/api/apply/x/intent", headers=bearer("apply-secret"))
    # No session cookie on this request at all.
    assert resolve_actor(_Scope(request), _Creds("apply-secret")) == AUTOMATION_ACTOR


def test_session_wins_when_both_credentials_are_present(client, monkeypatch):
    """The precedence rule that must be explicit, not accidental.

    A reverse proxy or test harness can attach the service token to a request a
    human is making. Recording "automation" there would blame the machine for a
    person's decision.
    """
    create_user("alice", PASSWORD)
    monkeypatch.setenv("APPLY_API_TOKEN", "apply-secret")
    token, _ = sign_in(client, "alice")

    actor = resolve_actor(_RequestWithCookie(token), _Creds("apply-secret"))
    assert actor == "alice", "session must win over the service token"


def test_open_access_attributes_to_a_distinct_sentinel(client):
    """Fresh clone: no users, no API_TOKEN — auth is not enforced at all.

    `require_token` allows these requests, so `require_actor` must attribute
    them rather than 401 (which would break every write on a first run). The
    sentinel is deliberately NOT "automation": reading "local-dev" on a row says
    "written while auth was off", which is a different fact.
    """
    actor = resolve_actor(_RequestWithCookie(""), None)
    assert actor == OPEN_ACCESS_ACTOR
    assert actor != AUTOMATION_ACTOR


def test_require_actor_fails_closed_when_auth_is_enforced(client, monkeypatch):
    """A user exists and no credential is presented -> 401, never an empty actor."""
    create_user("alice", PASSWORD)
    monkeypatch.delenv("APPLY_API_TOKEN", raising=False)

    response = client.post(
        "/api/tracker", json={"apply_url": "https://acme.example/j/1"}
    )
    assert response.status_code == 401


def test_an_authenticated_identity_is_never_masked_by_open_access(client, monkeypatch):
    """open_access() is checked LAST, so a real username always wins."""
    create_user("alice", PASSWORD)
    token, _ = sign_in(client, "alice")
    assert resolve_actor(_RequestWithCookie(token), None) == "alice"


# --- the actor reaches the write path ----------------------------------------


def test_actor_is_persisted_on_a_review_artifact(tmp_path, monkeypatch):
    import api.apply_state as apply_state

    monkeypatch.setattr(apply_state, "DB_PATH", tmp_path / "state.db")
    apply_state.save_review_artifact(
        {
            "job_fingerprint": "fp-1",
            "platform": "greenhouse",
            "job_title": "Backend Engineer",
            "apply_url": "https://acme.example/j/1",
            "package_path": "/tmp/pkg",
            "match_ratio": 0.82,
            "fill_status": "filled_ready",
            "created_at": "2026-10-07T10:00:00+00:00",
            "actor": "alice",
        }
    )
    stored = apply_state.get_review_artifact("fp-1")
    assert stored["actor"] == "alice"


def test_actor_survives_an_artifact_rewrite(tmp_path, monkeypatch):
    """The ON CONFLICT path must update actor too, or a re-fill by a different
    operator would keep attributing the artifact to whoever wrote it first."""
    import api.apply_state as apply_state

    monkeypatch.setattr(apply_state, "DB_PATH", tmp_path / "state.db")
    base = {
        "job_fingerprint": "fp-1",
        "platform": "greenhouse",
        "job_title": "Backend Engineer",
        "apply_url": "https://acme.example/j/1",
        "package_path": "/tmp/pkg",
        "match_ratio": 0.82,
        "fill_status": "filled_ready",
        "created_at": "2026-10-07T10:00:00+00:00",
    }
    apply_state.save_review_artifact({**base, "actor": "alice"})
    apply_state.save_review_artifact({**base, "actor": "bob"})
    assert apply_state.get_review_artifact("fp-1")["actor"] == "bob"


def test_missing_actor_is_stored_as_null_not_a_guess(tmp_path, monkeypatch):
    """Rows written before attribution existed have no knowable author.
    Back-filling a sentinel would fabricate provenance."""
    import api.apply_state as apply_state

    monkeypatch.setattr(apply_state, "DB_PATH", tmp_path / "state.db")
    apply_state.save_review_artifact(
        {
            "job_fingerprint": "fp-legacy",
            "platform": "lever",
            "job_title": "Old Row",
            "apply_url": "https://acme.example/j/old",
            "package_path": "/tmp/pkg",
            "match_ratio": 0.5,
            "fill_status": "needs_review",
            "created_at": "2026-01-01T00:00:00+00:00",
        }
    )
    assert apply_state.get_review_artifact("fp-legacy")["actor"] is None


def test_claim_and_intent_primitives_record_the_actor(tmp_path):
    from datetime import datetime, timedelta, timezone

    from api.apply_claims import claim_first, initialize_claim_store
    from api.apply_intents import create_intent, initialize_intent_store

    connection = sqlite3.connect(tmp_path / "primitives.db")
    connection.row_factory = sqlite3.Row
    initialize_claim_store(connection)
    initialize_intent_store(connection)

    now = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
    intent = create_intent(
        connection, "fp-2", "token-abc", now + timedelta(minutes=5), now, actor="alice"
    )
    assert intent["actor"] == "alice"

    claim = claim_first(connection, "fp-2", daily_cap=3, now=now, actor="alice")
    assert claim["actor"] == "alice"

    row = connection.execute(
        "SELECT actor FROM apply_claims WHERE job_fingerprint = 'fp-2'"
    ).fetchone()
    assert row["actor"] == "alice"
    connection.close()


def test_actor_column_is_added_to_a_pre_existing_database(tmp_path):
    """Existing deployments already hold real apply history — the column has to
    be added in place, not by recreating the table."""
    from api.apply_claims import initialize_claim_store
    from api.apply_intents import initialize_intent_store

    path = tmp_path / "legacy.db"
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE apply_claims (job_fingerprint TEXT PRIMARY KEY, status TEXT NOT NULL,"
        " claimed_at TEXT NOT NULL, cap_date TEXT NOT NULL, intent_hash TEXT NOT NULL)"
    )
    connection.execute(
        "CREATE TABLE apply_intents (job_fingerprint TEXT PRIMARY KEY,"
        " token_hash TEXT UNIQUE NOT NULL, expires_at TEXT NOT NULL,"
        " consumed INTEGER NOT NULL DEFAULT 0)"
    )
    connection.execute(
        "INSERT INTO apply_claims VALUES ('fp-old','submitted','2026-01-01','2026-01-01','h')"
    )
    connection.commit()

    initialize_claim_store(connection)  # must not raise, must not lose the row
    initialize_intent_store(connection)

    columns = {r[1] for r in connection.execute("PRAGMA table_info(apply_claims)")}
    assert "actor" in columns
    intent_columns = {r[1] for r in connection.execute("PRAGMA table_info(apply_intents)")}
    assert "actor" in intent_columns

    preserved = connection.execute(
        "SELECT status, actor FROM apply_claims WHERE job_fingerprint='fp-old'"
    ).fetchone()
    assert preserved[0] == "submitted", "existing history must survive the upgrade"
    assert preserved[1] is None
    connection.close()


def test_review_artifact_table_is_upgraded_in_place_from_the_oldest_schema(
    tmp_path, monkeypatch
):
    """`apply_review_artifacts` has the longest migration chain in the repo:
    `fill_status`, `resume_path`, `cover_letter_text`, `field_verification`,
    `profile_fields_verified` and finally `actor` were all added after the table
    shipped. A deployment that has been running since before any of them must
    reach the current schema without losing a single applied-job row.

    This is the one migration that cannot be rehearsed on a fresh database,
    because `CREATE TABLE IF NOT EXISTS` silently builds the newest schema and
    every ALTER becomes a no-op - the test only means anything when it starts
    from a genuinely old table.
    """
    from api import apply_state

    path = tmp_path / "legacy_artifacts.db"
    # DB_PATH must be a Path: apply_state.connect() calls .parent.mkdir() on it.
    monkeypatch.setattr(apply_state, "DB_PATH", path)

    bootstrap = sqlite3.connect(path)
    bootstrap.execute(
        """CREATE TABLE apply_review_artifacts (
            job_fingerprint TEXT PRIMARY KEY,
            platform TEXT NOT NULL,
            job_title TEXT NOT NULL,
            apply_url TEXT NOT NULL,
            package_path TEXT NOT NULL,
            screenshot_path TEXT,
            confirmation_path TEXT,
            confirmation_message TEXT,
            match_ratio REAL NOT NULL,
            created_at TEXT NOT NULL
        )"""
    )
    bootstrap.execute(
        "INSERT INTO apply_review_artifacts VALUES "
        "('fp-old','greenhouse','Staff Engineer','https://boards.example/1','pkg/1.zip',"
        "NULL,NULL,NULL,0.91,'2026-01-01T00:00:00+00:00')"
    )
    bootstrap.commit()
    bootstrap.close()

    connection = apply_state.connect()  # must not raise, must not lose the row

    columns = {r[1] for r in connection.execute("PRAGMA table_info(apply_review_artifacts)")}
    for expected in (
        "fill_status",
        "resume_path",
        "cover_letter_text",
        "field_verification",
        "profile_fields_verified",
        "actor",
    ):
        assert expected in columns, f"{expected} was never added to the legacy table"

    row = connection.execute(
        "SELECT job_title, match_ratio, fill_status, actor "
        "FROM apply_review_artifacts WHERE job_fingerprint='fp-old'"
    ).fetchone()
    assert row is not None, "the pre-existing application row was lost"
    assert row["job_title"] == "Staff Engineer"
    assert row["match_ratio"] == 0.91
    # NOT NULL DEFAULT backfills existing rows rather than leaving them invalid.
    assert row["fill_status"] == "filled_ready"
    assert row["actor"] is None, "history predates attribution; it must stay NULL, not be invented"

    # And the upgraded table is writable with an actor.
    apply_state.save_review_artifact(
        {
            "job_fingerprint": "fp-new",
            "platform": "greenhouse",
            "job_title": "Backend Engineer",
            "apply_url": "https://boards.example/2",
            "package_path": "pkg/2.zip",
            "match_ratio": 0.8,
            "fill_status": "filled_ready",
            "created_at": "2026-10-07T00:00:00+00:00",
            "actor": "alice",
        }
    )
    connection2 = apply_state.connect()
    assert connection2.execute(
        "SELECT actor FROM apply_review_artifacts WHERE job_fingerprint='fp-new'"
    ).fetchone()["actor"] == "alice"
    connection.close()
    connection2.close()


def test_sheets_created_by_is_best_effort_and_never_blocks_the_row():
    """A live user spreadsheet whose layout cannot be safely extended must still
    get the application row — attribution is best-effort, the record is not."""
    from tools import application_tracker as tracker

    class _Sheet:
        def __init__(self, header):
            self._rows = [list(header)] if header else []
            self.appended = []
            self.cells = {}

        def get_all_values(self):
            return self._rows + self.appended

        def append_row(self, row):
            self.appended.append(list(row))

        def update_cell(self, r, c, v):
            self.cells[(r, c)] = v

    class _Client:
        def __init__(self, sheet):
            self._sheet = sheet

        def worksheet(self, name):
            return self._sheet

    # Existing 12-column tab: header is added, value written.
    sheet = _Sheet(tracker.APPLIED_HEADERS[:12])
    result = tracker.mark_applied(
        _Client(sheet), apply_url="https://acme.example/j/1", created_by="alice"
    )
    assert sheet.cells.get((1, tracker.CREATED_BY_COL)) == "created_by"
    assert len(sheet.appended[0]) == 13
    assert sheet.appended[0][-1] == "alice"
    assert result["created_by"] == "alice"

    # Column 13 already holds something else: do not clobber, do not attribute.
    busy = _Sheet(tracker.APPLIED_HEADERS[:12] + ["my_own_column"])
    result2 = tracker.mark_applied(
        _Client(busy), apply_url="https://acme.example/j/2", created_by="alice"
    )
    assert len(busy.appended[0]) == 12, "must not write into someone else's column"
    assert "created_by" not in result2

    # No actor at all: row is unchanged, no header invented.
    plain = _Sheet(tracker.APPLIED_HEADERS[:12])
    tracker.mark_applied(_Client(plain), apply_url="https://acme.example/j/3")
    assert len(plain.appended[0]) == 12
    assert plain.cells == {}


# --- roles -------------------------------------------------------------------


def test_first_user_is_admin_and_later_users_are_operator(client):
    """Bootstrap rule: if the first account were an operator, nobody could ever
    reach the admin-only submit path and there would be no way to promote
    anyone without editing SQLite by hand."""
    create_user("alice", PASSWORD)
    create_user("bob", PASSWORD)
    assert get_user_role("alice") == ROLE_ADMIN
    assert get_user_role("bob") == ROLE_OPERATOR


def test_explicit_role_is_honoured_and_validated(client):
    create_user("alice", PASSWORD)  # takes the admin bootstrap slot
    create_user("carol", PASSWORD, role="admin")
    assert get_user_role("carol") == ROLE_ADMIN
    with pytest.raises(ValueError, match="Role must be one of"):
        create_user("dave", PASSWORD, role="superuser")


def test_set_user_role_promotes_and_demotes(client):
    create_user("alice", PASSWORD)
    create_user("bob", PASSWORD)
    assert set_user_role("bob", "admin") is True
    assert get_user_role("bob") == ROLE_ADMIN
    assert set_user_role("bob", "operator") is True
    assert get_user_role("bob") == ROLE_OPERATOR
    assert set_user_role("nobody", "admin") is False


def test_demotion_takes_effect_on_the_next_request(client):
    """Role is resolved on every session read, not cached in the session row —
    otherwise a demotion only applied when the operator happened to sign in
    again, which could be up to 7 days later."""
    create_user("alice", PASSWORD)
    token, _ = sign_in(client, "alice")
    assert get_session(token)["role"] == ROLE_ADMIN

    set_user_role("alice", "operator")
    assert get_session(token)["role"] == ROLE_OPERATOR


def test_role_is_reported_at_login_and_on_me(client):
    create_user("alice", PASSWORD)
    token, body = sign_in(client, "alice")
    assert body["role"] == ROLE_ADMIN
    assert client.get("/api/auth/me", cookies=as_user(token)).json()["role"] == ROLE_ADMIN


def test_a_service_token_has_no_role(client, monkeypatch):
    """A shared secret is not a person, so it can never satisfy an admin check
    by having a role — it is admitted to submit by a separate, explicit branch."""
    from api.deps import resolve_session_role

    create_user("alice", PASSWORD)
    monkeypatch.setenv("APPLY_API_TOKEN", "apply-secret")
    assert resolve_session_role(_RequestWithCookie("")) == ""


# --- submit gate -------------------------------------------------------------


def test_submit_gate_blocks_an_operator_session_even_with_the_token_attached(
    client, monkeypatch
):
    """The precedence rule applied to authorization, not just attribution.

    If a service token riding along could upgrade an operator, the role gate
    would be decorative: any operator behind a token-injecting proxy would get
    through.
    """
    from api.deps import require_submit_actor
    from fastapi import HTTPException

    create_user("alice", PASSWORD)
    create_user("bob", PASSWORD)  # operator
    monkeypatch.setenv("APPLY_API_TOKEN", "apply-secret")
    bob_token, _ = sign_in(client, "bob")

    with pytest.raises(HTTPException) as exc:
        require_submit_actor(_RequestWithCookie(bob_token), _Creds("apply-secret"))
    assert exc.value.status_code == 403


def test_submit_gate_allows_an_admin_session(client, monkeypatch):
    from api.deps import require_submit_actor

    create_user("alice", PASSWORD)
    monkeypatch.setenv("APPLY_API_TOKEN", "apply-secret")
    token, _ = sign_in(client, "alice")
    assert require_submit_actor(_RequestWithCookie(token), None) == "alice"


def test_submit_gate_allows_the_service_token_with_no_session(client, monkeypatch):
    """The documented server-to-server path must survive the role gate."""
    from api.deps import require_submit_actor

    create_user("alice", PASSWORD)
    monkeypatch.setenv("APPLY_API_TOKEN", "apply-secret")
    assert (
        require_submit_actor(_RequestWithCookie(""), _Creds("apply-secret"))
        == AUTOMATION_ACTOR
    )


def test_submit_gate_rejects_anonymous_with_401_not_403(client, monkeypatch):
    """401, so an anonymous probe learns nothing about whether the route exists."""
    from fastapi import HTTPException

    from api.deps import require_submit_actor

    create_user("alice", PASSWORD)
    monkeypatch.delenv("APPLY_API_TOKEN", raising=False)
    with pytest.raises(HTTPException) as exc:
        require_submit_actor(_RequestWithCookie(""), None)
    assert exc.value.status_code == 401


def test_submit_route_rejects_an_operator_end_to_end(client, monkeypatch):
    create_user("alice", PASSWORD)
    create_user("bob", PASSWORD)
    bob_token, _ = sign_in(client, "bob")

    response = client.post(
        "/api/apply/fp-test/submit", json={"confirm": True}, cookies=as_user(bob_token)
    )
    # 403 from the role gate, or 403 from the kill-switch — either way an
    # operator never reaches the browser. Assert it is not a 5xx/2xx.
    assert response.status_code == 403


# --- session cap -------------------------------------------------------------


def test_session_cap_evicts_the_oldest_not_the_newest(client, monkeypatch):
    """A legitimate operator on a phone, laptop and desktop must never be locked
    out — only the stalest session is dropped."""
    monkeypatch.setenv("MAX_SESSIONS_PER_USER", "3")
    user_id = create_user("alice", PASSWORD)

    tokens = [create_session(user_id)[0] for _ in range(5)]

    live = [t for t in tokens if get_session(t) is not None]
    assert len(live) == 3
    assert tokens[0] not in live and tokens[1] not in live, "oldest should be gone"
    assert tokens[-1] in live, "the newest session must always survive"


def test_session_cap_is_bounded_and_configurable(client, monkeypatch):
    monkeypatch.setenv("MAX_SESSIONS_PER_USER", "1")
    user_id = create_user("alice", PASSWORD)
    first = create_session(user_id)[0]
    second = create_session(user_id)[0]
    assert get_session(first) is None
    assert get_session(second) is not None


# --- audit trail -------------------------------------------------------------


def test_login_events_are_recorded_for_every_outcome(client, monkeypatch):
    monkeypatch.setenv("LOGIN_RATE_LIMIT", "2")
    monkeypatch.setenv("LOGIN_USER_RATE_LIMIT", "2")
    create_user("alice", PASSWORD)

    client.post("/api/auth/login", json={"username": "alice", "password": "wrong"})
    client.post("/api/auth/login", json={"username": "alice", "password": "wrong"})
    blocked = client.post("/api/auth/login", json={"username": "alice", "password": "wrong"})
    assert blocked.status_code == 429

    # The budget is spent, so clear it before the successful attempt — the
    # point of this test is which outcomes reach the audit table, not the limiter.
    from api.ratelimit import reset_login_limiter

    reset_login_limiter()
    sign_in(client, "alice")

    outcomes = [e["outcome"] for e in recent_login_events(20)]
    assert "failed" in outcomes
    assert "rate_limited" in outcomes
    assert "ok" in outcomes


def test_login_events_never_store_a_password(client):
    record_login_event("alice", "failed", "203.0.113.7")
    events = recent_login_events(5)
    assert events and events[0]["username"] == "alice"
    assert events[0]["client_ip"] == "203.0.113.7"
    dumped = repr(events)
    assert PASSWORD not in dumped


def test_record_login_event_rejects_an_unknown_outcome(client):
    """CHECK-constrained column: a typo must not become a corrupt row."""
    record_login_event("alice", "banana", "1.2.3.4")
    assert all(e["outcome"] != "banana" for e in recent_login_events(20))


def test_audit_write_failure_never_breaks_a_login(client, monkeypatch):
    """An audit insert that fails must not turn a working login into a 500.

    The audit helpers swallow their own errors, so the contract to pin is: with
    the store completely unreachable, neither helper raises. (Breaking `connect`
    mid-request is NOT the same scenario — `create_session` legitimately raises
    when it cannot persist a session, because a login that cannot be recorded
    must not be reported as successful.)
    """
    import api.auth as auth_module

    create_user("alice", PASSWORD)

    def broken_connect():
        raise sqlite3.OperationalError("audit store unavailable")

    real_connect = auth_module.connect
    auth_module.connect = broken_connect
    try:
        # Neither may raise — both are best-effort audit helpers.
        auth_module.record_login_event("alice", "ok", "1.2.3.4")
        assert auth_module.recent_login_events(5) == []
    finally:
        auth_module.connect = real_connect

    # Restore by hand rather than monkeypatch.undo(): the `monkeypatch` fixture
    # is shared with conftest's autouse fixtures in the same test, so undo()
    # would also revert AUTH_DB_PATH isolation and the login below would look up
    # the developer's real database instead of this test's.
    assert client.post(
        "/api/auth/login", json={"username": "alice", "password": PASSWORD}
    ).status_code == 200


# --- activity feed -----------------------------------------------------------


def test_activity_feed_is_gated(client):
    create_user("alice", PASSWORD)
    assert client.get("/api/activity").status_code == 401


def test_activity_feed_merges_sources_newest_first(client, tmp_path, monkeypatch):
    import api.apply_state as apply_state

    monkeypatch.setattr(apply_state, "DB_PATH", tmp_path / "state.db")
    create_user("alice", PASSWORD)
    token, _ = sign_in(client, "alice")

    apply_state.save_review_artifact(
        {
            "job_fingerprint": "fp-1",
            "platform": "greenhouse",
            "job_title": "Backend Engineer",
            "apply_url": "https://acme.example/j/1",
            "package_path": "/tmp/pkg",
            "match_ratio": 0.82,
            "fill_status": "filled_ready",
            "created_at": "2026-10-01T10:00:00+00:00",
            "actor": "alice",
        }
    )

    body = client.get("/api/activity", cookies=as_user(token)).json()
    kinds = {e["kind"] for e in body["events"]}
    assert "review_artifact" in kinds
    assert "login" in kinds, "admin should see login events"
    assert body["includes_login_events"] is True
    timestamps = [e["at"] for e in body["events"] if e["at"]]
    assert timestamps == sorted(timestamps, reverse=True)


def test_login_events_are_hidden_from_a_non_admin(client, monkeypatch, tmp_path):
    """They carry client IPs — a step more sensitive than "who built which
    review package". Non-admins get the feed without them, and are told why."""
    import api.apply_state as apply_state

    monkeypatch.setattr(apply_state, "DB_PATH", tmp_path / "state.db")
    create_user("alice", PASSWORD)  # admin
    create_user("bob", PASSWORD)  # operator
    bob_token, _ = sign_in(client, "bob")

    body = client.get("/api/activity", cookies=as_user(bob_token)).json()
    assert body["includes_login_events"] is False
    assert all(e["kind"] != "login" for e in body["events"])


def test_activity_limit_is_bounded(client):
    create_user("alice", PASSWORD)
    token, _ = sign_in(client, "alice")
    assert client.get("/api/activity?limit=5", cookies=as_user(token)).status_code == 200
    # Out-of-range limits are rejected by the Query(ge/le) contract.
    assert client.get("/api/activity?limit=99999", cookies=as_user(token)).status_code == 422


# --- helpers -----------------------------------------------------------------
# Minimal request/credential stand-ins so the dependency functions can be called
# directly. Driving them through TestClient would conflate "the dependency
# resolved the wrong actor" with "the route rejected me for another reason".


class _Creds:
    def __init__(self, credentials):
        self.credentials = credentials
        self.scheme = "Bearer"


class _RequestWithCookie:
    """Request stand-in carrying only a session cookie."""

    def __init__(self, token):
        self.cookies = {COOKIE: token} if token else {}
        self.headers = {}


class _Scope:
    def __init__(self, request):
        self.cookies = {}
        self.headers = request.headers


def _build_request_with_cookie(client, token):  # pragma: no cover - convenience
    return client.build_request("GET", "/api/auth/me", cookies=as_user(token))


def test_verify_login_reports_the_role(client):
    create_user("alice", PASSWORD)
    user = verify_login("alice", PASSWORD)
    assert user["role"] == ROLE_ADMIN
    assert verify_login("alice", "wrong") is None
