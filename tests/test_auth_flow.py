"""
Tests for authentication flow, rate limiting, usage tracking, and /me profile.

Covers get_current_user, check_rate_limit, increment_usage, and GET /me.
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone
from fastapi.testclient import TestClient


# ============ Fixtures ============


@pytest.fixture
def mock_supabase():
    """Mock Supabase client for auth tests."""
    mock = MagicMock()
    mock_user = MagicMock()
    mock_user.user.id = "auth-test-user-001"
    mock_user.user.email = "authtest@example.com"
    mock.auth.get_user.return_value = mock_user

    # Default: return existing user profile
    mock.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[{
            "id": "auth-test-user-001",
            "email": "authtest@example.com",
            "subscription_tier": "free",
            "summaries_this_month": 3,
            "summaries_reset_at": None,
            "email_digest_enabled": True,
            "email_digest_time": "20:00",
            "timezone": "UTC",
            "notion_access_token": None,
            "notion_database_id": None,
            "stripe_customer_id": None,
        }]
    )
    mock.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
    mock.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[])
    return mock


@pytest.fixture
def auth_app(mock_supabase):
    """Create app with mocked Supabase for auth flow tests."""
    with patch.dict("os.environ", {
        "GEMINI_API_KEY": "test-key",
        "SUPABASE_URL": "https://test.supabase.co",
        "SUPABASE_KEY": "test-key",
        "DEVELOPER_USER_IDS": "dev-user-999",
    }):
        import importlib
        from app import config
        importlib.reload(config)
        from app.routers import auth as auth_module
        auth_module.supabase = mock_supabase
        # Patch developer IDs into the auth module namespace
        auth_module.DEVELOPER_USER_IDS = ["dev-user-999"]
        from main import app
        yield app


@pytest.fixture
def client(auth_app):
    return TestClient(auth_app)


AUTH_HEADER = {"Authorization": "Bearer test-token"}


# ============ get_current_user ============


class TestGetCurrentUser:
    """Tests for the get_current_user auth dependency."""

    def test_no_header_returns_401(self, client):
        """Request without Authorization header should fail."""
        response = client.get("/me")
        assert response.status_code in (401, 403, 422)

    def test_invalid_format_returns_401(self, client):
        """Authorization header without 'Bearer ' prefix should fail."""
        response = client.get("/me", headers={"Authorization": "Token abc"})
        assert response.status_code == 401

    def test_valid_token_returns_user(self, client, mock_supabase):
        """Valid Bearer token should return user profile data."""
        response = client.get("/me", headers=AUTH_HEADER)
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "auth-test-user-001"
        assert data["email"] == "authtest@example.com"

    def test_auto_creates_new_user(self, client, mock_supabase):
        """First-time user should be auto-created with free tier."""
        # Simulate: no existing user row
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[]
        )
        response = client.get("/me", headers=AUTH_HEADER)
        assert response.status_code == 200
        # Verify insert was called to create the user
        mock_supabase.table.return_value.insert.assert_called()
        insert_arg = mock_supabase.table.return_value.insert.call_args[0][0]
        assert insert_arg["subscription_tier"] == "free"

    def test_developer_override_upgrades_to_admin(self, client, mock_supabase):
        """Developer user IDs should be overridden to admin tier."""
        # Set up user as a developer
        mock_user = MagicMock()
        mock_user.user.id = "dev-user-999"
        mock_user.user.email = "dev@example.com"
        mock_supabase.auth.get_user.return_value = mock_user

        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{
                "id": "dev-user-999",
                "email": "dev@example.com",
                "subscription_tier": "free",
                "summaries_this_month": 0,
                "summaries_reset_at": None,
                "email_digest_enabled": True,
                "email_digest_time": "20:00",
                "timezone": "UTC",
                "notion_access_token": None,
                "notion_database_id": None,
                "stripe_customer_id": None,
            }]
        )

        response = client.get("/me", headers=AUTH_HEADER)
        assert response.status_code == 200
        data = response.json()
        assert data["subscription_tier"] == "admin"


# ============ check_rate_limit ============


class TestCheckRateLimit:
    """Tests for the check_rate_limit helper function."""

    def test_pro_gets_unlimited(self):
        """Pro users should get -1 (unlimited)."""
        from app.routers.auth import check_rate_limit
        user = {"subscription_tier": "pro", "summaries_this_month": 999}
        assert check_rate_limit(user) == -1

    def test_lifetime_gets_unlimited(self):
        """Lifetime users should get -1 (unlimited)."""
        from app.routers.auth import check_rate_limit
        user = {"subscription_tier": "lifetime", "summaries_this_month": 0}
        assert check_rate_limit(user) == -1

    def test_free_with_remaining(self):
        """Free user with usage below limit should get remaining count."""
        from app.routers.auth import check_rate_limit
        user = {"subscription_tier": "free", "summaries_this_month": 3}
        remaining = check_rate_limit(user)
        assert remaining == 7  # FREE_TIER_LIMIT (10) - 3

    def test_free_exhausted_returns_429(self):
        """Free user at limit should raise 429."""
        from app.routers.auth import check_rate_limit
        from fastapi import HTTPException
        user = {"subscription_tier": "free", "summaries_this_month": 10}
        with pytest.raises(HTTPException) as exc_info:
            check_rate_limit(user)
        assert exc_info.value.status_code == 429

    def test_monthly_reset_on_new_month(self, mock_supabase):
        """Usage should reset when a new month starts."""
        from app.routers.auth import check_rate_limit
        # Patch the supabase module-level reference used by check_rate_limit
        with patch("app.routers.auth.supabase", mock_supabase):
            user = {
                "id": "reset-user",
                "subscription_tier": "free",
                "summaries_this_month": 10,
                "summaries_reset_at": "2025-01-15T00:00:00Z",  # Old month
            }
            remaining = check_rate_limit(user)
            # Should have been reset → full limit available
            assert remaining == 10  # FREE_TIER_LIMIT


# ============ increment_usage ============


class TestIncrementUsage:
    """Tests for the increment_usage helper function."""

    def test_calls_rpc(self, mock_supabase):
        """increment_usage should call the Supabase RPC."""
        with patch("app.routers.auth.supabase", mock_supabase):
            from app.routers.auth import increment_usage
            increment_usage("test-user-001")
            mock_supabase.rpc.assert_called_once_with(
                "increment_summaries", {"p_user_id": "test-user-001"}
            )


# ============ /me Profile ============


class TestMeProfile:
    """Tests for GET /me endpoint."""

    def test_returns_correct_shape(self, client, mock_supabase):
        """GET /me should return all expected profile fields."""
        response = client.get("/me", headers=AUTH_HEADER)
        assert response.status_code == 200
        data = response.json()

        # Core profile fields from UserProfile model
        assert "id" in data
        assert "email" in data
        assert "notion_connected" in data
        assert "subscription_tier" in data
        assert "summaries_this_month" in data
        assert "summaries_remaining" in data

        # Email digest fields added by the endpoint
        assert "email_digest_enabled" in data
        assert "email_digest_time" in data
        assert "timezone" in data

        # Verify computed field
        assert data["notion_connected"] is False  # No token in fixture
        assert data["summaries_remaining"] == 7  # 10 - 3
