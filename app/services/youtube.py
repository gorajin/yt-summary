"""
YouTube transcript extraction service.

Server-side extraction is available as a fallback when client-side extraction fails.
The iOS client handles transcript extraction locally to bypass YouTube's IP blocking,
but YouTube frequently changes their anti-bot measures. When client fails, this module
provides server-side extraction via youtube-transcript-api and yt-dlp.

Provides functions for extracting video IDs, titles, and transcripts
from YouTube videos using multiple fallback methods.
"""

import os
import re
import json
import time
import tempfile
import urllib.request
from typing import Optional, List, Tuple

import yt_dlp

from ..config import PREFERRED_LANGUAGES
from ..models import TranscriptSegment


def _retry_on_429(func, max_retries: int = 3, base_delay: float = 2.0):
    """Retry a function with exponential backoff on rate limit errors.
    
    YouTube rate limits aggressively on cloud IPs, so we need to
    back off and retry when we hit rate limit errors.
    
    YouTube disguises rate limits in multiple ways:
    - HTTP 429 Too Many Requests
    - ParseError (returns empty XML response)
    - YouTubeRequestFailed
    - 0-byte response with 200 OK (PoToken enforcement in 2026+)
    """
    last_error = None
    empty_response_count = 0
    
    for attempt in range(max_retries):
        try:
            result = func()
            # Check for empty/None results which may indicate PoToken enforcement
            if result is None or (isinstance(result, (list, str)) and len(result) == 0):
                empty_response_count += 1
                if empty_response_count >= 2:
                    # Multiple empty responses likely means PoToken enforcement, not rate limit
                    print(f"  → Multiple empty responses detected - likely PoToken enforcement")
                    raise Exception("Video requires authentication token (PoToken) that cannot be generated server-side.")
                print(f"  → Got empty result (attempt {attempt + 1}), waiting {base_delay}s before retry...")
                time.sleep(base_delay)
                continue
            return result
        except Exception as e:
            error_str = str(e).lower()
            error_type = type(e).__name__
            
            # Check if it's a rate limit error (including disguised ones)
            is_rate_limit = (
                '429' in error_str or 
                'too many' in error_str or 
                'rate' in error_str or
                'parseerror' in error_type.lower() or  # Empty XML response = rate limit
                'no element found' in error_str or      # XML parsing failed = empty response
                'youtuberequestfailed' in error_type.lower()  # Generic YouTube block
            )
            
            # Check if it's a PoToken enforcement issue
            is_potoken = (
                'potoken' in error_str or
                'pot=' in error_str or
                'authentication token' in error_str
            )
            
            if is_potoken:
                # Don't retry PoToken issues - they won't resolve
                print(f"  → PoToken enforcement detected, server-side extraction not possible")
                raise
            elif is_rate_limit:
                wait_time = base_delay * (2 ** attempt)  # exponential: 2, 4, 8 or 3, 6, 12 etc
                print(f"  → YouTube blocking detected ({error_type}), waiting {wait_time:.1f}s before retry {attempt + 1}/{max_retries}")
                time.sleep(wait_time)
                last_error = e
            else:
                # Not a rate limit error, don't retry
                raise
    # All retries exhausted
    raise last_error if last_error else Exception("Retry failed")


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
        
        # v1.2.4+ requires instance, not class methods
        ytt_api = YouTubeTranscriptApi()
        
        # Strategy 1: Try simple direct fetch first (most reliable)
        print("  → Trying direct fetch...")
        for lang in PREFERRED_LANGUAGES:
            try:
                fetched = ytt_api.fetch(video_id, languages=[lang])
                transcript_data = fetched.to_raw_data() if hasattr(fetched, 'to_raw_data') else list(fetched)
                transcript = ' '.join([entry['text'] if isinstance(entry, dict) else entry.text for entry in transcript_data])
                transcript = re.sub(r'\s+', ' ', transcript).strip()
                
                title = get_video_title(video_id)
                print(f"  → Got transcript in {lang} ({len(transcript)} chars)")
                return transcript, title
            except Exception as e:
                print(f"  → fetch({lang}) failed: {type(e).__name__}")
                continue
        
        # Strategy 2: List all transcripts and try each (v1.2.4 renamed list_transcripts to list)
        try:
            transcript_list = ytt_api.list(video_id)  # Note: list() not list_transcripts()
            
            # Strategy 1: Try to find transcript in preferred languages
            transcript_data = None
            for lang in PREFERRED_LANGUAGES:
                try:
                    transcript = transcript_list.find_transcript([lang])
                    fetched = transcript.fetch()
                    transcript_data = fetched.to_raw_data() if hasattr(fetched, 'to_raw_data') else fetched
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
                            fetched = transcript.fetch()
                            transcript_data = fetched.to_raw_data() if hasattr(fetched, 'to_raw_data') else fetched
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
                            fetched = translated.fetch()
                            transcript_data = fetched.to_raw_data() if hasattr(fetched, 'to_raw_data') else fetched
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
            print(f"  → list() failed: {type(list_err).__name__}: {list_err}")
        
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
    
    Uses retry logic with exponential backoff to handle YouTube 429 errors.
    """
    video_id = extract_video_id(url)
    if not video_id:
        raise Exception("Could not extract video ID")
    
    print(f"  → Extracting timestamped transcript for: {video_id}")
    
    # Get title early (less likely to be rate limited)
    title = get_video_title(video_id)
    
    # Wrap entire extraction in retry logic
    def try_extract_transcript():
        from youtube_transcript_api import YouTubeTranscriptApi
        
        # v1.2.4+ requires instance, not class methods
        ytt_api = YouTubeTranscriptApi()
        
        # Strategy 1: Simple direct fetch (most reliable in v1.2.4)
        for lang in PREFERRED_LANGUAGES:
            try:
                fetched = ytt_api.fetch(video_id, languages=[lang])
                # Handle FetchedTranscript (v1.2.4) or raw list (older versions)
                if hasattr(fetched, 'to_raw_data'):
                    transcript_data = fetched.to_raw_data()
                else:
                    # Convert FetchedTranscriptSnippet objects to dicts
                    transcript_data = [{'text': s.text, 'start': s.start, 'duration': s.duration} for s in fetched]
                print(f"  → Got transcript via fetch() in {lang}")
                return transcript_data
            except Exception as e:
                err_str = str(e).lower()
                if 'no transcript' not in err_str and 'could not find' not in err_str:
                    print(f"  → fetch({lang}): {type(e).__name__}")
                continue
        
        # Strategy 2: List all available and try each (v1.2.4: list() not list_transcripts())
        try:
            transcript_list = ytt_api.list(video_id)
            
            # Log available transcripts
            available = [f"{t.language_code}({'manual' if not t.is_generated else 'auto'})" for t in transcript_list]
            print(f"  → Available: {', '.join(available) if available else 'none'}")
            
            # Try preferred languages first
            for lang in PREFERRED_LANGUAGES:
                try:
                    transcript = transcript_list.find_transcript([lang])
                    fetched = transcript.fetch()
                    if hasattr(fetched, 'to_raw_data'):
                        return fetched.to_raw_data()
                    return [{'text': s.text, 'start': s.start, 'duration': s.duration} for s in fetched]
                except Exception:
                    continue
            
            # Try any available transcript
            for transcript in transcript_list:
                try:
                    fetched = transcript.fetch()
                    if hasattr(fetched, 'to_raw_data'):
                        return fetched.to_raw_data()
                    return [{'text': s.text, 'start': s.start, 'duration': s.duration} for s in fetched]
                except Exception as e:
                    print(f"  → {transcript.language_code}: {type(e).__name__}")
                    continue
            
            # Try translation to English
            for transcript in transcript_list:
                if transcript.is_translatable:
                    try:
                        translated = transcript.translate('en')
                        fetched = translated.fetch()
                        if hasattr(fetched, 'to_raw_data'):
                            return fetched.to_raw_data()
                        return [{'text': s.text, 'start': s.start, 'duration': s.duration} for s in fetched]
                    except Exception:
                        continue
                        
        except Exception as list_err:
            print(f"  → list() failed: {type(list_err).__name__}: {list_err}")
        
        return None
    
    # Try with retry logic for 429 errors
    transcript_data = None
    try:
        transcript_data = _retry_on_429(try_extract_transcript, max_retries=3, base_delay=3.0)
    except ImportError:
        print("  → youtube-transcript-api not available")
    except Exception as e:
        error_str = str(e).lower()
        if '429' in error_str or 'too many' in error_str:
            # Wait extra time before falling back
            print(f"  → YouTube rate limited after retries, waiting 10s before fallback...")
            time.sleep(10)
        print(f"  → Transcript extraction failed: {type(e).__name__}")
    
    # If we got transcript data, convert to segments
    if transcript_data:
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
        
        flat_text = ' '.join([s.text for s in segments])
        flat_text = re.sub(r'\s+', ' ', flat_text).strip()
        
        print(f"  → Got {len(segments)} timestamped segments ({len(flat_text)} chars)")
        return segments, flat_text, title
    
    # Fallback: Try yt-dlp with retry (wraps single call, no cascade)
    print("  → Falling back to yt-dlp...")
    try:
        def try_ytdlp():
            return _get_transcript_ytdlp(url)
        
        flat_text, ytdlp_title = _retry_on_429(try_ytdlp, max_retries=2, base_delay=5.0)
        title = ytdlp_title or title
        
        # Create pseudo-segments
        words = flat_text.split()
        words_per_segment = 75  # ~30 seconds at 150 wpm
        segments = []
        
        for i in range(0, len(words), words_per_segment):
            chunk_words = words[i:i + words_per_segment]
            estimated_start = (i / 150) * 60
            segments.append(TranscriptSegment(
                text=' '.join(chunk_words),
                start_time=estimated_start,
                end_time=estimated_start + 30
            ))
        
        return segments, flat_text, title
        
    except Exception as e:
        error_str = str(e).lower()
        print(f"  → yt-dlp failed: {type(e).__name__}: {str(e)[:100]}")
        
        # All fallbacks exhausted - return appropriate error
        if '429' in error_str or 'too many' in error_str or 'bot' in error_str:
            raise Exception("YouTube is temporarily limiting requests. Please try again in a few minutes.")
        elif '403' in error_str or 'forbidden' in error_str:
            raise Exception("Unable to access this video's transcript. It may be private or have captions disabled.")
        else:
            raise


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
