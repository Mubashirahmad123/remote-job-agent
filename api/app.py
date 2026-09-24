"""FastAPI application factory — Phase 1 reads.

Lazy-import rule: this module (and api.cache / api.schemas / api.deps /
api.routers.*) MUST never import agents.curator or main at startup —
agents/curator.py:57-79 parses the CV on import. Pipeline modules are
therefore imported lazily inside handlers (Phase 1 needs none at all:
all reads go through api.cache, which lazy-loads only
tools.sheet_writer / tools.application_tracker on first use).

Bind rule: serve on 127.0.0.1 by default; a non-local bind requires API_TOKEN
to be set (see __main__ guard below).

Router layout (one file per group for easy debugging):
  api/deps.py            — CORS origins + Bearer auth
  api/mappers.py         — row -> schema converters
  api/routers/health.py  — GET /api/health
  api/routers/jobs.py    — GET /api/jobs, GET /api/jobs/{fp}
  api/routers/stats.py   — GET /api/stats
  api/routers/tracker.py — GET/PATCH /api/tracker
   api/routers/system.py  — POST /api/jobs/refresh
   api/runs.py + api/routers/runs.py — POST/GET /api/scrape (background runs)
   api/routers/cv.py      — GET /api/cv/profile, GET /api/cv/variants (CV Studio reads)
"""

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.deps import cors_origins
from api.routers import health, jobs, cv, materials, runs, stats, system, tracker

FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend"


def create_app() -> FastAPI:
    app = FastAPI(title="remote-job-agent API (Phase 1 reads)", docs_url="/docs")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins(),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization"],
    )

    # One include per group — comment out a single line to isolate a bug.
    app.include_router(health.router)
    app.include_router(jobs.router)
    app.include_router(stats.router)
    app.include_router(tracker.router)
    app.include_router(system.router)
    app.include_router(runs.router)
    app.include_router(materials.router)
    app.include_router(cv.router)

    # Serve the dashboard UI same-origin so file:// CORS ("null" origin)
    # is never an issue: open http://127.0.0.1:8000/ instead of index.html.
    # Mounted LAST so /api/* and /docs always win over static files.
    if FRONTEND_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")

    return app


app = create_app()


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    host = os.getenv("API_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = int(os.getenv("API_PORT", "8000").strip() or "8000")
    non_local = host not in ("127.0.0.1", "localhost", "::1")
    if non_local and not (os.getenv("API_TOKEN") or "").strip():
        raise SystemExit(
            "Refusing non-local bind without API_TOKEN set. "
            "Bind 127.0.0.1 (default) or set API_TOKEN."
        )
    uvicorn.run("api.app:app", host=host, port=port)
