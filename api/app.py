"""FastAPI application factory — Phase 1 reads.

Lazy-import rule: this module (and api.cache / api.schemas / api.deps /
api.routers.*) MUST never import agents.curator or main at startup —
agents/curator.py:57-79 parses the CV on import. Pipeline modules are
therefore imported lazily inside handlers (Phase 1 needs none at all:
all reads go through api.cache, which lazy-loads only
tools.sheet_writer / tools.application_tracker on first use).

Bind rule: serve on 127.0.0.1 by default; a non-local bind requires API_TOKEN
to be set (enforced at import time inside create_app(), so the documented
`uvicorn api.app:app` path is covered — not just `python api/app.py`).

Auth rule: browser users log in (api/routers/auth.py — username+password ->
server-side session -> HttpOnly cookie); /api/* require a valid session via
deps.require_token. API_TOKEN stays server-side only (Bearer for
server-to-server calls) and is never exposed to the browser. `GET /` gates
the dashboard: unauthenticated visitors are redirected to /login.html.

Router layout (one file per group for easy debugging):
   api/deps.py            — CORS origins + session/Bearer auth
   api/routers/auth.py    — POST /api/auth/login, POST logout, GET /api/auth/me
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
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from api.deps import cors_origins
from api.routers import auth, health, jobs, cv, materials, runs, skills, stats, system, tracker, apply

FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend"


def _enforce_bind_guard() -> None:
    """Refuse non-local bind without API_TOKEN (import-time, not __main__-only).

    The old __main__-only guard never executed under the documented run path
    (uvicorn api.app:app), leaving a non-local bind fully open. create_app()
    runs on uvicorn import, so enforcing here closes the hole regardless of
    entry point. Localhost default stays open for dev.
    """
    host = (os.getenv("API_HOST", "127.0.0.1").strip() or "127.0.0.1")
    non_local = host not in ("127.0.0.1", "localhost", "::1")
    if non_local and not (os.getenv("API_TOKEN") or "").strip():
        raise RuntimeError(
            "Refusing non-local bind without API_TOKEN set. "
            "Bind 127.0.0.1 (default) or set API_TOKEN."
        )


def create_app() -> FastAPI:
    _enforce_bind_guard()
    app = FastAPI(title="remote-job-agent API (Phase 1 reads)", docs_url="/docs")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins(),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization"],
    )

    # One include per group — comment out a single line to isolate a bug.
    app.include_router(auth.router)
    app.include_router(health.router)
    app.include_router(jobs.router)
    app.include_router(stats.router)
    app.include_router(skills.router)
    app.include_router(tracker.router)
    app.include_router(system.router)
    app.include_router(runs.router)
    app.include_router(materials.router)
    app.include_router(cv.router)
    app.include_router(apply.router)

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

    # Serve the dashboard UI same-origin so file:// CORS ("null" origin)
    # is never an issue: open http://127.0.0.1:8000/ instead of index.html.
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
