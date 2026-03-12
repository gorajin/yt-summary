"""
Integration tests for authenticated API endpoints.

Tests /summaries (list, search, pagination), /summaries/{id} (detail + auth),
/summaries/{id}/export, /knowledge-map, /subscription/downgrade,
/email/preferences, and /me.
"""

import json
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from fastapi.testclient import TestClient


# ============ Fixtures ============


@pytest.fixture
def mock_supabase():
    """Mock Supabase client for integration tests."""
    mock = MagicMock()
    mock_user = MagicMock()
    mock_user.user.id = "test-user-001"
    mock_user.user.email = "test@example.com"
    mock.auth.get_user.return_value = mock_user

    # Default: return user profile
    mock.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[{
            "id": "test-user-001",
            "email": "test@example.com",
            "subscription_tier": "free",
            "summaries_this_month": 3,
            "email_digest_enabled": True,
            "email_digest_time": "20:00",
            "timezone": "UTC",
            "notion_access_token": "ntn_test",
            "notion_database_id": "db-123",
            "stripe_customer_id": None,
        }]
    )
    # Default: update succeeds
    mock.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
    return mock


@pytest.fixture
def integration_app(mock_supabase):
    """Create app with mocked Supabase for integration tests."""
    with patch.dict("os.environ", {
        "GEMINI_API_KEY": "test-key",
        "SUPABASE_URL": "https://test.supabase.co",
        "SUPABASE_KEY": "test-key",
    }):
        import importlib
        from app import config
        importlib.reload(config)
        from app.routers import auth as auth_module
        auth_module.supabase = mock_supabase
        from app.routers import history as history_module
        history_module.supabase = mock_supabase
        from app.routers import knowledge as knowledge_module
        knowledge_module.supabase = mock_supabase
        from main import app
        yield app


@pytest.fixture
def client(integration_app):
    return TestClient(integration_app)


AUTH_HEADER = {"Authorization": "Bearer test-token"}

SAMPLE_SUMMARY_ROW = {
    "id": "sum-001",
    "youtube_url": "https://youtu.be/dQw4w9WgXcQ",
    "video_id": "dQw4w9WgXcQ",
    "title": "React Server Components",
    "overview": "A deep dive into RSC.",
    "content_type": "tutorial",
    "source_type": "youtube",
    "notion_url": "https://notion.so/page-123",
    "summary_format": "detailed",
    "language": "en",
    "created_at": "2026-01-15T10:00:00Z",
    "summary_json": {
        "title": "React Server Components",
        "contentType": "tutorial",
        "overview": "A deep dive into RSC.",
        "keyInsights": [{"insight": "Reduces bundle size", "timestamp": "3:45", "context": "..."}],
        "mainConcepts": [],
        "detailedNotes": [],
        "notableQuotes": [],
        "resourcesMentioned": [],
        "actionItems": [],
    },
}


# ============ /summaries (list) ============


class TestSummariesList:
    """Tests for GET /summaries endpoint."""

    def test_default_list(self, client, mock_supabase):
        """GET /summaries should return user's summaries."""
        chain = MagicMock()
        chain.execute.return_value = MagicMock(data=[
            {"id": "s1", "youtube_url": "https://youtu.be/a", "title": "Video A", "created_at": "2026-01-01T00:00:00Z"},
            {"id": "s2", "youtube_url": "https://youtu.be/b", "title": "Video B", "created_at": "2026-01-02T00:00:00Z"},
        ])
        mock_supabase.table.return_value.select.return_value.eq.return_value.is_.return_value.order.return_value.range.return_value = chain
        response = client.get("/summaries", headers=AUTH_HEADER)
        assert response.status_code == 200
        assert len(response.json()) == 2

    def test_search_filter(self, client, mock_supabase):
        """GET /summaries?q=React should filter by title."""
        chain = MagicMock()
        chain.execute.return_value = MagicMock(data=[
            {"id": "s1", "youtube_url": "https://youtu.be/a", "title": "React Hooks", "created_at": "2026-01-01T00:00:00Z"},
        ])
        mock_supabase.table.return_value.select.return_value.eq.return_value.is_.return_value.ilike.return_value.order.return_value.range.return_value = chain
        response = client.get("/summaries?q=React", headers=AUTH_HEADER)
        assert response.status_code == 200
        assert len(response.json()) == 1

    def test_empty_results(self, client, mock_supabase):
        """GET /summaries should return empty list when no summaries exist."""
        chain = MagicMock()
        chain.execute.return_value = MagicMock(data=[])
        mock_supabase.table.return_value.select.return_value.eq.return_value.is_.return_value.order.return_value.range.return_value = chain
        response = client.get("/summaries", headers=AUTH_HEADER)
        assert response.status_code == 200
        assert response.json() == []

    def test_pagination(self, client, mock_supabase):
        """GET /summaries?limit=1&offset=1 should paginate."""
        chain = MagicMock()
        chain.execute.return_value = MagicMock(data=[
            {"id": "s2", "youtube_url": "https://youtu.be/b", "title": "Second", "created_at": "2026-01-02T00:00:00Z"},
        ])
        mock_supabase.table.return_value.select.return_value.eq.return_value.is_.return_value.order.return_value.range.return_value = chain
        response = client.get("/summaries?limit=1&offset=1", headers=AUTH_HEADER)
        assert response.status_code == 200
        assert len(response.json()) == 1


# ============ /summaries/{id} (detail) ============


class TestSummaryDetail:
    """Tests for GET /summaries/{id} endpoint."""

    def test_valid_retrieval(self, client, mock_supabase):
        """Should return full summary detail for own summary."""
        chain = MagicMock()
        chain.execute.return_value = MagicMock(data=[SAMPLE_SUMMARY_ROW])
        mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.is_.return_value = chain
        response = client.get("/summaries/sum-001", headers=AUTH_HEADER)
        assert response.status_code == 200
        assert response.json()["id"] == "sum-001"

    def test_missing_summary_returns_404(self, client, mock_supabase):
        """Should return 404 for non-existent summary."""
        chain = MagicMock()
        chain.execute.return_value = MagicMock(data=[])
        mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.is_.return_value = chain
        response = client.get("/summaries/nonexistent", headers=AUTH_HEADER)
        assert response.status_code == 404

    def test_requires_authentication(self, client):
        """Should require auth header."""
        response = client.get("/summaries/sum-001")
        assert response.status_code in (401, 403, 422)


# ============ /summaries/{id}/export ============


class TestSummaryExport:
    """Tests for GET /summaries/{id}/export endpoint."""

    def _mock_summary_chain(self, mock_supabase, data):
        chain = MagicMock()
        chain.execute.return_value = MagicMock(data=data)
        mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.is_.return_value = chain

    def test_markdown_export(self, client, mock_supabase):
        """Should export summary as markdown."""
        self._mock_summary_chain(mock_supabase, [SAMPLE_SUMMARY_ROW])
        response = client.get("/summaries/sum-001/export?format=markdown", headers=AUTH_HEADER)
        assert response.status_code == 200
        assert "text/markdown" in response.headers.get("content-type", "") or \
               "attachment" in response.headers.get("content-disposition", "")

    def test_html_export(self, client, mock_supabase):
        """Should export summary as HTML."""
        self._mock_summary_chain(mock_supabase, [SAMPLE_SUMMARY_ROW])
        response = client.get("/summaries/sum-001/export?format=html", headers=AUTH_HEADER)
        assert response.status_code == 200

    def test_text_export(self, client, mock_supabase):
        """Should export summary as plain text."""
        self._mock_summary_chain(mock_supabase, [SAMPLE_SUMMARY_ROW])
        response = client.get("/summaries/sum-001/export?format=text", headers=AUTH_HEADER)
        assert response.status_code == 200

    def test_export_missing_summary_returns_404(self, client, mock_supabase):
        """Should return 404 for non-existent summary."""
        self._mock_summary_chain(mock_supabase, [])
        response = client.get("/summaries/nonexistent/export?format=markdown", headers=AUTH_HEADER)
        assert response.status_code == 404


# ============ /knowledge-map ============


class TestKnowledgeMap:
    """Tests for knowledge map endpoints."""

    def test_get_map_no_map_exists(self, client, mock_supabase):
        """GET /knowledge-map should indicate no map when none exists."""
        with patch("app.routers.knowledge.get_knowledge_map", new_callable=AsyncMock, return_value=None):
            response = client.get("/knowledge-map", headers=AUTH_HEADER)
        assert response.status_code == 200
        data = response.json()
        assert data["knowledgeMap"] is None
        assert data["isStale"] is True

    def test_get_map_with_existing_map(self, client, mock_supabase):
        """GET /knowledge-map should return map data when it exists."""
        mock_map = {
            "map": {"topics": [], "connections": []},
            "version": 1,
            "notionUrl": None,
            "updatedAt": "2026-01-01T00:00:00Z",
            "summaryCount": 5,
            "currentSummaryCount": 5,
            "isStale": False,
        }
        with patch("app.routers.knowledge.get_knowledge_map", new_callable=AsyncMock, return_value=mock_map):
            response = client.get("/knowledge-map", headers=AUTH_HEADER)
        assert response.status_code == 200
        assert response.json()["isStale"] is False

    def test_build_map_returns_job_id(self, client, mock_supabase):
        """POST /knowledge-map/build should return a job ID."""
        mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[])
        # track_background_task is imported inside the function from main module
        with patch("main.track_background_task"):
            response = client.post("/knowledge-map/build", headers=AUTH_HEADER)
        assert response.status_code == 200
        assert "jobId" in response.json()


# ============ /subscription/downgrade ============


class TestSubscriptionDowngrade:
    """Tests for POST /subscription/downgrade endpoint."""

    def _set_user_tier(self, mock_supabase, tier):
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{
                "id": "test-user-001",
                "email": "test@example.com",
                "subscription_tier": tier,
                "summaries_this_month": 0,
            }]
        )

    def test_pro_to_free(self, client, mock_supabase):
        """Pro user should be downgraded to free."""
        self._set_user_tier(mock_supabase, "pro")
        response = client.post("/subscription/downgrade", headers=AUTH_HEADER)
        assert response.status_code == 200
        assert response.json()["subscription_tier"] == "free"

    def test_already_free(self, client, mock_supabase):
        """Already-free user should get success with no change."""
        self._set_user_tier(mock_supabase, "free")
        response = client.post("/subscription/downgrade", headers=AUTH_HEADER)
        assert response.status_code == 200
        assert response.json()["subscription_tier"] == "free"
        assert "Already on free" in response.json()["message"]

    def test_lifetime_stays_lifetime(self, client, mock_supabase):
        """Lifetime users should not be downgraded."""
        self._set_user_tier(mock_supabase, "lifetime")
        response = client.post("/subscription/downgrade", headers=AUTH_HEADER)
        assert response.status_code == 200
        assert response.json()["subscription_tier"] == "lifetime"

    def test_admin_stays_admin(self, client, mock_supabase):
        """Admin users should not be downgraded."""
        self._set_user_tier(mock_supabase, "admin")
        response = client.post("/subscription/downgrade", headers=AUTH_HEADER)
        assert response.status_code == 200
        assert response.json()["subscription_tier"] == "admin"


# ============ /email/preferences ============


class TestEmailPreferences:
    """Tests for email preferences endpoints."""

    def test_get_defaults(self, client, mock_supabase):
        """GET /email/preferences should return current settings."""
        response = client.get("/email/preferences", headers=AUTH_HEADER)
        assert response.status_code == 200
        data = response.json()
        assert "email_digest_enabled" in data
        assert "email_digest_time" in data
        assert "timezone" in data

    def test_put_valid_time(self, client, mock_supabase):
        """PUT /email/preferences with valid time should succeed."""
        response = client.put(
            "/email/preferences",
            json={"email_digest_time": "09:30"},
            headers=AUTH_HEADER,
        )
        assert response.status_code == 200
        assert response.json()["success"] is True

    def test_put_invalid_time_format(self, client, mock_supabase):
        """PUT /email/preferences with invalid time should fail."""
        response = client.put(
            "/email/preferences",
            json={"email_digest_time": "25:00"},
            headers=AUTH_HEADER,
        )
        assert response.status_code == 400

    def test_put_partial_update(self, client, mock_supabase):
        """PUT /email/preferences with only one field should succeed."""
        response = client.put(
            "/email/preferences",
            json={"email_digest_enabled": False},
            headers=AUTH_HEADER,
        )
        assert response.status_code == 200
