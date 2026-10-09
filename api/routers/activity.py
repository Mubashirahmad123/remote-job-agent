"""GET /api/activity?limit=N — merged, actor-attributed action feed.

Auth: gated at the router level like every other /api/* route (see
_GATE_ROUTERS in api/app.py), so any authenticated session may read it.

Login events are admin-only. They carry client IPs, which is a step more
sensitive than "who built which review package", so `include_logins` is set from
the caller's role rather than from a query parameter — a non-admin cannot ask
for them and be told no, they simply get the feed without them.
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Request

from api import activity
from api.deps import resolve_session_role

router = APIRouter(tags=["activity"])


@router.get("/api/activity")
def get_activity(
    request: Request,
    limit: Optional[int] = Query(None, ge=1, le=activity.MAX_LIMIT),
) -> Dict[str, Any]:
    """Newest-first merged feed over claims, intents, artifacts (+ logins for admin)."""
    from api.auth import ROLE_ADMIN

    is_admin = resolve_session_role(request) == ROLE_ADMIN
    events: List[Dict[str, Any]] = activity.collect(limit=limit, include_logins=is_admin)
    return {
        "count": len(events),
        "limit": limit if limit is not None else activity.DEFAULT_LIMIT,
        # Surfaced so a non-admin understands why sign-in history is absent
        # instead of assuming nobody has signed in.
        "includes_login_events": is_admin,
        "events": events,
    }
