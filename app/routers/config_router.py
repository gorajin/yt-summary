"""
Configuration router.

Provides dynamic configuration for iOS client, allowing server-side
updates to extraction patterns without App Store updates.
"""

from fastapi import APIRouter
from pydantic import BaseModel
from typing import List


router = APIRouter(tags=["config"])


class ExtractionConfig(BaseModel):
    """Configuration for YouTube transcript extraction."""
    version: int
    user_agent: str
    caption_track_patterns: List[str]
    pot_token_patterns: List[str]


# Current extraction configuration
# Update these when YouTube changes their HTML structure
CURRENT_CONFIG = ExtractionConfig(
    version=1,
    user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    caption_track_patterns=[
        # Pattern 1: baseUrl comes before languageCode
        r'"baseUrl"\s*:\s*"([^"]+)".*?"languageCode"\s*:\s*"([^"]+)"',
        # Pattern 2: languageCode comes before baseUrl
        r'"languageCode"\s*:\s*"([^"]+)".*?"baseUrl"\s*:\s*"([^"]+)"',
    ],
    pot_token_patterns=[
        r'"pot"\s*:\s*"([^"]+)"',
        r'"poToken"\s*:\s*"([^"]+)"',
        r'pot=([^&"]+)',
    ]
)


@router.get("/config/extraction", response_model=ExtractionConfig)
async def get_extraction_config():
    """Get current extraction configuration.
    
    iOS clients should fetch this on launch and cache locally.
    When extraction fails, refetch to get updated patterns.
    
    Returns regex patterns for:
    - Caption track extraction
    - Pot token extraction
    - Recommended User-Agent string
    """
    return CURRENT_CONFIG
