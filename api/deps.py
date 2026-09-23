"""Shared FastAPI dependencies: CORS origins + Bearer auth.

Extracted from api/app.py so every router file stays small and
debuggable. No pipeline imports here (lazy-import rule still holds).
"""

import os

from fastapi import Depends, HTTPException
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
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    """Enforce Authorization: Bearer <API_TOKEN> when API_TOKEN is set.

    No token configured -> allow all (local-dev default). Token configured ->
    require an exact match on every /api/* call, including reads, so a
    non-local bind (API_HOST=0.0.0.0 + API_TOKEN) is actually protected.
    """
    expected = (os.getenv("API_TOKEN") or "").strip()
    if not expected:
        return None
    provided = (creds.credentials or "").strip() if creds else ""
    if not provided or provided != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return None
