"""POST /api/scrape + GET /api/scrape[/{run_id}] — background scrape runs."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException

from api import runs
from api.deps import require_token

router = APIRouter(tags=["runs"])


@router.post("/api/scrape", status_code=202)
def start_scrape(_: None = Depends(require_token)) -> dict:
    try:
        return runs.start_scrape()
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("/api/scrape", response_model=List[dict])
def list_scrapes(_: None = Depends(require_token)) -> List[dict]:
    return runs.list_runs()


@router.get("/api/scrape/{run_id}")
def get_scrape(run_id: str, _: None = Depends(require_token)) -> dict:
    run = runs.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run
