"""
Knowledge Map synthesis service.

Second-pass AI agent that analyzes all of a user's summaries and produces
a cross-video topic graph with facts, connections, and importance scores.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from ..config import SUPABASE_URL, SUPABASE_KEY
from ..models import KnowledgeMap, Topic, TopicConnection, TopicFact
from .gemini import call_gemini_api

logger = logging.getLogger(__name__)


# ============ Supabase Helpers ============

def _get_supabase():
    """Get a Supabase client, or None if not configured."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None
    try:
        from supabase import create_client
        return create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        logger.error(f"Failed to create Supabase client: {e}")
        return None


# ============ Summary Condensation ============

def _condense_summary(summary: dict) -> dict:
    """Extract the essential fields from a summary for the knowledge map prompt.
    
    Works with the actual summaries table schema:
    id, youtube_url, title, notion_url, created_at
    """
    # Extract video ID from youtube_url if possible
    video_id = ""
    yt_url = summary.get("youtube_url", "")
    if "v=" in yt_url:
        video_id = yt_url.split("v=")[1].split("&")[0]
    elif "youtu.be/" in yt_url:
        video_id = yt_url.split("youtu.be/")[1].split("?")[0]
    
    return {
        "videoId": video_id,
        "title": summary.get("title") or "Untitled",
        "youtubeUrl": yt_url,
    }


# ============ Gemini Prompt ============

KNOWLEDGE_MAP_SYSTEM_PROMPT = """You are a Knowledge Synthesis Agent. Your job is to analyze a collection of
video summaries and create a structured knowledge map that reveals the topics,
key information, and connections across all the content.

INPUT: A list of video summaries, each containing a title, overview, key
insights, and main concepts.

OUTPUT: A JSON object with this EXACT structure (no markdown, no code fences):
{
  "topics": [
    {
      "name": "Topic Name",
      "description": "2-3 sentence description of what this topic covers across the videos",
      "facts": [
        {"fact": "Key fact or insight", "sourceVideoId": "video_id_here", "sourceTitle": "Video Title"}
      ],
      "relatedTopics": ["Other Topic Name"],
      "videoIds": ["video1", "video2"],
      "importance": 8
    }
  ],
  "connections": [
    {"from": "Topic A", "to": "Topic B", "relationship": "builds on"}
  ]
}

RULES:
1. Extract 5-20 distinct topics depending on the breadth of content
2. Topics should be specific enough to be useful (e.g., "React Server Components" not just "Programming")
3. Each fact MUST trace back to a specific source video using its videoId and title
4. Importance score (1-10): based on how many videos discuss the topic × depth of coverage
5. Connections should be meaningful relationships (e.g., "builds on", "contrasts with", "prerequisite for", "applies to")
6. Merge near-duplicate topics (e.g., "React" and "React.js" → one topic)
7. Include both domain-specific topics AND cross-cutting themes
8. If there's only 1 video, create 3-5 topics based on its content
9. Sort topics by importance (highest first)
10. Return ONLY the JSON object, no other text"""


MERGE_PROMPT = """You are a Knowledge Synthesis Agent. Merge these two partial knowledge maps into one unified map.

Partial Map 1:
{map1}

Partial Map 2:
{map2}

MERGE RULES:
1. Combine duplicate topics (same or very similar names) → merge their facts and video lists
2. Keep all unique topics from both maps
3. Update importance scores based on the combined coverage
4. Merge and deduplicate connections
5. Ensure no duplicate facts
6. Return the unified map in the same JSON format

Return ONLY the merged JSON object, no other text."""


# ============ Core Functions ============

async def build_knowledge_map(user_id: str, supabase_client=None) -> KnowledgeMap:
    """Build a complete knowledge map from all of a user's summaries.
    
    Fetches all summaries, condenses them, sends to Gemini for synthesis,
    and persists the result.
    
    Args:
        user_id: The user's ID
        supabase_client: Optional Supabase client (created if not provided)
    
    Returns:
        The generated KnowledgeMap
    """
    client = supabase_client or _get_supabase()
    if not client:
        raise RuntimeError("Supabase not available for knowledge map build")
    
    # Fetch all summaries for this user
    logger.info(f"Building knowledge map for user {user_id}")
    result = client.table("summaries").select(
        "id, youtube_url, title, notion_url, created_at"
    ).eq("user_id", user_id).order(
        "created_at", desc=True
    ).execute()
    
    summaries = result.data or []
    if not summaries:
        logger.warning(f"No summaries found for user {user_id}")
        return KnowledgeMap(total_summaries=0)
    
    logger.info(f"Found {len(summaries)} summaries for knowledge map")
    
    # Condense summaries for the prompt
    condensed = [_condense_summary(s) for s in summaries]
    
    # Build the knowledge map via Gemini
    if len(condensed) <= 40:
        knowledge_map = await _synthesize_single_batch(condensed)
    else:
        knowledge_map = await _synthesize_chunked(condensed)
    
    knowledge_map.total_summaries = len(summaries)
    
    # Persist to Supabase
    await _persist_knowledge_map(client, user_id, knowledge_map)
    
    return knowledge_map


async def _synthesize_single_batch(condensed: list) -> KnowledgeMap:
    """Process all summaries in a single Gemini call."""
    prompt = f"""{KNOWLEDGE_MAP_SYSTEM_PROMPT}

Here are {len(condensed)} video summaries to analyze:

{json.dumps(condensed, indent=2)}"""
    
    response = await asyncio.to_thread(call_gemini_api, prompt, 3, 120)
    return _parse_knowledge_map_response(response)


async def _synthesize_chunked(condensed: list) -> KnowledgeMap:
    """Process large summary collections by chunking and merging.
    
    Splits into groups of 20, builds partial maps, then merges them.
    """
    chunk_size = 20
    chunks = [condensed[i:i + chunk_size] for i in range(0, len(condensed), chunk_size)]
    logger.info(f"Chunking {len(condensed)} summaries into {len(chunks)} groups")
    
    partial_maps = []
    for i, chunk in enumerate(chunks):
        logger.info(f"Processing chunk {i + 1}/{len(chunks)} ({len(chunk)} summaries)")
        prompt = f"""{KNOWLEDGE_MAP_SYSTEM_PROMPT}

Here are {len(chunk)} video summaries to analyze (batch {i + 1} of {len(chunks)}):

{json.dumps(chunk, indent=2)}"""
        
        response = await asyncio.to_thread(call_gemini_api, prompt, 3, 120)
        partial_map = _parse_knowledge_map_response(response)
        partial_maps.append(partial_map)
    
    # Merge partial maps pairwise
    while len(partial_maps) > 1:
        merged = []
        for i in range(0, len(partial_maps), 2):
            if i + 1 < len(partial_maps):
                logger.info(f"Merging partial maps {i + 1} and {i + 2}")
                combined = await _merge_maps(partial_maps[i], partial_maps[i + 1])
                merged.append(combined)
            else:
                merged.append(partial_maps[i])
        partial_maps = merged
    
    return partial_maps[0]


async def _merge_maps(map1: KnowledgeMap, map2: KnowledgeMap) -> KnowledgeMap:
    """Merge two partial knowledge maps using Gemini."""
    prompt = MERGE_PROMPT.format(
        map1=json.dumps(map1.to_dict(), indent=2),
        map2=json.dumps(map2.to_dict(), indent=2),
    )
    
    response = await asyncio.to_thread(call_gemini_api, prompt, 3, 120)
    return _parse_knowledge_map_response(response)


def _parse_knowledge_map_response(response: dict) -> KnowledgeMap:
    """Parse Gemini's response into a KnowledgeMap dataclass.
    
    Handles both direct JSON and text-wrapped JSON responses.
    """
    # Extract the text content from Gemini response
    text = ""
    if isinstance(response, dict):
        candidates = response.get("candidates", [])
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            if parts:
                text = parts[0].get("text", "")
    
    if not text:
        logger.error("Empty response from Gemini for knowledge map")
        return KnowledgeMap()
    
    # Clean up response — strip markdown code fences if present
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first and last lines (code fences)
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        text = text.strip()
    
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse knowledge map JSON: {e}\nResponse: {text[:500]}")
        return KnowledgeMap()
    
    return KnowledgeMap.from_dict(data)


async def _persist_knowledge_map(client, user_id: str, knowledge_map: KnowledgeMap):
    """Upsert the knowledge map into Supabase."""
    try:
        # Check if a map already exists
        existing = client.table("knowledge_maps").select("id, version").eq(
            "user_id", user_id
        ).execute()
        
        now = datetime.now(timezone.utc).isoformat()
        map_data = knowledge_map.to_dict()
        
        if existing.data:
            # Update existing
            new_version = existing.data[0].get("version", 0) + 1
            knowledge_map.version = new_version
            map_data["version"] = new_version
            
            client.table("knowledge_maps").update({
                "map_json": map_data,
                "version": new_version,
                "summary_count": knowledge_map.total_summaries,
                "updated_at": now,
            }).eq("user_id", user_id).execute()
            
            logger.info(f"Updated knowledge map for user {user_id} (v{new_version})")
        else:
            # Insert new
            client.table("knowledge_maps").insert({
                "user_id": user_id,
                "map_json": map_data,
                "version": 1,
                "summary_count": knowledge_map.total_summaries,
            }).execute()
            
            logger.info(f"Created knowledge map for user {user_id}")
    except Exception as e:
        logger.error(f"Failed to persist knowledge map: {e}")


async def get_knowledge_map(user_id: str, supabase_client=None) -> Optional[dict]:
    """Retrieve a user's knowledge map from the database.
    
    Returns the map data with an `is_stale` flag if the user has added
    summaries since the last build.
    """
    client = supabase_client or _get_supabase()
    if not client:
        return None
    
    try:
        result = client.table("knowledge_maps").select(
            "map_json, version, summary_count, notion_url, updated_at"
        ).eq("user_id", user_id).execute()
        
        if not result.data:
            return None
        
        row = result.data[0]
        map_data = row["map_json"]
        
        # Check staleness: count current summaries
        count_result = client.table("summaries").select(
            "id", count="exact"
        ).eq("user_id", user_id).execute()
        
        current_count = count_result.count if hasattr(count_result, "count") else len(count_result.data or [])
        
        return {
            "map": map_data,
            "version": row["version"],
            "notionUrl": row.get("notion_url"),
            "updatedAt": row["updated_at"],
            "summaryCount": row["summary_count"],
            "currentSummaryCount": current_count,
            "isStale": current_count > row["summary_count"],
        }
    except Exception as e:
        logger.error(f"Failed to retrieve knowledge map: {e}")
        return None


async def update_notion_url(user_id: str, notion_url: str, supabase_client=None):
    """Update the Notion URL for a user's knowledge map."""
    client = supabase_client or _get_supabase()
    if not client:
        return
    
    try:
        client.table("knowledge_maps").update({
            "notion_url": notion_url,
        }).eq("user_id", user_id).execute()
    except Exception as e:
        logger.error(f"Failed to update knowledge map notion_url: {e}")
