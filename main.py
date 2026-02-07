"""
YouTube Summary API - Multi-User Version (Modularized)

FastAPI backend with Supabase auth, Notion OAuth, and user-specific summaries.

This is the entry point that composes all modular components.
For detailed implementation, see:
- app/services/ - YouTube, Gemini, Notion services
- app/routers/ - API endpoints
- app/config.py - Environment configuration
"""

import os
import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from app.config import ALLOWED_ORIGINS, validate_startup, setup_logging
from app.routers import auth, summarize, history, status, config_router

logger = logging.getLogger(__name__)

# Initialize rate limiter
limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown events."""
    # Startup
    setup_logging()
    validate_startup()
    
    # Start periodic job cleanup (every hour)
    cleanup_task = asyncio.create_task(_periodic_job_cleanup())
    logger.info("Started periodic job cleanup task")
    
    yield
    
    # Shutdown
    cleanup_task.cancel()
    logger.info("Application shutting down")


async def _periodic_job_cleanup():
    """Periodically clean up old jobs (every hour)."""
    from app.services.jobs import cleanup_old_jobs
    while True:
        try:
            await asyncio.sleep(3600)  # 1 hour
            count = await cleanup_old_jobs(max_age_hours=24)
            if count > 0:
                logger.info(f"Cleaned up {count} old jobs")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Job cleanup error: {e}")


# Initialize FastAPI app
app = FastAPI(
    title="YouTube Summary API",
    version="2.2.0",
    description="Summarize YouTube videos and save to Notion",
    lifespan=lifespan,
)

# Add rate limiter to app state
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS configuration
# Note: iOS apps don't send Origin headers the same way browsers do,
# so we need permissive settings for mobile app compatibility.
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS if ALLOWED_ORIGINS != ["*"] else ["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# Include routers
app.include_router(auth.router)
app.include_router(summarize.router)
app.include_router(history.router)
app.include_router(status.router)
app.include_router(config_router.router)


@app.get("/")
@limiter.limit("60/minute")
async def health(request: Request):
    """Health check endpoint."""
    return {"status": "ok", "service": "YouTube Summary API", "version": "2.2.0"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 3000))
    uvicorn.run(app, host="0.0.0.0", port=port)
