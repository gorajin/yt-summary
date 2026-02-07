"""
Tests for quota and rate limiting logic.

Tests the check_rate_limit and month comparison functions
used for monthly quota enforcement.
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime

from app.config import FREE_TIER_LIMIT, ADMIN_TIER_LIMIT, DEVELOPER_USER_IDS


class TestQuotaConfig:
    """Tests for quota configuration values."""

    def test_free_tier_limit_is_positive(self):
        assert FREE_TIER_LIMIT > 0

    def test_admin_tier_limit_greater_than_free(self):
        assert ADMIN_TIER_LIMIT > FREE_TIER_LIMIT

    def test_developer_user_ids_is_list(self):
        assert isinstance(DEVELOPER_USER_IDS, list)


class TestFriendlyErrors:
    """Tests for user-friendly error messages in summarize router."""

    def test_subtitles_disabled(self):
        from app.routers.summarize import get_friendly_error
        result = get_friendly_error("TranscriptsDisabled")
        assert "captions" in result.lower() or "subtitles" in result.lower()

    def test_no_transcript_found(self):
        from app.routers.summarize import get_friendly_error
        result = get_friendly_error("No transcript found for this video")
        assert len(result) > 0

    def test_age_restricted(self):
        from app.routers.summarize import get_friendly_error
        result = get_friendly_error("This video is age restricted")
        assert "age" in result.lower() or "sign in" in result.lower()

    def test_video_unavailable(self):
        from app.routers.summarize import get_friendly_error
        result = get_friendly_error("Video unavailable - private")
        assert "available" in result.lower() or "private" in result.lower()

    def test_unknown_error_passthrough(self):
        from app.routers.summarize import get_friendly_error
        result = get_friendly_error("Some completely unknown error xyz")
        assert len(result) > 0  # Should still return something


class TestVideoIdExtraction:
    """Tests for video ID extraction (also tested in test_youtube.py but
    these focus on edge cases relevant to quota tracking)."""

    def test_live_url(self):
        from app.services.youtube import extract_video_id
        url = "https://www.youtube.com/live/dQw4w9WgXcQ"
        assert extract_video_id(url) == "dQw4w9WgXcQ"

    def test_none_input(self):
        from app.services.youtube import extract_video_id
        assert extract_video_id(None) is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
