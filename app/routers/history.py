"""
History API router.

Provides endpoint for fetching user's summary history with search and pagination.
"""

import logging
from typing import List, Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, Request, Query
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
    title: Optional[str] = None
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
            .select("id, youtube_url, title, notion_url, created_at")
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
