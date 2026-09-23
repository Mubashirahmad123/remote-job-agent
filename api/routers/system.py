"""POST /api/jobs/refresh — invalidate sheet cache on demand."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from api import cache
from api.deps import require_token

router = APIRouter(tags=["system"])


@router.post("/api/jobs/refresh")
def refresh_jobs(
    body: Optional[dict] = None, _: None = Depends(require_token)
) -> dict:
    tab = (body or {}).get("tab") if isinstance(body, dict) else None
    try:
        cleared = cache.refresh(tab)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # Warm the cleared tabs so the response reflects fresh reads.
    warmed: dict = {}
    for t in cleared if tab else list(cache.ALL_TABS):
        try:
            if t in cache.JOB_TABS:
                warmed[t] = len(cache.get_jobs(tab=t, force=True))
            else:
                warmed[t] = len(cache.get_tab_rows(t, force=True))
        except Exception:
            warmed[t] = 0
    return {"status": "ok", "cleared": cleared, "warmed": warmed}
