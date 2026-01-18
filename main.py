"""
YouTube Summary API - Multi-User Version
FastAPI backend with Supabase auth, Notion OAuth, and user-specific summaries.
"""

import os
import re
import json
import tempfile
import urllib.request
import secrets
from typing import Optional
from datetime import date, datetime
from fastapi import FastAPI, HTTPException, Depends, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from dotenv import load_dotenv

import yt_dlp
from notion_client import Client as NotionClient
from supabase import create_client, Client as SupabaseClient

# Load environment variables
load_dotenv()

app = FastAPI(title="YouTube Summary API", version="2.0.0")

# CORS for iOS app
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Environment variables
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
NOTION_CLIENT_ID = os.getenv("NOTION_CLIENT_ID")
NOTION_CLIENT_SECRET = os.getenv("NOTION_CLIENT_SECRET")
NOTION_REDIRECT_URI = os.getenv("NOTION_REDIRECT_URI", "https://watchlater.up.railway.app/auth/notion/callback")

# Initialize Supabase (optional - for multi-user mode)
supabase: SupabaseClient = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        print("✓ Supabase connected")
    except Exception as e:
        print(f"⚠ Supabase initialization failed: {e}")
        print("  Multi-user mode disabled. Legacy mode still available.")
        supabase = None

# Free tier limits
FREE_TIER_LIMIT = 10


# ============ Models ============

class SummarizeRequest(BaseModel):
    url: str


class SummarizeResponse(BaseModel):
    success: bool
    title: Optional[str] = None
    notionUrl: Optional[str] = None
    error: Optional[str] = None
    remaining: Optional[int] = None


class UserProfile(BaseModel):
    id: str
    email: str
    notion_connected: bool
    subscription_tier: str
    summaries_this_month: int
    summaries_remaining: int


# ============ Auth Helpers ============

async def get_current_user(authorization: Optional[str] = Header(None)):
    """Verify JWT and return user from Supabase."""
    if not authorization:
        print("AUTH ERROR: No authorization header")
        raise HTTPException(status_code=401, detail="Authorization header required")
    
    if not authorization.startswith("Bearer "):
        print(f"AUTH ERROR: Invalid format - got: {authorization[:20]}...")
        raise HTTPException(status_code=401, detail="Invalid authorization format")
    
    token = authorization.replace("Bearer ", "")
    print(f"AUTH: Validating token (first 20 chars): {token[:20]}...")
    
    try:
        # Verify token with Supabase
        user_response = supabase.auth.get_user(token)
        if not user_response.user:
            print("AUTH ERROR: get_user returned no user")
            raise HTTPException(status_code=401, detail="Invalid token")
        
        print(f"AUTH: Token valid for user {user_response.user.id}")
        
        # Get user profile from our users table
        user_id = user_response.user.id
        
        # Try to get existing user (don't use .single() as it throws on 0 rows)
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
    """Check if user has remaining summaries. Returns remaining count."""
    tier = user.get("subscription_tier", "free")
    
    if tier in ["pro", "lifetime"]:
        return -1  # Unlimited
    
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


# ============ YouTube Functions ============

def extract_video_id(url: str) -> Optional[str]:
    """Extract video ID from various YouTube URL formats."""
    patterns = [
        r'(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/shorts\/)([a-zA-Z0-9_-]{11})',
        r'(?:youtube\.com\/embed\/)([a-zA-Z0-9_-]{11})',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    if re.match(r'^[a-zA-Z0-9_-]{11}$', url):
        return url
    return None


def get_transcript(url: str) -> tuple:
    """Fetch transcript. Tries youtube-transcript-api first, falls back to yt-dlp."""
    
    video_id = extract_video_id(url)
    if not video_id:
        raise Exception("Could not extract video ID")
    
    print(f"  → Attempting transcript extraction for video: {video_id}")
    
    # Try youtube-transcript-api first (more reliable on servers)
    try:
        print("  → Trying youtube-transcript-api...")
        from youtube_transcript_api import YouTubeTranscriptApi
        print("  → youtube-transcript-api imported successfully")
        
        # Try to get transcript in order of preference
        transcript_list = None
        for lang in ['en', 'en-US', 'en-GB', 'ko']:
            try:
                transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=[lang])
                print(f"  → Found transcript in language: {lang}")
                break
            except Exception as lang_err:
                print(f"  → No transcript in {lang}: {type(lang_err).__name__}")
                continue
        
        # Try auto-generated if manual not found
        if not transcript_list:
            try:
                print("  → Trying auto-generated transcript...")
                transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
                print("  → Got auto-generated transcript")
            except Exception as auto_err:
                print(f"  → Auto-generated failed: {type(auto_err).__name__}: {auto_err}")
        
        if transcript_list:
            transcript = ' '.join([entry['text'] for entry in transcript_list])
            transcript = re.sub(r'\s+', ' ', transcript).strip()
            
            # Get title via simple API call
            title = get_video_title(video_id)
            print(f"  → Got transcript via youtube-transcript-api ({len(transcript)} chars)")
            return transcript, title
        else:
            print("  → youtube-transcript-api returned no transcript, trying yt-dlp")
            
    except ImportError as ie:
        print(f"  → youtube-transcript-api not installed: {ie}, using yt-dlp")
    except Exception as e:
        print(f"  → youtube-transcript-api failed: {type(e).__name__}: {e}, trying yt-dlp")
    
    # Fallback to yt-dlp
    print("  → Falling back to yt-dlp...")
    return get_transcript_ytdlp(url)


def get_video_title(video_id: str) -> str:
    """Get video title using oembed API (no auth required)."""
    try:
        oembed_url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
        with urllib.request.urlopen(oembed_url, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
            return data.get('title', 'Untitled Video')
    except:
        return 'Untitled Video'


def get_transcript_ytdlp(url: str) -> tuple:
    """Fetch transcript using yt-dlp (fallback method). Returns (transcript, title)."""
    
    ydl_opts = {
        'writesubtitles': True,
        'writeautomaticsub': True,
        'subtitleslangs': ['en', 'en-US', 'en-GB', 'ko', 'ko-KR'],
        'subtitlesformat': 'json3',
        'skip_download': True,
        'quiet': True,
        'no_warnings': True,
    }
    
    with tempfile.TemporaryDirectory() as tmpdir:
        ydl_opts['outtmpl'] = os.path.join(tmpdir, '%(id)s.%(ext)s')
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            title = info.get('title', 'Untitled Video')
            
            subtitles = info.get('subtitles', {})
            auto_captions = info.get('automatic_captions', {})
            
            transcript_url = None
            
            # Try manual subtitles first
            for lang in ['en', 'en-US', 'en-GB', 'ko', 'ko-KR']:
                if lang in subtitles:
                    for fmt in subtitles[lang]:
                        if fmt.get('ext') == 'json3':
                            transcript_url = fmt.get('url')
                            break
                if transcript_url:
                    break
            
            # Fall back to auto-generated
            if not transcript_url:
                for lang in ['en', 'en-US', 'en-GB', 'ko', 'ko-KR']:
                    if lang in auto_captions:
                        for fmt in auto_captions[lang]:
                            if fmt.get('ext') == 'json3':
                                transcript_url = fmt.get('url')
                                break
                    if transcript_url:
                        break
            
            if not transcript_url:
                raise Exception("No subtitles available for this video")
            
            with urllib.request.urlopen(transcript_url) as response:
                transcript_data = json.loads(response.read().decode('utf-8'))
            
            events = transcript_data.get('events', [])
            texts = []
            for event in events:
                segs = event.get('segs', [])
                for seg in segs:
                    text = seg.get('utf8', '').strip()
                    if text and text != '\n':
                        texts.append(text)
            
            transcript = ' '.join(texts)
            transcript = re.sub(r'\s+', ' ', transcript).strip()
            
            if not transcript:
                raise Exception("Could not extract transcript text")
            
            return transcript, title


# ============ Gemini Functions ============

def summarize_with_gemini(transcript: str) -> dict:
    """Summarize transcript using Gemini REST API."""
    prompt = f"""Analyze this YouTube video transcript and provide a structured summary.

TRANSCRIPT:
{transcript[:15000]}

Respond in this exact JSON format (no markdown, just raw JSON):
{{
  "title": "A clear, descriptive title for this video",
  "oneLiner": "One sentence capturing the main point",
  "keyTakeaways": [
    "Key takeaway 1",
    "Key takeaway 2",
    "Key takeaway 3"
  ],
  "insights": [
    "Notable insight 1",
    "Notable insight 2"
  ]
}}

Guidelines:
- Title should be descriptive (not clickbait)
- 3-5 key takeaways that are actionable or memorable
- 2-4 notable insights or "aha moments"
"""
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
    
    data = {
        "contents": [{
            "parts": [{"text": prompt}]
        }]
    }
    
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode('utf-8'),
        headers={'Content-Type': 'application/json'},
        method='POST'
    )
    
    with urllib.request.urlopen(req, timeout=60) as response:
        result = json.loads(response.read().decode('utf-8'))
    
    text = result['candidates'][0]['content']['parts'][0]['text'].strip()
    
    if text.startswith('```'):
        text = re.sub(r'^```json?\n?', '', text)
        text = re.sub(r'\n?```$', '', text)
    
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {
            "title": "Video Summary",
            "oneLiner": "Could not parse summary",
            "keyTakeaways": ["Summary parsing failed"],
            "insights": []
        }


# ============ Notion Functions ============

def create_notion_page(notion_token: str, database_id: str, title: str, url: str, 
                       one_liner: str, takeaways: list, insights: list) -> str:
    """Create a Notion page with the summary using user's token."""
    notion = NotionClient(auth=notion_token)
    
    children = [
        {
            "object": "block",
            "type": "callout",
            "callout": {
                "rich_text": [{"type": "text", "text": {"content": one_liner}}],
                "icon": {"emoji": "💡"},
                "color": "blue_background"
            }
        },
        {"object": "block", "type": "divider", "divider": {}},
        {
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🎯 Key Takeaways"}}]}
        },
    ]
    
    for takeaway in takeaways:
        children.append({
            "object": "block",
            "type": "bulleted_list_item",
            "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": takeaway}}]}
        })
    
    children.append({"object": "block", "type": "divider", "divider": {}})
    children.append({
        "object": "block",
        "type": "heading_2",
        "heading_2": {"rich_text": [{"type": "text", "text": {"content": "✨ Notable Insights"}}]}
    })
    
    for insight in insights:
        children.append({
            "object": "block",
            "type": "bulleted_list_item",
            "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": insight}}]}
        })
    
    response = notion.pages.create(
        parent={"database_id": database_id},
        properties={
            "Title": {"title": [{"text": {"content": title}}]},
            "url": {"url": url},
            "Added": {"date": {"start": date.today().isoformat()}}
        },
        children=children
    )
    
    return response["url"]


# ============ API Endpoints ============

@app.get("/")
async def health():
    return {"status": "ok", "service": "YouTube Summary API", "version": "2.0.0"}


@app.get("/debug/token")
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


@app.get("/auth/notion")
async def notion_auth_start(user_id: str):
    """Start Notion OAuth flow."""
    if not NOTION_CLIENT_ID:
        raise HTTPException(status_code=500, detail="Notion OAuth not configured")
    
    # Store user_id in state for callback
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


@app.get("/auth/notion/callback")
async def notion_auth_callback(code: str, state: str):
    """Handle Notion OAuth callback."""
    try:
        if not NOTION_CLIENT_SECRET:
            print("ERROR: NOTION_CLIENT_SECRET not configured")
            return RedirectResponse(url=f"watchlater://notion-connected?success=false&error=server_not_configured")
        
        if not NOTION_CLIENT_ID:
            print("ERROR: NOTION_CLIENT_ID not configured")
            return RedirectResponse(url=f"watchlater://notion-connected?success=false&error=server_not_configured")
        
        # Extract user_id from state
        user_id = state.split(":")[0]
        print(f"Notion OAuth callback for user: {user_id}")
        
        # Exchange code for token
        token_url = "https://api.notion.com/v1/oauth/token"
        
        import base64
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
        
        # Find or create database for user
        notion = NotionClient(auth=access_token)
        
        # Search for existing database
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
        
        # Update user in database
        supabase.table("users").update({
            "notion_access_token": access_token,
            "notion_database_id": database_id,
            "notion_workspace": workspace_name
        }).eq("id", user_id).execute()
        
        print(f"✓ Notion connected for user {user_id}")
        
        # Redirect to app with success
        return RedirectResponse(url=f"watchlater://notion-connected?success=true")
        
    except Exception as e:
        print(f"Notion OAuth callback error: {str(e)}")
        import traceback
        traceback.print_exc()
        return RedirectResponse(url=f"watchlater://notion-connected?success=false&error=unknown")


@app.get("/me")
async def get_profile(user: dict = Depends(get_current_user)):
    """Get current user profile."""
    tier = user.get("subscription_tier", "free")
    used = user.get("summaries_this_month", 0)
    remaining = -1 if tier in ["pro", "lifetime"] else max(0, FREE_TIER_LIMIT - used)
    
    return UserProfile(
        id=user["id"],
        email=user["email"],
        notion_connected=bool(user.get("notion_access_token")),
        subscription_tier=tier,
        summaries_this_month=used,
        summaries_remaining=remaining
    )


@app.post("/summarize", response_model=SummarizeResponse)
async def summarize(request: SummarizeRequest, user: dict = Depends(get_current_user)):
    """Create a summary (authenticated)."""
    try:
        # Check rate limit
        remaining = check_rate_limit(user)
        
        # Check Notion is connected
        notion_token = user.get("notion_access_token")
        database_id = user.get("notion_database_id")
        
        if not notion_token or not database_id:
            raise HTTPException(status_code=400, detail="Please connect your Notion first")
        
        # Validate URL
        video_id = extract_video_id(request.url)
        if not video_id:
            raise HTTPException(status_code=400, detail="Invalid YouTube URL")
        
        # Process video
        print(f"Processing for user {user['id']}: {request.url}")
        
        print("  → Fetching transcript...")
        transcript, video_title = get_transcript(request.url)
        print(f"  → Got transcript ({len(transcript)} chars)")
        
        print("  → Summarizing with Gemini...")
        summary = summarize_with_gemini(transcript)
        final_title = summary.get("title") or video_title
        print(f"  → Generated: {final_title}")
        
        print("  → Creating Notion page...")
        notion_url = create_notion_page(
            notion_token=notion_token,
            database_id=database_id,
            title=final_title,
            url=f"https://youtu.be/{video_id}",
            one_liner=summary.get("oneLiner", ""),
            takeaways=summary.get("keyTakeaways", []),
            insights=summary.get("insights", [])
        )
        print(f"  ✓ Done → {notion_url}")
        
        # Increment usage (non-critical - don't fail if this errors)
        try:
            increment_usage(user["id"])
        except Exception as usage_err:
            print(f"  ⚠ Usage increment failed (non-critical): {usage_err}")
        
        # Log summary (non-critical)
        try:
            supabase.table("summaries").insert({
                "user_id": user["id"],
                "youtube_url": request.url,
                "title": final_title
            }).execute()
        except Exception as log_err:
            print(f"  ⚠ Summary logging failed (non-critical): {log_err}")
        
        return SummarizeResponse(
            success=True,
            title=final_title,
            notionUrl=notion_url,
            remaining=remaining - 1 if remaining > 0 else -1
        )
        
    except HTTPException:
        raise
    except Exception as e:
        error_msg = str(e)
        print(f"  ✗ Error: {error_msg}")
        
        # Convert technical errors to user-friendly messages
        friendly_error = get_friendly_error(error_msg)
        return SummarizeResponse(success=False, error=friendly_error)


def get_friendly_error(error: str) -> str:
    """Convert technical error messages to user-friendly ones."""
    error_lower = error.lower()
    
    # No subtitles available
    if "subtitles are disabled" in error_lower or "transcriptsdisabled" in error_lower:
        return "This video doesn't have subtitles enabled. The video owner has disabled captions."
    
    if "no subtitles available" in error_lower or "no transcript" in error_lower:
        return "No subtitles available for this video. Try a different video."
    
    # YouTube bot detection
    if "sign in to confirm you're not a bot" in error_lower or "cookies" in error_lower:
        return "Unable to access this video right now. Please try again in a few minutes."
    
    # Invalid URL
    if "invalid" in error_lower and "url" in error_lower:
        return "Invalid YouTube URL. Please paste a valid YouTube link."
    
    if "could not extract video id" in error_lower:
        return "Couldn't recognize this as a YouTube video. Please check the URL."
    
    # Network errors
    if "timeout" in error_lower or "connection" in error_lower:
        return "Connection error. Please check your internet and try again."
    
    # Rate limits
    if "rate limit" in error_lower or "too many requests" in error_lower:
        return "Too many requests. Please wait a moment and try again."
    
    # Default - keep it short
    if len(error) > 100:
        return "Something went wrong. Please try a different video."
    
    return error


# Legacy endpoint for backwards compatibility (no auth required)
@app.post("/summarize/legacy")
async def summarize_legacy(request: SummarizeRequest):
    """Legacy summarize endpoint using environment Notion token."""
    notion_token = os.getenv("NOTION_TOKEN")
    database_id = os.getenv("NOTION_DATABASE_ID")
    
    if not notion_token or not database_id:
        raise HTTPException(status_code=500, detail="Legacy mode not configured")
    
    try:
        video_id = extract_video_id(request.url)
        if not video_id:
            raise HTTPException(status_code=400, detail="Invalid YouTube URL")
        
        transcript, video_title = get_transcript(request.url)
        summary = summarize_with_gemini(transcript)
        final_title = summary.get("title") or video_title
        
        notion_url = create_notion_page(
            notion_token=notion_token,
            database_id=database_id,
            title=final_title,
            url=f"https://youtu.be/{video_id}",
            one_liner=summary.get("oneLiner", ""),
            takeaways=summary.get("keyTakeaways", []),
            insights=summary.get("insights", [])
        )
        
        return SummarizeResponse(success=True, title=final_title, notionUrl=notion_url)
        
    except Exception as e:
        return SummarizeResponse(success=False, error=str(e))


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 3000))
    uvicorn.run(app, host="0.0.0.0", port=port)
