"""
App Configuration Module

Centralized configuration for environment variables and constants.
"""

import os
import logging
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ============ Environment Variables ============

# Gemini API
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
GEMINI_API_ENDPOINT = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

# Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Notion OAuth
NOTION_CLIENT_ID = os.getenv("NOTION_CLIENT_ID")
NOTION_CLIENT_SECRET = os.getenv("NOTION_CLIENT_SECRET")
NOTION_REDIRECT_URI = os.getenv("NOTION_REDIRECT_URI", "https://watchlater.up.railway.app/auth/notion/callback")

# CORS
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# ============ Constants ============

# Tier limits
FREE_TIER_LIMIT = 10
ADMIN_TIER_LIMIT = 100

# Developer overrides (user IDs that get admin-tier limits)
DEVELOPER_USER_IDS = os.getenv("DEVELOPER_USER_IDS", "").split(",")

# Preferred transcript languages (shared across all extraction methods)
PREFERRED_LANGUAGES = [
    'en', 'en-US', 'en-GB',  # English variants
    'ko', 'ko-KR',            # Korean
    'ja',                     # Japanese
    'zh-Hans', 'zh-Hant',     # Chinese
    'es', 'fr', 'de', 'pt'    # European languages
]


# ============ Logging Setup ============

def setup_logging():
    """Configure structured logging for the application."""
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Quiet noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


# ============ Startup Validation ============

def validate_startup():
    """Validate critical configuration at startup."""
    warnings = []
    
    if not GEMINI_API_KEY:
        warnings.append("GEMINI_API_KEY not set - summarization will fail")
    else:
        print("✓ Gemini API key configured")
    
    if not SUPABASE_URL or not SUPABASE_KEY:
        warnings.append("Supabase credentials not set - multi-user mode disabled")
    else:
        print("✓ Supabase configured")
    
    for warning in warnings:
        print(f"⚠ WARNING: {warning}")
    
    return len(warnings) == 0
