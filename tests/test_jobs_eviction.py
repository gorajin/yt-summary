"""
Tests for job store eviction and concurrency.

Verifies that the in-memory fallback store respects its max-size cap,
evicts oldest entries first, and handles concurrent access safely.
"""

import asyncio
import pytest
from unittest.mock import patch

from app.services.jobs import (
    Job, JobStatus, create_job, get_job, update_job,
    _fallback_jobs, _FALLBACK_MAX_SIZE, _fallback_lock,
)


@pytest.fixture(autouse=True)
def clear_fallback_store():
    """Clear the in-memory job store before and after each test."""
    _fallback_jobs.clear()
    yield
    _fallback_jobs.clear()


@pytest.fixture
def disable_supabase():
    """Force fallback to in-memory store."""
    with patch("app.services.jobs._get_supabase", return_value=None):
        yield


# ============ Eviction Tests ============

class TestEviction:
    """Tests for max-size eviction in the fallback store."""

    @pytest.mark.asyncio
    async def test_eviction_cap_value(self):
        """Sanity: the cap is a sensible positive number."""
        assert _FALLBACK_MAX_SIZE > 0
        assert _FALLBACK_MAX_SIZE <= 10_000

    @pytest.mark.asyncio
    async def test_store_grows_up_to_max(self, disable_supabase):
        """Store should hold up to _FALLBACK_MAX_SIZE jobs without evicting."""
        with patch("app.services.jobs._FALLBACK_MAX_SIZE", 5):
            for i in range(5):
                await create_job(user_id=f"u{i}", youtube_url=f"url{i}")
            assert len(_fallback_jobs) == 5

    @pytest.mark.asyncio
    async def test_eviction_when_exceeding_max(self, disable_supabase):
        """Oldest job should be evicted when cap is exceeded."""
        with patch("app.services.jobs._FALLBACK_MAX_SIZE", 3):
            job1 = await create_job(user_id="u1", youtube_url="url1")
            job2 = await create_job(user_id="u2", youtube_url="url2")
            job3 = await create_job(user_id="u3", youtube_url="url3")
            assert len(_fallback_jobs) == 3

            # Adding a 4th should evict job1
            job4 = await create_job(user_id="u4", youtube_url="url4")
            assert len(_fallback_jobs) == 3
            assert job1.id not in _fallback_jobs
            assert job4.id in _fallback_jobs

    @pytest.mark.asyncio
    async def test_eviction_order_is_oldest_first(self, disable_supabase):
        """Jobs should be evicted in creation order (FIFO)."""
        with patch("app.services.jobs._FALLBACK_MAX_SIZE", 3):
            ids = []
            for i in range(5):
                job = await create_job(user_id=f"u{i}", youtube_url=f"url{i}")
                ids.append(job.id)

            # Jobs 0 and 1 should have been evicted; 2, 3, 4 remain
            assert len(_fallback_jobs) == 3
            assert ids[0] not in _fallback_jobs
            assert ids[1] not in _fallback_jobs
            assert ids[2] in _fallback_jobs
            assert ids[3] in _fallback_jobs
            assert ids[4] in _fallback_jobs


# ============ Concurrency Tests ============

class TestConcurrency:
    """Tests for concurrent access to the fallback store."""

    @pytest.mark.asyncio
    async def test_concurrent_creates(self, disable_supabase):
        """Multiple concurrent create_job calls should not lose data."""
        with patch("app.services.jobs._FALLBACK_MAX_SIZE", 100):
            tasks = [
                create_job(user_id=f"u{i}", youtube_url=f"url{i}")
                for i in range(50)
            ]
            jobs = await asyncio.gather(*tasks)

            assert len(jobs) == 50
            assert len(_fallback_jobs) == 50
            # All IDs should be unique
            ids = {j.id for j in jobs}
            assert len(ids) == 50

    @pytest.mark.asyncio
    async def test_concurrent_creates_with_eviction(self, disable_supabase):
        """Concurrent creates beyond cap should still maintain store size."""
        with patch("app.services.jobs._FALLBACK_MAX_SIZE", 10):
            tasks = [
                create_job(user_id=f"u{i}", youtube_url=f"url{i}")
                for i in range(25)
            ]
            await asyncio.gather(*tasks)

            # Should be capped at 10
            assert len(_fallback_jobs) <= 10

    @pytest.mark.asyncio
    async def test_concurrent_create_and_read(self, disable_supabase):
        """Concurrent creates and reads should not raise exceptions."""
        job = await create_job(user_id="u0", youtube_url="url0")

        async def create_some():
            for i in range(10):
                await create_job(user_id=f"u{i+1}", youtube_url=f"url{i+1}")

        async def read_some():
            for _ in range(10):
                await get_job(job.id)

        # Both operations should complete without errors
        await asyncio.gather(create_some(), read_some())

    @pytest.mark.asyncio
    async def test_concurrent_updates(self, disable_supabase):
        """Concurrent updates to the same job should not corrupt data."""
        job = await create_job(user_id="u1", youtube_url="url1")

        tasks = [
            update_job(job.id, progress=i * 10, stage=f"Stage {i}")
            for i in range(10)
        ]
        results = await asyncio.gather(*tasks)

        # All updates should succeed (no None returns)
        assert all(r is not None for r in results)

        # Final state should be one of the update values
        final = await get_job(job.id)
        assert final.progress in range(0, 100, 10)


# ============ Lock Tests ============

class TestFallbackLock:
    """Tests verifying the asyncio.Lock exists and is usable."""

    def test_lock_exists(self):
        assert _fallback_lock is not None
        assert isinstance(_fallback_lock, asyncio.Lock)

    @pytest.mark.asyncio
    async def test_lock_is_usable(self):
        """Lock should be acquirable and releasable."""
        async with _fallback_lock:
            pass  # Just verify we can acquire and release


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
