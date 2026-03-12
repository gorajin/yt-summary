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
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from app.config import ALLOWED_ORIGINS, validate_startup, setup_logging
from app.routers import auth, summarize, history, status, config_router, knowledge

logger = logging.getLogger(__name__)

# Initialize rate limiter
limiter = Limiter(key_func=get_remote_address)

# Track in-flight background tasks so we can drain them on shutdown
_background_tasks: set[asyncio.Task] = set()


def track_background_task(coro) -> asyncio.Task:
    """Create a tracked background task with automatic error handling.

    Unlike bare asyncio.create_task(), this:
    - Logs unhandled exceptions instead of silently dropping them
    - Registers the task for graceful shutdown draining
    """
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    task.add_done_callback(_log_task_exception)
    return task


def _log_task_exception(task: asyncio.Task):
    """Log unhandled exceptions from background tasks."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc:
        logger.error(f"Background task failed with unhandled exception: {exc}", exc_info=exc)


# ============ Security Middleware ============

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to every response."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = "default-src 'self'; frame-ancestors 'none'"
        return response


MAX_REQUEST_BODY_SIZE = 10_485_760  # 10 MB


class RequestBodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject request bodies that exceed the configured size limit."""

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > MAX_REQUEST_BODY_SIZE:
            return JSONResponse(
                status_code=413,
                content={"detail": f"Request body too large. Maximum size is {MAX_REQUEST_BODY_SIZE // (1024 * 1024)} MB."},
            )
        return await call_next(request)


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

    # Shutdown: cancel periodic task
    cleanup_task.cancel()

    # Drain in-flight background jobs (wait up to 30s)
    if _background_tasks:
        logger.info(f"Waiting for {len(_background_tasks)} in-flight background tasks to finish...")
        done, pending = await asyncio.wait(_background_tasks, timeout=30)
        if pending:
            logger.warning(f"Force-cancelling {len(pending)} background tasks after 30s timeout")
            for t in pending:
                t.cancel()

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
    version="3.6.0",
    description="Summarize YouTube videos and save to Notion",
    lifespan=lifespan,
)

# Add rate limiter to app state
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Security middleware (outermost — added first so it wraps everything)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestBodySizeLimitMiddleware)

# CORS configuration
# Note: iOS apps don't send Origin headers the same way browsers do,
# so we need permissive settings for mobile app compatibility.
# In production, set ALLOWED_ORIGINS to specific origins (e.g. your Railway domain).
if ALLOWED_ORIGINS == ["*"]:
    logger.warning("CORS allows ALL origins — set ALLOWED_ORIGINS in production")
    # Wildcard + credentials violates CORS spec and exposes JWTs to any origin.
    # Bearer-token auth does not require credentials mode.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

# Include routers
app.include_router(auth.router)
app.include_router(summarize.router)
app.include_router(history.router)
app.include_router(status.router)
app.include_router(config_router.router)
app.include_router(knowledge.router)


@app.get("/")
@limiter.limit("60/minute")
async def root(request: Request):
    """Root endpoint."""
    return {"status": "ok", "service": "YouTube Summary API", "version": "3.6.0"}


@app.get("/health")
async def health_check():
    """Dedicated health check endpoint for PaaS platforms (Railway, etc.)."""
    return {"status": "ok", "version": "3.6.0"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 3000))
    uvicorn.run(app, host="0.0.0.0", port=port)
