"""
Services package initialization.

Re-exports public APIs from all service modules for convenience.
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

from .jobs import (
    create_job,
    get_job,
    update_job,
    cleanup_old_jobs,
    Job,
    JobStatus,
)

from .extractors import (
    extract_content,
    detect_source_type,
)

from .apple_receipt import (
    verify_signed_transaction,
    VerifiedTransaction,
    ReceiptValidationError,
)

from .exporters.formats import (
    export_summary,
)

from .knowledge_map import (
    build_knowledge_map,
    get_knowledge_map,
)
