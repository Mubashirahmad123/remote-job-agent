"""GET /api/health — presence-only signals, never secret values."""

from fastapi import APIRouter, Depends

from api import cache
from api.deps import require_token
from api.schemas import HealthOut

router = APIRouter(tags=["health"])


@router.get("/api/health", response_model=HealthOut)
def health(_: None = Depends(require_token)) -> HealthOut:
    return HealthOut(
        status="ok",
        sheets_configured=cache.sheets_configured(),
        curated_jobs_loaded=cache.curated_count(),
        data_source=cache.data_source(),
    )
