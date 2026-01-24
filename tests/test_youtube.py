"""
Unit tests for YouTube service functions.
"""

import pytest
from app.services.youtube import extract_video_id


class TestExtractVideoId:
    """Tests for extract_video_id function."""
    
    def test_standard_url(self):
        """Test standard YouTube watch URL."""
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        assert extract_video_id(url) == "dQw4w9WgXcQ"
    
    def test_short_url(self):
        """Test youtu.be short URL."""
        url = "https://youtu.be/dQw4w9WgXcQ"
        assert extract_video_id(url) == "dQw4w9WgXcQ"
    
    def test_shorts_url(self):
        """Test YouTube Shorts URL."""
        url = "https://www.youtube.com/shorts/dQw4w9WgXcQ"
        assert extract_video_id(url) == "dQw4w9WgXcQ"
    
    def test_embed_url(self):
        """Test embed URL."""
        url = "https://www.youtube.com/embed/dQw4w9WgXcQ"
        assert extract_video_id(url) == "dQw4w9WgXcQ"
    
    def test_url_with_timestamp(self):
        """Test URL with timestamp parameter."""
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=120s"
        assert extract_video_id(url) == "dQw4w9WgXcQ"
    
    def test_url_with_playlist(self):
        """Test URL with playlist parameter."""
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf"
        assert extract_video_id(url) == "dQw4w9WgXcQ"
    
    def test_raw_video_id(self):
        """Test passing just the video ID."""
        assert extract_video_id("dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    
    def test_invalid_url(self):
        """Test invalid URL returns None."""
        assert extract_video_id("https://google.com") is None
    
    def test_empty_string(self):
        """Test empty string returns None."""
        assert extract_video_id("") is None
    
    def test_short_id(self):
        """Test too-short ID returns None."""
        assert extract_video_id("abc123") is None
    
    def test_mobile_url(self):
        """Test mobile YouTube URL."""
        url = "https://m.youtube.com/watch?v=dQw4w9WgXcQ"
        assert extract_video_id(url) == "dQw4w9WgXcQ"


class TestVideoIdEdgeCases:
    """Edge case tests for video ID extraction."""
    
    def test_id_with_hyphen(self):
        """Test video ID containing hyphens."""
        url = "https://youtu.be/abc-def_123"
        assert extract_video_id(url) == "abc-def_123"
    
    def test_id_with_underscore(self):
        """Test video ID containing underscores."""
        url = "https://youtu.be/abc_def_123"
        assert extract_video_id(url) == "abc_def_123"
    
    def test_url_with_extra_params(self):
        """Test URL with many query parameters."""
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&feature=share&si=abc123"
        assert extract_video_id(url) == "dQw4w9WgXcQ"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
