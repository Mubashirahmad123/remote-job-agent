"""POST /api/auth/login, POST /api/auth/logout, GET /api/auth/me.

Browser auth: username + password -> server-side session -> HttpOnly
cookie. API_TOKEN stays server-side only (Bearer for server-to-server
calls via deps.require_token) and is never accepted here.

Abuse resistance (this endpoint is the ONLY unauthenticated write on the API)
  1. Rate limit FIRST — api.ratelimit checks a per-IP and a per-username
     sliding window before any Argon2 work, and answers 429 + Retry-After.
  2. `async def` + `await asyncio.sleep()` for the failure penalty. The old
     sync handler called `time.sleep(0.5)`, which held a Starlette threadpool
     worker for the whole penalty: ~40 concurrent bad passwords saturated the
     default 40-thread pool and stalled every other sync route (measured 5.6s
     wall). Awaiting costs one cheap task instead.
  3. The blocking work that remains (SQLite + Argon2 verify) is dispatched to
     the threadpool explicitly via `run_in_threadpool`, so the event loop is
     never blocked by a slow hash.
  4. `purge_expired_sessions()` moved to the SUCCESS path — a failed attempt
     no longer earns an unauthenticated database write.
"""

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool

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
from api.ratelimit import client_ip, login_limiter
from api.schemas import LoginRequest

router = APIRouter(prefix="/api/auth", tags=["auth"])

logger = logging.getLogger("api.auth")

# Failure penalty: long enough to slow an interactive guesser, short enough to
# be harmless now that it is awaited instead of blocking a worker thread.
FAILURE_DELAY_SECONDS = 0.5


@router.post("/login")
async def login(body: LoginRequest, request: Request, response: Response) -> dict:
    """Verify credentials, create a server-side session, set the cookie."""
    ip = client_ip(request)
    username = (body.username or "").strip()

    # --- 1. Budget check BEFORE any expensive work --------------------------
    decision = login_limiter.allow(ip, username)
    if not decision.allowed:
        # Deliberately vague: do not reveal which budget tripped or whether the
        # username exists. Retry-After lets an honest client back off properly.
        logger.warning("login rate-limited ip=%s user=%s", ip, username or "-")
        raise HTTPException(
            status_code=429,
            detail="Too many sign-in attempts. Try again later.",
            headers={"Retry-After": str(decision.retry_after)},
        )

    # --- 2. Verify off the event loop ---------------------------------------
    user = await run_in_threadpool(verify_login, username, body.password)
    if user is None:
        logger.warning("login failed ip=%s user=%s", ip, username or "-")
        await asyncio.sleep(FAILURE_DELAY_SECONDS)  # non-blocking penalty
        # Same message for unknown-user and wrong-password: no enumeration.
        raise HTTPException(status_code=401, detail="Invalid username or password")

    # --- 3. Success: housekeeping, then mint the session ---------------------
    await run_in_threadpool(purge_expired_sessions)
    token, expires_at = await run_in_threadpool(create_session, user["id"])
    # A successful login clears the per-ACCOUNT budget so an operator who
    # mistyped twice is not punished later. The per-IP budget stays: one valid
    # credential does not prove the address is benign.
    login_limiter.clear_success(ip, username)
    set_session_cookie(response, token, secure=_cookie_secure(request))
    logger.info("login ok ip=%s user=%s", ip, user["username"])
    return {
        "authenticated": True,
        "username": user["username"],
        "expires_at": expires_at,
        "rate_limit_remaining": decision.remaining,
    }


@router.post("/logout")
async def logout(request: Request, response: Response) -> dict:
    """Invalidate the session server-side + clear the cookie (idempotent)."""
    token = request.cookies.get(SESSION_COOKIE) or ""
    deleted = await run_in_threadpool(delete_session, token) if token else False
    clear_session_cookie(response, secure=_cookie_secure(request))
    return {"ok": True, "deleted": bool(deleted)}


@router.get("/me")
async def me(request: Request) -> dict:
    """Current session identity; 401 only when auth is enforced."""
    user = await run_in_threadpool(session_user, request)
    if user is not None:
        return {
            "authenticated": True,
            "username": user["username"],
            "expires_at": user["expires_at"],
        }
    from api.auth import open_access

    if await run_in_threadpool(open_access):
        # Fresh local-dev instance (no API_TOKEN, no users): no session to
        # report, but nothing is enforced either — do not 401 the bootstrap.
        return {"authenticated": False, "open_access": True}
    raise HTTPException(status_code=401, detail="Not authenticated")
