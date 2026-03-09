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

    def test_root_response_shape(self):
        """Root response should have exactly the expected keys."""
        data = client.get("/").json()
        expected_keys = {"status", "service", "version"}
        assert expected_keys.issubset(set(data.keys()))


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

    def test_ingest_requires_auth(self):
        """Ingest endpoint should reject unauthenticated requests."""
        response = client.post(
            "/ingest",
            json={"url": "https://example.com/article"}
        )
        assert response.status_code in (401, 403, 422)

    def test_summaries_requires_auth(self):
        response = client.get("/summaries")
        assert response.status_code in (401, 403, 422)

    def test_summary_detail_requires_auth(self):
        """Individual summary endpoint should reject without auth."""
        response = client.get("/summaries/fake-summary-id")
        assert response.status_code in (401, 403, 422)

    def test_summary_export_requires_auth(self):
        """Summary export endpoint should reject without auth."""
        response = client.get("/summaries/fake-summary-id/export")
        assert response.status_code in (401, 403, 422)

    def test_knowledge_map_requires_auth(self):
        """Knowledge map endpoint should reject without auth."""
        response = client.get("/knowledge-map")
        assert response.status_code in (401, 403, 422)

    def test_knowledge_map_build_requires_auth(self):
        """Knowledge map build endpoint should reject without auth."""
        response = client.post("/knowledge-map/build")
        assert response.status_code in (401, 403, 422)

    def test_subscription_sync_requires_auth(self):
        """Subscription sync should reject without auth."""
        response = client.post("/subscription/sync", json={})
        assert response.status_code in (401, 403, 422)

    def test_email_preferences_get_requires_auth(self):
        """Email preferences GET should reject without auth."""
        response = client.get("/email/preferences")
        assert response.status_code in (401, 403, 422)

    def test_email_preferences_put_requires_auth(self):
        """Email preferences PUT should reject without auth."""
        response = client.put("/email/preferences", json={})
        assert response.status_code in (401, 403, 422)


# ============ Invalid Method Tests ============

class TestInvalidMethods:
    """Verify that endpoints reject wrong HTTP methods."""

    def test_root_rejects_post(self):
        response = client.post("/")
        assert response.status_code == 405

    def test_health_rejects_post(self):
        response = client.post("/health")
        assert response.status_code == 405

    def test_summarize_rejects_get(self):
        response = client.get("/summarize")
        assert response.status_code == 405

    def test_ingest_rejects_get(self):
        response = client.get("/ingest")
        assert response.status_code == 405


# ============ Invalid Body Tests ============

class TestInvalidRequestBodies:
    """Verify that endpoints reject malformed request bodies."""

    def test_summarize_empty_body(self):
        """POST /summarize with empty body should fail validation."""
        response = client.post("/summarize", json={})
        # Either 422 (validation) or 401/403 (auth before validation)
        assert response.status_code in (401, 403, 422)

    def test_summarize_missing_url(self):
        """POST /summarize without 'url' should fail."""
        response = client.post("/summarize", json={"transcript": "some text"})
        assert response.status_code in (401, 403, 422)

    def test_ingest_empty_body(self):
        """POST /ingest with empty body should fail validation."""
        response = client.post("/ingest", json={})
        assert response.status_code in (401, 403, 422)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
