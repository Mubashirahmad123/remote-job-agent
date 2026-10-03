"""GET /api/skills — aggregated `tech_stack` demand across a job tab.

Replaces the dashboard's static skill cloud. Read-only, cache-backed (same
TTL as /api/jobs and /api/stats), so it costs no extra Sheets round-trip
when the tab is already warm.
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from api import cache
from api.deps import require_token
from api.schemas import SkillsOut

router = APIRouter(tags=["skills"])


@router.get("/api/skills", response_model=SkillsOut)
def skills(
    _: None = Depends(require_token),
    tab: str = Query("ALL JOBS"),
    limit: int = Query(12, ge=1, le=100),
) -> SkillsOut:
    try:
        snapshot = cache.get_skills_snapshot(tab=tab, limit=limit)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return SkillsOut(**snapshot)
