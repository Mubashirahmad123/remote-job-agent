"""GET /api/health/live — unauthenticated liveness probe.

Why this exists separately from GET /api/health
  `/api/health` is gated (router-level `require_token`) and reports
  presence-only signals about Sheets and the curated-jobs cache. That is the
  right thing for an operator, and the wrong thing for a probe: an uptime
  monitor, a load balancer or a `docker compose` healthcheck has no session
  cookie, so it receives a 401 and cannot distinguish "the server is up but I
  am not logged in" from "the server is dead". Both look like an outage.

  This route answers the one question a probe actually has — is the process
  accepting requests — and nothing else.

Deliberately empty response
  No Sheets status, no job counts, no version, no user count, no config flags.
  An unauthenticated endpoint is a disclosure surface, so it discloses only that
  it answered. Anything worth knowing about the deployment belongs behind
  `/api/health`.

Not a readiness probe
  A 200 here means the HTTP server is alive. It does NOT mean Google Sheets is
  reachable or that the scrape pipeline works — use `/api/health` (authenticated)
  for that. Reporting dependency failures on an unauthenticated route would
  both leak state and flap the probe on transient upstream errors.
"""

from fastapi import APIRouter

# Included ungated in api/app.py (alongside the auth router) — see
# _GATED_ROUTERS, which deliberately omits this module.
router = APIRouter(tags=["liveness"])


@router.get("/api/health/live", include_in_schema=False)
def live() -> dict:
    return {"status": "ok"}
