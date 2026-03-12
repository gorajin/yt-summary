"""
Edge case tests for input validation, Unicode handling, pagination boundaries,
empty request bodies, and missing required fields.
"""

import json
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient


# ============ Fixtures ============


@pytest.fixture
def mock_supabase():
    """Mock Supabase client for edge case tests."""
    mock = MagicMock()
    mock_user = MagicMock()
    mock_user.user.id = "edge-user-001"
    mock_user.user.email = "edge@example.com"
    mock.auth.get_user.return_value = mock_user

    mock.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[{
            "id": "edge-user-001",
            "email": "edge@example.com",
            "subscription_tier": "free",
            "summaries_this_month": 0,
            "email_digest_enabled": True,
            "email_digest_time": "20:00",
            "timezone": "UTC",
            "notion_access_token": None,
            "notion_database_id": None,
            "stripe_customer_id": None,
        }]
    )
    mock.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
    return mock


@pytest.fixture
def edge_app(mock_supabase):
    """Create app with mocked Supabase for edge case tests."""
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
def client(edge_app):
    return TestClient(edge_app)


AUTH_HEADER = {"Authorization": "Bearer test-token"}


# ============ Long Inputs ============


class TestLongInputs:
    """Ensure very long inputs are handled gracefully."""

    def test_extremely_long_url_handled(self, client):
        """A URL over 2000 chars should be accepted as async job or rejected, not crash."""
        long_url = "https://www.youtube.com/watch?v=" + "a" * 2500
        response = client.post(
            "/summarize",
            json={"url": long_url},
            headers=AUTH_HEADER,
        )
        # The endpoint creates an async job (202) or rejects (400/422), either is fine.
        # The important thing is no 500 server error.
        assert response.status_code in (200, 202, 400, 422)

    def test_long_search_query_does_not_crash(self, client, mock_supabase):
        """A very long search query should not cause a server error."""
        chain = MagicMock()
        chain.execute.return_value = MagicMock(data=[])
        mock_supabase.table.return_value.select.return_value.eq.return_value.is_.return_value.ilike.return_value.order.return_value.range.return_value = chain
        long_query = "React " * 500  # ~3000 chars
        response = client.get(
            f"/summaries?q={long_query}",
            headers=AUTH_HEADER,
        )
        # Should return 200 with empty results (or at worst 422), not 500
        assert response.status_code in (200, 422)


# ============ Unicode Handling ============


class TestUnicodeHandling:
    """Ensure Unicode inputs are processed without crashing."""

    def test_unicode_search_query(self, client, mock_supabase):
        """Unicode characters in search should not crash the server."""
        chain = MagicMock()
        chain.execute.return_value = MagicMock(data=[])
        mock_supabase.table.return_value.select.return_value.eq.return_value.is_.return_value.ilike.return_value.order.return_value.range.return_value = chain
        response = client.get(
            "/summaries?q=リアクト入門",
            headers=AUTH_HEADER,
        )
        assert response.status_code in (200, 422)

    def test_unicode_in_timezone_field(self, client, mock_supabase):
        """Unicode timezone string should be accepted or rejected gracefully."""
        response = client.put(
            "/email/preferences",
            json={"timezone": "アジア/東京"},
            headers=AUTH_HEADER,
        )
        # The API stores timezone as-is (no validation of timezone names)
        # so this should succeed or fail gracefully
        assert response.status_code in (200, 400, 422)


# ============ Empty Request Bodies ============


class TestEmptyBodies:
    """Endpoints requiring a body should reject empty/missing bodies."""

    def test_summarize_empty_body(self, client):
        """POST /summarize with empty body should return 422."""
        response = client.post(
            "/summarize",
            content=b"{}",
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer test-token",
            },
        )
        # Missing required `url` field
        assert response.status_code == 422

    def test_ingest_empty_body(self, client):
        """POST /ingest with empty body should return 422."""
        response = client.post(
            "/ingest",
            content=b"{}",
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer test-token",
            },
        )
        # Missing required `url` field
        assert response.status_code == 422

    def test_email_preferences_empty_body(self, client, mock_supabase):
        """PUT /email/preferences with empty JSON should succeed (all optional fields)."""
        response = client.put(
            "/email/preferences",
            json={},
            headers=AUTH_HEADER,
        )
        # All fields are Optional, so empty body is valid but does nothing
        assert response.status_code == 200


# ============ Pagination Boundaries ============


class TestPaginationBoundaries:
    """Test unusual pagination parameters."""

    def test_offset_beyond_data(self, client, mock_supabase):
        """Offset way beyond data should return empty list."""
        chain = MagicMock()
        chain.execute.return_value = MagicMock(data=[])
        mock_supabase.table.return_value.select.return_value.eq.return_value.is_.return_value.order.return_value.range.return_value = chain
        response = client.get(
            "/summaries?offset=999999",
            headers=AUTH_HEADER,
        )
        assert response.status_code == 200
        assert response.json() == []

    def test_limit_zero_handled(self, client, mock_supabase):
        """limit=0 should return empty or be rejected."""
        chain = MagicMock()
        chain.execute.return_value = MagicMock(data=[])
        mock_supabase.table.return_value.select.return_value.eq.return_value.is_.return_value.order.return_value.range.return_value = chain
        response = client.get(
            "/summaries?limit=0",
            headers=AUTH_HEADER,
        )
        # Either returns empty list (200) or rejects (422)
        assert response.status_code in (200, 422)

    def test_negative_offset_handled(self, client, mock_supabase):
        """Negative offset should be rejected or clamped."""
        chain = MagicMock()
        chain.execute.return_value = MagicMock(data=[])
        mock_supabase.table.return_value.select.return_value.eq.return_value.is_.return_value.order.return_value.range.return_value = chain
        response = client.get(
            "/summaries?offset=-1",
            headers=AUTH_HEADER,
        )
        assert response.status_code in (200, 422)


# ============ Missing Required Fields ============


class TestMissingRequiredFields:
    """Endpoints should reject requests missing required fields."""

    def test_summarize_without_url(self, client):
        """POST /summarize without url field should return 422."""
        response = client.post(
            "/summarize",
            json={"transcript": "some text but no url"},
            headers=AUTH_HEADER,
        )
        assert response.status_code == 422

    def test_stripe_checkout_without_price_id(self, client, mock_supabase):
        """POST /subscription/stripe-checkout without price_id should return 422."""
        # Need Stripe configured for this endpoint to even validate the body
        with patch.dict("os.environ", {
            "STRIPE_SECRET_KEY": "sk_test_xxx",
            "WEB_APP_URL": "https://app.watchlater.dev",
        }):
            from app.routers import auth as auth_module
            auth_module.STRIPE_SECRET_KEY = "sk_test_xxx"
            auth_module.WEB_APP_URL = "https://app.watchlater.dev"

            response = client.post(
                "/subscription/stripe-checkout",
                json={},
                headers=AUTH_HEADER,
            )
        assert response.status_code == 422
