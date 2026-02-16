"""
Daily email digest service using Resend.

Sends users a summary of their day's notes with cross-video insights.
Designed to run as a cron job (hourly) via Railway.
"""

import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from app.utils import escape_html as _esc

logger = logging.getLogger(__name__)

# Resend API configuration
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
RESEND_FROM_EMAIL = os.getenv("RESEND_FROM_EMAIL", "WatchLater <digest@watchlater.app>")
APP_URL = os.getenv("APP_URL", "https://watchlater.app")


def send_email(to: str, subject: str, html: str) -> bool:
    """Send an email via Resend API.
    
    Returns True if sent successfully, False otherwise.
    """
    if not RESEND_API_KEY:
        logger.warning("RESEND_API_KEY not set, skipping email")
        return False
    
    try:
        response = httpx.post(
            "https://api.resend.com/emails",
            json={
                "from": RESEND_FROM_EMAIL,
                "to": [to],
                "subject": subject,
                "html": html,
            },
            headers={"Authorization": f"Bearer {RESEND_API_KEY}"},
            timeout=10,
        )
        response.raise_for_status()
        result = response.json()
        logger.info(f"Email sent to {to}: {result.get('id', 'ok')}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email to {to}: {e}")
        return False


def build_digest_html(summaries: list, user_email: str) -> str:
    """Build the HTML email content for a daily digest.
    
    Args:
        summaries: List of summary dicts from Supabase (today's summaries)
        user_email: For the unsubscribe link
    
    Returns:
        Styled HTML email string
    """
    today = datetime.now(timezone.utc).strftime("%B %d, %Y")
    count = len(summaries)
    
    # Build individual summary cards
    cards_html = ""
    all_insights = []
    
    for s in summaries:
        sj = s.get("summary_json") or {}
        title = sj.get("title") or s.get("title", "Untitled")
        overview = sj.get("overview") or s.get("overview", "")
        video_id = s.get("video_id", "")
        youtube_url = s.get("youtube_url", "")
        content_type = sj.get("contentType") or s.get("content_type", "general")
        summary_id = s.get("id", "")
        
        # Collect insights for cross-video synthesis
        for insight in sj.get("keyInsights", [])[:3]:
            if isinstance(insight, dict):
                all_insights.append({
                    "text": insight.get("insight", ""),
                    "video": title,
                })
        
        # Type emoji
        type_emoji = {
            "lecture": "📚", "interview": "🎙️", "tutorial": "🔧",
            "documentary": "🎬", "general": "📝"
        }.get(content_type, "📝")
        
        # Top 2 insights for this video
        insights_html = ""
        for insight in sj.get("keyInsights", [])[:2]:
            if isinstance(insight, dict):
                text = insight.get("insight", "")
                insights_html += f'<li style="color:#333;margin-bottom:4px;">{text}</li>'
        
        cards_html += f"""
        <div style="background:#f8f9fa;border-radius:12px;padding:16px;margin-bottom:16px;border-left:4px solid #4A90D9;">
            <div style="font-size:11px;color:#888;margin-bottom:4px;">{type_emoji} {content_type.upper()}</div>
            <div style="font-size:16px;font-weight:600;color:#1a1a1a;margin-bottom:8px;">{_esc(title)}</div>
            <div style="font-size:13px;color:#555;margin-bottom:12px;">{_esc(overview[:150])}</div>
            {f'<ul style="padding-left:20px;margin:0 0 12px 0;">{insights_html}</ul>' if insights_html else ''}
            <div>
                <a href="{youtube_url}" style="color:#4A90D9;text-decoration:none;font-size:13px;margin-right:16px;">▶️ Watch Video</a>
            </div>
        </div>
        """
    
    # Build cross-video synthesis section
    synthesis_html = ""
    if len(all_insights) >= 2:
        synthesis_html = """
        <div style="background:#fff8e1;border-radius:12px;padding:16px;margin-bottom:16px;border-left:4px solid #ffc107;">
            <div style="font-size:14px;font-weight:600;color:#1a1a1a;margin-bottom:8px;">💡 Across Your Videos Today</div>
            <div style="font-size:13px;color:#555;">
        """
        # Show top insights across videos
        seen = set()
        for item in all_insights[:4]:
            if item["text"] not in seen:
                seen.add(item["text"])
                synthesis_html += f'<div style="margin-bottom:8px;">• {_esc(item["text"])} <span style="color:#999;font-size:11px;">({_esc(item["video"][:40])})</span></div>'
        synthesis_html += "</div></div>"
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
    <body style="margin:0;padding:0;background:#f0f2f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
        <div style="max-width:560px;margin:0 auto;padding:24px 16px;">
            <!-- Header -->
            <div style="text-align:center;margin-bottom:24px;">
                <div style="font-size:24px;font-weight:700;color:#1a1a1a;">📚 Your Daily Learning Digest</div>
                <div style="font-size:13px;color:#888;margin-top:4px;">{today} · {count} {'video' if count == 1 else 'videos'} summarized</div>
            </div>
            
            <!-- Summary Cards -->
            {cards_html}
            
            <!-- Cross-Video Insights -->
            {synthesis_html}
            
            <!-- Footer -->
            <div style="text-align:center;margin-top:24px;padding-top:16px;border-top:1px solid #e0e0e0;">
                <div style="font-size:11px;color:#aaa;">
                    Sent by WatchLater · <a href="{APP_URL}" style="color:#4A90D9;text-decoration:none;">Open App</a>
                </div>
            </div>
        </div>
    </body>
    </html>
    """
    
    return html


# _esc is imported from app.utils.escape_html at the top of this file


def get_users_for_digest(supabase_client, current_hour: int) -> list:
    """Get users who should receive digests at the current hour.
    
    Args:
        supabase_client: Supabase client instance
        current_hour: Current hour in UTC (0-23)
    
    Returns:
        List of user dicts
    """
    try:
        # Find users whose preferred digest time matches the current hour
        # We match on the hour part of email_digest_time
        result = (
            supabase_client.table("users")
            .select("id, email, email_digest_time, timezone")
            .eq("email_digest_enabled", True)
            .execute()
        )
        
        if not result.data:
            return []
        
        # Filter users whose local time matches their preferred digest hour
        matching_users = []
        for user in result.data:
            preferred_time = user.get("email_digest_time", "20:00")
            try:
                preferred_hour = int(preferred_time.split(":")[0])
            except (ValueError, IndexError):
                preferred_hour = 20
            
            # Convert user's preferred local hour to UTC for comparison
            user_tz_str = user.get("timezone", "UTC")
            try:
                user_tz = ZoneInfo(user_tz_str)
                # Create a reference time today at the user's preferred hour in their zone
                now_utc = datetime.now(timezone.utc)
                local_ref = now_utc.astimezone(user_tz).replace(
                    hour=preferred_hour, minute=0, second=0, microsecond=0
                )
                # Convert that local time to UTC to see what UTC hour it corresponds to
                preferred_utc_hour = local_ref.astimezone(timezone.utc).hour
            except (ZoneInfoNotFoundError, Exception):
                # Fall back to treating preferred_hour as UTC
                logger.debug(f"Invalid timezone '{user_tz_str}' for user {user.get('id')}, using UTC")
                preferred_utc_hour = preferred_hour
            
            if preferred_utc_hour == current_hour:
                matching_users.append(user)
        
        return matching_users
        
    except Exception as e:
        logger.error(f"Failed to get digest users: {e}")
        return []


def get_todays_summaries(supabase_client, user_id: str) -> list:
    """Get summaries created in the past 24 hours for a user."""
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        
        result = (
            supabase_client.table("summaries")
            .select("id, youtube_url, title, notion_url, created_at")
            .eq("user_id", user_id)
            .gte("created_at", cutoff)
            .order("created_at", desc=True)
            .execute()
        )
        
        return result.data if result.data else []
        
    except Exception as e:
        logger.error(f"Failed to get today's summaries for {user_id}: {e}")
        return []


def send_daily_digests(supabase_client, current_hour: Optional[int] = None):
    """Main entry point for the digest cron job.
    
    Called hourly. Finds users whose preferred digest time matches
    the current hour, fetches their day's summaries, and sends emails.
    
    Args:
        supabase_client: Supabase client instance
        current_hour: Override for testing (default: current UTC hour)
    """
    if current_hour is None:
        current_hour = datetime.now(timezone.utc).hour
    
    logger.info(f"Running daily digest for hour {current_hour} UTC")
    
    users = get_users_for_digest(supabase_client, current_hour)
    logger.info(f"Found {len(users)} users for digest at hour {current_hour}")
    
    sent_count = 0
    skip_count = 0
    
    for user in users:
        user_id = user["id"]
        email = user.get("email")
        
        if not email:
            skip_count += 1
            continue
        
        summaries = get_todays_summaries(supabase_client, user_id)
        
        if not summaries:
            skip_count += 1
            continue
        
        # Build and send digest
        html = build_digest_html(summaries, email)
        count = len(summaries)
        subject = f"📚 Your Daily Learning Digest — {count} {'video' if count == 1 else 'videos'} summarized"
        
        if send_email(email, subject, html):
            sent_count += 1
        
    logger.info(f"Daily digest complete: sent={sent_count}, skipped={skip_count}")
    return sent_count
