"""
Authentication and user management router.

Provides endpoints for:
- Notion OAuth flow
- User profile retrieval
- Debug token validation
"""

import json
import base64
import secrets
import urllib.request
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends, Header
from fastapi.responses import RedirectResponse
from notion_client import Client as NotionClient

from ..config import (
    SUPABASE_URL,
    SUPABASE_KEY,
    NOTION_CLIENT_ID,
    NOTION_CLIENT_SECRET,
    NOTION_REDIRECT_URI,
    FREE_TIER_LIMIT,
)
from ..models import UserProfile

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
        print("AUTH ERROR: No authorization header")
        raise HTTPException(status_code=401, detail="Authorization header required")
    
    if not authorization.startswith("Bearer "):
        print(f"AUTH ERROR: Invalid format - expected 'Bearer <token>'")
        raise HTTPException(status_code=401, detail="Invalid authorization format")
    
    token = authorization.replace("Bearer ", "")
    token_length_category = "short" if len(token) < 100 else "medium" if len(token) < 500 else "long"
    print(f"AUTH: Validating {token_length_category} token ({len(token)} chars)")
    
    try:
        # Verify token with Supabase
        user_response = supabase.auth.get_user(token)
        if not user_response.user:
            print("AUTH ERROR: get_user returned no user")
            raise HTTPException(status_code=401, detail="Invalid token")
        
        print(f"AUTH: Token valid for user {user_response.user.id}")
        
        # Get user profile from our users table
        user_id = user_response.user.id
        
        try:
            result = supabase.table("users").select("*").eq("id", user_id).execute()
            existing_users = result.data if result.data else []
        except Exception as e:
            print(f"AUTH: Error fetching user: {e}")
            existing_users = []
        
        if existing_users and len(existing_users) > 0:
            print(f"AUTH: Found existing user profile for {user_id}")
            return existing_users[0]
        
        # Create user profile if doesn't exist
        print(f"AUTH: Creating new user profile for {user_id}")
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
        print(f"AUTH ERROR: Exception during validation: {type(e).__name__}: {str(e)}")
        raise HTTPException(status_code=401, detail=f"Authentication failed: {str(e)}")


def check_rate_limit(user: dict) -> int:
    """Check if user has remaining summaries. Returns remaining count.
    Also handles monthly reset if it's a new month.
    """
    tier = user.get("subscription_tier", "free")
    
    if tier in ["pro", "lifetime"]:
        return -1  # Unlimited
    
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
            
            if reset_date.year < now.year or reset_date.month < now.month:
                print(f"  → Resetting monthly usage for user {user_id} (last reset: {reset_date})")
                supabase.table("users").update({
                    "summaries_this_month": 0,
                    "summaries_reset_at": now.isoformat()
                }).eq("id", user_id).execute()
                return FREE_TIER_LIMIT
        except Exception as e:
            print(f"  ⚠ Usage reset check failed: {e}")
    
    used = user.get("summaries_this_month", 0)
    remaining = FREE_TIER_LIMIT - used
    
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

@router.get("/debug/token")
async def debug_token(authorization: Optional[str] = Header(None)):
    """Debug endpoint to test token validation."""
    result = {
        "has_authorization": authorization is not None,
        "has_supabase": supabase is not None,
        "supabase_url": SUPABASE_URL[:30] + "..." if SUPABASE_URL else None,
    }
    
    if not authorization:
        result["error"] = "No authorization header"
        return result
    
    if not authorization.startswith("Bearer "):
        result["error"] = "Invalid authorization format"
        return result
    
    token = authorization.replace("Bearer ", "")
    result["token_length"] = len(token)
    result["token_prefix"] = token[:30] + "..."
    
    try:
        user_response = supabase.auth.get_user(token)
        result["user_id"] = user_response.user.id if user_response.user else None
        result["user_email"] = user_response.user.email if user_response.user else None
        result["valid"] = user_response.user is not None
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {str(e)}"
        result["valid"] = False
    
    return result


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
        if not NOTION_CLIENT_SECRET:
            print("ERROR: NOTION_CLIENT_SECRET not configured")
            return RedirectResponse(url=f"watchlater://notion-connected?success=false&error=server_not_configured")
        
        if not NOTION_CLIENT_ID:
            print("ERROR: NOTION_CLIENT_ID not configured")
            return RedirectResponse(url=f"watchlater://notion-connected?success=false&error=server_not_configured")
        
        user_id = state.split(":")[0]
        print(f"Notion OAuth callback for user: {user_id}")
        
        token_url = "https://api.notion.com/v1/oauth/token"
        credentials = base64.b64encode(f"{NOTION_CLIENT_ID}:{NOTION_CLIENT_SECRET}".encode()).decode()
        
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": NOTION_REDIRECT_URI
        }
        
        print(f"Exchanging code for token with redirect_uri: {NOTION_REDIRECT_URI}")
        
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
            print(f"Notion token exchange failed: {e.code} - {error_body}")
            return RedirectResponse(url=f"watchlater://notion-connected?success=false&error=token_exchange_failed")
        
        access_token = token_data.get("access_token")
        workspace_name = token_data.get("workspace_name")
        print(f"Got Notion token for workspace: {workspace_name}")
        
        notion = NotionClient(auth=access_token)
        search_results = notion.search(filter={"property": "object", "value": "database"}).get("results", [])
        
        database_id = None
        for db in search_results:
            title = db.get("title", [{}])[0].get("plain_text", "")
            if "YouTube" in title or "Watch" in title or "Summary" in title:
                database_id = db["id"]
                print(f"Found existing database: {title} ({database_id})")
                break
        
        if not database_id:
            print("No matching database found - user will need to create one")
        
        supabase.table("users").update({
            "notion_access_token": access_token,
            "notion_database_id": database_id,
            "notion_workspace": workspace_name
        }).eq("id", user_id).execute()
        
        print(f"✓ Notion connected for user {user_id}")
        
        return RedirectResponse(url=f"watchlater://notion-connected?success=true")
        
    except Exception as e:
        print(f"Notion OAuth callback error: {str(e)}")
        import traceback
        traceback.print_exc()
        return RedirectResponse(url=f"watchlater://notion-connected?success=false&error=unknown")


@router.get("/me")
async def get_profile(user: dict = Depends(get_current_user)):
    """Get current user profile."""
    tier = user.get("subscription_tier", "free")
    used = user.get("summaries_this_month", 0)
    remaining = -1 if tier in ["pro", "lifetime"] else max(0, FREE_TIER_LIMIT - used)
    
    return UserProfile(
        id=user["id"],
        email=user["email"],
        notion_connected=bool(user.get("notion_access_token") and user.get("notion_database_id")),
        subscription_tier=tier,
        summaries_this_month=used,
        summaries_remaining=remaining
    )
