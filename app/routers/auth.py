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
import urllib.request
from typing import Optional
from datetime import datetime

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


@router.post("/subscription/sync")
async def sync_subscription(
    body: SubscriptionSyncRequest,
    user: dict = Depends(get_current_user)
):
    """Sync a StoreKit 2 subscription with the backend.
    
    Called by the iOS app after a successful purchase or on app launch
    when an active subscription is detected.
    
    For launch: trusts the client-verified transaction.
    Future: validate with Apple's App Store Server API.
    """
    user_id = user["id"]
    product_id = body.product_id
    
    # Map Apple product IDs to subscription tiers
    PRO_PRODUCT_IDS = {
        "com.watchlater.app.pro.monthly",
        "com.watchlater.app.pro.yearly",
    }
    
    if product_id not in PRO_PRODUCT_IDS:
        raise HTTPException(status_code=400, detail=f"Unknown product: {product_id}")
    
    # Update user's subscription tier
    try:
        supabase.table("users").update({
            "subscription_tier": "pro",
        }).eq("id", user_id).execute()
        
        logger.info(f"Subscription synced: user={user_id}, product={product_id}")
        
        return {
            "success": True,
            "subscription_tier": "pro",
            "message": "Subscription activated successfully"
        }
    except Exception as e:
        logger.error(f"Subscription sync failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to sync subscription")


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
        
        req = urllib.request.Request(
            token_url,
            data=json.dumps(data).encode('utf-8'),
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Basic {credentials}'
            },
            method='POST'
        )
        
        try:
            with urllib.request.urlopen(req) as response:
                token_data = json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8')
            logger.error(f"Notion token exchange failed: {e.code} - {error_body}")
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
    
    return UserProfile(
        id=user["id"],
        email=user["email"],
        notion_connected=bool(user.get("notion_access_token") and user.get("notion_database_id")),
        subscription_tier=tier,
        summaries_this_month=used,
        summaries_remaining=remaining
    )
