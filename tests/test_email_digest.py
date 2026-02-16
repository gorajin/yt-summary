"""
Tests for the email digest service (app/services/email_digest.py).

Tests HTML generation, user filtering, and the digest pipeline.
"""

import pytest
from app.services.email_digest import (
    build_digest_html, _esc, get_users_for_digest, get_todays_summaries
)


# ============ Fixtures ============

@pytest.fixture
def sample_summaries():
    """Two realistic summaries for digest testing."""
    return [
        {
            "id": "sum-1",
            "youtube_url": "https://youtu.be/abc123",
            "video_id": "abc123",
            "title": "How React Server Components Work",
            "overview": "A deep dive into RSC architecture.",
            "content_type": "tutorial",
            "created_at": "2026-02-08T10:00:00Z",
            "summary_json": {
                "title": "How React Server Components Work",
                "contentType": "tutorial",
                "overview": "A deep dive into RSC architecture.",
                "keyInsights": [
                    {"insight": "Server components reduce bundle size by 70%", "timestamp": "3:45", "context": ""},
                    {"insight": "Client components handle interactivity", "timestamp": "8:20", "context": ""},
                ],
                "mainConcepts": [],
                "detailedNotes": [],
                "notableQuotes": [],
                "resourcesMentioned": [],
                "actionItems": [],
                "questionsRaised": [],
            }
        },
        {
            "id": "sum-2",
            "youtube_url": "https://youtu.be/def456",
            "video_id": "def456",
            "title": "The Psychology of Productivity",
            "overview": "Research-backed productivity techniques.",
            "content_type": "lecture",
            "created_at": "2026-02-08T14:00:00Z",
            "summary_json": {
                "title": "The Psychology of Productivity",
                "contentType": "lecture",
                "overview": "Research-backed productivity techniques.",
                "keyInsights": [
                    {"insight": "The Zeigarnik effect drives task completion", "timestamp": "5:00", "context": ""},
                    {"insight": "Deep work requires 90-minute blocks", "timestamp": "12:30", "context": ""},
                ],
                "mainConcepts": [],
                "detailedNotes": [],
                "notableQuotes": [],
                "resourcesMentioned": [],
                "actionItems": [],
                "questionsRaised": [],
            }
        }
    ]


@pytest.fixture
def single_summary():
    """A single summary for edge case testing."""
    return [
        {
            "id": "sum-solo",
            "youtube_url": "https://youtu.be/solo",
            "video_id": "solo",
            "title": "Quick Tip",
            "overview": "A short tip.",
            "content_type": "general",
            "created_at": "2026-02-08T10:00:00Z",
            "summary_json": {
                "title": "Quick Tip",
                "contentType": "general",
                "overview": "A short tip.",
                "keyInsights": [
                    {"insight": "Only one insight here", "timestamp": "1:00", "context": ""},
                ],
            }
        }
    ]


# ============ HTML Escaping ============

class TestEscaping:
    def test_escapes_ampersand(self):
        assert _esc("A & B") == "A &amp; B"
    
    def test_escapes_angle_brackets(self):
        assert _esc("<script>") == "&lt;script&gt;"
    
    def test_plain_text_unchanged(self):
        assert _esc("Hello World") == "Hello World"


# ============ Digest HTML Tests ============

class TestDigestHtml:
    def test_has_header(self, sample_summaries):
        html = build_digest_html(sample_summaries, "user@example.com")
        assert "Daily Learning Digest" in html
    
    def test_has_video_count(self, sample_summaries):
        html = build_digest_html(sample_summaries, "user@example.com")
        assert "2 videos" in html
    
    def test_singular_video(self, single_summary):
        html = build_digest_html(single_summary, "user@example.com")
        assert "1 video" in html
    
    def test_has_video_titles(self, sample_summaries):
        html = build_digest_html(sample_summaries, "user@example.com")
        assert "React Server Components" in html
        assert "Psychology of Productivity" in html
    
    def test_has_overviews(self, sample_summaries):
        html = build_digest_html(sample_summaries, "user@example.com")
        assert "RSC architecture" in html
        assert "productivity techniques" in html
    
    def test_has_insights(self, sample_summaries):
        html = build_digest_html(sample_summaries, "user@example.com")
        assert "bundle size" in html
    
    def test_has_video_links(self, sample_summaries):
        html = build_digest_html(sample_summaries, "user@example.com")
        assert "youtu.be/abc123" in html
        assert "youtu.be/def456" in html
    
    def test_has_cross_video_section(self, sample_summaries):
        html = build_digest_html(sample_summaries, "user@example.com")
        assert "Across Your Videos Today" in html
    
    def test_no_cross_video_for_single(self, single_summary):
        html = build_digest_html(single_summary, "user@example.com")
        assert "Across Your Videos Today" not in html
    
    def test_has_content_type_badge(self, sample_summaries):
        html = build_digest_html(sample_summaries, "user@example.com")
        assert "TUTORIAL" in html
        assert "LECTURE" in html
    
    def test_escapes_html_in_titles(self):
        summaries = [{
            "id": "xss",
            "youtube_url": "https://youtu.be/x",
            "video_id": "x",
            "title": "<script>alert('xss')</script>",
            "overview": "Safe & sound",
            "content_type": "general",
            "created_at": "2026-01-01T00:00:00Z",
            "summary_json": {
                "title": "<script>alert('xss')</script>",
                "contentType": "general",
                "overview": "Safe & sound",
                "keyInsights": [],
            }
        }]
        html = build_digest_html(summaries, "test@test.com")
        assert "<script>" not in html
        assert "&lt;script&gt;" in html
    
    def test_valid_html_structure(self, sample_summaries):
        html = build_digest_html(sample_summaries, "user@example.com")
        assert "<!DOCTYPE html>" in html
        assert "</html>" in html
        assert "<body" in html

    def test_empty_summaries(self):
        html = build_digest_html([], "user@example.com")
        assert "Daily Learning Digest" in html
        assert "0 videos" in html


# ============ User Filtering Tests ============

class TestUserFiltering:
    """Tests for get_users_for_digest with a mock Supabase client."""
    
    def _make_mock_client(self, users):
        """Create a mock Supabase client that returns given users."""
        class MockResult:
            def __init__(self, data):
                self.data = data
        
        class MockQuery:
            def __init__(self, data):
                self.data = data
            def select(self, *args):
                return self
            def eq(self, *args):
                return self
            def execute(self):
                return MockResult(self.data)
        
        class MockClient:
            def __init__(self, data):
                self.data = data
            def table(self, name):
                return MockQuery(self.data)
        
        return MockClient(users)
    
    def test_matches_users_at_correct_hour(self):
        users = [
            {"id": "u1", "email": "a@test.com", "email_digest_time": "20:00", "timezone": "UTC"},
            {"id": "u2", "email": "b@test.com", "email_digest_time": "08:00", "timezone": "UTC"},
        ]
        client = self._make_mock_client(users)
        matched = get_users_for_digest(client, current_hour=20)
        assert len(matched) == 1
        assert matched[0]["id"] == "u1"
    
    def test_no_match_at_wrong_hour(self):
        users = [
            {"id": "u1", "email": "a@test.com", "email_digest_time": "20:00", "timezone": "UTC"},
        ]
        client = self._make_mock_client(users)
        matched = get_users_for_digest(client, current_hour=15)
        assert len(matched) == 0
    
    def test_handles_empty_users(self):
        client = self._make_mock_client([])
        matched = get_users_for_digest(client, current_hour=20)
        assert len(matched) == 0
    
    def test_handles_missing_time(self):
        users = [{"id": "u1", "email": "a@test.com", "timezone": "UTC"}]
        client = self._make_mock_client(users)
        # Default time is 20:00
        matched = get_users_for_digest(client, current_hour=20)
        assert len(matched) == 1
    
    def test_handles_invalid_time(self):
        users = [{"id": "u1", "email": "a@test.com", "email_digest_time": "invalid", "timezone": "UTC"}]
        client = self._make_mock_client(users)
        # Should fall back to hour 20
        matched = get_users_for_digest(client, current_hour=20)
        assert len(matched) == 1
