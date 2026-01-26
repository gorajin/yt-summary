"""
Summarize API router.

Provides the main /summarize endpoint for processing YouTube videos.
"""

from fastapi import APIRouter, HTTPException, Depends, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from ..models import SummarizeRequest, SummarizeResponse
from ..services.youtube import extract_video_id, get_transcript_with_timestamps
from ..services.gemini import process_long_transcript
from ..services.notion import create_lecture_notes_page
from .auth import get_current_user, check_rate_limit, increment_usage, supabase


router = APIRouter(tags=["summarize"])

# Rate limiter for abuse prevention (per-IP)
# These limits are generous for normal users but prevent abuse
limiter = Limiter(key_func=get_remote_address)


def get_friendly_error(error: str) -> str:
    """Convert technical error messages to user-friendly ones."""
    error_lower = error.lower()
    
    if "subtitles are disabled" in error_lower or "transcriptsdisabled" in error_lower:
        return "This video doesn't have subtitles enabled. The video owner has disabled captions."
    
    if "no subtitles available" in error_lower or "no transcript" in error_lower:
        return "No subtitles available for this video. Try a different video."
    
    if "sign in to confirm you're not a bot" in error_lower or "cookies" in error_lower:
        return "Unable to access this video right now. Please try again in a few minutes."
    
    if "invalid" in error_lower and "url" in error_lower:
        return "Invalid YouTube URL. Please paste a valid YouTube link."
    
    if "could not extract video id" in error_lower:
        return "Couldn't recognize this as a YouTube video. Please check the URL."
    
    if "timeout" in error_lower or "connection" in error_lower:
        return "Connection error. Please check your internet and try again."
    
    if "rate limit" in error_lower or "too many requests" in error_lower:
        return "Too many requests. Please wait a moment and try again."
    
    if len(error) > 100:
        return "Something went wrong. Please try a different video."
    
    return error


@router.post("/summarize", response_model=SummarizeResponse)
@limiter.limit("60/minute")  # Generous limit - user quota is the real protection
async def summarize(request: Request, body: SummarizeRequest, user: dict = Depends(get_current_user)):
    """Create a summary (authenticated).
    
    Rate limited to 60 requests per minute per IP. This is generous because:
    - User quota (monthly limit) is the real abuse protection
    - Mobile networks often share IPs causing false positives
    - Processing takes 10-30s anyway, natural rate limiting
    """
    try:
        # Check user-level rate limit (monthly quota)
        remaining = check_rate_limit(user)
        
        # Check Notion is connected
        notion_token = user.get("notion_access_token")
        database_id = user.get("notion_database_id")
        
        if not notion_token or not database_id:
            raise HTTPException(status_code=400, detail="Please connect your Notion first")
        
        # Validate URL
        video_id = extract_video_id(body.url)
        if not video_id:
            raise HTTPException(status_code=400, detail="Invalid YouTube URL")
        
        # Process video
        print(f"Processing for user {user['id']}: {body.url}")
        
        print("  → Fetching timestamped transcript...")
        segments, transcript, video_title = get_transcript_with_timestamps(body.url)
        print(f"  → Got {len(segments)} segments ({len(transcript)} chars)")
        
        print("  → Generating lecture notes (auto-detects long videos)...")
        notes = process_long_transcript(segments, video_title, video_id)
        print(f"  → Generated: {notes.title} (type: {notes.content_type.value})")
        
        print("  → Creating Notion page with rich formatting...")
        notion_url = create_lecture_notes_page(
            notion_token=notion_token,
            database_id=database_id,
            notes=notes,
            video_url=f"https://youtu.be/{video_id}",
            video_id=video_id
        )
        print(f"  ✓ Done → {notion_url}")
        
        # Increment usage (non-critical)
        try:
            increment_usage(user["id"])
        except Exception as usage_err:
            print(f"  ⚠ Usage increment failed (non-critical): {usage_err}")
        
        # Log summary (non-critical)
        try:
            supabase.table("summaries").insert({
                "user_id": user["id"],
                "youtube_url": body.url,
                "title": notes.title,
                "notion_url": notion_url  # Store for history feature
            }).execute()
        except Exception as log_err:
            print(f"  ⚠ Summary logging failed (non-critical): {log_err}")
        
        return SummarizeResponse(
            success=True,
            title=notes.title,
            notionUrl=notion_url,
            remaining=remaining - 1 if remaining > 0 else -1
        )
        
    except HTTPException:
        raise
    except Exception as e:
        error_msg = str(e)
        print(f"  ✗ Error: {error_msg}")
        
        friendly_error = get_friendly_error(error_msg)
        return SummarizeResponse(success=False, error=friendly_error)


@router.post("/summarize/legacy")
async def summarize_legacy(body: SummarizeRequest):
    """Legacy summarize endpoint - DEPRECATED. Use authenticated /summarize instead."""
    raise HTTPException(
        status_code=410, 
        detail="This endpoint has been deprecated. Please use the WatchLater iOS app with authentication."
    )
