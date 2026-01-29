"""
Job status router.

Provides endpoint for polling job status during async summarization.
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, Dict, Any

from ..services.jobs import get_job, JobStatus
from .auth import get_current_user


router = APIRouter(tags=["status"])


class JobStatusResponse(BaseModel):
    """Response model for job status."""
    job_id: str
    status: str  # pending, processing, complete, failed
    progress: int  # 0-100
    stage: str  # Human-readable current stage
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


@router.get("/status/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str, user: dict = Depends(get_current_user)):
    """Get the status of a summarization job.
    
    Poll this endpoint every 2-3 seconds to track progress.
    When status is "complete", the result field contains the summary data.
    """
    job = await get_job(job_id)
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Security: only allow users to see their own jobs
    if job.user_id != user["id"]:
        raise HTTPException(status_code=403, detail="Access denied")
    
    return JobStatusResponse(
        job_id=job.id,
        status=job.status.value,
        progress=job.progress,
        stage=job.stage,
        result=job.result,
        error=job.error
    )
