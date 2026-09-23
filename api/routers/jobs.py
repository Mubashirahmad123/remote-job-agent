"""GET /api/jobs + GET /api/jobs/{fingerprint} — enriched job reads."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from api import cache
from api.deps import require_token
from api.mappers import to_job_out
from api.schemas import JobOut

router = APIRouter(tags=["jobs"])


@router.get("/api/jobs", response_model=List[JobOut])
def list_jobs(
    _: None = Depends(require_token),
    tab: str = Query("ALL JOBS"),
    q: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> List[JobOut]:
    try:
        jobs = cache.get_jobs(tab=tab)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if source:
        wanted = source.strip().lower()
        jobs = [j for j in jobs if (j.get("source") or "").strip().lower() == wanted]
    if q:
        needle = q.strip().lower()
        jobs = [
            j
            for j in jobs
            if needle
            in " ".join(
                str(j.get(k) or "")
                for k in ("job_title", "company", "summary", "tech_stack")
            ).lower()
        ]
    page = jobs[offset:offset + limit]
    return [to_job_out(j) for j in page]


@router.get("/api/jobs/{job_fingerprint}", response_model=JobOut)
def get_job(job_fingerprint: str, _: None = Depends(require_token)) -> JobOut:
    job = cache.get_job(job_fingerprint)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return to_job_out(job)
