"""
Tests for Apple JWS receipt validation and subscription endpoints.

Tests the apple_receipt verification service and the subscription
management endpoints (sync and downgrade).
"""

import pytest
import json
import base64
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
from app.services.apple_receipt import (
    _base64url_decode,
    _extract_jws_parts,
    ReceiptValidationError,
    VerifiedTransaction,
    verify_signed_transaction,
    PRO_PRODUCT_IDS,
    EXPECTED_BUNDLE_ID,
)


# ============ Helper Functions ============

def _base64url_encode(data: bytes) -> str:
    """Encode bytes to base64url without padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _make_jws(header: dict, payload: dict, signature: bytes = b"x" * 64) -> str:
    """Construct a fake JWS string for testing."""
    h = _base64url_encode(json.dumps(header).encode())
    p = _base64url_encode(json.dumps(payload).encode())
    s = _base64url_encode(signature)
    return f"{h}.{p}.{s}"


# ============ Tests: Base64url Decoding ============

class TestBase64urlDecode:
    def test_standard_decode(self):
        original = b"hello world"
        encoded = _base64url_encode(original)
        assert _base64url_decode(encoded) == original

    def test_decode_with_padding(self):
        """base64url without padding should still decode correctly."""
        original = b"test"
        encoded = base64.urlsafe_b64encode(original).rstrip(b"=").decode()
        assert _base64url_decode(encoded) == original

    def test_decode_url_safe_chars(self):
        """Ensure +/ are replaced with -_ in url-safe encoding."""
        data = bytes(range(256))
        encoded = _base64url_encode(data)
        assert "+" not in encoded
        assert "/" not in encoded
        assert _base64url_decode(encoded) == data


# ============ Tests: JWS Parsing ============

class TestJWSParsing:
    def test_valid_jws_three_parts(self):
        header = {"alg": "ES256", "x5c": ["cert1"]}
        payload = {"productId": "com.test.product", "bundleId": "com.test.app"}
        jws = _make_jws(header, payload)

        h, p, sig = _extract_jws_parts(jws)
        assert h["alg"] == "ES256"
        assert p["productId"] == "com.test.product"

    def test_invalid_jws_wrong_parts(self):
        with pytest.raises(ReceiptValidationError, match="expected 3 parts"):
            _extract_jws_parts("only.two")

    def test_invalid_jws_empty(self):
        with pytest.raises(ReceiptValidationError, match="expected 3 parts"):
            _extract_jws_parts("")


# ============ Tests: VerifiedTransaction Dataclass ============

class TestVerifiedTransaction:
    def test_is_valid_pro_monthly(self):
        txn = VerifiedTransaction(
            product_id="com.watchlater.app.pro.monthly",
            original_transaction_id="12345",
            transaction_id="67890",
            expires_date=datetime.now(timezone.utc) + timedelta(days=30),
            purchase_date=datetime.now(timezone.utc),
            bundle_id=EXPECTED_BUNDLE_ID,
            is_valid_pro=True,
        )
        assert txn.is_valid_pro is True

    def test_is_valid_pro_yearly(self):
        txn = VerifiedTransaction(
            product_id="com.watchlater.app.pro.yearly",
            original_transaction_id="12345",
            transaction_id="67890",
            expires_date=datetime.now(timezone.utc) + timedelta(days=365),
            purchase_date=datetime.now(timezone.utc),
            bundle_id=EXPECTED_BUNDLE_ID,
            is_valid_pro=True,
        )
        assert txn.is_valid_pro is True

    def test_is_not_valid_pro_unknown(self):
        txn = VerifiedTransaction(
            product_id="com.other.app.premium",
            original_transaction_id="12345",
            transaction_id="67890",
            expires_date=None,
            purchase_date=datetime.now(timezone.utc),
            bundle_id="com.other.app",
            is_valid_pro=False,
        )
        assert txn.is_valid_pro is False


# ============ Tests: Full Verification (mocked crypto) ============

class TestVerifySignedTransaction:
    """Test the full verification flow with mocked certificate verification."""

    def test_missing_x5c_header(self):
        """JWS without x5c certificate chain should fail."""
        header = {"alg": "ES256"}  # No x5c
        payload = {"productId": "com.watchlater.app.pro.monthly"}
        jws = _make_jws(header, payload)

        with pytest.raises(ReceiptValidationError, match="missing x5c"):
            verify_signed_transaction(jws)

    def test_bundle_id_mismatch(self):
        """Verified JWS with wrong bundle ID should fail."""
        header = {"alg": "ES256", "x5c": ["cert1", "cert2"]}
        payload = {
            "productId": "com.watchlater.app.pro.monthly",
            "bundleId": "com.wrong.bundle",
            "originalTransactionId": "12345",
            "transactionId": "67890",
            "purchaseDate": int(datetime.now(timezone.utc).timestamp() * 1000),
        }
        jws = _make_jws(header, payload)

        with patch("app.services.apple_receipt._verify_certificate_chain") as mock_chain, \
             patch("app.services.apple_receipt._verify_jws_signature"):
            mock_cert = MagicMock()
            mock_chain.return_value = mock_cert

            with pytest.raises(ReceiptValidationError, match="Bundle ID mismatch"):
                verify_signed_transaction(jws)

    def test_successful_verification(self):
        """Full verification with mocked crypto should return VerifiedTransaction."""
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        expires_ms = int((datetime.now(timezone.utc) + timedelta(days=30)).timestamp() * 1000)

        header = {"alg": "ES256", "x5c": ["cert1", "cert2"]}
        payload = {
            "productId": "com.watchlater.app.pro.monthly",
            "bundleId": EXPECTED_BUNDLE_ID,
            "originalTransactionId": "1000000012345",
            "transactionId": "1000000067890",
            "purchaseDate": now_ms,
            "expiresDate": expires_ms,
            "environment": "Sandbox",
        }
        jws = _make_jws(header, payload)

        with patch("app.services.apple_receipt._verify_certificate_chain") as mock_chain, \
             patch("app.services.apple_receipt._verify_jws_signature"):
            mock_cert = MagicMock()
            mock_chain.return_value = mock_cert

            result = verify_signed_transaction(jws)

            assert result.product_id == "com.watchlater.app.pro.monthly"
            assert result.original_transaction_id == "1000000012345"
            assert result.is_valid_pro is True
            assert result.expires_date is not None
            assert result.bundle_id == EXPECTED_BUNDLE_ID

    def test_sandbox_rejected_when_disallowed(self):
        """Sandbox transactions should be rejected when allow_sandbox=False."""
        header = {"alg": "ES256", "x5c": ["cert1", "cert2"]}
        payload = {
            "productId": "com.watchlater.app.pro.monthly",
            "bundleId": EXPECTED_BUNDLE_ID,
            "originalTransactionId": "12345",
            "transactionId": "67890",
            "purchaseDate": int(datetime.now(timezone.utc).timestamp() * 1000),
            "environment": "Sandbox",
        }
        jws = _make_jws(header, payload)

        with patch("app.services.apple_receipt._verify_certificate_chain") as mock_chain, \
             patch("app.services.apple_receipt._verify_jws_signature"):
            mock_cert = MagicMock()
            mock_chain.return_value = mock_cert

            with pytest.raises(ReceiptValidationError, match="Sandbox"):
                verify_signed_transaction(jws, allow_sandbox=False)


# ============ Tests: Pro Product ID Validation ============

class TestProProductIDs:
    def test_monthly_is_pro(self):
        assert "com.watchlater.app.pro.monthly" in PRO_PRODUCT_IDS

    def test_yearly_is_pro(self):
        assert "com.watchlater.app.pro.yearly" in PRO_PRODUCT_IDS

    def test_unknown_not_pro(self):
        assert "com.watchlater.app.free" not in PRO_PRODUCT_IDS

    def test_expected_bundle_id(self):
        assert EXPECTED_BUNDLE_ID == "com.watchlater.app"
