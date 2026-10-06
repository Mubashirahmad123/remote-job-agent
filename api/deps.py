"""Shared FastAPI dependencies: CORS origins + session/Bearer auth.

Extracted from api/app.py so every router file stays small and
debuggable. No pipeline imports here (lazy-import rule still holds).
"""

import os

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

# CORS: localhost-only by default. Override with comma-separated
# API_CORS_ORIGINS. Non-local origins are never added unless explicitly set.
DEFAULT_CORS_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://localhost:8080",
    "http://127.0.0.1:8080",
]


def cors_origins() -> list:
    raw = os.getenv("API_CORS_ORIGINS", "").strip()
    if not raw:
        return list(DEFAULT_CORS_ORIGINS)
    return [o.strip() for o in raw.split(",") if o.strip()]


_bearer = HTTPBearer(auto_error=False)


def require_token(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    """Authenticate every /api/* call: session cookie OR server-side Bearer.

    Order of checks:
      1. Valid HttpOnly session cookie (browser login flow) -> allow.
      2. Authorization: Bearer <API_TOKEN> exact match (server-to-server:
         scheduler/CI; the token never appears in the browser) -> allow.
         A wrong Bearer is a 401, never a fallthrough.
      3. Fresh local-dev default: API_TOKEN unset AND no users exist ->
         allow, preserving today's open-localhost behavior until the first
         user is created or API_TOKEN is set. DB errors fail closed (401).
    """
    from api.auth import open_access, session_user

    if session_user(request) is not None:
        return None
    expected = (os.getenv("API_TOKEN") or "").strip()
    if expected:
        provided = (creds.credentials or "").strip() if creds else ""
        if provided != expected:
            raise HTTPException(status_code=401, detail="Unauthorized")
        return None
    if open_access():
        return None
    raise HTTPException(status_code=401, detail="Unauthorized")


def apply_access_ok(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = None,
) -> bool:
    """True when the caller may use submit-adjacent endpoints.

    Two credential classes, both server-issued, never browser-stored:
      1. A valid user session cookie — the logged-in dashboard user acting
         human-in-the-loop (the apply flow is user-initiated by design).
      2. Authorization: Bearer <APPLY_API_TOKEN> exact match — the dedicated
         elevated env secret for server-to-server/scripted use. The general
         API_TOKEN is never accepted here, and the value stays server-side.
    The SUBMIT_ENABLED kill-switch (api/safety.py) still gates /submit
    regardless of which credential class passed.
    """
    from api.auth import session_user

    if session_user(request) is not None:
        return True
    expected = (os.getenv("APPLY_API_TOKEN") or "").strip()
    provided = (creds.credentials or "").strip() if creds else ""
    return bool(expected) and provided != "" and provided == expected


def require_apply_token(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    """Session OR Bearer APPLY_API_TOKEN; anything else is a 401."""
    if not apply_access_ok(request, creds):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return None
