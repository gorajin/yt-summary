"""
Tests for the job management service.

Tests the in-memory fallback path (no Supabase connection required).
"""

import asyncio
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch

from app.services.jobs import (
    Job, JobStatus, create_job, get_job, update_job,
    cleanup_old_jobs, _fallback_jobs
)


@pytest.fixture(autouse=True)
def clear_fallback_store():
    """Clear the in-memory job store before each test."""
    _fallback_jobs.clear()
    yield
    _fallback_jobs.clear()


@pytest.fixture
def disable_supabase():
    """Force fallback to in-memory store by making _get_supabase return None."""
    with patch("app.services.jobs._get_supabase", return_value=None):
        yield


class TestCreateJob:
    """Tests for job creation."""

    @pytest.mark.asyncio
    async def test_create_job_returns_job(self, disable_supabase):
        job = await create_job(user_id="user-1", youtube_url="https://youtu.be/test123")
        assert isinstance(job, Job)
        assert job.user_id == "user-1"
        assert job.youtube_url == "https://youtu.be/test123"
        assert job.status == JobStatus.PENDING
        assert job.progress == 0

    @pytest.mark.asyncio
    async def test_create_job_unique_ids(self, disable_supabase):
        job1 = await create_job(user_id="user-1", youtube_url="url1")
        job2 = await create_job(user_id="user-1", youtube_url="url2")
        assert job1.id != job2.id

    @pytest.mark.asyncio
    async def test_create_job_stored_in_fallback(self, disable_supabase):
        job = await create_job(user_id="user-1", youtube_url="url1")
        assert job.id in _fallback_jobs


class TestGetJob:
    """Tests for job retrieval."""

    @pytest.mark.asyncio
    async def test_get_existing_job(self, disable_supabase):
        job = await create_job(user_id="user-1", youtube_url="url1")
        retrieved = await get_job(job.id)
        assert retrieved is not None
        assert retrieved.id == job.id

    @pytest.mark.asyncio
    async def test_get_nonexistent_job(self, disable_supabase):
        result = await get_job("nonexistent-id")
        assert result is None


class TestUpdateJob:
    """Tests for job updates."""

    @pytest.mark.asyncio
    async def test_update_status(self, disable_supabase):
        job = await create_job(user_id="user-1", youtube_url="url1")
        updated = await update_job(job.id, status=JobStatus.PROCESSING)
        assert updated is not None
        assert updated.status == JobStatus.PROCESSING

    @pytest.mark.asyncio
    async def test_update_progress(self, disable_supabase):
        job = await create_job(user_id="user-1", youtube_url="url1")
        updated = await update_job(job.id, progress=50, stage="Summarizing")
        assert updated.progress == 50
        assert updated.stage == "Summarizing"

    @pytest.mark.asyncio
    async def test_update_with_result(self, disable_supabase):
        job = await create_job(user_id="user-1", youtube_url="url1")
        result_data = {"success": True, "title": "Test Video"}
        updated = await update_job(
            job.id,
            status=JobStatus.COMPLETE,
            progress=100,
            result=result_data
        )
        assert updated.status == JobStatus.COMPLETE
        assert updated.result == result_data

    @pytest.mark.asyncio
    async def test_update_with_error(self, disable_supabase):
        job = await create_job(user_id="user-1", youtube_url="url1")
        updated = await update_job(
            job.id,
            status=JobStatus.FAILED,
            error="Transcript extraction failed"
        )
        assert updated.status == JobStatus.FAILED
        assert updated.error == "Transcript extraction failed"

    @pytest.mark.asyncio
    async def test_update_nonexistent_job(self, disable_supabase):
        result = await update_job("nonexistent", status=JobStatus.COMPLETE)
        assert result is None


class TestCleanupJobs:
    """Tests for job cleanup."""

    @pytest.mark.asyncio
    async def test_cleanup_old_jobs(self, disable_supabase):
        # Create a job and manually age it
        job = await create_job(user_id="user-1", youtube_url="url1")
        _fallback_jobs[job.id].created_at = datetime.utcnow() - timedelta(hours=48)

        removed = await cleanup_old_jobs(max_age_hours=24)
        assert removed == 1
        assert job.id not in _fallback_jobs

    @pytest.mark.asyncio
    async def test_cleanup_keeps_recent_jobs(self, disable_supabase):
        job = await create_job(user_id="user-1", youtube_url="url1")
        removed = await cleanup_old_jobs(max_age_hours=24)
        assert removed == 0
        assert job.id in _fallback_jobs

    @pytest.mark.asyncio
    async def test_cleanup_mixed_ages(self, disable_supabase):
        old_job = await create_job(user_id="user-1", youtube_url="old")
        _fallback_jobs[old_job.id].created_at = datetime.utcnow() - timedelta(hours=48)

        new_job = await create_job(user_id="user-1", youtube_url="new")

        removed = await cleanup_old_jobs(max_age_hours=24)
        assert removed == 1
        assert old_job.id not in _fallback_jobs
        assert new_job.id in _fallback_jobs


class TestJobStatus:
    """Tests for JobStatus enum."""

    def test_status_values(self):
        assert JobStatus.PENDING.value == "pending"
        assert JobStatus.PROCESSING.value == "processing"
        assert JobStatus.COMPLETE.value == "complete"
        assert JobStatus.FAILED.value == "failed"

    def test_status_from_string(self):
        assert JobStatus("pending") == JobStatus.PENDING
        assert JobStatus("complete") == JobStatus.COMPLETE


class TestJobLifecycle:
    """Integration-style tests for the full job lifecycle."""

    @pytest.mark.asyncio
    async def test_full_successful_lifecycle(self, disable_supabase):
        """Test: create → processing → progress updates → complete."""
        job = await create_job(user_id="user-1", youtube_url="https://youtu.be/test123")
        assert job.status == JobStatus.PENDING

        # Start processing
        job = await update_job(job.id, status=JobStatus.PROCESSING, progress=10, stage="Extracting transcript")
        assert job.status == JobStatus.PROCESSING

        # Progress
        job = await update_job(job.id, progress=50, stage="Summarizing with Gemini")
        assert job.progress == 50

        # Complete
        result = {"success": True, "title": "Test Video", "notionUrl": "https://notion.so/page"}
        job = await update_job(job.id, status=JobStatus.COMPLETE, progress=100, result=result)
        assert job.status == JobStatus.COMPLETE
        assert job.result["notionUrl"] == "https://notion.so/page"

    @pytest.mark.asyncio
    async def test_full_failed_lifecycle(self, disable_supabase):
        """Test: create → processing → fail."""
        job = await create_job(user_id="user-1", youtube_url="https://youtu.be/test123")
        
        await update_job(job.id, status=JobStatus.PROCESSING, progress=20, stage="Extracting")
        
        job = await update_job(
            job.id, status=JobStatus.FAILED,
            error="Subtitles are disabled for this video"
        )
        assert job.status == JobStatus.FAILED
        assert "disabled" in job.error


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
