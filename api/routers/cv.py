"""GET/PUT /api/cv/profile + GET /api/cv/variants + POST /api/cv/upload — CV Studio."""

from typing import Annotated, List

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool

from api import cache
from api.cv_store import CvUploadError, ingest_cv_upload
from api.deps import action_budget, require_token
from api.schemas import CvProfileOut, CvProfileUpdate, CvUploadOut, CvVariant

router = APIRouter(tags=["cv"])


@router.get("/api/cv/profile", response_model=CvProfileOut)
def get_cv_profile(_: None = Depends(require_token)) -> CvProfileOut:
    """Return the cached parsed-CV profile.

    501 by design when no fresh disk cache exists: per-request LLM parsing
    is disabled, so the client should run the pipeline once (parse_cv writes
    cache/cv_profile_*.json) instead of triggering heavy work here.
    """
    profile = cache.get_cv_profile()
    if profile is None:
        raise HTTPException(
            status_code=501,
            detail=(
                "No cached CV profile available. Run the pipeline once so "
                "tools/cv_parser writes cache/cv_profile_*.json; "
                "per-request LLM parsing is disabled by design."
            ),
        )
    return CvProfileOut(**profile)


@router.put("/api/cv/profile", response_model=CvProfileOut)
def update_cv_profile(
    patch: CvProfileUpdate, _: None = Depends(require_token)
) -> CvProfileOut:
    """Persist Resume Studio edits into the on-disk cv_parser cache.

    Merges whitelisted contact + skill fields only; never triggers LLM
    parsing. 501 when no CV file / cache anchor exists (same condition as
    GET). Never 500 on bad input — unknown fields ignored, bad types coerced.
    """
    try:
        data = patch.model_dump(exclude_unset=True)
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    merged = cache.save_cv_profile(data)
    if merged is None:
        raise HTTPException(
            status_code=501,
            detail=(
                "No cached CV profile available to update. Run the pipeline "
                "once so tools/cv_parser writes cache/cv_profile_*.json first."
            ),
        )
    return CvProfileOut(**merged)


@router.get("/api/cv/variants", response_model=List[CvVariant])
def list_cv_variants(_: None = Depends(require_token)) -> List[CvVariant]:
    """List CV variants (safe basenames + domain tags). Missing dir -> []."""
    rows = cache.list_cv_variants()
    return [CvVariant(**r) for r in rows if isinstance(r, dict)]


@router.post("/api/cv/upload", response_model=CvUploadOut)
async def upload_cv(
    request: Request,
    filename: Annotated[str, Query(min_length=1, max_length=180)],
    __: None = Depends(action_budget("action")),
    _: None = Depends(require_token),
) -> CvUploadOut:
    """Store an uploaded CV file into the CV library as a tagged variant.

    Raw-body upload: the browser sends the file bytes as the request body
    with ?filename= as metadata — no python-multipart dependency. Offline
    validation only (magic bytes, size cap, extractability probe); no
    per-request LLM parsing, same rule as GET /api/cv/profile. The ingest
    does blocking disk/CPU work (atomic write + extraction probe), so it
    runs on the threadpool, never on the event loop.
    """
    body = await request.body()
    try:
        result = await run_in_threadpool(ingest_cv_upload, filename, body)
    except CvUploadError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    return CvUploadOut(**result)
