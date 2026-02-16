"""
Content extractors for non-YouTube sources.

Normalizes articles, PDFs, and podcasts into TranscriptSegment[] so the
same Gemini pipeline can process any content uniformly.
"""

import re
import logging
import urllib.request
from typing import Optional, List, Tuple

from ..models import SourceType, TranscriptSegment

logger = logging.getLogger(__name__)

# ============ Source Detection ============

# YouTube URL patterns
_YT_PATTERNS = [
    r"(?:https?://)?(?:www\.)?youtube\.com/",
    r"(?:https?://)?youtu\.be/",
    r"(?:https?://)?m\.youtube\.com/",
]

# PDF URL pattern
_PDF_PATTERN = r"\.pdf(\?.*)?$"

# Podcast domain hints
_PODCAST_DOMAINS = [
    "podcasts.apple.com", "open.spotify.com", "overcast.fm",
    "pocketcasts.com", "castro.fm", "anchor.fm",
]


def detect_source_type(url: str) -> SourceType:
    """Auto-detect the content source type from a URL.
    
    Returns:
        SourceType enum value
    """
    url_lower = url.lower().strip()
    
    # YouTube
    for pattern in _YT_PATTERNS:
        if re.match(pattern, url_lower):
            return SourceType.YOUTUBE
    
    # PDF
    if re.search(_PDF_PATTERN, url_lower, re.IGNORECASE):
        return SourceType.PDF
    
    # Podcast platforms
    for domain in _PODCAST_DOMAINS:
        if domain in url_lower:
            return SourceType.PODCAST
    
    # Default to article
    return SourceType.ARTICLE


# ============ Article Extraction ============

def extract_article(url: str) -> Tuple[List[TranscriptSegment], str]:
    """Extract text content from a web article.
    
    Uses trafilatura for clean main-content extraction, falling back
    to basic HTML parsing if trafilatura is unavailable.
    
    Returns:
        (segments, title)
    """
    logger.info(f"Extracting article from: {url}")
    
    # Fetch the page
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        raise ValueError(f"Failed to fetch article: {e}")
    
    # Try trafilatura first (best quality)
    title = "Untitled Article"
    text = None
    
    try:
        import trafilatura
        result = trafilatura.extract(html, include_comments=False, include_tables=True)
        if result:
            text = result
        # Try to get title from metadata
        metadata = trafilatura.extract_metadata(html)
        if metadata and metadata.title:
            title = metadata.title
    except ImportError:
        logger.info("trafilatura not available, falling back to basic extraction")
    except Exception as e:
        logger.warning(f"trafilatura extraction failed: {e}")
    
    # Fallback: basic HTML title + body text extraction
    if not text:
        text, title = _basic_html_extract(html)
    
    if not text or len(text.strip()) < 50:
        raise ValueError("Could not extract meaningful content from this article. The page may be behind a paywall or require JavaScript.")
    
    # Split into paragraph-based segments
    segments = _text_to_segments(text)
    
    logger.info(f"Extracted article: '{title}' ({len(text)} chars, {len(segments)} segments)")
    return segments, title


def _basic_html_extract(html: str) -> Tuple[str, str]:
    """Fallback HTML extraction without external libraries."""
    # Extract title
    title = "Untitled Article"
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if title_match:
        title = re.sub(r"<[^>]+>", "", title_match.group(1)).strip()
    
    # Strip scripts, styles, nav, header, footer
    for tag in ["script", "style", "nav", "header", "footer", "aside", "noscript"]:
        html = re.sub(rf"<{tag}[^>]*>.*?</{tag}>", "", html, flags=re.IGNORECASE | re.DOTALL)
    
    # Extract text from paragraph tags
    paragraphs = re.findall(r"<p[^>]*>(.*?)</p>", html, re.IGNORECASE | re.DOTALL)
    
    if paragraphs:
        # Strip remaining HTML tags
        text = "\n\n".join(
            re.sub(r"<[^>]+>", "", p).strip() 
            for p in paragraphs 
            if len(re.sub(r"<[^>]+>", "", p).strip()) > 20
        )
    else:
        # Last resort: strip all tags
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()
    
    return text, title


def _text_to_segments(text: str, chars_per_segment: int = 2000) -> List[TranscriptSegment]:
    """Split text into segments based on paragraphs, with synthetic timestamps.
    
    Groups paragraphs into segments of ~2000 characters each.
    Uses paragraph index as synthetic "timestamp" for section navigation.
    """
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    
    segments = []
    current_text = []
    current_chars = 0
    segment_idx = 0
    
    for para in paragraphs:
        current_text.append(para)
        current_chars += len(para)
        
        if current_chars >= chars_per_segment:
            segments.append(TranscriptSegment(
                text="\n".join(current_text),
                start_time=float(segment_idx * 60),  # Synthetic: 1 min per segment
                end_time=float((segment_idx + 1) * 60),
            ))
            current_text = []
            current_chars = 0
            segment_idx += 1
    
    # Remaining text
    if current_text:
        segments.append(TranscriptSegment(
            text="\n".join(current_text),
            start_time=float(segment_idx * 60),
            end_time=float((segment_idx + 1) * 60),
        ))
    
    return segments if segments else [TranscriptSegment(text=text, start_time=0, end_time=0)]


# ============ PDF Extraction ============

def extract_pdf(url: Optional[str] = None, content: Optional[str] = None) -> Tuple[List[TranscriptSegment], str]:
    """Extract text from a PDF URL or pre-extracted content.
    
    If `content` is provided, uses it directly (client already extracted text).
    Otherwise downloads the PDF and extracts text page by page.
    
    Returns:
        (segments, title)
    """
    if content:
        # Client already extracted the text
        logger.info("Using client-provided PDF text")
        segments = _text_to_segments(content)
        title = _infer_title_from_text(content)
        return segments, title
    
    if not url:
        raise ValueError("Either url or content must be provided for PDF extraction")
    
    logger.info(f"Downloading PDF from: {url}")
    
    # Download PDF
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
        })
        with urllib.request.urlopen(req, timeout=30) as resp:
            pdf_bytes = resp.read()
    except Exception as e:
        raise ValueError(f"Failed to download PDF: {e}")
    
    # Size limit: 50MB
    if len(pdf_bytes) > 50 * 1024 * 1024:
        raise ValueError("PDF is too large (max 50MB)")
    
    # Try pymupdf
    try:
        import fitz  # pymupdf
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        
        title = doc.metadata.get("title", "") if doc.metadata else ""
        
        segments = []
        for page_num, page in enumerate(doc):
            page_text = page.get_text().strip()
            if page_text and len(page_text) > 20:
                segments.append(TranscriptSegment(
                    text=page_text,
                    start_time=float(page_num * 60),  # 1 min per page (synthetic)
                    end_time=float((page_num + 1) * 60),
                ))
        
        doc.close()
        
        if not title:
            all_text = " ".join(s.text for s in segments)
            title = _infer_title_from_text(all_text)
        
        logger.info(f"Extracted PDF: '{title}' ({len(segments)} pages)")
        return segments, title
        
    except ImportError:
        logger.warning("pymupdf not available, trying pdfminer")
    
    # Fallback: pdfminer.six
    try:
        from pdfminer.high_level import extract_text as pdfminer_extract
        import io
        
        text = pdfminer_extract(io.BytesIO(pdf_bytes))
        if not text or len(text.strip()) < 50:
            raise ValueError("PDF appears to be image-based or empty. Text extraction is not possible.")
        
        title = _infer_title_from_text(text)
        segments = _text_to_segments(text)
        
        logger.info(f"Extracted PDF (pdfminer): '{title}' ({len(segments)} segments)")
        return segments, title
        
    except ImportError:
        raise ValueError("No PDF extraction library available. Install pymupdf or pdfminer.six.")


def _infer_title_from_text(text: str) -> str:
    """Guess a title from the first meaningful line of text."""
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    for line in lines[:5]:
        # Skip very short lines (page numbers, headers)
        if 10 < len(line) < 200:
            return line
    return "Untitled Document"


# ============ Dispatcher ============

def extract_content(
    url: str,
    source_type: Optional[SourceType] = None,
    content: Optional[str] = None,
) -> Tuple[List[TranscriptSegment], str, SourceType]:
    """Extract content from any supported source.
    
    Args:
        url: Content URL
        source_type: Override auto-detection
        content: Pre-extracted text (for PDFs from client)
    
    Returns:
        (segments, title, detected_source_type)
    
    Raises:
        ValueError: If source type is unsupported or extraction fails
    """
    if source_type is None:
        source_type = detect_source_type(url)
    
    logger.info(f"Extracting content: type={source_type.value}, url={url[:80]}")
    
    if source_type == SourceType.YOUTUBE:
        raise ValueError("Use the /summarize endpoint for YouTube videos")
    
    if source_type == SourceType.ARTICLE:
        segments, title = extract_article(url)
    elif source_type == SourceType.PDF:
        segments, title = extract_pdf(url=url, content=content)
    elif source_type == SourceType.PODCAST:
        raise ValueError("Podcast extraction is coming soon. For now, paste the transcript text directly.")
    else:
        raise ValueError(f"Unsupported source type: {source_type}")
    
    return segments, title, source_type
