"""
Tests for user-friendly error message conversion.

Ensures that technical error strings from YouTube, Gemini, and network
layers are converted to clear, actionable messages for end users.
"""

import pytest
from app.routers.summarize import get_friendly_error


class TestSubtitleErrors:
    """Tests for subtitle/transcript-related errors."""

    def test_subtitles_disabled(self):
        result = get_friendly_error("TranscriptsDisabled")
        assert "captions" in result.lower() or "subtitles" in result.lower()

    def test_subtitles_are_disabled_long(self):
        result = get_friendly_error("Subtitles are disabled for this video")
        assert "subtitles" in result.lower() or "captions" in result.lower()

    def test_no_subtitles_available(self):
        result = get_friendly_error("No subtitles available for this video")
        assert "subtitles" in result.lower()

    def test_no_transcript_found(self):
        result = get_friendly_error("No transcript found")
        assert len(result) > 0
        assert "try" in result.lower() or "subtitles" in result.lower()


class TestBotDetection:
    """Tests for bot detection / cookie errors."""

    def test_sign_in_bot_check(self):
        result = get_friendly_error("Sign in to confirm you're not a bot")
        assert "try again" in result.lower()

    def test_cookies_error(self):
        result = get_friendly_error("Cookies are required to access this content")
        assert "try again" in result.lower()


class TestURLErrors:
    """Tests for URL validation errors."""

    def test_invalid_url(self):
        result = get_friendly_error("Invalid URL format")
        assert "youtube" in result.lower() or "url" in result.lower()

    def test_could_not_extract_video_id(self):
        result = get_friendly_error("Could not extract video ID from URL")
        assert "check the url" in result.lower() or "recognize" in result.lower()


class TestNetworkErrors:
    """Tests for network/connection errors."""

    def test_timeout(self):
        result = get_friendly_error("Connection timeout after 30s")
        assert "connection" in result.lower()

    def test_connection_refused(self):
        result = get_friendly_error("Connection refused by server")
        assert "connection" in result.lower()


class TestRateLimitErrors:
    """Tests for rate limit errors."""

    def test_rate_limit(self):
        result = get_friendly_error("Rate limit exceeded")
        assert "too many" in result.lower() or "wait" in result.lower()

    def test_too_many_requests(self):
        result = get_friendly_error("Too many requests from this IP")
        assert "wait" in result.lower() or "too many" in result.lower()


class TestPoTokenErrors:
    """Tests for YouTube PoToken enforcement errors (2026+)."""

    def test_potoken_error(self):
        result = get_friendly_error("PoToken required for this video")
        assert "restricted" in result.lower() or "protected" in result.lower()

    def test_authentication_token_error(self):
        result = get_friendly_error("Authentication token required")
        assert "restricted" in result.lower() or "verification" in result.lower()

    def test_multiple_empty_responses(self):
        result = get_friendly_error("Multiple empty responses received")
        assert "protected" in result.lower()


class TestFallbackBehavior:
    """Tests for generic/unknown error handling."""

    def test_long_error_gets_generic_message(self):
        """Errors over 100 chars should get a generic message."""
        long_error = "x" * 150
        result = get_friendly_error(long_error)
        assert result == "Something went wrong. Please try a different video."

    def test_short_unknown_error_passes_through(self):
        """Short unknown errors should pass through as-is."""
        error = "Weird error xyz"
        result = get_friendly_error(error)
        assert result == error

    def test_empty_string(self):
        """Empty error string should pass through."""
        result = get_friendly_error("")
        assert result == ""

    def test_returns_string(self):
        """All results should be strings."""
        assert isinstance(get_friendly_error("any error"), str)
        assert isinstance(get_friendly_error("TranscriptsDisabled"), str)
        assert isinstance(get_friendly_error("x" * 200), str)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
