"""FastAPI application factory — Phase 1 reads.

Lazy-import rule: this module (and api.cache / api.schemas / api.deps /
api.routers.*) MUST never import agents.curator or main at startup —
agents/curator.py:57-79 parses the CV on import. Pipeline modules are
therefore imported lazily inside handlers (Phase 1 needs none at all:
all reads go through api.cache, which lazy-loads only
tools.sheet_writer / tools.application_tracker on first use).

Bind rule: serve on 127.0.0.1 by default; a non-local bind requires API_TOKEN
to be set (enforced at import time inside create_app(), and checked against
BOTH the API_HOST env var and uvicorn's own `--host` flag — either one alone
decides the real bind address depending on how the app is started).

Auth rule: browser users log in (api/routers/auth.py — username+password ->
server-side session -> HttpOnly cookie); /api/* require a valid session via
deps.require_token. API_TOKEN stays server-side only (Bearer for
server-to-server calls) and is never exposed to the browser. `GET /` gates
the dashboard: unauthenticated visitors are redirected to /login.html.

Fail-CLOSED rule: auth is attached at the ROUTER level (`_gated`) as well as
per route, so a newly added endpoint is authenticated even if its author
forgets the `Depends(require_token)`. Only api/routers/auth.py is exempt —
/api/auth/login has to be reachable with no session. The same predicate
(`deps.credentials_ok`) also guards /docs + /openapi.json and the directly
navigable /index.html, neither of which any router dependency can reach.

Router layout (one file per group for easy debugging):
   api/deps.py            — CORS origins + session/Bearer auth
   api/ratelimit.py       — sliding-window limiter for /api/auth/login
   api/routers/auth.py    — POST /api/auth/login, POST logout, GET /api/auth/me
   api/routers/liveness.py— GET /api/health/live (unauthenticated probe)
   api/activity.py + api/routers/activity.py — GET /api/activity (actor feed)
   api/mappers.py         — row -> schema converters
   api/routers/health.py  — GET /api/health
   api/routers/jobs.py    — GET /api/jobs, GET /api/jobs/{fp}
   api/routers/stats.py   — GET /api/stats
   api/routers/skills.py  — GET /api/skills (tech_stack demand aggregate)
   api/routers/tracker.py — GET/PATCH /api/tracker
    api/routers/system.py  — POST /api/jobs/refresh
    api/runs.py + api/routers/runs.py — POST/GET /api/scrape (background runs)
    api/routers/cv.py      — GET /api/cv/profile, GET /api/cv/variants (CV Studio reads)
     api/safety.py + api/apply.py + api/routers/apply.py — POST /api/apply/{fp}
      fill-only (mode=review) + Greenhouse-only /intent + /submit (2b split;
      Lever has no submit path)
"""

import os
import sys
import warnings
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from api.deps import bearer_from_request, cors_origins, credentials_ok, require_token
from api.routers import activity, auth, health, jobs, cv, liveness, materials, runs, skills, stats, system, tracker, apply

FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend"

_LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")

# Docs are served by FastAPI itself, so no router dependency can reach them.
# They are gated by default: an unauthenticated scanner that finds the host
# should not also be handed the complete route inventory. A logged-in operator
# still gets Swagger, because the browser sends the session cookie same-origin.
# Set API_DOCS_ENABLED=true to publish them again.
_DOCS_PATHS = frozenset({"/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"})

# The dashboard shell is served by the StaticFiles mount, which bypasses the
# `GET /` route entirely — naming the file directly would otherwise hand the
# UI to someone with no session.
_DASHBOARD_PATHS = frozenset({"/index.html", "/index.htm"})


def _docs_enabled() -> bool:
    return (os.getenv("API_DOCS_ENABLED") or "").strip().lower() in ("1", "true", "yes", "on")


def _argv_host() -> str:
    """The host uvicorn was actually told to bind, from sys.argv, or "".

    Handles both `--host 0.0.0.0` and `--host=0.0.0.0`. uvicorn parses its CLI
    before importing the app module, so sys.argv is already complete when
    create_app() runs.
    """
    argv = list(sys.argv or [])
    for index, arg in enumerate(argv):
        if arg == "--host" and index + 1 < len(argv):
            return argv[index + 1].strip()
        if arg.startswith("--host="):
            return arg.split("=", 1)[1].strip()
    return ""


def _enforce_bind_guard() -> None:
    """Refuse a non-local bind without API_TOKEN (import-time, both entry points).

    Checks API_HOST *and* uvicorn's `--host`. Reading only the env var left the
    documented run command — `uvicorn api.app:app --host 0.0.0.0` with API_HOST
    unset — passing the guard while binding on every interface, which combined
    with `open_access()` (no users, no token) meant a fully public API.
    Localhost default stays open for dev.
    """
    host = (os.getenv("API_HOST", "127.0.0.1").strip() or "127.0.0.1")
    argv_host = _argv_host()
    candidates = [host] + ([argv_host] if argv_host else [])
    non_local = any(candidate not in _LOCAL_HOSTS for candidate in candidates)
    if non_local and not (os.getenv("API_TOKEN") or "").strip():
        raise RuntimeError(
            "Refusing non-local bind without API_TOKEN set. "
            "Bind 127.0.0.1 (default) or set API_TOKEN. "
            f"(saw API_HOST={host!r}, --host={argv_host or 'unset'!r})"
        )


class _GateMiddleware(BaseHTTPMiddleware):
    """Fail-closed gates for paths that no router dependency can reach.

    Runs before routing, so it also covers 404s and the static mount. Adds the
    baseline security headers on EVERY response so the app is not silently
    unprotected when deployed without Caddy in front of it.
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if (path in _DOCS_PATHS and not _docs_enabled()) or (
            path in _DASHBOARD_PATHS and request.method == "GET"
        ):
            if not credentials_ok(request, bearer_from_request(request)):
                if path in _DASHBOARD_PATHS:
                    return RedirectResponse("/login.html", status_code=302)
                return Response(
                    status_code=401,
                    media_type="application/json",
                    content='{"detail":"Unauthorized"}',
                )

        response = await call_next(request)

        # No Content-Security-Policy: the dashboard relies on inline
        # <script>/<style> blocks (login.html included), so a strict CSP would
        # break the UI. Shipping one means first extracting every inline block
        # — deliberately not half-done here.
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return response


def _include_gated(app: FastAPI, module) -> None:
    """Include one router with auth attached at the ROUTER level.

    Every route in these routers already repeats `Depends(require_token)` and
    all 24 were correct — but per-route auth fails OPEN: one forgotten line on
    a new route ships a public endpoint. Gating at include time makes the safe
    behaviour the default. `apply.py` keeps its stricter per-route
    `require_apply_token` on top; both run and the stricter one still wins.

    IMPORTANT — this must go through `include_router(dependencies=...)`, NOT by
    appending to `module.router.dependencies`. This FastAPI version resolves
    included routers lazily (`_IncludedRouter`), and mutating the list after
    construction is a silent no-op: the routes register, the app starts, and
    every request is served UNGATED. Declaring the dependency at construction
    or at include time both work; mutation does not. There is a test
    (`test_router_level_gate_covers_a_route_that_forgets_its_dependency`) that
    fails closed if this ever regresses.
    """
    app.include_router(module.router, dependencies=[Depends(require_token)])


# `auth` and `liveness` are deliberately absent: /api/auth/login must stay
# reachable logged out, and an unauthenticated probe needs /api/health/live to
# tell "up but not signed in" apart from "down".
_GATED_ROUTERS = (
    health, jobs, stats, skills, tracker, system, runs, materials, cv, apply, activity
)

# Included with NO router-level auth dependency.
_OPEN_ROUTERS = (auth, liveness)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Announce the auth posture once at startup.

    `open_access()` (no API_TOKEN AND no users) serves the ENTIRE API with no
    credentials. That is a deliberate localhost convenience, but a forgotten
    `create_user.py` on a public host means an open API — so the condition is
    shouted about at every start instead of failing silently. It is a warning,
    not a refusal: refusing would break the documented fresh-clone developer
    experience.
    """
    from api.auth import count_users, open_access

    try:
        is_open = open_access()
    except Exception:
        is_open = False
    if is_open:
        warnings.warn(
            "AUTH OPEN ACCESS: no users exist and API_TOKEN is unset, so every "
            "/api/* route is currently UNAUTHENTICATED. This is only safe on a "
            "loopback bind. Before exposing this host, run "
            "`python create_user.py <username>` and set API_TOKEN.",
            stacklevel=2,
        )
    else:
        print(
            "[api] auth enforced "
            f"(users={count_users()}, "
            f"api_token={'set' if (os.getenv('API_TOKEN') or '').strip() else 'unset'})",
            flush=True,
        )
    yield


def create_app() -> FastAPI:
    _enforce_bind_guard()

    # The docs routes are ALWAYS created — disabling them here would 404 for a
    # logged-in operator too, since FastAPI would never register the paths.
    # Access is decided by _GateMiddleware instead: anonymous -> 401, valid
    # session (the browser sends the HttpOnly cookie same-origin) -> Swagger.
    # API_DOCS_ENABLED=true makes them public again.
    app = FastAPI(
        title="remote-job-agent API (Phase 1 reads)",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=_lifespan,
    )

    app.add_middleware(_GateMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins(),
        # Auth is an HttpOnly COOKIE now, so credentials must be allowed for a
        # cross-origin dashboard to authenticate at all. Safe here because
        # `cors_origins()` always returns an explicit list, never "*" — and
        # Starlette rejects "*" combined with credentials anyway. The default
        # stays localhost-only; API_CORS_ORIGINS widens it deliberately.
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization"],
    )

    # One include per group — comment out a single line to isolate a bug.
    # `auth` is included ungated: /api/auth/login must stay reachable logged out.
    for module in _OPEN_ROUTERS:
        app.include_router(module.router)
    for module in _GATED_ROUTERS:
        _include_gated(app, module)

    @app.get("/", include_in_schema=False)
    def root_gate(request: Request):
        """Dashboard entry point: valid session (or fresh open local dev) gets
        the dashboard; anyone else is redirected to the login page. The API
        stays the hard gate — this only shapes the UX.
        """
        from api.auth import open_access, session_user

        if session_user(request) is not None or open_access():
            index = FRONTEND_DIR / "index.html"
            if index.is_file():
                return FileResponse(str(index))
            return {"detail": "Dashboard frontend missing (frontend/index.html)"}
        return RedirectResponse("/login.html", status_code=302)

    # Serve the dashboard UI same-origin so file:// CORS ("null" origin) is
    # never an issue: open http://127.0.0.1:8000/ instead of index.html.
    # Mounted LAST so /api/*, /docs, and the / gate above always win.
    if FRONTEND_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")

    return app


app = create_app()


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    # Reuse the import-time guard so both entry points agree; create_app()
    # already enforced it, this just surfaces the same error before uvicorn
    # starts for `python api/app.py` users.
    _enforce_bind_guard()
    host = os.getenv("API_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = int(os.getenv("API_PORT", "8000").strip() or "8000")
    uvicorn.run("api.app:app", host=host, port=port)
