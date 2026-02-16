"""
Tests for content extractors (app/services/extractors.py).

Tests source detection, article extraction, PDF extraction, and the dispatcher.
"""

import pytest
from app.models import SourceType, TranscriptSegment
from app.services.extractors import (
    detect_source_type, _text_to_segments, _basic_html_extract,
    _infer_title_from_text, extract_content,
)


# ============ Source Detection ============

class TestDetectSourceType:
    """Tests for auto-detecting content source from URL."""
    
    def test_youtube_standard(self):
        assert detect_source_type("https://www.youtube.com/watch?v=abc123") == SourceType.YOUTUBE
    
    def test_youtube_short(self):
        assert detect_source_type("https://youtu.be/abc123") == SourceType.YOUTUBE
    
    def test_youtube_mobile(self):
        assert detect_source_type("https://m.youtube.com/watch?v=abc123") == SourceType.YOUTUBE
    
    def test_youtube_embed(self):
        assert detect_source_type("https://www.youtube.com/embed/abc123") == SourceType.YOUTUBE
    
    def test_pdf_url(self):
        assert detect_source_type("https://example.com/paper.pdf") == SourceType.PDF
    
    def test_pdf_with_params(self):
        assert detect_source_type("https://arxiv.org/pdf/2301.12345.pdf?download=true") == SourceType.PDF
    
    def test_article_blog(self):
        assert detect_source_type("https://blog.example.com/cool-post") == SourceType.ARTICLE
    
    def test_article_medium(self):
        assert detect_source_type("https://medium.com/@user/article-title-123abc") == SourceType.ARTICLE
    
    def test_article_substack(self):
        assert detect_source_type("https://newsletter.substack.com/p/some-post") == SourceType.ARTICLE
    
    def test_podcast_apple(self):
        assert detect_source_type("https://podcasts.apple.com/us/podcast/some-show/id123") == SourceType.PODCAST
    
    def test_podcast_spotify(self):
        assert detect_source_type("https://open.spotify.com/episode/abc123") == SourceType.PODCAST
    
    def test_podcast_overcast(self):
        assert detect_source_type("https://overcast.fm/+abc123") == SourceType.PODCAST
    
    def test_unknown_defaults_to_article(self):
        assert detect_source_type("https://random-site.com/page") == SourceType.ARTICLE
    
    def test_case_insensitive(self):
        assert detect_source_type("HTTPS://WWW.YOUTUBE.COM/watch?v=ABC") == SourceType.YOUTUBE


# ============ Text Segmentation ============

class TestTextToSegments:
    def test_short_text_single_segment(self):
        text = "Short paragraph."
        segments = _text_to_segments(text)
        assert len(segments) == 1
        assert segments[0].text == "Short paragraph."
    
    def test_long_text_multiple_segments(self):
        # Create text > 2000 chars
        text = "\n".join([f"Paragraph {i}. " + "x" * 200 for i in range(20)])
        segments = _text_to_segments(text)
        assert len(segments) > 1
    
    def test_synthetic_timestamps(self):
        text = "\n".join(["A" * 2500, "B" * 2500])
        segments = _text_to_segments(text)
        assert segments[0].start_time == 0.0
        assert segments[0].end_time == 60.0
        if len(segments) > 1:
            assert segments[1].start_time == 60.0
    
    def test_empty_lines_ignored(self):
        text = "Line 1\n\n\n\nLine 2"
        segments = _text_to_segments(text)
        assert "Line 1" in segments[0].text
        assert "Line 2" in segments[0].text
    
    def test_returns_segment_type(self):
        segments = _text_to_segments("Hello world")
        assert isinstance(segments[0], TranscriptSegment)


# ============ Basic HTML Extraction ============

class TestBasicHtmlExtract:
    def test_extracts_title(self):
        html = "<html><head><title>My Article</title></head><body><p>Content here</p></body></html>"
        text, title = _basic_html_extract(html)
        assert title == "My Article"
    
    def test_extracts_paragraphs(self):
        html = "<body><p>First paragraph with enough text to pass the filter.</p><p>Second paragraph with enough text as well here.</p></body>"
        text, _ = _basic_html_extract(html)
        assert "First paragraph" in text
        assert "Second paragraph" in text
    
    def test_strips_scripts(self):
        html = "<body><script>alert('xss')</script><p>Real content that should be extracted here.</p></body>"
        text, _ = _basic_html_extract(html)
        assert "alert" not in text
        assert "Real content" in text
    
    def test_strips_nav_footer(self):
        html = "<body><nav>Navigation menu</nav><p>Article content that should be extracted today.</p><footer>Copyright</footer></body>"
        text, _ = _basic_html_extract(html)
        assert "Navigation menu" not in text
        assert "Article content" in text


# ============ Title Inference ============

class TestInferTitle:
    def test_first_meaningful_line(self):
        text = "How to Build a Great Product\n\nThis guide covers..."
        assert _infer_title_from_text(text) == "How to Build a Great Product"
    
    def test_skips_short_lines(self):
        text = "Page 1\n\nReal Title of the Document\n\nContent here..."
        assert _infer_title_from_text(text) == "Real Title of the Document"
    
    def test_fallback_for_empty(self):
        assert _infer_title_from_text("") == "Untitled Document"
    
    def test_fallback_for_only_short_lines(self):
        text = "pg 1\npg 2"
        assert _infer_title_from_text(text) == "Untitled Document"


# ============ Dispatcher ============

class TestExtractContent:
    def test_youtube_rejected(self):
        with pytest.raises(ValueError, match="Use the /summarize endpoint"):
            extract_content("https://www.youtube.com/watch?v=abc123")
    
    def test_podcast_not_yet_supported(self):
        with pytest.raises(ValueError, match="coming soon"):
            extract_content("https://podcasts.apple.com/us/podcast/show/id123")
    
    def test_explicit_source_type_override(self):
        """Verify that explicit source_type overrides auto-detection."""
        with pytest.raises(ValueError, match="coming soon"):
            extract_content("https://example.com/page", source_type=SourceType.PODCAST)
