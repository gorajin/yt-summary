"""
Services package initialization
"""

from .youtube import (
    extract_video_id,
    get_transcript,
    get_transcript_with_timestamps,
    get_video_title,
)

from .gemini import (
    call_gemini_api,
    detect_content_type,
    generate_lecture_notes,
    generate_lecture_notes_from_segments,
    process_long_transcript,
    summarize_with_gemini,
)

from .notion import (
    create_notion_page,
    create_lecture_notes_page,
)
