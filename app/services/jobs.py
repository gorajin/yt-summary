"""
Job management service for async summarization.

Persists jobs in Supabase for durability across server restarts.
Falls back to in-memory storage if Supabase is unavailable.
"""

import uuid
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class JobStatus(str, Enum):
    """Status of a summarization job."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass
class Job:
    """Represents a summarization job."""
    id: str
    user_id: str
    youtube_url: str
    status: JobStatus = JobStatus.PENDING
    progress: int = 0  # 0-100
    stage: str = "queued"  # Current processing stage description
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)


# In-memory fallback store (used only if Supabase is unavailable)
_fallback_jobs: Dict[str, Job] = {}


def _get_supabase():
    """Lazy import of the shared Supabase client."""
    from ..routers.auth import supabase
    return supabase


def _row_to_job(row: dict) -> Job:
    """Convert a Supabase row to a Job dataclass."""
    status_val = row.get("status", "pending")
    return Job(
        id=row["id"],
        user_id=row["user_id"],
        youtube_url=row["youtube_url"],
        status=JobStatus(status_val),
        progress=row.get("progress", 0),
        stage=row.get("stage", "queued"),
        result=row.get("result"),
        error=row.get("error"),
        created_at=datetime.fromisoformat(row["created_at"].replace("Z", "+00:00")) if isinstance(row.get("created_at"), str) else datetime.utcnow(),
        updated_at=datetime.fromisoformat(row["updated_at"].replace("Z", "+00:00")) if isinstance(row.get("updated_at"), str) else datetime.utcnow(),
    )


async def create_job(user_id: str, youtube_url: str) -> Job:
    """Create a new job and return it."""
    job_id = str(uuid.uuid4())
    
    supabase = _get_supabase()
    if supabase:
        try:
            row = {
                "id": job_id,
                "user_id": user_id,
                "youtube_url": youtube_url,
                "status": JobStatus.PENDING.value,
                "progress": 0,
                "stage": "queued",
            }
            result = supabase.table("jobs").insert(row).execute()
            if result.data:
                logger.info(f"Job {job_id[:8]} created in Supabase")
                return _row_to_job(result.data[0])
        except Exception as e:
            logger.warning(f"Supabase job create failed, using fallback: {e}")
    
    # Fallback to in-memory
    job = Job(id=job_id, user_id=user_id, youtube_url=youtube_url)
    _fallback_jobs[job_id] = job
    logger.info(f"Job {job_id[:8]} created in memory (fallback)")
    return job


async def get_job(job_id: str) -> Optional[Job]:
    """Get a job by ID."""
    supabase = _get_supabase()
    if supabase:
        try:
            result = supabase.table("jobs").select("*").eq("id", job_id).execute()
            if result.data:
                return _row_to_job(result.data[0])
            return None
        except Exception as e:
            logger.warning(f"Supabase job get failed, checking fallback: {e}")
    
    # Fallback
    return _fallback_jobs.get(job_id)


async def update_job(
    job_id: str,
    status: Optional[JobStatus] = None,
    progress: Optional[int] = None,
    stage: Optional[str] = None,
    result: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None
) -> Optional[Job]:
    """Update a job's state."""
    updates = {"updated_at": datetime.utcnow().isoformat()}
    
    if status is not None:
        updates["status"] = status.value
    if progress is not None:
        updates["progress"] = progress
    if stage is not None:
        updates["stage"] = stage
    if result is not None:
        updates["result"] = result
    if error is not None:
        updates["error"] = error
    
    supabase = _get_supabase()
    if supabase:
        try:
            db_result = supabase.table("jobs").update(updates).eq("id", job_id).execute()
            if db_result.data:
                return _row_to_job(db_result.data[0])
        except Exception as e:
            logger.warning(f"Supabase job update failed, using fallback: {e}")
    
    # Fallback to in-memory
    job = _fallback_jobs.get(job_id)
    if not job:
        return None
    
    if status is not None:
        job.status = status
    if progress is not None:
        job.progress = progress
    if stage is not None:
        job.stage = stage
    if result is not None:
        job.result = result
    if error is not None:
        job.error = error
    job.updated_at = datetime.utcnow()
    return job


async def cleanup_old_jobs(max_age_hours: int = 24) -> int:
    """Remove jobs older than max_age_hours."""
    supabase = _get_supabase()
    if supabase:
        try:
            result = supabase.rpc("cleanup_old_jobs", {"max_age_hours": max_age_hours}).execute()
            count = result.data if isinstance(result.data, int) else 0
            logger.info(f"Cleaned up {count} old jobs from Supabase")
            return count
        except Exception as e:
            logger.warning(f"Supabase job cleanup failed: {e}")
    
    # Fallback: clean in-memory store
    cutoff = datetime.utcnow()
    to_remove = [
        job_id for job_id, job in _fallback_jobs.items()
        if (cutoff - job.created_at).total_seconds() > max_age_hours * 3600
    ]
    for job_id in to_remove:
        del _fallback_jobs[job_id]
    return len(to_remove)
