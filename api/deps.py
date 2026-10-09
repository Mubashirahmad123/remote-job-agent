"""Shared FastAPI dependencies: CORS origins + session/Bearer auth.

Extracted from api/app.py so every router file stays small and
debuggable. No pipeline imports here (lazy-import rule still holds).
"""

import os
import warnings
from urllib.parse import urlparse

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


def _origin_problem(origin: str) -> str:
    """Why `origin` cannot be used as a CORS allow-list entry, or '' if it can.

    Starlette matches these strings verbatim against the request's Origin
    header, so anything that is not exactly `scheme://host[:port]` is dead
    config: it looks like it grants access and never matches anything.
    """
    if "*" in origin:
        return (
            "a wildcard. With allow_credentials=True Starlette does NOT reject "
            "it — preflight_explicit_allow_origin is `not allow_all_origins or "
            "allow_credentials`, so `*` plus credentials makes it REFLECT the "
            "caller's Origin and answer Access-Control-Allow-Credentials: true. "
            "That lets any website read authenticated responses. Name the origin."
        )
    if origin == "null":
        return "the `null` origin (file:// and sandboxed frames); serve the UI from the API"
    parsed = urlparse(origin)
    if parsed.scheme not in ("http", "https"):
        return f"scheme {parsed.scheme or '(none)'!r} is not http/https"
    if not parsed.hostname:
        return "has no host"
    if parsed.path not in ("", "/"):
        return f"carries a path ({parsed.path!r}); an Origin header never does, so it would never match"
    if origin.endswith("/"):
        return "has a trailing slash; an Origin header never does, so it would never match"
    if parsed.query or parsed.fragment:
        return "carries a query or fragment, which an Origin header never does"
    return ""


def cors_origins() -> list:
    """Allowed cross-origin dashboard origins.

    API_CORS_ORIGINS is FILTERED, not trusted. Three separate places used to
    claim a wildcard "is never accepted" (here, api/app.py, PRODUCTION.md,
    .env.example) while nothing in the code enforced it — and it was
    demonstrably false: with API_CORS_ORIGINS=* a request from
    `Origin: https://evil.example` came back with

        Access-Control-Allow-Origin: https://evil.example
        Access-Control-Allow-Credentials: true

    and GET /api/jobs returned 200 carrying the operator's session cookie, so
    any website could read the jobs, tracker, CV profile and audit feed of a
    logged-in operator.

    Rejected entries are dropped with a warning rather than raising: refusing to
    boot over a CORS typo would take the whole agent down, and dropping to the
    localhost defaults is strictly more restrictive than what was asked for, so
    this fails safe in the right direction.
    """
    raw = os.getenv("API_CORS_ORIGINS", "").strip()
    if not raw:
        return list(DEFAULT_CORS_ORIGINS)

    allowed: list = []
    rejected: list = []
    for entry in raw.split(","):
        origin = entry.strip()
        if not origin:
            continue
        problem = _origin_problem(origin)
        if problem:
            rejected.append((origin, problem))
        elif origin not in allowed:
            allowed.append(origin)

    for origin, problem in rejected:
        warnings.warn(
            f"[api] API_CORS_ORIGINS entry {origin!r} ignored: {problem}",
            RuntimeWarning,
            stacklevel=2,
        )
    if not allowed:
        warnings.warn(
            "[api] API_CORS_ORIGINS contained no usable origin, so cross-origin "
            "access falls back to the localhost defaults. The dashboard is served "
            "same-origin by this API, which needs no CORS entry at all.",
            RuntimeWarning,
            stacklevel=2,
        )
        return list(DEFAULT_CORS_ORIGINS)
    return allowed


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


def action_budget(kind: str):
    """Dependency factory: spend one unit of the per-actor budget for `kind`.

    Added ALONGSIDE `require_token` rather than replacing it, so the
    authentication semantics of the routes it guards are unchanged — this is a
    cost ceiling, not an auth mechanism. It depends on `require_actor` only to
    learn WHO is spending, which is the identity already recorded for
    attribution.

    See api/ratelimit.py for why these endpoints needed a budget at all.
    """
    from api.ratelimit import action_limiter

    def _dependency(actor: str = Depends(require_actor)) -> None:
        decision = action_limiter.allow(actor, kind)
        if not decision.allowed:
            raise HTTPException(
                status_code=429,
                detail=(
                    "Too many requests of this kind. Each one runs an LLM call or "
                    "a headless browser, so they are budgeted per operator."
                ),
                headers={"Retry-After": str(max(1, decision.retry_after))},
            )
        return None

    return _dependency


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
