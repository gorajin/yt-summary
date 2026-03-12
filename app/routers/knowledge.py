"""
Knowledge Map API router.

Provides endpoints for building, retrieving, sharing, and updating
a user's cross-video knowledge map.
"""

import logging
import secrets
from fastapi import APIRouter, Depends, Request, HTTPException, Query
from slowapi import Limiter
from slowapi.util import get_remote_address

from .auth import get_current_user, supabase
from ..services.knowledge_map import (
    build_knowledge_map,
    get_knowledge_map,
    update_notion_url,
)
from ..services.jobs import create_job, update_job, JobStatus

logger = logging.getLogger(__name__)

router = APIRouter(tags=["knowledge"])

# Rate limiter
limiter = Limiter(key_func=get_remote_address)


@router.get("/knowledge-map")
@limiter.limit("30/minute")
async def get_map(request: Request, user: dict = Depends(get_current_user)):
    """Get the user's knowledge map.
    
    Returns the map data with staleness info, or null if no map exists.
    """
    user_id = user["id"]
    
    result = await get_knowledge_map(user_id)
    
    if not result:
        return {"knowledgeMap": None, "isStale": True, "message": "No knowledge map built yet"}
    
    return {
        "knowledgeMap": result["map"],
        "version": result["version"],
        "notionUrl": result.get("notionUrl"),
        "updatedAt": result["updatedAt"],
        "summaryCount": result["summaryCount"],
        "currentSummaryCount": result["currentSummaryCount"],
        "isStale": result["isStale"],
    }


@router.post("/knowledge-map/build")
@limiter.limit("5/hour")
async def build_map(request: Request, user: dict = Depends(get_current_user)):
    """Trigger a full knowledge map rebuild.
    
    Creates an async job (same pattern as /summarize) and returns
    a job_id for polling via /status/{job_id}.
    """
    import uuid
    user_id = user["id"]
    
    # Create a job for tracking (without youtube_url since this isn't a video job)
    job_id = str(uuid.uuid4())
    try:
        supabase.table("jobs").insert({
            "id": job_id,
            "user_id": user_id,
            "youtube_url": "knowledge-map-build",
            "status": "pending",
            "progress": 0,
            "stage": "queued",
        }).execute()
    except Exception as e:
        logger.error(f"Job creation failed for knowledge map build: {e}")
        raise HTTPException(status_code=500, detail="Failed to start knowledge map build")

    # Run the build in a tracked background task
    from main import track_background_task
    track_background_task(_build_map_job(job_id, user_id, user))

    return {"jobId": job_id, "message": "Knowledge map build started"}


async def _build_map_job(job_id: str, user_id: str, user: dict):
    """Background task for building the knowledge map."""
    try:
        await update_job(job_id, status=JobStatus.PROCESSING, progress=10, stage="Gathering summaries...")
        
        knowledge_map = await build_knowledge_map(user_id)
        
        if not knowledge_map.topics:
            await update_job(
                job_id,
                status=JobStatus.COMPLETE,
                progress=100,
                result={"knowledgeMap": knowledge_map.to_dict(), "message": "No topics found"},
            )
            return
        
        await update_job(job_id, progress=70, stage="Building knowledge map...")
        
        # Optionally create Notion page
        notion_url = None
        notion_token = user.get("notion_access_token")
        notion_db_id = user.get("notion_database_id")
        
        if notion_token and notion_db_id:
            try:
                await update_job(job_id, progress=85, stage="Saving to Notion...")
                from ..services.notion import create_knowledge_map_page
                notion_url = create_knowledge_map_page(
                    notion_token=notion_token,
                    database_id=notion_db_id,
                    knowledge_map=knowledge_map,
                )
                if notion_url:
                    await update_notion_url(user_id, notion_url)
            except Exception as e:
                logger.error(f"Failed to create Notion knowledge map page: {e}")
        
        await update_job(
            job_id,
            status=JobStatus.COMPLETE,
            progress=100,
            stage="Done!",
            result={
                "knowledgeMap": knowledge_map.to_dict(),
                "notionUrl": notion_url,
                "topicCount": len(knowledge_map.topics),
                "connectionCount": len(knowledge_map.connections),
            },
        )
        
        logger.info(
            f"Knowledge map built for user {user_id}: "
            f"{len(knowledge_map.topics)} topics, "
            f"{len(knowledge_map.connections)} connections"
        )
        
    except Exception as e:
        logger.error(f"Knowledge map build failed for user {user_id}: {e}")
        await update_job(
            job_id,
            status=JobStatus.FAILED,
            error=f"Failed to build knowledge map: {str(e)}",
        )


# ============ Sharing ============


@router.post("/knowledge-map/share")
@limiter.limit("10/hour")
async def share_map(request: Request, user: dict = Depends(get_current_user)):
    """Generate a shareable link for the user's knowledge map.

    Creates a unique share_token and returns a public URL.
    Subsequent calls return the existing token without regenerating.
    """
    user_id = user["id"]

    try:
        # Check if map exists
        existing = (
            supabase.table("knowledge_maps")
            .select("id, share_token, map_json")
            .eq("user_id", user_id)
            .execute()
        )

        if not existing.data:
            raise HTTPException(status_code=404, detail="No knowledge map to share. Build one first.")

        row = existing.data[0]

        # Return existing token if already shared
        if row.get("share_token"):
            share_url = f"{_get_web_app_url()}/shared/{row['share_token']}"
            return {"shareToken": row["share_token"], "shareUrl": share_url}

        # Generate a new share token
        share_token = secrets.token_urlsafe(16)

        supabase.table("knowledge_maps").update(
            {"share_token": share_token}
        ).eq("id", row["id"]).execute()

        share_url = f"{_get_web_app_url()}/shared/{share_token}"
        logger.info(f"Knowledge map shared for user {user_id}: {share_token[:8]}...")

        return {"shareToken": share_token, "shareUrl": share_url}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error sharing knowledge map: {e}")
        raise HTTPException(status_code=500, detail="Failed to share knowledge map")


@router.get("/knowledge-map/shared/{share_token}")
@limiter.limit("60/minute")
async def get_shared_map(share_token: str, request: Request):
    """Get a publicly shared knowledge map (no auth required).

    Returns the map data for viewing purposes.
    """
    try:
        result = (
            supabase.table("knowledge_maps")
            .select("map_json, updated_at")
            .eq("share_token", share_token)
            .execute()
        )

        if not result.data:
            raise HTTPException(status_code=404, detail="Shared map not found or link has expired")

        row = result.data[0]
        map_json = row.get("map_json", {})

        return {
            "knowledgeMap": map_json,
            "updatedAt": row.get("updated_at"),
            "isShared": True,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching shared map: {e}")
        raise HTTPException(status_code=500, detail="Failed to load shared map")


# ============ Topic Deep-Dive ============


@router.get("/knowledge-map/topic/{topic_name}")
@limiter.limit("30/minute")
async def get_topic_summaries(
    topic_name: str,
    request: Request,
    user: dict = Depends(get_current_user),
):
    """Get all summaries related to a specific topic in the knowledge map.

    Looks up the topic's video_ids in the map, then fetches matching summaries.
    """
    user_id = user["id"]

    try:
        # Get the knowledge map
        map_result = (
            supabase.table("knowledge_maps")
            .select("map_json")
            .eq("user_id", user_id)
            .execute()
        )

        if not map_result.data:
            raise HTTPException(status_code=404, detail="No knowledge map found")

        map_json = map_result.data[0].get("map_json", {})
        topics = map_json.get("topics", [])

        # Find the topic
        matching_topic = None
        for t in topics:
            if t.get("name", "").lower() == topic_name.lower():
                matching_topic = t
                break

        if not matching_topic:
            raise HTTPException(status_code=404, detail=f"Topic '{topic_name}' not found")

        video_ids = matching_topic.get("videoIds", [])

        if not video_ids:
            return {"topic": matching_topic, "summaries": []}

        # Fetch summaries for these video IDs
        summaries_result = (
            supabase.table("summaries")
            .select("id, youtube_url, video_id, title, overview, content_type, created_at")
            .eq("user_id", user_id)
            .is_("deleted_at", "null")
            .in_("video_id", video_ids)
            .order("created_at", desc=True)
            .execute()
        )

        return {
            "topic": matching_topic,
            "summaries": summaries_result.data if summaries_result.data else [],
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching topic summaries: {e}")
        raise HTTPException(status_code=500, detail="Failed to load topic summaries")


def _get_web_app_url() -> str:
    """Get the web app URL from config or default."""
    import os
    return os.environ.get("WEB_APP_URL", "https://watchlater.app")
