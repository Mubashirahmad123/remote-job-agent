"""Session-auth tests — hermetic (tmp SQLite auth store, no network, no Sheets).

Covers the user-login flow end to end at the API boundary:
  - fresh local dev stays open (no users, no API_TOKEN)
  - creating a user flips /api/* and / to session-gated
  - login sets an HttpOnly rja_session cookie; wrong password gets 401
  - /me + protected routes honour the session; logout invalidates it
  - sessions survive an app "restart" (SQLite-backed)
  - API_TOKEN Bearer still works for server-to-server calls
  - apply-gated routes accept session OR Bearer APPLY_API_TOKEN, never the
    general API_TOKEN, and still fail closed with no credential
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.auth import create_user

COOKIE = "rja_session"


@pytest.fixture()
def client():
    return TestClient(create_app())


def login(client, username, password, **kwargs):
    return client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
        **kwargs,
    )


def set_cookie(response, name=COOKIE):
    """The Set-Cookie header for the session cookie ('' when absent)."""
    for header in response.headers.get_list("set-cookie"):
        if header.startswith(name + "="):
            return header
    return ""


# --- open local dev (no users, no API_TOKEN) -------------------------------

def test_open_access_when_no_users(client):
    assert client.get("/api/health").status_code == 200
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    body = me.json()
    assert body["authenticated"] is False
    assert body["open_access"] is True
    assert client.get("/").status_code == 200


# --- login + session ---------------------------------------------------------

def test_login_sets_httponly_session_cookie(client):
    create_user("alice", "s3cretPass1")

    bad = login(client, "alice", "nope-nope")
    assert bad.status_code == 401
    assert set_cookie(bad) == ""

    good = login(client, "alice", "s3cretPass1")
    assert good.status_code == 200
    assert good.json()["username"] == "alice"
    cookie = set_cookie(good)
    assert cookie
    lowered = cookie.lower()
    assert "httponly" in lowered  # JS can never read the session token
    assert "samesite=lax" in lowered
    assert "path=/" in lowered


def test_session_grants_access_and_logout_invalidates(client):
    create_user("bob", "s3cretPass2")
    token = login(client, "bob", "s3cretPass2").cookies.get(COOKIE)
    assert token

    assert client.get("/api/health", cookies={COOKIE: token}).status_code == 200
    me = client.get("/api/auth/me", cookies={COOKIE: token}).json()
    assert me["authenticated"] is True
    assert me["username"] == "bob"

    out = client.post("/api/auth/logout", cookies={COOKIE: token})
    assert out.status_code == 200
    assert out.json()["deleted"] is True

    # Server-side invalidation: the old cookie no longer works.
    assert client.get("/api/health", cookies={COOKIE: token}).status_code == 401


def test_session_survives_app_restart(client):
    create_user("carol", "s3cretPass3")
    token = login(client, "carol", "s3cretPass3").cookies.get(COOKIE)
    assert token

    fresh = TestClient(create_app())  # new process, same SQLite file
    assert fresh.get("/api/health", cookies={COOKIE: token}).status_code == 200


def test_root_redirects_unauthenticated_and_serves_dashboard_when_signed_in(client):
    create_user("dave", "s3cretPass4")

    redirect = client.get("/", follow_redirects=False)
    assert redirect.status_code == 302
    assert "/login.html" in redirect.headers["location"]

    token = login(client, "dave", "s3cretPass4").cookies.get(COOKIE)
    assert client.get("/", cookies={COOKIE: token}).status_code == 200


def test_unauthenticated_api_returns_401_once_user_exists(client):
    create_user("erin", "s3cretPass5")
    assert client.get("/api/health").status_code == 401
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/jobs").status_code == 401


# --- server-side Bearer tokens ----------------------------------------------

def test_api_token_bearer_still_works_for_server_calls(client, monkeypatch):
    create_user("frank", "s3cretPass6")
    monkeypatch.setenv("API_TOKEN", "server-secret")

    ok = client.get("/api/health", headers={"Authorization": "Bearer server-secret"})
    assert ok.status_code == 200
    bad = client.get("/api/health", headers={"Authorization": "Bearer wrong"})
    assert bad.status_code == 401


# --- apply-gated routes (session OR APPLY_API_TOKEN) -------------------------

def test_apply_intent_requires_credential_fails_closed(client):
    assert client.post("/api/apply/fp-test/intent").status_code == 401


def test_apply_intent_accepts_session_or_apply_token(client, monkeypatch):
    create_user("gina", "s3cretPass7")
    monkeypatch.setenv("APPLY_API_TOKEN", "apply-secret")
    token = login(client, "gina", "s3cretPass7").cookies.get(COOKIE)

    # Session passes the auth gate; the SUBMIT_ENABLED kill-switch then
    # answers 403 (conftest keeps submit disarmed) — proof the gate let it through.
    by_session = client.post("/api/apply/fp-test/intent", cookies={COOKIE: token})
    assert by_session.status_code == 403

    by_token = client.post(
        "/api/apply/fp-test/intent",
        headers={"Authorization": "Bearer apply-secret"},
    )
    assert by_token.status_code == 403


def test_general_api_token_never_grants_apply_gates(client, monkeypatch):
    create_user("hank", "s3cretPass8")
    monkeypatch.setenv("API_TOKEN", "server-secret")

    response = client.post(
        "/api/apply/fp-test/intent",
        headers={"Authorization": "Bearer server-secret"},
    )
    assert response.status_code == 401


def test_tracker_reconcile_requires_apply_credential(client):
    # No user, no token: the reconcile flag demands session OR APPLY_API_TOKEN.
    response = client.patch(
        "/api/tracker/fp-test",
        json={"status": "rejected", "reconcile_submit_failure": True},
    )
    assert response.status_code == 401
