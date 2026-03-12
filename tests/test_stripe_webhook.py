"""Tests for Stripe webhook and checkout endpoints."""

import json
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime

from fastapi.testclient import TestClient


# ============ Fixtures ============

@pytest.fixture
def mock_supabase():
    """Mock Supabase client for auth router."""
    mock = MagicMock()
    # Mock auth.get_user
    mock_user = MagicMock()
    mock_user.user.id = "test-user-123"
    mock_user.user.email = "test@example.com"
    mock.auth.get_user.return_value = mock_user
    # Mock table queries
    mock.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[{
            "id": "test-user-123",
            "email": "test@example.com",
            "subscription_tier": "free",
            "summaries_this_month": 0,
            "stripe_customer_id": None,
        }]
    )
    mock.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
    return mock


@pytest.fixture
def app_with_stripe(mock_supabase):
    """Create app with mocked Stripe and Supabase."""
    with patch.dict("os.environ", {
        "GEMINI_API_KEY": "test-key",
        "SUPABASE_URL": "https://test.supabase.co",
        "SUPABASE_KEY": "test-key",
        "STRIPE_SECRET_KEY": "sk_test_xxx",
        "STRIPE_WEBHOOK_SECRET": "whsec_test_xxx",
        "WEB_APP_URL": "https://app.watchlater.dev",
    }):
        import importlib
        from app import config
        importlib.reload(config)

        from app.routers import auth as auth_module
        auth_module.supabase = mock_supabase
        # Patch Stripe config in auth module's namespace — when other tests
        # import config first (without Stripe env vars), auth.py's local
        # bindings from `from ..config import ...` remain None even after
        # config is reloaded.
        auth_module.STRIPE_SECRET_KEY = "sk_test_xxx"
        auth_module.STRIPE_WEBHOOK_SECRET = "whsec_test_xxx"
        auth_module.WEB_APP_URL = "https://app.watchlater.dev"

        from main import app
        yield app


@pytest.fixture
def client(app_with_stripe):
    return TestClient(app_with_stripe)


# ============ Checkout Tests ============

class TestStripeCheckout:

    def test_checkout_creates_session(self, client, mock_supabase):
        """POST /subscription/stripe-checkout should create a Stripe session."""
        mock_session = MagicMock()
        mock_session.url = "https://checkout.stripe.com/session/xxx"

        with patch("stripe.Customer.create") as mock_customer, \
             patch("stripe.checkout.Session.create", return_value=mock_session):
            mock_customer.return_value = MagicMock(id="cus_test_123")

            response = client.post(
                "/subscription/stripe-checkout",
                json={"price_id": "price_test_monthly"},
                headers={"Authorization": "Bearer test-token"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["url"] == "https://checkout.stripe.com/session/xxx"

    def test_checkout_reuses_existing_customer(self, client, mock_supabase):
        """Should reuse existing Stripe customer ID if present."""
        # Set up user with existing stripe_customer_id
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{
                "id": "test-user-123",
                "email": "test@example.com",
                "subscription_tier": "free",
                "summaries_this_month": 0,
                "stripe_customer_id": "cus_existing_456",
            }]
        )

        mock_session = MagicMock()
        mock_session.url = "https://checkout.stripe.com/session/yyy"

        with patch("stripe.checkout.Session.create", return_value=mock_session) as mock_create:
            response = client.post(
                "/subscription/stripe-checkout",
                json={"price_id": "price_test_yearly"},
                headers={"Authorization": "Bearer test-token"},
            )

        assert response.status_code == 200
        # Verify Session.create was called with existing customer
        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["customer"] == "cus_existing_456"


# ============ Webhook Tests ============

class TestStripeWebhook:

    def test_checkout_completed_activates_pro(self, client, mock_supabase):
        """checkout.session.completed should set subscription_tier to pro."""
        event = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "metadata": {"user_id": "test-user-123"},
                    "subscription": "sub_test_789",
                    "customer": "cus_test_123",
                }
            }
        }

        with patch("stripe.Webhook.construct_event", return_value=event):
            response = client.post(
                "/subscription/stripe-webhook",
                content=json.dumps(event),
                headers={"stripe-signature": "test_sig"},
            )

        assert response.status_code == 200
        assert response.json() == {"received": True}

        # Verify subscription was updated
        mock_supabase.table.return_value.update.assert_called()
        update_call = mock_supabase.table.return_value.update.call_args[0][0]
        assert update_call["subscription_tier"] == "pro"
        assert update_call["stripe_subscription_id"] == "sub_test_789"

    def test_subscription_deleted_downgrades(self, client, mock_supabase):
        """customer.subscription.deleted should downgrade to free."""
        # Mock finding user by stripe_customer_id
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{"id": "test-user-123"}]
        )

        event = {
            "type": "customer.subscription.deleted",
            "data": {
                "object": {
                    "customer": "cus_test_123",
                }
            }
        }

        with patch("stripe.Webhook.construct_event", return_value=event):
            response = client.post(
                "/subscription/stripe-webhook",
                content=json.dumps(event),
                headers={"stripe-signature": "test_sig"},
            )

        assert response.status_code == 200
        assert response.json() == {"received": True}

    def test_invalid_signature_rejected(self, client):
        """Webhook with invalid signature should be rejected."""
        import stripe

        with patch(
            "stripe.Webhook.construct_event",
            side_effect=stripe.error.SignatureVerificationError("bad sig", "test_sig"),
        ):
            response = client.post(
                "/subscription/stripe-webhook",
                content=b"{}",
                headers={"stripe-signature": "bad_sig"},
            )

        assert response.status_code == 400

    def test_invalid_payload_rejected(self, client):
        """Webhook with invalid payload should be rejected."""
        with patch(
            "stripe.Webhook.construct_event",
            side_effect=ValueError("invalid payload"),
        ):
            response = client.post(
                "/subscription/stripe-webhook",
                content=b"bad payload",
                headers={"stripe-signature": "test_sig"},
            )

        assert response.status_code == 400
