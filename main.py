"""
YouTube to Notion API
FastAPI backend using yt-dlp for transcript extraction, Gemini REST API for summarization, and Notion for storage.
"""

import os
import re
import json
import tempfile
import urllib.request
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from datetime import date

import yt_dlp
from notion_client import Client as NotionClient

# Load environment variables
load_dotenv()

app = FastAPI(title="YouTube to Notion API")

# CORS for iOS shortcuts
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure Notion
notion = NotionClient(auth=os.getenv("NOTION_TOKEN"))
DATABASE_ID = os.getenv("NOTION_DATABASE_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")


class SummarizeRequest(BaseModel):
    url: str


class SummarizeResponse(BaseModel):
    success: bool
    title: Optional[str] = None
    notionUrl: Optional[str] = None
    error: Optional[str] = None


def extract_video_id(url: str) -> Optional[str]:
    """Extract video ID from various YouTube URL formats."""
    patterns = [
        r'(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/shorts\/)([a-zA-Z0-9_-]{11})',
        r'(?:youtube\.com\/embed\/)([a-zA-Z0-9_-]{11})',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    if re.match(r'^[a-zA-Z0-9_-]{11}$', url):
        return url
    return None


def get_transcript(url: str) -> tuple:
    """Fetch transcript using yt-dlp. Returns (transcript, title)."""
    
    ydl_opts = {
        'writesubtitles': True,
        'writeautomaticsub': True,
        'subtitleslangs': ['en', 'en-US', 'en-GB'],
        'subtitlesformat': 'json3',
        'skip_download': True,
        'quiet': True,
        'no_warnings': True,
    }
    
    with tempfile.TemporaryDirectory() as tmpdir:
        ydl_opts['outtmpl'] = os.path.join(tmpdir, '%(id)s.%(ext)s')
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            title = info.get('title', 'Untitled Video')
            
            subtitles = info.get('subtitles', {})
            auto_captions = info.get('automatic_captions', {})
            
            transcript_url = None
            
            for lang in ['en', 'en-US', 'en-GB', 'en-orig']:
                if lang in subtitles:
                    for fmt in subtitles[lang]:
                        if fmt.get('ext') == 'json3':
                            transcript_url = fmt.get('url')
                            break
                if transcript_url:
                    break
            
            if not transcript_url:
                for lang in ['en', 'en-US', 'en-GB', 'en-orig']:
                    if lang in auto_captions:
                        for fmt in auto_captions[lang]:
                            if fmt.get('ext') == 'json3':
                                transcript_url = fmt.get('url')
                                break
                    if transcript_url:
                        break
            
            if not transcript_url:
                raise Exception("No English subtitles available for this video")
            
            with urllib.request.urlopen(transcript_url) as response:
                transcript_data = json.loads(response.read().decode('utf-8'))
            
            events = transcript_data.get('events', [])
            texts = []
            for event in events:
                segs = event.get('segs', [])
                for seg in segs:
                    text = seg.get('utf8', '').strip()
                    if text and text != '\n':
                        texts.append(text)
            
            transcript = ' '.join(texts)
            transcript = re.sub(r'\s+', ' ', transcript).strip()
            
            if not transcript:
                raise Exception("Could not extract transcript text")
            
            return transcript, title


def summarize_with_gemini(transcript: str) -> dict:
    """Summarize transcript using Gemini REST API directly."""
    prompt = f"""Analyze this YouTube video transcript and provide a structured summary.

TRANSCRIPT:
{transcript[:15000]}

Respond in this exact JSON format (no markdown, just raw JSON):
{{
  "title": "A clear, descriptive title for this video",
  "oneLiner": "One sentence capturing the main point",
  "keyTakeaways": [
    "Key takeaway 1",
    "Key takeaway 2",
    "Key takeaway 3"
  ],
  "insights": [
    "Notable insight 1",
    "Notable insight 2"
  ]
}}

Guidelines:
- Title should be descriptive (not clickbait)
- 3-5 key takeaways that are actionable or memorable
- 2-4 notable insights or "aha moments"
"""
    
    # Use Gemini REST API directly
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
    
    data = {
        "contents": [{
            "parts": [{"text": prompt}]
        }]
    }
    
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode('utf-8'),
        headers={'Content-Type': 'application/json'},
        method='POST'
    )
    
    with urllib.request.urlopen(req, timeout=60) as response:
        result = json.loads(response.read().decode('utf-8'))
    
    # Extract text from response
    text = result['candidates'][0]['content']['parts'][0]['text'].strip()
    
    # Clean up response
    if text.startswith('```'):
        text = re.sub(r'^```json?\n?', '', text)
        text = re.sub(r'\n?```$', '', text)
    
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {
            "title": "Video Summary",
            "oneLiner": "Could not parse summary",
            "keyTakeaways": ["Summary parsing failed"],
            "insights": []
        }


def create_notion_page(title: str, url: str, one_liner: str, takeaways: list, insights: list) -> str:
    """Create a Notion page with the summary."""
    children = [
        {
            "object": "block",
            "type": "callout",
            "callout": {
                "rich_text": [{"type": "text", "text": {"content": one_liner}}],
                "icon": {"emoji": "💡"},
                "color": "blue_background"
            }
        },
        {"object": "block", "type": "divider", "divider": {}},
        {
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🎯 Key Takeaways"}}]}
        },
    ]
    
    for takeaway in takeaways:
        children.append({
            "object": "block",
            "type": "bulleted_list_item",
            "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": takeaway}}]}
        })
    
    children.append({"object": "block", "type": "divider", "divider": {}})
    children.append({
        "object": "block",
        "type": "heading_2",
        "heading_2": {"rich_text": [{"type": "text", "text": {"content": "✨ Notable Insights"}}]}
    })
    
    for insight in insights:
        children.append({
            "object": "block",
            "type": "bulleted_list_item",
            "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": insight}}]}
        })
    
    response = notion.pages.create(
        parent={"database_id": DATABASE_ID},
        properties={
            "Title": {"title": [{"text": {"content": title}}]},
            "url": {"url": url},
            "Added": {"date": {"start": date.today().isoformat()}}
        },
        children=children
    )
    
    return response["url"]


@app.get("/")
async def health():
    return {"status": "ok", "service": "YouTube to Notion API"}


@app.post("/summarize", response_model=SummarizeResponse)
async def summarize(request: SummarizeRequest):
    try:
        video_id = extract_video_id(request.url)
        if not video_id:
            raise HTTPException(status_code=400, detail="Invalid YouTube URL")
        
        print(f"Processing: {request.url}")
        
        print("  → Fetching transcript...")
        transcript, video_title = get_transcript(request.url)
        print(f"  → Got transcript ({len(transcript)} chars)")
        
        print("  → Summarizing with Gemini...")
        summary = summarize_with_gemini(transcript)
        final_title = summary.get("title") or video_title
        print(f"  → Generated: {final_title}")
        
        print("  → Creating Notion page...")
        notion_url = create_notion_page(
            title=final_title,
            url=f"https://youtu.be/{video_id}",
            one_liner=summary.get("oneLiner", ""),
            takeaways=summary.get("keyTakeaways", []),
            insights=summary.get("insights", [])
        )
        print(f"  ✓ Done → {notion_url}")
        
        return SummarizeResponse(
            success=True,
            title=final_title,
            notionUrl=notion_url
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"  ✗ Error: {str(e)}")
        return SummarizeResponse(success=False, error=str(e))


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 3000))
    uvicorn.run(app, host="0.0.0.0", port=port)
