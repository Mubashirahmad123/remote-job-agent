"""POST /api/resume/{fp} + /api/cover-letter/{fp} and their downloads."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse

from api import materials
from api.deps import require_token

router = APIRouter(tags=["materials"])


@router.post("/api/resume/{job_fingerprint}")
def create_resume(job_fingerprint: str, _: None = Depends(require_token)) -> dict:
    try:
        return materials.generate_resume(job_fingerprint)
    except LookupError:
        raise HTTPException(status_code=404, detail="Job not found")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Resume generation failed: {e}")


@router.get("/api/resume/{job_fingerprint}/download")
def download_resume(job_fingerprint: str, _: None = Depends(require_token)):
    path = materials.get_resume_pdf(job_fingerprint)
    if path is None:
        raise HTTPException(
            status_code=404, detail="No resume generated for this job yet"
        )
    return FileResponse(
        path, media_type="application/pdf", filename=path.name,
        headers={"Content-Disposition": f'attachment; filename="{path.name}"'},
    )


@router.post("/api/cover-letter/{job_fingerprint}")
def create_cover_letter(
    job_fingerprint: str, _: None = Depends(require_token)
) -> dict:
    try:
        return materials.generate_cover_letter(job_fingerprint)
    except LookupError:
        raise HTTPException(status_code=404, detail="Job not found")
    except Exception as e:
        raise HTTPException(
            status_code=502, detail=f"Cover letter generation failed: {e}"
        )


@router.get("/api/cover-letter/{job_fingerprint}/download")
def download_cover_letter(job_fingerprint: str, _: None = Depends(require_token)):
    path = materials.get_cover_letter_file(job_fingerprint)
    if path is None:
        raise HTTPException(
            status_code=404, detail="No cover letter generated for this job yet"
        )
    text = path.read_text(encoding="utf-8")
    return PlainTextResponse(
        text,
        headers={"Content-Disposition": f'attachment; filename="{path.name}"'},
    )
