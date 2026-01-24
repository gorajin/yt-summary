"""
History API router.

Provides endpoint for fetching user's summary history.
"""

from typing import List, Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from .auth import get_current_user, supabase


router = APIRouter(tags=["history"])

# Rate limiter for abuse prevention
limiter = Limiter(key_func=get_remote_address)


class SummaryHistoryItem(BaseModel):
    id: str
    youtube_url: str
    title: Optional[str]
    notion_url: Optional[str]
    created_at: str


@router.get("/summaries", response_model=List[SummaryHistoryItem])
@limiter.limit("30/minute")  # 30 requests per minute - very generous for history
async def get_summaries(request: Request, user: dict = Depends(get_current_user)):
    """Get user's summary history.
    
    Rate limited to 30 requests per minute per IP.
    """
    result = supabase.table("summaries")\
        .select("id, youtube_url, title, notion_url, created_at")\
        .eq("user_id", user["id"])\
        .order("created_at", desc=True)\
        .limit(50)\
        .execute()
    
    return [
        SummaryHistoryItem(
            id=item["id"],
            youtube_url=item["youtube_url"],
            title=item.get("title"),
            notion_url=item.get("notion_url"),
            created_at=item["created_at"]
        )
        for item in (result.data or [])
    ]

