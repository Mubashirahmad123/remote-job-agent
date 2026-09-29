"""POST /api/apply/{fp} — Phase 2a fill-only (review mode terminal state).

Gate placement (submit unreachable, not merely unrequested):
  - any `mode` other than "review" -> 400 (never dispatch).
  - dream tier -> 422 via DreamTierForbidden (well-formed but forbidden).
  - unknown fingerprint -> 404.
  - AUTO_APPLY_CONFIRM is never read here or in api.apply — env cannot
    re-enable submit over HTTP. See api/safety.py SUBMIT_ENABLED=False.
"""

from fastapi import APIRouter, Depends, HTTPException

from api import apply as apply_service
from api.deps import require_token
from api.schemas import ApplyRequest

router = APIRouter(tags=["apply"])


@router.post("/api/apply/{job_fingerprint}")
def apply_review(job_fingerprint: str, body: ApplyRequest | None = None, _: None = Depends(require_token)) -> dict:
    raw = body.mode if (body is not None and body.mode is not None) else "review"
    mode = raw.strip().lower()
    if mode != "review":
        raise HTTPException(status_code=400, detail="Only mode='review' is supported (fill-only)")
    try:
        return apply_service.fill_review(job_fingerprint)
    except LookupError:
        raise HTTPException(status_code=404, detail="Job not found")
    except apply_service.DreamTierForbidden as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Apply fill failed: {e}")
