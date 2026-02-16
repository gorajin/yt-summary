"""
Router-level integration tests.

Tests unauthenticated API endpoints using FastAPI's TestClient.
Verifies that routes are correctly wired, return proper status codes,
and produce valid response shapes.
"""

import pytest
from fastapi.testclient import TestClient
from main import app


client = TestClient(app)


# ============ Root Endpoint ============

class TestRootEndpoint:
    """Tests for the root / endpoint."""

    def test_root_returns_200(self):
        response = client.get("/")
        assert response.status_code == 200

    def test_root_has_status_ok(self):
        data = client.get("/").json()
        assert data["status"] == "ok"

    def test_root_has_version(self):
        data = client.get("/").json()
        assert "version" in data

    def test_root_has_service_name(self):
        data = client.get("/").json()
        assert "service" in data


# ============ Health Endpoint ============

class TestHealthEndpoint:
    """Tests for the /health endpoint."""

    def test_health_returns_200(self):
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_has_status_ok(self):
        data = client.get("/health").json()
        assert data["status"] == "ok"

    def test_health_has_version(self):
        data = client.get("/health").json()
        assert "version" in data


# ============ Status Endpoint ============

class TestStatusEndpoint:
    """Tests for the /status/{job_id} endpoint."""

    def test_nonexistent_job_requires_auth(self):
        """Without auth, status endpoint should return 401."""
        response = client.get("/status/nonexistent-job-id-12345")
        assert response.status_code in (401, 403)


# ============ Config Endpoint ============

class TestConfigEndpoint:
    """Tests for the /config/extraction endpoint."""

    def test_config_requires_auth(self):
        """Without auth, config endpoint should return 401."""
        response = client.get("/config/extraction")
        assert response.status_code in (401, 403)


# ============ Auth-Required Endpoints (should reject without token) ============

class TestAuthRequiredEndpoints:
    """Verify that authenticated endpoints properly reject unauthenticated requests."""

    def test_me_requires_auth(self):
        response = client.get("/me")
        assert response.status_code in (401, 403, 422)

    def test_summarize_requires_auth(self):
        response = client.post(
            "/summarize",
            json={"url": "https://youtu.be/dQw4w9WgXcQ"}
        )
        assert response.status_code in (401, 403, 422)

    def test_summaries_requires_auth(self):
        response = client.get("/summaries")
        assert response.status_code in (401, 403, 422)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
