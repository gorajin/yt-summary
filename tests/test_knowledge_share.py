"""Tests for knowledge map sharing and topic deep-dive endpoints."""

import pytest
from unittest.mock import patch, MagicMock


# ============ Share Token Generation ============


class TestShareMapEndpoint:
    """Test POST /knowledge-map/share."""

    @patch("app.routers.knowledge.supabase")
    def test_share_creates_token(self, mock_supabase):
        from fastapi.testclient import TestClient
        from main import app
        from app.routers.auth import get_current_user

        user = {"id": "user-123", "email": "test@test.com", "subscription_tier": "pro"}
        app.dependency_overrides[get_current_user] = lambda: user

        # Map exists but has no share_token
        mock_result = MagicMock()
        mock_result.data = [{"id": "map-1", "share_token": None, "map_json": {"topics": []}}]
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_result

        # Update returns success
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

        client = TestClient(app)
        response = client.post("/knowledge-map/share")

        assert response.status_code == 200
        data = response.json()
        assert "shareToken" in data
        assert "shareUrl" in data
        assert len(data["shareToken"]) > 10  # URL-safe token

        app.dependency_overrides.clear()

    @patch("app.routers.knowledge.supabase")
    def test_share_returns_existing_token(self, mock_supabase):
        from fastapi.testclient import TestClient
        from main import app
        from app.routers.auth import get_current_user

        user = {"id": "user-123", "email": "test@test.com", "subscription_tier": "pro"}
        app.dependency_overrides[get_current_user] = lambda: user

        # Map exists and already has a share_token
        mock_result = MagicMock()
        mock_result.data = [{"id": "map-1", "share_token": "existing_token_abc", "map_json": {}}]
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_result

        client = TestClient(app)
        response = client.post("/knowledge-map/share")

        assert response.status_code == 200
        assert response.json()["shareToken"] == "existing_token_abc"

        app.dependency_overrides.clear()

    @patch("app.routers.knowledge.supabase")
    def test_share_no_map_404(self, mock_supabase):
        from fastapi.testclient import TestClient
        from main import app
        from app.routers.auth import get_current_user

        user = {"id": "user-123", "email": "test@test.com", "subscription_tier": "free"}
        app.dependency_overrides[get_current_user] = lambda: user

        mock_result = MagicMock()
        mock_result.data = []
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_result

        client = TestClient(app)
        response = client.post("/knowledge-map/share")

        assert response.status_code == 404

        app.dependency_overrides.clear()


# ============ Public Shared Map ============


class TestGetSharedMap:
    """Test GET /knowledge-map/shared/{share_token}."""

    @patch("app.routers.knowledge.supabase")
    def test_valid_token_returns_map(self, mock_supabase):
        from fastapi.testclient import TestClient
        from main import app

        mock_result = MagicMock()
        mock_result.data = [{
            "map_json": {"topics": [{"name": "AI"}], "connections": []},
            "updated_at": "2026-03-11T00:00:00Z",
        }]
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_result

        client = TestClient(app)
        response = client.get("/knowledge-map/shared/valid_token_abc")

        assert response.status_code == 200
        data = response.json()
        assert data["isShared"] is True
        assert "knowledgeMap" in data

    @patch("app.routers.knowledge.supabase")
    def test_invalid_token_404(self, mock_supabase):
        from fastapi.testclient import TestClient
        from main import app

        mock_result = MagicMock()
        mock_result.data = []
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_result

        client = TestClient(app)
        response = client.get("/knowledge-map/shared/nonexistent_token")

        assert response.status_code == 404


# ============ Topic Deep-Dive ============


class TestGetTopicSummaries:
    """Test GET /knowledge-map/topic/{topic_name}."""

    @patch("app.routers.knowledge.supabase")
    def test_returns_summaries_for_topic(self, mock_supabase):
        from fastapi.testclient import TestClient
        from main import app
        from app.routers.auth import get_current_user

        user = {"id": "user-123", "email": "test@test.com", "subscription_tier": "pro"}
        app.dependency_overrides[get_current_user] = lambda: user

        # Knowledge map with a topic
        map_result = MagicMock()
        map_result.data = [{
            "map_json": {
                "topics": [{
                    "name": "Machine Learning",
                    "description": "ML concepts",
                    "videoIds": ["abc123DEF45", "xyz789GHI01"],
                }],
                "connections": [],
            }
        }]

        # Summaries matching the video IDs
        summaries_result = MagicMock()
        summaries_result.data = [
            {"id": "s1", "video_id": "abc123DEF45", "title": "ML Intro"},
            {"id": "s2", "video_id": "xyz789GHI01", "title": "Deep Learning"},
        ]

        # Mock chained Supabase calls
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = map_result
        mock_supabase.table.return_value.select.return_value.eq.return_value.is_.return_value.in_.return_value.order.return_value.execute.return_value = summaries_result

        client = TestClient(app)
        response = client.get("/knowledge-map/topic/Machine Learning")

        assert response.status_code == 200
        data = response.json()
        assert data["topic"]["name"] == "Machine Learning"
        assert len(data["summaries"]) == 2

        app.dependency_overrides.clear()

    @patch("app.routers.knowledge.supabase")
    def test_topic_not_found_404(self, mock_supabase):
        from fastapi.testclient import TestClient
        from main import app
        from app.routers.auth import get_current_user

        user = {"id": "user-123", "email": "test@test.com", "subscription_tier": "free"}
        app.dependency_overrides[get_current_user] = lambda: user

        map_result = MagicMock()
        map_result.data = [{
            "map_json": {
                "topics": [{"name": "Physics", "videoIds": []}],
                "connections": [],
            }
        }]
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = map_result

        client = TestClient(app)
        response = client.get("/knowledge-map/topic/Nonexistent Topic")

        assert response.status_code == 404

        app.dependency_overrides.clear()
