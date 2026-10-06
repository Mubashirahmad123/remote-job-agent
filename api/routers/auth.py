"""POST /api/auth/login, POST /api/auth/logout, GET /api/auth/me.

Browser auth: username + password -> server-side session -> HttpOnly
cookie. API_TOKEN stays server-side only (Bearer for server-to-server
calls via deps.require_token) and is never accepted here.
"""

import time

from fastapi import APIRouter, HTTPException, Request, Response

from api.auth import (
    SESSION_COOKIE,
    _cookie_secure,
    clear_session_cookie,
    create_session,
    delete_session,
    purge_expired_sessions,
    session_user,
    set_session_cookie,
    verify_login,
)
from api.schemas import LoginRequest

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login")
def login(body: LoginRequest, request: Request, response: Response) -> dict:
    """Verify credentials, create a server-side session, set the cookie."""
    purge_expired_sessions()
    user = verify_login(body.username, body.password)
    if user is None:
        time.sleep(0.5)  # small brute-force slowdown on failure
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token, expires_at = create_session(user["id"])
    set_session_cookie(response, token, secure=_cookie_secure(request))
    return {"authenticated": True, "username": user["username"], "expires_at": expires_at}


@router.post("/logout")
def logout(request: Request, response: Response) -> dict:
    """Invalidate the session server-side + clear the cookie (idempotent)."""
    token = request.cookies.get(SESSION_COOKIE) or ""
    deleted = delete_session(token) if token else False
    clear_session_cookie(response, secure=_cookie_secure(request))
    return {"ok": True, "deleted": bool(deleted)}


@router.get("/me")
def me(request: Request) -> dict:
    """Current session identity; 401 only when auth is enforced."""
    user = session_user(request)
    if user is not None:
        return {
            "authenticated": True,
            "username": user["username"],
            "expires_at": user["expires_at"],
        }
    from api.auth import open_access

    if open_access():
        # Fresh local-dev instance (no API_TOKEN, no users): no session to
        # report, but nothing is enforced either — do not 401 the bootstrap.
        return {"authenticated": False, "open_access": True}
    raise HTTPException(status_code=401, detail="Not authenticated")
