"""Tests for playlist URL parsing and batch summarization."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient

from app.services.youtube import extract_playlist_id, extract_video_id


# ============ Playlist ID Extraction ============

class TestExtractPlaylistId:
    def test_standard_playlist_url(self):
        url = "https://www.youtube.com/playlist?list=PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf"
        assert extract_playlist_id(url) == "PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf"

    def test_watch_url_with_playlist(self):
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLrAXtmErZgOe12345"
        assert extract_playlist_id(url) == "PLrAXtmErZgOe12345"

    def test_playlist_with_index(self):
        url = "https://www.youtube.com/watch?v=abc&list=PLxyz123&index=5"
        assert extract_playlist_id(url) == "PLxyz123"

    def test_no_playlist(self):
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        assert extract_playlist_id(url) is None

    def test_short_url_no_playlist(self):
        url = "https://youtu.be/dQw4w9WgXcQ"
        assert extract_playlist_id(url) is None

    def test_empty_url(self):
        assert extract_playlist_id("") is None
        assert extract_playlist_id(None) is None

    def test_playlist_id_with_dashes_underscores(self):
        url = "https://youtube.com/playlist?list=PL_abc-def_123"
        assert extract_playlist_id(url) == "PL_abc-def_123"


# ============ Playlist Video Extraction (mocked) ============

class TestGetPlaylistVideoIds:
    @patch("app.services.youtube.yt_dlp.YoutubeDL")
    def test_extracts_video_ids(self, mock_ydl_class):
        from app.services.youtube import get_playlist_video_ids

        mock_ydl = MagicMock()
        mock_ydl_class.return_value.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl_class.return_value.__exit__ = MagicMock(return_value=False)

        mock_ydl.extract_info.return_value = {
            "entries": [
                {"id": "video1abcdef"},
                {"id": "video2ghijkl"},
                {"id": "video3mnopqr"},
            ]
        }

        result = get_playlist_video_ids("https://youtube.com/playlist?list=PLtest")
        assert result == ["video1abcdef", "video2ghijkl", "video3mnopqr"]

    @patch("app.services.youtube.yt_dlp.YoutubeDL")
    def test_empty_playlist_raises(self, mock_ydl_class):
        from app.services.youtube import get_playlist_video_ids

        mock_ydl = MagicMock()
        mock_ydl_class.return_value.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl_class.return_value.__exit__ = MagicMock(return_value=False)

        mock_ydl.extract_info.return_value = {"entries": []}

        with pytest.raises(ValueError, match="empty"):
            get_playlist_video_ids("https://youtube.com/playlist?list=PLempty")

    @patch("app.services.youtube.yt_dlp.YoutubeDL")
    def test_invalid_playlist_raises(self, mock_ydl_class):
        from app.services.youtube import get_playlist_video_ids

        mock_ydl = MagicMock()
        mock_ydl_class.return_value.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl_class.return_value.__exit__ = MagicMock(return_value=False)

        mock_ydl.extract_info.return_value = {"title": "Not a playlist"}

        with pytest.raises(ValueError, match="Could not parse"):
            get_playlist_video_ids("https://youtube.com/watch?v=abc")

    @patch("app.services.youtube.yt_dlp.YoutubeDL")
    def test_skips_none_entries(self, mock_ydl_class):
        from app.services.youtube import get_playlist_video_ids

        mock_ydl = MagicMock()
        mock_ydl_class.return_value.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl_class.return_value.__exit__ = MagicMock(return_value=False)

        mock_ydl.extract_info.return_value = {
            "entries": [
                {"id": "video1abcdef"},
                None,
                {"id": "video2ghijkl"},
                {},  # no id
            ]
        }

        result = get_playlist_video_ids("https://youtube.com/playlist?list=PLtest")
        assert result == ["video1abcdef", "video2ghijkl"]


# ============ Batch Endpoint Gate ============

class TestBatchProGate:
    """Verify the batch endpoint is gated behind Pro subscription."""

    def _make_client(self, user_override: dict):
        from main import app
        from app.routers.auth import get_current_user

        app.dependency_overrides[get_current_user] = lambda: user_override
        client = TestClient(app)
        yield client
        app.dependency_overrides.clear()

    def test_free_user_blocked(self):
        user = {"id": "user-123", "email": "free@test.com", "subscription_tier": "free"}
        for client in self._make_client(user):
            response = client.post("/batch-summarize", json={
                "playlist_url": "https://youtube.com/playlist?list=PLtest",
            })
            assert response.status_code == 403
            assert "Pro" in response.json()["detail"]

    def test_no_urls_rejected(self):
        user = {"id": "user-123", "email": "pro@test.com", "subscription_tier": "pro"}
        for client in self._make_client(user):
            response = client.post("/batch-summarize", json={
                "urls": [],
            })
            assert response.status_code == 400
            assert "No videos" in response.json()["detail"]
