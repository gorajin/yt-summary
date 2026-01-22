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
from typing import Optional, List
from datetime import date, datetime
from enum import Enum
from dataclasses import dataclass, field
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


# ============ Lecture Notes Models ============

class ContentType(str, Enum):
    """Video content type for optimized processing"""
    LECTURE = "lecture"        # Educational, structured teaching
    INTERVIEW = "interview"    # Podcast, conversation, Q&A
    TUTORIAL = "tutorial"      # How-to, step-by-step instructions
    DOCUMENTARY = "documentary"  # Narrative, historical, investigative
    GENERAL = "general"        # Default fallback


@dataclass
class TranscriptSegment:
    """A segment of transcript with timestamp"""
    text: str
    start_time: float  # seconds from start
    end_time: float    # seconds from start
    
    def timestamp_str(self) -> str:
        """Format as MM:SS or HH:MM:SS"""
        mins, secs = divmod(int(self.start_time), 60)
        hours, mins = divmod(mins, 60)
        if hours > 0:
            return f"{hours}:{mins:02d}:{secs:02d}"
        return f"{mins}:{secs:02d}"


@dataclass
class LectureNotes:
    """Comprehensive notes structure for any video type"""
    title: str
    content_type: ContentType
    overview: str  # One-liner summary
    
    # Table of contents with timestamps
    table_of_contents: List[dict] = field(default_factory=list)  # [{section, timestamp}]
    
    # Main educational content
    main_concepts: List[dict] = field(default_factory=list)  # [{concept, definition, examples}]
    key_insights: List[dict] = field(default_factory=list)   # [{insight, timestamp, context}]
    detailed_notes: List[dict] = field(default_factory=list) # [{section, content, timestamp}]
    
    # Additional context
    notable_quotes: List[str] = field(default_factory=list)
    resources_mentioned: List[str] = field(default_factory=list)
    action_items: List[str] = field(default_factory=list)
    questions_raised: List[str] = field(default_factory=list)
    
    # Legacy compatibility - for backward-compatible API responses
    def to_legacy_format(self) -> dict:
        """Convert to the old summary format for API compatibility"""
        return {
            "title": self.title,
            "oneLiner": self.overview,
            "keyTakeaways": [
                i.get("insight", str(i)) if isinstance(i, dict) else str(i) 
                for i in self.key_insights[:5]
            ] if self.key_insights else [
                c.get("concept", str(c)) if isinstance(c, dict) else str(c) 
                for c in self.main_concepts[:5]
            ],
            "insights": self.notable_quotes[:3] if self.notable_quotes else []
        }


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
            # Parse the reset timestamp
            if isinstance(reset_at, str):
                reset_date = datetime.fromisoformat(reset_at.replace("Z", "+00:00"))
            else:
                reset_date = reset_at
            
            now = datetime.now(reset_date.tzinfo) if reset_date.tzinfo else datetime.now()
            
            # If reset was in a previous month, reset the counter
            if reset_date.year < now.year or reset_date.month < now.month:
                print(f"  → Resetting monthly usage for user {user_id} (last reset: {reset_date})")
                supabase.table("users").update({
                    "summaries_this_month": 0,
                    "summaries_reset_at": now.isoformat()
                }).eq("id", user_id).execute()
                return FREE_TIER_LIMIT  # Full quota available
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
    """Fetch transcript. Tries youtube-transcript-api first, falls back to yt-dlp.
    
    Supports multiple languages with preference order:
    1. English (manual or auto)
    2. Video's original language (auto-generated)
    3. Translation to English (if available)
    4. yt-dlp fallback with expanded language support
    """
    
    video_id = extract_video_id(url)
    if not video_id:
        raise Exception("Could not extract video ID")
    
    print(f"  → Attempting transcript extraction for video: {video_id}")
    
    # Try youtube-transcript-api first (more reliable on servers)
    try:
        print("  → Trying youtube-transcript-api...")
        from youtube_transcript_api import YouTubeTranscriptApi
        
        # Preferred language order
        preferred_languages = ['en', 'en-US', 'en-GB', 'ko', 'ko-KR', 'ja', 'zh-Hans', 'zh-Hant', 'es', 'fr', 'de', 'pt']
        
        # Try using list_transcripts for better control
        try:
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
            
            # Strategy 1: Try to find transcript in preferred languages
            transcript_data = None
            for lang in preferred_languages:
                try:
                    transcript = transcript_list.find_transcript([lang])
                    transcript_data = transcript.fetch()
                    print(f"  → Found transcript in language: {lang}")
                    break
                except:
                    continue
            
            # Strategy 2: Get ANY available transcript (manual or generated)
            if not transcript_data:
                print("  → No preferred language found, trying any available transcript...")
                try:
                    # Try to get any generated transcript first (often best quality)
                    for transcript in transcript_list:
                        try:
                            transcript_data = transcript.fetch()
                            print(f"  → Using {transcript.language} ({transcript.language_code}) transcript")
                            break
                        except Exception as fetch_err:
                            print(f"  → Failed to fetch {transcript.language_code}: {type(fetch_err).__name__}")
                            continue
                except:
                    pass
            
            # Strategy 3: Try translation to English
            if not transcript_data:
                print("  → Trying translation to English...")
                try:
                    for transcript in transcript_list:
                        if transcript.is_translatable:
                            translated = transcript.translate('en')
                            transcript_data = translated.fetch()
                            print(f"  → Translated from {transcript.language} to English")
                            break
                except Exception as trans_err:
                    print(f"  → Translation failed: {type(trans_err).__name__}")
            
            if transcript_data:
                transcript = ' '.join([entry['text'] for entry in transcript_data])
                transcript = re.sub(r'\s+', ' ', transcript).strip()
                
                title = get_video_title(video_id)
                print(f"  → Got transcript via youtube-transcript-api ({len(transcript)} chars)")
                return transcript, title
                
        except Exception as list_err:
            print(f"  → list_transcripts failed: {type(list_err).__name__}: {list_err}")
        
        # Fallback: Try direct get_transcript with various languages  
        print("  → Trying direct get_transcript...")
        for lang in preferred_languages:
            try:
                transcript_data = YouTubeTranscriptApi.get_transcript(video_id, languages=[lang])
                transcript = ' '.join([entry['text'] for entry in transcript_data])
                transcript = re.sub(r'\s+', ' ', transcript).strip()
                
                title = get_video_title(video_id)
                print(f"  → Got transcript in {lang} ({len(transcript)} chars)")
                return transcript, title
            except:
                continue
        
        print("  → youtube-transcript-api could not get transcript, trying yt-dlp")
            
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
    except (urllib.error.URLError, json.JSONDecodeError, KeyError, TimeoutError):
        return 'Untitled Video'


def get_transcript_ytdlp(url: str) -> tuple:
    """Fetch transcript using yt-dlp (fallback method). Returns (transcript, title)."""
    
    # Expanded language support
    subtitle_langs = ['en', 'en-US', 'en-GB', 'ko', 'ko-KR', 'ja', 'zh-Hans', 'zh-Hant', 'es', 'fr', 'de', 'pt']
    
    ydl_opts = {
        'writesubtitles': True,
        'writeautomaticsub': True,
        'subtitleslangs': subtitle_langs,
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
            for lang in subtitle_langs:
                if lang in subtitles:
                    for fmt in subtitles[lang]:
                        if fmt.get('ext') == 'json3':
                            transcript_url = fmt.get('url')
                            break
                if transcript_url:
                    break
            
            # Fall back to auto-generated
            if not transcript_url:
                for lang in subtitle_langs:
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

def detect_content_type(transcript: str, title: str) -> ContentType:
    """Detect video content type for optimized processing.
    Uses heuristics first, then Gemini for ambiguous cases.
    """
    text_lower = transcript.lower()[:5000]  # Check beginning for patterns
    title_lower = title.lower()
    
    # Tutorial indicators
    tutorial_patterns = [
        "step by step", "how to", "tutorial", "let me show you",
        "follow along", "in this video i'll show", "let's build",
        "coding tutorial", "walkthrough"
    ]
    if any(p in text_lower or p in title_lower for p in tutorial_patterns):
        return ContentType.TUTORIAL
    
    # Interview/podcast indicators
    interview_patterns = [
        "podcast", "interview", "my guest today", "welcome to the show",
        "thanks for having me", "let's talk about", "conversation with",
        "episode", "q&a"
    ]
    if any(p in text_lower or p in title_lower for p in interview_patterns):
        return ContentType.INTERVIEW
    
    # Lecture indicators
    lecture_patterns = [
        "lecture", "class", "lesson", "today we'll learn", "professor",
        "let's examine", "the concept of", "as we discussed",
        "university", "course", "curriculum"
    ]
    if any(p in text_lower or p in title_lower for p in lecture_patterns):
        return ContentType.LECTURE
    
    # Documentary indicators
    documentary_patterns = [
        "documentary", "the story of", "history of", "investigation",
        "the truth about", "behind the scenes", "untold story"
    ]
    if any(p in text_lower or p in title_lower for p in documentary_patterns):
        return ContentType.DOCUMENTARY
    
    return ContentType.GENERAL


def build_lecture_prompt(transcript: str, content_type: ContentType, word_count: int) -> str:
    """Build specialized prompt based on content type."""
    approx_minutes = word_count // 150
    
    # Base context
    context = f"""VIDEO LENGTH: Approximately {approx_minutes} minutes ({word_count:,} words)
CONTENT TYPE: {content_type.value}

TRANSCRIPT:
{transcript}
"""
    
    # Content-type specific instructions
    if content_type == ContentType.LECTURE:
        instructions = """
You are creating comprehensive LECTURE NOTES for a student. Extract:
1. Main concepts with clear definitions
2. Examples and case studies mentioned
3. Key formulas, frameworks, or models
4. Connections between concepts
5. Any recommended readings or resources

Think like a diligent student taking notes - capture EVERYTHING important."""

    elif content_type == ContentType.INTERVIEW:
        instructions = """
You are creating notes from a PODCAST/INTERVIEW. Extract:
1. Key perspectives from each speaker
2. Important quotes (verbatim when possible)
3. Stories and anecdotes shared
4. Advice or recommendations given
5. Books, people, or resources mentioned

Capture the unique insights from this conversation."""

    elif content_type == ContentType.TUTORIAL:
        instructions = """
You are creating a STEP-BY-STEP GUIDE from this tutorial. Extract:
1. Prerequisites or setup required
2. Each step in order with details
3. Commands, code snippets, or specific actions
4. Common mistakes or warnings mentioned
5. Tips and best practices

Make these notes actionable - someone should be able to follow them."""

    elif content_type == ContentType.DOCUMENTARY:
        instructions = """
You are creating notes from a DOCUMENTARY. Extract:
1. Timeline of events or narrative arc
2. Key facts and statistics
3. Important people and their roles
4. Sources or evidence cited
5. Main arguments or conclusions

Capture the story and its supporting evidence."""

    else:  # GENERAL
        instructions = """
You are creating comprehensive NOTES from this video. Extract:
1. Main topic and thesis
2. Key points and supporting details
3. Examples and evidence
4. Notable quotes or statements
5. Any calls to action or recommendations

Be thorough - capture all important information."""

    # Output format specification
    output_format = """
Respond in this EXACT JSON format (no markdown, just raw JSON):
{
  "title": "Clear, descriptive title",
  "contentType": "detected content type",
  "overview": "One comprehensive sentence summarizing the entire content",
  "tableOfContents": [
    {"section": "Section name", "description": "Brief description"}
  ],
  "mainConcepts": [
    {"concept": "Concept name", "definition": "Clear explanation", "examples": ["Example 1", "Example 2"]}
  ],
  "keyInsights": [
    {"insight": "The key insight", "context": "Why this matters or additional context"}
  ],
  "detailedNotes": [
    {"section": "Topic/Section", "points": ["Point 1", "Point 2", "Point 3"]}
  ],
  "notableQuotes": ["Exact or paraphrased quote 1", "Quote 2"],
  "resourcesMentioned": ["Book, website, or tool 1", "Resource 2"],
  "actionItems": ["Action 1", "Action 2"],
  "questionsRaised": ["Open question 1", "Question 2"]
}

GUIDELINES:
- For videos under 15 minutes: 3-5 main concepts, 5-8 insights, 2-3 detailed sections
- For videos 15-45 minutes: 5-8 main concepts, 8-12 insights, 3-5 detailed sections
- For videos 45+ minutes: 8-12 main concepts, 12-20 insights, 5-8 detailed sections
- Capture content from the ENTIRE video, not just the beginning
- Include specific details, numbers, names when mentioned
- Empty arrays are fine if that section doesn't apply
"""

    return context + instructions + output_format


def generate_lecture_notes(transcript: str, title: str = "") -> LectureNotes:
    """Generate comprehensive lecture notes from transcript.
    
    This is the new core summarization engine that produces detailed,
    structured notes suitable for any video type.
    """
    # Gemini 2.0 Flash handles up to ~1M tokens, we use 200k chars (~50k tokens)
    # for better results with very long content
    max_transcript_length = 200000
    transcript_text = transcript[:max_transcript_length]
    word_count = len(transcript_text.split())
    
    # Detect content type
    content_type = detect_content_type(transcript_text, title)
    print(f"  → Detected content type: {content_type.value}")
    
    # Build specialized prompt
    prompt = build_lecture_prompt(transcript_text, content_type, word_count)
    
    # Call Gemini API
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
    
    data = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.3,  # Lower for more factual extraction
            "topP": 0.8,
            "maxOutputTokens": 8192  # Allow longer responses for comprehensive notes
        }
    }
    
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode('utf-8'),
        headers={'Content-Type': 'application/json'},
        method='POST'
    )
    
    # 3 minute timeout for long-form content
    with urllib.request.urlopen(req, timeout=180) as response:
        result = json.loads(response.read().decode('utf-8'))
    
    text = result['candidates'][0]['content']['parts'][0]['text'].strip()
    
    # Clean markdown code blocks if present
    if text.startswith('```'):
        text = re.sub(r'^```json?\n?', '', text)
        text = re.sub(r'\n?```$', '', text)
    
    try:
        data = json.loads(text)
        
        return LectureNotes(
            title=data.get("title", title or "Untitled Notes"),
            content_type=content_type,
            overview=data.get("overview", ""),
            table_of_contents=data.get("tableOfContents", []),
            main_concepts=data.get("mainConcepts", []),
            key_insights=data.get("keyInsights", []),
            detailed_notes=data.get("detailedNotes", []),
            notable_quotes=data.get("notableQuotes", []),
            resources_mentioned=data.get("resourcesMentioned", []),
            action_items=data.get("actionItems", []),
            questions_raised=data.get("questionsRaised", [])
        )
    except json.JSONDecodeError as e:
        print(f"  ⚠ JSON parsing failed: {e}")
        # Return minimal notes on parse failure
        return LectureNotes(
            title=title or "Video Notes",
            content_type=ContentType.GENERAL,
            overview="Notes generation encountered an error",
            key_insights=[{"insight": "Could not parse AI response", "context": str(e)}]
        )


def summarize_with_gemini(transcript: str) -> dict:
    """Legacy summarization function - now uses generate_lecture_notes internally.
    
    Maintained for backward compatibility with existing API.
    Returns the old format: {title, oneLiner, keyTakeaways, insights}
    """
    notes = generate_lecture_notes(transcript)
    return notes.to_legacy_format()


# ============ Notion Functions ============

def create_notion_page(notion_token: str, database_id: str, title: str, url: str, 
                       one_liner: str, takeaways: list, insights: list) -> str:
    """Create a Notion page with the summary using user's token.
    Legacy function kept for backward compatibility."""
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


def create_lecture_notes_page(notion_token: str, database_id: str, 
                               notes: LectureNotes, video_url: str) -> str:
    """Create a comprehensive Notion page with rich lecture notes formatting.
    
    Uses toggle blocks for collapsible sections, callouts for key insights,
    and organized structure based on content type.
    """
    notion = NotionClient(auth=notion_token)
    
    # Content type icons
    type_icons = {
        ContentType.LECTURE: "📚",
        ContentType.INTERVIEW: "🎙️",
        ContentType.TUTORIAL: "🔧",
        ContentType.DOCUMENTARY: "🎬",
        ContentType.GENERAL: "📝"
    }
    
    children = []
    
    # 1. Overview callout
    children.append({
        "object": "block",
        "type": "callout",
        "callout": {
            "rich_text": [{"type": "text", "text": {"content": notes.overview}}],
            "icon": {"emoji": type_icons.get(notes.content_type, "📝")},
            "color": "blue_background"
        }
    })
    
    # 2. Table of Contents (if available)
    if notes.table_of_contents:
        children.append({"object": "block", "type": "divider", "divider": {}})
        children.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": "📑 Table of Contents"}}]}
        })
        for item in notes.table_of_contents[:10]:  # Limit to 10 sections
            section = item.get("section", "") if isinstance(item, dict) else str(item)
            desc = item.get("description", "") if isinstance(item, dict) else ""
            text = f"{section}: {desc}" if desc else section
            children.append({
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": text}}]}
            })
    
    # 3. Main Concepts (toggle blocks for expandable content)
    if notes.main_concepts:
        children.append({"object": "block", "type": "divider", "divider": {}})
        children.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🧠 Main Concepts"}}]}
        })
        for concept in notes.main_concepts[:12]:  # Limit to 12 concepts
            if isinstance(concept, dict):
                concept_name = concept.get("concept", "Concept")
                definition = concept.get("definition", "")
                examples = concept.get("examples", [])
                
                # Create toggle block with concept as header
                toggle_content = []
                if definition:
                    toggle_content.append({
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {"rich_text": [{"type": "text", "text": {"content": definition}}]}
                    })
                for ex in examples[:3]:  # Max 3 examples per concept
                    toggle_content.append({
                        "object": "block",
                        "type": "bulleted_list_item",
                        "bulleted_list_item": {"rich_text": [
                            {"type": "text", "text": {"content": "Example: ", "annotations": {"bold": True}}},
                            {"type": "text", "text": {"content": str(ex)}}
                        ]}
                    })
                
                children.append({
                    "object": "block",
                    "type": "toggle",
                    "toggle": {
                        "rich_text": [
                            {"type": "text", "text": {"content": f"📌 {concept_name}", "annotations": {"bold": True}}}
                        ],
                        "children": toggle_content if toggle_content else [
                            {"object": "block", "type": "paragraph", "paragraph": {"rich_text": []}}
                        ]
                    }
                })
            else:
                children.append({
                    "object": "block",
                    "type": "bulleted_list_item",
                    "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": str(concept)}}]}
                })
    
    # 4. Key Insights (callouts for emphasis)
    if notes.key_insights:
        children.append({"object": "block", "type": "divider", "divider": {}})
        children.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": "💡 Key Insights"}}]}
        })
        for insight in notes.key_insights[:15]:  # Limit to 15 insights
            if isinstance(insight, dict):
                insight_text = insight.get("insight", str(insight))
                context = insight.get("context", "")
                full_text = f"{insight_text}\n{context}" if context else insight_text
            else:
                full_text = str(insight)
            
            children.append({
                "object": "block",
                "type": "callout",
                "callout": {
                    "rich_text": [{"type": "text", "text": {"content": full_text}}],
                    "icon": {"emoji": "💡"},
                    "color": "yellow_background"
                }
            })
    
    # 5. Detailed Notes (organized by section)
    if notes.detailed_notes:
        children.append({"object": "block", "type": "divider", "divider": {}})
        children.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": "📝 Detailed Notes"}}]}
        })
        for section in notes.detailed_notes[:8]:  # Limit to 8 sections
            if isinstance(section, dict):
                section_name = section.get("section", "Section")
                points = section.get("points", [])
                
                children.append({
                    "object": "block",
                    "type": "heading_3",
                    "heading_3": {"rich_text": [{"type": "text", "text": {"content": section_name}}]}
                })
                for point in points[:10]:  # Max 10 points per section
                    children.append({
                        "object": "block",
                        "type": "bulleted_list_item",
                        "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": str(point)}}]}
                    })
    
    # 6. Notable Quotes
    if notes.notable_quotes:
        children.append({"object": "block", "type": "divider", "divider": {}})
        children.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": "💬 Notable Quotes"}}]}
        })
        for quote in notes.notable_quotes[:8]:
            children.append({
                "object": "block",
                "type": "quote",
                "quote": {"rich_text": [{"type": "text", "text": {"content": str(quote)}}]}
            })
    
    # 7. Resources Mentioned
    if notes.resources_mentioned:
        children.append({"object": "block", "type": "divider", "divider": {}})
        children.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🔗 Resources Mentioned"}}]}
        })
        for resource in notes.resources_mentioned[:10]:
            children.append({
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": str(resource)}}]}
            })
    
    # 8. Action Items
    if notes.action_items:
        children.append({"object": "block", "type": "divider", "divider": {}})
        children.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": "✅ Action Items"}}]}
        })
        for action in notes.action_items[:8]:
            children.append({
                "object": "block",
                "type": "to_do",
                "to_do": {
                    "rich_text": [{"type": "text", "text": {"content": str(action)}}],
                    "checked": False
                }
            })
    
    # 9. Questions Raised
    if notes.questions_raised:
        children.append({"object": "block", "type": "divider", "divider": {}})
        children.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": "❓ Questions to Explore"}}]}
        })
        for question in notes.questions_raised[:5]:
            children.append({
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": str(question)}}]}
            })
    
    # Notion has a limit of 100 blocks per request - truncate if needed
    if len(children) > 100:
        children = children[:99]
        children.append({
            "object": "block",
            "type": "callout",
            "callout": {
                "rich_text": [{"type": "text", "text": {"content": "Notes truncated due to length. View the video for complete content."}}],
                "icon": {"emoji": "⚠️"},
                "color": "gray_background"
            }
        })
    
    response = notion.pages.create(
        parent={"database_id": database_id},
        properties={
            "Title": {"title": [{"text": {"content": notes.title}}]},
            "url": {"url": video_url},
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
        
        print("  → Generating lecture notes with Gemini...")
        notes = generate_lecture_notes(transcript, video_title)
        print(f"  → Generated: {notes.title} (type: {notes.content_type.value})")
        
        print("  → Creating Notion page with rich formatting...")
        notion_url = create_lecture_notes_page(
            notion_token=notion_token,
            database_id=database_id,
            notes=notes,
            video_url=f"https://youtu.be/{video_id}"
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
                "title": notes.title
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


# Legacy endpoint - DEPRECATED
@app.post("/summarize/legacy")
async def summarize_legacy(request: SummarizeRequest):
    """Legacy summarize endpoint - DEPRECATED. Use authenticated /summarize instead."""
    raise HTTPException(
        status_code=410, 
        detail="This endpoint has been deprecated. Please use the WatchLater iOS app with authentication."
    )


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 3000))
    uvicorn.run(app, host="0.0.0.0", port=port)
