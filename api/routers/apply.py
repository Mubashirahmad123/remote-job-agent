"""POST /api/apply/{fp} — Phase 2a fill-only (review mode terminal state).

Gate placement (submit unreachable, not merely unrequested):
  - any `mode` other than "review" -> 400 (never dispatch).
  - dream tier -> 422 via DreamTierForbidden (well-formed but forbidden).
  - unknown fingerprint -> 404.
  - AUTO_APPLY_CONFIRM is never read here or in api.apply — env cannot
    re-enable submit over HTTP. See api/safety.py SUBMIT_ENABLED=False.
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, JSONResponse

from api import apply as apply_service
from api import safety
from api.deps import action_budget, require_actor, require_apply_token, require_submit_actor, require_token
from api.errors import failure, missing
from api.schemas import ApplyIntentOut, ApplyIntentRequest, ApplyRequest, ApplySubmitOut, ApplySubmitRequest

router = APIRouter(tags=["apply"])


@router.post("/api/apply/{job_fingerprint}")
def apply_review(
    job_fingerprint: str,
    body: ApplyRequest | None = None,
    _: None = Depends(require_token),
    __: None = Depends(action_budget("action")),
    actor: str = Depends(require_actor),
) -> dict:
    raw = body.mode if (body is not None and body.mode is not None) else "review"
    mode = raw.strip().lower()
    if mode != "review":
        raise HTTPException(status_code=400, detail="Only mode='review' is supported (fill-only)")
    try:
        # `actor` is threaded to the artifact row so a review package records
        # who generated it — the service default ("automation") is only correct
        # for the CLI/scheduler, never for a dashboard click.
        return apply_service.fill_review(job_fingerprint, actor=actor)
    except LookupError:
        raise HTTPException(status_code=404, detail="Job not found")
    except apply_service.DreamTierForbidden as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise failure("Apply fill", e)


@router.post("/api/apply/{job_fingerprint}/intent", response_model=ApplyIntentOut)
def apply_intent(
    job_fingerprint: str,
    body: ApplyIntentRequest | None = None,
    _: None = Depends(require_apply_token),
    __: None = Depends(action_budget("action")),
    actor: str = Depends(require_actor),
) -> dict:
    raw_mode = body.mode if body is not None else "review"
    if raw_mode.strip().lower() != "review":
        raise HTTPException(status_code=400, detail="Intent requires mode='review'")
    if not safety.submit_enabled():
        raise HTTPException(status_code=403, detail="Submit is disabled by kill-switch (SUBMIT_ENABLED=False)")
    try:
        return apply_service.create_greenhouse_intent(job_fingerprint, actor=actor)
    except LookupError:
        raise HTTPException(status_code=404, detail="Job not found")
    except apply_service.SubmitUnavailable as error:
        raise HTTPException(status_code=422, detail=str(error))
    except apply_service.SubmitRejected as error:
        if error.status_code == 409:
            return JSONResponse(
                status_code=409,
                content={"detail": error.detail, "retry_after": error.retry_after},
            )
        raise HTTPException(status_code=error.status_code, detail=error.detail)
    except Exception as error:
        raise failure("Apply intent", error)


@router.post("/api/apply/{job_fingerprint}/submit", response_model=ApplySubmitOut)
def apply_submit(
    job_fingerprint: str,
    body: ApplySubmitRequest | None = None,
    _: None = Depends(require_apply_token),
    __: None = Depends(action_budget("action")),
    actor: str = Depends(require_submit_actor),
) -> dict:
    if not safety.submit_enabled():
        raise HTTPException(status_code=403, detail="Submit is disabled by kill-switch (SUBMIT_ENABLED=False)")
    try:
        outcome = apply_service.submit_greenhouse(
            path_fingerprint=job_fingerprint,
            confirm=body.confirm if body is not None else None,
            body_fingerprint=body.job_fingerprint if body is not None else None,
            intent_token=body.intent_token if body is not None else None,
            typed_title=body.typed_title if body is not None else None,
            actor=actor,
        )
        if outcome.get("status") == "dry_run":
            # Returned as a raw response so the full rehearsal report survives
            # the ApplySubmitOut model, which only carries the three fields a
            # real submit reports. 200 with status="dry_run" — never
            # "submitted", so no caller can read a rehearsal as a submission.
            return JSONResponse(status_code=200, content=outcome)
        return outcome
    except LookupError:
        raise HTTPException(status_code=404, detail="Job not found")
    except apply_service.SubmitUnavailable as error:
        raise HTTPException(status_code=422, detail=str(error))
    except apply_service.DreamTierForbidden as error:
        raise HTTPException(status_code=422, detail=str(error))
    except apply_service.SubmitRejected as error:
        if error.status_code == 409:
            return JSONResponse(
                status_code=409,
                content={"detail": error.detail, "retry_after": error.retry_after},
            )
        raise HTTPException(status_code=error.status_code, detail=error.detail)
    except Exception as error:
        raise failure("Greenhouse submit", error)


_MEDIA_BY_SUFFIX = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


@router.get("/api/apply/{job_fingerprint}/screenshot")
def apply_screenshot(job_fingerprint: str, _: None = Depends(require_token)):
    """Serve the stored before-submit screenshot by artifact ID.

    Same auth as POST /api/apply/{fp} (open local-dev, Bearer when
    API_TOKEN is set). Lookup is by fingerprint only — never a raw
    client path. 404 when no fill ran yet (package-only) or the file
    is gone, so the frontend can show an honest empty state.
    """
    try:
        path = apply_service.get_review_screenshot_path(job_fingerprint)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except FileNotFoundError:
        # str(FileNotFoundError) IS the absolute path, so it would tell the
        # caller exactly where artifacts live inside the container.
        raise missing("Screenshot")
    media_type = _MEDIA_BY_SUFFIX.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(str(path), media_type=media_type, filename=path.name)
