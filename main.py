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

# Initialize Supabase
supabase: SupabaseClient = None
if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

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
        raise HTTPException(status_code=401, detail="Authorization header required")
    
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization format")
    
    token = authorization.replace("Bearer ", "")
    
    try:
        # Verify token with Supabase
        user_response = supabase.auth.get_user(token)
        if not user_response.user:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        # Get user profile from our users table
        user_id = user_response.user.id
        result = supabase.table("users").select("*").eq("id", user_id).single().execute()
        
        if not result.data:
            # Create user profile if doesn't exist
            new_user = {
                "id": user_id,
                "email": user_response.user.email,
                "subscription_tier": "free",
                "summaries_this_month": 0,
            }
            supabase.table("users").insert(new_user).execute()
            return new_user
        
        return result.data
    except Exception as e:
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
    supabase.rpc("increment_summaries", {"user_id": user_id}).execute()


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
    """Fetch transcript using yt-dlp. Returns (transcript, title)."""
    
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
    if not NOTION_CLIENT_SECRET:
        raise HTTPException(status_code=500, detail="Notion OAuth not configured")
    
    # Extract user_id from state
    user_id = state.split(":")[0]
    
    # Exchange code for token
    token_url = "https://api.notion.com/v1/oauth/token"
    
    import base64
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
    
    with urllib.request.urlopen(req) as response:
        token_data = json.loads(response.read().decode('utf-8'))
    
    access_token = token_data.get("access_token")
    workspace_name = token_data.get("workspace_name")
    
    # Find or create database for user
    notion = NotionClient(auth=access_token)
    
    # Search for existing database
    search_results = notion.search(filter={"property": "object", "value": "database"}).get("results", [])
    
    database_id = None
    for db in search_results:
        title = db.get("title", [{}])[0].get("plain_text", "")
        if "YouTube" in title or "Watch" in title or "Summary" in title:
            database_id = db["id"]
            break
    
    # Update user in database
    supabase.table("users").update({
        "notion_access_token": access_token,
        "notion_database_id": database_id,
        "notion_workspace": workspace_name
    }).eq("id", user_id).execute()
    
    # Redirect to app with success
    return RedirectResponse(url=f"watchlater://notion-connected?success=true")


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
        
        # Increment usage
        increment_usage(user["id"])
        
        # Log summary
        supabase.table("summaries").insert({
            "user_id": user["id"],
            "youtube_url": request.url,
            "title": final_title
        }).execute()
        
        return SummarizeResponse(
            success=True,
            title=final_title,
            notionUrl=notion_url,
            remaining=remaining - 1 if remaining > 0 else -1
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"  ✗ Error: {str(e)}")
        return SummarizeResponse(success=False, error=str(e))


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
