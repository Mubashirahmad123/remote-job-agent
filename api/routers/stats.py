"""GET /api/stats — aggregate counts + raw STATS-tab rows."""

from fastapi import APIRouter, Depends

from api import cache
from api.deps import require_token

router = APIRouter(tags=["stats"])


@router.get("/api/stats")
def stats(_: None = Depends(require_token)) -> dict:
    return cache.get_stats_snapshot()
