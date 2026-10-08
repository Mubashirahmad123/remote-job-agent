"""GET/POST /api/tracker + PATCH /api/tracker/{fp} — application tracker."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials

from api import cache
from api.deps import _bearer, apply_access_ok, require_actor, require_token
from api.errors import failure
from api.mappers import to_tracker_entry
from api.schemas import TrackerCreate, TrackerEntry, TrackerUpdate, VALID_TRACKER_STATUSES

router = APIRouter(tags=["tracker"])


@router.get("/api/tracker", response_model=List[TrackerEntry])
def list_tracker(
    _: None = Depends(require_token),
    status: Optional[str] = Query(None),
) -> List[TrackerEntry]:
    return [to_tracker_entry(r) for r in cache.get_tracker_rows(status=status)]


@router.post("/api/tracker", response_model=TrackerEntry, status_code=201)
def create_tracker_entry(
    body: TrackerCreate,
    _: None = Depends(require_token),
    actor: str = Depends(require_actor),
) -> TrackerEntry:
    try:
        row = cache.add_tracker_entry(body.model_dump(), created_by=actor)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise failure("Tracker create", e)
    return to_tracker_entry(row)


@router.patch("/api/tracker/{job_fingerprint}", response_model=TrackerEntry)
def patch_tracker(
    job_fingerprint: str,
    request: Request,
    body: TrackerUpdate,
    _: None = Depends(require_token),
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> TrackerEntry:
    normalized = (body.status or "").strip().lower()
    if normalized not in VALID_TRACKER_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status '{body.status}'. "
            f"Choose from: {', '.join(sorted(VALID_TRACKER_STATUSES))}",
        )
    from api import apply_state

    claim_status = apply_state.get_claim_status(job_fingerprint)
    if claim_status == "submit_unverified" or body.reconcile_submit_failure:
        if not apply_access_ok(request, creds):
            raise HTTPException(status_code=401, detail="Unauthorized")
        if body.reconcile_submit_failure and claim_status != "submit_unverified":
            raise HTTPException(status_code=409, detail="No submit_unverified claim to reconcile")
    try:
        row = cache.update_tracker_and_get(
            job_fingerprint, normalized, body.notes or ""
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="Application not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise failure("Tracker update", e)
    if row is None:
        raise HTTPException(status_code=404, detail="Application not found")
    if body.reconcile_submit_failure:
        from api.apply_claims import reconcile_failed_claim

        connection = apply_state.connect()
        try:
            reconciled = reconcile_failed_claim(connection, job_fingerprint)
        finally:
            connection.close()
        if not reconciled:
            raise HTTPException(status_code=409, detail="Submit claim was already reconciled")
    return to_tracker_entry(row)
