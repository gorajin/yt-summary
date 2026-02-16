"""
Apple JWS Transaction Verification Service.

Verifies StoreKit 2 signed transactions by:
1. Extracting the x5c certificate chain from the JWS header
2. Verifying the chain roots to Apple's known CA
3. Verifying the JWS signature using the leaf certificate
4. Returning the decoded transaction payload

No Apple API keys or secrets required — all verification happens
using Apple's public certificates embedded in the JWS itself.

Reference: https://developer.apple.com/documentation/appstoreserverapi/jwstransaction
"""

import json
import base64
import logging
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Optional

import jwt
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils as asym_utils

logger = logging.getLogger(__name__)

# Apple's known root certificate subject CN
APPLE_ROOT_CA_G3_CN = "Apple Root CA - G3"

# Expected bundle ID for WatchLater
EXPECTED_BUNDLE_ID = "com.watchlater.app"

# Valid Pro product IDs
PRO_PRODUCT_IDS = {
    "com.watchlater.app.pro.monthly",
    "com.watchlater.app.pro.yearly",
}


@dataclass
class VerifiedTransaction:
    """Parsed and verified Apple transaction."""
    product_id: str
    original_transaction_id: str
    transaction_id: str
    expires_date: Optional[datetime]
    purchase_date: datetime
    bundle_id: str
    is_valid_pro: bool  # whether this is a recognized Pro product


class ReceiptValidationError(Exception):
    """Raised when receipt validation fails."""
    pass


def _base64url_decode(data: str) -> bytes:
    """Decode base64url-encoded data with padding."""
    # Add padding if needed
    padding = 4 - len(data) % 4
    if padding != 4:
        data += "=" * padding
    return base64.urlsafe_b64decode(data)


def _extract_jws_parts(signed_transaction: str) -> tuple[dict, dict, bytes]:
    """Split a JWS into header, payload, and signature."""
    parts = signed_transaction.split(".")
    if len(parts) != 3:
        raise ReceiptValidationError("Invalid JWS format: expected 3 parts")
    
    header = json.loads(_base64url_decode(parts[0]))
    payload = json.loads(_base64url_decode(parts[1]))
    signature = _base64url_decode(parts[2])
    
    return header, payload, signature


def _verify_certificate_chain(x5c_chain: list[str]) -> x509.Certificate:
    """
    Verify the x5c certificate chain from Apple.
    
    The chain should be: [leaf, intermediate, root]
    - Root must be Apple Root CA - G3
    - Each cert must be signed by the next in the chain
    
    Returns the leaf certificate (used for signature verification).
    """
    if not x5c_chain or len(x5c_chain) < 2:
        raise ReceiptValidationError("Certificate chain too short")
    
    # Parse all certificates
    certs = []
    for cert_b64 in x5c_chain:
        cert_der = base64.b64decode(cert_b64)
        cert = x509.load_der_x509_certificate(cert_der)
        certs.append(cert)
    
    # Verify root certificate is Apple Root CA - G3
    root_cert = certs[-1]
    root_cn = root_cert.subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)
    if not root_cn or APPLE_ROOT_CA_G3_CN not in root_cn[0].value:
        raise ReceiptValidationError(
            f"Root certificate is not Apple Root CA: {root_cn[0].value if root_cn else 'unknown'}"
        )
    
    # Verify each certificate is signed by the next one in the chain
    for i in range(len(certs) - 1):
        child = certs[i]
        parent = certs[i + 1]
        
        try:
            parent_public_key = parent.public_key()
            parent_public_key.verify(
                child.signature,
                child.tbs_certificate_bytes,
                ec.ECDSA(child.signature_hash_algorithm)
            )
        except Exception as e:
            raise ReceiptValidationError(
                f"Certificate chain verification failed at position {i}: {e}"
            )
    
    # Check leaf certificate is not expired
    leaf = certs[0]
    now = datetime.now(timezone.utc)
    if now < leaf.not_valid_before_utc or now > leaf.not_valid_after_utc:
        raise ReceiptValidationError("Leaf certificate is expired or not yet valid")
    
    return leaf


def _verify_jws_signature(signed_transaction: str, leaf_cert: x509.Certificate) -> None:
    """Verify the JWS signature using the leaf certificate's public key."""
    parts = signed_transaction.split(".")
    signing_input = f"{parts[0]}.{parts[1]}".encode("ascii")
    signature = _base64url_decode(parts[2])
    
    public_key = leaf_cert.public_key()
    
    try:
        # Apple uses ES256 (ECDSA with P-256 and SHA-256)
        # JWS signatures are in raw (r || s) format, need to convert to DER
        r = int.from_bytes(signature[:32], "big")
        s = int.from_bytes(signature[32:], "big")
        der_signature = asym_utils.encode_dss_signature(r, s)
        
        public_key.verify(
            der_signature,
            signing_input,
            ec.ECDSA(hashes.SHA256())
        )
    except Exception as e:
        raise ReceiptValidationError(f"JWS signature verification failed: {e}")


def verify_signed_transaction(
    signed_transaction: str,
    bundle_id: str = EXPECTED_BUNDLE_ID,
    allow_sandbox: bool = True
) -> VerifiedTransaction:
    """
    Verify a StoreKit 2 signed JWS transaction.
    
    Args:
        signed_transaction: The JWS string from StoreKit 2's Transaction.jwsRepresentation
        bundle_id: Expected app bundle ID
        allow_sandbox: Whether to allow sandbox environment transactions
        
    Returns:
        VerifiedTransaction with extracted and verified fields
        
    Raises:
        ReceiptValidationError: If verification fails at any step
    """
    # Step 1: Parse JWS parts
    header, payload, _ = _extract_jws_parts(signed_transaction)
    
    # Step 2: Extract and verify certificate chain
    x5c = header.get("x5c")
    if not x5c:
        raise ReceiptValidationError("JWS header missing x5c certificate chain")
    
    leaf_cert = _verify_certificate_chain(x5c)
    
    # Step 3: Verify JWS signature
    _verify_jws_signature(signed_transaction, leaf_cert)
    
    # Step 4: Validate payload
    payload_bundle_id = payload.get("bundleId", "")
    if payload_bundle_id != bundle_id:
        raise ReceiptValidationError(
            f"Bundle ID mismatch: expected '{bundle_id}', got '{payload_bundle_id}'"
        )
    
    # Check environment
    environment = payload.get("environment", "")
    if environment == "Sandbox" and not allow_sandbox:
        raise ReceiptValidationError("Sandbox transactions not allowed in production")
    
    # Extract dates
    expires_ms = payload.get("expiresDate")
    expires_date = None
    if expires_ms:
        expires_date = datetime.fromtimestamp(expires_ms / 1000, tz=timezone.utc)
    
    purchase_ms = payload.get("purchaseDate", 0)
    purchase_date = datetime.fromtimestamp(purchase_ms / 1000, tz=timezone.utc)
    
    product_id = payload.get("productId", "")
    
    result = VerifiedTransaction(
        product_id=product_id,
        original_transaction_id=str(payload.get("originalTransactionId", "")),
        transaction_id=str(payload.get("transactionId", "")),
        expires_date=expires_date,
        purchase_date=purchase_date,
        bundle_id=payload_bundle_id,
        is_valid_pro=product_id in PRO_PRODUCT_IDS,
    )
    
    logger.info(
        f"Verified transaction: product={result.product_id}, "
        f"txn={result.transaction_id}, "
        f"expires={result.expires_date}, "
        f"env={environment}"
    )
    
    return result
