"""
Knowledge Map API router.

Provides endpoints for building, retrieving, and updating
a user's cross-video knowledge map.
"""

import asyncio
import logging
from fastapi import APIRouter, Depends, Request, HTTPException
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
    user_id = user["id"]
    
    # Create a job for tracking
    job = await create_job(user_id=user_id)
    job_id = job.id
    
    # Run the build in the background
    asyncio.create_task(_build_map_job(job_id, user_id, user))
    
    return {"jobId": job_id, "message": "Knowledge map build started"}


async def _build_map_job(job_id: str, user_id: str, user: dict):
    """Background task for building the knowledge map."""
    try:
        await update_job(job_id, status=JobStatus.PROCESSING, progress=10, stage="Gathering summaries...")
        
        knowledge_map = await build_knowledge_map(user_id)
        
        if not knowledge_map.topics:
            await update_job(
                job_id,
                status=JobStatus.COMPLETED,
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
            status=JobStatus.COMPLETED,
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
