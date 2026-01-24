"""
App Configuration Module

Centralized configuration for environment variables and constants.
"""

import os
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

# ============ Constants ============

# Free tier limits
FREE_TIER_LIMIT = 10

# Preferred transcript languages (shared across all extraction methods)
PREFERRED_LANGUAGES = [
    'en', 'en-US', 'en-GB',  # English variants
    'ko', 'ko-KR',            # Korean
    'ja',                     # Japanese
    'zh-Hans', 'zh-Hant',     # Chinese
    'es', 'fr', 'de', 'pt'    # European languages
]


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
