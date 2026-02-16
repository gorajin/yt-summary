"""
Pydantic models and dataclasses for the YouTube Summary API.
"""

from typing import Optional, List
from enum import Enum
from dataclasses import dataclass, field
from pydantic import BaseModel


# ============ Enums ============

class SourceType(str, Enum):
    """Content source type for extraction routing."""
    YOUTUBE = "youtube"
    ARTICLE = "article"
    PDF = "pdf"
    PODCAST = "podcast"


class ContentType(str, Enum):
    """Content type for optimized processing"""
    LECTURE = "lecture"        # Educational, structured teaching
    INTERVIEW = "interview"    # Podcast, conversation, Q&A
    TUTORIAL = "tutorial"      # How-to, step-by-step instructions
    DOCUMENTARY = "documentary"  # Narrative, historical, investigative
    ARTICLE = "article"        # Written article, blog post
    PAPER = "paper"            # Academic paper, research document
    PODCAST = "podcast"        # Audio podcast episode
    GENERAL = "general"        # Default fallback


# ============ API Request/Response Models ============

class SummarizeRequest(BaseModel):
    url: str
    transcript: Optional[str] = None  # Client-provided transcript (bypasses server fetch)


class IngestRequest(BaseModel):
    """Request to ingest any content source (article, PDF, podcast)."""
    url: str
    source_type: Optional[SourceType] = None  # Auto-detected if not provided
    content: Optional[str] = None  # Pre-extracted text content (e.g., PDF text from client)


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
    
    def to_dict(self) -> dict:
        """Serialize to a JSON-safe dict for Supabase JSONB storage."""
        return {
            "title": self.title,
            "contentType": self.content_type.value,
            "overview": self.overview,
            "tableOfContents": self.table_of_contents,
            "mainConcepts": self.main_concepts,
            "keyInsights": self.key_insights,
            "detailedNotes": self.detailed_notes,
            "notableQuotes": self.notable_quotes,
            "resourcesMentioned": self.resources_mentioned,
            "actionItems": self.action_items,
            "questionsRaised": self.questions_raised,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "LectureNotes":
        """Deserialize from a stored JSON dict."""
        return cls(
            title=data.get("title", "Untitled"),
            content_type=ContentType(data.get("contentType", "general")),
            overview=data.get("overview", ""),
            table_of_contents=data.get("tableOfContents", []),
            main_concepts=data.get("mainConcepts", []),
            key_insights=data.get("keyInsights", []),
            detailed_notes=data.get("detailedNotes", []),
            notable_quotes=data.get("notableQuotes", []),
            resources_mentioned=data.get("resourcesMentioned", []),
            action_items=data.get("actionItems", []),
            questions_raised=data.get("questionsRaised", []),
        )


# ============ Knowledge Map Models ============

@dataclass
class TopicFact:
    """A fact attributed to a topic, traced to a source video."""
    fact: str
    source_video_id: str
    source_title: str


@dataclass
class Topic:
    """A topic node in the knowledge map."""
    name: str
    description: str
    facts: List[TopicFact] = field(default_factory=list)
    related_topics: List[str] = field(default_factory=list)
    video_ids: List[str] = field(default_factory=list)
    importance: int = 5  # 1-10

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "facts": [
                {"fact": f.fact, "sourceVideoId": f.source_video_id, "sourceTitle": f.source_title}
                for f in self.facts
            ],
            "relatedTopics": self.related_topics,
            "videoIds": self.video_ids,
            "importance": self.importance,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Topic":
        return cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            facts=[
                TopicFact(
                    fact=f.get("fact", ""),
                    source_video_id=f.get("sourceVideoId", ""),
                    source_title=f.get("sourceTitle", ""),
                )
                for f in data.get("facts", [])
            ],
            related_topics=data.get("relatedTopics", []),
            video_ids=data.get("videoIds", []),
            importance=data.get("importance", 5),
        )


@dataclass
class TopicConnection:
    """An edge between two topics in the knowledge map."""
    from_topic: str
    to_topic: str
    relationship: str

    def to_dict(self) -> dict:
        return {
            "from": self.from_topic,
            "to": self.to_topic,
            "relationship": self.relationship,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TopicConnection":
        return cls(
            from_topic=data.get("from", ""),
            to_topic=data.get("to", ""),
            relationship=data.get("relationship", ""),
        )


@dataclass
class KnowledgeMap:
    """The complete knowledge map for a user."""
    topics: List[Topic] = field(default_factory=list)
    connections: List[TopicConnection] = field(default_factory=list)
    total_summaries: int = 0
    version: int = 1

    def to_dict(self) -> dict:
        return {
            "topics": [t.to_dict() for t in self.topics],
            "connections": [c.to_dict() for c in self.connections],
            "totalSummaries": self.total_summaries,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "KnowledgeMap":
        return cls(
            topics=[Topic.from_dict(t) for t in data.get("topics", [])],
            connections=[TopicConnection.from_dict(c) for c in data.get("connections", [])],
            total_summaries=data.get("totalSummaries", 0),
            version=data.get("version", 1),
        )

