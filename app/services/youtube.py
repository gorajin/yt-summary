"""
YouTube transcript extraction service.

Provides functions for extracting video IDs, titles, and transcripts
from YouTube videos using multiple fallback methods.
"""

import os
import re
import json
import tempfile
import urllib.request
from typing import Optional, List, Tuple

import yt_dlp

from ..config import PREFERRED_LANGUAGES
from ..models import TranscriptSegment


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


def get_video_title(video_id: str) -> str:
    """Get video title using oembed API (no auth required)."""
    try:
        oembed_url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
        with urllib.request.urlopen(oembed_url, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
            return data.get('title', 'Untitled Video')
    except (urllib.error.URLError, json.JSONDecodeError, KeyError, TimeoutError):
        return 'Untitled Video'


def get_transcript(url: str) -> Tuple[str, str]:
    """Fetch transcript. Tries youtube-transcript-api first, falls back to yt-dlp.
    
    Supports multiple languages with preference order:
    1. English (manual or auto)
    2. Video's original language (auto-generated)
    3. Translation to English (if available)
    4. yt-dlp fallback with expanded language support
    
    Returns:
        Tuple of (transcript_text, video_title)
    """
    
    video_id = extract_video_id(url)
    if not video_id:
        raise Exception("Could not extract video ID")
    
    print(f"  → Attempting transcript extraction for video: {video_id}")
    
    # Try youtube-transcript-api first (more reliable on servers)
    try:
        print("  → Trying youtube-transcript-api...")
        from youtube_transcript_api import YouTubeTranscriptApi
        
        # Try using list_transcripts for better control
        try:
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
            
            # Strategy 1: Try to find transcript in preferred languages
            transcript_data = None
            for lang in PREFERRED_LANGUAGES:
                try:
                    transcript = transcript_list.find_transcript([lang])
                    transcript_data = transcript.fetch()
                    print(f"  → Found transcript in language: {lang}")
                    break
                except Exception:
                    continue
            
            # Strategy 2: Get ANY available transcript (manual or generated)
            if not transcript_data:
                print("  → No preferred language found, trying any available transcript...")
                try:
                    for transcript in transcript_list:
                        try:
                            transcript_data = transcript.fetch()
                            print(f"  → Using {transcript.language} ({transcript.language_code}) transcript")
                            break
                        except Exception as fetch_err:
                            print(f"  → Failed to fetch {transcript.language_code}: {type(fetch_err).__name__}")
                            continue
                except Exception:
                    pass
            
            # Strategy 3: Try translation to English
            if not transcript_data:
                print("  → Trying translation to English...")
                try:
                    for transcript in transcript_list:
                        if transcript.is_translatable:
                            translated = transcript.translate('en')
                            transcript_data = translated.fetch()
                            print(f"  → Translated from {transcript.language} to English")
                            break
                except Exception as trans_err:
                    print(f"  → Translation failed: {type(trans_err).__name__}")
            
            if transcript_data:
                transcript = ' '.join([entry['text'] for entry in transcript_data])
                transcript = re.sub(r'\s+', ' ', transcript).strip()
                
                title = get_video_title(video_id)
                print(f"  → Got transcript via youtube-transcript-api ({len(transcript)} chars)")
                return transcript, title
                
        except Exception as list_err:
            print(f"  → list_transcripts failed: {type(list_err).__name__}: {list_err}")
        
        # Fallback: Try direct get_transcript with various languages  
        print("  → Trying direct get_transcript...")
        for lang in PREFERRED_LANGUAGES:
            try:
                transcript_data = YouTubeTranscriptApi.get_transcript(video_id, languages=[lang])
                transcript = ' '.join([entry['text'] for entry in transcript_data])
                transcript = re.sub(r'\s+', ' ', transcript).strip()
                
                title = get_video_title(video_id)
                print(f"  → Got transcript in {lang} ({len(transcript)} chars)")
                return transcript, title
            except Exception:
                continue
        
        print("  → youtube-transcript-api could not get transcript, trying yt-dlp")
            
    except ImportError as ie:
        print(f"  → youtube-transcript-api not installed: {ie}, using yt-dlp")
    except Exception as e:
        print(f"  → youtube-transcript-api failed: {type(e).__name__}: {e}, trying yt-dlp")
    
    # Fallback to yt-dlp
    print("  → Falling back to yt-dlp...")
    return _get_transcript_ytdlp(url)


def get_transcript_with_timestamps(url: str) -> Tuple[List[TranscriptSegment], str, str]:
    """Fetch transcript with timestamp data for each segment.
    
    Returns: (segments: List[TranscriptSegment], flat_text: str, title: str)
    
    This enhanced version preserves timing information for:
    - Generating timestamped notes
    - Creating clickable video links
    - Identifying natural section breaks
    """
    video_id = extract_video_id(url)
    if not video_id:
        raise Exception("Could not extract video ID")
    
    print(f"  → Extracting timestamped transcript for: {video_id}")
    
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        
        transcript_data = None
        
        # Try to get transcript with timestamps
        try:
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
            
            # Strategy 1: Preferred languages
            for lang in PREFERRED_LANGUAGES:
                try:
                    transcript = transcript_list.find_transcript([lang])
                    transcript_data = transcript.fetch()
                    print(f"  → Found timestamped transcript in: {lang}")
                    break
                except Exception:
                    continue
            
            # Strategy 2: Any available transcript
            if not transcript_data:
                for transcript in transcript_list:
                    try:
                        transcript_data = transcript.fetch()
                        print(f"  → Using {transcript.language} timestamped transcript")
                        break
                    except Exception:
                        continue
            
            # Strategy 3: Translation
            if not transcript_data:
                for transcript in transcript_list:
                    if transcript.is_translatable:
                        try:
                            translated = transcript.translate('en')
                            transcript_data = translated.fetch()
                            print(f"  → Translated to English with timestamps")
                            break
                        except Exception:
                            continue
                            
        except Exception as e:
            print(f"  → list_transcripts failed: {e}")
            # Fallback to direct fetch
            for lang in PREFERRED_LANGUAGES:
                try:
                    transcript_data = YouTubeTranscriptApi.get_transcript(video_id, languages=[lang])
                    print(f"  → Got timestamped transcript in {lang}")
                    break
                except Exception:
                    continue
        
        if transcript_data:
            # Convert to TranscriptSegment objects
            segments = []
            for entry in transcript_data:
                start = entry.get('start', 0)
                duration = entry.get('duration', 0)
                text = entry.get('text', '').strip()
                if text:  # Skip empty segments
                    segments.append(TranscriptSegment(
                        text=text,
                        start_time=start,
                        end_time=start + duration
                    ))
            
            # Also create flat text for backward compatibility
            flat_text = ' '.join([s.text for s in segments])
            flat_text = re.sub(r'\s+', ' ', flat_text).strip()
            
            title = get_video_title(video_id)
            print(f"  → Got {len(segments)} timestamped segments ({len(flat_text)} chars)")
            
            return segments, flat_text, title
            
    except ImportError:
        print("  → youtube-transcript-api not available")
    except Exception as e:
        print(f"  → Timestamped extraction failed: {e}")
    
    # Fallback: Get regular transcript and create segments without precise timestamps
    print("  → Falling back to basic transcript (no timestamps)")
    flat_text, title = get_transcript(url)
    
    # Create pseudo-segments (one per ~30 seconds of content assuming 150 wpm)
    words = flat_text.split()
    words_per_segment = 75  # ~30 seconds at 150 wpm
    segments = []
    
    for i in range(0, len(words), words_per_segment):
        chunk_words = words[i:i + words_per_segment]
        estimated_start = (i / 150) * 60  # Estimate based on word position
        segments.append(TranscriptSegment(
            text=' '.join(chunk_words),
            start_time=estimated_start,
            end_time=estimated_start + 30
        ))
    
    return segments, flat_text, title


def _get_transcript_ytdlp(url: str) -> Tuple[str, str]:
    """Fetch transcript using yt-dlp (fallback method). Returns (transcript, title)."""
    
    ydl_opts = {
        'writesubtitles': True,
        'writeautomaticsub': True,
        'subtitleslangs': PREFERRED_LANGUAGES,
        'subtitlesformat': 'json3',
        'skip_download': True,
        'quiet': True,
        'no_warnings': True,
        # Anti-blocking measures for cloud servers
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        },
        'geo_bypass': True,
        'geo_bypass_country': 'US',
        'socket_timeout': 30,
        'retries': 3,
        'extractor_retries': 3,
    }
    
    with tempfile.TemporaryDirectory() as tmpdir:
        ydl_opts['outtmpl'] = os.path.join(tmpdir, '%(id)s.%(ext)s')
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            title = info.get('title', 'Untitled Video')
            
            subtitles = info.get('subtitles', {})
            auto_captions = info.get('automatic_captions', {})
            
            transcript_url = None
            
            # Try manual subtitles first
            for lang in PREFERRED_LANGUAGES:
                if lang in subtitles:
                    for fmt in subtitles[lang]:
                        if fmt.get('ext') == 'json3':
                            transcript_url = fmt.get('url')
                            break
                if transcript_url:
                    break
            
            # Fall back to auto-generated
            if not transcript_url:
                for lang in PREFERRED_LANGUAGES:
                    if lang in auto_captions:
                        for fmt in auto_captions[lang]:
                            if fmt.get('ext') == 'json3':
                                transcript_url = fmt.get('url')
                                break
                    if transcript_url:
                        break
            
            if not transcript_url:
                raise Exception("No subtitles available for this video")
            
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
