"""
Gemini AI summarization service.

Provides functions for calling the Gemini API, detecting content types,
building prompts, and generating lecture notes from transcripts.
"""

import re
import json
import time
import urllib.request
from typing import List

from ..config import GEMINI_API_KEY, GEMINI_API_ENDPOINT
from ..models import ContentType, LectureNotes, TranscriptSegment


def call_gemini_api(prompt: str, max_retries: int = 3, timeout: int = 180) -> dict:
    """Call Gemini API with retry logic and exponential backoff.
    
    Args:
        prompt: The prompt to send to Gemini
        max_retries: Maximum number of retry attempts (default 3)
        timeout: Request timeout in seconds (default 180)
    
    Returns:
        Parsed JSON response from Gemini
        
    Raises:
        Exception: If all retries fail
    """
    url = f"{GEMINI_API_ENDPOINT}?key={GEMINI_API_KEY}"
    
    data = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.3,
            "topP": 0.8,
            "maxOutputTokens": 8192
        }
    }
    
    last_error = None
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(data).encode('utf-8'),
                headers={'Content-Type': 'application/json'},
                method='POST'
            )
            
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return json.loads(response.read().decode('utf-8'))
                
        except urllib.error.HTTPError as e:
            last_error = e
            if e.code == 429:  # Rate limited
                wait_time = (2 ** attempt) * 2  # 2, 4, 8 seconds
                print(f"    ⚠ Rate limited, waiting {wait_time}s before retry {attempt + 1}/{max_retries}")
                time.sleep(wait_time)
            elif e.code >= 500:  # Server error
                wait_time = (2 ** attempt) * 1  # 1, 2, 4 seconds
                print(f"    ⚠ Server error {e.code}, retrying in {wait_time}s ({attempt + 1}/{max_retries})")
                time.sleep(wait_time)
            else:
                raise  # Don't retry client errors (4xx except 429)
                
        except (urllib.error.URLError, TimeoutError) as e:
            last_error = e
            wait_time = (2 ** attempt) * 1
            print(f"    ⚠ Network error, retrying in {wait_time}s ({attempt + 1}/{max_retries})")
            time.sleep(wait_time)
    
    raise Exception(f"Gemini API failed after {max_retries} retries: {last_error}")


def detect_content_type(transcript: str, title: str) -> ContentType:
    """Detect video content type for optimized processing.
    Uses heuristics first, then Gemini for ambiguous cases.
    """
    text_lower = transcript.lower()[:5000]  # Check beginning for patterns
    title_lower = title.lower()
    
    # Tutorial indicators
    tutorial_patterns = [
        "step by step", "how to", "tutorial", "let me show you",
        "follow along", "in this video i'll show", "let's build",
        "coding tutorial", "walkthrough"
    ]
    if any(p in text_lower or p in title_lower for p in tutorial_patterns):
        return ContentType.TUTORIAL
    
    # Interview/podcast indicators
    interview_patterns = [
        "podcast", "interview", "my guest today", "welcome to the show",
        "thanks for having me", "let's talk about", "conversation with",
        "episode", "q&a"
    ]
    if any(p in text_lower or p in title_lower for p in interview_patterns):
        return ContentType.INTERVIEW
    
    # Lecture indicators
    lecture_patterns = [
        "lecture", "class", "lesson", "today we'll learn", "professor",
        "let's examine", "the concept of", "as we discussed",
        "university", "course", "curriculum"
    ]
    if any(p in text_lower or p in title_lower for p in lecture_patterns):
        return ContentType.LECTURE
    
    # Documentary indicators
    documentary_patterns = [
        "documentary", "the story of", "history of", "investigation",
        "the truth about", "behind the scenes", "untold story"
    ]
    if any(p in text_lower or p in title_lower for p in documentary_patterns):
        return ContentType.DOCUMENTARY
    
    return ContentType.GENERAL


def _build_lecture_prompt(transcript: str, content_type: ContentType, word_count: int) -> str:
    """Build specialized prompt based on content type."""
    approx_minutes = word_count // 150
    
    # Base context
    context = f"""VIDEO LENGTH: Approximately {approx_minutes} minutes ({word_count:,} words)
CONTENT TYPE: {content_type.value}

TRANSCRIPT:
{transcript}
"""
    
    # Content-type specific instructions
    if content_type == ContentType.LECTURE:
        instructions = """
You are creating comprehensive LECTURE NOTES for a student. Extract:
1. Main concepts with clear definitions
2. Examples and case studies mentioned
3. Key formulas, frameworks, or models
4. Connections between concepts
5. Any recommended readings or resources

Think like a diligent student taking notes - capture EVERYTHING important."""

    elif content_type == ContentType.INTERVIEW:
        instructions = """
You are creating notes from a PODCAST/INTERVIEW. Extract:
1. Key perspectives from each speaker
2. Important quotes (verbatim when possible)
3. Stories and anecdotes shared
4. Advice or recommendations given
5. Books, people, or resources mentioned

Capture the unique insights from this conversation."""

    elif content_type == ContentType.TUTORIAL:
        instructions = """
You are creating a STEP-BY-STEP GUIDE from this tutorial. Extract:
1. Prerequisites or setup required
2. Each step in order with details
3. Commands, code snippets, or specific actions
4. Common mistakes or warnings mentioned
5. Tips and best practices

Make these notes actionable - someone should be able to follow them."""

    elif content_type == ContentType.DOCUMENTARY:
        instructions = """
You are creating notes from a DOCUMENTARY. Extract:
1. Timeline of events or narrative arc
2. Key facts and statistics
3. Important people and their roles
4. Sources or evidence cited
5. Main arguments or conclusions

Capture the story and its supporting evidence."""

    else:  # GENERAL
        instructions = """
You are creating comprehensive NOTES from this video. Extract:
1. Main topic and thesis
2. Key points and supporting details
3. Examples and evidence
4. Notable quotes or statements
5. Any calls to action or recommendations

Be thorough - capture all important information."""

    # Output format specification
    output_format = """
Respond in this EXACT JSON format (no markdown, just raw JSON):
{
  "title": "Clear, descriptive title",
  "contentType": "detected content type",
  "overview": "One comprehensive sentence summarizing the entire content",
  "tableOfContents": [
    {"section": "Section name", "timestamp": "MM:SS", "description": "Brief description"}
  ],
  "mainConcepts": [
    {"concept": "Concept name", "definition": "Clear explanation", "timestamp": "MM:SS", "examples": ["Example 1", "Example 2"]}
  ],
  "keyInsights": [
    {"insight": "The key insight", "timestamp": "MM:SS", "context": "Why this matters or additional context"}
  ],
  "detailedNotes": [
    {"section": "Topic/Section", "timestamp": "MM:SS", "points": ["Point 1", "Point 2", "Point 3"]}
  ],
  "notableQuotes": [
    {"quote": "Exact or paraphrased quote", "speaker": "Speaker name if known", "timestamp": "MM:SS"}
  ],
  "resourcesMentioned": ["Book, website, or tool 1", "Resource 2"],
  "actionItems": ["Action 1", "Action 2"],
  "questionsRaised": ["Open question 1", "Question 2"]
}

GUIDELINES:
- For videos under 15 minutes: 3-5 main concepts, 5-8 insights, 2-3 detailed sections
- For videos 15-45 minutes: 5-8 main concepts, 8-12 insights, 3-5 detailed sections  
- For videos 45+ minutes: 8-12 main concepts, 12-20 insights, 5-8 detailed sections
- Capture content from the ENTIRE video, not just the beginning
- Include TIMESTAMPS (MM:SS format) when the topic/insight appears in the video
- Include specific details, numbers, names when mentioned
- Empty arrays are fine if that section doesn't apply
"""

    return context + instructions + output_format


def _build_timestamped_prompt(segments: List[TranscriptSegment], content_type: ContentType, video_id: str = "") -> str:
    """Build prompt with timestamped transcript for precise references.
    
    Formats the transcript to include timestamps every ~30 seconds,
    allowing Gemini to correlate content with video times.
    """
    # Format segments with timestamps inline
    formatted_chunks = []
    current_chunk = []
    last_timestamp_shown = -60  # Show timestamps every ~60 seconds
    
    for seg in segments:
        # Add timestamp marker periodically
        if seg.start_time - last_timestamp_shown >= 60:
            if current_chunk:
                formatted_chunks.append(' '.join(current_chunk))
                current_chunk = []
            timestamp = seg.timestamp_str()
            current_chunk.append(f"\n[{timestamp}] ")
            last_timestamp_shown = seg.start_time
        current_chunk.append(seg.text)
    
    if current_chunk:
        formatted_chunks.append(' '.join(current_chunk))
    
    timestamped_transcript = ''.join(formatted_chunks)
    word_count = len(timestamped_transcript.split())
    approx_minutes = word_count // 150
    
    # Calculate total duration from last segment
    total_duration = segments[-1].end_time if segments else 0
    duration_str = f"{int(total_duration // 60)}:{int(total_duration % 60):02d}"
    
    context = f"""VIDEO INFO:
- Duration: {duration_str} (approximately {approx_minutes} minutes of spoken content)
- Word count: {word_count:,} words
- Content type: {content_type.value}
{f"- Video ID: {video_id}" if video_id else ""}

TIMESTAMPED TRANSCRIPT:
The transcript below includes [MM:SS] timestamps. Use these to reference when topics appear.

{timestamped_transcript}
"""
    
    # Content-type specific instructions (same as before)
    if content_type == ContentType.LECTURE:
        instructions = """
You are creating comprehensive LECTURE NOTES for a student. Extract:
1. Main concepts with clear definitions - note WHEN each concept is introduced
2. Examples and case studies mentioned
3. Key formulas, frameworks, or models
4. Connections between concepts
5. Any recommended readings or resources

Think like a diligent student taking notes - capture EVERYTHING important with timestamps."""

    elif content_type == ContentType.INTERVIEW:
        instructions = """
You are creating notes from a PODCAST/INTERVIEW. Extract:
1. Key perspectives from each speaker - note when they make their points
2. Important quotes (verbatim when possible) with timestamps
3. Stories and anecdotes shared
4. Advice or recommendations given
5. Books, people, or resources mentioned

Capture the unique insights with precise timestamps for easy reference."""

    elif content_type == ContentType.TUTORIAL:
        instructions = """
You are creating a STEP-BY-STEP GUIDE from this tutorial. Extract:
1. Prerequisites or setup required
2. Each step in order with timestamp when it starts
3. Commands, code snippets, or specific actions
4. Common mistakes or warnings mentioned
5. Tips and best practices

Make these notes actionable with timestamps so users can jump to each step."""

    elif content_type == ContentType.DOCUMENTARY:
        instructions = """
You are creating notes from a DOCUMENTARY. Extract:
1. Timeline of events or narrative arc with timestamps
2. Key facts and statistics
3. Important people and their roles
4. Sources or evidence cited
5. Main arguments or conclusions

Capture the story with timestamps for key moments."""

    else:  # GENERAL
        instructions = """
You are creating comprehensive NOTES from this video. Extract:
1. Main topic and thesis
2. Key points and supporting details - note when discussed
3. Examples and evidence
4. Notable quotes or statements with timestamps
5. Any calls to action or recommendations

Be thorough - capture all important information with timestamps."""

    output_format = """
Respond in this EXACT JSON format (no markdown, just raw JSON):
{
  "title": "Clear, descriptive title",
  "contentType": "detected content type",
  "overview": "One comprehensive sentence summarizing the entire content",
  "tableOfContents": [
    {"section": "Section name", "timestamp": "MM:SS", "description": "Brief description"}
  ],
  "mainConcepts": [
    {"concept": "Concept name", "definition": "Clear explanation", "timestamp": "MM:SS", "examples": ["Example 1"]}
  ],
  "keyInsights": [
    {"insight": "The key insight", "timestamp": "MM:SS", "context": "Why this matters"}
  ],
  "detailedNotes": [
    {"section": "Topic/Section", "timestamp": "MM:SS", "points": ["Point 1", "Point 2"]}
  ],
  "notableQuotes": [
    {"quote": "The exact quote", "speaker": "Speaker name", "timestamp": "MM:SS"}
  ],
  "resourcesMentioned": ["Book or resource 1"],
  "actionItems": ["Action 1"],
  "questionsRaised": ["Question 1"]
}

CRITICAL TIMESTAMP INSTRUCTIONS:
- Use the [MM:SS] markers in the transcript to determine timestamps
- Every table of contents section MUST have a timestamp
- Key insights and concepts should have timestamps when they first appear
- Notable quotes MUST have timestamps
- Format: "MM:SS" (e.g., "5:30", "1:15:00" for longer videos)
"""

    return context + instructions + output_format


def generate_lecture_notes(transcript: str, title: str = "") -> LectureNotes:
    """Generate comprehensive lecture notes from transcript.
    
    This is the new core summarization engine that produces detailed,
    structured notes suitable for any video type.
    """
    # Gemini 2.0 Flash handles up to ~1M tokens, we use 200k chars (~50k tokens)
    # for better results with very long content
    max_transcript_length = 200000
    transcript_text = transcript[:max_transcript_length]
    word_count = len(transcript_text.split())
    
    # Detect content type
    content_type = detect_content_type(transcript_text, title)
    print(f"  → Detected content type: {content_type.value}")
    
    # Build specialized prompt
    prompt = _build_lecture_prompt(transcript_text, content_type, word_count)
    
    # Call Gemini API with retry logic
    result = call_gemini_api(prompt)
    
    text = result['candidates'][0]['content']['parts'][0]['text'].strip()
    
    # Clean markdown code blocks if present
    if text.startswith('```'):
        text = re.sub(r'^```json?\n?', '', text)
        text = re.sub(r'\n?```$', '', text)
    
    try:
        data = json.loads(text)
        
        return LectureNotes(
            title=data.get("title", title or "Untitled Notes"),
            content_type=content_type,
            overview=data.get("overview", ""),
            table_of_contents=data.get("tableOfContents", []),
            main_concepts=data.get("mainConcepts", []),
            key_insights=data.get("keyInsights", []),
            detailed_notes=data.get("detailedNotes", []),
            notable_quotes=data.get("notableQuotes", []),
            resources_mentioned=data.get("resourcesMentioned", []),
            action_items=data.get("actionItems", []),
            questions_raised=data.get("questionsRaised", [])
        )
    except json.JSONDecodeError as e:
        print(f"  ⚠ JSON parsing failed: {e}")
        # Return minimal notes on parse failure
        return LectureNotes(
            title=title or "Video Notes",
            content_type=ContentType.GENERAL,
            overview="Notes generation encountered an error",
            key_insights=[{"insight": "Could not parse AI response", "context": str(e)}]
        )


def generate_lecture_notes_from_segments(
    segments: List[TranscriptSegment], 
    title: str = "",
    video_id: str = ""
) -> LectureNotes:
    """Generate comprehensive lecture notes from timestamped transcript segments.
    
    This enhanced version uses timestamp information to:
    - Create precise table of contents with video links
    - Mark when each concept/insight appears in the video
    - Enable clickable timestamps in final output
    """
    if not segments:
        return LectureNotes(
            title=title or "Video Notes",
            content_type=ContentType.GENERAL,
            overview="No transcript available",
            key_insights=[]
        )
    
    # Create flat text for content detection
    flat_text = ' '.join([s.text for s in segments])
    word_count = len(flat_text.split())
    
    # Detect content type
    content_type = detect_content_type(flat_text, title)
    print(f"  → Detected content type: {content_type.value}")
    print(f"  → Processing {len(segments)} timestamped segments")
    
    # Build timestamped prompt
    prompt = _build_timestamped_prompt(segments, content_type, video_id)
    
    # Truncate prompt if too long (keep ~200k chars for transcript)
    max_prompt_length = 250000
    if len(prompt) > max_prompt_length:
        print(f"  ⚠ Truncating prompt from {len(prompt)} to {max_prompt_length} chars")
        prompt = prompt[:max_prompt_length]
    
    # Call Gemini API with retry logic
    result = call_gemini_api(prompt)
    
    text = result['candidates'][0]['content']['parts'][0]['text'].strip()
    
    # Clean markdown code blocks
    if text.startswith('```'):
        text = re.sub(r'^```json?\n?', '', text)
        text = re.sub(r'\n?```$', '', text)
    
    try:
        data = json.loads(text)
        
        # Process notable quotes - handle both old format (strings) and new format (objects)
        notable_quotes = data.get("notableQuotes", [])
        processed_quotes = []
        for q in notable_quotes:
            if isinstance(q, dict):
                # New format with quote/speaker/timestamp
                processed_quotes.append(q.get("quote", str(q)))
            else:
                # Old format (plain string)
                processed_quotes.append(str(q))
        
        return LectureNotes(
            title=data.get("title", title or "Untitled Notes"),
            content_type=content_type,
            overview=data.get("overview", ""),
            table_of_contents=data.get("tableOfContents", []),
            main_concepts=data.get("mainConcepts", []),
            key_insights=data.get("keyInsights", []),
            detailed_notes=data.get("detailedNotes", []),
            notable_quotes=processed_quotes,
            resources_mentioned=data.get("resourcesMentioned", []),
            action_items=data.get("actionItems", []),
            questions_raised=data.get("questionsRaised", [])
        )
    except json.JSONDecodeError as e:
        print(f"  ⚠ JSON parsing failed: {e}")
        # Fallback to non-timestamped version
        print("  → Falling back to generate_lecture_notes")
        return generate_lecture_notes(flat_text, title)


# ============ Long-Form Chunked Processing ============

def _split_into_chunks(segments: List[TranscriptSegment], max_minutes: int = 30) -> List[List[TranscriptSegment]]:
    """Split transcript segments into time-based chunks.
    
    Args:
        segments: List of transcript segments with timestamps
        max_minutes: Maximum duration per chunk in minutes
        
    Returns:
        List of segment lists, each representing a chunk
    """
    if not segments:
        return []
    
    max_seconds = max_minutes * 60
    chunks = []
    current_chunk = []
    chunk_start = segments[0].start_time
    
    for segment in segments:
        # Check if adding this segment would exceed chunk duration
        if segment.start_time - chunk_start >= max_seconds and current_chunk:
            chunks.append(current_chunk)
            current_chunk = []
            chunk_start = segment.start_time
        
        current_chunk.append(segment)
    
    # Don't forget the last chunk
    if current_chunk:
        chunks.append(current_chunk)
    
    return chunks


def _generate_notes_for_chunk(
    segments: List[TranscriptSegment], 
    chunk_index: int, 
    total_chunks: int,
    title: str,
    video_id: str
) -> LectureNotes:
    """Generate notes for a single chunk of a long video.
    
    Includes context about which part of the video this chunk represents.
    """
    chunk_start = segments[0].timestamp_str() if segments else "0:00"
    chunk_end = segments[-1].timestamp_str() if segments else "0:00"
    
    print(f"    → Processing chunk {chunk_index + 1}/{total_chunks} ({chunk_start} - {chunk_end})")
    
    # Modify title to indicate chunk
    chunk_title = f"{title} (Part {chunk_index + 1}/{total_chunks})"
    
    return generate_lecture_notes_from_segments(segments, chunk_title, video_id)


def _synthesize_notes(chunk_notes: List[LectureNotes], original_title: str) -> LectureNotes:
    """Synthesize multiple chunk notes into a single comprehensive LectureNotes object.
    
    Merges all insights, concepts, and details while removing duplicates.
    """
    if not chunk_notes:
        return LectureNotes(
            title=original_title or "Video Notes",
            content_type=ContentType.GENERAL,
            overview="No content available",
            key_insights=[]
        )
    
    if len(chunk_notes) == 1:
        single = chunk_notes[0]
        single.title = original_title  # Restore original title
        return single
    
    # Determine dominant content type
    content_types = [n.content_type for n in chunk_notes]
    dominant_type = max(set(content_types), key=content_types.count)
    
    # Combine overviews into unified summary
    overviews = [n.overview for n in chunk_notes if n.overview]
    combined_overview = " ".join(overviews[:3])  # First 3 chunk overviews
    if len(combined_overview) > 300:
        combined_overview = combined_overview[:297] + "..."
    
    # Merge lists while preserving order (chunks are already ordered)
    def merge_lists(attr_name: str, limit: int = 20) -> list:
        result = []
        seen = set()
        for note in chunk_notes:
            for item in getattr(note, attr_name, []):
                # Create a simple hash for deduplication
                if isinstance(item, dict):
                    key = str(item.get("insight", item.get("concept", item.get("section", str(item)))))
                else:
                    key = str(item)
                if key not in seen:
                    seen.add(key)
                    result.append(item)
        return result[:limit]
    
    return LectureNotes(
        title=original_title,
        content_type=dominant_type,
        overview=combined_overview,
        table_of_contents=merge_lists("table_of_contents", 15),
        main_concepts=merge_lists("main_concepts", 15),
        key_insights=merge_lists("key_insights", 25),
        detailed_notes=merge_lists("detailed_notes", 12),
        notable_quotes=merge_lists("notable_quotes", 12),
        resources_mentioned=merge_lists("resources_mentioned", 15),
        action_items=merge_lists("action_items", 10),
        questions_raised=merge_lists("questions_raised", 8)
    )


def process_long_transcript(
    segments: List[TranscriptSegment], 
    title: str = "",
    video_id: str = ""
) -> LectureNotes:
    """Process very long transcripts (2+ hours) by chunking and synthesizing.
    
    For videos under 2 hours, delegates to the standard processing.
    For longer videos, splits into 30-minute chunks, processes each,
    then synthesizes into a unified result.
    
    Returns:
        Comprehensive LectureNotes covering the entire video
    """
    if not segments:
        return LectureNotes(
            title=title or "Video Notes",
            content_type=ContentType.GENERAL,
            overview="No transcript available",
            key_insights=[]
        )
    
    # Calculate total duration
    total_duration = segments[-1].end_time if segments else 0
    total_minutes = total_duration / 60
    
    # Threshold: videos under 90 minutes use standard processing
    # (200k chars handles ~80 minutes well)
    if total_minutes < 90:
        print(f"  → Video is {total_minutes:.0f} min, using standard processing")
        return generate_lecture_notes_from_segments(segments, title, video_id)
    
    print(f"  → Long video detected ({total_minutes:.0f} min), using chunked processing")
    
    # Split into 30-minute chunks
    chunks = _split_into_chunks(segments, max_minutes=30)
    print(f"  → Split into {len(chunks)} chunks")
    
    # Process each chunk
    chunk_notes = []
    for i, chunk in enumerate(chunks):
        notes = _generate_notes_for_chunk(chunk, i, len(chunks), title, video_id)
        chunk_notes.append(notes)
    
    # Synthesize all chunk notes
    print(f"  → Synthesizing {len(chunk_notes)} chunk notes")
    final_notes = _synthesize_notes(chunk_notes, title)
    
    return final_notes


def summarize_with_gemini(transcript: str) -> dict:
    """Legacy summarization function - now uses generate_lecture_notes internally.
    
    Maintained for backward compatibility with existing API.
    Returns the old format: {title, oneLiner, keyTakeaways, insights}
    """
    notes = generate_lecture_notes(transcript)
    return notes.to_legacy_format()
