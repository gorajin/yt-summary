"""
History API router.

Provides endpoint for fetching user's summary history with search and pagination,
and individual summary detail with full content for in-app reading.
"""

import logging
from typing import List, Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, Request, Query, HTTPException
from slowapi import Limiter
from slowapi.util import get_remote_address

from .auth import get_current_user, supabase

logger = logging.getLogger(__name__)

router = APIRouter(tags=["history"])

# Rate limiter for abuse prevention
limiter = Limiter(key_func=get_remote_address)


class SummaryItem(BaseModel):
    """A summary history item."""
    id: str
    youtube_url: str
    video_id: Optional[str] = None
    title: Optional[str] = None
    overview: Optional[str] = None
    content_type: Optional[str] = None
    source_type: Optional[str] = None
    source_url: Optional[str] = None
    notion_url: Optional[str] = None
    created_at: str


class SummaryDetail(BaseModel):
    """Full summary detail with content for in-app reading."""
    id: str
    youtube_url: str
    video_id: Optional[str] = None
    title: Optional[str] = None
    overview: Optional[str] = None
    content_type: Optional[str] = None
    source_type: Optional[str] = None
    source_url: Optional[str] = None
    summary_json: Optional[dict] = None
    notion_url: Optional[str] = None
    created_at: str


@router.get("/summaries")
@limiter.limit("30/minute")
async def get_summaries(
    request: Request,
    user: dict = Depends(get_current_user),
    q: Optional[str] = Query(None, description="Search by title"),
    after: Optional[str] = Query(None, description="Filter: created after ISO date"),
    before: Optional[str] = Query(None, description="Filter: created before ISO date"),
    limit: int = Query(50, ge=1, le=100, description="Max results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
):
    """Get user's summary history with optional search and date filtering."""
    try:
        query = (
            supabase.table("summaries")
            .select("id, youtube_url, video_id, title, overview, content_type, source_type, source_url, notion_url, created_at")
            .eq("user_id", user["id"])
            .is_("deleted_at", "null")
        )
        
        # Apply search filter
        if q:
            query = query.ilike("title", f"%{q}%")
        
        # Apply date filters
        if after:
            query = query.gte("created_at", after)
        if before:
            query = query.lte("created_at", before)
        
        # Ordering and pagination
        query = query.order("created_at", desc=True).range(offset, offset + limit - 1)
        
        result = query.execute()
        return result.data if result.data else []
        
    except Exception as e:
        logger.error(f"Error fetching summaries: {e}")
        return []


@router.get("/summaries/{summary_id}")
@limiter.limit("60/minute")
async def get_summary_detail(
    summary_id: str,
    request: Request,
    user: dict = Depends(get_current_user),
):
    """Get full summary detail including content for in-app reading."""
    try:
        result = (
            supabase.table("summaries")
            .select("id, youtube_url, video_id, title, overview, content_type, source_type, source_url, summary_json, notion_url, created_at")
            .eq("id", summary_id)
            .eq("user_id", user["id"])
            .is_("deleted_at", "null")
            .execute()
        )
        
        if not result.data:
            raise HTTPException(status_code=404, detail="Summary not found")
        
        return result.data[0]
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching summary {summary_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch summary")


@router.get("/summaries/{summary_id}/export")
@limiter.limit("30/minute")
async def export_summary_endpoint(
    summary_id: str,
    request: Request,
    user: dict = Depends(get_current_user),
    format: str = Query("markdown", description="Export format: markdown, html, text"),
):
    """Export a summary in the requested format for Obsidian, Apple Notes, etc."""
    from fastapi.responses import Response
    from ..services.exporters.formats import export_summary
    
    try:
        # Fetch the full summary
        result = (
            supabase.table("summaries")
            .select("id, youtube_url, video_id, title, overview, content_type, source_type, source_url, summary_json, notion_url, created_at")
            .eq("id", summary_id)
            .eq("user_id", user["id"])
            .is_("deleted_at", "null")
            .execute()
        )
        
        if not result.data:
            raise HTTPException(status_code=404, detail="Summary not found")
        
        summary = result.data[0]
        
        if not summary.get("summary_json"):
            raise HTTPException(status_code=404, detail="No content available for export (legacy summary)")
        
        try:
            content, content_type = export_summary(summary, fmt=format, video_id=summary.get("video_id"))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        
        # Build filename
        # Build filename — sanitize for safe download
        import re as _re
        title_slug = _re.sub(r'[^\w\s-]', '', (summary.get("title") or "summary"))[:50].strip().replace(" ", "_")
        if not title_slug:
            title_slug = "summary"
        ext_map = {"markdown": "md", "md": "md", "html": "html", "text": "txt", "txt": "txt"}
        ext = ext_map.get(format.lower(), "txt")
        filename = f"{title_slug}.{ext}"
        
        return Response(
            content=content,
            media_type=content_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error exporting summary {summary_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to export summary")
