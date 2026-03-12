"""
Summarize API router.

Provides the /summarize endpoint for processing YouTube videos asynchronously.
Jobs are created immediately and processed in the background.
"""

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address

import asyncio
import uuid

from ..models import SummarizeRequest, SummarizeResponse, IngestRequest, BatchSummarizeRequest, TranscriptSegment, SourceType, SummaryFormat
from ..services.youtube import extract_video_id, extract_playlist_id, get_playlist_video_ids, get_transcript_with_timestamps
from ..services.gemini import process_long_transcript
from ..services.notion import create_lecture_notes_page
from ..services.jobs import create_job, update_job, JobStatus
from .auth import get_current_user, check_rate_limit, increment_usage, supabase

logger = logging.getLogger(__name__)

router = APIRouter(tags=["summarize"])

# Rate limiter for abuse prevention
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
    video_id: str,
    summary_format: SummaryFormat = SummaryFormat.DETAILED,
    language: str = "en"
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
        notes = process_long_transcript(
            segments=segments,
            title=video_title,
            video_id=video_id,
            summary_format=summary_format,
            language=language
        )
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
                video_id=video_id,
                summary_format=summary_format.value,
                language=language
            )
        else:
            logger.info(f"Job {job_id[:8]}: Notion not connected, skipping")
            await update_job(job_id, progress=90, stage="Saving summary")
        
        # Increment usage (non-critical)
        try:
            increment_usage(user["id"])
        except Exception as usage_err:
            logger.warning(f"Job {job_id[:8]}: Usage increment failed: {usage_err}")
        
        # Persist summary with full content for export and in-app reading
        summary_id = None
        try:
            summary_data = {
                "user_id": user["id"],
                "youtube_url": url,
                "video_id": video_id,
                "title": notes.title,
                "overview": notes.overview,
                "content_type": notes.content_type.value if notes.content_type else None,
                "summary_json": notes.to_dict(),
                "notion_url": notion_url,
                "source_type": "youtube",
                "summary_format": summary_format.value,
                "language": language,
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
@limiter.limit("10/minute")
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
        
        # Spawn tracked background task (errors are logged, task is drained on shutdown)
        from main import track_background_task
        track_background_task(
            process_summarization_job(
                job_id=job.id,
                user=user,
                url=body.url,
                transcript=body.transcript,
                video_id=video_id,
                summary_format=body.summary_format,
                language=body.language
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
    summary_format: SummaryFormat = SummaryFormat.DETAILED,
    language: str = "en"
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
        notes = process_long_transcript(
            segments=segments,
            title=title,
            video_id="",
            summary_format=summary_format,
            language=language
        )
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
                video_id="",
                summary_format=summary_format.value,
                language=language
            )
        else:
            await update_job(job_id, progress=90, stage="Saving summary")
        
        # Increment usage (non-critical)
        try:
            increment_usage(user["id"])
        except Exception as usage_err:
            logger.warning(f"Job {job_id[:8]}: Usage increment failed: {usage_err}")

        # Store in Supabase
        summary_id = None
        try:
            summary_data = {
                "user_id": user["id"],
                "youtube_url": url,
                "title": notes.title,
                "overview": notes.overview,
                "content_type": detected_type.value,
                "summary_json": notes.to_dict(),
                "notion_url": notion_url,
                "source_type": source_type.value,
                "source_url": url,
                "summary_format": summary_format.value,
                "language": language,
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
@limiter.limit("10/minute")
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
        
        from main import track_background_task
        track_background_task(
            process_ingest_job(
                job_id=job.id,
                user=user,
                url=body.url,
                source_type=source_type,
                content=body.content,
                summary_format=body.summary_format,
                language=body.language
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


# ============ Batch / Playlist Summarization (Pro-only) ============

# Semaphore to limit concurrent Gemini calls within a batch
_batch_semaphore = asyncio.Semaphore(5)


async def _process_batch_child(
    job_id: str, user: dict, url: str, video_id: str,
    summary_format: SummaryFormat, language: str
):
    """Wrapper that acquires the semaphore before processing a single video."""
    async with _batch_semaphore:
        await process_summarization_job(
            job_id=job_id, user=user, url=url,
            transcript=None, video_id=video_id,
            summary_format=summary_format, language=language
        )


@router.post("/batch-summarize")
@limiter.limit("5/minute")
async def batch_summarize(
    request: Request,
    body: BatchSummarizeRequest,
    user: dict = Depends(get_current_user),
):
    """Create batch summarization jobs for multiple videos or a playlist (Pro-only).

    Accepts either a list of YouTube URLs or a playlist URL.
    Returns immediately with a batch_id and individual job IDs for polling.
    """
    # Gate behind Pro subscription
    tier = user.get("subscription_tier", "free")
    if tier not in ("pro", "lifetime", "admin"):
        raise HTTPException(
            status_code=403,
            detail="Batch summarization requires a Pro subscription. Upgrade in Settings."
        )

    try:
        # Resolve video URLs
        video_urls = list(body.urls or [])
        if body.playlist_url:
            playlist_id = extract_playlist_id(body.playlist_url)
            if not playlist_id:
                raise HTTPException(status_code=400, detail="Invalid playlist URL")
            video_ids = get_playlist_video_ids(body.playlist_url, max_videos=50)
            video_urls.extend(f"https://youtu.be/{vid}" for vid in video_ids)

        if not video_urls:
            raise HTTPException(status_code=400, detail="No videos to process")
        if len(video_urls) > 50:
            video_urls = video_urls[:50]

        # Validate all URLs and create jobs
        batch_id = str(uuid.uuid4())
        child_jobs = []

        for url in video_urls:
            vid = extract_video_id(url)
            if not vid:
                logger.warning(f"Batch {batch_id[:8]}: Skipping invalid URL: {url}")
                continue

            job = await create_job(user["id"], url)
            child_jobs.append({"job_id": job.id, "video_id": vid, "url": url})

        if not child_jobs:
            raise HTTPException(status_code=400, detail="No valid YouTube URLs found")

        # Store batch metadata in a parent job
        parent_job = await create_job(user["id"], f"batch:{batch_id}")
        await update_job(
            parent_job.id,
            status=JobStatus.PROCESSING,
            progress=0,
            stage=f"Processing 0/{len(child_jobs)} videos",
            result={
                "batch_id": batch_id,
                "child_job_ids": [c["job_id"] for c in child_jobs],
                "total": len(child_jobs),
            }
        )

        logger.info(f"Batch {batch_id[:8]}: Created {len(child_jobs)} jobs for user {user['id']}")

        # Spawn child tasks with concurrency control
        from main import track_background_task
        for child in child_jobs:
            track_background_task(
                _process_batch_child(
                    job_id=child["job_id"],
                    user=user,
                    url=child["url"],
                    video_id=child["video_id"],
                    summary_format=body.summary_format or SummaryFormat.DETAILED,
                    language=body.language or "en",
                )
            )

        return JSONResponse(
            status_code=202,
            content={
                "batch_id": parent_job.id,
                "total": len(child_jobs),
                "jobs": [{"job_id": c["job_id"], "url": c["url"]} for c in child_jobs],
                "message": f"Batch of {len(child_jobs)} videos queued for processing.",
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating batch: {e}")
        raise HTTPException(status_code=500, detail=get_friendly_error(str(e)))


@router.get("/batch-status/{batch_id}")
@limiter.limit("60/minute")
async def get_batch_status(
    batch_id: str,
    request: Request,
    user: dict = Depends(get_current_user),
):
    """Get aggregated status of a batch summarization job.

    Returns overall progress plus individual job statuses.
    """
    from ..services.jobs import get_job

    parent = await get_job(batch_id)
    if not parent or parent.user_id != user["id"]:
        raise HTTPException(status_code=404, detail="Batch not found")

    batch_result = parent.result or {}
    child_ids = batch_result.get("child_job_ids", [])
    total = batch_result.get("total", len(child_ids))

    completed = 0
    failed = 0
    jobs_status = []

    for cid in child_ids:
        child = await get_job(cid)
        if not child:
            continue
        status_info = {
            "job_id": cid,
            "url": child.youtube_url,
            "status": child.status.value,
            "progress": child.progress,
            "title": child.result.get("title") if child.result else None,
            "error": child.error,
        }
        jobs_status.append(status_info)
        if child.status == JobStatus.COMPLETE:
            completed += 1
        elif child.status == JobStatus.FAILED:
            failed += 1

    all_done = (completed + failed) >= total
    overall_status = "complete" if all_done else "processing"
    overall_progress = int((completed + failed) / max(total, 1) * 100)

    return {
        "batch_id": batch_id,
        "status": overall_status,
        "progress": overall_progress,
        "total": total,
        "completed": completed,
        "failed": failed,
        "stage": f"Completed {completed}/{total} videos" if all_done else f"Processing {completed}/{total} videos",
        "jobs": jobs_status,
    }
