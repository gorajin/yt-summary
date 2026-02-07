"""
Configuration router.

Provides dynamic configuration for iOS client, allowing server-side
updates to extraction patterns without App Store updates.
"""

import logging
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import List

from .auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(tags=["config"])


class ExtractionPattern(BaseModel):
    """A regex pattern for extracting YouTube data."""
    name: str
    pattern: str
    description: str = ""


class ExtractionConfig(BaseModel):
    """Dynamic extraction configuration for the iOS client."""
    version: str
    caption_track_patterns: List[ExtractionPattern]
    user_agents: List[str]


@router.get("/config/extraction")
async def get_extraction_config(user: dict = Depends(get_current_user)):
    """Get current extraction patterns for iOS client.
    
    Requires authentication to prevent scraping of extraction strategies.
    """
    return ExtractionConfig(
        version="2.2.0",
        caption_track_patterns=[
            ExtractionPattern(
                name="innertube_captions",
                pattern=r'"captions":\s*\{.*?"captionTracks":\s*(\[.*?\])',
                description="Extract caption tracks from innertube response"
            ),
            ExtractionPattern(
                name="timedtext_url",
                pattern=r'"baseUrl":\s*"(https://www\.youtube\.com/api/timedtext[^"]*)"',
                description="Extract timedtext API URLs"
            ),
            ExtractionPattern(
                name="pot_token",
                pattern=r'"poToken":\s*"([^"]+)"',
                description="Extract proof-of-origin token"
            ),
        ],
        user_agents=[
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        ]
    )
