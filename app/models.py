"""
Pydantic models and dataclasses for the YouTube Summary API.
"""

from typing import Optional, List
from enum import Enum
from dataclasses import dataclass, field
from pydantic import BaseModel


# ============ API Request/Response Models ============

class SummarizeRequest(BaseModel):
    url: str
    transcript: Optional[str] = None  # Client-provided transcript (bypasses server fetch)


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
