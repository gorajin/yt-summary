"""
Security tests for the WatchLater API.

Tests cross-user data leakage, SSRF protection, OAuth state validation,
JWT handling, security header enforcement, and request body limits.
"""

import json
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from fastapi.testclient import TestClient


# ============ Fixtures ============


@pytest.fixture
def mock_supabase():
    """Mock Supabase client for security tests."""
    mock = MagicMock()
    mock_user = MagicMock()
    mock_user.user.id = "user-a-111"
    mock_user.user.email = "usera@example.com"
    mock.auth.get_user.return_value = mock_user

    # Default: return user profile for user-a
    mock.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[{
            "id": "user-a-111",
            "email": "usera@example.com",
            "subscription_tier": "free",
            "summaries_this_month": 0,
            "stripe_customer_id": None,
        }]
    )
    return mock


@pytest.fixture
def security_app(mock_supabase):
    """Create app with mocked Supabase for security tests."""
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
def client(security_app):
    return TestClient(security_app)


# ============ Cross-User Data Isolation ============


class TestCrossUserIsolation:
    """User A must not be able to access User B's data."""

    def test_summary_detail_rejects_other_users_summary(self, client, mock_supabase):
        """GET /summaries/{id} should 404 when summary belongs to another user."""
        # Simulate Supabase returning empty because .eq("user_id", "user-a-111")
        # filters out user-b's row
        chain = MagicMock()
        chain.execute.return_value = MagicMock(data=[])
        mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.is_.return_value = chain

        response = client.get(
            "/summaries/other-users-summary-id",
            headers={"Authorization": "Bearer test-token"},
        )
        assert response.status_code == 404

    def test_summary_export_rejects_other_users_summary(self, client, mock_supabase):
        """GET /summaries/{id}/export should 404 for another user's summary."""
        chain = MagicMock()
        chain.execute.return_value = MagicMock(data=[])
        mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.is_.return_value = chain

        response = client.get(
            "/summaries/other-users-summary-id/export?format=markdown",
            headers={"Authorization": "Bearer test-token"},
        )
        assert response.status_code == 404


# ============ SSRF Protection ============


class TestSSRFProtection:
    """Article/PDF extraction must reject private IPs and non-http schemes."""

    def test_rejects_file_scheme(self):
        from app.services.extractors import _validate_url_for_fetch
        with pytest.raises(ValueError, match="Unsupported URL scheme"):
            _validate_url_for_fetch("file:///etc/passwd")

    def test_rejects_ftp_scheme(self):
        from app.services.extractors import _validate_url_for_fetch
        with pytest.raises(ValueError, match="Unsupported URL scheme"):
            _validate_url_for_fetch("ftp://internal-server/data")

    def test_rejects_gopher_scheme(self):
        from app.services.extractors import _validate_url_for_fetch
        with pytest.raises(ValueError, match="Unsupported URL scheme"):
            _validate_url_for_fetch("gopher://internal/resource")

    def test_rejects_data_scheme(self):
        from app.services.extractors import _validate_url_for_fetch
        with pytest.raises(ValueError, match="Unsupported URL scheme"):
            _validate_url_for_fetch("data:text/html,<h1>pwned</h1>")

    def test_rejects_localhost(self):
        from app.services.extractors import _validate_url_for_fetch
        with pytest.raises(ValueError, match="private/reserved"):
            _validate_url_for_fetch("http://localhost/admin")

    def test_rejects_127_0_0_1(self):
        from app.services.extractors import _validate_url_for_fetch
        with pytest.raises(ValueError, match="private/reserved"):
            _validate_url_for_fetch("http://127.0.0.1/admin")

    def test_rejects_cloud_metadata_endpoint(self):
        from app.services.extractors import _validate_url_for_fetch
        with pytest.raises(ValueError, match="private/reserved"):
            _validate_url_for_fetch("http://169.254.169.254/latest/meta-data/")

    def test_rejects_private_10_range(self):
        from app.services.extractors import _validate_url_for_fetch
        with pytest.raises(ValueError, match="private/reserved"):
            _validate_url_for_fetch("http://10.0.0.1/internal")

    def test_rejects_private_192_168_range(self):
        from app.services.extractors import _validate_url_for_fetch
        with pytest.raises(ValueError, match="private/reserved"):
            _validate_url_for_fetch("http://192.168.1.1/router")

    def test_rejects_private_172_16_range(self):
        from app.services.extractors import _validate_url_for_fetch
        with pytest.raises(ValueError, match="private/reserved"):
            _validate_url_for_fetch("http://172.16.0.1/internal")

    def test_allows_public_https(self):
        """Public IPs should be allowed through."""
        from app.services.extractors import _validate_url_for_fetch
        with patch("app.services.extractors.socket.getaddrinfo", return_value=[
            (2, 1, 6, '', ('93.184.216.34', 0)),
        ]):
            result = _validate_url_for_fetch("https://example.com/article")
            assert result == "https://example.com/article"

    def test_rejects_no_hostname(self):
        from app.services.extractors import _validate_url_for_fetch
        with pytest.raises(ValueError, match="no hostname"):
            _validate_url_for_fetch("http://")

    def test_rejects_empty_scheme(self):
        from app.services.extractors import _validate_url_for_fetch
        with pytest.raises(ValueError):
            _validate_url_for_fetch("://no-scheme.com")

    def test_rejects_unresolvable_hostname(self):
        from app.services.extractors import _validate_url_for_fetch
        import socket
        with patch("app.services.extractors.socket.getaddrinfo", side_effect=socket.gaierror("DNS fail")):
            with pytest.raises(ValueError, match="Could not resolve"):
                _validate_url_for_fetch("https://definitely-not-a-real-host-xyz.invalid")


# ============ OAuth State Validation ============


class TestOAuthStateValidation:
    """Notion OAuth flow must validate state tokens."""

    def test_notion_auth_requires_authentication(self, client):
        """GET /auth/notion without auth should return 401."""
        response = client.get("/auth/notion")
        assert response.status_code in (401, 403, 422)

    def test_notion_callback_rejects_unknown_state(self, client):
        """Callback with unknown state token should fail gracefully."""
        response = client.get(
            "/auth/notion/callback?code=test-code&state=fake-user:bad-token",
            allow_redirects=False,
        )
        # Should redirect with error
        assert response.status_code in (302, 307)
        location = response.headers.get("location", "")
        assert "invalid_state" in location or "error" in location

    def test_notion_callback_rejects_malformed_state(self, client):
        """Callback with state that has no colon separator should fail."""
        response = client.get(
            "/auth/notion/callback?code=test-code&state=no-colon-here",
            allow_redirects=False,
        )
        assert response.status_code in (302, 307)
        location = response.headers.get("location", "")
        assert "invalid_state" in location or "error" in location


# ============ JWT Handling ============


class TestJWTHandling:
    """Test malformed and expired JWT handling."""

    def test_missing_auth_header_returns_401(self, client):
        response = client.get("/me")
        assert response.status_code in (401, 403, 422)

    def test_missing_bearer_prefix_returns_401(self, client, mock_supabase):
        response = client.get("/me", headers={"Authorization": "not-bearer token"})
        assert response.status_code == 401

    def test_expired_token_returns_401(self, client, mock_supabase):
        mock_supabase.auth.get_user.side_effect = Exception("Token expired")
        response = client.get("/me", headers={"Authorization": "Bearer expired-token"})
        assert response.status_code == 401

    def test_malformed_token_returns_401(self, client, mock_supabase):
        mock_supabase.auth.get_user.side_effect = Exception("Invalid JWT")
        response = client.get("/me", headers={"Authorization": "Bearer ..."})
        assert response.status_code == 401

    def test_empty_bearer_returns_401(self, client, mock_supabase):
        mock_supabase.auth.get_user.side_effect = Exception("Token required")
        response = client.get("/me", headers={"Authorization": "Bearer "})
        assert response.status_code == 401


# ============ Security Headers ============


class TestSecurityHeaders:
    """Verify security headers are present on all responses."""

    def test_x_content_type_options(self, client):
        response = client.get("/")
        assert response.headers.get("x-content-type-options") == "nosniff"

    def test_x_frame_options(self, client):
        response = client.get("/")
        assert response.headers.get("x-frame-options") == "DENY"

    def test_strict_transport_security(self, client):
        response = client.get("/")
        hsts = response.headers.get("strict-transport-security", "")
        assert "max-age=" in hsts

    def test_x_xss_protection(self, client):
        response = client.get("/")
        assert response.headers.get("x-xss-protection") is not None

    def test_referrer_policy(self, client):
        response = client.get("/")
        assert response.headers.get("referrer-policy") == "strict-origin-when-cross-origin"

    def test_permissions_policy(self, client):
        response = client.get("/")
        policy = response.headers.get("permissions-policy", "")
        assert "camera=()" in policy
        assert "microphone=()" in policy

    def test_content_security_policy(self, client):
        response = client.get("/")
        csp = response.headers.get("content-security-policy", "")
        assert "frame-ancestors 'none'" in csp


# ============ Request Body Limits ============


class TestRequestBodyLimit:
    """Verify oversized request bodies are rejected."""

    def test_oversized_content_length_returns_413(self, client):
        """Request with Content-Length > 10MB should be rejected."""
        response = client.post(
            "/summarize",
            content=b"{}",
            headers={
                "Content-Length": str(11_000_000),
                "Content-Type": "application/json",
                "Authorization": "Bearer test-token",
            },
        )
        assert response.status_code == 413


# ============ Invalid Content Type ============


class TestInvalidContentType:
    """Verify proper handling of unexpected content types."""

    def test_non_json_body_rejected(self, client):
        response = client.post(
            "/summarize",
            content=b"this is not json",
            headers={
                "Content-Type": "text/plain",
                "Authorization": "Bearer test-token",
            },
        )
        assert response.status_code == 422
