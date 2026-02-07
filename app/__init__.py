"""
App package initialization
"""

from .config import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    GEMINI_API_ENDPOINT,
    SUPABASE_URL,
    SUPABASE_KEY,
    NOTION_CLIENT_ID,
    NOTION_CLIENT_SECRET,
    NOTION_REDIRECT_URI,
    ALLOWED_ORIGINS,
    FREE_TIER_LIMIT,
    ADMIN_TIER_LIMIT,
    DEVELOPER_USER_IDS,
    PREFERRED_LANGUAGES,
    LOG_LEVEL,
    setup_logging,
    validate_startup,
)
