"""
Third-party transcript API service.

Uses Supadata.ai to reliably extract YouTube transcripts when
youtube-transcript-api and yt-dlp fail due to YouTube's blocking.

Supadata bypasses YouTube's anti-bot measures and provides reliable
transcript extraction with 100 free requests/month.
"""

import os
import urllib.request
import urllib.error
import json
from typing import Optional, Tuple, List
from ..models import TranscriptSegment

# API configuration
SUPADATA_API_KEY = os.getenv("SUPADATA_API_KEY")
SUPADATA_API_URL = "https://api.supadata.ai/v1/youtube/transcript"


def is_available() -> bool:
    """Check if Supadata API is configured."""
    return bool(SUPADATA_API_KEY)


def get_transcript(video_id: str) -> Tuple[List[TranscriptSegment], str, str]:
    """
    Fetch transcript using Supadata API.
    
    Args:
        video_id: YouTube video ID
        
    Returns:
        Tuple of (segments, flat_text, title)
        
    Raises:
        Exception if API call fails
    """
    if not SUPADATA_API_KEY:
        raise Exception("Supadata API key not configured")
    
    print(f"  → Trying Supadata API for: {video_id}")
    
    # Make API request
    url = f"{SUPADATA_API_URL}?url=https://www.youtube.com/watch?v={video_id}"
    
    request = urllib.request.Request(url)
    request.add_header("x-api-key", SUPADATA_API_KEY)
    request.add_header("Accept", "application/json")
    
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            data = json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        error_detail = e.read().decode('utf-8') if e.fp else str(e)
        raise Exception(f"Supadata API error ({e.code}): {error_detail}")
    except urllib.error.URLError as e:
        raise Exception(f"Supadata API connection failed: {e.reason}")
    
    # Parse response
    # Supadata returns: { "content": [{ "text": "...", "offset": 0, "duration": 5 }], ... }
    content = data.get("content", [])
    
    if not content:
        raise Exception("Supadata returned empty transcript")
    
    # Convert to our segment format
    segments = []
    for item in content:
        text = item.get("text", "").strip()
        offset = item.get("offset", 0) / 1000.0  # Convert ms to seconds
        duration = item.get("duration", 0) / 1000.0
        
        if text:
            segments.append(TranscriptSegment(
                text=text,
                start_time=offset,
                end_time=offset + duration
            ))
    
    # Create flat text
    flat_text = ' '.join([s.text for s in segments])
    
    # Supadata doesn't return title, so use placeholder
    title = data.get("title", "")
    
    print(f"  → Supadata SUCCESS: {len(segments)} segments, {len(flat_text)} chars")
    
    return segments, flat_text, title
