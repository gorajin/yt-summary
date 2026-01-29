"""
Job management service for async summarization.

Provides in-memory job storage for tracking long-running summarization tasks.
Jobs are ephemeral and don't persist across server restarts (acceptable for Railway).
"""

import uuid
import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any


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


# In-memory job store (simple dict, no persistence needed)
_jobs: Dict[str, Job] = {}

# Lock for thread-safe access
_lock = asyncio.Lock()


async def create_job(user_id: str, youtube_url: str) -> Job:
    """Create a new job and return it."""
    job_id = str(uuid.uuid4())
    job = Job(
        id=job_id,
        user_id=user_id,
        youtube_url=youtube_url
    )
    async with _lock:
        _jobs[job_id] = job
    return job


async def get_job(job_id: str) -> Optional[Job]:
    """Get a job by ID."""
    async with _lock:
        return _jobs.get(job_id)


async def update_job(
    job_id: str,
    status: Optional[JobStatus] = None,
    progress: Optional[int] = None,
    stage: Optional[str] = None,
    result: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None
) -> Optional[Job]:
    """Update a job's state."""
    async with _lock:
        job = _jobs.get(job_id)
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


async def cleanup_old_jobs(max_age_hours: int = 24):
    """Remove jobs older than max_age_hours."""
    cutoff = datetime.utcnow()
    async with _lock:
        to_remove = [
            job_id for job_id, job in _jobs.items()
            if (cutoff - job.created_at).total_seconds() > max_age_hours * 3600
        ]
        for job_id in to_remove:
            del _jobs[job_id]
    return len(to_remove)
