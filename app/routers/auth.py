"""
Authentication and user management router.

Provides endpoints for:
- Notion OAuth flow
- User profile retrieval
- Subscription sync
"""

import json
import base64
import logging
import secrets
from typing import Optional
from datetime import datetime

import httpx
from fastapi import APIRouter, HTTPException, Depends, Header
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from notion_client import Client as NotionClient

from ..config import (
    SUPABASE_URL,
    SUPABASE_KEY,
    NOTION_CLIENT_ID,
    NOTION_CLIENT_SECRET,
    NOTION_REDIRECT_URI,
    FREE_TIER_LIMIT,
    ADMIN_TIER_LIMIT,
    DEVELOPER_USER_IDS,
)
from ..models import UserProfile

logger = logging.getLogger(__name__)

# Initialize Supabase
from supabase import create_client, Client as SupabaseClient

supabase: SupabaseClient = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        print("✓ Supabase connected (auth router)")
    except Exception as e:
        print(f"⚠ Supabase initialization failed: {e}")


router = APIRouter(tags=["auth"])


# ============ Auth Helpers ============

async def get_current_user(authorization: Optional[str] = Header(None)):
    """Verify JWT and return user from Supabase."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header required")
    
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization format")
    
    token = authorization.replace("Bearer ", "")
    
    try:
        # Verify token with Supabase
        user_response = supabase.auth.get_user(token)
        if not user_response.user:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        user_id = user_response.user.id
        logger.debug(f"Token valid for user {user_id}")
        
        # Get user profile from our users table
        try:
            result = supabase.table("users").select("*").eq("id", user_id).execute()
            existing_users = result.data if result.data else []
        except Exception as e:
            logger.error(f"Error fetching user profile: {e}")
            existing_users = []
        
        if existing_users and len(existing_users) > 0:
            user = existing_users[0]
            # Apply developer override if applicable
            if user_id in DEVELOPER_USER_IDS and user.get("subscription_tier") == "free":
                user["subscription_tier"] = "admin"
            return user
        
        # Create user profile if doesn't exist
        logger.info(f"Creating new user profile for {user_id}")
        new_user = {
            "id": user_id,
            "email": user_response.user.email,
            "subscription_tier": "free",
            "summaries_this_month": 0,
        }
        supabase.table("users").insert(new_user).execute()
        return new_user
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Auth validation failed: {type(e).__name__}: {e}")
        raise HTTPException(status_code=401, detail=f"Authentication failed: {str(e)}")


def check_rate_limit(user: dict) -> int:
    """Check if user has remaining summaries. Returns remaining count.
    Also handles monthly reset if it's a new month.
    """
    tier = user.get("subscription_tier", "free")
    
    if tier in ["pro", "lifetime"]:
        return -1  # Unlimited
    
    # Admin tier gets higher limit
    limit = ADMIN_TIER_LIMIT if tier == "admin" else FREE_TIER_LIMIT
    
    # Check if we need to reset (new month)
    user_id = user.get("id")
    reset_at = user.get("summaries_reset_at")
    if reset_at and user_id:
        try:
            if isinstance(reset_at, str):
                reset_date = datetime.fromisoformat(reset_at.replace("Z", "+00:00"))
            else:
                reset_date = reset_at
            
            now = datetime.now(reset_date.tzinfo) if reset_date.tzinfo else datetime.now()
            
            # Robust month comparison (handles year rollover)
            if (now.year, now.month) > (reset_date.year, reset_date.month):
                logger.info(f"Resetting monthly usage for user {user_id}")
                supabase.table("users").update({
                    "summaries_this_month": 0,
                    "summaries_reset_at": now.isoformat()
                }).eq("id", user_id).execute()
                return limit
        except Exception as e:
            logger.warning(f"Usage reset check failed: {e}")
    
    used = user.get("summaries_this_month", 0)
    remaining = limit - used
    
    if remaining <= 0:
        raise HTTPException(
            status_code=429, 
            detail="Monthly limit reached. Upgrade to Pro for unlimited summaries."
        )
    
    return remaining


def increment_usage(user_id: str):
    """Increment the user's monthly usage counter."""
    supabase.rpc("increment_summaries", {"p_user_id": user_id}).execute()


# ============ Endpoints ============


class SubscriptionSyncRequest(BaseModel):
    """Request to sync a StoreKit subscription with the backend."""
    product_id: str
    original_transaction_id: Optional[str] = None
    signed_transaction: Optional[str] = None  # JWS from StoreKit 2


@router.post("/subscription/sync")
async def sync_subscription(
    body: SubscriptionSyncRequest,
    user: dict = Depends(get_current_user)
):
    """Sync a StoreKit 2 subscription with the backend.
    
    Called by the iOS app after a successful purchase or on app launch
    when an active subscription is detected.
    
    If `signed_transaction` is provided (JWS from StoreKit 2), it is
    cryptographically verified against Apple's certificate chain.
    Otherwise falls back to trusting the client (backward compat).
    """
    user_id = user["id"]
    product_id = body.product_id
    original_txn_id = body.original_transaction_id
    expires_at = None
    verified = False
    
    # Map Apple product IDs to subscription tiers
    PRO_PRODUCT_IDS = {
        "com.watchlater.app.pro.monthly",
        "com.watchlater.app.pro.yearly",
    }
    
    # --- JWS Verification (preferred) ---
    if body.signed_transaction:
        try:
            from ..services.apple_receipt import verify_signed_transaction, ReceiptValidationError
            
            txn = verify_signed_transaction(body.signed_transaction)
            
            # Use verified values instead of client-provided ones
            product_id = txn.product_id
            original_txn_id = txn.original_transaction_id
            expires_at = txn.expires_date
            verified = True
            
            if not txn.is_valid_pro:
                raise HTTPException(
                    status_code=400,
                    detail=f"Product '{product_id}' is not a recognized Pro subscription"
                )
            
            logger.info(f"JWS verified for user {user_id}: product={product_id}, expires={expires_at}")
            
        except ReceiptValidationError as e:
            logger.warning(f"JWS verification failed for user {user_id}: {e}")
            raise HTTPException(status_code=403, detail=f"Receipt verification failed: {e}")
    else:
        # Fallback: trust client (backward compatibility for older app versions)
        logger.warning(f"No signed_transaction provided for user {user_id}, trusting client claim")
        if product_id not in PRO_PRODUCT_IDS:
            raise HTTPException(status_code=400, detail=f"Unknown product: {product_id}")
    
    # Update user's subscription tier with tracking data
    try:
        update_data = {
            "subscription_tier": "pro",
            "subscription_product_id": product_id,
            "updated_at": datetime.now().isoformat(),
        }
        if original_txn_id:
            update_data["original_transaction_id"] = original_txn_id
        if expires_at:
            update_data["subscription_expires_at"] = expires_at.isoformat()
        
        supabase.table("users").update(update_data).eq("id", user_id).execute()
        
        logger.info(f"Subscription synced: user={user_id}, product={product_id}, verified={verified}")
        
        return {
            "success": True,
            "subscription_tier": "pro",
            "verified": verified,
            "message": "Subscription activated successfully"
        }
    except Exception as e:
        logger.error(f"Subscription sync failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to sync subscription")


@router.post("/subscription/downgrade")
async def downgrade_subscription(user: dict = Depends(get_current_user)):
    """Downgrade a user back to free tier.
    
    Called by the iOS app when Transaction.currentEntitlements returns empty
    (subscription expired, cancelled, or refunded). The absence of an active
    entitlement on the device IS the proof of expiry.
    
    Only downgrades users who are currently on 'pro' tier.
    """
    user_id = user["id"]
    current_tier = user.get("subscription_tier", "free")
    
    if current_tier == "free":
        return {
            "success": True,
            "subscription_tier": "free",
            "message": "Already on free tier"
        }
    
    # Don't downgrade lifetime or admin users
    if current_tier in ["lifetime", "admin"]:
        logger.info(f"Skipping downgrade for {current_tier} user {user_id}")
        return {
            "success": True,
            "subscription_tier": current_tier,
            "message": f"Cannot downgrade {current_tier} tier"
        }
    
    try:
        supabase.table("users").update({
            "subscription_tier": "free",
            "subscription_expires_at": None,
            "updated_at": datetime.now().isoformat(),
        }).eq("id", user_id).execute()
        
        logger.info(f"Subscription downgraded: user={user_id} (pro → free)")
        
        return {
            "success": True,
            "subscription_tier": "free",
            "message": "Subscription expired — downgraded to free tier"
        }
    except Exception as e:
        logger.error(f"Subscription downgrade failed for {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to update subscription")


@router.get("/auth/notion")
async def notion_auth_start(user_id: str):
    """Start Notion OAuth flow."""
    if not NOTION_CLIENT_ID:
        raise HTTPException(status_code=500, detail="Notion OAuth not configured")
    
    state = f"{user_id}:{secrets.token_urlsafe(16)}"
    
    auth_url = (
        f"https://api.notion.com/v1/oauth/authorize"
        f"?client_id={NOTION_CLIENT_ID}"
        f"&response_type=code"
        f"&owner=user"
        f"&redirect_uri={NOTION_REDIRECT_URI}"
        f"&state={state}"
    )
    
    return {"auth_url": auth_url}


@router.get("/auth/notion/callback")
async def notion_auth_callback(code: str, state: str):
    """Handle Notion OAuth callback."""
    try:
        if not NOTION_CLIENT_SECRET or not NOTION_CLIENT_ID:
            logger.error("Notion OAuth not configured")
            return RedirectResponse(url="watchlater://notion-connected?success=false&error=server_not_configured")
        
        user_id = state.split(":")[0]
        logger.info(f"Notion OAuth callback for user: {user_id}")
        
        token_url = "https://api.notion.com/v1/oauth/token"
        credentials = base64.b64encode(f"{NOTION_CLIENT_ID}:{NOTION_CLIENT_SECRET}".encode()).decode()
        
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": NOTION_REDIRECT_URI
        }
        
        try:
            async with httpx.AsyncClient() as client:
                token_response = await client.post(
                    token_url,
                    json=data,
                    headers={
                        'Content-Type': 'application/json',
                        'Authorization': f'Basic {credentials}'
                    },
                    timeout=15.0
                )
                if token_response.status_code != 200:
                    logger.error(f"Notion token exchange failed: {token_response.status_code} - {token_response.text}")
                    return RedirectResponse(url="watchlater://notion-connected?success=false&error=token_exchange_failed")
                token_data = token_response.json()
        except httpx.RequestError as e:
            logger.error(f"Notion token exchange network error: {e}")
            return RedirectResponse(url="watchlater://notion-connected?success=false&error=token_exchange_failed")
        
        access_token = token_data.get("access_token")
        workspace_name = token_data.get("workspace_name")
        logger.info(f"Got Notion token for workspace: {workspace_name}")
        
        notion = NotionClient(auth=access_token)
        search_results = notion.search(filter={"property": "object", "value": "database"}).get("results", [])
        
        database_id = None
        first_database_id = None
        
        for db in search_results:
            if not first_database_id:
                first_database_id = db["id"]
            
            title = db.get("title", [{}])[0].get("plain_text", "")
            title_lower = title.lower()
            
            keywords = ["youtube", "watch", "summary", "video", "notes", "learning", "lecture", "content"]
            if any(kw in title_lower for kw in keywords):
                database_id = db["id"]
                logger.info(f"Found matching database: {title} ({database_id})")
                break
        
        if not database_id and first_database_id:
            logger.info(f"No keyword match - using first available database: {first_database_id}")
            database_id = first_database_id
        
        if not database_id:
            logger.info("No databases found - attempting to create 'YouTube Summaries' database")
            try:
                page_results = notion.search(filter={"property": "object", "value": "page"}).get("results", [])
                
                if page_results:
                    parent_page_id = page_results[0]["id"]
                    new_db = notion.databases.create(
                        parent={"type": "page_id", "page_id": parent_page_id},
                        title=[{"type": "text", "text": {"content": "YouTube Summaries"}}],
                        properties={
                            "Title": {"title": {}},
                            "URL": {"url": {}},
                            "Type": {
                                "select": {
                                    "options": [
                                        {"name": "Lecture", "color": "blue"},
                                        {"name": "Tutorial", "color": "green"},
                                        {"name": "Interview", "color": "purple"},
                                        {"name": "Documentary", "color": "orange"},
                                        {"name": "General", "color": "gray"}
                                    ]
                                }
                            },
                            "Date Added": {"date": {}}
                        }
                    )
                    database_id = new_db["id"]
                    logger.info(f"Created new database: YouTube Summaries ({database_id})")
                else:
                    logger.warning("No pages found to use as parent")
                    
            except Exception as db_create_err:
                logger.error(f"Failed to create database: {db_create_err}")
        
        supabase.table("users").update({
            "notion_access_token": access_token,
            "notion_database_id": database_id,
            "notion_workspace": workspace_name
        }).eq("id", user_id).execute()
        
        logger.info(f"Notion connected for user {user_id}")
        
        return RedirectResponse(url="watchlater://notion-connected?success=true")
        
    except Exception as e:
        logger.error(f"Notion OAuth callback error: {e}", exc_info=True)
        return RedirectResponse(url="watchlater://notion-connected?success=false&error=unknown")


@router.get("/me")
async def get_profile(user: dict = Depends(get_current_user)):
    """Get current user profile."""
    tier = user.get("subscription_tier", "free")
    used = user.get("summaries_this_month", 0)
    limit = ADMIN_TIER_LIMIT if tier == "admin" else FREE_TIER_LIMIT
    remaining = -1 if tier in ["pro", "lifetime"] else max(0, limit - used)
    
    profile = UserProfile(
        id=user["id"],
        email=user["email"],
        notion_connected=bool(user.get("notion_access_token") and user.get("notion_database_id")),
        subscription_tier=tier,
        summaries_this_month=used,
        summaries_remaining=remaining
    )
    
    # Add email digest preferences
    return {
        **profile.model_dump(),
        "email_digest_enabled": user.get("email_digest_enabled", True),
        "email_digest_time": user.get("email_digest_time", "20:00"),
        "timezone": user.get("timezone", "UTC"),
    }


class EmailPreferencesRequest(BaseModel):
    """Request to update email digest preferences."""
    email_digest_enabled: Optional[bool] = None
    email_digest_time: Optional[str] = None  # HH:MM format
    timezone: Optional[str] = None


@router.get("/email/preferences")
async def get_email_preferences(user: dict = Depends(get_current_user)):
    """Get current email digest preferences."""
    return {
        "email_digest_enabled": user.get("email_digest_enabled", True),
        "email_digest_time": user.get("email_digest_time", "20:00"),
        "timezone": user.get("timezone", "UTC"),
    }


@router.put("/email/preferences")
async def update_email_preferences(
    body: EmailPreferencesRequest,
    user: dict = Depends(get_current_user),
):
    """Update email digest preferences."""
    user_id = user["id"]
    
    update_data = {"updated_at": datetime.now().isoformat()}
    
    if body.email_digest_enabled is not None:
        update_data["email_digest_enabled"] = body.email_digest_enabled
    
    if body.email_digest_time is not None:
        # Validate HH:MM format
        try:
            parts = body.email_digest_time.split(":")
            hour = int(parts[0])
            minute = int(parts[1])
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError
            update_data["email_digest_time"] = f"{hour:02d}:{minute:02d}"
        except (ValueError, IndexError):
            raise HTTPException(status_code=400, detail="Invalid time format. Use HH:MM (e.g., '20:00')")
    
    if body.timezone is not None:
        update_data["timezone"] = body.timezone
    
    try:
        supabase.table("users").update(update_data).eq("id", user_id).execute()
        
        return {
            "success": True,
            "email_digest_enabled": update_data.get("email_digest_enabled", user.get("email_digest_enabled", True)),
            "email_digest_time": update_data.get("email_digest_time", user.get("email_digest_time", "20:00")),
            "timezone": update_data.get("timezone", user.get("timezone", "UTC")),
        }
    except Exception as e:
        logger.error(f"Failed to update email prefs for {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to update preferences")
