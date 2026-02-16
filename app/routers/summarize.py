"""
Summarize API router.

Provides the /summarize endpoint for processing YouTube videos asynchronously.
Jobs are created immediately and processed in the background.
"""

import asyncio
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import JSONResponse

from ..models import SummarizeRequest, SummarizeResponse, IngestRequest, TranscriptSegment, SourceType
from ..services.youtube import extract_video_id, get_transcript_with_timestamps
from ..services.gemini import process_long_transcript
from ..services.notion import create_lecture_notes_page
from ..services.jobs import create_job, update_job, JobStatus
from .auth import get_current_user, check_rate_limit, increment_usage, supabase

logger = logging.getLogger(__name__)

router = APIRouter(tags=["summarize"])


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
    
    # PoToken enforcement (YouTube 2026+)
    if "potoken" in error_lower or "authentication token" in error_lower:
        return "This video has restricted captions that require additional verification. Please try a different video."
    
    # Multiple empty responses = PoToken enforcement
    if "multiple empty responses" in error_lower:
        return "This video's captions are protected. Please try a different video."
    
    if len(error) > 100:
        return "Something went wrong. Please try a different video."
    
    return error


async def process_summarization_job(
    job_id: str,
    user: dict,
    url: str,
    transcript: Optional[str],
    video_id: str
):
    """Background task to process a summarization job.
    
    Updates job progress at each stage for client polling.
    """
    try:
        notion_token = user.get("notion_access_token")
        database_id = user.get("notion_database_id")
        
        # Stage 1: Transcript (0-25%)
        await update_job(job_id, status=JobStatus.PROCESSING, progress=5, stage="Fetching transcript")
        
        # Check for client extraction failure signal
        # "__SERVER_EXTRACT__" means client tried and failed (likely PoToken enforcement)
        client_extraction_failed = transcript == "__SERVER_EXTRACT__"
        
        if transcript and not client_extraction_failed:
            logger.info(f"Job {job_id[:8]}: Using client-provided transcript")
            segments = [TranscriptSegment(text=transcript, start_time=0, end_time=0)]
            video_title = None
            await update_job(job_id, progress=25, stage="Transcript received")
        else:
            if client_extraction_failed:
                logger.info(f"Job {job_id[:8]}: Client extraction failed, attempting server-side")
            else:
                logger.info(f"Job {job_id[:8]}: No transcript provided, fetching server-side")
            segments, transcript, video_title = get_transcript_with_timestamps(url)
            await update_job(job_id, progress=25, stage="Transcript extracted")
        
        logger.info(f"Job {job_id[:8]}: Got {len(segments)} segments ({len(transcript)} chars)")
        
        # Stage 2: Analysis (25-50%)
        await update_job(job_id, progress=30, stage="Analyzing content")
        
        # Stage 3: Summarization (50-85%) - longest stage
        await update_job(job_id, progress=50, stage="Generating summary")
        logger.info(f"Job {job_id[:8]}: Generating lecture notes")
        notes = process_long_transcript(segments, video_title, video_id)
        await update_job(job_id, progress=85, stage="Summary complete")
        logger.info(f"Job {job_id[:8]}: Generated: {notes.title}")
        
        # Stage 4: Notion (85-100%) — only if user has Notion connected
        notion_url = None
        if notion_token and database_id:
            await update_job(job_id, progress=90, stage="Saving to Notion")
            logger.info(f"Job {job_id[:8]}: Creating Notion page")
            notion_url = create_lecture_notes_page(
                notion_token=notion_token,
                database_id=database_id,
                notes=notes,
                video_url=f"https://youtu.be/{video_id}",
                video_id=video_id
            )
        else:
            logger.info(f"Job {job_id[:8]}: Notion not connected, skipping")
            await update_job(job_id, progress=90, stage="Saving summary")
        
        # Increment usage (non-critical)
        try:
            increment_usage(user["id"])
        except Exception as usage_err:
            logger.warning(f"Job {job_id[:8]}: Usage increment failed: {usage_err}")
        
        # Log summary with full content (non-critical)
        summary_id = None
        try:
            summary_data = {
                "user_id": user["id"],
                "youtube_url": url,
                "video_id": video_id,
                "title": notes.title,
                "overview": notes.overview,
                "content_type": notes.content_type.value,
                "summary_json": notes.to_dict(),
                "notion_url": notion_url,
                "source_type": "youtube",
            }
            result = supabase.table("summaries").insert(summary_data).execute()
            if result.data:
                summary_id = result.data[0].get("id")
        except Exception as log_err:
            logger.warning(f"Job {job_id[:8]}: Summary logging failed: {log_err}")
        
        # Complete!
        await update_job(
            job_id,
            status=JobStatus.COMPLETE,
            progress=100,
            stage="Complete",
            result={
                "success": True,
                "title": notes.title,
                "notionUrl": notion_url,
                "summaryId": summary_id,
            }
        )
        logger.info(f"Job {job_id[:8]}: Complete → notion={notion_url}, id={summary_id}")
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Job {job_id[:8]}: Failed: {error_msg}")
        friendly_error = get_friendly_error(error_msg)
        await update_job(
            job_id,
            status=JobStatus.FAILED,
            progress=0,
            stage="Failed",
            error=friendly_error
        )


@router.post("/summarize")
async def summarize(request: Request, body: SummarizeRequest, user: dict = Depends(get_current_user)):
    """Create a summarization job (authenticated).
    
    Returns immediately with a job_id. Poll /status/{job_id} for progress.
    This async approach prevents timeouts for long videos (2+ hours).
    
    NOTE: Transcript is preferred from client (bypasses IP blocking).
    If client fails, server-side extraction via youtube-transcript-api is used as fallback.
    """
    # Validate: transcript is optional, server will fall back if not provided
    # (Client-side extraction is preferred but may fail due to YouTube changes)
    
    try:
        # Check user-level rate limit (monthly quota)
        remaining = check_rate_limit(user)
        
        # Validate URL
        video_id = extract_video_id(body.url)
        if not video_id:
            raise HTTPException(status_code=400, detail="Invalid YouTube URL")
        
        # Create job
        job = await create_job(user["id"], body.url)
        logger.info(f"Created job {job.id[:8]} for user {user['id']}: {body.url}")
        
        # Spawn background task
        asyncio.create_task(
            process_summarization_job(
                job_id=job.id,
                user=user,
                url=body.url,
                transcript=body.transcript,
                video_id=video_id
            )
        )
        
        # Return immediately with job ID (HTTP 202 Accepted)
        return JSONResponse(
            status_code=202,
            content={
                "job_id": job.id,
                "status": "pending",
                "message": "Job created. Poll /status/{job_id} for progress.",
                "remaining": remaining - 1 if remaining > 0 else -1
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error creating job: {error_msg}")
        raise HTTPException(status_code=500, detail=get_friendly_error(error_msg))


async def process_ingest_job(
    job_id: str,
    user: dict,
    url: str,
    source_type: SourceType,
    content: Optional[str] = None,
):
    """Background task to process a non-YouTube content ingestion job."""
    from ..services.extractors import extract_content
    
    try:
        notion_token = user.get("notion_access_token")
        database_id = user.get("notion_database_id")
        
        # Stage 1: Extract content (0-30%)
        await update_job(job_id, status=JobStatus.PROCESSING, progress=5, stage="Extracting content")
        segments, title, detected_type = extract_content(url, source_type=source_type, content=content)
        await update_job(job_id, progress=30, stage="Content extracted")
        logger.info(f"Job {job_id[:8]}: Extracted {len(segments)} segments from {detected_type.value}")
        
        # Stage 2: Summarization (30-85%)
        await update_job(job_id, progress=40, stage="Generating summary")
        notes = process_long_transcript(segments, title, video_id="")
        await update_job(job_id, progress=85, stage="Summary complete")
        logger.info(f"Job {job_id[:8]}: Generated: {notes.title}")
        
        # Stage 3: Notion (85-95%) — only if connected
        notion_url = None
        if notion_token and database_id:
            await update_job(job_id, progress=90, stage="Saving to Notion")
            notion_url = create_lecture_notes_page(
                notion_token=notion_token,
                database_id=database_id,
                notes=notes,
                video_url=url,
                video_id=""
            )
        else:
            await update_job(job_id, progress=90, stage="Saving summary")
        
        # Increment usage
        try:
            increment_usage(user["id"])
        except Exception:
            pass
        
        # Store in Supabase
        summary_id = None
        try:
            summary_data = {
                "user_id": user["id"],
                "youtube_url": url,  # Reusing column for any source URL
                "video_id": None,
                "title": notes.title,
                "overview": notes.overview,
                "content_type": notes.content_type.value,
                "summary_json": notes.to_dict(),
                "notion_url": notion_url,
                "source_type": detected_type.value,
                "source_url": url,
            }
            result = supabase.table("summaries").insert(summary_data).execute()
            if result.data:
                summary_id = result.data[0].get("id")
        except Exception as log_err:
            logger.warning(f"Job {job_id[:8]}: Summary logging failed: {log_err}")
        
        await update_job(
            job_id,
            status=JobStatus.COMPLETE,
            progress=100,
            stage="Complete",
            result={
                "success": True,
                "title": notes.title,
                "notionUrl": notion_url,
                "summaryId": summary_id,
                "sourceType": detected_type.value,
            }
        )
        logger.info(f"Job {job_id[:8]}: Complete → type={detected_type.value}, id={summary_id}")
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Job {job_id[:8]}: Failed: {error_msg}")
        await update_job(
            job_id,
            status=JobStatus.FAILED,
            progress=0,
            stage="Failed",
            error=get_friendly_error(error_msg)
        )


@router.post("/ingest")
async def ingest(request: Request, body: IngestRequest, user: dict = Depends(get_current_user)):
    """Ingest any content source (article, PDF, podcast).
    
    Returns immediately with a job_id. Poll /status/{job_id} for progress.
    """
    try:
        remaining = check_rate_limit(user)
        
        # Auto-detect source type if not provided
        from ..services.extractors import detect_source_type
        source_type = body.source_type or detect_source_type(body.url)
        
        if source_type == SourceType.YOUTUBE:
            raise HTTPException(status_code=400, detail="Use /summarize for YouTube videos")
        
        if source_type == SourceType.PODCAST:
            raise HTTPException(status_code=400, detail="Podcast support is coming soon")
        
        # Create job
        job = await create_job(user["id"], body.url)
        logger.info(f"Created ingest job {job.id[:8]}: type={source_type.value}, url={body.url}")
        
        asyncio.create_task(
            process_ingest_job(
                job_id=job.id,
                user=user,
                url=body.url,
                source_type=source_type,
                content=body.content,
            )
        )
        
        return JSONResponse(
            status_code=202,
            content={
                "job_id": job.id,
                "status": "pending",
                "source_type": source_type.value,
                "message": "Job created. Poll /status/{job_id} for progress.",
                "remaining": remaining - 1 if remaining > 0 else -1
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error creating ingest job: {error_msg}")
        raise HTTPException(status_code=500, detail=get_friendly_error(error_msg))
