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


def credentials_ok(request: Request, creds: HTTPAuthorizationCredentials | None = None) -> bool:
    """True when this caller is authenticated by ANY accepted mechanism.

    Single source of truth for "may this request through", shared by
    `require_token` (the /api/* dependency) and the middleware that guards
    /docs + /openapi.json. Keeping one predicate means the two can never drift
    apart — a docs gate that is laxer than the API gate would still leak the
    full route inventory.

    Order matters: a valid session wins before any Bearer inspection, so a
    logged-in operator who is ALSO sending a stale/wrong token is not locked
    out (and a wrong Bearer alone is never a pass).
    """
    from api.auth import open_access, session_user

    if session_user(request) is not None:
        return True
    expected = (os.getenv("API_TOKEN") or "").strip()
    if expected:
        provided = (creds.credentials or "").strip() if creds else ""
        return provided == expected
    return open_access()


def bearer_from_request(request: Request) -> HTTPAuthorizationCredentials | None:
    """Parse an `Authorization: Bearer <token>` header without FastAPI DI.

    Needed by middleware, which cannot use `Depends`. Returns None for any
    other scheme or a malformed header (never raises).
    """
    raw = ""
    try:
        raw = request.headers.get("authorization") or ""
    except Exception:
        return None
    parts = raw.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token) if token else None


def require_token(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    """Authenticate every /api/* call: session cookie OR server-side Bearer.

    Order of checks (see `credentials_ok`):
      1. Valid HttpOnly session cookie (browser login flow) -> allow.
      2. Authorization: Bearer <API_TOKEN> exact match (server-to-server:
         scheduler/CI; the token never appears in the browser) -> allow.
         A wrong Bearer is a 401, never a fallthrough.
      3. Fresh local-dev default: API_TOKEN unset AND no users exist ->
         allow, preserving today's open-localhost behavior until the first
         user is created or API_TOKEN is set. DB errors fail closed (401).
    """
    if not credentials_ok(request, creds):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return None



# --- Actor attribution (Scenario A — multi-operator) --------------------------
#
# Auth answers "may this request through?". Attribution answers "who did it?".
# Before this, `apply_access_ok()` returned a bool and threw the identity away,
# so every claim, intent, artifact and tracker row was recorded with no author.
#
# Precedence (BACKEND.md §4, PM.md §5) — explicit, not accidental:
#   valid session only            -> the username
#   valid service Bearer only     -> AUTOMATION_ACTOR
#   BOTH                          -> session wins (the username)
#   neither                       -> no actor (caller decides: 401 or a default)
#
# "Session wins" matters because a request can legitimately carry both — a
# reverse proxy that injects the service token, or a test harness. Recording
# "automation" there would blame the machine for a human's decision.

AUTOMATION_ACTOR = "automation"

# Actor recorded when auth is not being enforced at all (fresh clone: no users,
# no API_TOKEN — see api.auth.open_access). `require_token` deliberately allows
# those requests, so `require_actor` must attribute them rather than 401:
# failing closed here would break every write on a fresh install, which is the
# documented first-run experience. Kept distinct from AUTOMATION_ACTOR so a row
# reading "local-dev" is unambiguous — it means "written while auth was off",
# not "written by a service token".
OPEN_ACCESS_ACTOR = "local-dev"


def _bearer_matches(creds, env_var: str) -> bool:
    """Constant-time compare of a Bearer credential against one env secret."""
    import hmac

    expected = (os.getenv(env_var) or "").strip()
    provided = (creds.credentials or "").strip() if creds else ""
    return bool(expected) and bool(provided) and hmac.compare_digest(provided, expected)


def resolve_actor(request: Request, creds: HTTPAuthorizationCredentials | None = None) -> str:
    """The attributed actor for this request, or "" when there is none.

    Session first, then the service tokens. Returns "" (never None) so callers
    can treat it as a plain string and branch on truthiness.
    """
    from api.auth import open_access, session_user

    user = session_user(request)
    if user is not None:
        return user.get("username") or AUTOMATION_ACTOR
    if _bearer_matches(creds, "APPLY_API_TOKEN") or _bearer_matches(creds, "API_TOKEN"):
        return AUTOMATION_ACTOR
    # Last, not first: an authenticated identity always beats the "auth is off"
    # sentinel, so a real username is never masked by open-access mode.
    if open_access():
        return OPEN_ACCESS_ACTOR
    return ""


def resolve_session_role(request: Request) -> str:
    """Role of the session user, or "" when the caller is not a logged-in human.

    A service Bearer has no role: it is not a person, so it can never satisfy an
    admin-only gate. That is deliberate — an admin-only route must require an
    actual admin session, not a shared secret.
    """
    from api.auth import ROLE_OPERATOR, session_user

    user = session_user(request)
    if user is None:
        return ""
    return user.get("role") or ROLE_OPERATOR


def require_actor(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    """FastAPI dependency returning the actor string for a write path.

    Fails closed: 401 when no identifiable actor exists. Never returns "" —
    an unattributed write is exactly the bug this dependency exists to prevent.
    """
    actor = resolve_actor(request, creds)
    if not actor:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return actor


def require_submit_actor(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    """Attribution + authorization for POST /api/apply/{fp}/submit.

    Two ways to be allowed, matching the two credential classes the apply gate
    already accepts:
      1. A logged-in **admin** session -> attributed by username.
      2. `Authorization: Bearer <APPLY_API_TOKEN>` with NO session -> attributed
         as "automation". This is the documented server-to-server path; killing
         it would contradict why APPLY_API_TOKEN exists at all.

    Precedence follows the attribution rule — **the session wins**. If a session
    is present, that human is the actor and must be an admin; a service token
    riding along in the same request does not upgrade an operator. That is
    deliberate: otherwise an operator-role user could reach submit by having a
    proxy attach the token, and the role gate would be decorative.

    A service Bearer is intentionally NOT treated as an admin — it is a shared
    secret, not a person, so it has no role (see `resolve_session_role`).

    Status codes: 401 when nothing identifies the caller (so an anonymous probe
    learns nothing about the route), 403 when the caller is identified but not
    permitted. The SUBMIT_ENABLED kill-switch still answers 403 independently of
    this gate, and runs after it in the route.
    """
    from api.auth import ROLE_ADMIN, open_access, session_user

    if session_user(request) is not None:
        actor = require_actor(request, creds)
        if resolve_session_role(request) != ROLE_ADMIN:
            raise HTTPException(
                status_code=403,
                detail="Administrator session required to submit an application",
            )
        return actor
    if _bearer_matches(creds, "APPLY_API_TOKEN"):
        return AUTOMATION_ACTOR
    if open_access():
        return OPEN_ACCESS_ACTOR
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
