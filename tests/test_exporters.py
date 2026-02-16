"""
Tests for the export engine (app/services/exporters/formats.py).

Tests all three export formats: markdown, html, text.
"""

import pytest
from app.services.exporters.formats import (
    export_markdown, export_html, export_text, export_summary,
    _timestamp_to_youtube_link
)


# ============ Fixtures ============

@pytest.fixture
def sample_summary():
    """A realistic summary row from Supabase."""
    return {
        "id": "abc-123",
        "youtube_url": "https://youtu.be/dQw4w9WgXcQ",
        "video_id": "dQw4w9WgXcQ",
        "title": "How React Server Components Work",
        "overview": "A deep dive into React Server Components architecture.",
        "content_type": "tutorial",
        "created_at": "2026-02-08T10:00:00+09:00",
        "notion_url": "https://notion.so/page-123",
        "summary_json": {
            "title": "How React Server Components Work",
            "contentType": "tutorial",
            "overview": "A deep dive into React Server Components architecture.",
            "tableOfContents": [
                {"section": "Introduction", "timestamp": "0:00", "description": "What are RSC?"},
                {"section": "Architecture", "timestamp": "5:30", "description": "How they work internally"},
            ],
            "mainConcepts": [
                {
                    "concept": "Server Components",
                    "definition": "Components that render on the server and send HTML to the client.",
                    "timestamp": "2:15",
                    "examples": ["Page layout", "Data fetching components"]
                }
            ],
            "keyInsights": [
                {
                    "insight": "Server components eliminate client-side JS bundles",
                    "timestamp": "3:45",
                    "context": "Reduces bundle size by up to 70%"
                },
                {
                    "insight": "Client components still handle interactivity",
                    "timestamp": "8:20",
                    "context": "Use 'use client' directive"
                }
            ],
            "detailedNotes": [
                {
                    "section": "Setup & Prerequisites",
                    "timestamp": "1:00",
                    "points": ["Next.js 13+ required", "React 18+ with streaming support"]
                }
            ],
            "notableQuotes": [
                "The best code is the code you never send to the client."
            ],
            "resourcesMentioned": ["Next.js documentation", "React RFC #188"],
            "actionItems": ["Migrate existing pages to server components", "Audit client bundle size"],
            "questionsRaised": ["How does caching work with server components?"]
        }
    }


@pytest.fixture
def minimal_summary():
    """A summary with no summary_json (legacy)."""
    return {
        "id": "legacy-456",
        "youtube_url": "https://youtu.be/old123",
        "video_id": "old123",
        "title": "Old Video",
        "overview": None,
        "content_type": None,
        "created_at": "2025-01-01T00:00:00Z",
        "notion_url": "https://notion.so/old",
        "summary_json": None
    }


@pytest.fixture
def empty_json_summary():
    """A summary with an empty summary_json."""
    return {
        "id": "empty-789",
        "youtube_url": "https://youtu.be/empty",
        "video_id": "empty",
        "title": "Empty Summary",
        "overview": "Just an overview.",
        "content_type": "general",
        "created_at": "2026-01-01T00:00:00Z",
        "summary_json": {}
    }


# ============ Timestamp Link Tests ============

class TestTimestampLinks:
    def test_mm_ss(self):
        assert _timestamp_to_youtube_link("5:30", "abc") == "https://youtu.be/abc?t=330"
    
    def test_hh_mm_ss(self):
        assert _timestamp_to_youtube_link("1:05:30", "abc") == "https://youtu.be/abc?t=3930"
    
    def test_zero(self):
        assert _timestamp_to_youtube_link("0:00", "abc") == "https://youtu.be/abc?t=0"
    
    def test_no_video_id(self):
        assert _timestamp_to_youtube_link("5:30", "") == ""
    
    def test_no_timestamp(self):
        assert _timestamp_to_youtube_link("", "abc") == ""
    
    def test_invalid_timestamp(self):
        assert _timestamp_to_youtube_link("invalid", "abc") == ""


# ============ Markdown Export Tests ============

class TestMarkdownExport:
    def test_has_frontmatter(self, sample_summary):
        md = export_markdown(sample_summary)
        assert md.startswith("---\n")
        assert "title:" in md
        assert "tags: [watchlater, video-notes]" in md
    
    def test_has_title_and_overview(self, sample_summary):
        md = export_markdown(sample_summary)
        assert "# How React Server Components Work" in md
        assert "> A deep dive into" in md
    
    def test_has_timestamp_links(self, sample_summary):
        md = export_markdown(sample_summary)
        assert "youtu.be/dQw4w9WgXcQ?t=" in md
    
    def test_has_key_insights(self, sample_summary):
        md = export_markdown(sample_summary)
        assert "## 💡 Key Insights" in md
        assert "Server components eliminate" in md
    
    def test_has_concepts(self, sample_summary):
        md = export_markdown(sample_summary)
        assert "## 🧠 Main Concepts" in md
        assert "Server Components" in md
    
    def test_has_action_items_as_checkboxes(self, sample_summary):
        md = export_markdown(sample_summary)
        assert "- [ ] Migrate existing pages" in md
    
    def test_has_quotes(self, sample_summary):
        md = export_markdown(sample_summary)
        assert "> The best code is" in md
    
    def test_handles_empty_json(self, empty_json_summary):
        md = export_markdown(empty_json_summary)
        assert "# Empty Summary" in md
    
    def test_handles_no_json(self, minimal_summary):
        md = export_markdown(minimal_summary)
        assert "# Old Video" in md


# ============ HTML Export Tests ============

class TestHtmlExport:
    def test_has_h1(self, sample_summary):
        html = export_html(sample_summary)
        assert "<h1>" in html
        assert "How React Server Components Work" in html
    
    def test_has_blockquote_overview(self, sample_summary):
        html = export_html(sample_summary)
        assert "<blockquote" in html
        assert "A deep dive into" in html
    
    def test_has_insights(self, sample_summary):
        html = export_html(sample_summary)
        assert "Key Insights" in html
        assert "<strong>" in html
    
    def test_has_video_link(self, sample_summary):
        html = export_html(sample_summary)
        assert '<a href="https://youtu.be/dQw4w9WgXcQ">' in html
    
    def test_escapes_html(self):
        summary = {
            "summary_json": {
                "title": "Test <script>alert</script>",
                "overview": "A & B > C",
                "keyInsights": [],
            },
            "youtube_url": "",
        }
        html = export_html(summary)
        assert "<script>" not in html
        assert "&lt;script&gt;" in html
        assert "&amp;" in html
    
    def test_handles_empty_json(self, empty_json_summary):
        html = export_html(empty_json_summary)
        assert "<h1>" in html


# ============ Plain Text Export Tests ============

class TestTextExport:
    def test_has_uppercase_title(self, sample_summary):
        txt = export_text(sample_summary)
        assert "HOW REACT SERVER COMPONENTS WORK" in txt
    
    def test_has_numbered_insights(self, sample_summary):
        txt = export_text(sample_summary)
        assert "1. Server components eliminate" in txt
        assert "2. Client components still" in txt
    
    def test_has_concepts(self, sample_summary):
        txt = export_text(sample_summary)
        assert "MAIN CONCEPTS" in txt
        assert "• Server Components" in txt
    
    def test_has_action_items(self, sample_summary):
        txt = export_text(sample_summary)
        assert "[ ] Migrate existing pages" in txt
    
    def test_has_source_url(self, sample_summary):
        txt = export_text(sample_summary)
        assert "Source: https://youtu.be/" in txt
    
    def test_handles_empty_json(self, empty_json_summary):
        txt = export_text(empty_json_summary)
        assert "EMPTY SUMMARY" in txt


# ============ Export Dispatcher Tests ============

class TestExportDispatcher:
    def test_markdown_format(self, sample_summary):
        content, ct = export_summary(sample_summary, fmt="markdown")
        assert ct == "text/markdown"
        assert "---" in content
    
    def test_md_alias(self, sample_summary):
        content, ct = export_summary(sample_summary, fmt="md")
        assert ct == "text/markdown"
    
    def test_html_format(self, sample_summary):
        content, ct = export_summary(sample_summary, fmt="html")
        assert ct == "text/html"
        assert "<h1>" in content
    
    def test_text_format(self, sample_summary):
        content, ct = export_summary(sample_summary, fmt="text")
        assert ct == "text/plain"
    
    def test_txt_alias(self, sample_summary):
        content, ct = export_summary(sample_summary, fmt="txt")
        assert ct == "text/plain"
    
    def test_invalid_format(self, sample_summary):
        with pytest.raises(ValueError, match="Unsupported export format"):
            export_summary(sample_summary, fmt="pdf")
    
    def test_case_insensitive(self, sample_summary):
        content, ct = export_summary(sample_summary, fmt="MARKDOWN")
        assert ct == "text/markdown"
