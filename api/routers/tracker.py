"""GET /api/tracker + PATCH /api/tracker/{fp} — application tracker."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from api import cache
from api.deps import require_token
from api.mappers import to_tracker_entry
from api.schemas import TrackerEntry, TrackerUpdate, VALID_TRACKER_STATUSES

router = APIRouter(tags=["tracker"])


@router.get("/api/tracker", response_model=List[TrackerEntry])
def list_tracker(
    _: None = Depends(require_token),
    status: Optional[str] = Query(None),
) -> List[TrackerEntry]:
    return [to_tracker_entry(r) for r in cache.get_tracker_rows(status=status)]


@router.patch("/api/tracker/{job_fingerprint}", response_model=TrackerEntry)
def patch_tracker(
    job_fingerprint: str,
    body: TrackerUpdate,
    _: None = Depends(require_token),
) -> TrackerEntry:
    normalized = (body.status or "").strip().lower()
    if normalized not in VALID_TRACKER_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status '{body.status}'. "
            f"Choose from: {', '.join(sorted(VALID_TRACKER_STATUSES))}",
        )
    try:
        row = cache.update_tracker_and_get(
            job_fingerprint, normalized, body.notes or ""
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="Application not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Tracker update failed: {e}")
    if row is None:
        raise HTTPException(status_code=404, detail="Application not found")
    return to_tracker_entry(row)
